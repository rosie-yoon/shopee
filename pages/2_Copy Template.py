# pages/2_Copy Template.py
from pathlib import Path
import sys
import streamlit as st

# ⚠️ set_page_config는 첫 호출 전에
st.set_page_config(page_title="Copy Template", layout="wide")

# ─────────────────────────────────────────────────────────────────────────────
# import path (로컬/Cloud 모두 호환)
# ─────────────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]   # .../shopee
PARENT = ROOT.parent                          # .../mount/src
for p in (ROOT, PARENT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# ─────────────────────────────────────────────────────────────────────────────
# 핵심 임포트 (심플 버전)  ← 여기만 정확히 정리하면 됨
# ─────────────────────────────────────────────────────────────────────────────
from user_manager import is_logged_in, get_user_pref, ensure_login_persistence
from profile_sidebar import render_profile_sidebar
from item_uploader.app import run as item_uploader_run

# ─────────────────────────────────────────────────────────────────────────────
# 접근 제한: 로그인 복원 → 가드
# ─────────────────────────────────────────────────────────────────────────────
ensure_login_persistence()   # URL의 ?user= 로 세션 복원
if not is_logged_in():
    st.warning("로그인이 필요합니다. 먼저 로그인해 주세요.")
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# 프로필 사이드바 (Copy 전용 키)
# ─────────────────────────────────────────────────────────────────────────────
render_profile_sidebar(sheet_key="copy_sheet_id", host_key="copy_image_host")

# 사용자 프로필 → 세션 기본값 주입 (item_uploader가 사용)
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

# ─────────────────────────────────────────────────────────────────────────────
# 메인 실행
# ─────────────────────────────────────────────────────────────────────────────
item_uploader_run()
