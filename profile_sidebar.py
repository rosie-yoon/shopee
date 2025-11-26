# profile_sidebar.py (Refactored Clean Version v2)
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path
import sys
import streamlit as st

# ─────────────────────────────────────────────────────────────
# Path Fix
# ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ─────────────────────────────────────────────────────────────
# Imports
# ─────────────────────────────────────────────────────────────
from user_manager import (
    is_logged_in,
    get_user_pref,
    update_user_profile,
)

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
_SPREAD_RE = re.compile(r"/spreadsheets/d/([A-Za-z0-9\-_]+)")

def extract_sheet_id(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    m = _SPREAD_RE.search(s)
    if m:
        return m.group(1)
    # 이미 ID만 들어온 경우
    if re.fullmatch(r"[A-Za-z0-9\-_]{25,}", s):
        return s
    return None

def sheet_link(sid: str | None) -> str:
    if not sid:
        return ""
    return f"https://docs.google.com/spreadsheets/d/{sid}/edit#gid=0"


# ─────────────────────────────────────────────────────────────
# Profile Sidebar (Clean Version)
# ─────────────────────────────────────────────────────────────
def render_profile_sidebar(
    *,
    sheet_key: str,
    host_key: str,
    sheet_label: str = "Google Sheets URL",
    host_label: str = "Image Hosting URL",
) -> None:
    """
    완전 클린버전:
    - 프로필 값 → 우선 표시
    - 저장 시: update_user_profile() 단일 호출로 유지
    - session_state는 UI 표시용 보조 수단으로만 사용
    - 저장 후 rerun → 즉시 반영
    """

    with st.sidebar:
        if not is_logged_in():
            st.warning("로그인이 필요합니다.")
            return

        st.subheader("⚙️ 프로필 설정")

        # ----------------------------------------------------
        # 현재 프로필 값 (Profile → Session 우선순위 O, Session → Profile X)
        # ----------------------------------------------------
        prof_sid = get_user_pref(sheet_key, "") or get_user_pref("sheet_id", "")
        prof_host = (
            get_user_pref(host_key, "")
            or get_user_pref("image_host", "")
            or get_user_pref("default_image_host", "")
        )

        # ----------------------------------------------------
        # UI 입력 기본값 = 프로필 값
        # ----------------------------------------------------
        sheet_url = st.text_input(
            sheet_label,
            value=sheet_link(prof_sid) if prof_sid else "",
            placeholder="https://docs.google.com/spreadsheets/d/...",
            key=f"{sheet_key}_input",
        )

        image_host = st.text_input(
            host_label,
            value=prof_host or "",
            placeholder="https://example.com/",
            key=f"{host_key}_input",
        )

        # ----------------------------------------------------
        # 버튼 UI
        # ----------------------------------------------------
        col1, col2 = st.columns(2)

        # ─────────────────────────────────────────────
        # 저장 버튼
        # ─────────────────────────────────────────────
        if col1.button("저장", use_container_width=True):
            # 시트 ID 검증
            sid = extract_sheet_id(sheet_url)
            if not sid:
                st.error("올바른 Google Sheets URL을 입력해주세요.")
                return

            # 호스트 검증
            if image_host and not image_host.startswith(("http://", "https://")):
                st.error("Image Hosting URL은 http/https로 시작해야 합니다.")
                return

            # ─────────────────────────────────────────────
            # 핵심: update_user_profile() 단일 사용
            #      → users.json + 세션 + 프로필 로드 일관성 100%
            # ─────────────────────────────────────────────
            update_user_profile({
                sheet_key: sid,
                host_key: image_host,
            })

            # UI 세션 갱신 (표시 용도)
            st.session_state[sheet_key] = sid
            st.session_state[host_key] = image_host

            st.success("프로필이 저장되었습니다.")
            st.rerun()

        # ─────────────────────────────────────────────
        # 취소 버튼
        # ─────────────────────────────────────────────
        if col2.button("취소", use_container_width=True):
            st.rerun()
