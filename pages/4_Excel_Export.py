# -*- coding: utf-8 -*-
"""
Page 4: 통합 엑셀 생성기 (완전 해결 버전)
- ImportError 해결: user_manager 의존성 제거
- Shopee 파일 호환성: XML sanitization으로 freezePanes 오류 완전 해결
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
from user_manager import get_user_pref  # save_user_pref 제거 (ImportError 방지)
from item_uploader.utils_common import get_env, header_key

bootstrap_auth(go_home=False)

st.title("📊 통합 엑셀 생성기")
st.caption("BASIC/MEDIA/SALES 파일을 한 번에 업로드하여 Shopee 업로드용 엑셀을 생성합니다")
st.markdown("---")


# ──────────────────────────────────────────────
# 핵심 해결책: Shopee 엑셀 파일 Sanitizer
# ──────────────────────────────────────────────
def sanitize_shopee_excel(file_obj) -> io.BytesIO:
    """
    Shopee 엑셀 파일의 freezePanes 오류를 해결하기 위해
    내부 XML에서 문제가 되는 sheetViews 태그를 제거합니다.
    """
    try:
        file_obj.seek(0)
        content = file_obj.read()

        # ZIP 파일로 엑셀 내부 구조 접근
        zin = zipfile.ZipFile(io.BytesIO(content), 'r')
        out_buffer = io.BytesIO()
        zout = zipfile.ZipFile(out_buffer, 'w', zipfile.ZIP_DEFLATED)

        # 문제가 되는 XML 태그 제거 패턴
        sheetviews_pattern = re.compile(r'<sheetViews[^>]*>.*?</sheetViews>', re.DOTALL)
        pane_pattern = re.compile(r'<pane[^>]*/?>', re.DOTALL)

        for item in zin.infolist():
            data = zin.read(item.filename)

            # worksheet XML 파일에서만 sanitization 실행
            if item.filename.startswith('xl/worksheets/sheet') and item.filename.endswith('.xml'):
                xml_str = data.decode('utf-8', errors='ignore')
                # 문제 태그 제거
                xml_str = sheetviews_pattern.sub('', xml_str)
                xml_str = pane_pattern.sub('', xml_str)
                data = xml_str.encode('utf-8')

            zout.writestr(item, data)

        zout.close()
        out_buffer.seek(0)
        return out_buffer

    except Exception as e:
        # 실패 시 원본 반환
        print(f"Sanitize failed: {e}")
        file_obj.seek(0)
        return file_obj


# ──────────────────────────────────────────────
# 사이드바 설정 (직접 구현 - ImportError 방지)
# ──────────────────────────────────────────────
with st.sidebar:
    st.subheader("⚙️ 설정")

    current_host = (
            get_user_pref("export_image_host")
            or get_user_pref("copy_image_host")
            or get_user_pref("image_host")
            or get_env("IMAGE_HOSTING_URL")
            or ""
    )

    host_input = st.text_input(
        "Image Hosting URL (필수)",
        value=current_host,
        placeholder="https://example.com/images/",
        help="Cover Image URL 생성에 사용됩니다"
    )

    if st.button("💾 설정 저장", use_container_width=True):
        if host_input.strip():
            # 세션에 직접 저장 (save_user_pref 의존성 제거)
            if "user_prefs" not in st.session_state:
                st.session_state["user_prefs"] = {}
            st.session_state["user_prefs"]["export_image_host"] = host_input.strip()
            st.success("✅ 저장 완료")
            st.rerun()
        else:
            st.warning("⚠️ URL을 입력해주세요")

    if current_host:
        st.caption(f"현재 설정: `{current_host}`")


def resolve_export_host() -> str:
    """저장된 이미지 호스팅 URL 불러오기"""
    # 세션 우선 확인
    if "user_prefs" in st.session_state:
        val = st.session_state["user_prefs"].get("export_image_host")
        if val:
            return val.strip()

    # 기존 설정 폴백
    return (
            get_user_pref("export_image_host")
            or get_user_pref("copy_image_host")
            or get_user_pref("image_host")
            or get_env("IMAGE_HOSTING_URL")
            or ""
    ).strip()


# ──────────────────────────────────────────────
# 안전한 파일 로더
# ──────────────────────────────────────────────
def find_header_row(df_preview: pd.DataFrame) -> int:
    """Shopee 파일에서 실제 헤더 행 찾기"""
    keywords = ['product', 'sku', 'category', 'variation', 'option', 'name', 'image']

    for i in range(min(10, len(df_preview))):
        row_text = ' '.join([str(val).lower() for val in df_preview.iloc[i].values if pd.notna(val)])
        match_count = sum(1 for kw in keywords if kw in row_text)
        if match_count >= 3:
            return i
    return 0


def load_local_file_safe(file) -> pd.DataFrame:
    """Shopee 파일 호환 로더 (Sanitization 적용)"""
    if file is None:
        return pd.DataFrame()

    try:
        # CSV 처리
        if file.name.endswith('.csv'):
            return pd.read_csv(file, dtype=str).fillna('')

        # Excel 처리 - Sanitization 적용
        file.seek(0)
        clean_file = sanitize_shopee_excel(file)

        try:
            # 헤더 위치 감지
            df_preview = pd.read_excel(clean_file, header=None, nrows=10, engine='openpyxl')
            header_row = find_header_row(df_preview)

            # 실제 데이터 로드
            clean_file.seek(0)
            df = pd.read_excel(clean_file, header=header_row, engine='openpyxl', dtype=str)
            return df.fillna('').dropna(how='all')

        except Exception:
            # 폴백: 기본 방식
            clean_file.seek(0)
            return pd.read_excel(clean_file, dtype=str, engine='openpyxl').fillna('')

    except Exception as e:
        st.error(f"파일 로드 실패 ({file.name}): {str(e)}")
        return pd.DataFrame()


# ──────────────────────────────────────────────
# 파일 분류 및 컬럼 매칭
# ──────────────────────────────────────────────
def classify_files(uploaded_files):
    """파일명 키워드로 자동 분류"""
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


def find_column_flexible(target: str, df_columns: List[str], aliases: List[str] = []) -> Optional[str]:
    """유연한 컬럼 검색"""
    target_key = header_key(target)

    # 정확 매칭
    for col in df_columns:
        if header_key(str(col)) == target_key:
            return col

    # 별칭 매칭
    for alias in aliases:
        alias_key = header_key(alias)
        for col in df_columns:
            if header_key(str(col)) == alias_key:
                return col

    # 부분 매칭
    for col in df_columns:
        col_key = header_key(str(col))
        if target_key in col_key or col_key in target_key:
            return col

    return None


# ──────────────────────────────────────────────
# 데이터 병합 및 변환
# ──────────────────────────────────────────────
def generate_cover_image_url(row: pd.Series, image_host: str, shop_code: str) -> str:
    """Cover Image URL 생성 (Step 6 규칙: PSKU 우선 → SKU)"""
    if not image_host or not shop_code:
        return ""

    if not image_host.endswith('/'):
        image_host += '/'

    psku = str(row.get('PSKU', '') or '').strip()
    sku = str(row.get('SKU', '') or '').strip()
    sku_for_url = psku if psku else sku

    return f"{image_host}{sku_for_url}_C_{shop_code}.jpg" if sku_for_url else ""


def merge_and_convert_data(df_basic, df_sales, df_media, image_host, shop_code):
    """3개 데이터프레임 병합 및 Shopee 형식 변환 (SKU 매칭 오류 수정)"""

    # ========================================
    # 1. 안전한 컬럼 매칭 (중복 방지 로직)
    # ========================================

    # BASIC PSKU 매칭
    psku_basic = find_column_flexible('PSKU', df_basic.columns,
                                      ['et_title_product_id', 'Product ID', 'ProductID', 'Item ID'])

    # SALES PSKU 매칭 (Parent SKU 계열)
    psku_sales = find_column_flexible('PSKU', df_sales.columns,
                                      ['et_title_parent_sku', 'Parent SKU', 'ParentSKU', 'Product ID'])

    # SALES SKU 매칭 (Child SKU 계열) - 핵심 수정
    sku_sales = None

    # Child SKU 우선 검색 (Parent와 명확히 구분)
    child_sku_candidates = [
        'et_title_child_sku', 'et_title_seller_sku', 'et_title_variation_sku',
        'Seller SKU', 'SellerSKU', 'Child SKU', 'ChildSKU', 'Variation SKU'
    ]

    for candidate in child_sku_candidates:
        found_col = find_column_flexible('SKU', df_sales.columns, [candidate])
        if found_col and found_col != psku_sales:  # Parent SKU와 다른지 확인
            sku_sales = found_col
            break

    # 여전히 못 찾았으면 'sku'가 포함된 컬럼 중 parent가 아닌 것 검색
    if not sku_sales:
        for col in df_sales.columns:
            col_lower = str(col).lower()
            if 'sku' in col_lower and 'parent' not in col_lower and col != psku_sales:
                sku_sales = col
                break

    # MEDIA PSKU 매칭
    psku_media = find_column_flexible('PSKU', df_media.columns,
                                      ['et_title_product_id', 'Product ID', 'ProductID', 'Item ID'])

    # ========================================
    # 2. 디버깅 정보 (개선된 버전)
    # ========================================
    with st.expander("🔍 컬럼 매칭 결과"):
        st.write("**BASIC PSKU:**", f"`{psku_basic}`")
        st.write("**SALES PSKU:**", f"`{psku_sales}`")
        st.write("**SALES SKU:**", f"`{sku_sales}`")
        st.write("**MEDIA PSKU:**", f"`{psku_media}`")

        # 중복 매칭 경고
        if psku_sales == sku_sales:
            st.error("⚠️ **치명적 오류**: PSKU와 SKU가 같은 컬럼을 가리킵니다!")
            st.write("SALES 파일의 전체 컬럼 목록:")
            st.write(list(df_sales.columns))

    # ========================================
    # 3. 필수 컬럼 검증 (강화)
    # ========================================
    missing = []
    if not psku_basic: missing.append("BASIC: PSKU/Product ID 계열 컬럼")
    if not psku_sales: missing.append("SALES: PSKU/Parent SKU 계열 컬럼")
    if not sku_sales: missing.append("SALES: SKU/Child SKU 계열 컬럼")
    if not psku_media: missing.append("MEDIA: PSKU/Product ID 계열 컬럼")

    # 중복 매칭 특별 처리
    if psku_sales == sku_sales:
        missing.append(f"SALES: PSKU와 SKU가 동일한 컬럼({psku_sales})을 가리킵니다. et_title_child_sku 컬럼이 있는지 확인하세요.")

    if missing:
        raise ValueError("컬럼 매칭 실패:\n• " + "\n• ".join(missing))

    # ========================================
    # 4. 안전한 컬럼명 변경 (DataFrame 복사 + 순차 처리)
    # ========================================
    df_basic = df_basic.copy()
    df_sales = df_sales.copy()
    df_media = df_media.copy()

    # 순차적 rename으로 충돌 방지
    df_basic = df_basic.rename(columns={psku_basic: 'PSKU'})
    df_media = df_media.rename(columns={psku_media: 'PSKU'})

    # SALES는 별도 처리 (PSKU → SKU 순서로)
    rename_map = {}
    if psku_sales: rename_map[psku_sales] = 'PSKU'
    if sku_sales and sku_sales != psku_sales: rename_map[sku_sales] = 'SKU'

    df_sales = df_sales.rename(columns=rename_map)

    # ========================================
    # 5. 병합 전 최종 검증
    # ========================================
    if 'PSKU' not in df_sales.columns:
        raise ValueError(f"SALES 파일에서 PSKU 컬럼 생성 실패. 원본 컬럼: {psku_sales}")
    if 'SKU' not in df_sales.columns:
        raise ValueError(f"SALES 파일에서 SKU 컬럼 생성 실패. 원본 컬럼: {sku_sales}")

    # ========================================
    # 6. 데이터 타입 통일
    # ========================================
    for df in [df_basic, df_sales, df_media]:
        if 'PSKU' in df.columns:
            df['PSKU'] = df['PSKU'].astype(str).str.strip()
        if 'SKU' in df.columns:
            df['SKU'] = df['SKU'].astype(str).str.strip()

    # ========================================
    # 7. 병합 실행
    # ========================================
    try:
        merged_df = pd.merge(df_sales, df_basic, on='PSKU', how='left', suffixes=('', '_basic'))
        merged_df = pd.merge(merged_df, df_media, on='PSKU', how='left', suffixes=('', '_media'))
    except Exception as e:
        raise ValueError(f"데이터 병합 실패: {str(e)}")

    # ========================================
    # 8. 이미지 URL 처리 (Cover Image 제외)
    # ========================================
    if image_host:
        if not image_host.endswith('/'):
            image_host += '/'

        image_cols = [col for col in merged_df.columns
                      if any(k in str(col).lower() for k in ['image', 'img'])
                      and 'cover' not in str(col).lower()]

        for col in image_cols:
            merged_df[col] = merged_df[col].apply(
                lambda x: f"{image_host}{x}"
                if pd.notna(x) and str(x).strip() and not str(x).startswith(("http", "https"))
                else str(x) if pd.notna(x) else ""
            )

    # ========================================
    # 9. 최종 컬럼 구성
    # ========================================
    target_columns = [
        "Category", "PSKU", "Product Name", "Variation Name1",
        "Option for Variation 1", "Image per Variation", "SKU",
        "Cover image", "Item Image 1", "Item Image 2", "Item Image 3",
        "Item Image 4", "Item Image 5", "Item Image 6", "Item Image 7", "Item Image 8"
    ]

    final_df = pd.DataFrame()
    for target_col in target_columns:
        if target_col == "Cover image":
            final_df[target_col] = ""
        else:
            source_col = find_column_flexible(target_col, merged_df.columns)
            final_df[target_col] = merged_df[source_col] if source_col else ""

    # ========================================
    # 10. Cover Image URL 생성
    # ========================================
    final_df['Cover image'] = final_df.apply(
        lambda row: generate_cover_image_url(row, image_host, shop_code),
        axis=1
    )

    # ========================================
    # 11. 카테고리 숫자 코드 제거
    # ========================================
    if 'Category' in final_df.columns:
        final_df['Category'] = final_df['Category'].astype(str).str.replace(
            r'^\s*\d+\s*-\s*', '', regex=True
        ).replace('nan', '')

    return final_df


# ──────────────────────────────────────────────
# 엑셀 생성 (단일 탭)
# ──────────────────────────────────────────────
def create_excel_file(final_df: pd.DataFrame) -> io.BytesIO:
    """단일 탭 'Shopee_Upload' 엑셀 파일 생성"""
    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        final_df.to_excel(writer, index=False, sheet_name='Shopee_Upload')

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

        # 헤더 행 적용
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
current_host = resolve_export_host()

if current_host:
    st.success(f"✅ **이미지 호스팅 URL:** `{current_host}`")
else:
    st.error("❌ **이미지 호스팅 URL이 설정되지 않았습니다.**")
    st.warning("👈 좌측 사이드바에서 URL을 설정해주세요.")

st.subheader("📁 파일 및 설정")

col_upload, col_shop = st.columns([3, 1])

with col_upload:
    uploaded_files = st.file_uploader(
        "BASIC, MEDIA, SALES 파일을 모두 선택하세요",
        type=['xlsx', 'xls', 'csv'],
        accept_multiple_files=True
    )

with col_shop:
    shop_code = st.text_input(
        "샵 코드 (필수)",
        placeholder="예: RO, 01",
        help="Cover Image URL 생성에 사용됩니다"
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
                # 안전한 파일 로드
                df_basic = load_local_file_safe(basic_file)
                df_sales = load_local_file_safe(sales_file)
                df_media = load_local_file_safe(media_file)

                if df_basic.empty or df_sales.empty or df_media.empty:
                    st.error("❌ 일부 파일을 읽을 수 없습니다. 파일 형식을 확인해주세요.")
                    st.stop()

                # 병합 및 변환
                final_df = merge_and_convert_data(
                    df_basic, df_sales, df_media,
                    current_host, shop_code
                )

                st.success(f"✅ **완료!** 총 {len(final_df):,}개 행이 생성되었습니다.")

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
