import io
import os
import httpx
from PIL import Image
from rembg import remove, new_session

_session_cache = {}


def _translate_model_name(name: str) -> str:
    """前端模型名 -> rembg 模型名"""
    mapping = {
        "rmbg-1.4": "bria-rmbg",
        "birefnet": "birefnet-general",
        "rmbg-2.0": "bria-rmbg",
        "u2net": "u2net",
        "u2netp": "u2netp",
    }
    return mapping.get(name, name)


def _get_session(model_name: str, threads: int = 0, disable_arena: bool = True):
    """缓存 session 避免重复加载模型"""
    actual_name = _translate_model_name(model_name)
    cache_key = f"{actual_name}_t{threads}"
    if cache_key not in _session_cache:
        _session_cache[cache_key] = new_session(
            actual_name,
            intra_op_num_threads=threads if threads > 0 else 1,
            inter_op_num_threads=threads if threads > 0 else 1,
        )
    return _session_cache[cache_key]


def remove_bg_local(image: Image.Image, model_name: str = "u2net",
                    threads: int = 0, disable_arena: bool = True) -> Image.Image:
    """使用 rembg 本地抠图"""
    session = _get_session(model_name, threads, disable_arena)

    img_bytes = io.BytesIO()
    image.save(img_bytes, format="PNG")
    img_bytes.seek(0)
    result = remove(img_bytes.getvalue(), session=session)
    return Image.open(io.BytesIO(result)).convert("RGBA")


def remove_bg_api_sync(image: Image.Image, api_key: str) -> Image.Image:
    """使用 remove.bg API 在线抠图 (同步)"""
    img_bytes = io.BytesIO()
    image.save(img_bytes, format="PNG")
    img_bytes.seek(0)

    response = httpx.post(
        "https://api.remove.bg/v1.0/removebg",
        files={"image_file": ("image.png", img_bytes, "image/png")},
        data={"size": "auto"},
        headers={"X-Api-Key": api_key},
        timeout=30,
    )

    if response.status_code != 200:
        raise Exception(f"remove.bg API 错误: {response.status_code} - {response.text[:200]}")

    return Image.open(io.BytesIO(response.content)).convert("RGBA")


def remove_background(image: Image.Image, method: str = "local", api_key: str = "",
                      model_name: str = "u2net", threads: int = 0, disable_arena: bool = True) -> Image.Image:
    """统一抠图入口（同步）"""
    if method == "none":
        return image.convert("RGBA")
    elif method == "local":
        return remove_bg_local(image, model_name, threads, disable_arena)
    elif method == "api":
        if not api_key:
            raise ValueError("使用 API 抠图需要提供 remove.bg API Key")
        return remove_bg_api_sync(image, api_key)
    else:
        raise ValueError(f"未知抠图方式: {method}")