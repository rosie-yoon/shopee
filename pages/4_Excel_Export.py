# -*- coding: utf-8 -*-
"""
Page 4: 통합 엑셀 생성기 (최적화 버전)
BASIC/MEDIA/SALES 파일을 한 번에 업로드하여 Shopee 업로드용 엑셀 생성
- 일괄 파일 업로드 및 자동 분류
- 사이드바 이미지 호스팅 URL 자동 적용
- Cover Image 규칙: 기존 Step 6과 동일 (PSKU 우선 → SKU)
- 단일 탭 출력
"""

from pathlib import Path
import sys
import io
from datetime import datetime
from typing import List, Optional, Tuple

import streamlit as st
import pandas as pd

st.set_page_config(page_title="Excel Export", layout="wide")

# 프로젝트 루트 경로 추가
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from auth_guard import bootstrap_auth
from user_manager import get_user_pref
from profile_sidebar import render_profile_sidebar
from item_uploader.utils_common import get_env, header_key

bootstrap_auth(go_home=False)

st.title("📊 통합 엑셀 생성기")
st.caption("BASIC/MEDIA/SALES 파일을 한 번에 업로드하여 Shopee 업로드용 엑셀을 생성합니다")
st.markdown("---")

# ──────────────────────────────────────────────
# 사이드바 설정
# ──────────────────────────────────────────────
render_profile_sidebar(
    sheet_key="export_sheet_id",
    host_key="export_image_host",
    sheet_label="데이터 시트 URL (미사용)",
    host_label="Image Hosting URL (필수)",
)


def resolve_export_host() -> str:
    """프로필 → 세션 → 환경 순서로 Image Host 탐색"""
    host = (
            get_user_pref("export_image_host")
            or get_user_pref("copy_image_host")
            or get_user_pref("image_host")
    )
    if host:
        return host.strip()

    host = st.session_state.get("IMAGE_HOSTING_URL")
    if host:
        return host.strip()

    return get_env("IMAGE_HOSTING_URL") or ""


# ──────────────────────────────────────────────
# 파일 분류 및 처리 함수
# ──────────────────────────────────────────────
def _target_tab(filename: str) -> Optional[str]:
    """
    기존 item_uploader.upload_apply와 동일한 규칙으로 파일 분류
    파일명에 basic/media/sales 키워드 포함 여부로 판단
    """
    low = filename.lower()
    if "basic" in low:
        return "BASIC"
    if "media" in low:
        return "MEDIA"
    if "sales" in low:
        return "SALES"
    return None


def classify_files(uploaded_files) -> Tuple[Optional[any], Optional[any], Optional[any]]:
    """업로드된 파일들을 자동 분류하여 반환"""
    basic_file = None
    media_file = None
    sales_file = None

    for file in uploaded_files:
        file_type = _target_tab(file.name)
        if file_type == "BASIC":
            basic_file = file
        elif file_type == "MEDIA":
            media_file = file
        elif file_type == "SALES":
            sales_file = file

    return basic_file, media_file, sales_file


def load_local_file(file) -> pd.DataFrame:
    """업로드된 파일을 DataFrame으로 변환"""
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
# 데이터 병합 및 변환 로직
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
    기존 automation_steps.py Step 6과 동일한 Cover Image URL 생성 규칙

    우선순위:
    1. PSKU(Parent SKU) 우선 사용
    2. PSKU가 없으면 SKU 사용
    3. 형식: {host}{sku}_C_{shop_code}.jpg
    """
    if not image_host or not shop_code:
        return ""

    if not image_host.endswith('/'):
        image_host += '/'

    # Parent SKU 우선 규칙 (Step 6과 동일)
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
        image_host: str,
        shop_code: str
) -> pd.DataFrame:
    """
    3개 데이터프레임을 병합하고 Shopee 형식으로 변환

    병합 순서:
    1. SALES를 기준으로 BASIC과 MEDIA를 PSKU로 연결
    2. Cover Image는 Step 6 규칙으로 생성
    3. 기타 이미지는 호스팅 URL + 파일명으로 처리
    4. 최종 컬럼 순서 정렬
    """

    # 1. 필수 컬럼 검증 및 매핑
    psku_basic = find_column('PSKU', df_basic.columns) or find_column('Product ID', df_basic.columns)
    psku_sales = find_column('PSKU', df_sales.columns) or find_column('Parent SKU', df_sales.columns)
    psku_media = find_column('PSKU', df_media.columns) or find_column('Product ID', df_media.columns)
    sku_sales = find_column('SKU', df_sales.columns) or find_column('Seller SKU', df_sales.columns)

    if not all([psku_basic, psku_sales, psku_media, sku_sales]):
        missing = []
        if not psku_basic: missing.append("BASIC: PSKU/Product ID")
        if not psku_sales: missing.append("SALES: PSKU/Parent SKU")
        if not psku_media: missing.append("MEDIA: PSKU/Product ID")
        if not sku_sales: missing.append("SALES: SKU/Seller SKU")
        raise ValueError(f"필수 컬럼 누락:\n• " + "\n• ".join(missing))

    # 2. 컬럼명 통일 (병합 키)
    df_basic = df_basic.rename(columns={psku_basic: 'PSKU'})
    df_sales = df_sales.rename(columns={psku_sales: 'PSKU', sku_sales: 'SKU'})
    df_media = df_media.rename(columns={psku_media: 'PSKU'})

    # 3. 병합 실행 (Left Join)
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

        # Cover Image를 제외한 나머지 이미지 컬럼 처리
        image_cols = [col for col in merged_df.columns
                      if any(keyword in col.lower() for keyword in ['image', 'img'])
                      and 'cover' not in col.lower()]

        for col in image_cols:
            merged_df[col] = merged_df[col].apply(
                lambda x: f"{image_host}{x}"
                if pd.notna(x) and str(x).strip() and not str(x).startswith(("http://", "https://"))
                else x
            )

    # 5. 최종 컬럼 구성
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

    # 6. Cover Image URL 생성 (Step 6 규칙 적용)
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

# 현재 설정된 Image Host 표시
current_host = resolve_export_host()
if current_host:
    st.success(f"✅ **사용 중인 이미지 호스팅 URL:** `{current_host}`")
    st.caption("💡 설정 변경은 좌측 사이드바에서 가능합니다.")
else:
    st.error("❌ **이미지 호스팅 URL이 설정되지 않았습니다.**")
    st.warning("⚠️ 좌측 사이드바에서 'Image Hosting URL'을 설정한 후 '💾 설정 저장'을 클릭해주세요.")

st.subheader("📁 파일 및 설정")

col_upload, col_shop = st.columns([3, 1])

with col_upload:
    # 일괄 파일 업로드
    uploaded_files = st.file_uploader(
        "BASIC, MEDIA, SALES 파일을 모두 선택하세요",
        type=['xlsx', 'xls', 'csv'],
        accept_multiple_files=True,
        help="파일명에 basic/media/sales 키워드가 포함되어야 합니다.\n예: product_basic.xlsx, item_media.xlsx, sales_data.xlsx"
    )

with col_shop:
    # 샵 코드 입력
    shop_code = st.text_input(
        "샵 코드 (필수)",
        placeholder="예: RO, 01",
        help="Cover Image URL 생성에 사용됩니다\n형식: {SKU}_C_{샵코드}.jpg"
    )

# 파일 분류 및 상태 표시
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

    # 실행 조건 확인
    all_ready = all([basic_file, media_file, sales_file, shop_code, current_host])

    if not all_ready:
        missing = []
        if not basic_file: missing.append("BASIC 파일")
        if not media_file: missing.append("MEDIA 파일")
        if not sales_file: missing.append("SALES 파일")
        if not shop_code: missing.append("샵 코드")
        if not current_host: missing.append("이미지 호스팅 URL")

        st.warning(f"⚠️ **실행하려면 다음이 필요합니다:** {', '.join(missing)}")

    # 실행 버튼
    if st.button("🚀 통합 엑셀 생성", type="primary", disabled=not all_ready, use_container_width=True):
        try:
            with st.spinner("데이터를 병합하고 엑셀을 생성하는 중..."):
                # 데이터 로드
                df_basic = load_local_file(basic_file)
                df_sales = load_local_file(sales_file)
                df_media = load_local_file(media_file)

                # 병합 및 변환
                final_df = merge_and_convert_data(
                    df_basic, df_sales, df_media,
                    current_host, shop_code
                )

                st.success(f"✅ **병합 완료!** 총 {len(final_df):,}개 행이 생성되었습니다.")

                # 결과 미리보기
                st.subheader("📊 결과 미리보기")
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
                    st.metric("Cover Image 생성", f"{has_cover:,}")

                # 엑셀 다운로드
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
            st.error(f"❌ **처리 중 오류 발생:** {str(e)}")
            with st.expander("🔍 상세 오류 정보"):
                import traceback

                st.code(traceback.format_exc())

