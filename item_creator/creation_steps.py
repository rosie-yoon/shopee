# item_creator/creation_steps.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import List, Dict, Optional, Any, Tuple
import io
import csv
import re
from io import BytesIO
from collections import defaultdict

import gspread
from gspread.cell import Cell
from gspread.utils import rowcol_to_a1
from gspread.exceptions import WorksheetNotFound
# [수정] pandas를 파일 상단에서 명시적으로 임포트하여 안정성 확보
import pandas as pd

# [최종 수정] 모든 공용 유틸리티는 이제 main_controller.py가 로드한
# utils_common (최상위 모듈 또는 item_creator.utils_common)에서
# 직접 가져오거나, item_uploader 대신 item_creator의 utils_common을 사용하도록 변경합니다.
from utils_common import (
    header_key, top_of_category, get_tem_sheet_name,
    with_retry, safe_worksheet, authorize_gspread, extract_sheet_id,
    get_env
)
from .utils_common import get_env, join_url, forward_fill_by_group


# === automation_steps.py 공통 헬퍼 함수 이식 ===

# ========================================
# [NEW] 카테고리 정규화 및 3단계 매칭 함수
# ========================================

def normalize_category_path(category: str) -> str:
    """
    카테고리 경로 정규화 (계층 구조 보존)

    Args:
        category: 원본 카테고리 문자열

    Returns:
        정규화된 카테고리 경로

    Examples:
        >>> normalize_category_path("100832 - Beauty / Makeup / Lips")
        "beauty/makeup/lips"
        >>> normalize_category_path("Beauty - Makeup")
        "beauty/makeup"
    """
    if not category or not isinstance(category, str):
        return ""

    # 1. Shopee 숫자 코드 제거 (예: "100832 - " 삭제)
    cleaned = re.sub(r'^\s*\d+\s*-\s*', '', category.strip())

    # 2. 구분자 통일
    cleaned = cleaned.replace('\\', '/')  # 백슬래시 → 슬래시
    cleaned = re.sub(r'\s+-\s+', '/', cleaned)  # " - " → "/"
    cleaned = re.sub(r'\s*/\s*', '/', cleaned)  # " / " → "/"

    # 3. 세그먼트별 공백 제거 및 소문자 변환
    segments = [seg.strip().lower() for seg in cleaned.split('/') if seg.strip()]

    # 4. 최종 경로 생성
    result = '/'.join(segments)

    # 5. 중복 슬래시 제거
    while '//' in result:
        result = result.replace('//', '/')

    return result.strip('/')


def find_best_template_match(category: str, template_dict: Dict[str, List[str]]) -> Tuple[List[str], str]:
    """
    3단계 우선순위 매칭으로 최적 템플릿 검색

    Args:
        category: 원본 카테고리 문자열
        template_dict: 템플릿 사전 {정규화된_키: 헤더_리스트}

    Returns:
        (템플릿_헤더_리스트, 매칭된_키)
    """
    normalized = normalize_category_path(category)
    if not normalized:
        return [], ""

    parts = normalized.split('/')

    # 깊은 경로부터 최상위까지 순차 검색
    # 예: beauty/makeup/lips → beauty/makeup → beauty
    for depth in range(len(parts), 0, -1):
        search_path = '/'.join(parts[:depth])

        if search_path in template_dict:
            print(f"   [TEMPLATE_MATCH] Found at depth {depth}: '{search_path}' for '{category}'")
            return template_dict[search_path], search_path

    return [], ""


def _find_col_index(keys: List[str], name: str, extra_alias: List[str] = []) -> int:

    """
    헤더 키 목록(keys=header_key 적용된 리스트)에서 name 또는 alias를 찾음
    - 1순위: name(타겟)의 정확 매칭
    - 2순위: name(타겟)의 부분 일치 (예: productname ⊂ productnameeng)
    - 3순위: alias의 정확 매칭
    - 4순위: alias의 부분 일치
    """
    tgt = header_key(name)
    alias_keys = [header_key(a) for a in extra_alias if a]

    # 1) 정확 매칭 - 타겟
    if tgt:
        for i, k in enumerate(keys):
            if k == tgt:
                return i

    # 2) 부분 일치 - 타겟 (productname ⊂ productnameeng 같은 케이스용)
    if tgt:
        for i, k in enumerate(keys):
            if tgt in k:
                return i

    # 3) 정확 매칭 - alias
    for i, k in enumerate(keys):
        if k in alias_keys and (not tgt or k != tgt):
            return i

    # 4) 부분 일치 - alias
    for i, k in enumerate(keys):
        if any(a and a in k for a in alias_keys):
            return i

    return -1


# _pick_index_by_candidates (Weight 매핑을 위해 이식)
def _pick_index_by_candidates(header_row: List[str], candidates: List[str]) -> int:
    """헤더 행에서 후보명(정규화)으로 가장 그럴듯한 인덱스 찾기 (정확 > 부분 일치)"""
    keys = [header_key(x) for x in header_row]
    # 정확 일치
    for cand in candidates:
        ck = header_key(cand)
        for i, k in enumerate(keys):
            if k == ck:
                return i
    # 부분 일치
    for cand in candidates:
        ck = header_key(cand)
        if not ck:
            continue
        for i, k in enumerate(keys):
            if ck in k:
                return i
    return -1


def _load_template_dict(ref: gspread.Spreadsheet) -> Dict[str, List[str]]:
    """템플릿 사전을 정규화된 키로 로딩 (개선된 버전)"""
    ref_sheet = get_env("TEMPLATE_DICT_SHEET_NAME", "TemplateDict")
    ws = safe_worksheet(ref, ref_sheet)
    vals = with_retry(lambda: ws.get_all_values()) or []

    out: Dict[str, List[str]] = {}

    for r in vals[1:]:
        if not r or not (r[0] or "").strip():
            continue

        original_category = r[0].strip()
        headers = [str(x or "").strip() for x in r[1:]]

        # 정규화된 키로 저장 (핵심 개선!)
        normalized_key = normalize_category_path(original_category)
        if normalized_key:
            out[normalized_key] = headers

            # 디버깅을 위한 로그 (처음 5개만 출력)
            if len(out) <= 5:
                print(f"   [TEMPLATE_LOAD] '{original_category}' → '{normalized_key}'")

    print(f"   [TEMPLATE_LOAD] Total templates loaded: {len(out)}")
    print(f"\n📋 [TEMPLATE_LOAD] 로딩 완료:")
    print(f"   총 템플릿 개수: {len(out)}")
    print(f"   샘플 키들 (처음 10개):")
    for i, key in enumerate(list(out.keys())[:10], 1):
        print(f"     {i}. '{key}'")
    return out


# C1: TEM_OUTPUT 시트 준비/초기화
def run_step_C1(sh: gspread.Spreadsheet, ref: Optional[gspread.Spreadsheet]):
    print("\n[ Create ] Step C1: Prepare TEM_OUTPUT sheet ...")
    tem_name = get_tem_sheet_name()
    try:
        tem_ws = safe_worksheet(sh, tem_name)
        with_retry(lambda: tem_ws.clear())
    except Exception:
        tem_ws = with_retry(lambda: sh.add_worksheet(title=tem_name, rows=2000, cols=200))
    with_retry(lambda: tem_ws.update(values=[[""]], range_name="A1"))
    print("C1 Done.")


# Collection 헤더 인덱스 수집
def _collect_indices(header_row: List[str]) -> Dict[str, int]:
    keys = [header_key(x) for x in header_row]
    key_to_idx = {k: i for i, k in enumerate(keys)}

    return {
        "create": key_to_idx.get("create", 0),
        "variation": key_to_idx.get("parentsku", 1),  # 실제 사용하는 컬럼 이름에 맞게
        "sku": key_to_idx.get("sku", 2),
        "brand": key_to_idx.get("brand", 3),
        "item_eng": key_to_idx.get("itemeng", 4),
        "option_eng": key_to_idx.get("optioneng", 5),
        "prod_name": key_to_idx.get("productname", 6),
        "desc_draft": key_to_idx.get("descriptiondraft", 7),
        "desc": key_to_idx.get("description", 8),
        "category": key_to_idx.get("category", 9),
        "detail_idx": key_to_idx.get("detailsindex", 10),
    }


def _is_true(v: str) -> bool:
    return str(v or "").strip().lower() in ("true", "t", "1", "y", "yes", "✔", "✅")


# C2: Collection → TEM_OUTPUT 생성 (매핑 + Variation 그룹 공란 보정)
def run_step_C2(sh: gspread.Spreadsheet, ref: gspread.Spreadsheet):
    print("\n[ Create ] Step C2: Build TEM from Collection ...")
    tem_name = get_tem_sheet_name()
    template_dict = _load_template_dict(ref)

    coll_ws = safe_worksheet(sh, "Collection")
    coll_vals = with_retry(lambda: coll_ws.get_all_values()) or []
    if not coll_vals or len(coll_vals) < 2:
        print("[C2] Collection 비어 있음.")
        return

    colmap = _collect_indices(coll_vals[0])
    create_i = colmap["create"] if colmap["create"] >= 0 else 0
    variation_i = colmap["variation"] if colmap["variation"] >= 0 else 1
    sku_i = colmap["sku"] if colmap["sku"] >= 0 else 2
    brand_i = colmap["brand"] if colmap["brand"] >= 0 else 3
    option_i = colmap["option_eng"] if colmap["option_eng"] >= 0 else 5
    pname_i = colmap["prod_name"] if colmap["prod_name"] >= 0 else 7
    desc_i = colmap["desc"] if colmap["desc"] >= 0 else 9
    category_i = colmap["category"] if colmap["category"] >= 0 else 10
    dcount_i = colmap["detail_idx"] if colmap["detail_idx"] >= 0 else 11

    fill_cols = [variation_i, brand_i, pname_i, desc_i, category_i, dcount_i]

    def _reset_when(row: List[str]) -> bool:
        return not any(str(x or "").strip() for x in row)

    ff_vals = forward_fill_by_group(
        [list(r) for r in coll_vals],
        group_idx=variation_i,
        fill_col_indices=fill_cols,
        reset_when=_reset_when
    )

    buckets: Dict[str, Dict[str, List]] = {}
    failures: List[List[str]] = []

    def set_if_exists(headers: List[str], row: List[str], name: str, value: str):
        idx = _find_col_index([header_key(h) for h in headers], name)
        if idx >= 0:
            row[idx] = value

    for r in range(1, len(ff_vals)):
        row = ff_vals[r]
        if not _is_true(row[create_i] if create_i < len(row) else ""):
            continue

        variation = (row[variation_i] if variation_i < len(row) else "").strip()
        sku = (row[sku_i] if sku_i < len(row) else "").strip()
        brand = (row[brand_i] if brand_i < len(row) else "").strip()
        opt1 = (row[option_i] if option_i < len(row) else "").strip()
        pname = (row[pname_i] if pname_i < len(row) else "").strip()
        desc = (row[desc_i] if desc_i < len(row) else "").strip()
        category = (row[category_i] if category_i < len(row) else "").strip()

        if not category:
            pid = variation or sku or f"ROW{r + 1}"
            failures.append([pid, "", pname, "CATEGORY_MISSING", f"row={r + 1}"])
            continue

        # ========================================
        # 핵심 수정: 3단계 우선순위 매칭 적용
        # ========================================
        pid = variation or sku or f"ROW{r + 1}"

        headers, matched_key = find_best_template_match(category, template_dict)

        headers, matched_key = find_best_template_match(category, template_dict)

        if not headers:
            # ========================================
            # 진단: 매칭 실패 원인 상세 분석
            # ========================================
            pid = variation or sku or f"ROW{r + 1}"
            normalized_cat = normalize_category_path(category)
            parts = normalized_cat.split('/') if normalized_cat else []

            print(f"\n🚨 [MATCHING_FAILED] Row {r + 1} - PID: {pid}")
            print(f"   원본 카테고리: '{category}'")
            print(f"   정규화 결과: '{normalized_cat}'")
            print(f"   분할 결과: {parts}")

            print(f"   시도한 경로들:")
            for depth in range(len(parts), 0, -1):
                search_path = '/'.join(parts[:depth])
                exists = "✅ 존재" if search_path in template_dict else "❌ 없음"
                print(f"     - depth {depth}: '{search_path}' {exists}")

            # TemplateDict 샘플 출력 (힌트 제공)
            print(f"   TemplateDict 샘플 키 (처음 10개):")
            for i, key in enumerate(list(template_dict.keys())[:10], 1):
                print(f"     {i}. '{key}'")

            # 🚫 기본 템플릿 사용 금지 - 해당 상품 건너뛰기
            failures.append([pid, category, pname, "TEMPLATE_NOT_FOUND",
                             f"normalized={normalized_cat}"])
            print(f"   ❌ 상품 건너뛰기: 템플릿 매칭 실패")
            continue  # 🔥 핵심: 기본 템플릿 대신 건너뛰기

        tem_row = [""] * len(headers)
        set_if_exists(headers, tem_row, "category", category)
        set_if_exists(headers, tem_row, "product name", pname)
        set_if_exists(headers, tem_row, "product description", desc)
        set_if_exists(headers, tem_row, "variation integration", variation)
        set_if_exists(headers, tem_row, "variation name1", "Options")
        set_if_exists(headers, tem_row, "option for variation 1", opt1)
        set_if_exists(headers, tem_row, "sku", sku)
        set_if_exists(headers, tem_row, "brand", brand)

        pid = variation or sku or f"ROW{r + 1}"
        # 버킷 키는 매칭된 정규화 키 사용
        b = buckets.setdefault(matched_key, {"headers": headers, "pids": [], "rows": []})
        b["pids"].append([pid])
        b["rows"].append(tem_row)

    out_matrix: List[List[str]] = []
    for _, pack in buckets.items():
        out_matrix.append(["PID"] + pack["headers"])
        out_matrix.extend([pid_row + data_row for pid_row, data_row in zip(pack["pids"], pack["rows"])])

    if out_matrix:
        tem_ws = safe_worksheet(sh, tem_name)
        with_retry(lambda: tem_ws.clear())
        max_cols = max(len(r) for r in out_matrix)
        end_a1 = rowcol_to_a1(len(out_matrix), max_cols)
        with_retry(lambda: tem_ws.resize(rows=len(out_matrix) + 10, cols=max_cols + 10))
        with_retry(lambda: tem_ws.update(values=out_matrix, range_name=f"A1:{end_a1}"))

    if failures:
        # Failures 기록 로직... (생략)
        pass

    print(f"C2 Done. Buckets: {len(buckets)}")


# C3: FDA Registration No. 채우기 (STEP 3 이식)
def run_step_C3_fda(sh: gspread.Spreadsheet, ref: gspread.Spreadsheet, overwrite: bool = False):
    """
    (STEP 3 이식) Reference 시트의 목록을 기준으로, TEM_OUTPUT 행에 고정 FDA 코드를 채웁니다.
    """
    print("\n[ Create ] Step C3: Fill FDA Code (STEP 3)...")

    tem_name = get_tem_sheet_name()
    fda_sheet_name = get_env("FDA_CATEGORIES_SHEET_NAME", "TH Cos")
    fda_header = get_env("FDA_HEADER_NAME", "FDA Registration No.")
    FDA_CODE = "10-1-9999999"

    try:
        # Reference 시트에서 FDA 대상 카테고리 목록 읽기 (정규화 적용)
        fda_ws = safe_worksheet(ref, fda_sheet_name)
        fda_vals_2d = with_retry(lambda: fda_ws.get_values('A:A', value_render_option='UNFORMATTED_VALUE'))

        # 정규화된 키로 변환하여 저장
        target_categories = set()
        for r in (fda_vals_2d or []):
            if r and str(r[0]).strip():
                normalized = normalize_category_path(str(r[0]).strip())
                if normalized:
                    target_categories.add(normalized)

        print(f"   [FDA] Loaded {len(target_categories)} categories")

    except Exception as e:

        print(
            f"[!] '{fda_sheet_name}' 탭을 읽는 데 실패했습니다: {e}. Step C3을 건너<binary data, 2 bytes><binary data, 2 bytes><binary data, 2 bytes>니다.")
        return

    try:
        tem_ws = safe_worksheet(sh, tem_name)
        vals = with_retry(lambda: tem_ws.get_all_values()) or []
    except WorksheetNotFound:
        print(f"[!] {tem_name} 탭 없음. Step C1/C2 선행 필요.");
        return

    if not vals: return

    updates: List[Cell] = []
    current_keys, col_category_B, col_fda_B = None, -1, -1

    for r0, row in enumerate(vals):
        if (row[1] if len(row) > 1 else "").strip().lower() == "category":
            current_keys = [header_key(h) for h in row[1:]]
            col_category_B = _find_col_index(current_keys, "category")
            # header_key를 사용하여 FDA 헤더를 찾습니다.
            col_fda_B = _find_col_index(current_keys, fda_header)
            continue
        if not current_keys or col_fda_B < 0 or col_category_B < 0: continue

        pid = (row[0] if len(row) > 0 else "").strip()
        if not pid: continue

        category_val_raw = (row[col_category_B + 1] if len(row) > (col_category_B + 1) else "").strip()
        if not category_val_raw:
            continue

        # 정규화된 키로 비교 (핵심 개선!)
        category_val_normalized = normalize_category_path(category_val_raw)

        if category_val_normalized in target_categories:

            c_fda_sheet_col = col_fda_B + 2
            # TEM_OUTPUT 행의 해당 열 값(FDA 필드)을 가져옵니다.
            cur_fda = (row[c_fda_sheet_col - 1] if len(row) >= c_fda_sheet_col else "").strip()

            if not cur_fda or overwrite:
                updates.append(Cell(row=r0 + 1, col=c_fda_sheet_col, value=FDA_CODE))

    if updates:
        with_retry(lambda: tem_ws.update_cells(updates, value_input_option="RAW"))

    print(f"C3 Done. FDA codes applied: {len(updates)} cells.")


# C4: MARGIN → TEM 가격 매핑 (SKU 기준, 'SKU Price' 채우기)
def run_step_C4_prices(sh: gspread.Spreadsheet):
    # C4 로직... (생략)
    pass


# C5: 이미지 URL 채우기 (Option/Cover/Details) + Variation 복원
def run_step_C5_images(
        sh: gspread.Spreadsheet,
        shop_code: str,
        cover_base_url: str,
        details_base_url: str,
        option_base_url: str,
):
    # C5 로직... (생략)
    pass


# C6: Stock/Weight/Brand 보정 (Weight 채우기 STEP 4 이식)
def run_step_C6_stock_weight_brand(sh: gspread.Spreadsheet):
    print("\n[ Create ] Step C6: Fill Stock, Weight, Brand (Weight STEP 4)...")
    tem_name = get_tem_sheet_name()
    tem_ws = safe_worksheet(sh, tem_name)
    tem_vals = with_retry(lambda: tem_ws.get_all_values()) or []
    if not tem_vals:
        print("[C6] TEM_OUTPUT 비어 있음.")
        return

    # 1) MARGIN 시트 로드 (SKU ↔ Weight)
    sku_to_weight: Dict[str, str] = {}
    try:
        mg_ws = safe_worksheet(sh, "MARGIN")
        mg_vals = with_retry(lambda: mg_ws.get_all_values()) or []
        if len(mg_vals) >= 2:
            mg_keys = [header_key(h) for h in mg_vals[0]]

            # [STEP 4 이식 확인]: _pick_index_by_candidates를 사용하여 인덱스 후보 적용
            idx_mg_sku = _pick_index_by_candidates(mg_vals[0], ["sku", "seller_sku"])
            # Weight 채우기 (automation_steps.py의 STEP 4와 동일한 후보)
            idx_mg_weight = _pick_index_by_candidates(mg_vals[0], ["weight", "package weight"])

            if idx_mg_sku != -1 and idx_mg_weight != -1:
                for r in range(1, len(mg_vals)):
                    row = mg_vals[r]
                    sku = (row[idx_mg_sku] if idx_mg_sku < len(row) else "").strip()
                    weight = (row[idx_mg_weight] if idx_mg_weight < len(row) else "").strip()
                    if sku and weight:
                        sku_to_weight[sku] = weight
    except WorksheetNotFound:
        print("[C6] MARGIN 시트를 찾을 수 없습니다. Weight 매핑을 건너뜜.")
    except Exception as e:
        print(f"[C6] MARGIN 처리 중 오류: {e}. Weight 매핑 건너뜜.")

    # Brand 매핑 로직은 그대로 유지 (Brand=0 고정)

    # 2) TEM에서 블록별 헤더 탐지 후 Stock, Weight, Brand, SKU 인덱스 찾아 채움
    updates: List[Cell] = []
    cur_headers = None
    idx_t_sku = idx_t_stock = idx_t_weight = idx_t_brand = -1

    for r0, row in enumerate(tem_vals):
        if (row[1] if len(row) > 1 else "").strip().lower() == "category":
            cur_headers = [header_key(h) for h in row[1:]]
            idx_t_sku = _find_col_index(cur_headers, "sku")
            idx_t_stock = _find_col_index(cur_headers, "stock")
            idx_t_weight = _find_col_index(cur_headers, "weight")
            idx_t_brand = _find_col_index(cur_headers, "brand")
            continue
        if not cur_headers or idx_t_sku == -1: continue
        sku = (row[idx_t_sku + 1] if idx_t_sku != -1 and len(row) > idx_t_sku + 1 else "").strip()
        if not sku: continue

        # Stock (M열 = 1000)
        if idx_t_stock != -1:
            val = "1000"
            cur = (row[idx_t_stock + 1] if len(row) > idx_t_stock + 1 else "").strip()
            if cur != val:
                updates.append(Cell(row=r0 + 1, col=idx_t_stock + 2, value=val))

        # Brand (AE열 = 0)
        if idx_t_brand != -1:
            val = "0"
            cur = (row[idx_t_brand + 1] if len(row) > idx_t_brand + 1 else "").strip()
            if cur != val:
                updates.append(Cell(row=r0 + 1, col=idx_t_brand + 2, value=val))

        # Weight (Z열 = MARGIN 매핑)
        if idx_t_weight != -1 and sku:
            val = sku_to_weight.get(sku, "")
            if val:
                cur = (row[idx_t_weight + 1] if len(row) > idx_t_weight + 1 else "").strip()
                if cur != val:
                    updates.append(Cell(row=r0 + 1, col=idx_t_weight + 2, value=val))

    if updates:
        with_retry(lambda: tem_ws.update_cells(updates, value_input_option="RAW"))

    print(f"C6 Done. Updates: {len(updates)} cells")


class ShopeeCreator:
    """
    [V_20251009_FINAL_DOWNLOAD_FIX] 신규 상품 템플릿 생성 파이프라인 컨트롤러. (main_controller.py의 _ImplCreator)
    """

    def __init__(self, sheet_url: str, ref_url: Optional[str] = None) -> None:
        if not sheet_url:
            raise ValueError("sheet_url is required.")
        self.sheet_url = sheet_url
        self.ref_url = ref_url

        self.gc: Optional[gspread.Client] = None
        self.sh: Optional[gspread.Spreadsheet] = None
        self.ref: Optional[gspread.Spreadsheet] = None

        # main_controller.py에서 주입되는 속성들
        self.shop_code: Optional[str] = None
        self.cover_base_url: Optional[str] = None
        self.details_base_url: Optional[str] = None
        self.option_base_url: Optional[str] = None

    # ----------------------------------------------------------
    # 내부 유틸
    # ----------------------------------------------------------

    def _connect(self) -> None:
        """gspread 인증 및 대상/레퍼런스 스프레드시트 오픈"""
        # (생략)

    def _reset_failures(self) -> None:
        """실행 시마다 Failures 시트를 초기화"""
        # (생략)

    # ----------------------------------------------------------
    # 실행
    # ----------------------------------------------------------
    def run(self) -> bool:
        """
        실행 전체 파이프라인:
          C1 → C2 → C3 (FDA) → C4 → C5 → C6
        """
        # (생략)
        try:
            # 인증 및 시트 연결
            self._connect()
            assert self.sh is not None
            if not self.ref:
                raise ValueError("Reference sheet URL is required or invalid.")

            self._reset_failures()

            # 단계 실행: C3 (FDA) 추가
            run_step_C1(self.sh, self.ref)
            run_step_C2(self.sh, self.ref)
            run_step_C3_fda(self.sh, self.ref)
            run_step_C4_prices(self.sh)
            run_step_C5_images(
                self.sh,
                shop_code=self.shop_code,
                cover_base_url=self.cover_base_url,
                details_base_url=self.details_base_url,
                option_base_url=self.option_base_url,
            )
            run_step_C6_stock_weight_brand(self.sh)

            print("✅ 모든 단계 완료되었습니다.")
            return True

        except Exception as e:
            # (생략)
            print(f"[ERROR] ShopeeCreator.run() 실패: {e}")
            import traceback
            traceback.print_exc()
            return False

    # ----------------------------------------------------------
    # 엑셀 다운로드 (xlsx) - STEP 7 이식
    # ----------------------------------------------------------

    def get_tem_values_xlsx(self) -> Optional[BytesIO]:
        """
        [STEP 7 이식] TEM_OUTPUT 시트를 TopLevel Category 단위로 분할하여 엑셀(xlsx) 파일로 반환합니다.
        - A열 PID 제거, Category 형식 정규화 조건 반영, 오토 포맷 적용.
        """
        # (로직 생략 - 이전 답변과 동일)
        if not self.sh: return None
        tem_name = get_tem_sheet_name()
        try:
            tem_ws = safe_worksheet(self.sh, tem_name)
        except WorksheetNotFound:
            return None

        all_data = with_retry(lambda: tem_ws.get_all_values())
        if not all_data: return None

        df = pd.DataFrame(all_data)
        for c in df.columns: df[c] = df[c].astype(str)
        header_mask = df.iloc[:, 1].str.lower().eq("category")
        header_indices = df.index[header_mask].tolist()
        if not header_indices: return None

        output = BytesIO()
        try:
            import xlsxwriter; engine = "xlsxwriter"
        except ImportError:
            try:
                import openpyxl; engine = "openpyxl"
            except ImportError:
                print("[!] 엑셀(xlsx) 생성을 위해 'xlsxwriter' 또는 'openpyxl' 라이브러리가 필요합니다. CSV로 폴백할 수 있습니다.")
                return None  # <--- 여기서 None 반환됨!

        with pd.ExcelWriter(output, engine=engine) as writer:
            # (STEP 7 분할 로직 - 생략)
            for i, header_index in enumerate(header_indices):
                start_row = header_index + 1
                end_row = header_indices[i + 1] if i + 1 < len(header_indices) else len(df)
                if start_row >= end_row: continue

                header_row = df.iloc[header_index, 1:]
                chunk_df = df.iloc[start_row:end_row, 1:].copy()

                if not chunk_df.empty and chunk_df.shape[1] > 0 and header_key(header_row.iloc[0]) == "category":
                    chunk_df.iloc[:, 0] = chunk_df.iloc[:, 0].astype(str).str.replace(r"\s*-\s*", "-", regex=True)

                columns = header_row.astype(str).tolist()
                if len(columns) != chunk_df.shape[1]:
                    if len(columns) < chunk_df.shape[1]:
                        columns += [f"col_{k}" for k in range(len(columns), chunk_df.shape[1])]
                    else:
                        columns = columns[: chunk_df.shape[1]]
                chunk_df.columns = columns

                cat_col_name = next((c for c in columns if c.lower() == "category"), None)
                first_cat = str(chunk_df.iloc[0][cat_col_name]) if (cat_col_name and not chunk_df.empty) else "UNKNOWN"
                top_level_name = top_of_category(first_cat) or "UNKNOWN"
                sheet_name = re.sub(r"[\s/\\*?:\[\]]", "_", str(top_level_name).title())[:31]

                chunk_df.to_excel(writer, sheet_name=sheet_name, index=False)

                # (오토 포맷 로직 생략)

        output.seek(0)
        print("Final template file generated successfully (xlsx).")
        return output

    # ----------------------------------------------------------
    # CSV Export (main_controller가 fallback으로 사용)
    # ----------------------------------------------------------

    def get_tem_values_csv(self) -> Optional[bytes]:
        """
        [main_controller가 사용하는 공식 CSV 다운로드 함수]
        - A열 PID 제거 및 Category 정규화 로직이 포함된 최신 버전입니다.
        """
        # (CSV 폴백 로직 - 생략)
        if not self.sh: return None
        try:
            ws = safe_worksheet(self.sh, "TEM_OUTPUT")
            vals = with_retry(lambda: ws.get_all_values()) or []
            if not vals: return None

            processed_vals = [];
            current_headers = None
            for row in vals:
                if (row[1] if len(row) > 1 else "").strip().lower() == "category":
                    current_headers = row[1:]
                    processed_vals.append(current_headers)
                    continue
                if current_headers and len(row) > 1:
                    data_row = row[1:]
                    if len(data_row) > 0 and current_headers and header_key(current_headers[0]) == "category":
                        data_row[0] = re.sub(r"\s*-\s*", "-", data_row[0])
                    processed_vals.append(data_row)
                elif len(row) > 0:
                    processed_vals.append(row[1:])

            if not processed_vals: return None
            buf = io.StringIO();
            writer = csv.writer(buf)
            writer.writerows(processed_vals)
            return buf.getvalue().encode("utf-8-sig")
        except Exception as e:
            print(f"[WARN] TEM_OUTPUT CSV 변환 실패: {e}")
            return None
