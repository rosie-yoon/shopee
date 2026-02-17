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
    기존 SALES 기준 구조 유지 + 정밀 옵션 매칭 추가
    """

    # ========================================
    # 1. 컬럼 매핑 (위치 기반 폴백 포함)
    # ========================================
    def find_col_with_fallback(df_cols, targets, fallback_idx=None):
        # 헤더명 우선 매칭
        for target in targets:
            tgt_key = header_key(target)
            for col in df_cols:
                if header_key(str(col)) == tgt_key:
                    return col

        # 부분 매칭
        for target in targets:
            tgt_key = header_key(target)
            for col in df_cols:
                if tgt_key in header_key(str(col)):
                    return col

        # 위치 기반 폴백
        if fallback_idx is not None and 0 <= fallback_idx < len(df_cols):
            return df_cols[fallback_idx]
        return None

    # BASIC 매핑
    basic_psku = find_parent_sku_column(df_basic.columns)
    basic_name = find_column_flexible('Product Name', df_basic.columns, [
        'et_title_product_name', 'Item Name', 'Title'
    ])

    # SALES 매핑
    sales_psku = find_parent_sku_column(df_sales.columns)
    sales_sku = find_child_sku_column(df_sales.columns, sales_psku or "")
    sales_opt = find_col_with_fallback(df_sales.columns, [
        'Variation Name', 'Option Name', 'Option', 'Variation Option'
    ])

    # MEDIA 매핑 (핵심 수정)
    media_psku = find_parent_sku_column(df_media.columns)

    # Category: D열 폴백
    media_cat = find_col_with_fallback(df_media.columns, [
        'Category', 'et_title_category', 'Product Category'
    ], fallback_idx=3)

    # Variation Name1: P열 폴백
    media_var_name = find_col_with_fallback(df_media.columns, [
        'Variation Name1', 'Variation Name', 'et_title_variation_name'
    ], fallback_idx=15)

    media_opt_val = find_column_flexible('Option for Variation 1', df_media.columns, [
        'Variation Option', 'Option for Variation 1', 'Option'
    ])

    media_opt_img = find_column_flexible('Image per Variation', df_media.columns, [
        'Image per Variation', 'Variation Image', 'Option Image'
    ])

    # Item Images 매핑
    item_images_map = {}
    for i in range(1, 9):
        found = find_column_flexible(f'Item Image {i}', df_media.columns, [
            f'Item Image {i}', f'Image {i}', f'ps_item_image_url_{i}'
        ])
        if found:
            item_images_map[f'Item Image {i}'] = found

    # ========================================
    # 2. 디버깅 정보
    # ========================================
    with st.expander("🔍 수정된 컬럼 매핑 결과", expanded=True):
        st.write("### MEDIA 파일 매핑 (수정됨)")
        st.write(f"- **Category**: `{media_cat}` {'✅' if media_cat else '❌'}")
        st.write(f"- **Variation Name1**: `{media_var_name}` {'✅' if media_var_name else '❌'}")
        st.write(f"- **Option for Var 1**: `{media_opt_val}` {'✅' if media_opt_val else '❌'}")
        st.write(f"- **Image per Var**: `{media_opt_img}` {'✅' if media_opt_img else '❌'}")

        if media_cat and len(df_media.columns) > 3 and media_cat == df_media.columns[3]:
            st.info("📍 Category: D열 위치 기반 매핑 적용됨")
        if media_var_name and len(df_media.columns) > 15 and media_var_name == df_media.columns[15]:
            st.info("📍 Variation Name1: P열 위치 기반 매핑 적용됨")

    # ========================================
    # 3. SKU-옵션 매칭 딕셔너리 생성 (핵심 추가)
    # ========================================
    media_lookup = {}  # PSKU → {category, var_name, item_images}
    option_lookup = {}  # (PSKU, 정규화된_옵션) → 이미지_URL

    if media_psku:
        for _, row in df_media.iterrows():
            psku = str(row[media_psku]).strip()
            if not psku:
                continue

            # PSKU 레벨 정보 (Category, Variation Name1, Item Images)
            if psku not in media_lookup:
                cat = str(row[media_cat]).strip() if media_cat else ""
                var_name = str(row[media_var_name]).strip() if media_var_name else ""

                # Item Images 추출
                item_imgs = []
                for i in range(1, 9):
                    col = item_images_map.get(f'Item Image {i}')
                    img_url = str(row[col]).strip() if col else ""
                    item_imgs.append(img_url)

                media_lookup[psku] = {
                    "category": cat,
                    "var_name": var_name,
                    "item_images": item_imgs
                }

            # SKU 레벨 정보 (옵션별 이미지)
            if media_opt_val and media_opt_img:
                opt_val = str(row[media_opt_val]).strip()
                opt_img = str(row[media_opt_img]).strip()

                if opt_val:
                    # automation_steps_revised.py와 동일한 정규화
                    norm_key = re.sub(r'\s+', ' ', opt_val.lower())
                    option_lookup[(psku, norm_key)] = opt_img

    # ========================================
    # 4. 기존 병합 구조 유지 + 추가 매핑
    # ========================================
    # 컬럼명 표준화
    df_basic_clean = df_basic.copy()
    df_sales_clean = df_sales.copy()
    df_media_clean = df_media.copy()

    # Rename
    if basic_psku and basic_name:
        df_basic_clean.rename(columns={basic_psku: 'PSKU', basic_name: 'Product Name'}, inplace=True)
    if sales_psku and sales_sku:
        df_sales_clean.rename(columns={sales_psku: 'PSKU', sales_sku: 'SKU'}, inplace=True)

    # PSKU 전처리 (기존 로직 유지)
    for df in [df_basic_clean, df_sales_clean]:
        if 'PSKU' in df.columns:
            df['PSKU'] = df['PSKU'].replace(r'^\s*$', pd.NA, regex=True)
            df['PSKU'] = df['PSKU'].ffill()
            df['PSKU'] = df['PSKU'].astype(str).str.strip()

    # 기존 병합 (SALES 기준 유지)
    merged_df = pd.merge(df_sales_clean, df_basic_clean, on='PSKU', how='left', suffixes=('', '_basic'))

    # ========================================
    # 5. Lookup 기반 추가 매핑 (핵심 개선)
    # ========================================
    # 새 컬럼들 초기화
    merged_df['Category'] = ""
    merged_df['Variation Name1'] = ""
    merged_df['Option for Variation 1'] = ""
    merged_df['Image per Variation'] = ""

    for i in range(1, 9):
        merged_df[f'Item Image {i}'] = ""

    # SALES 옵션 컬럼 정보
    sales_opt_col = None
    if sales_opt and sales_opt in df_sales.columns:
        # 원본 컬럼명으로 접근
        sales_opt_col = sales_opt

    # 각 행에 대해 Lookup 매칭
    for idx, row in merged_df.iterrows():
        psku = str(row['PSKU']).strip()

        # PSKU 레벨 정보 매핑
        if psku in media_lookup:
            info = media_lookup[psku]
            merged_df.at[idx, 'Category'] = info['category']
            merged_df.at[idx, 'Variation Name1'] = info['var_name']

            # Item Images
            for i, img_url in enumerate(info['item_images'], 1):
                if i <= 8:
                    merged_df.at[idx, f'Item Image {i}'] = img_url

        # SKU 레벨 정보 매핑 (옵션별 이미지)
        if sales_opt_col:
            # 원본 SALES 데이터에서 옵션값 가져오기
            sales_row_idx = merged_df.index[merged_df.index == idx][0]
            original_sales_idx = sales_row_idx  # 인덱스가 유지된다고 가정

            # df_sales에서 해당 행의 옵션값 추출
            if original_sales_idx < len(df_sales):
                sales_opt_val = str(df_sales.iloc[original_sales_idx][sales_opt_col]).strip()
                merged_df.at[idx, 'Option for Variation 1'] = sales_opt_val

                # 정규화하여 이미지 매핑
                if sales_opt_val:
                    norm_key = re.sub(r'\s+', ' ', sales_opt_val.lower())
                    opt_img = option_lookup.get((psku, norm_key), "")
                    merged_df.at[idx, 'Image per Variation'] = opt_img

    # ========================================
    # 6. 최종 처리 (기존 로직 유지)
    # ========================================
    # 트래시 데이터 제거
    merged_df = merged_df[
        (merged_df['PSKU'].notna()) &
        (merged_df['PSKU'] != '') &
        (merged_df['PSKU'].str.lower() != 'parent sku')
        ].copy().reset_index(drop=True)

    # 최종 컬럼 구성
    target_columns = [
        "Category", "PSKU", "Product Name", "Variation Name1",
        "Option for Variation 1", "Image per Variation", "SKU",
        "Cover image", "Item Image 1", "Item Image 2", "Item Image 3",
        "Item Image 4", "Item Image 5", "Item Image 6", "Item Image 7", "Item Image 8"
    ]

    final_df = pd.DataFrame()
    for col in target_columns:
        if col == "Cover image":
            continue
        final_df[col] = merged_df.get(col, "")

    # Cover Image 생성
    final_df['Cover image'] = final_df.apply(
        lambda row: generate_cover_image_url(row, image_host, shop_code),
        axis=1
    )

    # 후처리
    if 'Category' in final_df.columns:
        final_df['Category'] = final_df['Category'].astype(str).str.replace(
            r'^\s*\d+\s*-\s*', '', regex=True
        ).replace('nan', '')

    return final_df.fillna('')


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
