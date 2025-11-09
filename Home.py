# Home.py (v6 UI clean: cards box + Google blue button + PNG icons)
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

# Auth/session helpers
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

# 딥링크 복구
qp_user = st.query_params.get("user")
if qp_user and not is_logged_in():
    st.session_state[SESSION_USER_KEY] = qp_user
    st.session_state[SESSION_AUTH_KEY] = True

# Header
left, right = st.columns([1, 1])
with left:
    st.title("Shopee Support Tools")
st.caption("운영/지원 자동화를 위한 툴킷")
st.divider()

# Login panel (로그인 전엔 카드 미노출)
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

# 로그인 정보 및 로그아웃
u = current_user()
c1, c2 = st.columns([3, 1])
with c1:
    st.success(f"✅ 로그인됨: **{u}**")
with c2:
    if st.button("로그아웃", use_container_width=True):
        do_logout()

st.divider()

# Style: 구글 블루 버튼 + 간단 텍스트 여백
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

# Cards (네이티브 컨테이너 border=True)
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
st.caption("Version: v4.2")
