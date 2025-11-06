# pages/1_Cover Image.py
import streamlit as st
from pathlib import Path
import sys
from user_manager import is_logged_in
from image_compose.app import run as image_compose_run

st.set_page_config(page_title="Cover Image", layout="wide")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from user_manager import is_logged_in, ensure_login_persistence
# ...
ensure_login_persistence()            # ✅ 세션 복원 (가드 전에)
if not is_logged_in():
    st.warning("로그인이 필요합니다. 사용자명을 입력해 로그인해 주세요.")
    st.stop()

image_compose_run()
