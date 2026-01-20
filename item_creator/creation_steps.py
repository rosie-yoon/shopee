# item_creator/creation_steps.py
# -*- coding: utf-8 -*-
"""
[V_20250120_RECURSIVE_MATCHING] 신규 상품 템플릿 생성 파이프라인
- C2: 완전 재귀 매칭 전략 적용 (automation_steps_revised.py Step 1 로직 이식)
- C3: FDA 카테고리 정규화 강화
- C4, C5: 완전한 구현 추가
"""
from __future__ import annotations

from typing import List, Dict, Optional, Any
import io
import csv
import re
from io import BytesIO
from collections import defaultdict

import gspread
from gspread.cell import Cell
from gspread.utils import rowcol_to_a1
from gspread.exceptions import WorksheetNotFound
import pandas as pd

from utils_common import (
    header_key, top_of_category, get_tem_sheet_name,
    with_retry, safe_worksheet, authorize_gspread, extract_sheet_id,
    get_env
)
from .utils_common import join_url, forward_fill_by_group


# ==============================================================================
# [NEW] 중카테고리 & 시트명 유틸 (automation_steps와 로직 통일)
# ==============================================================================

def mid_of_category(s: str, depth: int = 2) -> str:
    """카테고리 경로에서 중카테고리(depth=2)까지만 추출"""
    if not s or not isinstance(s, str):
        return ""
    # 숫자 코드 제거
    cleaned = s.strip()
    cleaned = re.sub(r'^\s*\d+\s*-\s*', '', cleaned)
    # 슬래시로 분할하여 중카테고리 추출
    parts = [p.strip() for p in cleaned.split("/") if p.strip()]
    if len(parts) <= depth:
        return "/".join(parts)
    return "/".join(parts[:depth])


def safe_sheet_name(category_name: str, max_length: int = 31) -> str:
    """Excel 시트명 제약 조건을 만족하도록 카테고리명 변환"""
    if not category_name:
        return "UNKNOWN"
    # 특수문자를 언더스코어로 치환
    clean_name = re.sub(r'[\\/*?:\[\]&]', '_', str(category_name))
    clean_name = clean_name.replace(' ', '_')
    clean_name = re.sub(r'_+', '_', clean_name)
    clean_name = clean_name.strip('_')

    if len(clean_name) <= max_length:
        return clean_name

    # 스마트 축약: 마지막 부분(세부 카테고리) 우선 보존
    parts = clean_name.split('_')
    if len(parts) >= 2:
        first_part = parts[0][:10]
        remaining_length = max_length - len(first_part) - 1
        last_parts = '_'.join(parts[1:])
        if len(last_parts) <= remaining_length:
            return f"{first_part}_{last_parts}"
        else:
            return f"{first_part}_{last_parts[:remaining_length]}"
    return clean_name[:max_length]


# ==============================================================================
# automation_steps.py 공통 헬퍼 함수 이식
# ==============================================================================

def _find_col_index(keys: List[str], name: str, extra_alias: List[str] = []) -> int:
    """헤더 키 목록에서 name 또는 alias를 찾음 (정확 > 부분 일치)"""
    tgt = header_key(name)
    alias_keys = [header_key(a) for a in extra_alias if a]

    # 1) 정확 매칭 - 타겟
    if tgt:
        for i, k in enumerate(keys):
            if k == tgt:
                return i

    # 2) 부분 일치 - 타겟
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


def _pick_index_by_candidates(header_row: List[str], candidates: List[str]) -> int:
    """헤더 행에서 후보명(정규화)으로 가장 그럴듯한 인덱스 찾기"""
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
    """레퍼런스 시트에서 템플릿 헤더 사전 로딩"""
    ref_sheet = get_env("TEMPLATE_DICT_SHEET_NAME", "TemplateDict")
    ws = safe_worksheet(ref, ref_sheet)
    vals = with_retry(lambda: ws.get_all_values()) or []
    out: Dict[str, List[str]] = {}
    for r in vals[1:]:
        if not r or not (r[0] or "").strip():
            continue
        out[header_key(r[0])] = [str(x or "").strip() for x in r[1:]]
    return out


def _append_failures(sh: gspread.Spreadsheet, rows: List[List[str]]):
    """Failures 탭에 rows를 append. 공간 부족 시 자동 resize."""
    if not rows:
        return
    try:
        ws = safe_worksheet(sh, "Failures")
        vals = with_retry(lambda: ws.get_all_values()) or []
        start_row = len(vals) + 1
        end_row = start_row + len(rows) - 1

        if end_row > ws.row_count:
            with_retry(lambda: ws.resize(rows=end_row + 100, cols=max(ws.col_count, 10)))

        with_retry(lambda: ws.update(values=rows, range_name=f"A{start_row}"))

    except WorksheetNotFound:
        ws = with_retry(lambda: sh.add_worksheet(title="Failures", rows=1000, cols=10))
        header = [["PID", "Category", "Name", "Reason", "Detail"]]
        with_retry(lambda: ws.update(values=header + rows, range_name="A1"))


# ==============================================================================
# C1: TEM_OUTPUT 시트 준비/초기화
# ==============================================================================

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
        "variation": key_to_idx.get("parentsku", 1),
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


# ==============================================================================
# C2: Collection → TEM_OUTPUT 생성 (완전 재귀 매칭 전략 적용)
# ==============================================================================

def run_step_C2(sh: gspread.Spreadsheet, ref: gspread.Spreadsheet):
    """
    [V_20250120_RECURSIVE_MATCHING] Collection → TEM_OUTPUT 생성
    - automation_steps_revised.py Step 1의 완전 재귀 매칭 전략 이식
    - 가장 깊은 경로부터 최상위까지 순차 검색하여 최적 템플릿 매칭
    """
    print("\n[ Create ] Step C2: Build TEM from Collection (Recursive Matching)...")
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
        # 핵심 개선: 완전 재귀 매칭 전략 (automation_steps_revised.py 이식)
        # ========================================

        # 1. 카테고리 경로 분할 및 정규화
        cleaned_cat = re.sub(r'^\s*\d+\s*-\s*', '', category.strip())
        normalized_cat = re.sub(r'\s*/\s*', '/', cleaned_cat)
        parts = [p.strip() for p in normalized_cat.split('/') if p.strip()]

        headers = None
        bucket_key = ""
        match_level = ""

        # 2. 가장 깊은 경로부터 최상위까지 순차 검색
        # 예: A/B/C/D -> A/B/C -> A/B -> A 순서로 시도
        for i in range(len(parts), 0, -1):
            sub_path = "/".join(parts[:i])
            key = header_key(sub_path)

            if key in template_dict:
                headers = template_dict[key]
                bucket_key = key
                match_level = f"DEPTH_{i}"
                if i < len(parts):
                    print(f"   [MATCH] Found template at depth {i}: {sub_path}")
                break

        # 3. 매칭 실패 시 기본 템플릿 적용
        if not headers:
            headers = ["Category", "Product Name", "SKU", "Brand", "Stock", "Weight"]

            # 버킷 키는 중카테고리(depth=2) 기준으로 그룹화 유지
            if len(parts) >= 2:
                fallback_path = "/".join(parts[:2])
            elif len(parts) == 1:
                fallback_path = parts[0]
            else:
                fallback_path = "UNKNOWN"

            bucket_key = header_key(fallback_path)
            match_level = "DEFAULT"

            print(f"   [DEFAULT] Template not found for '{category}'. Scanned {len(parts)} levels.")
            failures.append(["", category, pname, "TEMPLATE_NOT_FOUND", f"scanned_levels={len(parts)}"])

        # 4. TEM 행 생성
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
        b = buckets.setdefault(bucket_key, {"headers": headers, "pids": [], "rows": []})
        b["pids"].append([pid])
        b["rows"].append(tem_row)

    # 5. TEM_OUTPUT 시트에 출력
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
        _append_failures(sh, failures)

    print("========== STEP C2 RESULT ==========")
    print(f"TEM 생성 행수: {len(out_matrix) - len(buckets):,}")
    print(f"Failures 기록: {len(failures):,}")
    print(f"Buckets: {len(buckets)}")


# ==============================================================================
# C3: FDA Registration No. 채우기 (카테고리 정규화 강화)
# ==============================================================================

def run_step_C3_fda(sh: gspread.Spreadsheet, ref: gspread.Spreadsheet, overwrite: bool = False):
    """
    [V_20250120_NORMALIZED_MATCHING] FDA 코드 채우기
    - 카테고리 정규화 로직 강화 (공백/특수문자 처리)
    """
    print("\n[ Create ] Step C3: Fill FDA Code (Normalized Matching)...")

    tem_name = get_tem_sheet_name()
    fda_sheet_name = get_env("FDA_CATEGORIES_SHEET_NAME", "TH Cos")
    fda_header = get_env("FDA_HEADER_NAME", "FDA Registration No.")
    FDA_CODE = "10-1-9999999"

    def _normalize_category(s: str) -> str:
        """카테고리 정규화: 숫자 코드 제거 + 공백/특수문자 처리"""
        if not s: return ""
        # 1단계: 숫자 코드 제거
        cleaned = re.sub(r'^\s*\d+\s*-\s*', '', str(s).strip())
        # 2단계: 슬래시 주변 공백 정규화
        normalized = re.sub(r'\s*/\s*', '/', cleaned)
        # 3단계: 소문자 변환
        result = normalized.lower()
        # 4단계: 특수문자 처리
        result = result.replace(" - ", "/").replace("-", "/").replace("\\", "/")
        result = "/".join(seg.strip() for seg in result.split("/") if seg.strip())
        # 중복 슬래시 제거
        while "//" in result:
            result = result.replace("//", "/")
        return result

    try:
        fda_ws = safe_worksheet(ref, fda_sheet_name)
        fda_vals_2d = with_retry(lambda: fda_ws.get_values('A:A', value_render_option='UNFORMATTED_VALUE'))
        # 정규화된 카테고리 목록 생성
        target_categories = {
            _normalize_category(str(r[0]))
            for r in (fda_vals_2d or [])
            if r and str(r[0]).strip()
        }
    except Exception as e:
        print(f"[!] '{fda_sheet_name}' 탭을 읽는 데 실패했습니다: {e}. Step C3을 건너뜁니다.")
        return

    try:
        tem_ws = safe_worksheet(sh, tem_name)
        vals = with_retry(lambda: tem_ws.get_all_values()) or []
    except WorksheetNotFound:
        print(f"[!] {tem_name} 탭 없음. Step C1/C2 선행 필요.")
        return

    if not vals:
        print("[!] TEM_OUTPUT 비어 있음.")
        return

    updates: List[Cell] = []
    current_keys, col_category_B, col_fda_B = None, -1, -1
    updated_rows = 0

    for r0, row in enumerate(vals):
        if (row[1] if len(row) > 1 else "").strip().lower() == "category":
            current_keys = [header_key(h) for h in row[1:]]
            col_category_B = _find_col_index(current_keys, "category")
            col_fda_B = _find_col_index(current_keys, fda_header)
            continue
        if not current_keys or col_fda_B < 0 or col_category_B < 0:
            continue

        pid = (row[0] if len(row) > 0 else "").strip()
        if not pid:
            continue

        category_val_raw = (row[col_category_B + 1] if len(row) > (col_category_B + 1) else "").strip()
        category_val_normalized = _normalize_category(category_val_raw)

        if category_val_normalized and category_val_normalized in target_categories:
            c_fda_sheet_col = col_fda_B + 2
            cur_fda = (row[c_fda_sheet_col - 1] if len(row) >= c_fda_sheet_col else "").strip()

            if not cur_fda or overwrite:
                updates.append(Cell(row=r0 + 1, col=c_fda_sheet_col, value=FDA_CODE))
                updated_rows += 1

    if updates:
        with_retry(lambda: tem_ws.update_cells(updates, value_input_option="RAW"))

    print(f"========== STEP C3 FDA RESULT ==========")
    print(f"적용된 셀 수: {updated_rows:,}")
    print("Step C3: Fill FDA Code Finished.")


# ==============================================================================
# C4: MARGIN → TEM 가격 매핑 (완전 구현)
# ==============================================================================

def run_step_C4_prices(sh: gspread.Spreadsheet):
    """Step C4: MARGIN 시트의 가격을 SKU 기준으로 TEM_OUTPUT에 매핑"""
    print("\n[ Create ] Step C4: Fill Prices from MARGIN...")
    tem_name = get_tem_sheet_name()

    try:
        tem_ws = safe_worksheet(sh, tem_name)
        tem_vals = with_retry(lambda: tem_ws.get_all_values()) or []
    except WorksheetNotFound:
        print("[C4] TEM_OUTPUT 없음.")
        return

    if not tem_vals:
        print("[C4] TEM_OUTPUT 비어 있음.")
        return

    # MARGIN 시트에서 SKU → Price 매핑 구축
    sku_to_price: Dict[str, str] = {}
    try:
        mg_ws = safe_worksheet(sh, "MARGIN")
        mg_vals = with_retry(lambda: mg_ws.get_all_values()) or []
        if len(mg_vals) >= 2:
            idx_mg_sku = _pick_index_by_candidates(mg_vals[0], ["sku", "seller_sku"])
            idx_mg_price = _pick_index_by_candidates(mg_vals[0], ["price", "sku price", "global sku price"])

            if idx_mg_sku != -1 and idx_mg_price != -1:
                for r in range(1, len(mg_vals)):
                    row = mg_vals[r]
                    sku = (row[idx_mg_sku] if idx_mg_sku < len(row) else "").strip()
                    price = (row[idx_mg_price] if idx_mg_price < len(row) else "").strip()
                    if sku and price:
                        sku_to_price[sku] = price
    except WorksheetNotFound:
        print("[C4] MARGIN 시트 없음. 가격 매핑 건너뜀.")
        return
    except Exception as e:
        print(f"[C4] MARGIN 처리 중 오류: {e}")
        return

    # TEM_OUTPUT에 가격 채우기
    updates: List[Cell] = []
    cur_headers = None
    idx_t_sku = idx_t_price = -1

    for r0, row in enumerate(tem_vals):
        if (row[1] if len(row) > 1 else "").strip().lower() == "category":
            cur_headers = [header_key(h) for h in row[1:]]
            idx_t_sku = _find_col_index(cur_headers, "sku")
            idx_t_price = _find_col_index(cur_headers, "globalskuprice", ["price", "sku price"])
            continue

        if not cur_headers or idx_t_sku == -1 or idx_t_price == -1:
            continue

        sku = (row[idx_t_sku + 1] if idx_t_sku != -1 and len(row) > idx_t_sku + 1 else "").strip()
        if not sku:
            continue

        price = sku_to_price.get(sku, "")
        if price:
            cur_price = (row[idx_t_price + 1] if len(row) > idx_t_price + 1 else "").strip()
            if cur_price != price:
                updates.append(Cell(row=r0 + 1, col=idx_t_price + 2, value=price))

    if updates:
        with_retry(lambda: tem_ws.update_cells(updates, value_input_option="USER_ENTERED"))

    print(f"========== STEP C4 RESULT ==========")
    print(f"Price updates: {len(updates)} cells")
    print("Step C4: Fill Prices Finished.")


# ==============================================================================
# C5: 이미지 URL 채우기 (완전 구현)
# ==============================================================================

def run_step_C5_images(
        sh: gspread.Spreadsheet,
        shop_code: str,
        cover_base_url: str,
        details_base_url: str,
        option_base_url: str,
):
    """
    Step C5: 이미지 URL 생성 및 채우기
    - Cover Image: {cover_base_url}/{Parent SKU}_C_{shop_code}.jpg
    - Option Image: {option_base_url}/{SKU}_O_{shop_code}.jpg
    - Details Images: {details_base_url}/{Parent SKU}_D{n}_{shop_code}.jpg
    """
    print("\n[ Create ] Step C5: Fill Image URLs...")
    tem_name = get_tem_sheet_name()

    try:
        tem_ws = safe_worksheet(sh, tem_name)
        tem_vals = with_retry(lambda: tem_ws.get_all_values()) or []
    except WorksheetNotFound:
        print("[C5] TEM_OUTPUT 없음.")
        return

    if not tem_vals:
        print("[C5] TEM_OUTPUT 비어 있음.")
        return

    # URL 정규화
    if not cover_base_url.endswith("/"): cover_base_url += "/"
    if not details_base_url.endswith("/"): details_base_url += "/"
    if not option_base_url.endswith("/"): option_base_url += "/"

    updates: List[Cell] = []
    cur_headers = None
    idx_t_sku = idx_t_psku = idx_t_cover = idx_t_opt_img = -1
    idx_t_details: List[int] = []

    # Collection에서 Details Index 정보 읽기
    details_count_map: Dict[str, int] = {}  # Parent SKU → Details 개수
    try:
        coll_ws = safe_worksheet(sh, "Collection")
        coll_vals = with_retry(lambda: coll_ws.get_all_values()) or []
        if len(coll_vals) >= 2:
            colmap = _collect_indices(coll_vals[0])
            var_i = colmap["variation"]
            dcount_i = colmap["detail_idx"]

            if var_i >= 0 and dcount_i >= 0:
                for r in range(1, len(coll_vals)):
                    row = coll_vals[r]
                    psku = (row[var_i] if var_i < len(row) else "").strip()
                    dcount_str = (row[dcount_i] if dcount_i < len(row) else "").strip()
                    if psku and dcount_str:
                        try:
                            details_count_map[psku] = int(dcount_str)
                        except ValueError:
                            pass
    except Exception as e:
        print(f"[C5] Collection Details Index 읽기 실패: {e}")

    for r0, row in enumerate(tem_vals):
        if (row[1] if len(row) > 1 else "").strip().lower() == "category":
            cur_headers = [header_key(h) for h in row[1:]]
            idx_t_sku = _find_col_index(cur_headers, "sku")
            idx_t_psku = _find_col_index(cur_headers, "variationintegration", ["parent sku", "parentsku"])
            idx_t_cover = _find_col_index(cur_headers, "coverimage")
            idx_t_opt_img = _find_col_index(cur_headers, "imagepervariation", ["option image"])

            # Details Image 컬럼 찾기 (Item Image 1~9)
            idx_t_details = []
            for i in range(1, 10):
                idx = _find_col_index(cur_headers, f"itemimage{i}")
                if idx >= 0:
                    idx_t_details.append(idx)
            continue

        if not cur_headers:
            continue

        sku = (row[idx_t_sku + 1] if idx_t_sku != -1 and len(row) > idx_t_sku + 1 else "").strip()
        psku = (row[idx_t_psku + 1] if idx_t_psku != -1 and len(row) > idx_t_psku + 1 else "").strip()

        # Cover Image (Parent SKU 우선)
        if idx_t_cover >= 0:
            sku_for_cover = psku if psku else sku
            if sku_for_cover:
                cover_url = f"{cover_base_url}{sku_for_cover}_C_{shop_code}.jpg"
                updates.append(Cell(row=r0 + 1, col=idx_t_cover + 2, value=cover_url))

        # Option Image (SKU 기준)
        if idx_t_opt_img >= 0 and sku:
            opt_url = f"{option_base_url}{sku}_O_{shop_code}.jpg"
            updates.append(Cell(row=r0 + 1, col=idx_t_opt_img + 2, value=opt_url))

        # Details Images (Parent SKU 기준, Details Index 개수만큼)
        if idx_t_details and psku:
            detail_count = details_count_map.get(psku, 0)
            for i, idx in enumerate(idx_t_details, start=1):
                if i <= detail_count:
                    detail_url = f"{details_base_url}{psku}_D{i}_{shop_code}.jpg"
                    updates.append(Cell(row=r0 + 1, col=idx + 2, value=detail_url))

    if updates:
        with_retry(lambda: tem_ws.update_cells(updates, value_input_option="USER_ENTERED"))

    print(f"========== STEP C5 RESULT ==========")
    print(f"Image URL updates: {len(updates)} cells")
    print("Step C5: Fill Image URLs Finished.")


# ==============================================================================
# C6: Stock/Weight/Brand 보정 (Weight 채우기 STEP 4 이식)
# ==============================================================================

def run_step_C6_stock_weight_brand(sh: gspread.Spreadsheet):
    """
    Step C6: Stock, Weight, Brand 채우기
    - Stock: 1000 (고정)
    - Brand: 0 (고정)
    - Weight: MARGIN 시트의 SKU 매핑 (automation_steps_revised.py STEP 4 로직)
    """
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
            idx_mg_sku = _pick_index_by_candidates(mg_vals[0], ["sku", "seller_sku"])
            idx_mg_weight = _pick_index_by_candidates(mg_vals[0], ["weight", "package weight"])

            if idx_mg_sku != -1 and idx_mg_weight != -1:
                for r in range(1, len(mg_vals)):
                    row = mg_vals[r]
                    sku = (row[idx_mg_sku] if idx_mg_sku < len(row) else "").strip()
                    weight = (row[idx_mg_weight] if idx_mg_weight < len(row) else "").strip()
                    if sku and weight:
                        sku_to_weight[sku] = weight
    except WorksheetNotFound:
        print("[C6] MARGIN 시트를 찾을 수 없습니다. Weight 매핑을 건너뜀.")
    except Exception as e:
        print(f"[C6] MARGIN 처리 중 오류: {e}. Weight 매핑 건너뜀.")

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
        if not cur_headers or idx_t_sku == -1:
            continue

        sku = (row[idx_t_sku + 1] if idx_t_sku != -1 and len(row) > idx_t_sku + 1 else "").strip()
        if not sku:
            continue

        # Stock (1000 고정)
        if idx_t_stock != -1:
            val = "1000"
            cur = (row[idx_t_stock + 1] if len(row) > idx_t_stock + 1 else "").strip()
            if cur != val:
                updates.append(Cell(row=r0 + 1, col=idx_t_stock + 2, value=val))

        # Brand (0 고정)
        if idx_t_brand != -1:
            val = "0"
            cur = (row[idx_t_brand + 1] if len(row) > idx_t_brand + 1 else "").strip()
            if cur != val:
                updates.append(Cell(row=r0 + 1, col=idx_t_brand + 2, value=val))

        # Weight (MARGIN 매핑)
        if idx_t_weight != -1 and sku:
            val = sku_to_weight.get(sku, "")
            if val:
                cur = (row[idx_t_weight + 1] if len(row) > idx_t_weight + 1 else "").strip()
                if cur != val:
                    updates.append(Cell(row=r0 + 1, col=idx_t_weight + 2, value=val))

    if updates:
        with_retry(lambda: tem_ws.update_cells(updates, value_input_option="RAW"))

    print(f"========== STEP C6 RESULT ==========")
    print(f"Updates: {len(updates)} cells")
    print("Step C6: Fill Stock, Weight, Brand Finished.")


# ==============================================================================
# Main Controller Class
# ==============================================================================

class ShopeeCreator:
    """
    [V_20250120_RECURSIVE_MATCHING] 신규 상품 템플릿 생성 파이프라인 컨트롤러
    - C2: 완전 재귀 매칭 전략 적용
    - C3: FDA 카테고리 정규화 강화
    - C4, C5: 완전한 구현 추가
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
        if not self.gc:
            self.gc = authorize_gspread()

        sheet_id = extract_sheet_id(self.sheet_url)
        if not sheet_id:
            raise ValueError(f"Invalid sheet_url: {self.sheet_url}")
        self.sh = self.gc.open_by_key(sheet_id)

        if self.ref_url:
            ref_id = extract_sheet_id(self.ref_url)
            if ref_id:
                self.ref = self.gc.open_by_key(ref_id)

        if not self.ref:
            print("[WARN] Reference sheet not available. Some features may be limited.")

    def _reset_failures(self) -> None:
        """실행 시마다 Failures 시트를 초기화"""
        if not self.sh:
            return
        try:
            ws = safe_worksheet(self.sh, "Failures")
            with_retry(lambda: ws.clear())
            header = [["PID", "Category", "Name", "Reason", "Detail"]]
            with_retry(lambda: ws.update(values=header, range_name="A1"))
        except WorksheetNotFound:
            ws = with_retry(lambda: self.sh.add_worksheet(title="Failures", rows=1000, cols=10))
            header = [["PID", "Category", "Name", "Reason", "Detail"]]
            with_retry(lambda: ws.update(values=header, range_name="A1"))
        except Exception as e:
            print(f"[WARN] Failures 시트 초기화 실패: {e}")

    # ----------------------------------------------------------
    # 실행
    # ----------------------------------------------------------
    def run(self) -> bool:
        """
        실행 전체 파이프라인:
          C1 → C2 → C3 (FDA) → C4 → C5 → C6
        """
        try:
            # 인증 및 시트 연결
            self._connect()
            assert self.sh is not None
            if not self.ref:
                raise ValueError("Reference sheet URL is required or invalid.")

            self._reset_failures()

            # 단계 실행
            run_step_C1(self.sh, self.ref)
            run_step_C2(self.sh, self.ref)
            run_step_C3_fda(self.sh, self.ref)
            run_step_C4_prices(self.sh)
            run_step_C5_images(
                self.sh,
                shop_code=self.shop_code or "",
                cover_base_url=self.cover_base_url or "",
                details_base_url=self.details_base_url or "",
                option_base_url=self.option_base_url or "",
            )
            run_step_C6_stock_weight_brand(self.sh)

            print("✅ 모든 단계 완료되었습니다.")
            return True

        except Exception as e:
            print(f"[ERROR] ShopeeCreator.run() 실패: {e}")
            import traceback
            traceback.print_exc()
            return False

    # ----------------------------------------------------------
    # 엑셀 다운로드 (xlsx) - 중카테고리 기준 분할
    # ----------------------------------------------------------

    def get_tem_values_xlsx(self) -> Optional[BytesIO]:
        """
        [STEP 7 이식] TEM_OUTPUT 시트를 중카테고리 단위로 분할하여 엑셀(xlsx) 파일로 반환합니다.
        - A열 PID 제거, Category 형식 정규화 조건 반영, 오토 포맷 적용.
        """
        if not self.sh:
            return None

        tem_name = get_tem_sheet_name()
        try:
            tem_ws = safe_worksheet(self.sh, tem_name)
        except WorksheetNotFound:
            return None

        all_data = with_retry(lambda: tem_ws.get_all_values())
        if not all_data:
            return None

        df = pd.DataFrame(all_data)
        for c in df.columns:
            df[c] = df[c].astype(str)

        header_mask = df.iloc[:, 1].str.lower().eq("category")
        header_indices = df.index[header_mask].tolist()
        if not header_indices:
            return None

        output = BytesIO()
        try:
            import xlsxwriter
            engine = "xlsxwriter"
        except ImportError:
            try:
                import openpyxl
                engine = "openpyxl"
            except ImportError:
                print("[!] 엑셀(xlsx) 생성을 위해 'xlsxwriter' 또는 'openpyxl' 라이브러리가 필요합니다.")
                return None

        with pd.ExcelWriter(output, engine=engine) as writer:
            for i, header_index in enumerate(header_indices):
                start_row = header_index + 1
                end_row = header_indices[i + 1] if i + 1 < len(header_indices) else len(df)
                if start_row >= end_row:
                    continue

                header_row = df.iloc[header_index, 1:]
                chunk_df = df.iloc[start_row:end_row, 1:].copy()

                # Category 정규화 (숫자 코드 제거)
                if not chunk_df.empty and chunk_df.shape[1] > 0 and header_key(header_row.iloc[0]) == "category":
                    chunk_df.iloc[:, 0] = chunk_df.iloc[:, 0].astype(str).str.replace(r"\s*-\s*", "-", regex=True)

                columns = header_row.astype(str).tolist()
                if len(columns) != chunk_df.shape[1]:
                    if len(columns) < chunk_df.shape[1]:
                        columns += [f"col_{k}" for k in range(len(columns), chunk_df.shape[1])]
                    else:
                        columns = columns[: chunk_df.shape[1]]
                chunk_df.columns = columns

                # ========================================
                # 핵심 변경: 중카테고리 기준 시트명 생성
                # ========================================
                cat_col_name = next((c for c in columns if c.lower() == "category"), None)
                first_cat = str(chunk_df.iloc[0][cat_col_name]) if (cat_col_name and not chunk_df.empty) else "UNKNOWN"

                # 중카테고리 기준으로 시트명 생성
                mid_level_name = mid_of_category(first_cat) or "UNKNOWN"
                sheet_name = safe_sheet_name(mid_level_name)

                chunk_df.to_excel(writer, sheet_name=sheet_name, index=False)

                # 엑셀 포맷 적용
                try:
                    ws = writer.sheets.get(sheet_name)
                    if ws:
                        try:
                            ws.freeze_panes(1, 0)
                        except Exception:
                            pass
                        try:
                            widths = [
                                max(9, min(60, int(chunk_df[col].astype(str).map(len).max() or 0) + 2))
                                for col in chunk_df.columns
                            ]
                            for col_idx, width in enumerate(widths):
                                ws.set_column(col_idx, col_idx, width)
                        except Exception:
                            pass
                except Exception:
                    pass

        output.seek(0)
        print("Final template file generated successfully (xlsx/Mid-Category).")
        return output

    # ----------------------------------------------------------
    # CSV Export (main_controller가 fallback으로 사용)
    # ----------------------------------------------------------

    def get_tem_values_csv(self) -> Optional[bytes]:
        """
        [main_controller가 사용하는 공식 CSV 다운로드 함수]
        - A열 PID 제거 및 Category 정규화 로직이 포함된 최신 버전입니다.
        """
        if not self.sh:
            return None

        try:
            ws = safe_worksheet(self.sh, "TEM_OUTPUT")
            vals = with_retry(lambda: ws.get_all_values()) or []
            if not vals:
                return None

            processed_vals = []
            current_headers = None

            for row in vals:
                if (row[1] if len(row) > 1 else "").strip().lower() == "category":
                    current_headers = row[1:]
                    processed_vals.append(current_headers)
                    continue

                if current_headers and len(row) > 1:
                    data_row = row[1:]
                    # Category 정규화
                    if len(data_row) > 0 and current_headers and header_key(current_headers[0]) == "category":
                        data_row[0] = re.sub(r"\s*-\s*", "-", data_row[0])
                    processed_vals.append(data_row)
                elif len(row) > 0:
                    processed_vals.append(row[1:])

            if not processed_vals:
                return None

            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerows(processed_vals)
            return buf.getvalue().encode("utf-8-sig")

        except Exception as e:
            print(f"[WARN] TEM_OUTPUT CSV 변환 실패: {e}")
            return None
