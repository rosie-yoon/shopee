# profile_sidebar.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path
import sys
import streamlit as st

# ─────────────────────────────────────────────────────────────
# Import path (ROOT만 추가: 감시 범위 최소화)
# ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent  # .../shopee
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ─────────────────────────────────────────────────────────────
# user_manager 안전 임포트
#  - update_user_profile이 없으면 폴백(_update_user_profile) 정의
# ─────────────────────────────────────────────────────────────
from user_manager import is_logged_in, get_user_pref  # 필수 심볼

try:
    # 권장 최신 인터페이스
    from user_manager import update_user_profile as _update_user_profile
except Exception:
    # 폴백: set_user_profile_value / set_user_pref 중 가능한 것으로 저장
    try:
        from user_manager import set_user_profile_value as _set_profile_value
    except Exception:
        _set_profile_value = None  # type: ignore[assignment]
    try:
        from user_manager import set_user_pref as _set_user_pref
    except Exception:
        _set_user_pref = None  # type: ignore[assignment]

    def _update_user_profile(data: dict | None = None, **kwargs) -> bool:  # noqa: N802
        """
        update_user_profile이 없는 환경을 위한 폴백.
        현재 로그인 사용자의 프로필에 data/kwargs를 병합 저장.
        """
        updated = False
        if isinstance(data, dict):
            for k, v in data.items():
                if _set_profile_value:
                    updated |= bool(_set_profile_value(k, v))  # type: ignore[misc]
                elif _set_user_pref:
                    _set_user_pref(k, v)  # type: ignore[misc]
                    updated = True
        for k, v in kwargs.items():
            if _set_profile_value:
                updated |= bool(_set_profile_value(k, v))  # type: ignore[misc]
            elif _set_user_pref:
                _set_user_pref(k, v)  # type: ignore[misc]
                updated = True
        return updated

# ─────────────────────────────────────────────────────────────
# 내부 헬퍼(외부 유틸 무의존)
# ─────────────────────────────────────────────────────────────
_SPREAD_RE = re.compile(r"/spreadsheets/d/([A-Za-z0-9\-_]+)")

def extract_sheet_id(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    m = _SPREAD_RE.search(s)
    if m:
        return m.group(1)
    # 이미 ID만 들어온 경우(문자+숫자+_- 25자 이상)
    if re.fullmatch(r"[A-Za-z0-9\-_]{25,}", s):
        return s
    return None

def sheet_link(sid: str | None) -> str:
    if not sid:
        return ""
    return f"https://docs.google.com/spreadsheets/d/{sid}/edit#gid=0"

def _safe_save_env(key: str, value: str) -> None:
    """
    로컬 개발 편의용 .env 업데이트. (Cloud에선 무시돼도 OK)
    절대 실패로 앱이 죽지 않게 try/except
    """
    try:
        env_path = ROOT / ".env"
        mapping: dict[str, str] = {}
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                mapping[k.strip()] = v.strip()
        mapping[key] = value
        env_path.write_text(
            "\n".join(f"{k}={v}" for k, v in mapping.items()) + "\n",
            encoding="utf-8",
        )
    except Exception:
        # Cloud 환경 등에서 권한/파일 문제 시 조용히 무시
        pass

# ─────────────────────────────────────────────────────────────
# 공개 API: 사이드바 렌더
# ─────────────────────────────────────────────────────────────
def render_profile_sidebar(
    *,
    sheet_key: str,
    host_key: str,
    sheet_label: str = "Google Sheets URL",
    host_label: str = "Image Hosting URL",
) -> None:
    """
    사용자 프로필의 특정 키(sheet_key/host_key)를 편집/저장하는 사이드바 컴포넌트.
    - user_manager의 프로필 값을 기본값으로 표시
    - 저장 시 user_manager에 반영 + session_state 갱신
    """
    with st.sidebar:
        if not is_logged_in():
            st.warning("로그인이 필요합니다.")
            return

        st.subheader("⚙️ 프로필 설정")

        # 현재 값 (없으면 레거시 키에서 폴백)
        cur_sid = get_user_pref(sheet_key, "") or get_user_pref("sheet_id", "")
        cur_host = (
            get_user_pref(host_key, "")
            or get_user_pref("image_host", "")
            or get_user_pref("default_image_host", "")
        )

        # 입력 폼
        sheet_url = st.text_input(
            sheet_label,
            value=sheet_link(cur_sid) if cur_sid else "",
            placeholder="https://docs.google.com/spreadsheets/d/...",
            key=f"{sheet_key}_url",
        )
        image_host = st.text_input(
            host_label,
            value=cur_host or "",
            placeholder="예: https://example.com/",
            key=f"{host_key}_host",
        )

        col1, col2 = st.columns(2)
        if col1.button("저장", use_container_width=True):
            sid = extract_sheet_id(sheet_url)
            if not sid:
                st.error("올바른 Google Sheets URL을 입력해주세요.")
                return
            if image_host and not image_host.startswith(("http://", "https://")):
                st.error("이미지 호스팅 주소를 확인해주세요. (http/https)")
                return

            # user_manager에 저장 (안전 폴백 포함)
            _update_user_profile({sheet_key: sid, host_key: image_host})

            # 세션/레거시/로컬 .env 갱신
            st.session_state[sheet_key] = sid
            st.session_state[host_key] = image_host
            _safe_save_env(sheet_key, sid)
            _safe_save_env(host_key, image_host)

            st.success("프로필이 저장되었습니다.")
            st.rerun()

        if col2.button("취소", use_container_width=True):
            st.rerun()
