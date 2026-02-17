def generate_cover_image_url(row: pd.Series, image_host: str, shop_code: str) -> str:
    """Cover Image URL 생성 (PSKU 기준만 사용)"""
    if not image_host or not shop_code:
        return ""

    if not image_host.endswith('/'):
        image_host += '/'

    # PSKU만 사용 (SKU 폴백 제거)
    psku = str(row.get('PSKU', '') or '').strip()

    return f"{image_host}{psku}_C_{shop_code}.jpg" if psku else ""


def merge_and_convert_data(df_basic, df_sales, df_media, image_host, shop_code):
    """3개 데이터프레임 병합 및 Shopee 형식 변환 (6가지 문제점 해결 버전)"""

    # ========================================
    # 1. 강화된 컬럼 매칭 (별칭 대폭 확장)
    # ========================================

    # BASIC PSKU 매칭
    psku_basic = find_column_flexible('PSKU', df_basic.columns,
                                      ['et_title_product_id', 'Product ID', 'ProductID', 'Item ID', 'Parent SKU'])

    # BASIC Category 매칭 (문제 #1 해결)
    category_basic = find_column_flexible('Category', df_basic.columns,
                                          ['et_title_category', 'Product Category', 'Category Name',
                                           'Category ID', 'Global Category ID', 'Shopee Category Id', 'Cat ID'])

    # SALES PSKU 매칭 (Parent SKU 계열)
    psku_sales = find_column_flexible('PSKU', df_sales.columns,
                                      ['et_title_parent_sku', 'Parent SKU', 'ParentSKU', 'Product ID', 'Item ID'])

    # SALES SKU 매칭 (Child SKU 계열) - Parent와 명확히 구분
    sku_sales = None
    child_sku_candidates = [
        'et_title_child_sku', 'et_title_seller_sku', 'et_title_variation_sku',
        'Seller SKU', 'SellerSKU', 'Child SKU', 'ChildSKU', 'Variation SKU', 'Model SKU'
    ]

    for candidate in child_sku_candidates:
        found_col = find_column_flexible('SKU', df_sales.columns, [candidate])
        if found_col and found_col != psku_sales:
            sku_sales = found_col
            break

    if not sku_sales:
        for col in df_sales.columns:
            col_lower = str(col).lower()
            if 'sku' in col_lower and 'parent' not in col_lower and col != psku_sales:
                sku_sales = col
                break

    # SALES Variation 컬럼 매칭 (문제 #5 해결)
    variation_name_sales = find_column_flexible('Variation Name1', df_sales.columns,
                                                ['et_title_variation_name', 'Variation Name', 'Variation Name1',
                                                 'Model Name', 'Tier 1', 'Option Name'])

    variation_option_sales = find_column_flexible('Option for Variation 1', df_sales.columns,
                                                  ['et_title_variation_option', 'Variation Option',
                                                   'Option for Variation 1',
                                                   'Model Option', 'Tier 1 Option', 'Variation Value'])

    # MEDIA PSKU 매칭
    psku_media = find_column_flexible('PSKU', df_media.columns,
                                      ['et_title_product_id', 'Product ID', 'ProductID', 'Item ID'])

    # MEDIA Image per Variation 매칭 (문제 #5 해결)
    image_per_var_media = find_column_flexible('Image per Variation', df_media.columns,
                                               ['et_title_variation_image', 'Variation Image', 'Image per Variation',
                                                'Option Image', 'Model Image'])

    # ========================================
    # 2. 상세 디버깅 정보
    # ========================================
    with st.expander("🔍 컬럼 매칭 결과"):
        st.write("**BASIC 파일:**")
        st.write(f"- PSKU: `{psku_basic}`")
        st.write(f"- Category: `{category_basic}`")

        st.write("**SALES 파일:**")
        st.write(f"- PSKU: `{psku_sales}`")
        st.write(f"- SKU: `{sku_sales}`")
        st.write(f"- Variation Name1: `{variation_name_sales}`")
        st.write(f"- Option for Variation 1: `{variation_option_sales}`")

        st.write("**MEDIA 파일:**")
        st.write(f"- PSKU: `{psku_media}`")
        st.write(f"- Image per Variation: `{image_per_var_media}`")

        # 중복 매칭 경고
        if psku_sales == sku_sales:
            st.error("⚠️ **치명적 오류**: PSKU와 SKU가 같은 컬럼을 가리킵니다!")
            st.write("SALES 파일의 전체 컬럼 목록:")
            st.write(list(df_sales.columns))

    # ========================================
    # 3. 필수 컬럼 검증
    # ========================================
    missing = []
    if not psku_basic: missing.append("BASIC: PSKU/Product ID 계열 컬럼")
    if not psku_sales: missing.append("SALES: PSKU/Parent SKU 계열 컬럼")
    if not sku_sales: missing.append("SALES: SKU/Child SKU 계열 컬럼")
    if not psku_media: missing.append("MEDIA: PSKU/Product ID 계열 컬럼")

    if psku_sales == sku_sales:
        missing.append(f"SALES: PSKU와 SKU가 동일한 컬럼({psku_sales})을 가리킵니다.")

    if missing:
        raise ValueError("컬럼 매칭 실패:\n• " + "\n• ".join(missing))

    # ========================================
    # 4. DataFrame 복사 및 컬럼명 변경
    # ========================================
    df_basic = df_basic.copy()
    df_sales = df_sales.copy()
    df_media = df_media.copy()

    # BASIC 컬럼명 변경
    rename_basic = {psku_basic: 'PSKU'}
    if category_basic:
        rename_basic[category_basic] = 'Category'
    df_basic = df_basic.rename(columns=rename_basic)

    # SALES 컬럼명 변경
    rename_sales = {}
    if psku_sales: rename_sales[psku_sales] = 'PSKU'
    if sku_sales and sku_sales != psku_sales: rename_sales[sku_sales] = 'SKU'
    if variation_name_sales: rename_sales[variation_name_sales] = 'Variation Name1'
    if variation_option_sales: rename_sales[variation_option_sales] = 'Option for Variation 1'
    df_sales = df_sales.rename(columns=rename_sales)

    # MEDIA 컬럼명 변경
    rename_media = {psku_media: 'PSKU'}
    if image_per_var_media:
        rename_media[image_per_var_media] = 'Image per Variation'
    df_media = df_media.rename(columns=rename_media)

    # ========================================
    # 5. PSKU 반복 입력 처리 (문제 #2 해결)
    # ========================================
    # 빈 문자열과 공백을 NaN으로 변환 후 forward fill
    for df in [df_basic, df_sales, df_media]:
        if 'PSKU' in df.columns:
            df['PSKU'] = df['PSKU'].replace(r'^\s*$', pd.NA, regex=True)
            df['PSKU'] = df['PSKU'].ffill()  # pandas 최신 버전 호환
            df['PSKU'] = df['PSKU'].astype(str).str.strip()

    # ========================================
    # 6. 데이터 타입 통일
    # ========================================
    for df in [df_basic, df_sales, df_media]:
        if 'SKU' in df.columns:
            df['SKU'] = df['SKU'].astype(str).str.strip()

    # ========================================
    # 7. 병합 실행 (SALES 기준)
    # ========================================
    try:
        # SALES를 기준으로 병합 (Variation 단위이므로)
        merged_df = pd.merge(df_sales, df_basic, on='PSKU', how='left', suffixes=('', '_basic'))
        merged_df = pd.merge(merged_df, df_media, on='PSKU', how='left', suffixes=('', '_media'))
    except Exception as e:
        raise ValueError(f"데이터 병합 실패: {str(e)}")

    # ========================================
    # 8. 트래시 데이터 제거 (문제 #6 해결)
    # ========================================
    # PSKU가 없거나 헤더 텍스트인 행 제거
    merged_df = merged_df[
        (merged_df['PSKU'].notna()) &
        (merged_df['PSKU'] != '') &
        (merged_df['PSKU'].str.lower() != 'psku') &
        (merged_df['PSKU'].str.lower() != 'parent sku') &
        (merged_df['PSKU'].str.lower() != 'product id')
        ].copy()

    # SKU가 없는 행도 제거 (추가 안전장치)
    if 'SKU' in merged_df.columns:
        merged_df = merged_df[
            (merged_df['SKU'].notna()) &
            (merged_df['SKU'] != '') &
            (merged_df['SKU'].str.lower() != 'sku')
            ].copy()

    # 인덱스 리셋
    merged_df = merged_df.reset_index(drop=True)

    # ========================================
    # 9. Media 원본 데이터 보존 (문제 #4 해결)
    # ========================================
    # Cover Image를 제외한 모든 이미지는 원본 그대로 사용
    # 기존의 이미지 URL 가공 로직을 완전히 제거

    # ========================================
    # 10. 최종 컬럼 구성
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
            # Cover image는 나중에 별도 생성
            final_df[target_col] = ""
        elif target_col in merged_df.columns:
            # 직접 매칭되는 컬럼 사용
            final_df[target_col] = merged_df[target_col]
        else:
            # 유연한 매칭 시도
            source_col = find_column_flexible(target_col, merged_df.columns)
            if source_col:
                final_df[target_col] = merged_df[source_col]
            else:
                final_df[target_col] = ""

    # ========================================
    # 11. Cover Image URL 생성 (문제 #3 해결)
    # ========================================
    final_df['Cover image'] = final_df.apply(
        lambda row: generate_cover_image_url(row, image_host, shop_code),
        axis=1
    )

    # ========================================
    # 12. 카테고리 숫자 코드 제거
    # ========================================
    if 'Category' in final_df.columns:
        final_df['Category'] = final_df['Category'].astype(str).str.replace(
            r'^\s*\d+\s*-\s*', '', regex=True
        ).replace('nan', '').replace('', '')

    # ========================================
    # 13. 최종 데이터 정리
    # ========================================
    final_df = final_df.fillna('')
    final_df = final_df.reset_index(drop=True)

    return final_df
