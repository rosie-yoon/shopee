# Home.py (v5 UI-only)
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
import streamlit as st

st.set_page_config(
    page_title="Shopee Support Tools",
    layout="wide",
    initial_sidebar_state="collapsed",
)

SESSION_USER_KEY = "user"
SESSION_AUTH_KEY = "is_logged_in"

def is_logged_in() -> bool:
    return bool(st.session_state.get(SESSION_AUTH_KEY)) and bool(st.session_state.get(SESSION_USER_KEY))

def current_user() -> str:
    return st.session_state.get(SESSION_USER_KEY, "") or ""

def pin_user_query(username: str) -> bool:
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

qp_user = st.query_params.get("user")
if qp_user and not is_logged_in():
    st.session_state[SESSION_USER_KEY] = qp_user
    st.session_state[SESSION_AUTH_KEY] = True

left, right = st.columns([1, 1])
with left:
    st.title("Shopee Support Tools")
st.caption("운영/지원 자동화를 위한 툴킷")
st.divider()

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
    st.stop()

u = current_user()
c1, c2 = st.columns([3, 1])
with c1:
    st.success(f"✅ 로그인됨: **{u}**")
with c2:
    if st.button("로그아웃", use_container_width=True):
        do_logout()

st.divider()

ICON_DIR = Path(__file__).resolve().parent / "assets/icons"

def icon_path_candidates(name: str):
    return [ICON_DIR / f"{name}@3x.png", ICON_DIR / f"{name}.png"]

def find_icon(name: str):
    for cand in icon_path_candidates(name):
        if cand.exists():
            return cand
    return None

def render_card(col, icon_name: str, title: str, desc: str, page_path: str):
    with col:
        p = find_icon(icon_name)
        if p:
            st.image(str(p), width=28)
        else:
            cands = icon_path_candidates(icon_name)
            st.caption(f"아이콘을 찾을 수 없습니다: {cands[0].name} / {cands[1].name}")
        st.write(f"### {title}")
        st.caption(desc)
        if st.button("열기", type="primary", use_container_width=True, key=f"btn_{icon_name}"):
            try:
                st.switch_page(page_path)
            except Exception:
                st.warning("페이지 이동에 실패했습니다. 사이드바 메뉴를 이용해 주세요.")

c1, c2, c3 = st.columns(3)
render_card(c1, "cover", "Cover Image", "상품 커버 썸네일 합성기", "pages/1_Cover Image.py")
render_card(c2, "copy", "Copy Template", "3종 템플릿 복사/업로드", "pages/2_Copy Template.py")
render_card(c3, "create", "Create Template", "템플릿 생성/전처리/내보내기", "pages/3_Create Template.py")

st.divider()
st.caption("Version: v5 (UI-only)")
