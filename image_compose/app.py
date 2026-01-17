from __future__ import annotations
from pathlib import Path
import io
import zipfile
import re
from datetime import datetime

import streamlit as st
from PIL import Image as PILImage

# 내부 유틸 (절대 임포트로 고정)
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
    if x is None:
        return None
    if isinstance(x, (bytes, bytearray)):
        return x
    if isinstance(x, PILImage.Image):
        return x
    if hasattr(x, "getvalue"):
        try:
            return x.getvalue()
        except Exception:
            pass
    if hasattr(x, "read"):
        try:
            return x.read()
        except Exception:
            pass
    if isinstance(x, (str, Path)) and Path(x).exists():
        return str(x)
    return None


# ---------- 템플릿 파일명 유효성 검사 ----------
def validate_template_names(files):
    """
    템플릿 파일명 검사:
    1. 특수문자 포함 여부 (영문, 숫자, 언더스코어, 하이픈만 허용)
    2. 중복된 이름(Stem) 존재 여부
    """
    if not files:
        return True, []

    seen_stems = set()
    errors = []

    # 허용된 문자: 영문, 숫자, 언더스코어, 하이픈만
    pattern = re.compile(r'^[a-zA-Z0-9_-]+$')

    for f in files:
        stem = Path(f.name).stem

        # 1. 특수문자 검사
        if not pattern.match(stem):
            errors.append(f"'{f.name}' - 영문, 숫자, _, - 만 사용 가능합니다")
            continue

        # 2. 중복 검사
        if stem in seen_stems:
            errors.append(f"'{stem}' - 중복된 템플릿명입니다 (확장자가 달라도 불가)")
        else:
            seen_stems.add(stem)

    if errors:
        return False, errors
    return True, []


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
            "template_in_front": False,  # 새로운 옵션명
        }
        for k, v in defaults.items():
            st.session_state.setdefault(k, v)

    init_state()
    ss = st.session_state

    # ---------- 유틸리티 함수들 ----------
    def _files_fingerprint(files):
        if not files:
            return []
        fps = []
        for f in files:
            try:
                name = getattr(f, "name", "noname")
                try:
                    size = getattr(f, "size", None)
                except Exception:
                    size = None
                if size is None:
                    try:
                        size = len(f.getvalue())
                    except Exception:
                        size = 0
                fps.append((name, int(size)))
            except Exception:
                fps.append(("unknown", 0))
        return fps

    def _options_signature():
        return (
            ss.anchor,
            float(ss.resize_ratio),
            ss.shadow_preset,
            bool(ss.template_in_front),
        )

    # ---- 미리보기 업데이트 함수 ----
    def update_preview(item_files, template_files):
        ss.preview_img = None
        if not item_files or not template_files:
            return

        item_bytes = item_files[0].getvalue()
        tpl_bytes = template_files[0].getvalue()
        item_img = PILImage.open(io.BytesIO(item_bytes))
        template_img = PILImage.open(io.BytesIO(tpl_bytes))

        # 템플릿 앞 배치 모드에서는 그림자 강제 OFF
        _shadow = ss.shadow_preset if not ss.template_in_front else "off"

        opts = {
            "anchor": ss.anchor,
            "resize_ratio": ss.resize_ratio,
            "shadow_preset": _shadow,
            "out_format": "PNG",
            "template_in_front": bool(ss.template_in_front),
        }
        result = compose_one_bytes(item_img, template_img, **opts)
        if not result:
            ss.preview_img = None
            return

        buf = result[0]
        data = buf.getvalue() if hasattr(buf, "getvalue") else bytes(buf)
        ss.preview_img = data

    def generate_preview_list(item_files, template_files, max_count: int = 12):
        ss.preview_list = []
        ss.preview_idx = 0
        if not item_files or not template_files:
            return

        out = []
        for item_file in item_files:
            if len(out) >= max_count:
                break
            try:
                item_img = PILImage.open(io.BytesIO(item_file.getvalue()))
            except Exception:
                continue

            for template_file in template_files:
                if len(out) >= max_count:
                    break
                try:
                    template_img = PILImage.open(io.BytesIO(template_file.getvalue()))
                except Exception:
                    continue

                _shadow = ss.shadow_preset if not ss.template_in_front else "off"
                opts = {
                    "anchor": ss.anchor,
                    "resize_ratio": ss.resize_ratio,
                    "shadow_preset": _shadow,
                    "out_format": "PNG",
                    "template_in_front": bool(ss.template_in_front),
                }
                result = compose_one_bytes(item_img, template_img, **opts)
                if result:
                    buf = result[0]
                    data = buf.getvalue()
                    out.append(data)
        ss.preview_list = out

    # ---- 배치 합성 & Zip 생성 ----
    def run_batch_composition(item_files, template_files, fmt, quality):
        zip_buf = io.BytesIO()
        count = 0
        with zipfile.ZipFile(zip_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for item_file in item_files:
                try:
                    item_img = PILImage.open(io.BytesIO(item_file.getvalue()))
                except:
                    continue

                for template_file in template_files:
                    try:
                        template_img = PILImage.open(io.BytesIO(template_file.getvalue()))
                    except:
                        continue

                    _shadow = ss.shadow_preset if not ss.template_in_front else "off"
                    opts = {
                        "anchor": ss.anchor,
                        "resize_ratio": ss.resize_ratio,
                        "shadow_preset": _shadow,
                        "out_format": fmt,
                        "quality": quality,
                        "template_in_front": bool(ss.template_in_front),
                    }
                    result = compose_one_bytes(item_img, template_img, **opts)
                    if result:
                        img_buf, ext = result
                        item_name = Path(item_file.name).stem

                        # 템플릿 파일명에서 샵코드 자동 추출
                        template_code = Path(template_file.name).stem

                        # 새로운 파일명 규칙
                        filename = f"{item_name}_C_{template_code}.{ext}"

                        zf.writestr(filename, img_buf.getvalue())
                        count += 1
        zip_buf.seek(0)
        return zip_buf, count

    # ---- UI 레이아웃 ----
    left, right = st.columns([1, 1])

    with left:
        st.subheader("이미지 업로드")

        # 새로운 옵션: 템플릿 앞 배치 (흰색 배경 포함)
        st.checkbox(
            "템플릿을 상품 앞에 배치 (액자 효과)",
            key="template_in_front",
            help="체크 시: 흰색 배경 → 상품 → 템플릿 순서로 합성됩니다.",
        )

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
            help="파일명이 샵코드로 사용됩니다 (예: RORO.jpg → RORO)"
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

        # 그림자 프리셋 (템플릿 앞 배치 시 비활성화)
        if ss.template_in_front and st.session_state.get("shadow_preset") != "off":
            st.session_state["shadow_preset"] = "off"

        c3.selectbox(
            "그림자 프리셋",
            list(SHADOW_PRESETS.keys()),
            key="shadow_preset",
            disabled=ss.template_in_front,
            help="템플릿 앞 배치 시 자동으로 비활성화됩니다"
        )

        # ---- 미리보기 섹션 ----
        st.subheader("미리보기")

        # 유효성 검사 통과 시에만 미리보기 갱신
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

        # 즉시 생성 및 다운로드 버튼
        btn_disabled = (not item_files or not template_files or not is_valid_tpl)

        # 날짜 기반 Zip 파일명 생성 (YYMMDD 형식)
        date_str = datetime.now().strftime("%y%m%d")
        zip_filename = f"Thumb_Craft_Results_{date_str}.zip"

        if st.button(
                "🎨 이미지 생성 & 다운로드 준비",
                type="primary",
                use_container_width=True,
                disabled=btn_disabled
        ):
            with st.spinner("이미지 합성 중입니다..."):
                zip_buf, count = run_batch_composition(item_files, template_files, "JPEG", 100)

            if count > 0:
                st.success(f"✅ 총 {count}장의 이미지가 생성되었습니다!")
                st.download_button(
                    label=f"💾 {zip_filename} 다운로드",
                    data=zip_buf,
                    file_name=zip_filename,
                    mime="application/zip",
                    use_container_width=True,
                )
            else:
                st.warning("생성된 이미지가 없습니다. 파일을 확인해주세요.")

        # 비활성화 이유 표시
        if btn_disabled and template_files and not is_valid_tpl:
            st.warning("⚠️ 템플릿 파일명을 수정해야 생성할 수 있습니다.")


# ---------- CLI 실행 블록 ----------
if __name__ == "__main__":
    import argparse
    from tqdm import tqdm
    from PIL import Image


    def main_cli():
        parser = argparse.ArgumentParser(description="Thumb Craft - CLI 이미지 합성 도구")
        parser.add_argument("--item_folder", required=True, help="Item 이미지 폴더")
        parser.add_argument("--template_folder", required=True, help="Template 이미지 폴더")
        parser.add_argument("--out_dir", default="C_out", help="결과물 저장 폴더")

        parser.add_argument("--anchor", default="center",
                            choices=["center", "top", "bottom", "left", "right", "top-left", "top-right", "bottom-left",
                                     "bottom-right"])
        parser.add_argument("--resize_ratio", type=float, default=1.0)
        parser.add_argument("--shadow_preset", default="off", choices=SHADOW_PRESETS.keys())
        parser.add_argument("--out_format", default="JPEG", choices=["JPEG", "PNG"])
        parser.add_argument("--quality", type=int, default=92)
        parser.add_argument("--template_in_front", action="store_true", help="템플릿을 맨 앞에 배치 (흰색 배경 추가)")

        args = parser.parse_args()

        item_folder = Path(args.item_folder)
        template_folder = Path(args.template_folder)
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        item_files = load_images_from_folder(item_folder)
        template_files = load_images_from_folder(template_folder)

        # CLI 유효성 검사
        template_paths = [Path(name + ".dummy") for name, _ in template_files]  # 검사용 임시 객체
        _, errors = validate_template_names(template_paths)
        if errors:
            print("❌ 템플릿 파일명 오류:")
            for e in errors:
                print(f"  {e}")
            return

        if not item_files or not template_files:
            print("❌ 파일이 없습니다.")
            return

        # 템플릿 앞 배치 시 그림자 강제 OFF
        _shadow = args.shadow_preset if not args.template_in_front else "off"

        opts = {
            "anchor": args.anchor,
            "resize_ratio": args.resize_ratio,
            "shadow_preset": _shadow,
            "out_format": args.out_format,
            "quality": args.quality,
            "template_in_front": args.template_in_front,
        }

        # 날짜 기반 Zip 파일명
        date_str = datetime.now().strftime("%y%m%d")
        zip_path = out_dir.parent / f"{out_dir.name}_{date_str}.zip"

        generated_count = 0

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            total_jobs = len(item_files) * len(template_files)
            with tqdm(total=total_jobs, desc="이미지 합성 중") as pbar:
                for item_name, item_path in item_files:
                    try:
                        item_img = Image.open(item_path)
                    except:
                        pbar.update(len(template_files))
                        continue

                    for template_name, template_path in template_files:
                        try:
                            template_img = Image.open(template_path)
                        except:
                            pbar.update(1)
                            continue

                        result = compose_one_bytes(item_img, template_img, **opts)
                        if result:
                            img_buf, ext = result

                            # 템플릿 파일명에서 샵코드 자동 추출
                            filename = f"{item_name}_C_{template_name}.{ext}"

                            # 개별 파일 저장
                            save_path = out_dir / filename
                            save_path.write_bytes(img_buf.getvalue())
                            # Zip 저장
                            zf.writestr(filename, img_buf.getvalue())
                            generated_count += 1
                        pbar.update(1)

        print(f"✅ 완료! 총 {generated_count}개 이미지 생성")
        print(f"   📁 개별 파일: {out_dir}")
        print(f"   📦 압축 파일: {zip_path}")


    main_cli()
else:
    run()
