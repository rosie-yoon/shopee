# user_manager.py
# -*- coding: utf-8 -*-
"""
Lightweight user/session manager for Streamlit apps.

- No side effects on import (DO NOT call st.set_page_config here)
- Unified helpers for:
  * login/logout
  * query<->session sync (user pinning)
  * per-user preferences (in-memory via st.session_state)
"""

from __future__ import annotations
from typing import Any, Dict, Optional
import streamlit as st

# ─────────────────────────────────────────────────────────────
# Keys & constants
# ─────────────────────────────────────────────────────────────
SESSION_USER_KEY = "user"
SESSION_AUTH_KEY = "is_logged_in"
SESSION_PREFS_KEY = "USER_PREFS"  # { username: {k: v, ...}, ... }

# ─────────────────────────────────────────────────────────────
# Basic state helpers
# ─────────────────────────────────────────────────────────────
def is_logged_in() -> bool:
    """Return True if a user is authenticated."""
    return bool(st.session_state.get(SESSION_AUTH_KEY)) and bool(
        st.session_state.get(SESSION_USER_KEY)
    )

def get_current_user(default: str = "") -> str:
    """Get current username from session_state (or default)."""
    return st.session_state.get(SESSION_USER_KEY, default) or default

# ─────────────────────────────────────────────────────────────
# Query <-> Session synchronization
# ─────────────────────────────────────────────────────────────
def sync_from_query() -> bool:
    """
    If ?user is present and session is not authenticated, restore session from query.
    Returns:
        changed (bool): True if session_state has been updated.
    """
    qp_user = st.query_params.get("user")
    if qp_user and not is_logged_in():
        st.session_state[SESSION_USER_KEY] = qp_user
        st.session_state[SESSION_AUTH_KEY] = True
        return True
    return False

def pin_user_query(username: Optional[str] = None) -> bool:
    """
    Pin ?user=<username> in the URL.
    If the URL already has the same user, do nothing.
    Returns:
        updated (bool): True when query was actually changed (rerun recommended).
    """
    username = username or get_current_user("")
    if not username:
        return False
    qp = dict(st.query_params)  # copy
    if qp.get("user") == username:
        return False
    qp["user"] = username
    st.query_params = qp
    return True

# Backward-compatible alias (pages가 호출하던 이름 유지)
def ensure_login_persistence() -> None:
    """Legacy helper. Just restores session from query if needed."""
    sync_from_query()

# ─────────────────────────────────────────────────────────────
# Auth actions
# ─────────────────────────────────────────────────────────────
def login(username: str, *, pin_query: bool = True, rerun: bool = True) -> None:
    """Set session as authenticated and (optionally) pin ?user."""
    username = (username or "").strip()
    if not username:
        raise ValueError("username is required")
    st.session_state[SESSION_USER_KEY] = username
    st.session_state[SESSION_AUTH_KEY] = True
    if pin_query and pin_user_query(username) and rerun:
        st.rerun()

def logout(*, clear_query: bool = True, also_clear_nav: bool = True, rerun: bool = True) -> None:
    """Clear session auth & (optionally) clear query params (?user, ?nav)."""
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
# Per-user preferences (in-memory)
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

def get_user_pref(key: str, default: Any = None, user: Optional[str] = None) -> Any:
    """Read a preference value for a user."""
    user = user or get_current_user("")
    if not user:
        return default
    prefs = _prefs_for(user)
    return prefs.get(key, default)

def set_user_pref(key: str, value: Any, user: Optional[str] = None) -> None:
    """Save a preference value for a user."""
    user = user or get_current_user("")
    if not user:
        return
    prefs = _prefs_for(user)
    prefs[key] = value

# ─────────────────────────────────────────────────────────────
# Optional: convenience guards
# ─────────────────────────────────────────────────────────────
def require_login() -> None:
    """Raise Streamlit stop if not logged in."""
    if not is_logged_in():
        st.stop()

# ─────────────────────────────────────────────────────────────
# Compatibility helpers expected by profile_sidebar.py
# ─────────────────────────────────────────────────────────────
def get_user_profile(default: Optional[Dict[str, Any]] = None):
    """Return full profile dict for current user."""
    user = get_current_user("")
    if not user:
        return default
    return _prefs_for(user)

def update_user_profile(data: Optional[Dict[str, Any]] = None, **kwargs) -> bool:
    """
    Update current user's profile.
    Accepts either a dict `data` or keyword args.
    Returns True if updated.
    """
    user = get_current_user("")
    if not user:
        return False
    prefs = _prefs_for(user)
    if data and isinstance(data, dict):
        prefs.update(data)
    if kwargs:
        prefs.update(kwargs)
    return True

# Some legacy code may import a shortened name:
update_user_prof = update_user_profile  # alias

def set_user_profile_value(key: str, value: Any) -> bool:
    """Set a single profile key for current user."""
    user = get_current_user("")
    if not user:
        return False
    prefs = _prefs_for(user)
    prefs[key] = value
    return True
