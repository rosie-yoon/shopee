from __future__ import annotations

# ===============================
# 기본 라이브러리
# ===============================
import io
import zipfile
from pathlib import Path

import streamlit as st
from PIL import Image as PILImage

# ===============================
# 내부 유틸 (기존 코드 그대로 사용)
# ===============================
from image_compose.composer_utils import (
    compose_one_bytes,
    SHADOW_PRESETS,
    has_useful_alpha,
    ensure_rgba,
)

# ===============================
# (1) SwinIR 업스케일 유틸
# ===============================
# 지금은 구조 설명을 위해 "자리"만 잡아둠
# → 실제 SwinIR 코드로 교체 가능
def upscale_pil_image(img: PILImage.Image, scale: int = 2) -> PILImage.Image:
    """
    출력 전용 업스케일 함수
    - 미리보기에는 절대 사용하지 않음
    - 2x 업스케일 전용
    """
    if scale <= 1:
        return img

    w, h = img.size
    return img.resize((w * scale, h * scale), PILImage.BICUBIC)


# ===============================
# Streamlit 이미지 표시 헬퍼
# ===============================
def st_image_center(img, width=None, caption=None):
    container = st.container()
    _, center, _ = container.columns([1, 4, 1])
    with center:
        st.image(img, width=width, caption=caption)


# ===============================
# 메인 앱
# ===============================
def run():
    st.title("Cover Image Generator")

    # ---------------------------
    # 세션 상태 초기화
    # ---------------------------
    if "upscale_output" not in st.session_state:
        st.session_state.upscale_output = False

    # ---------------------------
    # UI 레이아웃
    # ---------------------------
    left, right = st.columns([1, 1])

    # ===========================
    # 왼쪽: 파일 업로드
    # ===========================
    with left:
        st.subheader("이미지 업로드")

        allow_non_alpha = st.checkbox(
            "템플릿 앞에 배치 (일반 사진 허용)",
            value=False
        )

        item_types = ["png", "webp"] + (["jpg", "jpeg"] if allow_non_alpha else [])
        item_files = st.file_uploader(
            "Item 이미지 업로드",
            type=item_types,
            accept_multiple_files=True
        )

        template_files = st.file_uploader(
            "Template 이미지 업로드",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True
        )

    # ===========================
    # 오른쪽: 설정 + 미리보기
    # ===========================
    with right:
        st.subheader("설정")

        anchor = st.selectbox(
            "배치 위치",
            [
                "center", "top", "bottom", "left", "right",
                "top-left", "top-right", "bottom-left", "bottom-right"
            ]
        )

        resize_ratio = st.selectbox(
            "아이템 크기",
            [1.3, 1.2, 1.1, 1.0, 0.9, 0.8],
            index=3,
            format_func=lambda x: f"{int(x*100)}%"
        )

        shadow_preset = st.selectbox(
            "그림자 프리셋",
            list(SHADOW_PRESETS.keys()),
            disabled=allow_non_alpha
        )

        st.divider()

        # 🔥 업스케일 옵션
        st.checkbox(
            "출력 이미지 2x 업스케일 (SwinIR)",
            key="upscale_output",
            help="미리보기는 그대로 두고, ZIP 다운로드 이미지에만 적용"
        )

        st.divider()
        st.subheader("미리보기")

        # ---------------------------
        # 미리보기 (첫 1장만)
        # ---------------------------
        preview_img = None
        if item_files and template_files:
            try:
                item_img = PILImage.open(io.BytesIO(item_files[0].getvalue()))
                template_img = PILImage.open(io.BytesIO(template_files[0].getvalue()))

                is_cutout = has_useful_alpha(ensure_rgba(item_img))
                if (not is_cutout) and (not allow_non_alpha):
                    st.warning("투명 배경이 아닌 Item은 미리보기에서 제외됩니다.")
                else:
                    opts = {
                        "anchor": anchor,
                        "resize_ratio": resize_ratio,
                        "shadow_preset": shadow_preset if is_cutout else "off",
                        "out_format": "PNG",
                        "overlay_template_if_no_alpha": allow_non_alpha,
                    }
                    result = compose_one_bytes(item_img, template_img, **opts)
                    if result:
                        buf, _ = result
                        preview_img = PILImage.open(io.BytesIO(buf.getvalue()))
            except Exception:
                preview_img = None

        if preview_img:
            w = int(preview_img.width * 0.4)
            st_image_center(preview_img, width=w, caption="미리보기")
        else:
            st.caption("파일을 업로드하면 미리보기가 표시됩니다.")

        st.divider()

        # ===========================
        # ZIP 생성 버튼
        # ===========================
        if st.button(
            "이미지 생성 & 다운로드",
            type="primary",
            disabled=not (item_files and template_files)
        ):
            zip_buf = io.BytesIO()
            count = 0

            with st.spinner("이미지 생성 중..."):
                with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for item_file in item_files:
                        item_img = PILImage.open(io.BytesIO(item_file.getvalue()))
                        is_cutout = has_useful_alpha(ensure_rgba(item_img))

                        if (not is_cutout) and (not allow_non_alpha):
                            continue

                        for tpl_file in template_files:
                            template_img = PILImage.open(io.BytesIO(tpl_file.getvalue()))

                            opts = {
                                "anchor": anchor,
                                "resize_ratio": resize_ratio,
                                "shadow_preset": shadow_preset if is_cutout else "off",
                                "out_format": "PNG",
                                "overlay_template_if_no_alpha": allow_non_alpha,
                            }

                            result = compose_one_bytes(item_img, template_img, **opts)
                            if not result:
                                continue

                            img_buf, ext = result
                            img = PILImage.open(io.BytesIO(img_buf.getvalue()))

                            # ✅ 여기서만 업스케일
                            if st.session_state.upscale_output:
                                img = upscale_pil_image(img, scale=2)

                            out_buf = io.BytesIO()
                            img.save(out_buf, format="PNG")

                            name = f"{Path(item_file.name).stem}_C_{Path(tpl_file.name).stem}.png"
                            zf.writestr(name, out_buf.getvalue())
                            count += 1

            zip_buf.seek(0)

            if count == 0:
                st.warning("생성된 이미지가 없습니다.")
            else:
                st.success(f"{count}개의 이미지 생성 완료!")
                st.download_button(
                    "ZIP 다운로드",
                    zip_buf,
                    file_name="Cover_Images.zip",
                    mime="application/zip"
                )


# ===============================
# 실행
# ===============================
if __name__ == "__main__":
    run()
