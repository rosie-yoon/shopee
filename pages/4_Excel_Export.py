# -*- coding: utf-8 -*-
"""
Page 4: 통합 엑셀 생성기 (Cover Image 규칙 적용 + 단일 탭)
BASIC/MEDIA/SALES 데이터를 병합하여 Shopee 업로드용 엑셀을 생성합니다.
"""

from pathlib import Path
import sys
import io
from datetime import datetime
from typing import List, Dict, Optional

import streamlit as st
import pandas as pd

st.set_page_config(page_title="Excel Export", layout="wide")

# 프로젝트 루트 경로 추가
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from auth_guard import bootstrap_auth
from user_manager import get_user_pref
from profile_sidebar import render_profile_sidebar, extract_sheet_id

# item_uploader 모듈에서 공통 유틸 import
from item_uploader.utils_common import (
    load_env, open_sheet_by_env, safe_worksheet,
    with_retry, get_env, header_key
)

bootstrap_auth(go_home=False)

st.title("📊 통합 엑셀 생성기")
st.caption("BASIC/MEDIA/SALES 데이터를 병합하여 Shopee 업로드용 엑셀을 생성합니다")
st.markdown("---")

# ──────────────────────────────────────────────
# 사이드바 설정
# ──────────────────────────────────────────────
render_profile_sidebar(
    sheet_key="export_sheet_id",
    host_key="export_image_host",
    sheet_label="데이터 시트 URL",
    host_label="Image Hosting URL",
)


def resolve_export_sid() -> str:
    """프로필 → 세션 → 환경 순서로 Sheet ID 탐색"""
    raw = (
            get_user_pref("export_sheet_id")
            or get_user_pref("copy_sheet_id")
            or get_user_pref("sheet_id")
    )
    if raw:
        sid = extract_sheet_id(str(raw))
        if sid:
            return sid

    sid = (st.session_state.get("GOOGLE_SHEETS_SPREADSHEET_ID") or "").strip()
    if sid:
        return sid

    raw = (
            get_env("GOOGLE_SHEETS_SPREADSHEET_ID")
            or get_env("GOOGLE_SHEET_KEY")
    )
    return extract_sheet_id(str(raw)) if raw else ""


def resolve_export_host() -> str:
    """프로필 → 세션 → 환경 순서로 Image Host 탐색"""
    host = (
            get_user_pref("export_image_host")
            or get_user_pref("copy_image_host")
            or get_user_pref("image_host")
    )
    if host:
        return host

    host = st.session_state.get("IMAGE_HOSTING_URL")
    if host:
        return host

    return get_env("IMAGE_HOSTING_URL") or ""


# ──────────────────────────────────────────────
# 데이터 로딩 함수
# ──────────────────────────────────────────────
@st.cache_data(show_spinner=False, ttl=300)
def load_sheet_data(spreadsheet_id: str, sheet_name: str) -> pd.DataFrame:
    """Google Sheets에서 데이터를 로드합니다."""
    try:
        load_env()
        import os
        os.environ["GOOGLE_SHEETS_SPREADSHEET_ID"] = spreadsheet_id

        sh = open_sheet_by_env()
        ws = safe_worksheet(sh, sheet_name)
        data = with_retry(lambda: ws.get_all_values())

        if not data:
            return pd.DataFrame()

        # 첫 행을 헤더로 사용
        df = pd.DataFrame(data[1:], columns=data[0])
        return df

    except Exception as e:
        st.error(f"시트 로드 실패 ({sheet_name}): {str(e)}")
        return pd.DataFrame()


def load_local_file(file) -> pd.DataFrame:
    """업로드된 파일을 DataFrame으로 변환합니다."""
    if file is None:
        return pd.DataFrame()

    try:
        if file.name.endswith('.csv'):
            return pd.read_csv(file)
        else:
            return pd.read_excel(file)
    except Exception as e:
        st.error(f"파일 로드 실패 ({file.name}): {str(e)}")
        return pd.DataFrame()


# ──────────────────────────────────────────────
# 컬럼 매핑 및 병합 로직
# ──────────────────────────────────────────────
def find_column(target: str, df_columns: List[str]) -> Optional[str]:
    """header_key 함수를 사용한 지능형 컬럼 매칭"""
    target_key = header_key(target)
    for col in df_columns:
        if header_key(col) == target_key:
            return col
    return None


def generate_cover_image_url(row: pd.Series, image_host: str, shop_code: str) -> str:
    """
    기존 automation_steps.py의 Step 6 로직과 동일하게 Cover Image URL 생성

    규칙:
    1. Parent SKU가 있으면 우선 사용
    2. 없으면 SKU 사용
    3. 형식: {host}{sku}_C_{shop_code}.jpg
    """
    if not image_host or not shop_code:
        return ""

    if not image_host.endswith('/'):
        image_host += '/'

    # Parent SKU 우선, 없으면 SKU 사용 (Step 6 로직과 동일)
    psku = str(row.get('PSKU', '') or '').strip()
    sku = str(row.get('SKU', '') or '').strip()

    sku_for_url = psku if psku else sku

    if sku_for_url:
        return f"{image_host}{sku_for_url}_C_{shop_code}.jpg"

    return ""


def merge_and_convert_data(
        df_basic: pd.DataFrame,
        df_sales: pd.DataFrame,
        df_media: pd.DataFrame,
        image_host: str = "",
        shop_code: str = ""
) -> pd.DataFrame:
    """
    3개 데이터프레임을 병합하고 Shopee 형식으로 변환합니다.

    병합 로직:
    1. SALES를 기준으로 BASIC과 MEDIA를 PSKU로 연결
    2. Cover Image URL은 Step 6 로직과 동일하게 생성
    3. 기타 이미지 URL 자동 생성
    4. Shopee 업로드 형식에 맞게 컬럼 순서 정렬
    """

    # 1. 필수 컬럼 검증 및 정규화
    psku_basic = find_column('PSKU', df_basic.columns) or find_column('Product ID', df_basic.columns)
    psku_sales = find_column('PSKU', df_sales.columns) or find_column('Parent SKU', df_sales.columns)
    psku_media = find_column('PSKU', df_media.columns) or find_column('Product ID', df_media.columns)
    sku_sales = find_column('SKU', df_sales.columns) or find_column('Seller SKU', df_sales.columns)

    if not all([psku_basic, psku_sales, psku_media, sku_sales]):
        missing = []
        if not psku_basic: missing.append("BASIC에서 PSKU/Product ID")
        if not psku_sales: missing.append("SALES에서 PSKU/Parent SKU")
        if not psku_media: missing.append("MEDIA에서 PSKU/Product ID")
        if not sku_sales: missing.append("SALES에서 SKU/Seller SKU")
        raise ValueError(f"필수 컬럼 누락: {', '.join(missing)}")

    # 2. 컬럼명 통일 (병합 키)
    df_basic = df_basic.rename(columns={psku_basic: 'PSKU'})
    df_sales = df_sales.rename(columns={psku_sales: 'PSKU', sku_sales: 'SKU'})
    df_media = df_media.rename(columns={psku_media: 'PSKU'})

    # 3. Sales 기준 병합 (Left Join)
    try:
        # Sales + Basic
        merged_df = pd.merge(
            df_sales,
            df_basic,
            on='PSKU',
            how='left',
            suffixes=('', '_basic')
        )

        # + Media
        merged_df = pd.merge(
            merged_df,
            df_media,
            on='PSKU',
            how='left',
            suffixes=('', '_media')
        )

    except Exception as e:
        raise ValueError(f"데이터 병합 실패: {str(e)}")

    # 4. 이미지 URL 처리 (Cover Image 제외)
    if image_host:
        if not image_host.endswith('/'):
            image_host += '/'

        # Cover Image를 제외한 나머지 이미지 컬럼만 처리
        image_cols = [col for col in merged_df.columns
                      if any(keyword in col.lower() for keyword in ['image', 'img'])
                      and 'cover' not in col.lower()]

        for col in image_cols:
            merged_df[col] = merged_df[col].apply(
                lambda x: f"{image_host}{x}" if pd.notna(x) and str(x).strip() and not str(x).startswith("http") else x
            )

    # 5. 최종 컬럼 순서 정리
    target_columns = [
        "Category", "PSKU", "Product Name", "Variation Name1",
        "Option for Variation 1", "Image per Variation", "SKU",
        "Cover image", "Item Image 1", "Item Image 2", "Item Image 3",
        "Item Image 4", "Item Image 5", "Item Image 6", "Item Image 7", "Item Image 8"
    ]

    final_df = pd.DataFrame()
    for target_col in target_columns:
        source_col = find_column(target_col, merged_df.columns)
        if source_col and target_col != "Cover image":  # Cover image는 별도 생성
            final_df[target_col] = merged_df[source_col]
        else:
            final_df[target_col] = ""

    # 6. Cover Image URL 생성 (Step 6 로직 적용)
    final_df['Cover image'] = final_df.apply(
        lambda row: generate_cover_image_url(row, image_host, shop_code),
        axis=1
    )

    # 7. 카테고리 숫자 코드 제거
    if 'Category' in final_df.columns:
        final_df['Category'] = final_df['Category'].str.replace(
            r'^\s*\d+\s*-\s*', '', regex=True
        )

    return final_df


# ──────────────────────────────────────────────
# 엑셀 생성 함수 (단일 탭)
# ──────────────────────────────────────────────
def create_excel_file(final_df: pd.DataFrame) -> io.BytesIO:
    """단일 탭 'Shopee_Upload' 엑셀 파일 생성"""
    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        final_df.to_excel(writer, index=False, sheet_name='Shopee_Upload')

        # 워크시트 포맷팅
        workbook = writer.book
        worksheet = writer.sheets['Shopee_Upload']

        # 헤더 포맷
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#4472C4',
            'font_color': 'white',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter'
        })

        # 헤더 행 포맷 적용
        for col_num, value in enumerate(final_df.columns.values):
            worksheet.write(0, col_num, value, header_format)

        # 컬럼 너비 자동 조정
        for i, col in enumerate(final_df.columns):
            max_len = max(
                final_df[col].astype(str).map(len).max(),
                len(col)
            ) + 2
            worksheet.set_column(i, i, min(max_len, 50))

        # 첫 행 고정
        worksheet.freeze_panes(1, 0)

    buffer.seek(0)
    return buffer


# ──────────────────────────────────────────────
# 메인 UI
# ──────────────────────────────────────────────
tab1, tab2 = st.tabs(["📂 로컬 파일 업로드", "☁️ Google Sheets"])

# Tab 1: 로컬 파일 업로드
with tab1:
    st.subheader("📁 파일 업로드")
    col1, col2, col3 = st.columns(3)

    with col1:
        basic_file = st.file_uploader("BASIC 파일", type=['xlsx', 'xls', 'csv'], key="basic")
    with col2:
        sales_file = st.file_uploader("SALES 파일", type=['xlsx', 'xls', 'csv'], key="sales")
    with col3:
        media_file = st.file_uploader("MEDIA 파일", type=['xlsx', 'xls', 'csv'], key="media")

    col_a, col_b = st.columns(2)
    with col_a:
        host = st.text_input("이미지 호스팅 URL", value=resolve_export_host(), key="host_local")
    with col_b:
        shop_code = st.text_input(
            "샵 코드 (Cover Image용)",
            placeholder="예: RO, 01 등",
            help="Cover Image URL 생성에 사용됩니다 (필수)",
            key="shop_local"
        )

    if basic_file and sales_file and media_file and shop_code:
        if st.button("🚀 파일 병합 및 엑셀 생성", type="primary", key="btn_local"):
            try:
                with st.spinner("파일을 처리하는 중..."):
                    df_basic = load_local_file(basic_file)
                    df_sales = load_local_file(sales_file)
                    df_media = load_local_file(media_file)

                    final_df = merge_and_convert_data(
                        df_basic, df_sales, df_media,
                        host, shop_code
                    )

                    st.success(f"✅ 병합 완료! 총 {len(final_df)}개 행 생성")

                    # 결과 미리보기
                    st.subheader("📊 결과 미리보기 (상위 10개)")
                    st.dataframe(final_df.head(10), use_container_width=True)

                    # 통계 정보
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("총 행 수", f"{len(final_df):,}")
                    with col2:
                        unique_psku = final_df['PSKU'].nunique()
                        st.metric("고유 상품 수", f"{unique_psku:,}")
                    with col3:
                        unique_sku = final_df['SKU'].nunique()
                        st.metric("고유 SKU 수", f"{unique_sku:,}")
                    with col4:
                        has_cover = (final_df['Cover image'] != '').sum()
                        st.metric("Cover Image", f"{has_cover:,}")

                    # 엑셀 다운로드 (단일 탭)
                    buffer = create_excel_file(final_df)

                    date_str = datetime.now().strftime("%Y%m%d_%H%M")
                    filename = f"Shopee_Upload_{shop_code}_{date_str}.xlsx"

                    st.download_button(
                        label=f"📥 {filename} 다운로드",
                        data=buffer,
                        file_name=filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        type="primary",
                        use_container_width=True
                    )

            except Exception as e:
                st.error(f"❌ 처리 중 오류 발생: {str(e)}")
    elif basic_file and sales_file and media_file:
        st.warning("⚠️ 샵 코드를 입력해주세요. Cover Image 생성에 필요합니다.")

# Tab 2: Google Sheets
with tab2:
    sid = resolve_export_sid()

    if not sid:
        st.warning("⚠️ Google Sheets ID가 설정되지 않았습니다. 사이드바에서 설정해주세요.")
    else:
        with st.sidebar:
            st.caption(f"사용 중인 Sheet ID: `{sid}`")

        st.subheader("📋 시트 이름 설정")
        col1, col2, col3 = st.columns(3)

        with col1:
            basic_sheet = st.text_input("BASIC 시트명", value="BASIC")
        with col2:
            sales_sheet = st.text_input("SALES 시트명", value="SALES")
        with col3:
            media_sheet = st.text_input("MEDIA 시트명", value="MEDIA")

        col_a, col_b = st.columns(2)
        with col_a:
            host_gs = st.text_input("이미지 호스팅 URL", value=resolve_export_host(), key="host_gs")
        with col_b:
            shop_code_gs = st.text_input(
                "샵 코드 (Cover Image용)",
                placeholder="예: RO, 01 등",
                help="Cover Image URL 생성에 사용됩니다 (필수)",
                key="shop_gs"
            )

        if shop_code_gs and st.button("📥 시트 데이터 로드 및 병합", type="primary", key="btn_gs"):
            try:
                with st.spinner("Google Sheets에서 데이터를 불러오는 중..."):
                    df_basic = load_sheet_data(sid, basic_sheet)
                    df_sales = load_sheet_data(sid, sales_sheet)
                    df_media = load_sheet_data(sid, media_sheet)

                    if df_basic.empty or df_sales.empty or df_media.empty:
                        st.error("❌ 일부 시트를 불러올 수 없습니다.")
                    else:
                        final_df = merge_and_convert_data(
                            df_basic, df_sales, df_media,
                            host_gs, shop_code_gs
                        )

                        st.success(f"✅ 병합 완료! 총 {len(final_df)}개 행 생성")

                        # 결과 미리보기 및 다운로드 (로컬과 동일한 로직)
                        st.subheader("📊 결과 미리보기 (상위 10개)")
                        st.dataframe(final_df.head(10), use_container_width=True)

                        # 엑셀 다운로드
                        buffer = create_excel_file(final_df)

                        date_str = datetime.now().strftime("%Y%m%d_%H%M")
                        filename = f"Shopee_Upload_GS_{shop_code_gs}_{date_str}.xlsx"

                        st.download_button(
                            label=f"📥 {filename} 다운로드",
                            data=buffer,
                            file_name=filename,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            type="primary",
                            use_container_width=True
                        )

            except Exception as e:
                st.error(f"❌ Google Sheets 처리 중 오류 발생: {str(e)}")
        elif not shop_code_gs:
            st.warning("⚠️ 샵 코드를 입력해주세요. Cover Image 생성에 필요합니다.")

