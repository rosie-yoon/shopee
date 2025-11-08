# Home.py (v4 - light + native cards)
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from urllib.parse import quote

import streamlit as st
# from ui_theme import apply_theme  # ❌ 다크 테마 제거

st.set_page_config(
    page_title="Shopee Support Tools",
    layout="wide",
    initial_sidebar_state="collapsed",

# ─────────────────────────────────────────────────────────────
# Auth/session helpers (user_manager 없이 동작)
# ─────────────────────────────────────────────────────────────
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
# Cards (네이티브 구성: 가로 병렬, HTML 없음)
#  - "도구 모음" 타이틀 제거
#  - 클릭 즉시 해당 페이지로 이동 (st.page_link)
# ─────────────────────────────────────────────────────────────
# 첫 줄
c1, c2, c3 = st.columns(3)
with c1:
    st.write("### Cover Image")
    st.write("상품 커버 썸네일 합성기")
    st.page_link("pages/1_Cover Image.py", label="열기 →", icon="🖼️")

with c2:
    st.write("### Copy Template")
    st.write("3종 템플릿 복사/업로드")
    st.page_link("pages/2_Copy Template.py", label="열기 →", icon="📄")

with c3:
    st.write("### Create Template")
    st.write("템플릿 생성/전처리/내보내기")
    st.page_link("pages/3_Create Template.py", label="열기 →", icon="⚙️")

st.divider()
st.caption("Version: v4 (light + native cards)")
