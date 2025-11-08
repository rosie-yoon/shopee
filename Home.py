# Home.py (v4 clean)
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import streamlit as st

# ─────────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Shopee Support Tools",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────────────────────────────────────────
# Auth/session helpers (user_manager 미의존 버전)
# ─────────────────────────────────────────────────────────────
SESSION_USER_KEY = "user"
SESSION_AUTH_KEY = "is_logged_in"

def is_logged_in() -> bool:
    return bool(st.session_state.get(SESSION_AUTH_KEY)) and bool(
        st.session_state.get(SESSION_USER_KEY)
    )

def current_user() -> str:
    return st.session_state.get(SESSION_USER_KEY, "") or ""

def pin_user_query(username: str) -> bool:
    """?user= 을 세션 사용자로 고정. 실제 변경되면 True(= rerun 권장)."""
    if not username:
        return False
    qp = dict(st.query_params)
    if qp.get("user") == username:
        return False
    qp["user"] = username
    st.query_params = qp
    return True

def do_login(username: str) -> None:
    username = (username or "").strip()
    if not username:
        return
    st.session_state[SESSION_USER_KEY] = username
    st.session_state[SESSION_AUTH_KEY] = True
    if pin_user_query(username):
        st.rerun()

def do_logout(clear_nav: bool = True) -> None:
    st.session_state.pop(SESSION_USER_KEY, None)
    st.session_state.pop(SESSION_AUTH_KEY, None)
    qp = dict(st.query_params)
    qp.pop("user", None)
    if clear_nav:
        qp.pop("nav", None)
    st.query_params = qp
    st.rerun()

# ─────────────────────────────────────────────────────────────
# 딥링크 복구
# ─────────────────────────────────────────────────────────────
qp_user = st.query_params.get("user")
if qp_user and not is_logged_in():
    st.session_state[SESSION_USER_KEY] = qp_user
    st.session_state[SESSION_AUTH_KEY] = True

# ─────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────
left, right = st.columns([1, 1])
with left:
    st.title("Shopee Support Tools")
st.caption("운영/지원 자동화를 위한 툴킷")
st.divider()

# ─────────────────────────────────────────────────────────────
# Login panel
# ─────────────────────────────────────────────────────────────
if not is_logged_in():
    st.info("로그인이 필요합니다. 사용자명을 입력해 로그인해 주세요.")
    with st.form("login_form"):
        username = st.text_input("사용자명", value=qp_user or "", placeholder="ex) yeojin")
        ok = st.form_submit_button("로그인", use_container_width=True)
    if ok:
        if not username.strip():
            st.error("사용자명을 입력해 주세요.")
        else:
            do_login(username.strip())
            st.stop()
else:
    u = current_user()
    c1, c2 = st.columns([3, 1])
    with c1:
        st.success(f"✅ 로그인됨: **{u}**")
    with c2:
        if st.button("로그아웃", use_container_width=True):
            do_logout()

st.divider()

# ─────────────────────────────────────────────────────────────
# Cards with your PNG icons (no emoji fallback)
# ─────────────────────────────────────────────────────────────
ICON_DIR = Path(__file__).resolve().parent / "assets/icons"

def find_icon(name: str):
    for cand in (ICON_DIR / f"{name}@3x.png", ICON_DIR / f"{name}.png"):
        if cand.exists():
            return cand
    return None

def render_card(col, icon_name: str, title: str, desc: str, page_path: str):
    with col:
        p = find_icon(icon_name)
        if p:
            st.image(str(p), width=28)
        else:
            st.write("")  # 아이콘 없을 때만 여백
        st.write(f"### {title}")
        st.caption(desc)
        st.page_link(page_path, label="열기 →")

c1, c2, c3 = st.columns(3)
render_card(c1, "design", "Cover Image", "상품 커버 썸네일 합성기", "pages/1_Cover Image.py")
render_card(c2, "copy", "Copy Template", "3종 템플릿 복사/업로드", "pages/2_Copy Template.py")
render_card(c3, "create", "Create Template", "템플릿 생성/전처리/내보내기", "pages/3_Create Template.py")

st.divider()
st.caption("Version: v4 clean")
