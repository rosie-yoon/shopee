# Home.py
# -*- coding: utf-8 -*-
import base64
from pathlib import Path
from urllib.parse import quote
import streamlit as st

from user_manager import is_logged_in, login, logout

# --------------------------------------------------------------------
# 기본 설정
# --------------------------------------------------------------------
st.set_page_config(
    page_title="Shopee Support Tools",
    layout="wide",
    initial_sidebar_state="expanded" if is_logged_in() else "collapsed"
)

# 사이드바 표시 상태 제어 (로그인 전 숨김 / 로그인 후 표시)
if not is_logged_in():
    st.markdown("<style>section[data-testid='stSidebar']{display:none !important;}</style>", unsafe_allow_html=True)
else:
    st.markdown("<style>section[data-testid='stSidebar']{display:block !important;}</style>", unsafe_allow_html=True)

# --------------------------------------------------------------------
# 아이콘 유틸
# --------------------------------------------------------------------
ICON_DIR = Path("assets/icons")

def resolve_icon(name: str) -> Path:
    hi = ICON_DIR / f"{name}@3x.png"
    lo = ICON_DIR / f"{name}.png"
    return hi if hi.exists() else lo

def icon_b64(path: Path) -> str:
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except Exception:
        return ""

ICONS = {
    "cover":  resolve_icon("cover"),
    "copy":   resolve_icon("copy"),
    "create": resolve_icon("create"),
}

# --------------------------------------------------------------------
# 로그인 섹션 (미로그인 시)
# --------------------------------------------------------------------
st.title("Shopee Support Tools")
st.divider()

if not is_logged_in():
    st.subheader("🔐 Login")
    username = st.text_input("사용자 이름을 입력하세요", placeholder="예: yeojin")
    if st.button("로그인", type="primary", use_container_width=False) and username.strip():
        if login(username.strip()):
            st.success("로그인 성공!")
            st.rerun()
        else:
            st.error("등록되지 않은 사용자입니다. 관리자에게 문의하세요.")
    st.caption("버전: v3.2")
    st.stop()

# --------------------------------------------------------------------
# (로그인 상태) 상단 로그아웃 버튼
# --------------------------------------------------------------------
left, mid, right = st.columns([6, 4, 2])
with left:
    st.subheader("환영합니다 👋")
with right:
    if st.button("로그아웃"):
        logout()
        st.rerun()

st.divider()

# --------------------------------------------------------------------
# 카드 목록
# --------------------------------------------------------------------
cards = [
    {
        "icon": ICONS["cover"],
        "title": "Cover Image",
        "desc": "썸네일로 사용할 커버 이미지 생성",
        "path": "pages/1_Cover Image.py",
    },
    {
        "icon": ICONS["copy"],
        "title": "Copy Template",
        "desc": "복제용 Mass Upload 템플릿 생성",
        "path": "pages/2_Copy Template.py",
    },
    {
        "icon": ICONS["create"],
        "title": "Create Template",
        "desc": "신규 상품 Mass Upload 템플릿 생성",
        "path": "pages/3_Create Template.py",
    },
]

st.markdown(
    """
    <style>
      .ui-card{
        background: rgba(255,255,255,.08);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border-radius:16px; padding:14px 16px 16px;
        box-shadow:0 4px 18px rgba(0,0,0,.25), inset 0 0 0 1px rgba(255,255,255,.05);
        transition: transform .15s ease, background .25s ease;
        min-height: 130px;
      }
      .ui-card:hover{ background: rgba(255,255,255,.12); transform: translateY(-1px); }
      a.card-link{ display:block; text-decoration:none !important; color:inherit !important; -webkit-tap-highlight-color: transparent; outline:none !important; }
      a.card-link:hover, a.card-link:active, a.card-link *{ text-decoration:none !important; }
      .row{ display:flex; align-items:center; gap:10px; margin-bottom:6px; }
      .row img{ width:36px; height:36px; flex:0 0 auto; }
      .row .title{ font-weight:800; font-size:1.1rem; margin:0; color:#fff; }
      .desc{ margin:0; color:rgba(255,255,255,.85); }
    </style>
    """,
    unsafe_allow_html=True,
)

cols = st.columns(3)
for col, c in zip(cols, cards):
    with col:
        b64 = icon_b64(c["icon"])
        href = f"?nav={quote(c['path'])}"
        st.markdown(
            f"""
            <a class="card-link" href="{href}" target="_self" rel="noopener">
              <div class="ui-card">
                <div class="row">
                  {'<img src="data:image/png;base64,'+b64+'" alt="icon"/>' if b64 else ''}
                  <div class="title">{c["title"]}</div>
                </div>
                <p class="desc">{c["desc"]}</p>
              </div>
            </a>
            """,
            unsafe_allow_html=True,
        )

st.divider()
st.caption("버전: v3.2")
