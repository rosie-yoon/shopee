import unicodedata
import streamlit as st
from pathlib import Path
import json

USER_PATH = Path("data/users.json")

def load_users() -> dict:
    try:
        return json.loads(USER_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _norm(s: str | None) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s).strip()

def login(username: str) -> bool:
    name = _norm(username)
    users = load_users()

    # 1) 키명으로 매칭
    for key, prof in users.items():
        if _norm(key) == name:
            st.session_state["username"] = key
            st.session_state["current_user"] = prof
            return True

    # 2) display_name으로 매칭
    for key, prof in users.items():
        if _norm(prof.get("display_name")) == name:
            st.session_state["username"] = key
            st.session_state["current_user"] = prof
            return True

    return False
