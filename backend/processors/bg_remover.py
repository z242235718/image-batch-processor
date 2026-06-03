# Author: w2422 <z242235718@163.com>
# Copyright (C) 2026 w2422. All rights reserved.

import gc
import io
import os
import threading
import httpx
from PIL import Image
from rembg import remove, new_session

_session_cache = {}
_session_cache_lock = threading.Lock()
_active_batches = 0
_batch_count_lock = threading.Lock()

# 背景移除预处理缩放最大尺寸
# rembg bria-rmbg 模型内部输入为 1024x1024，更高分辨率只会增加内存开销而不会改善抠图质量
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


def _get_session(model_name: str, threads: int = 0, disable_arena: bool = True):
    """缓存 session 避免重复加载模型

    rembg 的 new_session() 内部创建 SessionOptions 时，只有 OMP_NUM_THREADS
    环境变量存在才会设置 intra/inter_op_num_threads；传参给 kwargs 会被忽略。
    因此需要在调用前设置好环境变量。
    """
    actual_name = _translate_model_name(model_name)
    # threads <= 0 时自动计算：取 CPU 核数 1/4，至少 1 线程
    effective_threads = threads if threads > 0 else max(1, os.cpu_count() // 4 or 1)
    cache_key = f"{actual_name}_t{effective_threads}"
    with _session_cache_lock:
        if cache_key not in _session_cache:
            # 让 rembg 在创建 SessionOptions 时控制线程数，避免 OpenBLAS/OMP
            # 使用默认的高并发数导致内存分配失败（bad allocation）
            if "OMP_NUM_THREADS" not in os.environ:
                os.environ["OMP_NUM_THREADS"] = str(effective_threads)
            if disable_arena:
                os.environ["ORT_DISABLE_CPU_MEM_ARENA"] = "1"
            print(f"\n[模型加载] 正在加载模型: {actual_name} ...")
            print(f"[模型加载] 首次使用会自动下载 (~300MB-1GB)，请耐心等待...")
            import sys
            sys.stdout.flush()
            _session_cache[cache_key] = new_session(actual_name)
            print(f"[模型加载] {actual_name} 加载完成 ✓")
            sys.stdout.flush()
        return _session_cache[cache_key]


def remove_bg_local(image: Image.Image, model_name: str = "rmbg-1.4",
                    threads: int = 0, disable_arena: bool = True) -> Image.Image:
    """使用 rembg 本地抠图（带预处理缩放，优化大图内存和速度）"""
    # 预处理：缩放到 MAX_BG_DIM 以内（rembg 内部会缩放到模型输入尺寸，
    # 提前缩放可以避免在全分辨率下解码/编码 PNG，大幅降低内存峰值）
    orig_size = image.size
    needs_resize = max(orig_size) > MAX_BG_DIM
    if needs_resize:
        ratio = MAX_BG_DIM / max(orig_size)
        new_size = (int(orig_size[0] * ratio), int(orig_size[1] * ratio))
        img_resized = image.resize(new_size, Image.LANCZOS)
    else:
        img_resized = image

    session = _get_session(model_name, threads, disable_arena)

    # 直接传递 PIL Image 给 rembg.remove()，跳过 PNG 编码/解码圆环，
    # 减少 CPU 开销和临时内存缓冲区
    result_img = remove(img_resized, session=session)
    if result_img.mode != "RGBA":
        result_img = result_img.convert("RGBA")

    # 推理完成后立即释放缩放副本
    if needs_resize:
        del img_resized
        gc.collect()

    # 后处理：如果缩放过，将 alpha 蒙版放大回原始尺寸再合并
    if needs_resize:
        alpha = result_img.getchannel("A")
        alpha_resized = alpha.resize(orig_size, Image.LANCZOS)
        result_img = image.convert("RGBA")
        result_img.putalpha(alpha_resized)

    return result_img


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