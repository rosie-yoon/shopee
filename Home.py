# Home.py
# -*- coding: utf-8 -*-
import base64
from pathlib import Path
from urllib.parse import quote
import streamlit as st

from ui_theme import apply_theme  # 공통 테마
# ✅ 추가: 로그인/로그아웃 유틸
from user_manager import is_logged_in, logout

# --------------------------------------------------------------------
# 기본 설정 + 홈에서는 사이드바 완전 숨김
# --------------------------------------------------------------------
st.set_page_config(
    page_title="Shopee Support Tools",
    layout="wide",
    initial_sidebar_state="collapsed",
)
apply_theme(hide_sidebar=True)

# ✅ 로그인 가드: 네비게이션 처리 전에 차단
if not is_logged_in():
    st.warning("로그인이 필요합니다. 아래 버튼을 눌러 로그인 페이지로 이동하세요.")
    if st.button("로그인 페이지로 이동", type="primary"):
        st.switch_page("pages/0_Login.py")
    st.stop()

# --------------------------------------------------------------------
# 쿼리 파라미터로 페이지 전환 (카드 전체 클릭용)
# --------------------------------------------------------------------
def get_nav_target() -> str | None:
    # Streamlit 버전 호환: query_params / experimental_get_query_params
    try:
        nav = st.query_params.get("nav", None)
        if isinstance(nav, list):
            nav = nav[0] if nav else None
    except Exception:
        nav = st.experimental_get_query_params().get("nav", [None])[0]
    return nav

target = get_nav_target()
if target:
    # 예: target == "pages/3_Create Items.py"
    st.switch_page(target)

# --------------------------------------------------------------------
# 아이콘 유틸
# --------------------------------------------------------------------
ICON_DIR = Path("assets/icons")

def resolve_icon(name: str) -> Path:
    hi = ICON_DIR / f"{name}@3x.png"
    lo = ICON_DIR / f"{name}.png"
    return hi if hi.exists() else lo

def icon_b64(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

ICONS = {
    "cover":  resolve_icon("cover"),
    "copy":   resolve_icon("copy"),
    "create": resolve_icon("create"),
}

# --------------------------------------------------------------------
# 페이지 전용 스타일 (카드만)
# --------------------------------------------------------------------
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

# --------------------------------------------------------------------
# 본문
# --------------------------------------------------------------------
# 상단 타이틀 + 우측 로그아웃 버튼
left, mid, right = st.columns([6, 4, 2])
with left:
    st.title("Shopee Support Tools")
with right:
    if st.button("로그아웃"):
        logout()
        st.switch_page("pages/0_Login.py")

st.divider()

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

cols = st.columns(3)
for col, c in zip(cols, cards):
    with col:
        b64 = icon_b64(c["icon"]) if Path(c["icon"]).exists() else ""
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
st.caption("Version: v3")
