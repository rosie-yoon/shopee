# pages/2_Copy Template.py
# -*- coding: utf-8 -*-

# 1) 표준 라이브러리
from pathlib import Path
import sys
import os

# 2) Streamlit 설정
import streamlit as st
st.set_page_config(page_title="Copy Template", layout="wide")

# 3) 프로젝트 루트 경로 보정
ROOT = Path(__file__).resolve().parents[1]   # .../shopee
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

# 4) 내부 모듈 import
from auth_guard import bootstrap_auth, current_user
from user_manager import get_user_pref
from profile_sidebar import render_profile_sidebar
from item_uploader.app import run as item_uploader_run

# 5) 인증 부트스트랩
bootstrap_auth(go_home=False)

# 6) 페이지 본문
st.title("Copy Template")
st.caption("3종 템플릿 복사/업로드")

# 프로필 사이드바 (Copy 전용 키)
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

# 실행 전 env 동기화 → 실행
def _sync_env_from_session():
    sid = st.session_state.get("GOOGLE_SHEETS_SPREADSHEET_ID", "")
    host = st.session_state.get("IMAGE_HOSTING_URL", "")
    if sid:
        os.environ["GOOGLE_SHEETS_SPREADSHEET_ID"] = sid
        os.environ["GOOGLE_SHEET_KEY"] = sid  # 별칭 키 대비
    if host:
        os.environ["IMAGE_HOSTING_URL"] = host

_sync_env_from_session()
item_uploader_run()
