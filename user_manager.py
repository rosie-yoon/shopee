# user_manager.py (refactored & safe)
# -*- coding: utf-8 -*-
"""
User/session & profile manager for Streamlit apps.

Enhancements:
- Profiles loaded from <app_root>/data/users.json (absolute & stable path)
- Only registered users can log in
- New session always starts logged-out
- Session + query params fully cleaned on logout
- Atomic file write for profiles
"""

from __future__ import annotations
from typing import Any, Dict, Optional
from pathlib import Path
import json
import streamlit as st

# ─────────────────────────────────────────────
# Constants & Keys
# ─────────────────────────────────────────────
SESSION_USER_KEY = "user"
SESSION_AUTH_KEY = "is_logged_in"
SESSION_PREFS_KEY = "USER_PREFS"
SESSION_INIT_KEY = "_SESSION_INITIALIZED"

_PROFILES_CACHE: Optional[Dict[str, Dict[str, Any]]] = None


# ─────────────────────────────────────────────
# Paths: Always app root/data/users.json
# ─────────────────────────────────────────────
def _profiles_path() -> Path:
    """Force profile file location: <app_root>/data/users.json"""
    root = Path(__file__).resolve().parents[1]  # shopee_dev / shopee_v1
    return root / "data" / "users.json"


# ─────────────────────────────────────────────
# Load / Save Profiles (Atomic)
# ─────────────────────────────────────────────
def _load_profiles() -> Dict[str, Dict[str, Any]]:
    global _PROFILES_CACHE
    if _PROFILES_CACHE is not None:
        return _PROFILES_CACHE

    p = _profiles_path()
    if not p.exists():
        _PROFILES_CACHE = {}
        return _PROFILES_CACHE

    try:
        _PROFILES_CACHE = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        _PROFILES_CACHE = {}

    return _PROFILES_CACHE


def _save_profiles(data: Dict[str, Dict[str, Any]]) -> None:
    global _PROFILES_CACHE
    _PROFILES_CACHE = data

    p = _profiles_path()
    p.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write: temp → rename
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


# ─────────────────────────────────────────────
# Session Initialization (Always logged-out)
# ─────────────────────────────────────────────
def _initialize_session_once() -> None:
    """
    Ensure that a brand-new Streamlit session starts as logged-out.
    Only runs once per session (reruns do NOT reset login state).
    """
    if st.session_state.get(SESSION_INIT_KEY):
        return  # Already initialized in this session

    st.session_state[SESSION_INIT_KEY] = True
    st.session_state[SESSION_USER_KEY] = ""
    st.session_state[SESSION_AUTH_KEY] = False


# ─────────────────────────────────────────────
# Basic Accessors
# ─────────────────────────────────────────────
def is_logged_in() -> bool:
    return bool(st.session_state.get(SESSION_AUTH_KEY)) and bool(
        st.session_state.get(SESSION_USER_KEY)
    )


def get_current_user(default: str = "") -> str:
    return st.session_state.get(SESSION_USER_KEY, default) or default


# ─────────────────────────────────────────────
# Login / Logout
# ─────────────────────────────────────────────
def login(username: str, *, pin_query: bool = True, rerun: bool = True) -> None:
    """
    Only registered users can log in.
    """
    username = (username or "").strip()
    profiles = _load_profiles()

    if username not in profiles:
        raise ValueError("등록되지 않은 사용자입니다.")

    st.session_state[SESSION_USER_KEY] = username
    st.session_state[SESSION_AUTH_KEY] = True

    if pin_query:
        pin_user_query(username)

    if rerun:
        st.rerun()


def logout(*, clear_query: bool = True, rerun: bool = True) -> None:
    """
    Full reset: session + query params
    """
    st.session_state.clear()
    st.session_state[SESSION_INIT_KEY] = True  # ensure next state is logged-out
    st.session_state[SESSION_USER_KEY] = ""
    st.session_state[SESSION_AUTH_KEY] = False

    if clear_query:
        st.query_params = {}

    if rerun:
        st.rerun()


# ─────────────────────────────────────────────
# Query <-> Session Sync
# (Optional: only allow if user exists)
# ─────────────────────────────────────────────
def sync_from_query() -> bool:
    """
    If ?user=... exists AND the user exists in profiles, auto-login.
    """
    qp_user = st.query_params.get("user")
    if not qp_user:
        return False

    profiles = _load_profiles()
    if qp_user not in profiles:
        return False  # invalid user → ignore

    if not is_logged_in():
        st.session_state[SESSION_USER_KEY] = qp_user
        st.session_state[SESSION_AUTH_KEY] = True
        return True

    return False


def pin_user_query(username: Optional[str] = None) -> bool:
    username = username or get_current_user("")
    if not username:
        return False

    qp = dict(st.query_params)
    if qp.get("user") == username:
        return False  # no change

    qp["user"] = username
    st.query_params = qp
    return True


def ensure_login_persistence() -> None:
    """Call this at the top of each page."""
    _initialize_session_once()  # ensures clean session at first load
    sync_from_query()


# ─────────────────────────────────────────────
# Preferences API
# ─────────────────────────────────────────────
def _ensure_prefs_root() -> Dict[str, Dict[str, Any]]:
    if SESSION_PREFS_KEY not in st.session_state:
        st.session_state[SESSION_PREFS_KEY] = {}
    return st.session_state[SESSION_PREFS_KEY]


def _prefs_for(user: str) -> Dict[str, Any]:
    root = _ensure_prefs_root()
    if user not in root:
        root[user] = {}
    return root[user]


def get_user_pref(key: str, default: Any = None, user: Optional[str] = None) -> Any:
    user = user or get_current_user("")
    if not user:
        return default

    f = _load_profiles().get(user, {})
    if key in f:
        return f.get(key, default)

    return _prefs_for(user).get(key, default)


def set_user_pref(key: str, value: Any, user: Optional[str] = None) -> None:
    user = user or get_current_user("")
    if not user:
        return

    prefs = _prefs_for(user)
    prefs[key] = value

    profs = _load_profiles()
    profs.setdefault(user, {})[key] = value
    _save_profiles(profs)


def get_user_profile(default: Optional[Dict[str, Any]] = None) -> Dict[str, Any] | None:
    user = get_current_user("")
    if not user:
        return default

    base = _load_profiles().get(user, {})
    sess = _prefs_for(user)
    merged = dict(base)
    merged.update(sess)
    return merged


def update_user_profile(data: Optional[Dict[str, Any]] = None, **kwargs) -> bool:
    user = get_current_user("")
    if not user:
        return False

    payload = {}
    if isinstance(data, dict):
        payload.update(data)
    if kwargs:
        payload.update(kwargs)
    if not payload:
        return True

    prefs = _prefs_for(user)
    prefs.update(payload)

    profs = _load_profiles()
    profs.setdefault(user, {}).update(payload)
    _save_profiles(profs)

    return True


update_user_prof = update_user_profile


def set_user_profile_value(key: str, value: Any) -> bool:
    return update_user_profile({key: value})


# ─────────────────────────────────────────────
# Guard
# ─────────────────────────────────────────────
def require_login() -> None:
    if not is_logged_in():
        st.stop()
