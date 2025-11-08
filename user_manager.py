# Home.py (merged)
# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
from pathlib import Path
from urllib.parse import quote

import streamlit as st
from ui_theme import apply_theme  # 공통 테마

# =========================
# 기본 설정
# =========================
st.set_page_config(
    page_title="Shopee Support Tools",
    layout="wide",
    initial_sidebar_state="collapsed",
)

apply_theme()

# =========================
# 유틸: 아이콘 로딩 (선택)
# =========================
ICON_DIR = Path("assets/icons")

def _find_icon_path(name: str) -> Path | None:
    cands = [ICON_DIR / f"{name}@3x.png", ICON_DIR / f"{name}.png"]
    for p in cands:
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

# =========================
# 인증/세션 관리
# =========================
SESSION_USER_KEY = "user"
SESSION_AUTH_KEY = "is_logged_in"

def is_logged_in() -> bool:
    return bool(st.session_state.get(SESSION_AUTH_KEY)) and bool(st.session_state.get(SESSION_USER_KEY))

def pin_user_query(username: str) -> None:
    # st.query_params는 dict-like. 키를 직접 설정해 pin
    qp = st.query_params
    qp["user"] = username  # 유지
    st.query_params = qp   # 일부 버전에서는 재할당이 필요함

def do_login(username: str) -> None:
    st.session_state[SESSION_USER_KEY] = username
    st.session_state[SESSION_AUTH_KEY] = True
    pin_user_query(username)

def do_logout() -> None:
    st.session_state.pop(SESSION_USER_KEY, None)
    st.session_state.pop(SESSION_AUTH_KEY, None)
    # 쿼리 파라미터 초기화
    qp = dict(st.query_params)
    if "user" in qp:
        qp.pop("user")
    if "nav" in qp:
        qp.pop("nav")
    st.query_params = qp

# =========================
# 네비게이션 매핑
#  - 링크는 ?nav=<key>&user=<name>
#  - 홈이 nav를 감지해서 st.switch_page로 라우팅
# =========================
NAV_MAP = {
    # key: (표시제목, 설명, 아이콘명, switch_page 대상)
    "cover": ("Cover Image", "상품 커버 썸네일 합성기", "design", "pages/1_Cover Image.py"),
    "template": ("Copy Template", "3종 템플릿 복사/업로드", "copy", "pages/2_Copy Template.py"),
    "automation": ("Automation", "템플릿 → 전처리 → 업로드 자동화", "create", "app.py"),
}

def handle_nav():
    """?nav=... 이 있고, 로그인되어 있으면 즉시 페이지 전환"""
    nav = st.query_params.get("nav")
    if not nav:
        return
    if nav not in NAV_MAP:
        return
    if not is_logged_in():
        return
    # 전환 직전 user pin (안전)
    pin_user_query(st.session_state[SESSION_USER_KEY])
    target = NAV_MAP[nav][3]
    st.switch_page(target)

# =========================
# 상단: 로그인 가드 + 즉시 네비게이션
# =========================
# 쿼리에 user가 있고 세션이 비어 있으면 세션도 복구 (딥링크 대비)
qp_user = st.query_params.get("user")
if qp_user and not is_logged_in():
    st.session_state[SESSION_USER_KEY] = qp_user
    st.session_state[SESSION_AUTH_KEY] = True

# nav 처리(로그인 이후에만)
handle_nav()

# =========================
# 헤더
# =========================
col_l, col_r = st.columns([1, 1])
with col_l:
    st.title("Shopee Support Tools")
with col_r:
    st.empty()

st.caption("운영/지원 자동화를 위한 툴킷")

# =========================
# 로그인 섹션
# =========================
if not is_logged_in():
    st.info("로그인이 필요합니다. 사용자명을 입력해 로그인해 주세요.")
    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("사용자명", value=qp_user or "", placeholder="ex) yeojin")
        ok = st.form_submit_button("로그인", use_container_width=True)
    if ok:
        if not username.strip():
            st.error("사용자명을 입력해 주세요.")
        else:
            do_login(username.strip())
            st.success(f"{username} 님, 환영합니다!")
            st.rerun()
else:
    u = st.session_state[SESSION_USER_KEY]
    c1, c2 = st.columns([3, 1])
    with c1:
        st.success(f"✅ 로그인됨: **{u}**")
    with c2:
        if st.button("로그아웃", use_container_width=True):
            do_logout()
            st.rerun()

st.divider()

# =========================
# 카드 그리드
# =========================
CARD_CATALOG = []
for key, (title, desc, icon_name, _) in NAV_MAP.items():
    CARD_CATALOG.append(
        {
            "key": key,
            "title": title,
            "desc": desc,
            "icon_b64": resolve_icon_b64(icon_name),
        }
    )

# 스타일: 카드(단일 레이어)
st.markdown(
    """
    <style>
      .ui-grid{
        display:grid;
        gap:16px;
        grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      }
      .ui-card{
        background: rgba(255,255,255,.04);
        border: 1px solid rgba(255,255,255,.1);
        border-radius: 16px;
        padding: 18px 18px 16px 18px;
        text-decoration: none !important;
        transition: transform .12s ease, border-color .12s ease, background .12s ease;
        display: block;
      }
      .ui-card:hover{
        transform: translateY(-1px);
        border-color: rgba(255,255,255,.24);
        background: rgba(255,255,255,.06);
      }
      .ui-card .row{
        display:flex; align-items:center; gap:10px;
      }
      .ui-card .title{
        font-weight:700; font-size:18px; margin: 0;
      }
      .ui-card .desc{
        color: rgba(255,255,255,.7);
        margin: 8px 0 0 0;
        font-size: 14px;
      }
      .ui-card img{
        width: 22px; height: 22px; object-fit: contain;
        opacity:.9;
      }
      a.ui-card, a.ui-card:visited, a.ui-card:hover{
        color: inherit;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# 그리드 렌더링
st.subheader("도구 모음")
st.write("")  # 여백

user_for_link = st.session_state.get(SESSION_USER_KEY, "")
with st.container():
    st.markdown('<div class="ui-grid">', unsafe_allow_html=True)
    for c in CARD_CATALOG:
        # ?nav=...&user=... 로 자기 자신 호출 → 상단 handle_nav()가 switch_page 수행
        href = f"?nav={quote(c['key'])}"
        if user_for_link:
            href += f"&user={quote(user_for_link)}"
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
st.caption("Version: v3 (merged login + nav)")
