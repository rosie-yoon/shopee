from __future__ import annotations
from pathlib import Path
import io
import zipfile
import re
from datetime import datetime

import streamlit as st
from PIL import Image as PILImage

from image_compose.composer_utils import (
    compose_one_bytes,
    SHADOW_PRESETS,
    has_useful_alpha,
    ensure_rgba,
    load_images_from_folder
)

BASE_DIR = Path(__file__).resolve().parent


# ---------- Streamlit 호환 이미지 렌더 ----------
def _st_image(img, width: int | None = None, **kwargs):
    """버전별 호환성 + 중앙 정렬"""
    container = st.container()
    _, center_col, _ = container.columns([1, 4, 1])
    with center_col:
        if width is not None:
            return st.image(img, width=width, **kwargs)
        try:
            return st.image(img, use_container_width=True, **kwargs)
        except TypeError:
            kwargs.pop("use_container_width", None)
            try:
                return st.image(img, use_column_width=True, **kwargs)
            except TypeError:
                kwargs.pop("use_column_width", None)
                return st.image(img, **kwargs)


def _to_streamlit_image_input(x):
    """Streamlit이 받는 타입으로 정규화"""
    if x is None: return None
    if isinstance(x, (bytes, bytearray)): return x
    if isinstance(x, PILImage.Image): return x
    if hasattr(x, "getvalue"):
        try:
            return x.getvalue()
        except:
            pass
    if hasattr(x, "read"):
        try:
            return x.read()
        except:
            pass
    if isinstance(x, (str, Path)) and Path(x).exists(): return str(x)
    return None


# ---------- 템플릿 파일명 유효성 검사 ----------
def validate_template_names(files):
    """
    템플릿 파일명 검사:
    1. 영문, 숫자, 언더스코어, 하이픈만 허용
    2. 중복된 이름(확장자 제외) 방지
    """
    if not files:
        return True, []

    seen_stems = set()
    errors = []
    pattern = re.compile(r'^[a-zA-Z0-9_-]+$')

    for f in files:
        stem = Path(f.name).stem

        if not pattern.match(stem):
            errors.append(f"'{f.name}' - 영문, 숫자, _, - 만 사용 가능합니다")
            continue

        if stem in seen_stems:
            errors.append(f"'{stem}' - 중복된 템플릿명입니다 (확장자가 달라도 불가)")
        else:
            seen_stems.add(stem)

    return (False, errors) if errors else (True, [])


# ---------- 조합 분석 시스템 ----------
def analyze_combinations(item_files, template_files):
    """
    상품-템플릿 조합 분석:
    - PNG 템플릿: 흰배경 + 액자 모드
    - JPG 템플릿: 일반 모드 (투명 배경 필요)
    """
    valid_combinations = []
    invalid_combinations = []

    for item_file in item_files:
        try:
            item_img = PILImage.open(io.BytesIO(item_file.getvalue()))
            has_alpha = has_useful_alpha(ensure_rgba(item_img))
        except:
            continue

        for template_file in template_files:
            template_ext = Path(template_file.name).suffix.lower()
            is_png_template = (template_ext == '.png')

            if has_alpha:
                # 투명 배경 있음 - 모든 템플릿 조합 가능
                mode = 'frame' if is_png_template else 'normal'
                valid_combinations.append((item_file, template_file, mode))
            else:
                # 투명 배경 없음 - PNG 템플릿만 가능
                if is_png_template:
                    valid_combinations.append((item_file, template_file, 'frame'))
                else:
                    invalid_combinations.append((item_file, template_file, '투명배경 없음 + JPG 템플릿'))

    return {
        'valid_combinations': valid_combinations,
        'invalid_combinations': invalid_combinations,
        'summary': {
            'total': len(valid_combinations) + len(invalid_combinations),
            'valid': len(valid_combinations),
            'invalid': len(invalid_combinations)
        }
    }


def run():
    PREVIEW_SCALE = 0.3
    st.title("Cover Image")

    # ---- 세션 상태 초기화 ----
    def init_state():
        defaults = {
            "anchor": "center",
            "resize_ratio": 1.0,
            "shadow_preset": "off",
            "item_uploader_key": 0,
            "template_uploader_key": 0,
            "preview_img": None,
            "preview_list": [],
            "preview_idx": 0,
            "preview_sig": None,
            "combination_analysis": None,
        }
        for k, v in defaults.items():
            st.session_state.setdefault(k, v)

    init_state()
    ss = st.session_state

    # ---------- 유틸리티 함수들 ----------
    def _files_fingerprint(files):
        """파일 시그니처 생성 (캐싱용)"""
        if not files:
            return []
        fps = []
        for f in files:
            try:
                fps.append((f.name, f.size))
            except:
                fps.append(("unknown", 0))
        return fps

    def _options_signature():
        """설정 옵션 시그니처 생성"""
        return (ss.anchor, float(ss.resize_ratio), ss.shadow_preset)

    # ---- 미리보기 업데이트 함수 ----
    def update_preview(item_files, template_files):
        """단일 미리보기 생성"""
        ss.preview_img = None
        if not item_files or not template_files:
            return

        item_file = item_files[0]
        template_file = template_files[0]

        try:
            item_img = PILImage.open(io.BytesIO(item_file.getvalue()))
            template_img = PILImage.open(io.BytesIO(template_file.getvalue()))
        except:
            return

        # 확장자로 자동 모드 결정
        template_ext = Path(template_file.name).suffix.lower()
        composition_mode = "frame" if template_ext == ".png" else "normal"

        # 조합 유효성 검사
        has_alpha = has_useful_alpha(ensure_rgba(item_img))
        if not has_alpha and composition_mode == "normal":
            ss.preview_img = None
            return

        # 그림자는 normal 모드에서만 적용
        shadow_preset = ss.shadow_preset if composition_mode == "normal" else "off"

        opts = {
            "anchor": ss.anchor,
            "resize_ratio": ss.resize_ratio,
            "shadow_preset": shadow_preset,
            "out_format": "PNG",  # 미리보기는 PNG 고정
            "composition_mode": composition_mode,
        }

        result = compose_one_bytes(item_img, template_img, **opts)
        if result:
            ss.preview_img = result[0].getvalue()

    def generate_preview_list(item_files, template_files, max_count: int = 12):
        """다중 미리보기 리스트 생성"""
        ss.preview_list = []
        ss.preview_idx = 0
        if not item_files or not template_files:
            return

        analysis = analyze_combinations(item_files, template_files)
        valid_combinations = analysis['valid_combinations']

        out = []
        for item_file, template_file, mode in valid_combinations:
            if len(out) >= max_count:
                break

            try:
                item_img = PILImage.open(io.BytesIO(item_file.getvalue()))
                template_img = PILImage.open(io.BytesIO(template_file.getvalue()))
            except:
                continue

            template_ext = Path(template_file.name).suffix.lower()
            composition_mode = "frame" if template_ext == ".png" else "normal"
            shadow_preset = ss.shadow_preset if composition_mode == "normal" else "off"

            opts = {
                "anchor": ss.anchor,
                "resize_ratio": ss.resize_ratio,
                "shadow_preset": shadow_preset,
                "out_format": "PNG",  # ✅ 수정: fmt 대신 PNG 고정값
                "composition_mode": composition_mode,
            }

            result = compose_one_bytes(item_img, template_img, **opts)
            if result:
                out.append(result[0].getvalue())

        ss.preview_list = out

    # ---- 배치 합성 & Zip 생성 ----
    def run_batch_composition(analysis, fmt, quality):
        """최종 배치 합성 (매개변수로 fmt 받음)"""
        zip_buf = io.BytesIO()
        count = 0

        valid_combinations = analysis['valid_combinations']

        with zipfile.ZipFile(zip_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for item_file, template_file, mode in valid_combinations:
                try:
                    item_img = PILImage.open(io.BytesIO(item_file.getvalue()))
                    template_img = PILImage.open(io.BytesIO(template_file.getvalue()))
                except:
                    continue

                template_ext = Path(template_file.name).suffix.lower()
                composition_mode = "frame" if template_ext == ".png" else "normal"
                shadow_preset = ss.shadow_preset if composition_mode == "normal" else "off"

                opts = {
                    "anchor": ss.anchor,
                    "resize_ratio": ss.resize_ratio,
                    "shadow_preset": shadow_preset,
                    "out_format": fmt,  # 배치에서는 매개변수 fmt 사용
                    "quality": quality,
                    "composition_mode": composition_mode,
                }

                result = compose_one_bytes(item_img, template_img, **opts)
                if result:
                    img_buf, ext = result
                    item_name = Path(item_file.name).stem
                    template_code = Path(template_file.name).stem
                    filename = f"{item_name}_C_{template_code}.{ext}"
                    zf.writestr(filename, img_buf.getvalue())
                    count += 1

        zip_buf.seek(0)
        return zip_buf, count

    # ================= UI 레이아웃 =================
    left, right = st.columns([1, 1])

    with left:
        st.subheader("이미지 업로드")

        # 자동 모드 안내
        st.info("""
        **🤖 자동 합성 모드**
        - **PNG 템플릿**: 흰배경 + 액자 모드 (상품이 템플릿 안에)
        - **JPG 템플릿**: 일반 모드 (상품이 템플릿 위에)
        """)

        # 아이템 업로드
        item_files = st.file_uploader(
            "1. Item 이미지 업로드",
            type=["png", "webp", "jpg", "jpeg"],
            accept_multiple_files=True,
            key=f"item_{ss.item_uploader_key}",
            help="투명 배경 PNG/WEBP 권장"
        )
        if st.button("아이템 리스트 삭제", key="btn_clear_items"):
            ss.item_uploader_key += 1
            st.rerun()

        # 템플릿 업로드
        template_files = st.file_uploader(
            "2. Template 이미지 업로드 (파일명 = 샵코드)",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
            key=f"tpl_{ss.template_uploader_key}",
            help="PNG: 액자 모드 자동 적용 / JPG: 일반 모드 자동 적용"
        )
        if st.button("템플릿 삭제", key="btn_clear_tpls"):
            ss.template_uploader_key += 1
            st.rerun()

        # 템플릿 파일명 유효성 검사
        is_valid_tpl, tpl_errors = validate_template_names(template_files)
        if template_files and not is_valid_tpl:
            st.error("🚨 템플릿 파일명 오류가 발견되었습니다!")
            for err in tpl_errors:
                st.write(f"❌ {err}")
            st.info("💡 파일명을 수정한 후 다시 업로드해주세요.")

        # 조합 분석 및 통계 표시
        if item_files and template_files and is_valid_tpl:
            analysis = analyze_combinations(item_files, template_files)
            ss.combination_analysis = analysis

            summary = analysis['summary']

            if summary['invalid'] > 0:
                st.warning(f"""
                ⚠️ **조합 분석 결과**
                - ✅ 생성 가능: **{summary['valid']}개**
                - ❌ 자동 제외: **{summary['invalid']}개** (투명배경 없음 + JPG 템플릿)
                """)
            else:
                st.success(f"✅ 모든 조합 생성 가능 ({summary['valid']}개)")

    with right:
        st.subheader("이미지 설정")
        c1, c2, c3 = st.columns(3)

        # 배치 위치
        c1.selectbox(
            "배치 위치",
            ["center", "top", "bottom", "left", "right", "top-left", "top-right", "bottom-left", "bottom-right"],
            key="anchor",
        )

        # 리사이즈 비율
        resize_options = [1.3, 1.2, 1.1, 1.0, 0.9, 0.8, 0.7]
        current = ss.get("resize_ratio", 1.0)
        idx = resize_options.index(current) if current in resize_options else resize_options.index(1.0)
        ss["resize_ratio"] = c2.selectbox(
            "리사이즈",
            resize_options,
            index=idx,
            format_func=lambda x: f"{int(round(x * 100))}%",
            key="sel_resize_ratio",
        )

        # 그림자 프리셋
        c3.selectbox(
            "그림자 프리셋",
            list(SHADOW_PRESETS.keys()),
            key="shadow_preset",
            help="JPG 템플릿 + 투명 배경 상품에만 적용됩니다"
        )

        # ---- 미리보기 섹션 ----
        st.subheader("미리보기")

        # 시그니처 기반 자동 갱신
        if is_valid_tpl:
            cur_sig = (
                tuple(_files_fingerprint(item_files)),
                tuple(_files_fingerprint(template_files)),
                _options_signature(),
            )
            if cur_sig != ss.preview_sig:
                update_preview(item_files, template_files)
                generate_preview_list(item_files, template_files)
                ss.preview_sig = cur_sig
        else:
            ss.preview_img = None
            ss.preview_list = []

        # 미리보기 렌더링
        if ss.preview_list:
            n = len(ss.preview_list)
            cprev, ccenter, cnext = st.columns([1, 5, 1])
            with cprev:
                if st.button("◀", use_container_width=True, key="nav_prev"):
                    ss.preview_idx = (ss.preview_idx - 1) % n
            with ccenter:
                st.write(f"**{ss.preview_idx + 1} / {n}**")
            with cnext:
                if st.button("▶", use_container_width=True, key="nav_next"):
                    ss.preview_idx = (ss.preview_idx + 1) % n

            current_bytes = ss.preview_list[ss.preview_idx]
            try:
                _im = PILImage.open(io.BytesIO(current_bytes))
                _w = int(max(1, _im.width * PREVIEW_SCALE))
            except:
                _w = None
            _st_image(_to_streamlit_image_input(current_bytes), caption=f"미리보기 #{ss.preview_idx + 1}", width=_w)

        elif ss.preview_img:
            try:
                _im = PILImage.open(io.BytesIO(ss.preview_img))
                _w = int(max(1, _im.width * PREVIEW_SCALE))
            except:
                _w = None
            _st_image(_to_streamlit_image_input(ss.preview_img), caption="미리보기", width=_w)
        else:
            st.info("이미지를 업로드하면 미리보기가 표시됩니다.")

        st.divider()

        # 생성 & 다운로드 버튼
        btn_disabled = (not item_files or not template_files or not is_valid_tpl)
        date_str = datetime.now().strftime("%y%m%d")
        zip_filename = f"Thumb_Craft_Results_{date_str}.zip"

        if st.button(
                "🎨 이미지 생성 & 다운로드",
                type="primary",
                use_container_width=True,
                disabled=btn_disabled
        ):
            analysis = ss.get('combination_analysis')
            if not analysis:
                st.error("조합 분석 실패. 파일을 다시 업로드해주세요.")
            else:
                with st.spinner("이미지 합성 중입니다..."):
                    zip_buf, count = run_batch_composition(analysis, "JPEG", 100)

                if count > 0:
                    invalid_count = analysis['summary']['invalid']
                    st.success(f"✅ 총 {count}장의 이미지가 생성되었습니다!")
                    if invalid_count > 0:
                        st.info(f"ℹ️ {invalid_count}개 조합은 자동으로 제외되었습니다.")

                    st.download_button(
                        label=f"💾 {zip_filename} 다운로드",
                        data=zip_buf,
                        file_name=zip_filename,
                        mime="application/zip",
                        use_container_width=True,
                    )
                else:
                    st.warning("생성된 이미지가 없습니다. 조합을 확인해주세요.")

        if btn_disabled and template_files and not is_valid_tpl:
            st.warning("⚠️ 템플릿 파일명을 수정해야 생성할 수 있습니다.")


# CLI 블록 (import 시 실행 방지)
if __name__ == "__main__":
    print("CLI 모드는 별도 파일에서 실행하세요.")
