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

# ==============================
# ENV 보장: 프로필/세션/시크릿 순으로 SID/Host 확정 → ENV 주입
# ==============================
from profile_sidebar import extract_sheet_id  # 중복 import면 이 줄은 생략하세요

def resolve_copy_sid() -> str:
    sid = (st.session_state.get("GOOGLE_SHEETS_SPREADSHEET_ID") or "").strip()
    if not sid:
        raw = get_user_pref("copy_sheet_id") or get_user_pref("sheet_id")
        sid = extract_sheet_id(str(raw)) if raw else ""
    if not sid:
        raw = st.secrets.get("GOOGLE_SHEETS_SPREADSHEET_ID") or st.secrets.get("GOOGLE_SHEET_KEY")
        sid = extract_sheet_id(str(raw)) if raw else ""
    return sid or ""

def resolve_copy_host() -> str:
    return (
        st.session_state.get("IMAGE_HOSTING_URL")
        or get_user_pref("copy_image_host")
        or get_user_pref("image_host")
        or get_user_pref("default_image_host")
        or ""
    )

sid = resolve_copy_sid()
host = resolve_copy_host()

# 주입 (+별칭) 및 세션 동기화
if sid:
    os.environ["GOOGLE_SHEETS_SPREADSHEET_ID"] = sid
    os.environ["GOOGLE_SHEET_KEY"] = sid
    st.session_state["GOOGLE_SHEETS_SPREADSHEET_ID"] = sid
else:
    with st.sidebar:
        st.warning("Google Sheets URL/ID가 설정되지 않았습니다. 사이드바에서 저장 후 다시 시도하세요.")
    st.stop()

if host:
    os.environ["IMAGE_HOSTING_URL"] = host
    st.session_state["IMAGE_HOSTING_URL"] = host

with st.sidebar:
    st.caption(f"사용 중인 Sheet ID: `{sid}`")

# ==============================
# 메인 실행
# ==============================
item_uploader_run()

