# pages/2_Copy Template.py
from pathlib import Path
import sys
import streamlit as st

# ⚠️ set_page_config는 첫 호출 전에
st.set_page_config(page_title="Copy Template", layout="wide")

# 프로젝트 루트(shopee)를 임포트 경로에 추가
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ✅ Streamlit Cloud 대비: 루트 상위(/mount/src)도 추가
PARENT = ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

# ✅ 프로필 사이드바 임포트 (안전 폴백 포함)
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

# 내부 모듈
from item_uploader.app import run as item_uploader_run

# ✅ 접근 제한: 로그인 안 했으면 차단
if not is_logged_in():
    st.warning("로그인이 필요합니다. 먼저 로그인해 주세요.")
    st.stop()

# ✅ 공통 프로필 사이드바 (Copy 전용 키로 저장/로드)
#    - users.json 예: copy_sheet_id / copy_image_host (없으면 기존 sheet_id/image_host로 폴백)
render_profile_sidebar(sheet_key="copy_sheet_id", host_key="copy_image_host")

# ✅ 사용자 프로필 → 세션 기본값 주입 (item_uploader가 사용)
st.session_state.setdefault(
    "GOOGLE_SHEETS_SPREADSHEET_ID",
    get_user_pref("copy_sheet_id") or get_user_pref("sheet_id")
)
st.session_state.setdefault(
    "IMAGE_HOSTING_URL",
    get_user_pref("copy_image_host") or get_user_pref("image_host") or get_user_pref("default_image_host")
)

# (선택) 안내 문구
with st.sidebar:
    st.write("")  # 한 줄 여백
    st.markdown(
        """
* [샵 복제 시트 템플릿](https://docs.google.com/spreadsheets/d/1l5DK-1lNGHFPfl7mbI6sTR_qU1cwHg2-tlBXzY2JhbI/edit?gid=0#gid=0)의 사본을 생성하여 위 Google Sheets URL에 입력해주세요.  
* 사본 생성 시, 시트의 안내사항을 꼭 확인해주세요.
        """
    )

# ==============================
# 메인 실행
# ==============================
item_uploader_run()
