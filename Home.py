# Home.py (Stable Clean Version v7)
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import streamlit as st

# Page config
st.set_page_config(
    page_title="Shopee Support Tools",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ──────────────────────────────────────────────
# Import user/session manager
# ──────────────────────────────────────────────
from user_manager import (
    ensure_login_persistence,
    is_logged_in,
    get_current_user,
    login,
    logout,
)

# 최초 세션 초기화 + query sync
ensure_login_persistence()

# ──────────────────────────────────────────────
# UI Header
# ──────────────────────────────────────────────
st.title("Shopee Support Tools")
st.caption("운영/지원 자동화를 위한 툴킷")
st.divider()

# ──────────────────────────────────────────────
# 로그인 UI
# ──────────────────────────────────────────────
if not is_logged_in():
    st.info("로그인이 필요합니다. 사용자명을 입력해 로그인해 주세요.")
    with st.form("login_form"):
        username = st.text_input("사용자명", value="", placeholder="ex) yeojin")
        ok = st.form_submit_button("로그인", use_container_width=True)
    if ok:
        if not username.strip():
            st.error("사용자명을 입력해 주세요.")
        else:
            login(username.strip(), pin_query=True, rerun=True)
    st.stop()

# ──────────────────────────────────────────────
# 로그인 정보 + 로그아웃
# ──────────────────────────────────────────────
u = get_current_user()
c1, c2 = st.columns([3, 1])
with c1:
    st.success(f"✅ 로그인됨: **{u}**")
with c2:
    if st.button("로그아웃", use_container_width=True):
        logout(clear_query=True, rerun=True)

st.divider()

# ──────────────────────────────────────────────
# 스타일 (Google Blue Buttons)
# ──────────────────────────────────────────────
st.markdown(
    """
    <style>
      div.stButton > button[kind="primary"],
      div.stButton > button[data-testid="baseButton-primary"]{
        background:#1a73e8;border-color:#1a73e8;color:#fff
      }
      div.stButton > button[kind="primary"]:hover,
      div.stButton > button[data-testid="baseButton-primary"]:hover{
        background:#1669c1;border-color:#1669c1;color:#fff
      }
      .card-title{margin:6px 0 6px 0;font-size:18px}
      .card-desc{margin:0 0 12px 0;color:#5f6368;font-size:14px}
    </style>
    """,
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────
# Cards
# ──────────────────────────────────────────────
ICON_DIR = Path(__file__).resolve().parent / "assets" / "icons"

def _icon_path(name: str) -> str:
    for cand in (ICON_DIR / f"{name}@3x.png", ICON_DIR / f"{name}.png"):
        if cand.exists():
            return str(cand)
    return ""

def _card(col, title: str, desc: str, icon_name: str, page_path: str, key: str):
    with col:
        with st.container(border=True):
            ip = _icon_path(icon_name)
            if ip:
                st.image(ip, width=36)
            st.markdown(f"<h3 class='card-title'>{title}</h3>", unsafe_allow_html=True)
            st.markdown(f"<p class='card-desc'>{desc}</p>", unsafe_allow_html=True)
            if st.button("열기", type="primary", use_container_width=True, key=key):
                try:
                    st.switch_page(page_path)
                except Exception:
                    st.warning("페이지 이동에 실패했습니다. 사이드바 메뉴를 이용해 주세요.")

c1, c2, c3 = st.columns(3)
_card(c1, "Cover Image",   "상품 커버 썸네일 합성기",      "cover",  "pages/1_Cover Image.py",  "btn_cover")
_card(c2, "Copy Template",  "3종 템플릿 복사/업로드",       "copy",   "pages/2_Copy Template.py","btn_copy")
_card(c3, "Create Template","템플릿 생성/전처리/내보내기", "create", "pages/3_Create Template.py","btn_create")

st.divider()
st.caption("Version: v4.3")
