# user_manager.py (추가/개선)
from __future__ import annotations
import json
from pathlib import Path
import streamlit as st

USER_PATH = Path("data/users.json")

def load_users() -> dict:
    if USER_PATH.exists():
        return json.loads(USER_PATH.read_text(encoding="utf-8"))
    return {}

def save_users(data: dict) -> None:
    USER_PATH.parent.mkdir(parents=True, exist_ok=True)
    USER_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def get_current_user() -> dict | None:
    return st.session_state.get("current_user")

def is_logged_in() -> bool:
    return "current_user" in st.session_state and st.session_state["current_user"]

def login(username: str) -> bool:
    users = load_users()
    if username in users:
        st.session_state["current_user"] = users[username]
        st.session_state["username"] = username
        return True
    return False

def logout():
    for key in ["current_user", "username"]:
        st.session_state.pop(key, None)

def get_user_pref(key: str, default: str = "") -> str:
    user = get_current_user()
    if not user:
        return default
    return str(user.get(key, default))

def update_user_profile(patch: dict) -> None:
    """현재 로그인 사용자 프로필을 patch하여 저장 + 세션 동기화"""
    username = st.session_state.get("username")
    if not username:
        return
    data = load_users()
    cur = data.get(username, {})
    cur.update({k: v for k, v in patch.items() if v is not None})
    data[username] = cur
    save_users(data)
    st.session_state["current_user"] = cur  # 세션 동기화
import streamlit as st

# ✅ 페이지 이동 후에도 로그인 상태 유지 (Session hash 기반)
def ensure_login_persistence():
    """
    세션이 새로 열려도 브라우저 쿠키처럼 로그인 유지.
    홈에서 로그인 성공 시 username을 query_param으로 저장하고,
    다른 페이지는 그걸 다시 세션에 복원.
    """
    if "username" not in st.session_state:
        # URL에 username이 있으면 복원
        q = st.query_params or {}
        username = q.get("user", [None])[0] if isinstance(q.get("user"), list) else q.get("user")
        if username:
            users = load_users()
            if username in users:
                st.session_state["username"] = username
                st.session_state["current_user"] = users[username]
