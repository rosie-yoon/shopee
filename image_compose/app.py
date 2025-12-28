from __future__ import annotations

from pathlib import Path
import io
import zipfile

import streamlit as st
from PIL import Image as PILImage
from PIL import ImageFilter

from image_compose.composer_utils import (
    compose_one_bytes,
    SHADOW_PRESETS,
    has_useful_alpha,
    ensure_rgba,
)


# ======================================================
# 1080 고정 화질 개선 (사이즈 변경 ❌)
# ======================================================
def enhance_1080_quality(img: PILImage.Image) -> PILImage.Image:
    """
    - 이미지 사이즈 유지
    - 글자/로고 안전한 선명도 보정
    """
    return img.filter(
        ImageFilter.UnsharpMask(
            radius=1.2,   # 엣지 반경 (작게)
            percent=110,  # 강도 (보수적)
            threshold=3,  # 노이즈 억제
        )
    )


# ======================================================
# Streamlit 이미지 중앙 렌더
# ======================================================
def _st_image(img, width=None):
    _, mid, _ = st.columns([1, 4, 1])
    with mid:
        st.image(img, width=width)


# ======================================================
# 메인 앱
# ======================================================
def run():
    PREVIEW_SCALE = 0.3
    st.title("Cover Image")

    # ------------------------------
    # 세션 상태
    # ------------------------------
    def init_state():
        defaults = {
            "anchor": "center",
            "resize_ratio": 1.0,
            "shadow_preset": "off",
            "allow_non_alpha_overlay": False,
            "item_key": 0,
            "tpl_key": 0,
            "preview_sig": None,
            "preview_list": [],
            "preview_idx": 0,
            "zip_sig": None,
            "zip_buf": None,
            "zip_count": 0,
            "enable_enhance": False,
        }
        for k, v in defaults.items():
            st.session_state.setdefault(k, v)

    init_state()
    ss = st.session_state

    # ------------------------------
    # 유틸
    # ------------------------------
    def _files_sig(files):
        if not files:
            return []
        out = []
        for f in files:
            try:
                out.append((f.name, len(f.getvalue())))
            except Exception:
                out.append((f.name, 0))
        return out

    def _options_sig():
        return (
            ss.anchor,
            ss.resize_ratio,
            ss.shadow_preset,
            ss.allow_non_alpha_overlay,
            ss.enable_enhance,
        )

    # ------------------------------
    # 미리보기 생성
    # ------------------------------
    def generate_preview(item_files, tpl_files):
        ss.preview_list = []
        ss.preview_idx = 0
        if not item_files or not tpl_files:
            return

        for item in item_files:
            try:
                item_img = PILImage.open(io.BytesIO(item.getvalue()))
            except Exception:
                continue

            is_cutout = has_useful_alpha(ensure_rgba(item_img))
            if not is_cutout and not ss.allow_non_alpha_overlay:
                continue

            for tpl in tpl_files:
                try:
                    tpl_img = PILImage.open(io.BytesIO(tpl.getvalue()))
                except Exception:
                    continue

                shadow = ss.shadow_preset if (is_cutout or not ss.allow_non_alpha_overlay) else "off"
                opts = {
                    "anchor": ss.anchor,
                    "resize_ratio": ss.resize_ratio,
                    "shadow_preset": shadow,
                    "out_format": "PNG",
                    "overlay_template_if_no_alpha": ss.allow_non_alpha_overlay,
                }
                result = compose_one_bytes(item_img, tpl_img, **opts)
                if result:
                    buf, _ = result
                    ss.preview_list.append(buf.getvalue())
                if len(ss.preview_list) >= 12:
                    return

    # ------------------------------
    # ZIP 생성
    # ------------------------------
    def build_zip(item_files, tpl_files, shop_code: str):
        zip_buf = io.BytesIO()
        count = 0

        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in item_files:
                item_img = PILImage.open(io.BytesIO(item.getvalue()))
                is_cutout = has_useful_alpha(ensure_rgba(item_img))
                if not is_cutout and not ss.allow_non_alpha_overlay:
                    continue

                for tpl in tpl_files:
                    tpl_img = PILImage.open(io.BytesIO(tpl.getvalue()))
                    shadow = ss.shadow_preset if (is_cutout or not ss.allow_non_alpha_overlay) else "off"

                    opts = {
                        "anchor": ss.anchor,
                        "resize_ratio": ss.resize_ratio,
                        "shadow_preset": shadow,
                        "out_format": "PNG",
                        "overlay_template_if_no_alpha": ss.allow_non_alpha_overlay,
                    }

                    result = compose_one_bytes(item_img, tpl_img, **opts)
                    if not result:
                        continue

                    buf, _ = result
                    img = PILImage.open(io.BytesIO(buf.getvalue()))

                    # 🔥 1080 화질 개선 (사이즈 변경 없음)
                    if ss.enable_enhance:
                        img = enhance_1080_quality(img)

                    out_buf = io.BytesIO()
                    img.save(out_buf, format="PNG")

                    item_name = Path(item.name).stem
                    shop = shop_code if shop_code else Path(tpl.name).stem
                    filename = f"{item_name}_C_{shop}.png"

                    zf.writestr(filename, out_buf.getvalue())
                    count += 1

        zip_buf.seek(0)
        return zip_buf, count

    # ======================================================
    # UI
    # ======================================================
    left, right = st.columns([1, 1])

    # ---------------- LEFT ----------------
    with left:
        st.subheader("이미지 업로드")

        st.checkbox("템플릿 앞에 배치", key="allow_non_alpha_overlay")

        item_types = ["png", "webp"] + (["jpg", "jpeg"] if ss.allow_non_alpha_overlay else [])
        item_files = st.file_uploader(
            "1. Item 이미지 업로드",
            type=item_types,
            accept_multiple_files=True,
            key=f"item_{ss.item_key}",
        )

        if st.button("아이템 삭제", use_container_width=True):
            ss.item_key += 1
            ss.preview_sig = None
            st.rerun()

        tpl_files = st.file_uploader(
            "2. Template 이미지 업로드",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
            key=f"tpl_{ss.tpl_key}",
        )

        if st.button("템플릿 삭제", use_container_width=True):
            ss.tpl_key += 1
            ss.preview_sig = None
            st.rerun()

    # ---------------- RIGHT ----------------
    with right:
        st.subheader("이미지 설정")

        c1, c2, c3 = st.columns(3)
        c1.selectbox(
            "배치",
            [
                "center", "top", "bottom", "left", "right",
                "top-left", "top-right", "bottom-left", "bottom-right",
            ],
            key="anchor",
        )

        ratios = [1.3, 1.2, 1.1, 1.0, 0.9, 0.8, 0.7]
        ss.resize_ratio = c2.selectbox(
            "리사이즈",
            ratios,
            index=ratios.index(ss.resize_ratio),
            format_func=lambda x: f"{int(x*100)}%",
        )

        if ss.allow_non_alpha_overlay:
            ss.shadow_preset = "off"
            c3.selectbox("그림자", SHADOW_PRESETS.keys(), disabled=True)
        else:
            c3.selectbox("그림자", SHADOW_PRESETS.keys(), key="shadow_preset")

        st.markdown("#### 저장 화질 옵션")
        st.checkbox("1080 화질 개선 (선명도 보정)", key="enable_enhance")

        # -------- 미리보기 --------
        st.subheader("미리보기")

        sig = (
            tuple(_files_sig(item_files)),
            tuple(_files_sig(tpl_files)),
            _options_sig(),
        )
        if sig != ss.preview_sig:
            generate_preview(item_files, tpl_files)
            ss.preview_sig = sig

        if ss.preview_list:
            n = len(ss.preview_list)
            nav_l, nav_c, nav_r = st.columns([1, 5, 1])
            with nav_l:
                if st.button("◀"):
                    ss.preview_idx = (ss.preview_idx - 1) % n
            with nav_c:
                st.write(f"{ss.preview_idx + 1} / {n}")
            with nav_r:
                if st.button("▶"):
                    ss.preview_idx = (ss.preview_idx + 1) % n

            img = PILImage.open(io.BytesIO(ss.preview_list[ss.preview_idx]))
            _st_image(img, width=int(img.width * PREVIEW_SCALE))
        else:
            st.caption("파일을 업로드하면 미리보기가 표시됩니다.")

        # -------- 저장 --------
        @st.dialog("출력 설정")
        def show_save_dialog(item_files, tpl_files):
            shop = st.text_input("Shop 구분값 (선택)")

            zip_sig = (
                tuple(_files_sig(item_files)),
                tuple(_files_sig(tpl_files)),
                _options_sig(),
                shop,
            )

            if zip_sig != ss.zip_sig:
                with st.spinner("이미지 생성 중..."):
                    ss.zip_buf, ss.zip_count = build_zip(item_files, tpl_files, shop)
                    ss.zip_sig = zip_sig

            if ss.zip_count == 0:
                st.warning("생성된 이미지가 없습니다.")
            else:
                st.success(f"{ss.zip_count}개 이미지 준비 완료")
                st.download_button(
                    "ZIP 다운로드",
                    ss.zip_buf,
                    file_name="Thumb_Craft_Results.zip",
                    mime="application/zip",
                    use_container_width=True,
                )

        if st.button(
            "이미지 생성",
            type="primary",
            use_container_width=True,
            disabled=not (item_files and tpl_files),
        ):
            show_save_dialog(item_files, tpl_files)


if __name__ == "__main__":
    run()
