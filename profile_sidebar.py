# profile_sidebar.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import re
from pathlib import Path
import streamlit as st

# 루트 경로를 sys.path에 추가 (Cloud/Local 호환)
import sys
ROOT = Path(__file__).resolve().parent         # .../shopee
PARENT = ROOT.parent                           # .../mount/src
for p in (ROOT, PARENT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# user_manager만 의존 (필수)
from user_manager import is_logged_in, get_user_pref, update_user_profile

# ------------------------
# 내부 헬퍼(외부 유틸 무의존)
# ------------------------
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
        mapping = {}
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                mapping[k.strip()] = v.strip()
        mapping[key] = value
        env_path.write_text(
            "\n".join(f"{k}={v}" for k, v in mapping.items()) + "\n",
            encoding="utf-8"
        )
    except Exception:
        pass

# ------------------------
# 공개 API: 사이드바 렌더
# ------------------------
def render_profile_sidebar(
    *,
    sheet_key: str,
    host_key: str,
    sheet_label: str = "Google Sheets URL",
    host_label: str = "Image Hosting URL",
) -> None:
    """
    사용자 프로필의 특정 키(sheet_key/host_key)를 편집/저장하는 사이드바 컴포넌트.
    - users.json의 해당 키를 가져와 기본값 표시
    - 저장 시 users.json + session_state + (옵션) .env를 업데이트
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
            value=(sheet_link(cur_sid) if cur_sid else ""),
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

            # users.json 업데이트
            update_user_profile({sheet_key: sid, host_key: image_host})

            # 세션/레거시/로컬 .env 갱신
            st.session_state[sheet_key] = sid
            st.session_state[host_key] = image_host
            _safe_save_env(sheet_key, sid)
            _safe_save_env(host_key, image_host)

            st.success("프로필이 저장되었습니다.")
            st.rerun()

        if col2.button("취소", use_container_width=True):
            st.rerun()
