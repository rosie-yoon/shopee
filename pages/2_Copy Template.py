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

# ✅ 로그인/프로필 사이드바
from user_manager import is_logged_in, get_user_pref
from profile_sidebar import render_profile_sidebar

# 내부 모듈 임포트
from item_uploader.app import run as item_uploader_run

# ✅ 접근 제한: 로그인 안 했으면 차단
if not is_logged_in():
    st.warning("로그인이 필요합니다. 먼저 로그인 페이지에서 사용자명을 입력해 주세요.")
    st.stop()

# ✅ 공통 프로필 사이드바 (여기서 사용자별 시트/호스팅 URL을 수정·저장 가능)
render_profile_sidebar()

# ✅ 로그인 사용자 프로필을 세션 기본값으로 주입
#    - item_uploader는 실행 시 이 값을 사용함
st.session_state.setdefault("GOOGLE_SHEETS_SPREADSHEET_ID", get_user_pref("sheet_id"))
st.session_state.setdefault("IMAGE_HOSTING_URL", get_user_pref("image_host"))

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
