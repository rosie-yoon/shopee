# pages/1_Cover Image.py
# -*- coding: utf-8 -*-

# 1) 표준 라이브러리
from pathlib import Path
import sys

# 2) Streamlit 설정 (가장 먼저)
import streamlit as st
st.set_page_config(page_title="Cover Image", layout="wide")

# 3) 프로젝트 루트 경로 보정
ROOT = Path(__file__).resolve().parents[1]  # .../shopee
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

# 4) 내부 모듈 import (경로 보정 후)
from auth_guard import bootstrap_auth, current_user
from image_compose.app import run as image_compose_run

# 5) 인증 부트스트랩(딥링크 복구 → 로그인 확인 → ?user= pin → 필요시 rerun)
bootstrap_auth(go_home=False)

# 6) 페이지 본문
st.title("Cover Image")
st.caption("상품 커버 썸네일 합성기")

# 메인 앱 실행
image_compose_run()
