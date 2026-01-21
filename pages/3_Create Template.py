# pages/3_Create Template.py (clean full replacement v7)
# -*- coding: utf-8 -*-

from pathlib import Path
import sys
import io
import time
import traceback
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
# Sidebar (프로필)
# ──────────────────────────────────────────────
render_profile_sidebar(
    sheet_key="create_sheet_id",
    host_key="create_image_host",
    sheet_label="상품등록 시트 URL",
    host_label="Image Hosting URL",
)

# ──────────────────────────────────────────────
# Helpers — 프로필 우선 로딩 (절대 순서 깨지면 안됨)
# ──────────────────────────────────────────────
def resolve_create_sid() -> str:
    # 1) 프로필 최우선
    raw = (
        get_user_pref("create_sheet_id")
        or get_user_pref("sheet_id")
    )
    if raw:
        sid = extract_sheet_id(str(raw))
        if sid:
            return sid

    # 2) 세션 값 (이제 뒤로)
    sid = (st.session_state.get("SOURCE_SPREADSHEET_ID") or "").strip()
    if sid:
        return sid

    # 3) 환경
    raw = (
        get_env("SOURCE_SPREADSHEET_ID")
        or get_env("GOOGLE_SHEETS_SPREADSHEET_ID")
        or get_env("GOOGLE_SHEET_KEY")
    )
    sid = extract_sheet_id(str(raw)) if raw else ""
    return sid or ""

def resolve_create_host() -> str:
    # 1) 프로필 최우선
    host = (
        get_user_pref("create_image_host")
        or get_user_pref("image_host")
        or get_user_pref("default_image_host")
    )
    if host:
        return host

    # 2) 세션
    host = st.session_state.get("IMAGE_BASE_URL")
    if host:
        return host

    # 3) 환경
    return get_env("IMAGE_HOSTING_URL") or ""

# ──────────────────────────────────────────────
# Resolve (확정 값)
# ──────────────────────────────────────────────
sid = resolve_create_sid()
host = resolve_create_host()

st.session_state["SOURCE_SPREADSHEET_ID"] = sid
st.session_state["IMAGE_BASE_URL"] = host

# 기본 상태
st.session_state.setdefault("DL_XLSX", None)
st.session_state.setdefault("DL_TEXT", None)

# ──────────────────────────────────────────────
# 1. 입력
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
# 2. 실행
# ──────────────────────────────────────────────
if run_clicked:
    shop_code = shop_code_input.strip()
    st.session_state["SHOP_CODE"] = shop_code

    # Creator: get_env 사용 → secrets 없어도 crash X
    ctrl = ShopeeCreator(st.secrets)

    if host:
        try:
            ctrl.set_image_base(base_url=host, shop_code=shop_code)
        except Exception:
            pass

    # 원본 시트 열기
    try:
        gs = ctrl.gs
        sh = gs.open_by_key(sid)
    except Exception as e:
        st.error(f"입력 시트 열기 실패: {e}")
        st.stop()

    # Reference 시트
    ref_raw = (
        get_user_pref("reference_sheet_id")
        or get_env("REFERENCE_SPREADSHEET_ID")
        or get_env("REFERENCE_SHEET_KEY")
        or ""
    )
    try:
        ref_id = extract_sheet_id(ref_raw)
        ref = gs.open_by_key(ref_id)
    except Exception as e:
        st.error(f"레퍼런스 시트 열기 실패: secrets/env의 REFERENCE_SPREADSHEET_ID/KEY를 확인하세요.\n\nError: {e}")
        st.stop()

    progress = st.progress(0.0, text="시작합니다…")

    run_list = [
        ("C1 Initialize", lambda: steps.run_step_C1(sh, ref)),
        ("C2 Collection → TEM", lambda: steps.run_step_C2(sh, ref)),
        ("C7 Mandatory Defaults", lambda: steps.run_step_C7_mandatory_defaults(sh, ref)),
        ("C3 FDA", lambda: steps.run_step_C3_fda(sh, ref)),
        ("C4 Prices", lambda: steps.run_step_C4_prices(sh)),
        ("C5 Images", lambda: steps.run_step_C5_images(sh=sh, base_url=host, shop_code=shop_code)),
        ("C6 Stock/Weight/Brand", lambda: steps.run_step_C6_stock_weight_brand(sh)),
    ]

    total = len(run_list)
    ok = True

    for i, (name, fn) in enumerate(run_list, start=1):
        try:
            progress.progress((i - 1) / total, text=f"{name} 실행 중…")
            with io.StringIO() as buf:
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

        # 다운로드 생성
        try:
            out = export_tem_xlsx(sh)

            if hasattr(out, "getbuffer"):
                out_bytes = out.getbuffer().tobytes()
            elif hasattr(out, "getvalue"):
                gv = out.getvalue()
                out_bytes = gv if isinstance(gv, (bytes, bytearray)) else None
            else:
                out_bytes = out if isinstance(out, (bytes, bytearray)) else None

            if out_bytes and out_bytes.startswith(b"PK"):
                st.session_state["DL_XLSX"] = out_bytes
                st.success("엑셀 파일을 생성했습니다.")
            else:
                st.session_state["DL_XLSX"] = None
                st.warning("엑셀 형식이 아닙니다. TEM_OUTPUT 시트를 확인하세요.")

        except Exception as ex:
            st.session_state["DL_XLSX"] = None
            st.error(f"다운로드 생성 중 오류: {ex}")

# ──────────────────────────────────────────────
# 3. 다운로드 UI
# ──────────────────────────────────────────────
st.markdown("---")
st.subheader("2. 최종 파일 다운로드")

file_base = (st.session_state.get("SHOP_CODE") or "TEM") + "_TEM_OUTPUT"

try:
    out = st.session_state.get("DL_XLSX")

    if isinstance(out, (bytes, bytearray)) and out[:2] == b"PK":
        st.download_button(
            "📥 템플릿 파일 다운로드 (.xlsx)",
            data=out,
            file_name=f"{file_base}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    else:
        st.info("엑셀 파일이 생성되면 여기에 다운로드 버튼이 표시됩니다.")
except Exception as e:
    st.error(f"다운로드 생성 중 오류: {e}")
