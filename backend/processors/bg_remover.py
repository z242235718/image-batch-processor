# Author: w2422 <z242235718@163.com>
# Copyright (C) 2026 w2422. All rights reserved.

import gc
import io
import os
import threading
from pathlib import Path

import httpx
from PIL import Image, ImageOps
from rembg import remove, new_session

_session_cache = {}
_session_cache_lock = threading.Lock()
_active_batches = 0
_batch_count_lock = threading.Lock()

# 在模块加载阶段设置 OMP 环境变量，确保在 ONNX Runtime/OMP 初始化前生效
os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")
os.environ.setdefault("OMP_DYNAMIC", "FALSE")
os.environ.setdefault("OMP_SCHEDULE", "STATIC")
os.environ.setdefault("OMP_THREAD_LIMIT", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("ORT_DISABLE_CPU_MEM_ARENA", "1")

# 背景移除预处理缩放最大尺寸（推理用 probe 缩略图边长上限）
# BRIA-RMBG 模型的 ONNX graph 有硬编码的 Split 节点，输入必须为 (1024, 1024)
# 改变此值只影响 PIL 阶段 probe 构造内存，不影响 ONNX Runtime 内部张量分配
MAX_BG_DIM = 1024


def _translate_model_name(name: str) -> str:
    """前端模型名 -> rembg 模型名"""
    mapping = {
        "rmbg-1.4": "bria-rmbg",
        "birefnet": "birefnet-general",
        "rmbg-2.0": "bria-rmbg",
    }
    # 已移除模型（如 u2net）或未知名称 → 回退到默认推荐
    return mapping.get(name, mapping.get("rmbg-1.4", "bria-rmbg"))


def register_batch():
    """注册一个批处理任务开始，防止其他批次未完成时误释放 session"""
    global _active_batches
    with _batch_count_lock:
        _active_batches += 1


def unregister_batch():
    """一个批处理任务结束，若无其他活动批次则释放模型内存"""
    global _active_batches
    with _batch_count_lock:
        _active_batches -= 1
        if _active_batches <= 0:
            with _session_cache_lock:
                _session_cache.clear()
            gc.collect()


def clear_session_cache():
    """强制清空所有模型缓存并回收内存（供外部调用）"""
    global _active_batches
    with _batch_count_lock:
        _active_batches = 0
        with _session_cache_lock:
            _session_cache.clear()
        gc.collect()


def release_cached_session():
    """释放缓存的 rembg 模型 session，不干扰批处理计数器

    推理完成后、后续非推理操作前调用此函数可提前归还 ONNX 内存，
    避免已分配的 ONNX 页面在后续文件操作中被缺页换入 RSS。
    与 clear_session_cache() 不同，此函数不清零 _active_batches，
    因此不会影响外层 register_batch/unregister_batch 的生命周期管理。
    """
    with _session_cache_lock:
        _session_cache.clear()
    gc.collect()


def _get_session(model_name: str, threads: int = 0, disable_arena: bool = True):
    """缓存 session 避免重复加载模型

    rembg 的 new_session() 内部创建 SessionOptions 时，只有 OMP_NUM_THREADS
    环境变量存在才会设置 intra/inter_op_num_threads；传参给 kwargs 会被忽略。
    因此需要在调用前设置好环境变量。
    """
    actual_name = _translate_model_name(model_name)
    # threads <= 0 时默认用 1 线程（降低峰值 CPU 和并行 malloc 导致的堆碎片）
    effective_threads = max(1, threads if threads > 0 else 1)
    cache_key = f"{actual_name}_t{effective_threads}_a{1 if disable_arena else 0}"
    with _session_cache_lock:
        if cache_key not in _session_cache:
            # 让 rembg 在创建 SessionOptions 时控制线程数，避免 OpenBLAS/OMP
            # 使用默认的高并发数导致内存分配失败（bad allocation）
            os.environ["OMP_NUM_THREADS"] = str(effective_threads)
            os.environ["OMP_WAIT_POLICY"] = "PASSIVE"
            os.environ["OMP_DYNAMIC"] = "FALSE"
            os.environ["OMP_SCHEDULE"] = "STATIC"
            os.environ["OMP_THREAD_LIMIT"] = str(effective_threads)
            os.environ["MKL_NUM_THREADS"] = str(effective_threads)
            os.environ["OPENBLAS_NUM_THREADS"] = str(effective_threads)
            if disable_arena:
                os.environ["ORT_DISABLE_CPU_MEM_ARENA"] = "1"
            else:
                os.environ["ORT_DISABLE_CPU_MEM_ARENA"] = "0"
            print(f"\n[模型加载] 正在加载模型: {actual_name} ...")
            print(f"[模型加载] 首次使用会自动下载 (~300MB-1GB)，请耐心等待...")
            import sys
            sys.stdout.flush()
            _session_cache[cache_key] = new_session(actual_name)
            print(f"[模型加载] {actual_name} 加载完成")
            sys.stdout.flush()
        return _session_cache[cache_key]


def _normalize_work_image(image: Image.Image) -> Image.Image:
    """将输入图规范为适合 rembg 的轻量 RGB 图，尽量减少峰值内存。"""
    if image.mode == "RGB":
        return image
    if image.mode in ("RGBA", "LA"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        alpha = image.getchannel("A") if "A" in image.getbands() else None
        try:
            background.paste(image, mask=alpha)
        finally:
            if alpha is not None:
                try:
                    alpha.close()
                except Exception:
                    pass
        return background
    return image.convert("RGB")


def _exif_transposed_size(image: Image.Image) -> tuple[int, int]:
    """返回应用 EXIF 方向后的原图尺寸，不触发全图解码。"""
    width, height = image.size
    try:
        orientation = image.getexif().get(0x0112)
    except Exception:
        orientation = None
    if orientation in (5, 6, 7, 8):
        return height, width
    return width, height


def _build_probe_image_from_path(image_path: str | Path) -> tuple[Image.Image, tuple[int, int]]:
    """从源文件直接构建 rembg 推理小图，避免先物化全分辨率图像。"""
    with Image.open(image_path) as src_img:
        orig_size = _exif_transposed_size(src_img)
        try:
            src_img.draft("RGB", (MAX_BG_DIM, MAX_BG_DIM))
        except Exception:
            pass
        src_img.thumbnail((MAX_BG_DIM, MAX_BG_DIM), Image.LANCZOS)
        probe = ImageOps.exif_transpose(src_img)
        probe.load()

    if max(probe.size) > MAX_BG_DIM:
        ratio = MAX_BG_DIM / max(probe.size)
        new_size = (max(1, int(probe.size[0] * ratio)), max(1, int(probe.size[1] * ratio)))
        resized = probe.resize(new_size, Image.LANCZOS)
        try:
            probe.close()
        except Exception:
            pass
        probe = resized

    normalized = _normalize_work_image(probe)
    if normalized is not probe:
        try:
            probe.close()
        except Exception:
            pass
    return normalized, orig_size


def _run_rembg_alpha(image: Image.Image, orig_size: tuple, session) -> Image.Image:
    """运行 rembg 并返回与原图同尺寸的 alpha 蒙版。"""
    alpha = _run_rembg_probe_alpha(image, session)

    if alpha.size != orig_size:
        alpha_full = alpha.resize(orig_size, Image.LANCZOS)
        try:
            alpha.close()
        except Exception:
            pass
        del alpha
        gc.collect()
        return alpha_full

    return alpha


def _run_rembg_probe_alpha(image: Image.Image, session) -> Image.Image:
    """运行 rembg 并返回推理输入尺寸的 alpha 蒙版，不放大到原图尺寸。"""
    normalized = _normalize_work_image(image)
    owns_normalized = normalized is not image
    needs_resize = max(normalized.size) > MAX_BG_DIM

    try:
        if needs_resize:
            ratio = MAX_BG_DIM / max(normalized.size)
            new_size = (max(1, int(normalized.size[0] * ratio)), max(1, int(normalized.size[1] * ratio)))
            img_input = normalized.resize(new_size, Image.LANCZOS)
            owns_input = True
        else:
            img_input = normalized
            owns_input = owns_normalized

        try:
            result_img = remove(img_input, session=session, only_mask=True)
        finally:
            if owns_input:
                try:
                    img_input.close()
                except Exception:
                    pass
            if owns_normalized and normalized is not img_input:
                try:
                    normalized.close()
                except Exception:
                    pass
            gc.collect()

        if result_img.mode != "L":
            alpha = result_img.convert("L")
            try:
                result_img.close()
            except Exception:
                pass
            return alpha
        return result_img
    finally:
        if owns_normalized:
            try:
                normalized.close()
            except Exception:
                pass
            gc.collect()


def remove_bg_local_alpha(image: Image.Image, model_name: str = "rmbg-1.4",
                          threads: int = 0, disable_arena: bool = True) -> Image.Image:
    """使用 rembg 本地抠图并返回 alpha 蒙版（与原图同尺寸）"""
    orig_size = image.size
    session = _get_session(model_name, threads, disable_arena)
    return _run_rembg_alpha(image, orig_size, session)


def remove_bg_local_alpha_from_path(image_path: str | Path, model_name: str = "rmbg-1.4",
                                    threads: int = 0, disable_arena: bool = True) -> Image.Image:
    """从原图路径直接生成 alpha 蒙版，只构建 rembg 推理需要的小图。"""
    session = _get_session(model_name, threads, disable_arena)
    probe = None
    try:
        probe, orig_size = _build_probe_image_from_path(image_path)
        return _run_rembg_alpha(probe, orig_size, session)
    finally:
        if probe is not None:
            try:
                probe.close()
            except Exception:
                pass
        del probe
        gc.collect()


def remove_bg_local_probe_alpha_from_path(image_path: str | Path, model_name: str = "rmbg-1.4",
                                          threads: int = 0, disable_arena: bool = True) -> tuple[Image.Image, tuple[int, int], tuple[int, int]]:
    """从原图路径生成推理小图尺寸的 alpha 蒙版，不放大到原图尺寸。"""
    session = _get_session(model_name, threads, disable_arena)
    probe = None
    try:
        probe, orig_size = _build_probe_image_from_path(image_path)
        alpha = _run_rembg_probe_alpha(probe, session)
        return alpha, orig_size, alpha.size
    finally:
        if probe is not None:
            try:
                probe.close()
            except Exception:
                pass
        del probe
        gc.collect()


def remove_bg_local(image: Image.Image, model_name: str = "rmbg-1.4",
                    threads: int = 0, disable_arena: bool = True) -> Image.Image:
    """使用 rembg 本地抠图（带预处理缩放，优化大图内存和速度）"""
    alpha = remove_bg_local_alpha(image, model_name, threads, disable_arena)

    base_img = image if image.mode == "RGBA" else image.convert("RGBA")
    try:
        base_img.putalpha(alpha)
    finally:
        try:
            alpha.close()
        except Exception:
            pass
        del alpha
        gc.collect()

    return base_img


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
                      model_name: str = "rmbg-1.4", threads: int = 0, disable_arena: bool = True) -> Image.Image:
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
