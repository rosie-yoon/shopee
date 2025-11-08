# Home.py (v3-safe, no user_manager dependency)
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from urllib.parse import quote
import base64

import streamlit as st
from ui_theme import apply_theme

# ─────────────────────────────────────────────────────────────
# Page config & theme
# ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Shopee Support Tools",
    layout="wide",
    initial_sidebar_state="collapsed",
)
apply_theme()

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────
SESSION_USER_KEY = "user"
SESSION_AUTH_KEY = "is_logged_in"
ICON_DIR = Path("assets/icons")

NAV_MAP = {
    # key: (표시제목, 설명, 아이콘명, switch_page 대상)
    "cover": ("Cover Image", "상품 커버 썸네일 합성기", "design", "pages/1_Cover Image.py"),
    "template": ("Copy Template", "3종 템플릿 복사/업로드", "copy", "pages/2_Copy Template.py"),
    "automation": ("Create Template", "템플릿 생성/전처리/내보내기", "create", "pages/3_Create Template.py"),
}

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _find_icon_path(name: str) -> Path | None:
    for p in (ICON_DIR / f"{name}@3x.png", ICON_DIR / f"{name}.png"):
        if p.exists():
            return p
    return None

def resolve_icon_b64(name: str) -> str | None:
    p = _find_icon_path(name)
    if not p:
        return None
    try:
        return base64.b64encode(p.read_bytes()).decode("utf-8")
    except Exception:
        return None

def is_logged_in() -> bool:
    return bool(st.session_state.get(SESSION_AUTH_KEY)) and bool(st.session_state.get(SESSION_USER_KEY))

def current_user() -> str:
    return st.session_state.get(SESSION_USER_KEY, "") or ""

def pin_user_query(username: str) -> bool:
    """
    ?user= 값을 세션 사용자로 고정. 변경이 실제 발생하면 True 반환(= rerun 필요).
    """
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

def handle_nav():
    """
    ?nav= 이 있고 로그인된 경우 해당 페이지로 switch_page
    """
    nav = st.query_params.get("nav")
    if not nav or nav not in NAV_MAP:
        return
    if not is_logged_in():
        return
    pin_user_query(current_user())  # 안전핀
    target = NAV_MAP[nav][3]
    st.switch_page(target)

# ─────────────────────────────────────────────────────────────
# Auth bootstrap (딥링크 복구 → nav 처리)
# ─────────────────────────────────────────────────────────────
qp_user = st.query_params.get("user")
if qp_user and not is_logged_in():
    st.session_state[SESSION_USER_KEY] = qp_user
    st.session_state[SESSION_AUTH_KEY] = True

handle_nav()

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
# Card grid
# ─────────────────────────────────────────────────────────────
CATALOG = [
    {"key": k, "title": t, "desc": d, "icon_b64": resolve_icon_b64(i)}
    for k, (t, d, i, _) in NAV_MAP.items()
]

st.markdown(
    """
    <style>
      .ui-grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));}
      .ui-card{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.1);
               border-radius:16px;padding:18px 18px 16px 18px;text-decoration:none !important;
               transition:transform .12s ease,border-color .12s ease,background .12s ease;display:block;}
      .ui-card:hover{transform:translateY(-1px);border-color:rgba(255,255,255,.24);background:rgba(255,255,255,.06);}
      .ui-card .row{display:flex;align-items:center;gap:10px;}
      .ui-card .title{font-weight:700;font-size:18px;margin:0;}
      .ui-card .desc{color:rgba(255,255,255,.7);margin:8px 0 0 0;font-size:14px;}
      .ui-card img{width:22px;height:22px;object-fit:contain;opacity:.9;}
      a.ui-card,a.ui-card:visited,a.ui-card:hover{color:inherit;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.subheader("도구 모음")
st.write("")

u = current_user()
st.markdown('<div class="ui-grid">', unsafe_allow_html=True)
for c in CATALOG:
    href = f"?nav={quote(c['key'])}"
    if u:
        href += f"&user={quote(u)}"
    b64 = c["icon_b64"] or ""
    st.markdown(
        f"""
        <a class="ui-card" href="{href}" target="_self">
          <div class="row">
            {'<img src="data:image/png;base64,'+b64+'" alt="icon"/>' if b64 else ''}
            <div class="title">{c["title"]}</div>
          </div>
          <p class="desc">{c["desc"]}</p>
        </a>
        """,
        unsafe_allow_html=True,
    )
st.markdown('</div>', unsafe_allow_html=True)

st.divider()
st.caption("Version: v3-safe (no user_manager dependency)")
