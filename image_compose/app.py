def update_preview(item_files, template_files):
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

    # 확장자로 모드 결정
    template_ext = Path(template_file.name).suffix.lower()
    composition_mode = "frame" if template_ext == ".png" else "normal"

    # 유효성 체크
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
        "out_format": "PNG",
        "composition_mode": composition_mode,  # 명시적 모드 전달
    }

    result = compose_one_bytes(item_img, template_img, **opts)
    if result:
        ss.preview_img = result[0].getvalue()
