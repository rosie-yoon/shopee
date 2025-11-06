# pages/1_Cover Image.py
import streamlit as st
from pathlib import Path
import sys

# pages/ 아래에 있으므로 프로젝트 루트(shopee)를 sys.path에 추가 (견고성 ↑)
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

# ✅ 로그인/프로필 사이드바/유틸
from user_manager import is_logged_in, get_user_pref
from profile_sidebar import render_profile_sidebar

# 기존 이미지 합성 앱 (폴더명이 image_compose 여야 함)
from image_compose.app import run as image_compose_run  # 그대로 유지

# ⚠️ set_page_config는 첫 Streamlit 호출 전에 선언
st.set_page_config(page_title="Cover Image", layout="wide")

# ✅ 접근 제한: 로그인 안 했으면 차단
if not is_logged_in():
    st.warning("로그인이 필요합니다. 먼저 로그인 페이지에서 사용자명을 입력해 주세요.")
    st.stop()

# ✅ 공통 프로필 사이드바 (사용자가 여기서 시트/호스팅 URL 수정 → 저장)
render_profile_sidebar()

# ✅ 로그인 사용자 프로필을 세션 기본값으로 주입
#    - 이후 image_compose 내부나 자동화 로직에서 세션/ENV를 참조할 때 바로 반영됨
st.session_state.setdefault("GOOGLE_SHEETS_SPREADSHEET_ID", get_user_pref("sheet_id"))
st.session_state.setdefault("IMAGE_HOSTING_URL", get_user_pref("image_host"))

# 실제 페이지 실행
image_compose_run()
