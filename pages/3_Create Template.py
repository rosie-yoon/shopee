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

# ✅ 경로 설정 (Cloud 호환)
ROOT = Path(__file__).resolve().parents[1]  # .../shopee
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PARENT = ROOT.parent  # /mount/src
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

# ✅ 프로필 사이드바 임포트 (Cloud 폴백 포함)
try:
    from profile_sidebar import render_profile_sidebar
except ModuleNotFoundError:
    try:
        from shopee.profile_sidebar import render_profile_sidebar
    except Exception as e:
        st.error(f"profile_sidebar 임포트 실패: {e}")
        st.stop()

# ✅ 로그인 유틸
from user_manager import is_logged_in, get_user_pref

# ──────────────────────────────────────────────────────────────────────────────
# 프로젝트 모듈
# ──────────────────────────────────────────────────────────────────────────────
from shopee_creator.controller import ShopeeCreator
from shopee_creator.utils_creator import extract_sheet_id, get_env
import shopee_creator.creation_steps as steps
from shopee_creator.creation_steps import export_tem_xlsx  # XLSX만 사용

# ──────────────────────────────────────────────────────────────────────────────
# 접근 제한 & 프로필 사이드바 / 사용자 프로필 → 세션 기본값
# ──────────────────────────────────────────────────────────────────────────────
if not is_logged_in():
    st.warning("로그인이 필요합니다. 먼저 사용자명을 입력해 로그인해 주세요.")
    st.stop()

# ✅ 공통 프로필 사이드바 (Create 전용 키로 저장/로드)
#  - users.json 예시: create_sheet_id / create_image_host
render_profile_sidebar(
    sheet_key="create_sheet_id",
    host_key="create_image_host",
    sheet_label="상품등록 시트 URL",
    host_label="Image Hosting URL",
)

# ✅ 로그인 사용자 프로필 → 세션 매핑
st.session_state.setdefault(
    "SOURCE_SPREADSHEET_ID",
    get_user_pref("create_sheet_id") or get_user_pref("sheet_id")
)
st.session_state.setdefault(
    "IMAGE_BASE_URL",
    get_user_pref("create_image_host") or get_user_pref("image_host") or get_user_pref("default_image_host")
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
# 실행: 단계별 호출 (C1→C2→C7→C3→C4→C5→C6)
# ──────────────────────────────────────────────────────────────────────────────
if run_clicked:
    shop_code = shop_code_input.strip()
    st.session_state["SHOP_CODE"] = shop_code

    ctrl = ShopeeCreator(st.secrets)
    if base_url or shop_code:
        try:
            ctrl.set_image_base(base_url=base_url, shop_code=shop_code)
        except Exception:
            pass

    # 입력 시트 오픈
    try:
        gs = ctrl.gs
        sh = gs.open_by_key(sid)
    except Exception as e:
        st.error(f"입력 시트 열기 실패: {e}")
        st.stop()

    # 레퍼런스 시트 열기
    ref_id_or_url = st.secrets.get("REFERENCE_SPREADSHEET_ID") or st.secrets.get("REFERENCE_SPREADSHEET_URL") or ""
    try:
        rid = extract_sheet_id(str(ref_id_or_url))
        ref = gs.open_by_key(rid)
    except Exception as e:
        st.error(f"레퍼런스 시트 열기 실패: secrets에 REFERENCE_SPREADSHEET_ID/URL을 확인하세요.\n\nError: {e}")
        st.stop()

    # 프로그레스바
    progress = st.progress(0.0, text="시작합니다…")

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
            buf = io.StringIO()
            with redirect_stdout(buf):
                fn()
            time.sleep(0.2)
            progress.progress(i/total, text=f"{name} 완료")
        except Exception:
            progress.progress((i-1)/total, text=f"{name} 실패")
            st.error(f"실행 실패: {name} 단계에서 오류가 발생했습니다.")
            with st.expander("자세한 오류", expanded=False):
                st.code(traceback.format_exc())
            ok = False
            break

    if ok:
        progress.progress(1.0, text="모든 단계 완료")
        st.success("모든 단계가 정상 완료되었습니다! 🎉")

        # 실행 직후 내보내기
        try:
            xio = export_tem_xlsx(sh)
            if xio:
                st.session_state["DL_XLSX"] = xio.getvalue()
            else:
                st.session_state["DL_XLSX"] = None
                st.warning("엑셀 내보내기 생성에 실패했습니다. TEM_OUTPUT 시트를 확인해 주세요.")
        except Exception as ex:
            st.session_state["DL_XLSX"] = None
            st.warning(f"다운로드 생성 중 오류: {ex}")

# ──────────────────────────────────────────────────────────────────────────────
# 2. 최종 파일 다운로드
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
