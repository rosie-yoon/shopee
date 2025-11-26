# pages/3_Create Template.py (v6 clean)
# -*- coding: utf-8 -*-

from pathlib import Path
import sys
import io
import time
import traceback
import os
from contextlib import redirect_stdout
import streamlit as st

# ──────────────────────────────────────────────
# Page Config
# ──────────────────────────────────────────────
st.set_page_config(page_title="Create Template", layout="wide")

# ──────────────────────────────────────────────
# Project Path Fix
# ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

# ──────────────────────────────────────────────
# Internal Imports
# ──────────────────────────────────────────────
from auth_guard import bootstrap_auth
from user_manager import get_user_pref
from profile_sidebar import render_profile_sidebar, extract_sheet_id

from shopee_creator.controller import ShopeeCreator
from shopee_creator.utils_creator import get_env
import shopee_creator.creation_steps as steps
from shopee_creator.creation_steps import export_tem_xlsx

# ──────────────────────────────────────────────
# Auth Bootstrap
# ──────────────────────────────────────────────
bootstrap_auth(go_home=False)

# ──────────────────────────────────────────────
# Header
# ──────────────────────────────────────────────
st.title("Create Template")
st.caption("템플릿 생성 / 전처리 / 내보내기")
st.markdown("---")

# ──────────────────────────────────────────────
# Sidebar: User Profile (Create 전용 키 사용)
# ──────────────────────────────────────────────
render_profile_sidebar(
    sheet_key="create_sheet_id",
    host_key="create_image_host",
    sheet_label="상품등록 시트 URL",
    host_label="Image Hosting URL",
)

# ──────────────────────────────────────────────
# Resolve Sheet ID & Host from Session / Profile / Secret
# ──────────────────────────────────────────────
def resolve_create_sid() -> str:
    sid = (st.session_state.get("SOURCE_SPREADSHEET_ID") or "").strip()
    if not sid:
        raw = get_user_pref("create_sheet_id") or get_user_pref("sheet_id")
        sid = extract_sheet_id(str(raw)) if raw else ""
    if not sid:
        raw = (
            st.secrets.get("SOURCE_SPREADSHEET_ID")
            or st.secrets.get("GOOGLE_SHEETS_SPREADSHEET_ID")
            or st.secrets.get("GOOGLE_SHEET_KEY")
        )
        sid = extract_sheet_id(str(raw)) if raw else ""
    return sid or ""

def resolve_create_host() -> str:
    return (
        st.session_state.get("IMAGE_BASE_URL")
        or get_user_pref("create_image_host")
        or get_user_pref("image_host")
        or get_user_pref("default_image_host")
        or ""
    )

sid = resolve_create_sid()
host = resolve_create_host()

st.session_state["SOURCE_SPREADSHEET_ID"] = sid
st.session_state["IMAGE_BASE_URL"] = host

# 기본 세션값
st.session_state.setdefault("DL_XLSX", None)
st.session_state.setdefault("DL_TEXT", None)

# ──────────────────────────────────────────────
# 1. 입력 구역
# ──────────────────────────────────────────────
st.subheader("1. 파일 및 샵 코드 입력")

with st.sidebar:
    if not sid:
        st.warning("상품등록 시트 URL/ID가 설정되지 않았습니다. 사이드바에서 저장 후 다시 시도하세요.")
    else:
        st.caption(f"Source Sheet ID: `{sid}`")
    if host:
        st.caption(f"Image Base URL: {host}")

shop_code_input = st.text_input(
    "샵 코드 입력",
    value=st.session_state.get("SHOP_CODE", ""),
    placeholder="예: RO, 01 등 커버 이미지 코드와 동일하게 입력하세요.",
)
run_enabled = bool(sid and shop_code_input.strip())
run_clicked = st.button("🚀 실행", type="primary", use_container_width=True, disabled=not run_enabled)

# ──────────────────────────────────────────────
# 2. 실행 및 생성
# ──────────────────────────────────────────────
if run_clicked:
    shop_code = shop_code_input.strip()
    st.session_state["SHOP_CODE"] = shop_code

    ctrl = ShopeeCreator(st.secrets)
    if base_url := host:
        try:
            ctrl.set_image_base(base_url=base_url, shop_code=shop_code)
        except Exception:
            pass

    try:
        gs = ctrl.gs
        sh = gs.open_by_key(sid)
    except Exception as e:
        st.error(f"입력 시트 열기 실패: {e}")
        st.stop()

    ref_id_or_url = (
        st.secrets.get("REFERENCE_SPREADSHEET_ID")
        or st.secrets.get("REFERENCE_SPREADSHEET_URL")
        or ""
    )
    try:
        rid = extract_sheet_id(str(ref_id_or_url))
        ref = gs.open_by_key(rid)
    except Exception as e:
        st.error(f"레퍼런스 시트 열기 실패: secrets에 REFERENCE_SPREADSHEET_ID/URL을 확인하세요.\n\nError: {e}")
        st.stop()

    progress = st.progress(0.0, text="시작합니다…")

    run_list = [
        ("C1 Initialize", lambda: steps.run_step_C1(sh, ref)),
        ("C2 Collection → TEM", lambda: steps.run_step_C2(sh, ref)),
        ("C7 Mandatory Defaults", lambda: steps.run_step_C7_mandatory_defaults(sh, ref)),
        ("C3 FDA", lambda: steps.run_step_C3_fda(sh, ref)),
        ("C4 Prices", lambda: steps.run_step_C4_prices(sh)),
        ("C5 Images", lambda: steps.run_step_C5_images(sh=sh, base_url=base_url, shop_code=shop_code)),
        ("C6 Stock/Weight/Brand", lambda: steps.run_step_C6_stock_weight_brand(sh)),
    ]

    total = len(run_list)
    ok = True

    for i, (name, fn) in enumerate(run_list, start=1):
        try:
            progress.progress((i - 1) / total, text=f"{name} 실행 중…")
            with redirect_stdout(io.StringIO()):
                fn()
            time.sleep(0.2)
            progress.progress(i / total, text=f"{name} 완료")
        except Exception:
            progress.progress((i - 1) / total, text=f"{name} 실패")
            st.error(f"실행 실패: {name} 단계에서 오류가 발생했습니다.")
            with st.expander("자세한 오류", expanded=False):
                st.code(traceback.format_exc())
            ok = False
            break

    if ok:
        progress.progress(1.0, text="모든 단계 완료 ✅")
        st.success("모든 단계가 정상 완료되었습니다! 🎉")

        # ───── 다운로드 생성 (바이트 형식 검증)
        try:
            out = export_tem_xlsx(sh)
            xlsx_bytes, txt_fallback = None, None

            if hasattr(out, "getbuffer"):
                xlsx_bytes = out.getbuffer().tobytes()
            elif hasattr(out, "getvalue"):
                gv = out.getvalue()
                if isinstance(gv, (bytes, bytearray)):
                    xlsx_bytes = gv
                elif isinstance(gv, str):
                    txt_fallback = gv
            elif isinstance(out, bytes):
                xlsx_bytes = out
            elif isinstance(out, str):
                txt_fallback = out

            if xlsx_bytes and not xlsx_bytes.startswith(b"PK\x03\x04"):
                txt_fallback = xlsx_bytes.decode("utf-8", errors="ignore")
                xlsx_bytes = None

            st.session_state["DL_XLSX"] = xlsx_bytes
            st.session_state["DL_TEXT"] = txt_fallback

            if xlsx_bytes:
                st.success("엑셀 파일을 생성했습니다.")
            elif txt_fallback:
                st.warning("엑셀 형식이 아닌 텍스트 결과가 생성되었습니다. 아래에서 텍스트로 다운로드 가능합니다.")
            else:
                st.warning("출력 데이터가 없습니다. TEM_OUTPUT 시트를 확인하세요.")
        except Exception as ex:
            st.session_state["DL_XLSX"] = None
            st.session_state["DL_TEXT"] = None
            st.error(f"다운로드 생성 중 오류: {ex}")

# ──────────────────────────────────────────────
# 3. 최종 파일 다운로드
# ──────────────────────────────────────────────
st.markdown("---")
st.subheader("2. 최종 파일 다운로드")

file_base = (st.session_state.get("SHOP_CODE") or "TEM") + "_TEM_OUTPUT"

try:
    # export_tem_xlsx() 결과를 확실히 바이트로 변환
    out = st.session_state.get("DL_XLSX")
    if not out:
        from shopee_creator.creation_steps import export_tem_xlsx

        ctrl = ShopeeCreator(st.secrets)
        gs = ctrl.gs
        sid = st.session_state.get("SOURCE_SPREADSHEET_ID")
        sh = gs.open_by_key(sid)

        # export_tem_xlsx → 이제 bytes 또는 None 반환
        out = export_tem_xlsx(sh)

        if out:
            st.download_button(
                label="템플릿 다운로드 (xlsx)",
                data=out,
                file_name="Shopee_Create_Template.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        else:
            st.warning(
                "Google Sheets 읽기 요청이 너무 많아 쿼터 제한(RATE LIMIT)에 걸렸어요.\n"
                "1~2분 후에 다시 시도해 주세요!"
            )

    # 엑셀 매직 헤더 확인 (PK 시작)
    if isinstance(out, (bytes, bytearray)) and out[:2] == b"PK":
        st.download_button(
            "📥 템플릿 파일 다운로드 (.xlsx)",
            data=out,
            file_name=f"{file_base}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    else:
        st.error("❌ 생성된 파일이 올바른 엑셀 형식이 아닙니다. TEM_OUTPUT 시트를 확인해 주세요.")
except Exception as e:
    st.error(f"다운로드 생성 중 오류 발생: {e}")
