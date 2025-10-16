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
from shopee_creator.creation_steps import export_tem_xlsx, export_tem_csv

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
            "상품등록 시트 URL",
            value=(f"https://docs.google.com/spreadsheets/d/{cur_source_sid}" if cur_source_sid else ""),
            placeholder="https://docs.google.com/spreadsheets/d/...",
        )
        image_host = st.text_input(
            "Image Hosting URL",
            value=cur_img_host or "",
            placeholder="예: https://example.com/",
        )
        submitted = st.form_submit_button("저장")
        if submitted:
            sid = extract_sheet_id(source_url)
            if not sid:
                st.error("올바른 Google Sheets URL을 입력해주세요.")
            elif image_host and not image_host.startswith(("http://", "https://")):
                st.error("이미지 호스팅 주소를 확인해주세요. (http/https)")
            else:
                st.session_state["SOURCE_SPREADSHEET_ID"] = sid
                st.session_state["IMAGE_BASE_URL"] = image_host
                # Shop Code는 본문에서 입력
                if "SHOP_CODE" in st.session_state:
                    del st.session_state["SHOP_CODE"]
                st.success("설정이 저장되었습니다!")
                st.rerun()

for _k in ("DL_XLSX", "DL_CSV"):
    if _k not in st.session_state:
        st.session_state[_k] = None

# ──────────────────────────────────────────────────────────────────────────────
# Main: 실행/초기화 & 단계 실행
# ──────────────────────────────────────────────────────────────────────────────
st.title("Create Template")

st.markdown("---")
st.subheader("1. 파일 및 샵 코드 입력")

# 본문에 샵 코드 입력
sid = st.session_state.get("SOURCE_SPREADSHEET_ID", "")
base_url = st.session_state.get("IMAGE_BASE_URL", "")
shop_code_input = st.text_input(
    "샵 코드 입력",
    value=st.session_state.get("SHOP_CODE", ""),
    placeholder="예: RO, 01 등 커버 이미지 코드와 동일하게 입력하세요.",
)

# 실행 버튼 (아래, 세로 배치)
run_disabled = not (sid and shop_code_input.strip())
run_clicked = st.button("🚀 파일 업로드 및 실행", type="primary", use_container_width=True, disabled=not sid or run_disabled)

if run_clicked:
    shop_code = shop_code_input.strip()
    st.session_state["SHOP_CODE"] = shop_code  # 최신값 반영

    # Controller 준비
    ctrl = ShopeeCreator(st.secrets)
    if base_url or shop_code:
        try:
            ctrl.set_image_base(base_url=base_url, shop_code=shop_code)
        except Exception:
            pass

    reporter = StepReporter()
    st.subheader("실행 로그")

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
            # run_step이 없으면 구(舊) run() 폴백
            reporter.set(name, "⏳ 진행 중 (호환 모드)")
            buf = io.StringIO()
            try:
                with redirect_stdout(buf):
                    ctrl.run(input_sheet_url=f"https://docs.google.com/spreadsheets/d/{sid}")
                out = buf.getvalue().strip()
                if out:
                    reporter.log(out)
                reporter.set(name, "✅ 완료")
            except Exception:
                out = buf.getvalue().strip()
                if out:
                    reporter.log(out)
                reporter.log(traceback.format_exc())
                reporter.set(name, "❌ 실패")
                reporter.banner(False, f"실행 실패: {name} 단계에서 오류가 발생했습니다.")
                ok = False
                break
        except Exception:
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

        # [ADD] 실행 직후 바로 내보내기 파일 생성 → 세션 저장 (버튼 즉시 활성화)
        try:
            # sid는 위에서 세션에서 읽은 SOURCE_SPREADSHEET_ID (key)
            sh = ctrl.gs.open_by_key(sid)

            xio = export_tem_xlsx(sh)  # BytesIO or None
            if xio:
                st.session_state["DL_XLSX"] = xio.getvalue()
                st.session_state["DL_CSV"] = None
            else:
                csv_bytes = export_tem_csv(sh)  # bytes or None
                st.session_state["DL_XLSX"] = None
                st.session_state["DL_CSV"] = csv_bytes
        except Exception as ex:
            st.warning(f"다운로드 생성 중 오류: {ex}")


# --------------------------------------------------------------------
# 2. 최종 파일 다운로드 (항상 표시: 준비되면 자동 활성화)
# --------------------------------------------------------------------
st.markdown("---")
st.subheader("2. 최종 파일 다운로드")

file_base = (st.session_state.get("SHOP_CODE") or "TEM") + "_TEM_OUTPUT"
xlsx_bytes = st.session_state.get("DL_XLSX")
csv_bytes  = st.session_state.get("DL_CSV")

st.download_button(
    "📥 템플릿 파일 다운로드 (.xlsx)",
    data=(xlsx_bytes or b""),
    file_name=f"{file_base}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
    disabled=not bool(xlsx_bytes),
)

st.download_button(
    "📥 템플릿 파일 다운로드 (.CSV)",
    data=(csv_bytes or b""),
    file_name=f"{file_base}.csv",
    mime="text/csv",
    use_container_width=True,
    disabled=not bool(csv_bytes),
)
