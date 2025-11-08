# user_manager.py
# -*- coding: utf-8 -*-
import unicodedata
import streamlit as st
from pathlib import Path
import json

USER_PATH = Path("data/users.json")

# -----------------------------
# 내부 유틸
# -----------------------------
def load_users() -> dict:
    """users.json을 안전하게 로드"""
    try:
        return json.loads(USER_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_users(users: dict) -> None:
    """users.json 저장"""
    USER_PATH.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")

def _norm(s: str | None) -> str:
    """한글/공백 정규화"""
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s).strip()

# -----------------------------
# 로그인 / 세션 관련
# -----------------------------
def login(username: str) -> bool:
    """사용자명 또는 display_name으로 로그인"""
    name = _norm(username)
    users = load_users()

    # 1️⃣ 키명 매칭
    for key, prof in users.items():
        if _norm(key) == name:
            st.session_state["username"] = key
            st.session_state["current_user"] = prof
            return True

    # 2️⃣ display_name 매칭
    for key, prof in users.items():
        if _norm(prof.get("display_name")) == name:
            st.session_state["username"] = key
            st.session_state["current_user"] = prof
            return True

    return False


def is_logged_in() -> bool:
    """로그인 여부 확인"""
    return "username" in st.session_state and "current_user" in st.session_state


def logout() -> None:
    """로그아웃"""
    for k in ["username", "current_user"]:
        if k in st.session_state:
            del st.session_state[k]


def get_current_user() -> dict:
    """현재 로그인 사용자 정보"""
    return st.session_state.get("current_user", {})


def get_user_pref(key: str, default=None):
    """현재 사용자 설정값 조회"""
    user = get_current_user()
    return user.get(key, default)


def ensure_login_persistence():
    """
    Streamlit rerun 시 로그인 세션 복원
    - username만 남고 current_user가 사라진 경우 재로딩
    """
    if "username" in st.session_state and "current_user" not in st.session_state:
        users = load_users()
        uname = st.session_state["username"]
        if uname in users:
            st.session_state["current_user"] = users[uname]


def pin_user_query():
    """
    현재 로그인 사용자명을 URL 쿼리에 고정 (?user=)
    """
    try:
        q = st.query_params
        uname = st.session_state.get("username")
        if uname:
            q["user"] = uname
    except Exception:
        pass
