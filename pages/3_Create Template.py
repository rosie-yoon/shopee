# pages/3_Create Template.py
# -*- coding: utf-8 -*-

import streamlit as st
from pathlib import Path
import sys
import io
import time
from contextlib import redirect_stdout
import traceback

# ──────────────────────────────────────────────────────────────────────────────
# Page config & import path
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Create Template", layout="wide")

ROOT = Path(__file__).resolve().parents[1]  # .../shopee
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 프로젝트 모듈
from shopee_creator.controller import ShopeeCreator
from shopee_creator.utils_creator import extract_sheet_id, get_env
import shopee_creator.creation_steps as steps
from shopee_creator.creation_steps import export_tem_xlsx  # XLSX만 사용

# ──────────────────────────────────────────────────────────────────────────────
# Sidebar: 설정 폼 (URL/이미지 호스팅만)
# ──────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("⚙️ 초기 설정")

    cur_source_sid = st.session_state.get("SOURCE_SPREADSHEET_ID", get_env("SOURCE_SPREADSHEET_ID", ""))
    cur_img_host  = st.session_state.get("IMAGE_BASE_URL",      get_env("IMAGE_BASE_URL", ""))

    with st.form("settings_form_create_template"):
        source_url = st.text_input(
            "상품등록 시트 URL",
            value=(f"https://docs.google.com/spreadsheets/d/{cur_source_sid}" if cur_source_sid else ""),
            placeholder="https://docs.google.com/spreadsheets/d/...",
        )
        image_host = st.text_input(
            "Image Hosting URL",
            value=cur_img_host or "",
            placeholder="예: https://example.com/",
        )
        submitted = st.form_submit_button("저장")
        if submitted:
            sid = extract_sheet_id(source_url)
            if not sid:
                st.error("올바른 Google Sheets URL을 입력해주세요.")
            elif image_host and not image_host.startswith(("http://", "https://")):
                st.error("이미지 호스팅 주소를 확인해주세요. (http/https)")
            else:
                st.session_state["SOURCE_SPREADSHEET_ID"] = sid
                st.session_state["IMAGE_BASE_URL"]       = image_host
                # Shop Code는 본문에서 입력하므로 초기화
                st.session_state.pop("SHOP_CODE", None)
                st.success("설정이 저장되었습니다!")
                st.rerun()

        st.write("")  

        st.markdown(
            """
        * [상품등록 시트 템플릿](https://docs.google.com/spreadsheets/d/1MP4kpazAQkvGI7Ew31jthKnwjs8WZP0kWhyLPUpTgJA/edit?gid=0#gid=0)의 사본을 생성하여 위 구글 시트 URL 란에 입력해주세요.  
        * 사본 생성 시, 시트의 안내사항을 꼭 확인해주세요.
        """
        )



# 다운로드 바이트 세션 기본값 (XLSX만)
st.session_state.setdefault("DL_XLSX", None)

# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────
st.title("Create Template")
st.markdown("---")
st.subheader("1. 파일 및 샵 코드 입력")

sid = st.session_state.get("SOURCE_SPREADSHEET_ID", "")
base_url = st.session_state.get("IMAGE_BASE_URL", "")

shop_code_input = st.text_input(
    "샵 코드 입력",
    value=st.session_state.get("SHOP_CODE", ""),
    placeholder="예: RO, 01 등 커버 이미지 코드와 동일하게 입력하세요.",
)

run_enabled = bool(sid and shop_code_input.strip())
run_clicked = st.button("🚀 실행", type="primary", use_container_width=True, disabled=not run_enabled)

# ──────────────────────────────────────────────────────────────────────────────
# 실행: 프로그레스바 방식(표/로그 X), 단계별 직접 호출(C1→C2→C7→C3→C4→C5→C6)
# ──────────────────────────────────────────────────────────────────────────────
if run_clicked:
    shop_code = shop_code_input.strip()
    st.session_state["SHOP_CODE"] = shop_code  # 최신 반영

    # 컨트롤러 / gspread 클라이언트 준비 (한 번만)
    ctrl = ShopeeCreator(st.secrets)
    if base_url or shop_code:
        try:
            ctrl.set_image_base(base_url=base_url, shop_code=shop_code)
        except Exception:
            pass

    # 입력 시트/레퍼런스 시트 Open (open_by_key로 1회씩만)
    try:
        gs = ctrl.gs
        sh  = gs.open_by_key(sid)
    except Exception as e:
        st.error(f"입력 시트 열기 실패: {e}")
        st.stop()

    # Ref URL/ID 읽기 (secrets: REFERENCE_SPREADSHEET_ID or URL)
    ref_id_or_url = st.secrets.get("REFERENCE_SPREADSHEET_ID") or st.secrets.get("REFERENCE_SPREADSHEET_URL") or ""
    try:
        rid = extract_sheet_id(str(ref_id_or_url))
        ref = gs.open_by_key(rid)
    except Exception as e:
        st.error(f"레퍼런스 시트 열기 실패: secrets에 REFERENCE_SPREADSHEET_ID/URL을 확인하세요.\n\nError: {e}")
        st.stop()

    # 프로그레스바
    progress = st.progress(0.0, text="시작합니다…")

    # 단계 정의
    run_list = [
        ("C1 Initialize",             lambda: steps.run_step_C1(sh, ref)),
        ("C2 Collection → TEM",       lambda: steps.run_step_C2(sh, ref)),
        ("C7 Mandatory Defaults",     lambda: steps.run_step_C7_mandatory_defaults(sh, ref)),
        ("C3 FDA",                    lambda: steps.run_step_C3_fda(sh, ref)),
        ("C4 Prices",                 lambda: steps.run_step_C4_prices(sh)),
        ("C5 Images",                 lambda: steps.run_step_C5_images(sh=sh, base_url=base_url, shop_code=shop_code)),
        ("C6 Stock/Weight/Brand",     lambda: steps.run_step_C6_stock_weight_brand(sh)),
    ]

    total = len(run_list)
    ok = True

    for i, (name, fn) in enumerate(run_list, start=1):
        try:
            progress.progress((i-1)/total, text=f"{name} 실행 중…")
            # 내부 print 로그는 캡처만 하고 화면엔 출력하지 않음
            buf = io.StringIO()
            with redirect_stdout(buf):
                fn()
            # 약간의 슬립으로 API 피크 완화(429 방지 도움)
            time.sleep(0.2)
            progress.progress(i/total, text=f"{name} 완료")
        except Exception:
            progress.progress((i-1)/total, text=f"{name} 실패")
            # 개발용 디버깅을 위해서는 아래 주석 해제 가능
            # st.code(buf.getvalue())
            st.error(f"실행 실패: {name} 단계에서 오류가 발생했습니다.")
            # 상세 오류는 Expander로만 노출(원하면 제거 가능)
            with st.expander("자세한 오류", expanded=False):
                st.code(traceback.format_exc())
            ok = False
            break

    if ok:
        progress.progress(1.0, text="모든 단계 완료")
        st.success("모든 단계가 정상 완료되었습니다! 🎉")

        # 실행 직후 바로 내보내기 파일 생성 → 세션 저장 (버튼 즉시 활성화)
        try:
            xio = export_tem_xlsx(sh)  # BytesIO or None
            if xio:
                st.session_state["DL_XLSX"] = xio.getvalue()
            else:
                st.session_state["DL_XLSX"] = None
                st.warning("엑셀 내보내기 생성에 실패했습니다. TEM_OUTPUT 시트를 확인해 주세요.")
        except Exception as ex:
            st.session_state["DL_XLSX"] = None
            st.warning(f"다운로드 생성 중 오류: {ex}")

# ──────────────────────────────────────────────────────────────────────────────
# 2. 최종 파일 다운로드 (항상 표시: 준비되면 자동 활성화)
# ──────────────────────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("2. 최종 파일 다운로드")

file_base = (st.session_state.get("SHOP_CODE") or "TEM") + "_TEM_OUTPUT"
xlsx_bytes = st.session_state.get("DL_XLSX")

st.download_button(
    "📥 템플릿 파일 다운로드 (.xlsx)",
    data=(xlsx_bytes or b""),
    file_name=f"{file_base}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
    disabled=not bool(xlsx_bytes),
)
