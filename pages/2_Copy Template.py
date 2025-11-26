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
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

# 4) 내부 모듈 import
from auth_guard import bootstrap_auth
from user_manager import get_user_pref
from profile_sidebar import render_profile_sidebar, extract_sheet_id
from item_uploader.app import run as item_uploader_run
from shopee_creator.utils_creator import get_env

# 5) 인증 부트스트랩
bootstrap_auth(go_home=False)

# 6) 페이지 본문
st.title("Copy Template")
st.caption("3종 템플릿 복사/업로드")
st.markdown("---")

# 사이드바 (Copy 전용)
render_profile_sidebar(
    sheet_key="copy_sheet_id",
    host_key="copy_image_host",
    sheet_label="BASIC/MEDIA/SALES 시트 URL",
    host_label="Image Hosting URL",
)

# ──────────────────────────────────────────────
# Helper — 프로필 우선 로더
# ──────────────────────────────────────────────
def resolve_copy_sid() -> str:
    # 1) 프로필 최우선
    raw = (
        get_user_pref("copy_sheet_id")
        or get_user_pref("sheet_id")
    )
    if raw:
        sid = extract_sheet_id(str(raw))
        if sid:
            return sid

    # 2) 세션 값 (뒤로)
    sid = (st.session_state.get("GOOGLE_SHEETS_SPREADSHEET_ID") or "").strip()
    if sid:
        return sid

    # 3) 환경 / secrets-safe
    raw = (
        get_env("GOOGLE_SHEETS_SPREADSHEET_ID")
        or get_env("GOOGLE_SHEET_KEY")
    )
    sid = extract_sheet_id(str(raw)) if raw else ""
    return sid or ""

def resolve_copy_host() -> str:
    # 1) 프로필 우선
    host = (
        get_user_pref("copy_image_host")
        or get_user_pref("image_host")
        or get_user_pref("default_image_host")
    )
    if host:
        return host

    # 2) 세션
    host = st.session_state.get("IMAGE_HOSTING_URL")
    if host:
        return host

    # 3) 환경
    return get_env("IMAGE_HOSTING_URL") or ""

# ──────────────────────────────────────────────
# Resolve final values
# ──────────────────────────────────────────────
sid = resolve_copy_sid()
host = resolve_copy_host()

# 환경(Step1) + 세션(Step2) 동기화
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
    st.caption(f"사용 중인 Copy Template Sheet ID: `{sid}`")

# ──────────────────────────────────────────────
# 메인 실행
# ──────────────────────────────────────────────
item_uploader_run()
