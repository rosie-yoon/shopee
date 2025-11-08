# auth_guard.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional
import streamlit as st

# 세션 키 (Home.py 병합안과 동일)
SESSION_USER_KEY = "user"
SESSION_AUTH_KEY = "is_logged_in"

# ─────────────────────────────────────────────────────────────────────────────
# 내부 유틸
# ─────────────────────────────────────────────────────────────────────────────
def _qp_dict() -> dict:
    # st.query_params는 dict-like → 복사본으로 다루고 재할당
    return dict(st.query_params)

def _set_qp(qp: dict) -> None:
    st.query_params = qp

# ─────────────────────────────────────────────────────────────────────────────
# 상태 조회/동기화
# ─────────────────────────────────────────────────────────────────────────────
def is_logged_in() -> bool:
    return bool(st.session_state.get(SESSION_AUTH_KEY)) and bool(st.session_state.get(SESSION_USER_KEY))

def current_user() -> str:
    return st.session_state.get(SESSION_USER_KEY, "") or ""

def sync_from_query() -> bool:
    """
    쿼리에 ?user=가 있고 세션이 비어 있으면 세션을 복구.
    Returns:
        changed(bool): 세션이 실제로 바뀌었는지
    """
    qp_user = st.query_params.get("user")
    if (not is_logged_in()) and qp_user:
        st.session_state[SESSION_USER_KEY] = qp_user
        st.session_state[SESSION_AUTH_KEY] = True
        return True
    return False

def pin_user_query(username: Optional[str] = None) -> bool:
    """
    쿼리파라미터의 user 값을 세션 사용자와 동일하게 '핀' 고정.
    Returns:
        updated(bool): 쿼리가 실제로 바뀌었는지(= rerun 필요 여부)
    """
    username = username or current_user()
    if not username:
        return False
    qp = _qp_dict()
    if qp.get("user") == username:
        return False
    qp["user"] = username
    _set_qp(qp)
    return True

# ─────────────────────────────────────────────────────────────────────────────
# 가드/부트스트랩
# ─────────────────────────────────────────────────────────────────────────────
def require_login(go_home: bool = False,
                  message: str = "로그인이 필요합니다. 먼저 사용자명을 입력해 로그인해 주세요.") -> None:
    """
    미로그인이면 경고 후 stop. go_home=True면 Home으로 전환 시도.
    """
    if is_logged_in():
        return
    st.warning(message)
    if go_home:
        try:
            st.switch_page("Home.py")
        except Exception:
            # Cloud/로컬 환경차로 switch_page 실패해도 안전
            pass
    st.stop()

def bootstrap_auth(go_home: bool = False) -> None:
    """
    페이지 상단에서 한 줄로 호출:
      1) ?user= → 세션 복구
      2) 미로그인 차단 (옵션: 홈으로 전환)
      3) 쿼리 user 핀(필요할 때만) 후 rerun
    """
    sync_from_query()
    if not is_logged_in():
        require_login(go_home=go_home)
    if pin_user_query():   # 쿼리가 바뀌었으면 한 번만 rerun
        st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# 로그아웃 유틸 (옵션)
# ─────────────────────────────────────────────────────────────────────────────
def logout(clear_query: bool = True, also_clear_nav: bool = True) -> None:
    st.session_state.pop(SESSION_USER_KEY, None)
    st.session_state.pop(SESSION_AUTH_KEY, None)
    if clear_query:
        qp = _qp_dict()
        qp.pop("user", None)
        if also_clear_nav:
            qp.pop("nav", None)
        _set_qp(qp)
    st.rerun()
