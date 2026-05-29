import io
from PIL import Image


def compress_image(
    image: Image.Image,
    output_format: str = "JPEG",
    quality: int = 85,
    max_file_size_kb: int = 0,
    max_width: int = 0,
) -> bytes:
    """压缩图片并返回字节数据"""
    img = image.copy()

    # 如果需要限制宽度，等比缩放
    if max_width > 0 and img.width > max_width:
        ratio = max_width / img.width
        new_height = int(img.height * ratio)
        img = img.resize((max_width, new_height), Image.LANCZOS)

    # JPEG 不支持透明通道
    if output_format.upper() in ("JPEG", "JPG"):
        if img.mode == "RGBA":
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

    # 如果设定了目标文件大小，用二分法逼近
    if max_file_size_kb > 0:
        target_bytes = max_file_size_kb * 1024
        low, high = 1, 95
        best_data = None

        while low <= high:
            mid = (low + high) // 2
            data = _encode(img, output_format, mid)
            if len(data) <= target_bytes:
                best_data = data
                low = mid + 1
            else:
                high = mid - 1

        if best_data:
            return best_data
        return _encode(img, output_format, 1)

    return _encode(img, output_format, quality)


def _encode(img: Image.Image, fmt: str, quality: int) -> bytes:
    buf = io.BytesIO()
    save_kwargs = {"optimize": True}

    if fmt.upper() in ("JPEG", "JPG"):
        save_kwargs["quality"] = quality
        img.save(buf, format="JPEG", **save_kwargs)
    elif fmt.upper() == "WEBP":
        save_kwargs["quality"] = quality
        img.save(buf, format="WEBP", **save_kwargs)
    elif fmt.upper() == "PNG":
        save_kwargs["compress_level"] = max(0, min(9, (100 - quality) // 11))
        img.save(buf, format="PNG", **save_kwargs)

    return buf.getvalue()
