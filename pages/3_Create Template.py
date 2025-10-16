# pages/3_Create Template.py
# -*- coding: utf-8 -*-

import streamlit as st
import io
import traceback
from contextlib import redirect_stdout
from pathlib import Path
import sys

# ──────────────────────────────────────────────────────────────────────────────
# Page config & import path (Copy Template 스타일)
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Create Template", layout="wide")

ROOT = Path(__file__).resolve().parents[1]  # .../shopee
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 프로젝트 모듈
from shopee_creator.controller import ShopeeCreator
from shopee_creator.utils_creator import extract_sheet_id, get_env

# ──────────────────────────────────────────────────────────────────────────────
# Helper: StepReporter (단계별 상태/로그/배너)
# ──────────────────────────────────────────────────────────────────────────────
class StepReporter:
    """단계별 진행 상황/로그를 실시간으로 렌더링"""
    def __init__(self):
        self.status_area = st.empty()
        self.log_area = st.empty()
        self.rows = []  # [(step, status)]

    def set(self, step: str, status: str):
        # 상태 테이블 갱신
        for i, (s, _) in enumerate(self.rows):
            if s == step:
                self.rows[i] = (step, status)
                break
        else:
            self.rows.append((step, status))
        md = "| 단계 | 상태 |\n|---|---|\n" + "\n".join(f"| {s} | {t} |" for s, t in self.rows)
        self.status_area.markdown(md)

    def log(self, text: str):
        if text:
            self.log_area.code(text, language="text")

    def banner(self, ok: bool, text: str):
        (st.success if ok else st.error)(text)


# ──────────────────────────────────────────────────────────────────────────────
# Sidebar: 설정 폼 (Copy Template 톤&매너)
# ──────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.subheader("⚙️ 초기 설정")

    cur_source_sid = st.session_state.get(
        "SOURCE_SPREADSHEET_ID",
        get_env("SOURCE_SPREADSHEET_ID", "")
    )
    cur_img_host = st.session_state.get(
        "IMAGE_BASE_URL",
        get_env("IMAGE_BASE_URL", "")
    )
    cur_shop_code = st.session_state.get(
        "SHOP_CODE",
        get_env("SHOP_CODE", "")
    )

    with st.form("settings_form_create_template"):
        source_url = st.text_input(
            "상품등록 시트 URL (필수)",
            value=(f"https://docs.google.com/spreadsheets/d/{cur_source_sid}" if cur_source_sid else ""),
            placeholder="https://docs.google.com/spreadsheets/d/...",
        )
        image_host = st.text_input(
            "Image Hosting URL (선택 / 커버·상세 규칙 base)",
            value=cur_img_host or "",
            placeholder="예: https://cdn.example.com/SHOPCODE/",
        )
        shop_code = st.text_input(
            "Shop Code",
            value=cur_shop_code or "",
            placeholder="예: KIKI",
        )
        submitted = st.form_submit_button("저장")
        if submitted:
            sid = extract_sheet_id(source_url)
            if not sid:
                st.error("올바른 Google Sheets URL을 입력해주세요.")
            elif image_host and not image_host.startswith(("http://", "https://")):
                st.error("이미지 호스팅 주소를 확인해주세요. (http/https)")
            else:
                # 세션 저장
                st.session_state["SOURCE_SPREADSHEET_ID"] = sid
                st.session_state["IMAGE_BASE_URL"] = image_host
                st.session_state["SHOP_CODE"] = shop_code
                st.success("설정이 저장되었습니다!")
                st.rerun()

# ──────────────────────────────────────────────────────────────────────────────
# Main: 실행/초기화 & 단계 실행
# ──────────────────────────────────────────────────────────────────────────────
st.title("Create Template")
st.caption("C1 → C2 → C7 → C3 → C4 → C5 → C6 순서로 템플릿 생성/보정")

st.divider()
col1, col2 = st.columns([1, 1], gap="small")
with col1:
    run_clicked = st.button("실행", type="primary", use_container_width=True)
with col2:
    reset_clicked = st.button("초기화", use_container_width=True)

if reset_clicked:
    for k in ("SOURCE_SPREADSHEET_ID", "IMAGE_BASE_URL", "SHOP_CODE"):
        if k in st.session_state:
            del st.session_state[k]
    st.rerun()

if run_clicked:
    sid = st.session_state.get("SOURCE_SPREADSHEET_ID", "")
    base_url = st.session_state.get("IMAGE_BASE_URL", "")
    shop_code = st.session_state.get("SHOP_CODE", "")

    if not sid:
        st.error("사이드바에서 '상품등록 시트 URL'을 먼저 저장해 주세요.")
        st.stop()

    # Controller 준비
    ctrl = ShopeeCreator(st.secrets)
    if base_url or shop_code:
        try:
            ctrl.set_image_base(base_url=base_url, shop_code=shop_code)
        except Exception:
            # set_image_base 없거나 실패해도 치명적이지 않음
            pass

    reporter = StepReporter()
    st.subheader("실행 로그")

    # 단계 정의 (컨트롤러에 run_step(tag, ...)가 있을 때)
    steps = [
        ("C1 Initialize",           lambda: ctrl.run_step("C1", source_url=f"https://docs.google.com/spreadsheets/d/{sid}")),
        ("C2 Collection → TEM",     lambda: ctrl.run_step("C2")),
        ("C7 Mandatory Defaults",   lambda: ctrl.run_step("C7")),
        ("C3 FDA",                  lambda: ctrl.run_step("C3")),
        ("C4 Prices",               lambda: ctrl.run_step("C4")),
        ("C5 Images",               lambda: ctrl.run_step("C5")),
        ("C6 Stock/Weight/Brand",   lambda: ctrl.run_step("C6")),
    ]

    ok = True
    for name, fn in steps:
        reporter.set(name, "⏳ 진행 중")
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                fn()
            out = buf.getvalue().strip()
            if out:
                reporter.log(out)
            reporter.set(name, "✅ 완료")
        except AttributeError:
            # 컨트롤러에 run_step이 없는 경우: 기존 ctrl.run(...)으로 폴백
            reporter.set(name, "⏳ 진행 중 (호환 모드)")
            buf = io.StringIO()
            try:
                with redirect_stdout(buf):
                    # 기존 run(input_sheet_url=...) 시그니처 가정
                    ctrl.run(input_sheet_url=f"https://docs.google.com/spreadsheets/d/{sid}")
                out = buf.getvalue().strip()
                if out:
                    reporter.log(out)
                reporter.set(name, "✅ 완료")
            except Exception as e:
                out = buf.getvalue().strip()
                if out:
                    reporter.log(out)
                reporter.log(traceback.format_exc())
                reporter.set(name, "❌ 실패")
                reporter.banner(False, f"실행 실패: {name} 단계에서 오류가 발생했습니다.")
                ok = False
                break
        except Exception as e:
            out = buf.getvalue().strip()
            if out:
                reporter.log(out)
            reporter.log(traceback.format_exc())
            reporter.set(name, "❌ 실패")
            reporter.banner(False, f"실행 실패: {name} 단계에서 오류가 발생했습니다.")
            ok = False
            break

    if ok:
        reporter.banner(True, "모든 단계가 정상 완료되었습니다! 🎉")
