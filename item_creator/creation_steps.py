# item_creator/creation_steps.py
# -*- coding: utf-8 -*-
"""
[V_20250120_COMPLETE_FIX] 신규 상품 템플릿 생성 파이프라인
- C2: 완전 재귀 매칭 + C5 호환 안전 템플릿 적용
- C5: 페이지 호출 방식 완전 호환 + 유연한 컬럼 매칭
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
# [NEW] 카테고리 경로 생성 헬퍼 함수
# ==============================================================================

def _generate_category_paths(category_raw: str) -> List[str]:
    """카테고리에서 가장 깊은 경로부터 상위 경로까지 순차 생성"""
    if not category_raw:
        return []

    # 숫자 코드 제거 + 공백 정규화
    cleaned = re.sub(r'^\s*\d+\s*-\s*', '', category_raw.strip())
    normalized = re.sub(r'\s*/\s*', '/', cleaned)

    parts = [p.strip() for p in normalized.split('/') if p.strip()]
    if not parts:
        return []

    # 가장 깊은 경로부터 상위 경로까지
    paths: List[str] = []
    for i in range(len(parts), 0, -1):
        sub_path = "/".join(parts[:i])
        paths.append(sub_path)
    return paths


# ==============================================================================
# 공통 헬퍼 함수
# ==============================================================================

def _find_col_index(keys: List[str], name: str, extra_alias: List[str] = []) -> int:
    """헤더 키 목록에서 name 또는 alias를 찾음 (정확 > 부분 일치)"""
    tgt = header_key(name)
    alias_keys = [header_key(a) for a in extra_alias if a]

    # 정확 매칭 - 타겟
    if tgt:
        for i, k in enumerate(keys):
            if k == tgt: return i
    # 부분 일치 - 타겟
    if tgt:
        for i, k in enumerate(keys):
            if tgt in k: return i
    # 정확 매칭 - alias
    for i, k in enumerate(keys):
        if k in alias_keys and (not tgt or k != tgt): return i
    # 부분 일치 - alias
    for i, k in enumerate(keys):
        if any(a and a in k for a in alias_keys): return i
    return -1


def _pick_index_by_candidates(header_row: List[str], candidates: List[str]) -> int:
    """헤더 행에서 후보명(정규화)으로 가장 그럴듯한 인덱스 찾기"""
    keys = [header_key(x) for x in header_row]
    for cand in candidates:
        ck = header_key(cand)
        for i, k in enumerate(keys):
            if k == ck: return i
    for cand in candidates:
        ck = header_key(cand)
        if not ck: continue
        for i, k in enumerate(keys):
            if ck in k: return i
    return -1


def _load_template_dict(ref: gspread.Spreadsheet) -> Dict[str, List[str]]:
    """레퍼런스 시트에서 템플릿 헤더 사전 로딩"""
    ref_sheet = get_env("TEMPLATE_DICT_SHEET_NAME", "TemplateDict")
    ws = safe_worksheet(ref, ref_sheet)
    vals = with_retry(lambda: ws.get_all_values()) or []
    out: Dict[str, List[str]] = {}
    for r in vals[1:]:
        if not r or not (r[0] or "").strip(): continue
        out[header_key(r[0])] = [str(x or "").strip() for x in r[1:]]
    return out


def _is_true(v: str) -> bool:
    return str(v or "").strip().lower() in ("true", "t", "1", "y", "yes", "✔", "✅")


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
# C2: Collection → TEM_OUTPUT 생성 (완전 재귀 매칭 + 안전 템플릿)
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


def run_step_C2(sh: gspread.Spreadsheet, ref: gspread.Spreadsheet):
    """
    [V_20250120_COMPLETE_FIX] Collection → TEM_OUTPUT 생성
    - 완전 재귀 매칭 전략 적용
    - 매칭 실패 시 C5 호환 안전 템플릿 사용 (RuntimeError 완전 방지)
    """
    print("\n[ Create ] Step C2: Build TEM from Collection (Complete Fix)...")
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

        # ================================
        # [핵심] 완전 재귀 카테고리 매칭
        # ================================
        headers = None
        bucket_key = ""
        tried_paths: List[str] = []

        # 가장 깊은 경로부터 상위 경로까지 순차 검색
        for path in _generate_category_paths(category):
            key = header_key(path)
            tried_paths.append(path)
            if key in template_dict:
                headers = template_dict[key]
                bucket_key = key
                if len(tried_paths) > 1:
                    print(f"   [MATCH] Found template at: {path}")
                break

        # 매칭 실패 시 C5 완전 호환 안전 템플릿 사용
        if not headers:
            headers = [
                "Category", "Product Name", "Product Description",
                "Variation Integration", "Parent SKU", "SKU",
                "Variation Name 1", "Option for Variation 1",
                "Price", "Stock", "Weight", "Brand",
                "Cover Image", "Image Per Variation",
                "Item Image 1", "Item Image 2", "Item Image 3",
                "Item Image 4", "Item Image 5", "Item Image 6",
                "Item Image 7", "Item Image 8", "Item Image 9"
            ]
            bucket_key = header_key(top_of_category(category) or "UNKNOWN")
            print(f"   [SAFE_DEFAULT] Using C5-compatible template for '{category}'")
            failures.append([
                "", category, pname, "TEMPLATE_NOT_FOUND",
                f"tried_paths={' -> '.join(tried_paths[:3])}..."
            ])

        # TEM 행 생성
        tem_row = [""] * len(headers)
        set_if_exists(headers, tem_row, "category", category)
        set_if_exists(headers, tem_row, "product name", pname)
        set_if_exists(headers, tem_row, "product description", desc)
        set_if_exists(headers, tem_row, "variation integration", variation)
        set_if_exists(headers, tem_row, "parent sku", variation)
        set_if_exists(headers, tem_row, "variation name1", "Options")
        set_if_exists(headers, tem_row, "option for variation 1", opt1)
        set_if_exists(headers, tem_row, "sku", sku)
        set_if_exists(headers, tem_row, "brand", brand)

        pid = variation or sku or f"ROW{r + 1}"
        b = buckets.setdefault(bucket_key, {"headers": headers, "pids": [], "rows": []})
        b["pids"].append([pid])
        b["rows"].append(tem_row)

    # TEM_OUTPUT 시트에 출력
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
        try:
            ws = safe_worksheet(sh, "Failures")
            vals = with_retry(lambda: ws.get_all_values()) or []
            start_row = len(vals) + 1
            with_retry(lambda: ws.update(values=failures, range_name=f"A{start_row}"))
        except Exception:
            pass

    print("========== STEP C2 RESULT ==========")
    print(f"TEM 생성 행수: {len(out_matrix) - len(buckets):,}")
    print(f"Failures 기록: {len(failures):,}")
    print(f"Buckets: {len(buckets)}")


# ==============================================================================
# C3: FDA Registration No. 채우기
# ==============================================================================

def run_step_C3_fda(sh: gspread.Spreadsheet, ref: gspread.Spreadsheet, overwrite: bool = False):
    print("\n[ Create ] Step C3: Fill FDA Code...")
    tem_name = get_tem_sheet_name()
    fda_sheet_name = get_env("FDA_CATEGORIES_SHEET_NAME", "TH Cos")
    fda_header = get_env("FDA_HEADER_NAME", "FDA Registration No.")
    FDA_CODE = "10-1-9999999"

    try:
        fda_ws = safe_worksheet(ref, fda_sheet_name)
        fda_vals_2d = with_retry(lambda: fda_ws.get_values('A:A', value_render_option='UNFORMATTED_VALUE'))
        target_categories = {str(r[0]).strip().lower() for r in (fda_vals_2d or []) if r and str(r[0]).strip()}
    except Exception:
        print(f"[!] '{fda_sheet_name}' 탭 읽기 실패. C3 건너뜀.")
        return

    try:
        tem_ws = safe_worksheet(sh, tem_name)
        vals = with_retry(lambda: tem_ws.get_all_values()) or []
    except WorksheetNotFound:
        print(f"[!] {tem_name} 탭 없음.")
        return

    if not vals: return

    updates: List[Cell] = []
    current_keys, col_category_B, col_fda_B = None, -1, -1

    for r0, row in enumerate(vals):
        if (row[1] if len(row) > 1 else "").strip().lower() == "category":
            current_keys = [header_key(h) for h in row[1:]]
            col_category_B = _find_col_index(current_keys, "category")
            col_fda_B = _find_col_index(current_keys, fda_header)
            continue
        if not current_keys or col_fda_B < 0 or col_category_B < 0: continue

        pid = (row[0] if len(row) > 0 else "").strip()
        if not pid: continue

        category_val_raw = (row[col_category_B + 1] if len(row) > (col_category_B + 1) else "").strip()
        if category_val_raw.lower() in target_categories:
            c_fda_sheet_col = col_fda_B + 2
            cur_fda = (row[c_fda_sheet_col - 1] if len(row) >= c_fda_sheet_col else "").strip()
            if not cur_fda or overwrite:
                updates.append(Cell(row=r0 + 1, col=c_fda_sheet_col, value=FDA_CODE))

    if updates:
        with_retry(lambda: tem_ws.update_cells(updates, value_input_option="RAW"))
    print(f"C3 Done. FDA applied: {len(updates)}")


# ==============================================================================
# C4: MARGIN → TEM 가격 매핑
# ==============================================================================

def run_step_C4_prices(sh: gspread.Spreadsheet):
    print("\n[ Create ] Step C4: Fill Prices...")
    tem_name = get_tem_sheet_name()
    try:
        tem_ws = safe_worksheet(sh, tem_name)
        tem_vals = with_retry(lambda: tem_ws.get_all_values()) or []
    except WorksheetNotFound:
        return
    if not tem_vals: return

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
    except Exception:
        pass

    updates: List[Cell] = []
    cur_headers = None
    idx_t_sku = idx_t_price = -1

    for r0, row in enumerate(tem_vals):
        if (row[1] if len(row) > 1 else "").strip().lower() == "category":
            cur_headers = [header_key(h) for h in row[1:]]
            idx_t_sku = _find_col_index(cur_headers, "sku")
            idx_t_price = _find_col_index(cur_headers, "globalskuprice", ["price", "sku price"])
            continue
        if not cur_headers or idx_t_sku == -1 or idx_t_price == -1: continue

        sku = (row[idx_t_sku + 1] if idx_t_sku != -1 and len(row) > idx_t_sku + 1 else "").strip()
        if not sku: continue

        price = sku_to_price.get(sku, "")
        if price:
            cur_price = (row[idx_t_price + 1] if len(row) > idx_t_price + 1 else "").strip()
            if cur_price != price:
                updates.append(Cell(row=r0 + 1, col=idx_t_price + 2, value=price))

    if updates:
        with_retry(lambda: tem_ws.update_cells(updates, value_input_option="USER_ENTERED"))
    print(f"C4 Done. Prices updated: {len(updates)}")


# ==============================================================================
# C5: 이미지 URL 채우기 (페이지 호출 방식 완전 호환)
# ==============================================================================

def run_step_C5_images(sh: gspread.Spreadsheet, base_url: str, shop_code: str):
    """
    [V_20250120_COMPLETE_FIX] 이미지 URL 채우기
    - 페이지 호출 방식 완전 호환 (base_url 파라미터)
    - 유연한 컬럼 매칭 (컬럼이 있으면 채우고 없으면 무시)
    """
    print("\n[ Create ] Step C5: Fill Image URLs (Complete Compatibility)...")
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
    if not base_url.endswith("/"):
        base_url += "/"

    updates: List[Cell] = []
    cur_headers = None
    idx_t_sku = idx_t_psku = idx_t_cover = idx_t_opt_img = -1
    idx_t_details: List[int] = []

    # Collection에서 Details Index 정보 읽기
    details_count_map: Dict[str, int] = {}
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
    except Exception:
        pass

    for r0, row in enumerate(tem_vals):
        if (row[1] if len(row) > 1 else "").strip().lower() == "category":
            cur_headers = [header_key(h) for h in row[1:]]
            idx_t_sku = _find_col_index(cur_headers, "sku")
            idx_t_psku = _find_col_index(cur_headers, "variationintegration", ["parent sku", "parentsku"])
            idx_t_cover = _find_col_index(cur_headers, "coverimage")
            idx_t_opt_img = _find_col_index(cur_headers, "imagepervariation", ["option image"])

            # Details Image 컬럼 찾기 (유연한 매칭)
            idx_t_details = []
            for i in range(1, 10):
                idx = _find_col_index(cur_headers, f"itemimage{i}")
                if idx >= 0: idx_t_details.append(idx)
            continue

        if not cur_headers: continue

        sku = (row[idx_t_sku + 1] if idx_t_sku != -1 and len(row) > idx_t_sku + 1 else "").strip()
        psku = (row[idx_t_psku + 1] if idx_t_psku != -1 and len(row) > idx_t_psku + 1 else "").strip()

        # Cover Image (Parent SKU 우선, 컬럼이 있을 때만)
        if idx_t_cover >= 0:
            sku_for_cover = psku if psku else sku
            if sku_for_cover:
                cover_url = f"{base_url}{sku_for_cover}_C_{shop_code}.jpg"
                updates.append(Cell(row=r0 + 1, col=idx_t_cover + 2, value=cover_url))

        # Option Image (SKU 기준, 컬럼이 있을 때만)
        if idx_t_opt_img >= 0 and sku:
            opt_url = f"{base_url}{sku}_O_{shop_code}.jpg"
            updates.append(Cell(row=r0 + 1, col=idx_t_opt_img + 2, value=opt_url))

        # Details Images (Parent SKU 기준, 컬럼이 있을 때만)
        if idx_t_details and psku:
            detail_count = details_count_map.get(psku, 0)
            for i, idx in enumerate(idx_t_details, start=1):
                if i <= detail_count:
                    detail_url = f"{base_url}{psku}_D{i}_{shop_code}.jpg"
                    updates.append(Cell(row=r0 + 1, col=idx + 2, value=detail_url))

    if updates:
        with_retry(lambda: tem_ws.update_cells(updates, value_input_option="USER_ENTERED"))

    print(f"========== STEP C5 RESULT ==========")
    print(f"Image URL updates: {len(updates)} cells")
    print("Step C5: Fill Image URLs Finished.")


# ==============================================================================
# C6: Stock/Weight/Brand 보정
# ==============================================================================

def run_step_C6_stock_weight_brand(sh: gspread.Spreadsheet):
    print("\n[ Create ] Step C6: Fill Stock, Weight, Brand...")
    tem_name = get_tem_sheet_name()
    tem_ws = safe_worksheet(sh, tem_name)
    tem_vals = with_retry(lambda: tem_ws.get_all_values()) or []
    if not tem_vals: return

    # MARGIN 시트 로드 (SKU ↔ Weight)
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
    except Exception:
        pass

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
    print(f"C6 Done. Updates: {len(updates)}")


# ==============================================================================
# Main Controller Class
# ==============================================================================

class ShopeeCreator:
    """
    [V_20250120_COMPLETE_FIX] 신규 상품 템플릿 생성 파이프라인 컨트롤러
    """

    def __init__(self, sheet_url: str, ref_url: Optional[str] = None) -> None:
        if not sheet_url: raise ValueError("sheet_url is required.")
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
        if not self.gc: self.gc = authorize_gspread()
        sheet_id = extract_sheet_id(self.sheet_url)
        if not sheet_id: raise ValueError(f"Invalid sheet_url: {self.sheet_url}")
        self.sh = self.gc.open_by_key(sheet_id)
        if self.ref_url:
            ref_id = extract_sheet_id(self.ref_url)
            if ref_id: self.ref = self.gc.open_by_key(ref_id)

    def _reset_failures(self) -> None:
        if not self.sh: return
        try:
            ws = safe_worksheet(self.sh, "Failures")
            with_retry(lambda: ws.clear())
            header = [["PID", "Category", "Name", "Reason", "Detail"]]
            with_retry(lambda: ws.update(values=header, range_name="A1"))
        except WorksheetNotFound:
            ws = with_retry(lambda: self.sh.add_worksheet(title="Failures", rows=1000, cols=10))
            header = [["PID", "Category", "Name", "Reason", "Detail"]]
            with_retry(lambda: ws.update(values=header, range_name="A1"))
        except Exception:
            pass

    def run(self) -> bool:
        try:
            self._connect()
            assert self.sh is not None
            if not self.ref: raise ValueError("Reference sheet URL is required or invalid.")

            self._reset_failures()
            run_step_C1(self.sh, self.ref)
            run_step_C2(self.sh, self.ref)
            run_step_C3_fda(self.sh, self.ref)
            run_step_C4_prices(self.sh)

            # [핵심 수정] 페이지 호출 방식에 맞춘 C5 호출
            base_url = self.cover_base_url or self.details_base_url or self.option_base_url or ""
            run_step_C5_images(sh=self.sh, base_url=base_url, shop_code=self.shop_code or "")

            run_step_C6_stock_weight_brand(self.sh)
            print("✅ 모든 단계 완료되었습니다.")
            return True
        except Exception as e:
            print(f"[ERROR] ShopeeCreator.run() 실패: {e}")
            import traceback
            traceback.print_exc()
            return False

    def get_tem_values_xlsx(self) -> Optional[BytesIO]:
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
                return None

        with pd.ExcelWriter(output, engine=engine) as writer:
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

                def _mid_of_category(s: str, depth: int = 2) -> str:
                    if not s: return ""
                    cleaned = re.sub(r'^\s*\d+\s*-\s*', '', s.strip())
                    parts = [p.strip() for p in cleaned.split("/") if p.strip()]
                    return "/".join(parts[:depth]) if len(parts) > depth else "/".join(parts)

                cat_col_name = next((c for c in columns if c.lower() == "category"), None)
                first_cat = str(chunk_df.iloc[0][cat_col_name]) if (cat_col_name and not chunk_df.empty) else "UNKNOWN"
                mid_level_name = _mid_of_category(first_cat) or "UNKNOWN"
                clean_name = re.sub(r'[\\/*?:\[\]&]', '_', str(mid_level_name))
                sheet_name = re.sub(r'_+', '_', clean_name.replace(' ', '_')).strip('_')[:31]

                chunk_df.to_excel(writer, sheet_name=sheet_name, index=False)
                try:
                    ws = writer.sheets.get(sheet_name)
                    if ws:
                        try:
                            ws.freeze_panes(1, 0)
                        except:
                            pass
                        try:
                            widths = [max(9, min(60, int(chunk_df[col].astype(str).map(len).max() or 0) + 2)) for col in
                                      chunk_df.columns]
                            for col_idx, width in enumerate(widths): ws.set_column(col_idx, col_idx, width)
                        except:
                            pass
                except:
                    pass
        output.seek(0)
        return output

    def get_tem_values_csv(self) -> Optional[bytes]:
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
        except Exception:
            return None
