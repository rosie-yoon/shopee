# Home.py
# -*- coding: utf-8 -*-
import base64
from pathlib import Path
from urllib.parse import quote
import streamlit as st

# --- import path fix (Streamlit Cloud 호환) ---
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent  # /mount/src/shopee
PARENT = ROOT.parent                    # /mount/src
for p in (ROOT, PARENT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
# ----------------------------------------------


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

# ✅ URL의 ?nav= 경로가 있으면 해당 페이지로 전환
def _switch_by_query():
    try:
        nav = st.query_params.get("nav", None)
        if isinstance(nav, list):
            nav = nav[0] if nav else None
    except Exception:
        nav = st.experimental_get_query_params().get("nav", [None])[0]
    if nav:
        st.switch_page(nav)

_switch_by_query()


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
            st.query_params["user"] = username.strip()  # ✅ 로그인 사용자 이름 URL에 저장
            st.rerun()
        else:
            st.error("등록되지 않은 사용자입니다. 관리자에게 문의하세요.")
    st.caption("버전: v3.2")
    st.stop()

# ... (위 내용 동일)

# 로그인 상태에서만 도달
left, mid, right = st.columns([6, 4, 2])
with left:
    st.subheader("환영합니다 👋")
with right:
    if st.button("로그아웃"):
        logout()
        st.rerun()

st.divider()

# 현재 로그인 사용자 쿼리 유지용
try:
    q = st.query_params
except Exception:
    q = st.experimental_get_query_params()
user_q = q.get("user")
user_q = (user_q[0] if isinstance(user_q, list) else user_q) if user_q else None

cards = [
    {"icon": ICONS["cover"],  "title": "Cover Image",  "desc": "썸네일로 사용할 커버 이미지 생성",     "path": "pages/1_Cover Image.py"},
    {"icon": ICONS["copy"],   "title": "Copy Template","desc": "복제용 Mass Upload 템플릿 생성",     "path": "pages/2_Copy Template.py"},
    {"icon": ICONS["create"], "title": "Create Template","desc":"신규 상품 Mass Upload 템플릿 생성", "path": "pages/3_Create Template.py"},
]

st.markdown("""
<style>
  .ui-card{ background:#ffffff;border-radius:16px;padding:14px 16px 16px;
            box-shadow:0 4px 18px rgba(0,0,0,.1);min-height:130px;transition:transform .15s}
  .ui-card:hover{ background:#f9fafb; transform:translateY(-1px) }
  a.card-link{ display:block; text-decoration:none !important; color:inherit !important; }
  .row{ display:flex; align-items:center; gap:10px; margin-bottom:6px; }
  .row img{ width:36px; height:36px; }
  .row .title{ font-weight:800; font-size:1.1rem; margin:0; color:#111827; }
  .desc{ margin:0; color:#374151; }
</style>
""", unsafe_allow_html=True)

cols = st.columns(3)
for col, c in zip(cols, cards):
    with col:
        b64 = icon_b64(c["icon"])
        # ✅ user 쿼리를 보존해서 넘김
        if user_q:
            href = f"?user={quote(user_q)}&nav={quote(c['path'])}"
        else:
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
