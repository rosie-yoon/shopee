# pages/0_Login.py
import streamlit as st
from user_manager import login, load_users, is_logged_in

st.set_page_config(page_title="Login", layout="centered")

st.title("🔐 Shopee Support Login")
st.caption("관리자 등록된 사용자만 접속할 수 있습니다.")

username = st.text_input("사용자 이름을 입력하세요", placeholder="예: yeojin")

if st.button("로그인"):
    if login(username.strip()):
        st.success("로그인 성공! 잠시 후 홈으로 이동합니다.")
        st.switch_page("Home.py")
    else:
        st.error("등록되지 않은 사용자입니다. 관리자에게 문의하세요.")

if not load_users():
    st.warning("⚠️ data/users.json 파일이 비어 있습니다. 관리자 계정이 필요합니다.")
