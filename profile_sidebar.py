# profile_sidebar.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import streamlit as st
from user_manager import is_logged_in, get_user_pref, update_user_profile
from utils_common import extract_sheet_id, sheet_link, save_env_value  # 기존 유틸 재사용:contentReference[oaicite:2]{index=2}

def render_profile_sidebar():
    if not is_logged_in():
        with st.sidebar:
            st.warning("로그인이 필요합니다.")
        return

    with st.sidebar:
        st.subheader("⚙️ 프로필 설정")
        # 현재 사용자 프로필에서 기본값
        cur_sid   = get_user_pref("sheet_id", "")
        cur_host  = get_user_pref("image_host", "")

        sheet_url = st.text_input(
            "Google Sheets URL",
            value=sheet_link(cur_sid) if cur_sid else "",
            placeholder="https://docs.google.com/spreadsheets/d/...",
            key="profile_sheet_url",
        )
        image_host = st.text_input(
            "Image Hosting URL",
            value=cur_host or "",
            placeholder="예: https://shopeecopy.com/COVER/",
            key="profile_image_host",
        )

        col1, col2 = st.columns(2)
        save_clicked = col1.button("저장", use_container_width=True)
        reset_clicked = col2.button("취소", use_container_width=True)

        if save_clicked:
            sid = extract_sheet_id(sheet_url)
            if not sid:
                st.error("올바른 Google Sheets URL을 입력해주세요.")
                return
            if not image_host or not image_host.startswith(("http://", "https://")):
                st.error("이미지 호스팅 주소를 확인해주세요.")
                return

            # 1) 사용자 프로필(users.json) 업데이트
            update_user_profile({"sheet_id": sid, "image_host": image_host})

            # 2) 세션 키(레거시 호환)도 함께 갱신
            st.session_state["GOOGLE_SHEETS_SPREADSHEET_ID"] = sid
            st.session_state["IMAGE_HOSTING_URL"] = image_host

            # 3) .env도 동기화 (로컬 개발 호환):contentReference[oaicite:3]{index=3}
            save_env_value("GOOGLE_SHEETS_SPREADSHEET_ID", sid)
            save_env_value("IMAGE_HOSTING_URL", image_host)

            st.success("프로필이 저장되었습니다.")
            st.rerun()

        if reset_clicked:
            st.rerun()
