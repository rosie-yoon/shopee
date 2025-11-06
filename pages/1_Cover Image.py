# pages/1_Cover Image.py
# -*- coding: utf-8 -*-
import streamlit as st
from pathlib import Path
import sys

# ⚠️ set_page_config는 첫 Streamlit 호출 전에 선언
st.set_page_config(page_title="Cover Image", layout="wide")

# pages/ 아래에 있으므로 프로젝트 루트(shopee)를 sys.path에 추가 (견고성 ↑)
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

# ✅ 로그인 유틸
from user_manager import is_logged_in

# 기존 이미지 합성 앱 (폴더명이 image_compose 여야 함)
from image_compose.app import run as image_compose_run

# ✅ 접근 제한: 로그인 안 했으면 차단
if not is_logged_in():
    st.warning("로그인이 필요합니다. 사용자명을 입력해 로그인해 주세요.")
    st.stop()

# ──────────────────────────────────────────────────────────────────────────────
# 본문: 별도 설정 없이 바로 이미지 합성기 실행
# ──────────────────────────────────────────────────────────────────────────────
image_compose_run()
