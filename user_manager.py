# user_manager.py (clean, file-backed)
# -*- coding: utf-8 -*-
"""
User/session & profile manager for Streamlit apps.

- No side effects on import (DO NOT call st.set_page_config here)
- Auth helpers: login/logout, query<->session sync (user pinning)
- Profile prefs: file-backed (data/users.json) + session cache
"""

from __future__ import annotations
from typing import Any, Dict, Optional
from pathlib import Path
import json
import streamlit as st

# ─────────────────────────────────────────────────────────────
# Keys & constants
# ─────────────────────────────────────────────────────────────
SESSION_USER_KEY = "user"
SESSION_AUTH_KEY = "is_logged_in"
SESSION_PREFS_KEY = "USER_PREFS"  # { username: {k: v, ...}, ... }

# ─────────────────────────────────────────────────────────────
# File-backed profiles (data/users.json)
# ─────────────────────────────────────────────────────────────
_PROFILES_CACHE: Optional[Dict[str, Dict[str, Any]]] = None

def _profiles_path() -> Path:
    # user_manager.py 위치 기준 ../data/users.json
    return Path(__file__).resolve().parent / "data" / "users.json"

def _load_profiles() -> Dict[str, Dict[str, Any]]:
    global _PROFILES_CACHE
    if _PROFILES_CACHE is not None:
        return _PROFILES_CACHE
    p = _profiles_path()
    if p.exists():
        try:
            _PROFILES_CACHE = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            _PROFILES_CACHE = {}
    else:
        _PROFILES_CACHE = {}
    return _PROFILES_CACHE

def _save_profiles(profiles: Dict[str, Dict[str, Any]]) -> None:
    global _PROFILES_CACHE
    _PROFILES_CACHE = profiles
    p = _profiles_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")

def _profile_for(user: str) -> Dict[str, Any]:
    profs = _load_profiles()
    return dict(profs.get(user) or {})

# ─────────────────────────────────────────────────────────────
# Basic state helpers
# ─────────────────────────────────────────────────────────────
def is_logged_in() -> bool:
    return bool(st.session_state.get(SESSION_AUTH_KEY)) and bool(
        st.session_state.get(SESSION_USER_KEY)
    )

def get_current_user(default: str = "") -> str:
    return st.session_state.get(SESSION_USER_KEY, default) or default

# ─────────────────────────────────────────────────────────────
# Query <-> Session synchronization
# ─────────────────────────────────────────────────────────────
def sync_from_query() -> bool:
    qp_user = st.query_params.get("user")
    if qp_user and not is_logged_in():
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
        return False
    qp["user"] = username
    st.query_params = qp
    return True

def ensure_login_persistence() -> None:
    sync_from_query()

# ─────────────────────────────────────────────────────────────
# Auth actions
# ─────────────────────────────────────────────────────────────
def login(username: str, *, pin_query: bool = True, rerun: bool = True) -> None:
    username = (username or "").strip()
    if not username:
        raise ValueError("username is required")
    st.session_state[SESSION_USER_KEY] = username
    st.session_state[SESSION_AUTH_KEY] = True
    if pin_query and pin_user_query(username) and rerun:
        st.rerun()

def logout(*, clear_query: bool = True, also_clear_nav: bool = True, rerun: bool = True) -> None:
    st.session_state.pop(SESSION_USER_KEY, None)
    st.session_state.pop(SESSION_AUTH_KEY, None)
    if clear_query:
        qp = dict(st.query_params)
        qp.pop("user", None)
        if also_clear_nav:
            qp.pop("nav", None)
        st.query_params = qp
    if rerun:
        st.rerun()

# ─────────────────────────────────────────────────────────────
# Session-cached preferences (in-memory)
# ─────────────────────────────────────────────────────────────
def _ensure_prefs_root() -> Dict[str, Dict[str, Any]]:
    if SESSION_PREFS_KEY not in st.session_state:
        st.session_state[SESSION_PREFS_KEY] = {}
    return st.session_state[SESSION_PREFS_KEY]  # type: ignore[return-value]

def _prefs_for(user: str) -> Dict[str, Any]:
    root = _ensure_prefs_root()
    if user not in root:
        root[user] = {}
    return root[user]

# ─────────────────────────────────────────────────────────────
# Public profile API (file → session → default)
# ─────────────────────────────────────────────────────────────
def get_user_pref(key: str, default: Any = None, user: Optional[str] = None) -> Any:
    user = user or get_current_user("")
    if not user:
        return default
    # 1) file-backed
    f = _profile_for(user)
    if key in f:
        return f.get(key, default)
    # 2) session-cached
    prefs = _prefs_for(user)
    return prefs.get(key, default)

def set_user_pref(key: str, value: Any, user: Optional[str] = None) -> None:
    user = user or get_current_user("")
    if not user:
        return
    # session
    prefs = _prefs_for(user)
    prefs[key] = value
    # file
    profs = _load_profiles()
    if user not in profs:
        profs[user] = {}
    profs[user][key] = value
    _save_profiles(profs)

def get_user_profile(default: Optional[Dict[str, Any]] = None) -> Dict[str, Any] | None:
    user = get_current_user("")
    if not user:
        return default
    # merge: file base + session overlay
    base = _profile_for(user)
    sess = _prefs_for(user)
    merged = dict(base)
    merged.update(sess)
    return merged

def update_user_profile(data: Optional[Dict[str, Any]] = None, **kwargs) -> bool:
    user = get_current_user("")
    if not user:
        return False
    payload: Dict[str, Any] = {}
    if isinstance(data, dict):
        payload.update(data)
    if kwargs:
        payload.update(kwargs)
    if not payload:
        return True

    # session update
    prefs = _prefs_for(user)
    prefs.update(payload)

    # file update
    profs = _load_profiles()
    base = dict(profs.get(user) or {})
    base.update(payload)
    profs[user] = base
    _save_profiles(profs)
    return True

# legacy alias some code may import
update_user_prof = update_user_profile

def set_user_profile_value(key: str, value: Any) -> bool:
    user = get_current_user("")
    if not user:
        return False
    # session
    prefs = _prefs_for(user)
    prefs[key] = value
    # file
    profs = _load_profiles()
    base = dict(profs.get(user) or {})
    base[key] = value
    profs[user] = base
    _save_profiles(profs)
    return True

# ─────────────────────────────────────────────────────────────
# Guards
# ─────────────────────────────────────────────────────────────
def require_login() -> None:
    if not is_logged_in():
        st.stop()
