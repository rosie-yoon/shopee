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

import pandas as pd


# ✅ 공용 유틸은 "한 군데"에서만 가져오도록 정리 (get_env 섀도잉 제거)
from .utils_common import (
    header_key, top_of_category, get_tem_sheet_name,
    with_retry, safe_worksheet, authorize_gspread, extract_sheet_id,
    get_env, join_url, forward_fill_by_group
)


# ✅ 패키지 로컬 유틸은 get_env 제외하고 필요한 것만
from .utils_common import join_url, forward_fill_by_group


# ==============================================================================
# 공통 헬퍼 (automation_steps.py 스타일)
# ==============================================================================

def _find_col_index(keys: List[str], name: str, extra_alias: List[str] = []) -> int:
    """
    헤더 키 목록(keys=header_key 적용된 리스트)에서 name 또는 alias를 찾음
    - 1순위: name(타겟)의 정확 매칭
    - 2순위: name(타겟)의 부분 일치
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


def _append_failures(sh: gspread.Spreadsheet, rows: List[List[str]]):
    """Failures 탭에 rows를 append. 없으면 생성."""
    if not rows:
        return
    try:
        ws = safe_worksheet(sh, "Failures")
        vals = with_retry(lambda: ws.get_all_values()) or []
        start_row = len(vals) + 1
        end_row = start_row + len(rows) - 1

        if end_row > ws.row_count:
            with_retry(lambda: ws.resize(rows=end_row + 200, cols=max(ws.col_count, 10)))

        with_retry(lambda: ws.update(values=rows, range_name=f"A{start_row}"))
    except WorksheetNotFound:
        ws = with_retry(lambda: sh.add_worksheet(title="Failures", rows=1000, cols=10))
        header = [["PID", "Category", "Name", "Reason", "Detail"]]
        with_retry(lambda: ws.update(values=header + rows, range_name="A1"))


# ==============================================================================
# Template Dict 로딩
# ==============================================================================

def _load_template_dict(ref: gspread.Spreadsheet) -> Dict[str, List[str]]:
    """
    Reference 시트의 TemplateDict를 로딩해 dict로 반환
    key: header_key(category)
    value: headers(list[str])
    """
    ref_sheet = get_env("TEMPLATE_DICT_SHEET_NAME", "TemplateDict")
    ws = safe_worksheet(ref, ref_sheet)
    vals = with_retry(lambda: ws.get_all_values()) or []
    out: Dict[str, List[str]] = {}
    for r in vals[1:]:
        if not r or not (r[0] or "").strip():
            continue
        out[header_key(r[0])] = [str(x or "").strip() for x in r[1:]]
    return out


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


# ==============================================================================
# C2: Collection -> TEM_OUTPUT 생성
# ==============================================================================

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

        pid = variation or sku or f"ROW{r+1}"

        if not category:
            failures.append([pid, "", pname, "CATEGORY_MISSING", f"row={r+1}"])
            continue

        top_norm = header_key(top_of_category(category) or "")
        headers = template_dict.get(top_norm)
        if not headers:
            failures.append([pid, category, pname, "TEMPLATE_TOPLEVEL_NOT_FOUND", f"top={top_of_category(category)}"])
            continue

        tem_row = [""] * len(headers)
        set_if_exists(headers, tem_row, "category", category)
        set_if_exists(headers, tem_row, "product name", pname)
        set_if_exists(headers, tem_row, "product description", desc)
        set_if_exists(headers, tem_row, "variation integration", variation)
        set_if_exists(headers, tem_row, "variation name1", "Options")
        set_if_exists(headers, tem_row, "option for variation 1", opt1)
        set_if_exists(headers, tem_row, "sku", sku)
        set_if_exists(headers, tem_row, "brand", brand)

        b = buckets.setdefault(top_norm, {"headers": headers, "pids": [], "rows": []})
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
        _append_failures(sh, failures)

    print(f"C2 Done. Buckets: {len(buckets)} / Failures: {len(failures)}")


# ==============================================================================
# C3: FDA Registration No. 채우기
# ==============================================================================

def run_step_C3_fda(sh: gspread.Spreadsheet, ref: gspread.Spreadsheet, overwrite: bool = False):
    print("\n[ Create ] Step C3: Fill FDA Code (STEP 3)...")

    tem_name = get_tem_sheet_name()
    fda_sheet_name = get_env("FDA_CATEGORIES_SHEET_NAME", "TH Cos")
    fda_header = get_env("FDA_HEADER_NAME", "FDA Registration No.")
    FDA_CODE = "10-1-9999999"

    try:
        fda_ws = safe_worksheet(ref, fda_sheet_name)
        fda_vals_2d = with_retry(lambda: fda_ws.get_values('A:A', value_render_option='UNFORMATTED_VALUE'))
        target_categories = {str(r[0]).strip().lower() for r in (fda_vals_2d or []) if r and str(r[0]).strip()}
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
        return

    updates: List[Cell] = []
    current_keys, col_category_B, col_fda_B = None, -1, -1

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
        category_val_normalized = category_val_raw.lower()

        if category_val_normalized and category_val_normalized in target_categories:
            c_fda_sheet_col = col_fda_B + 2
            cur_fda = (row[c_fda_sheet_col - 1] if len(row) >= c_fda_sheet_col else "").strip()
            if not cur_fda or overwrite:
                updates.append(Cell(row=r0 + 1, col=c_fda_sheet_col, value=FDA_CODE))

    if updates:
        with_retry(lambda: tem_ws.update_cells(updates, value_input_option="RAW"))

    print(f"C3 Done. FDA codes applied: {len(updates)} cells.")


# ==============================================================================
# C4: 가격 매핑 (여기는 기존대로 pass - 네 프로젝트 원본 로직 붙이면 됨)
# ==============================================================================

def run_step_C4_prices(sh: gspread.Spreadsheet):
    # TODO: 기존 프로젝트의 C4 로직을 여기에 유지/이식
    pass


# ==============================================================================
# C5: 이미지 URL 채우기 + Variation 복원 (🔥 핵심 수정본)
# ==============================================================================

def _parse_c5_headers(header_row: List[str]) -> Dict[str, Any]:
    """
    C5 전용 헤더 파서
    - '헤더가 유효한지'를 검증하지 않음
    - 존재하는 컬럼만 인덱스를 반환 (없으면 -1)
    """
    keys = [header_key(h) for h in header_row]
    return {
        "sku": _find_col_index(keys, "sku"),
        "parent_sku": _find_col_index(keys, "parentsku"),
        "variation": _find_col_index(keys, "variationintegration"),
        "cover": _find_col_index(keys, "coverimage"),
        "option_img": _find_col_index(keys, "imagepervariation"),
        "item_imgs": [i for i, k in enumerate(keys) if k.startswith("itemimage")],
    }


def run_step_C5_images(
    sh: gspread.Spreadsheet,
    shop_code: str,
    cover_base_url: str,
    details_base_url: str,
    option_base_url: str,
):
    """
    C5는 "검증"이 아니라 "보강" 단계:
    - 헤더는 row[1] == 'category' 만으로 탐지
    - 컬럼은 있으면 채우고, 없으면 스킵
    - 절대 RuntimeError를 내지 않음

    (복제기능의 Step 6 / Step 5 패턴과 동일한 철학) :contentReference[oaicite:1]{index=1}
    """
    print("\n[ Create ] Step C5: Fill Image URLs + Restore Variation ...")

    tem_name = get_tem_sheet_name()
    tem_ws = safe_worksheet(sh, tem_name)
    tem_vals = with_retry(lambda: tem_ws.get_all_values()) or []
    if not tem_vals:
        print("[C5] TEM_OUTPUT 비어 있음.")
        return

    updates: List[Cell] = []
    current_hdr: Optional[Dict[str, Any]] = None
    pid_groups: Dict[str, List[int]] = defaultdict(list)

    for r_idx, row in enumerate(tem_vals):
        # 헤더 감지
        if len(row) > 1 and (row[1] or "").strip().lower() == "category":
            current_hdr = _parse_c5_headers(row[1:])
            continue
        if not current_hdr:
            continue

        # PID 그룹(variation 복원용)
        pid = (row[0] or "").strip()
        if pid:
            pid_groups[pid].append(r_idx + 1)

        # SKU 추출
        sku = ""
        if current_hdr["sku"] != -1 and len(row) > current_hdr["sku"] + 1:
            sku = (row[current_hdr["sku"] + 1] or "").strip()
        if not sku:
            continue

        # Cover Image
        if current_hdr["cover"] != -1:
            c = current_hdr["cover"] + 2
            if c - 1 < len(row) and not (row[c - 1] or "").strip():
                url = join_url(cover_base_url, f"{sku}_C_{shop_code}.jpg")
                updates.append(Cell(row=r_idx + 1, col=c, value=url))

        # Option Image
        if current_hdr["option_img"] != -1:
            c = current_hdr["option_img"] + 2
            if c - 1 < len(row) and not (row[c - 1] or "").strip():
                url = join_url(option_base_url, f"{sku}_O_{shop_code}.jpg")
                updates.append(Cell(row=r_idx + 1, col=c, value=url))

        # Detail / Item Images
        for k, idx in enumerate(current_hdr["item_imgs"], start=1):
            c = idx + 2
            if c - 1 < len(row) and not (row[c - 1] or "").strip():
                url = join_url(details_base_url, f"{sku}_{k}_{shop_code}.jpg")
                updates.append(Cell(row=r_idx + 1, col=c, value=url))

    # Variation Integration 복원 (컬럼이 있을 때만)
    # 복제 기능과 동일하게 PID 중복행이면 V{pid} 부여 :contentReference[oaicite:2]{index=2}
    if current_hdr and current_hdr.get("variation", -1) != -1:
        col_v = current_hdr["variation"] + 2
        for pid, rows in pid_groups.items():
            if len(rows) > 1:
                v_code = f"V{pid}"
                for r in rows:
                    updates.append(Cell(row=r, col=col_v, value=v_code))

    if updates:
        with_retry(lambda: tem_ws.update_cells(updates, value_input_option="USER_ENTERED"))

    print(f"C5 Done. Updates: {len(updates)} cells.")


# ==============================================================================
# C6: Stock/Weight/Brand 보정
# ==============================================================================

def run_step_C6_stock_weight_brand(sh: gspread.Spreadsheet):
    print("\n[ Create ] Step C6: Fill Stock, Weight, Brand ...")

    tem_name = get_tem_sheet_name()
    tem_ws = safe_worksheet(sh, tem_name)
    tem_vals = with_retry(lambda: tem_ws.get_all_values()) or []
    if not tem_vals:
        print("[C6] TEM_OUTPUT 비어 있음.")
        return

    # MARGIN에서 SKU -> Weight
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
        print("[C6] MARGIN 시트를 찾을 수 없습니다. Weight 매핑 스킵.")
    except Exception as e:
        print(f"[C6] MARGIN 처리 오류: {e}. Weight 매핑 스킵.")

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

        sku = (row[idx_t_sku + 1] if len(row) > idx_t_sku + 1 else "").strip()
        if not sku:
            continue

        # Stock = 1000
        if idx_t_stock != -1:
            val = "1000"
            cur = (row[idx_t_stock + 1] if len(row) > idx_t_stock + 1 else "").strip()
            if cur != val:
                updates.append(Cell(row=r0 + 1, col=idx_t_stock + 2, value=val))

        # Brand = 0
        if idx_t_brand != -1:
            val = "0"
            cur = (row[idx_t_brand + 1] if len(row) > idx_t_brand + 1 else "").strip()
            if cur != val:
                updates.append(Cell(row=r0 + 1, col=idx_t_brand + 2, value=val))

        # Weight = mapping
        if idx_t_weight != -1:
            val = sku_to_weight.get(sku, "")
            if val:
                cur = (row[idx_t_weight + 1] if len(row) > idx_t_weight + 1 else "").strip()
                if cur != val:
                    updates.append(Cell(row=r0 + 1, col=idx_t_weight + 2, value=val))

    if updates:
        with_retry(lambda: tem_ws.update_cells(updates, value_input_option="RAW"))

    print(f"C6 Done. Updates: {len(updates)} cells")


# ==============================================================================
# Creator Controller
# ==============================================================================

class ShopeeCreator:
    """
    신규 상품 템플릿 생성 파이프라인 컨트롤러
    """

    def __init__(self, sheet_url: str, ref_url: Optional[str] = None) -> None:
        if not sheet_url:
            raise ValueError("sheet_url is required.")
        self.sheet_url = sheet_url
        self.ref_url = ref_url

        self.gc: Optional[gspread.Client] = None
        self.sh: Optional[gspread.Spreadsheet] = None
        self.ref: Optional[gspread.Spreadsheet] = None

        self.shop_code: Optional[str] = None
        self.cover_base_url: Optional[str] = None
        self.details_base_url: Optional[str] = None
        self.option_base_url: Optional[str] = None

    def _connect(self) -> None:
        """gspread 인증 및 대상/레퍼런스 스프레드시트 오픈"""
        # TODO: 기존 프로젝트의 _connect 로직 유지
        pass

    def _reset_failures(self) -> None:
        """실행 시마다 Failures 시트를 초기화"""
        # TODO: 기존 프로젝트의 Failures 초기화 로직 유지
        pass

    def run(self) -> bool:
        """
        실행 전체 파이프라인:
          C1 → C2 → C3 → C4 → C5 → C6
        """
        try:
            self._connect()
            assert self.sh is not None
            if not self.ref:
                raise ValueError("Reference sheet URL is required or invalid.")

            self._reset_failures()

            run_step_C1(self.sh, self.ref)
            run_step_C2(self.sh, self.ref)
            run_step_C3_fda(self.sh, self.ref)
            run_step_C4_prices(self.sh)

            run_step_C5_images(
                self.sh,
                shop_code=str(self.shop_code or "").strip(),
                cover_base_url=str(self.cover_base_url or "").strip(),
                details_base_url=str(self.details_base_url or "").strip(),
                option_base_url=str(self.option_base_url or "").strip(),
            )

            run_step_C6_stock_weight_brand(self.sh)

            print("✅ 모든 단계 완료되었습니다.")
            return True

        except Exception as e:
            print(f"[ERROR] ShopeeCreator.run() 실패: {e}")
            import traceback
            traceback.print_exc()
            return False

    # --------------------------------------------------------------------------
    # 엑셀 다운로드 (xlsx) - 기존 로직 유지
    # --------------------------------------------------------------------------

    def get_tem_values_xlsx(self) -> Optional[BytesIO]:
        """
        TEM_OUTPUT 시트를 TopLevel Category 단위로 분할하여 엑셀(xlsx) 파일로 반환
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
                print("[!] 엑셀(xlsx) 생성을 위해 'xlsxwriter' 또는 'openpyxl' 필요. CSV 폴백 가능.")
                return None

        with pd.ExcelWriter(output, engine=engine) as writer:
            for i, header_index in enumerate(header_indices):
                start_row = header_index + 1
                end_row = header_indices[i + 1] if i + 1 < len(header_indices) else len(df)
                if start_row >= end_row:
                    continue

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

        output.seek(0)
        print("Final template file generated successfully (xlsx).")
        return output

    # --------------------------------------------------------------------------
    # CSV Export (기존 로직 유지)
    # --------------------------------------------------------------------------

    def get_tem_values_csv(self) -> Optional[bytes]:
        """
        TEM_OUTPUT CSV 변환
        - PID(A열) 제거
        - Category 형식 정규화(하이픈 공백 제거)
        """
        if not self.sh:
            return None

        try:
            ws = safe_worksheet(self.sh, "TEM_OUTPUT")
            vals = with_retry(lambda: ws.get_all_values()) or []
            if not vals:
                return None

            processed_vals: List[List[str]] = []
            current_headers = None

            for row in vals:
                if (row[1] if len(row) > 1 else "").strip().lower() == "category":
                    current_headers = row[1:]
                    processed_vals.append(current_headers)
                    continue

                if current_headers and len(row) > 1:
                    data_row = row[1:]
                    if len(data_row) > 0 and header_key(current_headers[0]) == "category":
                        data_row[0] = re.sub(r"\s*-\s*", "-", data_row[0])
                    processed_vals.append(data_row)
                else:
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
