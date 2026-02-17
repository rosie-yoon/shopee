# -*- coding: utf-8 -*-
"""
Page 4: 통합 엑셀 생성기 (Parent SKU/Child SKU 완전 해결 버전)
- 실제 컬럼명 'Parent SKU', 'Child SKU' 정확 매핑
- Media Info 파일 전처리 강화
- automation_steps_revised.py 로직 적용
"""

from pathlib import Path
import sys
import io
import re
import zipfile
from datetime import datetime
from typing import List, Optional

import streamlit as st
import pandas as pd

st.set_page_config(page_title="Excel Export", layout="wide")

# 프로젝트 루트 경로 추가
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from auth_guard import bootstrap_auth
from user_manager import get_user_pref
from item_uploader.utils_common import get_env, header_key

bootstrap_auth(go_home=False)

st.title("📊 통합 엑셀 생성기")
st.caption("BASIC/MEDIA/SALES 파일을 한 번에 업로드하여 Shopee 업로드용 엑셀을 생성합니다")
st.markdown("---")


# ──────────────────────────────────────────────
# Shopee 엑셀 파일 Sanitizer
# ──────────────────────────────────────────────
def sanitize_shopee_excel(file_obj) -> io.BytesIO:
    """Shopee 엑셀 파일의 freezePanes 오류 해결"""
    try:
        file_obj.seek(0)
        content = file_obj.read()

        zin = zipfile.ZipFile(io.BytesIO(content), 'r')
        out_buffer = io.BytesIO()
        zout = zipfile.ZipFile(out_buffer, 'w', zipfile.ZIP_DEFLATED)

        sheetviews_pattern = re.compile(r'<sheetViews[^>]*>.*?</sheetViews>', re.DOTALL)
        pane_pattern = re.compile(r'<pane[^>]*/?>', re.DOTALL)

        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.startswith('xl/worksheets/sheet') and item.filename.endswith('.xml'):
                xml_str = data.decode('utf-8', errors='ignore')
                xml_str = sheetviews_pattern.sub('', xml_str)
                xml_str = pane_pattern.sub('', xml_str)
                data = xml_str.encode('utf-8')
            zout.writestr(item, data)

        zout.close()
        out_buffer.seek(0)
        return out_buffer
    except Exception as e:
        print(f"Sanitize failed: {e}")
        file_obj.seek(0)
        return file_obj


# ──────────────────────────────────────────────
# 사이드바 설정
# ──────────────────────────────────────────────
with st.sidebar:
    st.subheader("⚙️ 설정")

    current_host = (
            get_user_pref("export_image_host") or
            get_user_pref("copy_image_host") or
            get_user_pref("image_host") or
            get_env("IMAGE_HOSTING_URL") or ""
    )

    host_input = st.text_input(
        "Image Hosting URL (필수)",
        value=current_host,
        placeholder="https://example.com/images/",
        help="Cover Image URL 생성에 사용됩니다"
    )

    if st.button("💾 설정 저장", use_container_width=True):
        if host_input.strip():
            if "user_prefs" not in st.session_state:
                st.session_state["user_prefs"] = {}
            st.session_state["user_prefs"]["export_image_host"] = host_input.strip()
            st.success("✅ 저장 완료")
            st.rerun()
        else:
            st.warning("⚠️ URL을 입력해주세요")


def resolve_export_host() -> str:
    """저장된 이미지 호스팅 URL 불러오기"""
    if "user_prefs" in st.session_state:
        val = st.session_state["user_prefs"].get("export_image_host")
        if val:
            return val.strip()
    return (
            get_user_pref("export_image_host") or
            get_user_pref("copy_image_host") or
            get_user_pref("image_host") or
            get_env("IMAGE_HOSTING_URL") or ""
    ).strip()


# ──────────────────────────────────────────────
# 파일 로더 및 전처리
# ──────────────────────────────────────────────
def find_header_row(df_preview: pd.DataFrame) -> int:
    """헤더 행 자동 감지"""
    keywords = ['product', 'sku', 'category', 'variation', 'option', 'name', 'image', 'parent']
    for i in range(min(10, len(df_preview))):
        row_text = ' '.join([str(val).lower() for val in df_preview.iloc[i].values if pd.notna(val)])
        match_count = sum(1 for kw in keywords if kw in row_text)
        if match_count >= 3:
            return i
    return 0


def load_local_file_safe(file) -> pd.DataFrame:
    """안전한 파일 로더 (Sanitization + 전처리 적용)"""
    if file is None:
        return pd.DataFrame()

    try:
        if file.name.endswith('.csv'):
            df = pd.read_csv(file, dtype=str).fillna('')
        else:
            file.seek(0)
            clean_file = sanitize_shopee_excel(file)

            try:
                df_preview = pd.read_excel(clean_file, header=None, nrows=10, engine='openpyxl')
                header_row = find_header_row(df_preview)
                clean_file.seek(0)
                df = pd.read_excel(clean_file, header=header_row, engine='openpyxl', dtype=str)
                df = df.fillna('').dropna(how='all')
            except Exception:
                clean_file.seek(0)
                df = pd.read_excel(clean_file, dtype=str, engine='openpyxl').fillna('')

        # 파일별 전처리
        if "media" in file.name.lower():
            df = preprocess_media_file(df)
        elif "sales" in file.name.lower():
            df = preprocess_sales_file(df)

        return df

    except Exception as e:
        st.error(f"파일 로드 실패 ({file.name}): {str(e)}")
        return pd.DataFrame()


def preprocess_media_file(df: pd.DataFrame) -> pd.DataFrame:
    """Media Info 파일 전처리 (설명 행 제거)"""
    if df.empty:
        return df

    first_col = df.columns[0]

    # "Not Editable", "Optional" 등 설명 행 제거
    df = df[
        ~df[first_col].astype(str).str.lower().isin([
            'not editable', 'optional', '', 'nan'
        ])
    ]

    # 너무 긴 설명 텍스트 행 제거 (50자 이상)
    df = df[df[first_col].astype(str).str.len() < 50]

    # "If the product has..." 같은 설명 행 제거
    df = df[
        ~df[first_col].astype(str).str.contains(
            'product has|please note|upload', case=False, na=False
        )
    ]

    return df.reset_index(drop=True)


def preprocess_sales_file(df: pd.DataFrame) -> pd.DataFrame:
    """Sales 파일 전처리 (헤더 잔재 제거)"""
    if df.empty:
        return df

    first_col = df.columns[0]

    # JSON 문자열이나 헤더 잔재 제거
    df = df[
        ~df[first_col].astype(str).str.contains(
            r'search_condition|\{|\}', case=False, na=False, regex=True
        )
    ]

    # "Parent SKU" 텍스트가 데이터로 들어간 행 제거
    df = df[
        df[first_col].astype(str).str.lower() != 'parent sku'
        ]

    return df.reset_index(drop=True)


# ──────────────────────────────────────────────
# 정확한 컬럼 검색 (automation_steps 로직 적용)
# ──────────────────────────────────────────────
def find_parent_sku_column(df_columns: List[str]) -> Optional[str]:
    """Parent SKU 컬럼 직접 검색"""
    # 1단계: 정확한 매칭
    for col in df_columns:
        col_clean = str(col).strip().lower()
        if col_clean in ['parent sku', 'parentsku', 'parent_sku']:
            return col

    # 2단계: 포함 검색
    for col in df_columns:
        col_lower = str(col).lower()
        if 'parent' in col_lower and 'sku' in col_lower:
            return col

    # 3단계: 유연한 검색 (Product ID 등)
    for col in df_columns:
        if header_key(col) in ['productid', 'itemid', 'pid']:
            return col

    return None


def find_child_sku_column(df_columns: List[str], parent_col: str) -> Optional[str]:
    """Child SKU 컬럼 검색 (Parent와 명확히 구분)"""
    # 1단계: 정확한 매칭
    priority_names = ['sku', 'child sku', 'childsku', 'seller sku', 'sellersku']

    for name in priority_names:
        for col in df_columns:
            col_clean = str(col).strip().lower()
            if col_clean == name and col != parent_col:
                return col

    # 2단계: 포함 검색
    for col in df_columns:
        col_lower = str(col).lower()
        if ('sku' in col_lower and 'parent' not in col_lower) and col != parent_col:
            return col

    return None


def find_column_flexible(target: str, df_columns: List[str], aliases: List[str] = []) -> Optional[str]:
    """유연한 컬럼 검색"""
    target_key = header_key(target)

    # 1. 정확 매칭
    for col in df_columns:
        if header_key(str(col)) == target_key:
            return col

    # 2. 별칭 매칭
    for alias in aliases:
        alias_key = header_key(alias)
        for col in df_columns:
            if header_key(str(col)) == alias_key:
                return col

    # 3. 부분 매칭
    for col in df_columns:
        col_key = header_key(str(col))
        if target_key in col_key or col_key in target_key:
            return col

    return None


def classify_files(uploaded_files):
    """파일명으로 자동 분류"""
    basic, media, sales = None, None, None
    for file in uploaded_files:
        low = file.name.lower()
        if "basic" in low:
            basic = file
        elif "media" in low:
            media = file
        elif "sales" in low:
            sales = file
    return basic, media, sales


# ──────────────────────────────────────────────
# Cover Image URL 생성
# ──────────────────────────────────────────────
def generate_cover_image_url(row: pd.Series, image_host: str, shop_code: str) -> str:
    """Cover Image URL 생성 (Parent SKU 우선)"""
    if not image_host or not shop_code:
        return ""

    if not image_host.endswith('/'):
        image_host += '/'

    parent_sku = str(row.get('PSKU', '') or '').strip()
    sku_for_url = parent_sku if parent_sku else str(row.get('SKU', '') or '').strip()

    return f"{image_host}{sku_for_url}_C_{shop_code}.jpg" if sku_for_url else ""


# ──────────────────────────────────────────────
# 데이터 병합 및 변환 (완전 해결 버전)
# ──────────────────────────────────────────────
def merge_and_convert_data(df_basic, df_sales, df_media, image_host, shop_code):
    """
    SKU 기반 통합 (automation_steps Step1 철학):
    - MEDIA를 기준으로 1행=1옵션(=1SKU) row를 생성
    - SALES에서 (PSKU, OptionName) → SKU 매핑
      (automation_steps도 (pid, normalized_option) → sku 로 매핑) :contentReference[oaicite:2]{index=2}
    - BASIC은 (PSKU → Product Name) 등 보조값으로만 사용
    - 최종 헤더 순서 고정:
      Category, PSKU, Product Name, Variation Name1, Option for Variation 1, Image per Variation,
      SKU, Cover image, Item Image 1..8
    """

    # -------------------------
    # 0) 기본 유틸
    # -------------------------
    def _norm_opt(s: str) -> str:
        s = (s or "").strip().lower()
        s = re.sub(r"\s+", " ", s)
        return s

    def _safe_get(row: pd.Series, col: str) -> str:
        if not col:
            return ""
        return str(row.get(col, "") or "").strip()

    def _col_by_key(df_cols, key: str, aliases=None):
        aliases = aliases or []
        return find_column_flexible(key, list(df_cols), aliases)

    def _fallback_by_index(df: pd.DataFrame, idx0: int) -> Optional[str]:
        # idx0: 0-based
        if df is None or df.empty:
            return None
        cols = list(df.columns)
        if 0 <= idx0 < len(cols):
            return cols[idx0]
        return None

    # -------------------------
    # 1) 필수 컬럼 탐색 (BASIC/SALES/MEDIA)
    # -------------------------

    # BASIC
    psku_basic = find_parent_sku_column(df_basic.columns)
    pname_basic = _col_by_key(df_basic.columns, "Product Name", ["Item Name", "Title", "ProductName", "Name"])

    # SALES
    psku_sales = find_parent_sku_column(df_sales.columns)
    sku_sales = find_child_sku_column(df_sales.columns, psku_sales or "")
    opt_sales = _col_by_key(
        df_sales.columns,
        "Option for Variation 1",
        ["Variation Name", "Variation Option", "Option Name", "Option 1 Name", "Option", "Variation"]
    )

    # MEDIA
    psku_media = find_parent_sku_column(df_media.columns)

    # Category는 "MEDIA D열"이라고 했으니, 우선 헤더명으로 찾고 실패하면 D(=index 3) fallback
    cat_media = _col_by_key(df_media.columns, "Category", ["Product Category", "Category Name"])
    if not cat_media:
        cat_media = _fallback_by_index(df_media, 3)  # D열

    # Product Name도 MEDIA에 있으면 쓰고, 없으면 BASIC에서 보조
    pname_media = _col_by_key(df_media.columns, "Product Name", ["ProductName", "Item Name", "ItemName", "Name"])

    # Variation Name1은 "MEDIA P열"이라고 했으니, 우선 헤더명으로 찾고 실패하면 P(=index 15) fallback
    vname_media = _col_by_key(df_media.columns, "Variation Name1", ["Variation Name", "Variation", "VariationName1"])
    if not vname_media:
        vname_media = _fallback_by_index(df_media, 15)  # P열

    # MEDIA가 "행 단위(Option for Variation 1 / Image per Variation)" 구조인지 먼저 확인
    opt1_media_row = _col_by_key(
        df_media.columns,
        "Option for Variation 1",
        ["Option 1 Name", "Option Name", "Variation Option", "Option"]
    )
    imgvar_media_row = _col_by_key(
        df_media.columns,
        "Image per Variation",
        ["Option 1 Image", "Option Image", "Image Per Variation", "Variation Image"]
    )

    # MEDIA가 "Option1 Name / Option1 Image ... OptionN Name / OptionN Image" 다열 구조인지 탐지
    # automation_steps는 option(\d+)name / option(\d+)image 패턴으로 찾음 :contentReference[oaicite:3]{index=3}
    keys = {c: header_key(str(c)) for c in df_media.columns}
    optN_name_cols = {}  # n -> colname
    optN_img_cols = {}   # n -> colname
    for col, k in keys.items():
        m = re.match(r"^option(\d+)name$", k)
        if m:
            optN_name_cols[int(m.group(1))] = col
        m2 = re.match(r"^option(\d+)image$", k)
        if m2:
            optN_img_cols[int(m2.group(1))] = col

    # Item Image 1~8 (MEDIA에서 찾기)
    item_img_cols = {}
    for i in range(1, 9):
        # header_key("Item Image 1") -> "itemimage1" 같은 형태
        target_k = header_key(f"Item Image {i}")
        found = None
        for col, k in keys.items():
            if k == target_k or k.startswith(target_k):  # 느슨하게 허용
                found = col
                break
        if not found:
            # 부분 매칭(혹시 "ps_item_image1" 같은 형태)
            for col, k in keys.items():
                if "itemimage" in k and k.endswith(str(i)):
                    found = col
                    break
        if found:
            item_img_cols[i] = found

    # -------------------------
    # 2) 필수 컬럼 검증 (최소 기준)
    # -------------------------
    missing = []
    if not psku_media: missing.append("MEDIA: Parent SKU(PSKU)")
    if not cat_media: missing.append("MEDIA: Category (또는 D열)")
    # 옵션 구조는 2가지 중 하나라도 있어야 함
    if not opt1_media_row and not optN_name_cols:
        missing.append("MEDIA: Option 컬럼 (Option for Variation 1 또는 OptionN Name 구조)")
    if not psku_sales: missing.append("SALES: Parent SKU(PSKU)")
    if not sku_sales: missing.append("SALES: Child SKU(SKU)")
    if not opt_sales:
        # 옵션 매칭이 SKU 매핑 핵심이라 SALES의 옵션 컬럼이 없으면 매칭 불가
        missing.append("SALES: Option/Variation Name 컬럼 (옵션명)")

    if missing:
        with st.expander("🔍 컬럼 탐색 디버깅", expanded=True):
            st.write("BASIC columns:", list(df_basic.columns))
            st.write("SALES columns:", list(df_sales.columns))
            st.write("MEDIA columns:", list(df_media.columns))
        raise ValueError("필수 컬럼 누락: " + ", ".join(missing))

    # -------------------------
    # 3) 표준 컬럼명으로 rename (필요한 것만)
    # -------------------------
    b = df_basic.copy()
    s = df_sales.copy()
    mdf = df_media.copy()

    b.rename(columns={psku_basic: "PSKU"} if psku_basic else {}, inplace=True)
    if pname_basic:
        b.rename(columns={pname_basic: "Product Name"}, inplace=True)

    s.rename(columns={psku_sales: "PSKU", sku_sales: "SKU", opt_sales: "_OPT_RAW"}, inplace=True)

    m_ren = {psku_media: "PSKU"}
    if cat_media: m_ren[cat_media] = "Category"
    if pname_media: m_ren[pname_media] = "Product Name"
    if vname_media: m_ren[vname_media] = "Variation Name1"
    if opt1_media_row: m_ren[opt1_media_row] = "Option for Variation 1"
    if imgvar_media_row: m_ren[imgvar_media_row] = "Image per Variation"
    for i, col in item_img_cols.items():
        m_ren[col] = f"Item Image {i}"
    mdf.rename(columns=m_ren, inplace=True)

    # PSKU forward fill (MEDIA만)
    # SALES에 ffill 적용하면 데이터 오염 가능성이 커서, 여기서는 MEDIA에만 제한적으로 적용
    mdf["PSKU"] = mdf["PSKU"].replace(r"^\s*$", pd.NA, regex=True).ffill().astype(str).str.strip()

    # -------------------------
    # 4) SALES: (PSKU, normalized_option) → SKU 매핑 테이블 생성
    # -------------------------
    s["_OPT_NORM"] = s["_OPT_RAW"].astype(str).map(_norm_opt)
    s["PSKU"] = s["PSKU"].astype(str).str.strip()
    s["SKU"] = s["SKU"].astype(str).str.strip()

    sku_map = {}  # (psku, opt_norm) -> sku
    for _, row in s.iterrows():
        psku = str(row.get("PSKU", "") or "").strip()
        optn = str(row.get("_OPT_NORM", "") or "").strip()
        sku = str(row.get("SKU", "") or "").strip()
        if psku and optn and sku:
            sku_map[(psku, optn)] = sku

    # BASIC: PSKU -> Product Name 보조 맵
    pname_map = {}
    if "PSKU" in b.columns:
        b["PSKU"] = b["PSKU"].astype(str).str.strip()
        if "Product Name" in b.columns:
            for _, row in b.iterrows():
                psku = str(row.get("PSKU", "") or "").strip()
                pn = str(row.get("Product Name", "") or "").strip()
                if psku and pn and psku not in pname_map:
                    pname_map[psku] = pn

    # -------------------------
    # 5) MEDIA를 중심으로 1행=1옵션 row 생성
    # -------------------------
    out_rows = []

    # (A) MEDIA가 "다열 옵션(OptionN Name/Image)" 구조면 explode
    use_multi_opt = bool(optN_name_cols)

    # 안전: 정렬된 option index 순서
    opt_indices = sorted(optN_name_cols.keys()) if use_multi_opt else []

    for _, r in mdf.iterrows():
        psku = str(r.get("PSKU", "") or "").strip()
        if not psku:
            continue

        category = str(r.get("Category", "") or "").strip()
        # Product Name: MEDIA 우선, 없으면 BASIC map
        pname = str(r.get("Product Name", "") or "").strip()
        if not pname:
            pname = pname_map.get(psku, "")

        vname1 = str(r.get("Variation Name1", "") or "").strip()
        # 템플릿에 option/options 같은 쓰레기 들어오면 비우기 (기존 코드 의도 유지)
        if vname1.lower() in ["option", "options"]:
            vname1 = ""

        # 공통 Item Images 1~8
        item_images = {f"Item Image {i}": str(r.get(f"Item Image {i}", "") or "").strip() for i in range(1, 9)}

        if use_multi_opt:
            # option1name/option1image... 구조
            for n in opt_indices:
                name_col = optN_name_cols.get(n)
                img_col = optN_img_cols.get(n)

                opt_name = str(r.get(name_col, "") or "").strip() if name_col else ""
                if not opt_name:
                    continue
                opt_img = str(r.get(img_col, "") or "").strip() if img_col else ""

                opt_norm = _norm_opt(opt_name)
                sku = sku_map.get((psku, opt_norm), "")

                out_rows.append({
                    "Category": category,
                    "PSKU": psku,
                    "Product Name": pname,
                    "Variation Name1": vname1,
                    "Option for Variation 1": opt_name,
                    "Image per Variation": opt_img,
                    "SKU": sku,
                    **item_images,
                })
        else:
            # (B) 행 단위 Option for Variation 1 / Image per Variation 구조
            opt_name = str(r.get("Option for Variation 1", "") or "").strip()
            if not opt_name:
                # 옵션이 없는(단품)도 허용: SKU 매칭은 빈칸으로 둘 수 있음
                out_rows.append({
                    "Category": category,
                    "PSKU": psku,
                    "Product Name": pname,
                    "Variation Name1": vname1,
                    "Option for Variation 1": "",
                    "Image per Variation": str(r.get("Image per Variation", "") or "").strip(),
                    "SKU": "",
                    **item_images,
                })
            else:
                opt_img = str(r.get("Image per Variation", "") or "").strip()
                opt_norm = _norm_opt(opt_name)
                sku = sku_map.get((psku, opt_norm), "")
                out_rows.append({
                    "Category": category,
                    "PSKU": psku,
                    "Product Name": pname,
                    "Variation Name1": vname1,
                    "Option for Variation 1": opt_name,
                    "Image per Variation": opt_img,
                    "SKU": sku,
                    **item_images,
                })

    if not out_rows:
        raise ValueError("MEDIA 기반으로 생성된 행이 없습니다. (PSKU/Category/Option 구조를 확인하세요)")

    final_df = pd.DataFrame(out_rows)

    # -------------------------
    # 6) Cover image 생성 + Category 정리
    # -------------------------
    final_df["Cover image"] = final_df.apply(
        lambda row: generate_cover_image_url(row, image_host, shop_code),
        axis=1
    )

    if "Category" in final_df.columns:
        final_df["Category"] = final_df["Category"].astype(str).str.replace(
            r"^\s*\d+\s*-\s*", "", regex=True
        ).replace("nan", "")

    # -------------------------
    # 7) 최종 헤더 순서 고정
    # -------------------------
    final_columns = [
        "Category",
        "PSKU",
        "Product Name",
        "Variation Name1",
        "Option for Variation 1",
        "Image per Variation",
        "SKU",
        "Cover image",
        "Item Image 1",
        "Item Image 2",
        "Item Image 3",
        "Item Image 4",
        "Item Image 5",
        "Item Image 6",
        "Item Image 7",
        "Item Image 8",
    ]

    for c in final_columns:
        if c not in final_df.columns:
            final_df[c] = ""

    final_df = final_df[final_columns].fillna("")

    # -------------------------
    # 8) 디버그(원하면 유지)
    # -------------------------
    with st.expander("🔍 SKU 기반 매핑 요약", expanded=False):
        st.write(f"- SALES SKU map size: {len(sku_map):,} (key=(PSKU, option_norm))")
        st.write(f"- BASIC Product Name map size: {len(pname_map):,}")
        st.write(f"- MEDIA 옵션 구조: {'OptionN(다열) explode' if use_multi_opt else '행 단위 option'}")
        # SKU 매칭 성공률 간단 지표
        if "SKU" in final_df.columns:
            matched = (final_df["SKU"].astype(str).str.strip() != "").sum()
            st.write(f"- SKU 매칭 성공: {matched:,} / {len(final_df):,}")

    return final_df



# ──────────────────────────────────────────────
# 엑셀 생성
# ──────────────────────────────────────────────
def create_excel_file(final_df: pd.DataFrame) -> io.BytesIO:
    """단일 탭 엑셀 파일 생성"""
    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        final_df.to_excel(writer, index=False, sheet_name='Shopee_Upload')

        workbook = writer.book
        worksheet = writer.sheets['Shopee_Upload']

        header_format = workbook.add_format({
            'bold': True, 'bg_color': '#4472C4', 'font_color': 'white',
            'border': 1, 'align': 'center', 'valign': 'vcenter'
        })

        for col_num, value in enumerate(final_df.columns.values):
            worksheet.write(0, col_num, value, header_format)
            max_len = max(final_df[value].astype(str).map(len).max(), len(value)) + 2
            worksheet.set_column(col_num, col_num, min(max_len, 50))

        worksheet.freeze_panes(1, 0)

    buffer.seek(0)
    return buffer


# ──────────────────────────────────────────────
# 메인 UI
# ──────────────────────────────────────────────
current_host = resolve_export_host()

if current_host:
    st.success(f"✅ **이미지 호스팅 URL:** `{current_host}`")
else:
    st.error("❌ **이미지 호스팅 URL 미설정** (좌측 사이드바에서 설정)")

st.subheader("📁 파일 및 설정")
col_upload, col_shop = st.columns([3, 1])

with col_upload:
    uploaded_files = st.file_uploader(
        "BASIC, MEDIA, SALES 파일 선택",
        type=['xlsx', 'xls', 'csv'],
        accept_multiple_files=True
    )

with col_shop:
    shop_code = st.text_input(
        "샵 코드 (필수)",
        placeholder="예: RO",
        help="Cover Image URL 생성용"
    )

if uploaded_files:
    basic_file, media_file, sales_file = classify_files(uploaded_files)

    st.subheader("📋 파일 분류 결과")
    col1, col2, col3 = st.columns(3)

    with col1:
        if basic_file:
            st.success(f"✅ **BASIC**\n`{basic_file.name}`")
        else:
            st.error("❌ **BASIC** 파일 없음")

    with col2:
        if media_file:
            st.success(f"✅ **MEDIA**\n`{media_file.name}`")
        else:
            st.error("❌ **MEDIA** 파일 없음")

    with col3:
        if sales_file:
            st.success(f"✅ **SALES**\n`{sales_file.name}`")
        else:
            st.error("❌ **SALES** 파일 없음")

    all_ready = all([basic_file, media_file, sales_file, shop_code, current_host])

    if st.button("🚀 통합 엑셀 생성", type="primary", disabled=not all_ready, use_container_width=True):
        try:
            with st.spinner("데이터 병합 및 엑셀 생성 중..."):
                df_basic = load_local_file_safe(basic_file)
                df_sales = load_local_file_safe(sales_file)
                df_media = load_local_file_safe(media_file)

                if df_basic.empty or df_sales.empty or df_media.empty:
                    st.error("❌ 파일 로드 실패. 파일 형식을 확인해주세요.")
                    st.stop()

                final_df = merge_and_convert_data(
                    df_basic, df_sales, df_media,
                    current_host, shop_code
                )

                st.success(f"✅ **완료!** 총 {len(final_df):,}개 행 생성")

                st.subheader("📊 결과 미리보기")
                st.dataframe(final_df.head(10), use_container_width=True)

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("총 행 수", f"{len(final_df):,}")
                with col2:
                    unique_psku = final_df['PSKU'].nunique()
                    st.metric("고유 상품", f"{unique_psku:,}")
                with col3:
                    unique_sku = final_df['SKU'].nunique()
                    st.metric("고유 SKU", f"{unique_sku:,}")
                with col4:
                    has_cover = (final_df['Cover image'] != '').sum()
                    st.metric("Cover Image", f"{has_cover:,}")

                buffer = create_excel_file(final_df)
                filename = f"Shopee_Upload_{shop_code}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"

                st.download_button(
                    label=f"📥 {filename} 다운로드",
                    data=buffer,
                    file_name=filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    use_container_width=True
                )

        except Exception as e:
            st.error(f"❌ **오류 발생:** {str(e)}")
            with st.expander("🔍 상세 오류 정보"):
                import traceback

                st.code(traceback.format_exc())
