# Author: w2422 <z242235718@163.com>
# Copyright (C) 2026 w2422. All rights reserved.

import asyncio
import ctypes
import gc
import io
import json
import os
import shutil
import sys
import uuid
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, Form, WebSocket, WebSocketDisconnect, Query, Request, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageOps

from config import (
    INPUT_DIR, OUTPUT_DIR, TEMP_DIR, ASSETS_DIR, FRONTEND_DIR,
    CONCURRENT_PROCESS_LIMIT, CONCURRENT_BG_LIMIT, SESSION_CLEANUP_INTERVAL,
)
from backend.models import ProcessResult, TaskStatus
from backend.task_manager import task_manager
from backend.file_manager import (
    save_uploaded_file,
    delete_result_files,
    get_output_path,
    cleanup_old_files,
    periodic_cleanup,
    get_cutout_path,
    get_alpha_path,
    get_probe_alpha_path,
    get_result_meta_path,
    get_result_thumb_path,
)
from backend.utils.image_utils import generate_thumbnail
from backend.session_manager import generate_session_id, touch_session, cleanup_expired_sessions, COOKIE_NAME, get_expired_sessions, delete_session_directories, remove_session_index
from backend.processors.bg_remover import remove_background, remove_bg_local_alpha, remove_bg_local_alpha_from_path, remove_bg_local_probe_alpha_from_path, register_batch, unregister_batch, release_cached_session

# ─── 运行时配置持久化 ───
# 打包后 config.py 位于只读目录，API Key 等运行时配置改为写入 JSON 文件
# 开发模式下也使用此机制，行为一致

_RUNTIME_CONFIG_PATH: Optional[Path] = None


def _get_runtime_config_path() -> Path:
    global _RUNTIME_CONFIG_PATH
    if _RUNTIME_CONFIG_PATH is None:
        from config import DATA_DIR
        _RUNTIME_CONFIG_PATH = DATA_DIR / "runtime_config.json"
    return _RUNTIME_CONFIG_PATH


def _save_runtime_config(key: str, value: any) -> None:
    """将运行时配置保存到可写位置（%%LOCALAPPDATA%%\\ImageProcessor\\runtime_config.json）"""
    path = _get_runtime_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        data[key] = value
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass  # 非关键功能，静默失败


def _load_runtime_config(key: str, default: any = None) -> any:
    """从持久化存储读取运行时配置"""
    path = _get_runtime_config_path()
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8")).get(key, default)
    except Exception:
        pass
    return default
from backend.processors.logo_adder import add_logo
from backend.processors.watermark import (
    add_text_watermark,
    extract_blind_watermark,
)
from backend.utils.perceptual_hash import compute_phash, hamming_distance
from backend.processors.compressor import compress_image
from backend.processors.mask_cropper import apply_mask_crop


def _save_png_lossless(image: Image.Image) -> bytes:
    """保存为 PNG 并做最大无损压缩（保持透明通道，不失真）"""
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True, compress_level=9)
    return buf.getvalue()


def _find_original_path(session_id: str, image_id: str) -> Optional[Path]:
    """按 image_id 查找原始上传文件路径（兼容内存记录丢失后的回退）。"""
    meta = image_store.get(session_id, {}).get(image_id)
    if meta and os.path.exists(meta["path"]):
        return Path(meta["path"])

    session_input = INPUT_DIR / session_id
    for ext in ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif']:
        path = session_input / f"{image_id}{ext}"
        if path.exists():
            return path
    return None


def _compose_rgba_from_source_and_alpha(source_path: Path, alpha_path: Path) -> Image.Image:
    """从原图 + alpha 蒙版合成 RGBA cutout。"""
    with Image.open(source_path) as src_img:
        src_img.load()
        base_img = ImageOps.exif_transpose(src_img)
    if base_img.mode != "RGBA":
        base_img = base_img.convert("RGBA")

    with Image.open(alpha_path) as alpha_img:
        alpha_img.load()
        alpha = alpha_img.convert("L")

    try:
        if alpha.size != base_img.size:
            resized_alpha = alpha.resize(base_img.size, Image.LANCZOS)
            try:
                base_img.putalpha(resized_alpha)
            finally:
                try:
                    resized_alpha.close()
                except Exception:
                    pass
        else:
            base_img.putalpha(alpha)
    finally:
        try:
            alpha.close()
        except Exception:
            pass

    return base_img


def _build_alpha_thumbnail_from_source_and_alpha(source_path: Path, alpha_path: Path, size: int = 200) -> bytes:
    """仅为缩略图生成小尺寸 RGBA 预览，避免先重建整张全分辨率 cutout。"""
    with Image.open(source_path) as src_img:
        try:
            src_img.draft("RGB", (size, size))
        except Exception:
            pass
        src_img.thumbnail((size, size), Image.LANCZOS)
        target = ImageOps.exif_transpose(src_img)
        target.load()

    try:
        if target.mode != "RGBA":
            small_img = target.convert("RGBA")
        else:
            small_img = target
        try:
            with Image.open(alpha_path) as alpha_img:
                alpha_img.thumbnail((size, size), Image.LANCZOS)
                alpha = alpha_img.convert("L")
            try:
                if alpha.size != small_img.size:
                    resized_alpha = alpha.resize(small_img.size, Image.LANCZOS)
                    try:
                        small_img.putalpha(resized_alpha)
                    finally:
                        try:
                            resized_alpha.close()
                        except Exception:
                            pass
                else:
                    small_img.putalpha(alpha)
                return generate_thumbnail(small_img, size=size, copy_image=False)
            finally:
                try:
                    alpha.close()
                except Exception:
                    pass
        finally:
            try:
                small_img.close()
            except Exception:
                pass
    finally:
        if target.mode == "RGBA":
            try:
                target.close()
            except Exception:
                pass


def _load_result_meta(session_id: str, image_id: str, run_id: str) -> Optional[dict]:
    """读取结果元数据。"""
    meta_path = get_result_meta_path(image_id, run_id=run_id, session_id=session_id)
    if not meta_path.exists():
        return None
    try:
        with open(meta_path, encoding="utf-8") as mf:
            return json.load(mf)
    except Exception:
        return None


def _save_result_meta(session_id: str, image_id: str, run_id: str, payload: dict) -> None:
    """统一写入结果元数据。"""
    meta_path = get_result_meta_path(image_id, run_id=run_id, session_id=session_id)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    with open(meta_path, "w", encoding="utf-8") as mf:
        json.dump(payload, mf, ensure_ascii=False)


def _find_latest_alpha_meta(session_id: str, image_id: str) -> Optional[dict]:
    """查找当前图片最新的 alpha-only-v1 结果元数据。"""
    session_temp = TEMP_DIR / session_id
    if not session_temp.exists():
        return None

    latest = None
    for f in session_temp.iterdir():
        if not f.name.startswith(f"{image_id}_") or not f.name.endswith("_meta.json"):
            continue
        try:
            with open(f, encoding="utf-8") as mf:
                data = json.load(mf)
        except Exception:
            continue
        if data.get("id") != image_id:
            continue
        if data.get("protocol_version") != "alpha-only-v1":
            continue
        if latest is None or data.get("finished_at", "") > latest.get("finished_at", ""):
            latest = data
    return latest


def _get_alpha_path_from_meta(session_id: str, meta: Optional[dict], image_id: str) -> Optional[Path]:
    """从结果元数据或默认别名解析全尺寸 alpha 文件路径。"""
    if meta:
        alpha_rel = meta.get("alpha_url", "")
        if alpha_rel.startswith("/api/alpha/"):
            alpha_path = get_alpha_path(image_id, run_id=meta.get("run_id", ""), session_id=session_id)
            if alpha_path.exists():
                return alpha_path
        if meta.get("alpha_storage") == "probe":
            return None
    alpha_path = get_alpha_path(image_id, session_id=session_id)
    if alpha_path.exists():
        return alpha_path
    return None


def _get_probe_alpha_path_from_meta(session_id: str, meta: Optional[dict], image_id: str) -> Optional[Path]:
    """从结果元数据或默认别名解析 probe alpha 小图路径。"""
    if meta:
        run_id = meta.get("run_id", "")
        probe_path = get_probe_alpha_path(image_id, run_id=run_id, session_id=session_id)
        if probe_path.exists():
            return probe_path
    probe_path = get_probe_alpha_path(image_id, session_id=session_id)
    if probe_path.exists():
        return probe_path
    return None


def _materialize_alpha_asset(session_id: str, meta: dict, image_id: str) -> Path:
    """按需将 probe alpha 放大为全尺寸 alpha 资产，供兼容接口/编辑器使用。"""
    alpha_path = get_alpha_path(image_id, run_id=meta.get("run_id", ""), session_id=session_id)
    if alpha_path.exists():
        return alpha_path
    probe_path = _get_probe_alpha_path_from_meta(session_id, meta, image_id)
    if probe_path is None:
        raise FileNotFoundError("probe alpha 资产不存在")

    source_width = int(meta.get("source_width") or 0)
    source_height = int(meta.get("source_height") or 0)
    if source_width <= 0 or source_height <= 0:
        source_path = _find_original_path(session_id, meta.get("source_image_id", image_id))
        if not source_path:
            raise FileNotFoundError("原图不存在")
        with Image.open(source_path) as src_img:
            source_width, source_height = ImageOps.exif_transpose(src_img).size

    with Image.open(probe_path) as probe_img:
        probe_alpha = probe_img.convert("L")
    try:
        if probe_alpha.size != (source_width, source_height):
            alpha_full = probe_alpha.resize((source_width, source_height), Image.LANCZOS)
        else:
            alpha_full = probe_alpha
        try:
            alpha_path.parent.mkdir(parents=True, exist_ok=True)
            alpha_full.save(alpha_path, "PNG")
            return alpha_path
        finally:
            if alpha_full is not probe_alpha:
                try:
                    alpha_full.close()
                except Exception:
                    pass
    finally:
        try:
            probe_alpha.close()
        except Exception:
            pass
        gc.collect()
        _compact_heap()


def _build_result_meta(
    image_id: str,
    filename: str,
    run_id: str,
    features: str,
    output_size: int,
    finished_at: str,
    *,
    protocol_version: str = "legacy",
    source_image_id: str = "",
    result_kind: str = "materialized",
    preview_url: str = "",
    download_url: str = "",
    alpha_url: str = "",
    materialized: bool = True,
    cutout_editable: bool = False,
    has_alpha_source: bool = False,
) -> dict:
    """构造统一结果元数据。"""
    download_url = download_url or f"/api/download/{run_id}/{image_id}"
    preview_url = preview_url or f"/api/preview/{run_id}/{image_id}"
    payload = {
        "id": image_id,
        "filename": filename,
        "run_id": run_id,
        "features": features,
        "output_size": output_size,
        "output_url": download_url,
        "download_url": download_url,
        "thumbnail_url": f"/api/result-thumbnail/{run_id}/{image_id}",
        "preview_url": preview_url,
        "finished_at": finished_at,
        "protocol_version": protocol_version,
        "source_image_id": source_image_id or image_id,
        "result_kind": result_kind,
        "alpha_url": alpha_url,
        "materialized": materialized,
        "cutout_editable": cutout_editable,
        "has_alpha_source": has_alpha_source,
    }
    return payload


def _materialize_result_bytes(session_id: str, meta: dict) -> tuple[bytes, str, str]:
    """为 alpha-only 结果按需生成导出文件字节。"""
    image_id = meta["id"]
    run_id = meta.get("run_id", "")
    source_path = _find_original_path(session_id, meta.get("source_image_id", image_id))
    alpha_path = _get_alpha_path_from_meta(session_id, meta, image_id)
    if alpha_path is None:
        alpha_path = _get_probe_alpha_path_from_meta(session_id, meta, image_id)
    if not source_path or not alpha_path:
        raise FileNotFoundError("alpha-only 结果缺少原图或 alpha 资产")

    with Image.open(alpha_path) as alpha_img:
        alpha = alpha_img.convert("L")

    try:
        with Image.open(source_path) as src_img:
            src_img.load()
            base_img = ImageOps.exif_transpose(src_img)
        try:
            output_format = meta.get("render_output_format", "PNG")
            quality = int(meta.get("render_quality", 95) or 95)
            max_file_size_kb = int(meta.get("render_max_file_size_kb", 0) or 0)
            max_width = int(meta.get("render_max_width", 0) or 0)
            source_file_size = int(meta.get("source_file_size", 0) or 0)
            prefer_target_jpeg_size = bool(meta.get("prefer_target_jpeg_size", False))
            if base_img.mode != "RGBA":
                rgba_img = base_img.convert("RGBA")
                try:
                    working_img = rgba_img
                    if alpha.size != working_img.size:
                        resized_alpha = alpha.resize(working_img.size, Image.LANCZOS)
                    else:
                        resized_alpha = alpha
                    try:
                        working_img.putalpha(resized_alpha)
                        data = compress_image(
                            working_img,
                            output_format,
                            quality,
                            max_file_size_kb,
                            max_width,
                            source_file_size,
                            prefer_target_jpeg_size,
                        )
                    finally:
                        if resized_alpha is not alpha:
                            try:
                                resized_alpha.close()
                            except Exception:
                                pass
                finally:
                    try:
                        rgba_img.close()
                    except Exception:
                        pass
            else:
                if alpha.size != base_img.size:
                    resized_alpha = alpha.resize(base_img.size, Image.LANCZOS)
                else:
                    resized_alpha = alpha
                try:
                    base_img.putalpha(resized_alpha)
                    data = compress_image(
                        base_img,
                        output_format,
                        quality,
                        max_file_size_kb,
                        max_width,
                        source_file_size,
                        prefer_target_jpeg_size,
                    )
                finally:
                    if resized_alpha is not alpha:
                        try:
                            resized_alpha.close()
                        except Exception:
                            pass
        finally:
            try:
                base_img.close()
            except Exception:
                pass
    finally:
        try:
            alpha.close()
        except Exception:
            pass

    ext_map = {"JPEG": ".jpg", "JPG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
    ext = ext_map.get(str(meta.get("render_output_format", "PNG")).upper(), ".png")
    filename = Path(meta.get("filename") or f"{image_id}{ext}").stem + ext
    return data, ext, filename


def _compute_features_str(
    bg_method: str = "none",
    logo_enabled: bool = False,
    wm_mode: str = "off",
    wm_text: str = "",
    wm_blind_enabled: bool = False,
    compress_enabled: bool = False,
) -> str:
    """根据处理参数计算 features 字符串，供 _meta.json 持久化"""
    parts = []
    if bg_method != "none":
        parts.append("bg")
    if logo_enabled:
        parts.append("logo")
    if wm_mode in ("position", "tile", "dense") and wm_text:
        parts.append("watermark")
    if wm_blind_enabled:
        parts.append("blind")
    if compress_enabled:
        parts.append("compress")
    return ",".join(parts)


# ─── Windows 堆紧缩 ───
# gc.collect() 释放 Python 对象后，numpy/ONNX 的 C 缓冲区被 free() 但
# Windows C 运行时（ucrtbase）不将空闲页归还给 OS，导致内存基线居高不下。
# HeapCompact 强制合并空闲块并将空页归还给 OS。

_WIN32 = sys.platform == "win32"
if _WIN32:
    _GetProcessHeap = ctypes.windll.kernel32.GetProcessHeap
    _GetProcessHeap.restype = ctypes.c_void_p

    _HeapCompact = ctypes.windll.kernel32.HeapCompact
    _HeapCompact.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    _HeapCompact.restype = ctypes.c_size_t


def _compact_heap():
    """Windows 堆紧缩：将 C 堆中已 free() 的页面归还给 OS"""
    if _WIN32:
        for _ in range(3):
            try:
                _HeapCompact(_GetProcessHeap(), 0)
            except Exception:
                break


def _prewarm_bg_model(method: str, api_key: str, model: str, threads: int, disable_arena: bool):
    """预加载抠图模型 + 跑一次小推理，预热 ONNX 内部状态

    隔离模型加载和首次推理的内存尖峰，使其发生在批处理开始之前。
    local 模式预热 alpha-only 通路，避免首张图意外走 legacy cutout 合成链。
    """
    dummy = Image.new("RGBA", (64, 64), (0, 0, 0, 255))
    if method == "local":
        alpha = remove_bg_local_alpha(dummy, model, threads, disable_arena)
        try:
            alpha.close()
        except Exception:
            pass
        return
    remove_background(dummy, method, api_key, model, threads, disable_arena)


app = FastAPI(title="图片批量处理工具")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 内存存储（session_id -> image_id -> meta）
image_store: Dict[str, Dict[str, dict]] = {}
logo_store: Dict[str, Dict[str, dict]] = {}
_active_worker_tasks = set()

# ─── Session 中间件 ───


@app.middleware("http")
async def session_middleware(request: Request, call_next):
    """自动管理 SessionID：首次访问生成并写入 Cookie，后续请求自动携带"""
    session_id = request.cookies.get(COOKIE_NAME)
    if not session_id:
        session_id = generate_session_id()
    # 更新活动时间（仅在非静态文件请求时，减少磁盘 I/O）
    path = request.url.path
    if not path.startswith("/assets/") and not path.startswith("/frontend/"):
        touch_session(session_id)
    request.state.session_id = session_id
    response = await call_next(request)
    if COOKIE_NAME not in request.cookies:
        response.set_cookie(
            key=COOKIE_NAME,
            value=session_id,
            httponly=True,
            max_age=86400 * 30,  # 30 天
            samesite="lax",
        )
    return response


# 静态文件
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")
app.mount("/frontend", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")


async def sunday_full_cleanup():
    """每周日 03:00 清理所有处理结果（输出 + 临时目录）"""
    while True:
        now = datetime.now()
        # 计算到下一个周日 03:00 的秒数
        days_until_sunday = (6 - now.weekday()) % 7
        if days_until_sunday == 0 and now.hour >= 3:
            days_until_sunday = 7
        next_run = (now + timedelta(days=days_until_sunday)).replace(
            hour=3, minute=0, second=0, microsecond=0
        )
        wait_seconds = (next_run - now).total_seconds()
        await asyncio.sleep(wait_seconds)

        # 删除所有结果文件（保留 session 目录结构）
        for dir_path in [OUTPUT_DIR, TEMP_DIR]:
            if not dir_path.exists():
                continue
            for f in dir_path.iterdir():
                try:
                    if f.is_file():
                        os.remove(f)
                    elif f.is_dir():
                        shutil.rmtree(f, ignore_errors=True)
                except OSError:
                    pass


async def periodic_session_cleanup():
    """后台定时任务：清理过期 Session 的资源"""
    while True:
        await asyncio.sleep(SESSION_CLEANUP_INTERVAL)
        count = cleanup_expired_sessions()
        # 同时清理普通过期文件
        cleanup_old_files()


@app.on_event("startup")
async def startup():
    # 启动时立即清理过期 Session 和文件
    cleanup_expired_sessions()
    cleanup_old_files()
    # 后台定时任务：每小时清理过期 Session + 文件
    asyncio.create_task(periodic_session_cleanup())
    # 后台定时任务：每周日 03:00 彻底清理所有结果
    asyncio.create_task(sunday_full_cleanup())


# ─── 页面 ───

@app.get("/")
async def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


# ─── 上传 ───

@app.post("/api/upload")
async def upload_images(request: Request, files: List[UploadFile] = File(...)):
    session_id = request.state.session_id
    uploaded = []
    for file in files:
        if not file.filename:
            continue
        try:
            content = await file.read()
            meta = save_uploaded_file(content, file.filename, session_id=session_id)
            image_store.setdefault(session_id, {})[meta["id"]] = meta
            uploaded.append(meta)
        except ValueError as e:
            continue  # 跳过不合法文件

    return {"images": uploaded, "total": len(uploaded)}


@app.post("/api/upload-logo")
async def upload_logo(request: Request, file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="无效文件")
    try:
        session_id = request.state.session_id
        content = await file.read()
        meta = save_uploaded_file(content, file.filename, session_id=session_id)
        logo_store.setdefault(session_id, {})[meta["id"]] = meta
        return {"logo_id": meta["id"], "thumbnail_url": meta["thumbnail_url"]}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── 图片管理 ───

@app.get("/api/images")
async def list_images(request: Request):
    session_id = request.state.session_id
    images = list(image_store.get(session_id, {}).values())
    return {"images": images}


@app.delete("/api/images/{image_id}")
async def delete_image(request: Request, image_id: str):
    session_id = request.state.session_id
    session_images = image_store.get(session_id, {})
    if image_id not in session_images:
        raise HTTPException(status_code=404, detail="图片不存在")
    session_images.pop(image_id)
    # 仅移除内存记录，不删除源文件，避免已存在的结果卡片预览失效
    return {"ok": True}


@app.delete("/api/results")
async def clear_all_results(request: Request):
    """清除当前 session 的所有处理结果文件（输出+临时目录），保留原始上传"""
    session_id = request.state.session_id
    for base_dir in [OUTPUT_DIR, TEMP_DIR]:
        session_dir = base_dir / session_id
        if session_dir.exists():
            shutil.rmtree(session_dir, ignore_errors=True)
    return {"ok": True}


@app.get("/api/results")
async def list_all_results(request: Request):
    """列出当前 session 的所有已保存处理结果（供页面刷新后重新加载结果卡片）"""
    session_id = request.state.session_id
    session_temp = TEMP_DIR / session_id
    results = []
    if session_temp.exists():
        for f in session_temp.iterdir():
            if f.name.endswith("_meta.json"):
                try:
                    with open(f) as mf:
                        data = json.load(mf)
                    results.append(data)
                except Exception:
                    pass
    # 按完成时间降序排列
    results.sort(key=lambda r: r.get("finished_at", ""), reverse=True)
    return {"results": results}


@app.delete("/api/results/{image_id}")
async def delete_result(request: Request, image_id: str, run_id: str = Query("")):
    """只删除当前 session 的处理结果，保留原始上传图片"""
    session_id = request.state.session_id
    delete_result_files(image_id, run_id=run_id, session_id=session_id)
    return {"ok": True}


# ─── 缩略图 & 原图 ───

@app.get("/api/logo-default")
async def get_default_logo():
    """获取默认 Logo 图片"""
    logo_path = ASSETS_DIR / "logo.png"
    if logo_path.exists():
        return FileResponse(logo_path, media_type="image/png")
    raise HTTPException(status_code=404, detail="默认Logo不存在")


@app.get("/api/thumbnail/{image_id}")
async def get_thumbnail(request: Request, image_id: str):
    session_id = request.state.session_id
    session_temp = TEMP_DIR / session_id
    thumb_path = session_temp / f"{image_id}_thumb.png"
    if thumb_path.exists():
        return FileResponse(thumb_path, media_type="image/png")
    meta = image_store.get(session_id, {}).get(image_id)
    if meta and os.path.exists(meta["path"]):
        return FileResponse(meta["path"])
    # 回退：从 session 的 input 目录下直接找原图
    session_input = INPUT_DIR / session_id
    for ext in ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif']:
        path = session_input / f"{image_id}{ext}"
        if path.exists():
            return FileResponse(path)
    raise HTTPException(status_code=404, detail="缩略图不存在")


@app.get("/api/original/{image_id}")
async def get_original(request: Request, image_id: str):
    session_id = request.state.session_id
    meta = image_store.get(session_id, {}).get(image_id)
    if meta and os.path.exists(meta["path"]):
        return FileResponse(meta["path"])
    # 如果内存记录已被删除，直接从 session 的 input 目录查找
    session_input = INPUT_DIR / session_id
    for ext in ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif']:
        path = session_input / f"{image_id}{ext}"
        if path.exists():
            return FileResponse(path)
    raise HTTPException(status_code=404, detail="原图不存在")


@app.get("/api/cutout/{image_id}")
async def get_cutout(request: Request, image_id: str):
    """获取抠图结果 PNG（含透明通道），供编辑器使用"""
    session_id = request.state.session_id
    cutout_path = get_cutout_path(image_id, session_id=session_id)
    if cutout_path.exists():
        return FileResponse(cutout_path, media_type="image/png")

    alpha_meta = _find_latest_alpha_meta(session_id, image_id)
    alpha_path = _get_alpha_path_from_meta(session_id, alpha_meta, image_id)
    if alpha_path is None:
        alpha_path = _get_probe_alpha_path_from_meta(session_id, alpha_meta, image_id)
    source_path = _find_original_path(session_id, image_id)
    if alpha_path and source_path:
        try:
            with _compose_rgba_from_source_and_alpha(source_path, alpha_path) as cutout_img:
                # 限制输出尺寸，加速编辑器加载（大图从 3000→1200px 以内）
                w, h = cutout_img.size
                MAX_CUTOUT_SIZE = 1200
                if max(w, h) > MAX_CUTOUT_SIZE:
                    cutout_img.thumbnail((MAX_CUTOUT_SIZE, MAX_CUTOUT_SIZE), Image.LANCZOS)
                png_data = await asyncio.to_thread(_save_png_lossless, cutout_img)
            return StreamingResponse(io.BytesIO(png_data), media_type="image/png")
        except Exception:
            pass

    # 没有抠图结果则回退到原图
    if source_path and source_path.exists():
        return FileResponse(source_path)
    raise HTTPException(status_code=404, detail="抠图结果不存在")


@app.get("/api/alpha/{run_id}/{image_id}")
async def get_alpha_asset(request: Request, run_id: str, image_id: str):
    """获取 alpha-only 资产（单通道 PNG）"""
    session_id = request.state.session_id
    alpha_path = get_alpha_path(image_id, run_id=run_id, session_id=session_id)
    if not alpha_path.exists():
        alpha_path = get_alpha_path(image_id, session_id=session_id)
    if alpha_path.exists():
        return FileResponse(alpha_path, media_type="image/png")
    meta = _load_result_meta(session_id, image_id, run_id)
    if meta and meta.get("alpha_storage") == "probe":
        try:
            alpha_path = await asyncio.to_thread(_materialize_alpha_asset, session_id, meta, image_id)
            return FileResponse(alpha_path, media_type="image/png")
        except FileNotFoundError:
            pass
    raise HTTPException(status_code=404, detail="alpha 资产不存在")


@app.get("/api/preview/{run_id}/{image_id}")
async def get_result_preview(request: Request, run_id: str, image_id: str):
    """获取结果预览图，alpha-only 结果按需从 source + alpha 合成。"""
    session_id = request.state.session_id
    meta = _load_result_meta(session_id, image_id, run_id)
    if meta and meta.get("protocol_version") == "alpha-only-v1":
        source_path = _find_original_path(session_id, meta.get("source_image_id", image_id))
        alpha_path = _get_alpha_path_from_meta(session_id, meta, image_id)
        if alpha_path is None:
            alpha_path = _get_probe_alpha_path_from_meta(session_id, meta, image_id)
        if source_path and alpha_path:
            with _compose_rgba_from_source_and_alpha(source_path, alpha_path) as preview_img:
                png_data = await asyncio.to_thread(_save_png_lossless, preview_img)
            return StreamingResponse(io.BytesIO(png_data), media_type="image/png")

    for ext in [".jpg", ".png", ".webp"]:
        path = get_output_path(image_id, ext, run_id=run_id, session_id=session_id)
        if path.exists():
            return FileResponse(path)
    raise HTTPException(status_code=404, detail="预览不存在")


@app.get("/api/last-mask/{image_id}")
async def get_last_mask(request: Request, image_id: str):
    """获取该图片最近一次保存的蒙版 PNG，供「再次编辑」预填画板。"""
    session_id = request.state.session_id
    session_temp = TEMP_DIR / session_id
    last_mask_path = session_temp / f"{image_id}_last_mask.png"
    if not last_mask_path.exists():
        raise HTTPException(status_code=404, detail="尚未保存过蒙版")
    return FileResponse(last_mask_path, media_type="image/png")


# ─── 异步处理 ───

@app.post("/api/process")
async def process_images(
    request: Request,
    bg_method: str = Form("none"),
    bg_model: str = Form("rmbg-1.4"),
    api_key: str = Form(""),
    bg_threads: int = Form(0),
    bg_disable_arena: bool = Form(False),
    logo_enabled: bool = Form(False),
    logo_position: str = Form("right-bottom"),
    logo_ratio: float = Form(0.15),
    logo_opacity: float = Form(0.8),
    logo_margin: int = Form(20),
    logo_tile: bool = Form(False),
    logo_file_id: Optional[str] = Form(None),
    wm_mode: str = Form("off"),
    wm_text: Optional[str] = Form(None),
    wm_text_color: str = Form("#FFFFFF"),
    wm_text_ratio: float = Form(0.05),
    wm_opacity: float = Form(0.5),
    wm_position: str = Form("right-bottom"),
    wm_tile_direction: str = Form("horizontal"),
    wm_dense_density: int = Form(5),
    wm_blind_enabled: bool = Form(False),
    wm_blind_text: Optional[str] = Form(None),
    wm_blind_strength: int = Form(16),
    wm_blind_use_mask: bool = Form(True),
    compress_enabled: bool = Form(True),
    output_format: str = Form("JPEG"),
    quality: int = Form(85),
    max_file_size_kb: int = Form(0),
    max_width: int = Form(0),
    mask: Optional[UploadFile] = File(None),
    target_image_id: Optional[str] = Form(None),
    image_ids: Optional[str] = Form(None),
    crop_mask_count: int = Form(0),
):
    session_id = request.state.session_id
    session_images = image_store.get(session_id, {})
    if not session_images:
        raise HTTPException(status_code=400, detail="请先上传图片")

    # 如果带了蒙版 + target_image_id，则只处理这一张
    if mask is not None and target_image_id and target_image_id in session_images:
        image_ids_list = [target_image_id]
    elif image_ids:
        # 前端指定了要处理的图片 ID，只处理这些
        ids = [iid.strip() for iid in image_ids.split(",") if iid.strip() in session_images]
        if not ids:
            raise HTTPException(status_code=400, detail="没有有效的图片 ID")
        image_ids_list = ids
    else:
        image_ids_list = list(session_images.keys())
    filenames = [session_images[iid]["filename"] for iid in image_ids_list]
    task = task_manager.create_task(image_ids_list, filenames, session_id=session_id)
    task.status = TaskStatus.RUNNING

    # 预读蒙版字节（mask 是一次性的 UploadFile）
    mask_bytes: Optional[bytes] = None
    if mask is not None:
        mask_bytes = await mask.read()

    # 读批量蒙版（crop_mask_count > 0 时从动态字段 mask_0, mask_1, ... 读取）
    mask_map: Optional[Dict[int, bytes]] = None
    if crop_mask_count > 0:
        mask_map = {}
        form_data = await request.form()
        for i in range(crop_mask_count):
            key = f"mask_{i}"
            if key in form_data:
                upload_file = form_data[key]
                mask_map[i] = await upload_file.read()

    config = {
        "bg_method": bg_method,
        "bg_model": bg_model,
        "api_key": api_key,
        "bg_threads": bg_threads,
        "bg_disable_arena": bg_disable_arena,
        "logo_enabled": logo_enabled,
        "logo_position": logo_position,
        "logo_ratio": logo_ratio,
        "logo_opacity": logo_opacity,
        "logo_margin": logo_margin,
        "logo_tile": logo_tile,
        "logo_file_id": logo_file_id,
        "wm_mode": wm_mode,
        "wm_text": wm_text,
        "wm_text_color": wm_text_color,
        "wm_text_ratio": wm_text_ratio,
        "wm_opacity": wm_opacity,
        "wm_position": wm_position,
        "wm_tile_direction": wm_tile_direction,
        "wm_dense_density": wm_dense_density,
        "wm_blind_enabled": wm_blind_enabled,
        "wm_blind_text": wm_blind_text,
        "wm_blind_strength": wm_blind_strength,
        "wm_blind_use_mask": wm_blind_use_mask,
        "compress_enabled": compress_enabled,
        "output_format": output_format,
        "quality": quality,
        "max_file_size_kb": max_file_size_kb,
        "max_width": max_width,
    }

    # 加载 Logo（从当前 session 的 logo_store 中查找）
    logo_img = None
    if logo_enabled:
        session_logos = logo_store.get(session_id, {})
        if logo_file_id and logo_file_id in session_logos:
            logo_img = Image.open(session_logos[logo_file_id]["path"]).convert("RGBA")
        else:
            logo_path = ASSETS_DIR / "logo.png"
            if logo_path.exists():
                logo_img = Image.open(logo_path).convert("RGBA")

    worker_task = asyncio.create_task(_batch_process(task.batch_id, image_ids_list, config, logo_img, mask_bytes, mask_map=mask_map, session_id=session_id))
    _active_worker_tasks.add(worker_task)
    worker_task.add_done_callback(_active_worker_tasks.discard)
    return {"batch_id": task.batch_id, "total": task.total, "image_ids": image_ids_list}


async def _batch_process(batch_id: str, image_ids: List[str], config: dict, logo_img, mask_bytes: Optional[bytes] = None, mask_map: Optional[Dict[int, bytes]] = None, session_id: str = ""):
    # 启用抠图时，外层信号量设为 1（串行处理），避免多张全分辨率图同时驻留内存。
    # ONNX 推理本身已通过 bg_semaphore=1 串行化，降低并发对吞吐量无影响。
    has_bg_batch = config.get("bg_method", "none") != "none"
    effective_limit = 1 if has_bg_batch else CONCURRENT_PROCESS_LIMIT
    semaphore = asyncio.Semaphore(effective_limit)
    # 背景移除（ONNX推理）使用独立信号量，避免多张图同时推理导致OOM
    bg_semaphore = asyncio.Semaphore(CONCURRENT_BG_LIMIT)

    async def process_one(image_id: str):
        async with semaphore:
            if task_manager.is_cancelled(batch_id):
                return
            meta = image_store.get(session_id, {}).get(image_id)
            if not meta:
                result = ProcessResult(id=image_id, filename="unknown", status="error", error_msg="原始图片已不存在")
                await task_manager.update_result(batch_id, result)
                return

            result = ProcessResult(id=image_id, filename=meta["filename"], status="processing")
            try:
                cutout_path = get_cutout_path(image_id, session_id=session_id)
                alpha_path = get_alpha_path(image_id, run_id=batch_id, session_id=session_id)
                alpha_alias_path = get_alpha_path(image_id, session_id=session_id)
                has_bg = config["bg_method"] != "none"
                is_local_bg = config["bg_method"] == "local"
                has_post_process = (
                    config["logo_enabled"] and logo_img
                ) or (
                    config["wm_mode"] in ("position", "tile", "dense") and config["wm_text"]
                ) or mask_bytes or mask_map
                alpha_only_fast_path = has_bg and is_local_bg and not has_post_process
                result.error_msg = json.dumps({
                    "alpha_only_fast_path": alpha_only_fast_path,
                    "has_bg": has_bg,
                    "is_local_bg": is_local_bg,
                    "has_post_process": bool(has_post_process),
                    "bg_method": config.get("bg_method"),
                    "wm_mode": config.get("wm_mode"),
                    "wm_text": bool(config.get("wm_text")),
                    "logo_enabled": bool(config.get("logo_enabled")),
                    "mask_bytes": bool(mask_bytes),
                    "mask_map_count": len(mask_map) if mask_map else 0,
                }, ensure_ascii=False)

                source_path = Path(meta["path"])
                img = None
                materialized_output_size = 0
                source_size = None
                probe_size = None
                probe_alpha_path = None
                probe_alpha_alias_path = None

                # 1. 抠图（使用独立信号量，并发数 = CONCURRENT_BG_LIMIT）
                if has_bg:
                    if task_manager.is_cancelled(batch_id):
                        result.status = "error"; result.error_msg = "已取消"
                        await task_manager.update_result(batch_id, result); return
                    async with bg_semaphore:
                        # 再次检查取消（等待信号量期间可能已被取消）
                        if task_manager.is_cancelled(batch_id):
                            result.status = "error"; result.error_msg = "已取消"
                            await task_manager.update_result(batch_id, result); return

                        if is_local_bg:
                            if alpha_only_fast_path:
                                alpha, source_size, probe_size = await asyncio.to_thread(
                                    remove_bg_local_probe_alpha_from_path, source_path,
                                    config["bg_model"], config["bg_threads"], config["bg_disable_arena"]
                                )
                                probe_alpha_path = get_probe_alpha_path(image_id, run_id=batch_id, session_id=session_id)
                                probe_alpha_alias_path = get_probe_alpha_path(image_id, session_id=session_id)
                                probe_alpha_path.parent.mkdir(parents=True, exist_ok=True)
                                await asyncio.to_thread(alpha.save, str(probe_alpha_path), "PNG")
                                await asyncio.to_thread(alpha.save, str(probe_alpha_alias_path), "PNG")
                                for ext in (".jpg", ".png", ".webp"):
                                    stale_output = get_output_path(image_id, ext, run_id=batch_id, session_id=session_id)
                                    if stale_output.exists():
                                        try:
                                            stale_output.unlink()
                                        except OSError:
                                            pass
                                try:
                                    alpha.close()
                                except Exception:
                                    pass
                                del alpha
                            else:
                                with Image.open(source_path) as src_img:
                                    src_img.load()
                                    img = await asyncio.to_thread(ImageOps.exif_transpose, src_img)
                                alpha = await asyncio.to_thread(
                                    remove_bg_local_alpha, img,
                                    config["bg_model"], config["bg_threads"], config["bg_disable_arena"]
                                )
                                alpha_path.parent.mkdir(parents=True, exist_ok=True)
                                await asyncio.to_thread(alpha.save, str(alpha_path), "PNG")
                                await asyncio.to_thread(alpha.save, str(alpha_alias_path), "PNG")
                                if has_post_process:
                                    base_img = img if img.mode == "RGBA" else img.convert("RGBA")
                                    try:
                                        base_img.putalpha(alpha)
                                    finally:
                                        try:
                                            alpha.close()
                                        except Exception:
                                            pass
                                        del alpha
                                        gc.collect()
                                    img = base_img
                                else:
                                    try:
                                        alpha.close()
                                    except Exception:
                                        pass
                                    del alpha
                        else:
                            with Image.open(source_path) as src_img:
                                src_img.load()
                                img = await asyncio.to_thread(ImageOps.exif_transpose, src_img)
                            # 环境变量 ORT_DISABLE_CPU_MEM_ARENA 由 bg_remover._get_session 统一管理
                            img = await asyncio.to_thread(
                                remove_background, img, config["bg_method"], config["api_key"],
                                config["bg_model"], config["bg_threads"], config["bg_disable_arena"]
                            )
                            # 非 local 路径先保持 legacy cutout.png 兼容行为
                            cutout_path.parent.mkdir(parents=True, exist_ok=True)
                            await asyncio.to_thread(img.save, str(cutout_path), "PNG")

                    # batch 保守路径：抠图后立刻释放全分辨率结果，后续按需从 cutout / source+alpha 重开
                    if img is not None and is_local_bg and alpha_only_fast_path:
                        try:
                            img.close()
                        except Exception:
                            pass
                        del img
                        img = None
                        gc.collect()
                        _compact_heap()
                    elif img is not None and not is_local_bg:
                        try:
                            img.close()
                        except Exception:
                            pass
                        del img
                        img = None
                        gc.collect()
                        _compact_heap()

                        if has_post_process:
                            with Image.open(cutout_path) as cutout_img:
                                cutout_img.load()
                                img = cutout_img.convert("RGBA")
                else:
                    with Image.open(source_path) as src_img:
                        src_img.load()
                        img = await asyncio.to_thread(ImageOps.exif_transpose, src_img)

                # 2. Logo (图片型)
                if config["logo_enabled"] and logo_img:
                    if task_manager.is_cancelled(batch_id):
                        result.status = "error"; result.error_msg = "已取消"
                        await task_manager.update_result(batch_id, result); return
                    new_img = await asyncio.to_thread(
                        add_logo, img, logo_img,
                        config["logo_position"],
                        config["logo_ratio"],
                        config["logo_opacity"],
                        margin=config["logo_margin"],
                        tile=config["logo_tile"],
                    )
                    del img; img = new_img

                # 3. 显式水印
                if config["wm_mode"] in ("position", "tile", "dense") and config["wm_text"]:
                    if task_manager.is_cancelled(batch_id):
                        result.status = "error"; result.error_msg = "已取消"
                        await task_manager.update_result(batch_id, result); return
                    new_img = await asyncio.to_thread(
                        add_text_watermark, img,
                        config["wm_text"],
                        config["wm_position"],
                        config["wm_text_ratio"],
                        config["wm_opacity"],
                        config["wm_text_color"],
                        config["wm_mode"] == "tile" or config["wm_mode"] == "dense",
                        config["wm_tile_direction"],
                        config["wm_mode"] == "dense",
                        config["wm_dense_density"],
                    )
                    del img; img = new_img

                # 4. 蒙版裁切（用户手绘蒙版；全白/缺失 = no-op）
                # 从 mask_map 按图片索引取对应 mask，若无则回退到 mask_bytes
                img_mask_bytes = mask_bytes
                if mask_map:
                    try:
                        idx = image_ids.index(image_id)
                        mask_keys = sorted(mask_map.keys())
                        if mask_keys:
                            mask_idx = min(idx, mask_keys[-1])
                            img_mask_bytes = mask_map.get(mask_idx, mask_bytes)
                    except ValueError:
                        pass
                if img_mask_bytes:
                    if task_manager.is_cancelled(batch_id):
                        result.status = "error"; result.error_msg = "已取消"
                        await task_manager.update_result(batch_id, result); return
                    img = await asyncio.to_thread(apply_mask_crop, img, img_mask_bytes)
                    # 保存蒙版供「再次编辑」预填
                    last_mask_path = TEMP_DIR / session_id / f"{image_id}_last_mask.png"
                    last_mask_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(last_mask_path, "wb") as f:
                        f.write(img_mask_bytes)

                if task_manager.is_cancelled(batch_id):
                    result.status = "error"; result.error_msg = "已取消"
                    await task_manager.update_result(batch_id, result); return

                # local-bg 且无后处理：直接走 alpha-only descriptor + lazy export
                protocol_version = "legacy"
                materialized = True
                output_size = 0
                result_mode = "legacy"
                if alpha_only_fast_path:
                    print(f"DEBUG alpha-fast-path descriptor image_id={image_id} batch_id={batch_id}", flush=True)
                    release_cached_session()
                    gc.collect()
                    _compact_heap()

                    session_temp = TEMP_DIR / session_id
                    session_temp.mkdir(parents=True, exist_ok=True)
                    source_img_for_thumb = _find_original_path(session_id, image_id)
                    if source_img_for_thumb is None:
                        raise FileNotFoundError("原图不存在")

                    thumb_data = await asyncio.to_thread(
                        _build_alpha_thumbnail_from_source_and_alpha,
                        source_img_for_thumb,
                        probe_alpha_alias_path or alpha_alias_path,
                        200,
                    )
                    thumb_path = get_result_thumb_path(image_id, run_id=batch_id, session_id=session_id)
                    print(f"DEBUG alpha-fast-path before thumb write image_id={image_id} batch_id={batch_id} path={thumb_path}", flush=True)
                    with open(thumb_path, "wb") as f:
                        f.write(thumb_data)
                    print(f"DEBUG alpha-fast-path after thumb write image_id={image_id} batch_id={batch_id} bytes={len(thumb_data)}", flush=True)
                    protocol_version = "alpha-only-v1"
                    materialized = False
                    result_mode = "alpha-only-v1"
                    output_size = (probe_alpha_path or alpha_path).stat().st_size if (probe_alpha_path or alpha_path).exists() else 0
                    print(f"DEBUG alpha-fast-path after output-size image_id={image_id} batch_id={batch_id} output_size={output_size}", flush=True)
                else:
                    print(f"DEBUG legacy-branch image_id={image_id} batch_id={batch_id} has_bg={has_bg} is_local_bg={is_local_bg} has_post_process={has_post_process}", flush=True)
                    if has_bg and not has_post_process:
                        with Image.open(cutout_path) as cutout_img:
                            cutout_img.load()
                            img = cutout_img.convert("RGBA")

                    # 6. 压缩
                    original_ext = Path(meta["filename"]).suffix.lower()
                    prefer_target_jpeg_size = (
                        config["compress_enabled"]
                        and config["bg_method"] != "none"
                        and original_ext in (".jpg", ".jpeg")
                        and config["output_format"].upper() in ("JPEG", "JPG")
                        and int(config.get("max_file_size_kb", 0) or 0) <= 0
                    )
                    if config["compress_enabled"]:
                        data = await asyncio.to_thread(
                            compress_image, img,
                            config["output_format"],
                            config["quality"],
                            config["max_file_size_kb"],
                            config["max_width"],
                            meta.get("file_size", 0),
                            prefer_target_jpeg_size,
                        )
                    else:
                        # 所有格式统一走 compress_image（JPEG 高质量 / PNG palette 量化 / WebP 有损）
                        fmt = config.get("output_format", "JPEG").upper()
                        data = await asyncio.to_thread(
                            compress_image, img, fmt,
                            max(config.get("quality", 85), 95), 0, 0,
                        )

                    # 保存
                    ext_map = {"JPEG": ".jpg", "JPG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
                    ext = ext_map.get(config["output_format"].upper(), ".jpg")
                    out_path = get_output_path(image_id, ext, run_id=batch_id, session_id=session_id)
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(out_path, "wb") as f:
                        f.write(data)

                    # 生成结果缩略图（峰值内存优先：输出落盘后短时打开，避免再复制整张处理图）
                    del img
                    gc.collect()
                    _compact_heap()

                    with Image.open(out_path) as out_img:
                        thumb_data = generate_thumbnail(out_img, copy_image=False)
                    session_temp = TEMP_DIR / session_id
                    session_temp.mkdir(parents=True, exist_ok=True)
                    thumb_path = get_result_thumb_path(image_id, run_id=batch_id, session_id=session_id)
                    with open(thumb_path, "wb") as f:
                        f.write(thumb_data)
                    materialized_output_size = len(data)
                    output_size = len(data)

                result.status = "done"
                result.run_id = batch_id
                result.output_size = output_size
                result.output_url = f"/api/download/{batch_id}/{image_id}"
                result.thumbnail_url = f"/api/result-thumbnail/{batch_id}/{image_id}"
                result.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                result.error_msg = json.dumps({
                    "alpha_only_fast_path": alpha_only_fast_path,
                    "protocol_version": protocol_version,
                    "materialized": materialized,
                    "result_mode": result_mode,
                }, ensure_ascii=False)

                # 先更新进度，再持久化结果元数据；避免磁盘写入失败把已完成结果整批打回 error
                await task_manager.update_result(batch_id, result)

                # 保存结果元数据（持久化，供页面刷新后重新加载结果卡片）
                features_str = _compute_features_str(
                    bg_method=config["bg_method"],
                    logo_enabled=config["logo_enabled"],
                    wm_mode=config["wm_mode"],
                    wm_text=config.get("wm_text", ""),
                    wm_blind_enabled=config.get("wm_blind_enabled", False),
                    compress_enabled=config["compress_enabled"],
                )
                meta_payload = _build_result_meta(
                    image_id,
                    meta["filename"],
                    batch_id,
                    features_str,
                    output_size,
                    result.finished_at,
                    protocol_version=protocol_version,
                    source_image_id=image_id,
                    result_kind="alpha-cutout" if protocol_version == "alpha-only-v1" else "materialized",
                    preview_url=f"/api/preview/{batch_id}/{image_id}",
                    download_url=f"/api/download/{batch_id}/{image_id}",
                    alpha_url=f"/api/alpha/{batch_id}/{image_id}" if protocol_version == "alpha-only-v1" else "",
                    materialized=materialized,
                    cutout_editable=has_bg,
                    has_alpha_source=has_bg,
                )
                meta_payload["result_mode"] = result_mode
                if protocol_version == "alpha-only-v1":
                    meta_payload.update({
                        "render_output_format": config["output_format"].upper(),
                        "render_quality": config["quality"],
                        "render_max_file_size_kb": config["max_file_size_kb"],
                        "render_max_width": config["max_width"],
                        "source_file_size": meta.get("file_size", 0),
                        "alpha_storage": "probe",
                        "source_width": source_size[0] if source_size else 0,
                        "source_height": source_size[1] if source_size else 0,
                        "probe_width": probe_size[0] if probe_size else 0,
                        "probe_height": probe_size[1] if probe_size else 0,
                        "prefer_target_jpeg_size": (
                            config["compress_enabled"]
                            and Path(meta["filename"]).suffix.lower() in (".jpg", ".jpeg")
                            and config["output_format"].upper() in ("JPEG", "JPG")
                            and int(config.get("max_file_size_kb", 0) or 0) <= 0
                        ),
                    })
                _save_result_meta(session_id, image_id, batch_id, meta_payload)
                direct_meta_path = TEMP_DIR / session_id / f"{image_id}_{batch_id}_meta.json"
                try:
                    with open(direct_meta_path, "w", encoding="utf-8") as mf:
                        json.dump(meta_payload, mf, ensure_ascii=False)
                except Exception:
                    pass
                debug_meta_path = get_result_meta_path(image_id, run_id=batch_id, session_id=session_id)
                try:
                    with open(debug_meta_path, encoding="utf-8") as _dbg_f:
                        debug_meta_saved = json.load(_dbg_f)
                except Exception as _dbg_e:
                    debug_meta_saved = {"debug_error": str(_dbg_e)}
                print(f"DEBUG batch meta saved: {debug_meta_path} => {debug_meta_saved}", flush=True)

                if materialized_output_size:
                    del data
                gc.collect()
                _compact_heap()

            except Exception as e:
                print(f"DEBUG batch process error image_id={image_id} batch_id={batch_id}: {e}", flush=True)
                result.status = "error"
                result.error_msg = str(e)
                result.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                await task_manager.update_result(batch_id, result)
                return

    # 注册批处理，防止并发清理
    register_batch()

    # 预加载抠图模型（隔离模型加载和首次推理的内存尖峰，避免首图处理时飙高）
    if config.get("bg_method", "none") != "none":
        await asyncio.to_thread(
            _prewarm_bg_model,
            config["bg_method"], config["api_key"],
            config["bg_model"], config["bg_threads"], config["bg_disable_arena"],
        )
        gc.collect()
        _compact_heap()
        release_cached_session()

    # 按需串行/并发处理
    try:
        if has_bg_batch:
            for iid in image_ids:
                await process_one(iid)
        else:
            tasks = [asyncio.create_task(process_one(iid)) for iid in image_ids]
            await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        # 所有图片处理完毕，注销 batch；若无其他活动批次则释放模型内存
        unregister_batch()
        gc.collect()
        _compact_heap()


# ─── WebSocket 进度 ───

@app.websocket("/api/ws/progress/{batch_id}")
async def websocket_progress(websocket: WebSocket, batch_id: str):
    await websocket.accept()
    # 验证 session 是否匹配（batch_id 嵌入 session_id[:8] 前缀）
    task = task_manager.get_task(batch_id)

    if not task:
        await websocket.send_json({"error": "批次不存在"})
        await websocket.close()
        return

    # 先注册，避免竞态条件丢失消息
    await task_manager.register_ws(batch_id, websocket)

    # 再发送当前状态
    await websocket.send_json({
        "batch_id": batch_id,
        "total": task.total,
        "done": task.done,
        "failed": task.failed,
        "status": task.status.value,
        "results": [r.model_dump() for r in task.results],
    })

    try:
        while True:
            data = await websocket.receive_text()
            if data == "cancel":
                task_manager.cancel_task(batch_id)
                await task_manager.cancel_pending(batch_id)
    except WebSocketDisconnect:
        await task_manager.remove_ws(batch_id, websocket)


# ─── 轮询进度 (降级) ───

@app.get("/api/progress/{batch_id}")
async def get_progress(batch_id: str):
    task = task_manager.get_task(batch_id)
    if not task:
        raise HTTPException(status_code=404, detail="批次不存在")
    return {
        "batch_id": task.batch_id,
        "total": task.total,
        "done": task.done,
        "failed": task.failed,
        "status": task.status.value,
        "results": [r.model_dump() for r in task.results],
    }


# ─── 下载 ───

@app.get("/api/download/{image_id}")
async def download_single(request: Request, image_id: str):
    session_id = request.state.session_id
    for ext in [".jpg", ".png", ".webp"]:
        path = get_output_path(image_id, ext, session_id=session_id)
        if path.exists():
            return FileResponse(path, filename=path.name)
    # 回退到原始文件
    meta = image_store.get(session_id, {}).get(image_id)
    if meta and os.path.exists(meta["path"]):
        return FileResponse(meta["path"], filename=meta["filename"])
    raise HTTPException(status_code=404, detail="文件不存在")


@app.get("/api/download/{run_id}/{image_id}")
async def download_single_run(request: Request, run_id: str, image_id: str):
    session_id = request.state.session_id
    for ext in [".jpg", ".png", ".webp"]:
        path = get_output_path(image_id, ext, run_id=run_id, session_id=session_id)
        if path.exists():
            return FileResponse(path, filename=path.name)

    meta = _load_result_meta(session_id, image_id, run_id)
    if meta and meta.get("protocol_version") == "alpha-only-v1":
        try:
            data, ext, filename = await asyncio.to_thread(_materialize_result_bytes, session_id, meta)
            out_path = get_output_path(image_id, ext, run_id=run_id, session_id=session_id)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(data)
            output_len = len(data)
            meta["materialized"] = True
            meta["output_size"] = output_len
            meta["output_url"] = f"/api/download/{run_id}/{image_id}"
            meta["download_url"] = f"/api/download/{run_id}/{image_id}"
            _save_result_meta(session_id, image_id, run_id, meta)
            del data
            gc.collect()
            _compact_heap()
            return FileResponse(out_path, filename=filename)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="文件不存在")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"按需导出失败: {str(e)}")

    raise HTTPException(status_code=404, detail="文件不存在")


@app.get("/api/result-thumbnail/{image_id}")
async def get_result_thumbnail(request: Request, image_id: str):
    session_id = request.state.session_id
    thumb_path = TEMP_DIR / session_id / f"{image_id}_result_thumb.png"
    if thumb_path.exists():
        return FileResponse(thumb_path, media_type="image/png")
    raise HTTPException(status_code=404, detail="结果缩略图不存在")


@app.get("/api/result-thumbnail/{run_id}/{image_id}")
async def get_result_thumbnail_run(request: Request, run_id: str, image_id: str):
    session_id = request.state.session_id
    thumb_path = get_result_thumb_path(image_id, run_id=run_id, session_id=session_id)
    if thumb_path.exists():
        return FileResponse(thumb_path, media_type="image/png")

    meta = _load_result_meta(session_id, image_id, run_id)
    if meta and meta.get("protocol_version") == "alpha-only-v1":
        source_path = _find_original_path(session_id, meta.get("source_image_id", image_id))
        alpha_path = _get_alpha_path_from_meta(session_id, meta, image_id)
        if alpha_path is None:
            alpha_path = _get_probe_alpha_path_from_meta(session_id, meta, image_id)
        if source_path and alpha_path:
            try:
                thumb_data = await asyncio.to_thread(
                    _build_alpha_thumbnail_from_source_and_alpha,
                    source_path,
                    alpha_path,
                    200,
                )
                thumb_path.parent.mkdir(parents=True, exist_ok=True)
                with open(thumb_path, "wb") as f:
                    f.write(thumb_data)
                return FileResponse(thumb_path, media_type="image/png")
            except Exception:
                pass
    raise HTTPException(status_code=404, detail="结果缩略图不存在")


@app.post("/api/download-all")
async def download_all(request: Request, data: dict):
    """打包当前 session 界面可见的处理结果"""
    session_id = request.state.session_id
    items = data.get("items", [])
    if not items:
        raise HTTPException(status_code=400, detail="没有可下载的处理结果")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in items:
            run_id = item.get("run_id", "")
            image_id = item.get("image_id", "")
            added = False
            for ext in [".jpg", ".png", ".webp"]:
                path = get_output_path(image_id, ext, run_id=run_id, session_id=session_id)
                if path.exists():
                    zf.write(path, path.name)
                    added = True
                    break

            if added:
                continue

            meta = _load_result_meta(session_id, image_id, run_id)
            if meta and meta.get("protocol_version") == "alpha-only-v1":
                try:
                    data_bytes, ext, filename = await asyncio.to_thread(_materialize_result_bytes, session_id, meta)
                    out_path = get_output_path(image_id, ext, run_id=run_id, session_id=session_id)
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(out_path, "wb") as f:
                        f.write(data_bytes)
                    output_len = len(data_bytes)
                    meta["materialized"] = True
                    meta["output_size"] = output_len
                    meta["output_url"] = f"/api/download/{run_id}/{image_id}"
                    meta["download_url"] = f"/api/download/{run_id}/{image_id}"
                    _save_result_meta(session_id, image_id, run_id, meta)
                    zf.writestr(filename, data_bytes)
                    del data_bytes
                    gc.collect()
                    _compact_heap()
                except FileNotFoundError:
                    continue
                except Exception:
                    continue
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": "attachment; filename=processed_images.zip",
            "Content-Length": str(buf.getbuffer().nbytes),
        },
    )


# ─── 盲水印提取 ───

@app.post("/api/extract-watermark")
async def extract_watermark(file: UploadFile = File(...)):
    """
    从上传的图片中提取 DCT 鲁棒盲水印

    先用 DCT 中频水印提取，失败后降级到感知哈希匹配作为兜底。
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="无效文件")
    try:
        content = await file.read()
        img = Image.open(io.BytesIO(content))

        text = extract_blind_watermark(img)

        # 同时计算感知哈希供前端对比
        phash = compute_phash(img)
        phash_hex = f"{phash:016x}"

        is_dct = not text.startswith("[PHASH:")
        return {
            "ok": True,
            "extracted_text": text,
            "method": "dct" if is_dct else "phash",
            "phash": phash_hex,
            "filename": file.filename,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"水印提取失败: {str(e)}")


@app.get("/api/extract-watermark/{run_id}/{image_id}")
async def extract_watermark_from_result(request: Request, run_id: str, image_id: str):
    """
    从已处理结果文件中直接提取盲水印（服务器端读取，避免客户端下载再上传）

    适用于结果卡片上的"提取水印"按钮，速度远快于 POST 上传方式。
    """
    session_id = request.state.session_id
    img = None
    for ext in [".jpg", ".png", ".webp"]:
        path = get_output_path(image_id, ext, run_id=run_id, session_id=session_id)
        if path.exists():
            img = Image.open(path)
            break
    if img is None:
        raise HTTPException(status_code=404, detail="结果文件不存在，可能已被清理")

    try:
        text = extract_blind_watermark(img)
        phash = compute_phash(img)
        phash_hex = f"{phash:016x}"

        is_dct = not text.startswith("[PHASH:")
        return {
            "ok": True,
            "extracted_text": text,
            "method": "dct" if is_dct else "phash",
            "phash": phash_hex,
            "filename": path.name,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"水印提取失败: {str(e)}")


# ─── 继续处理 ───

@app.post("/api/reprocess")
async def reprocess_image(
    request: Request,
    source_run_id: str = Form(...),
    source_image_id: str = Form(...),
    # 去除背景
    bg_enabled: bool = Form(False),
    bg_method: str = Form("local"),
    bg_model: str = Form("rmbg-1.4"),
    api_key: str = Form(""),
    bg_threads: int = Form(0),
    bg_disable_arena: bool = Form(False),
    # Logo
    logo_enabled: bool = Form(False),
    logo_position: str = Form("right-bottom"),
    logo_ratio: float = Form(0.15),
    logo_opacity: float = Form(0.8),
    logo_margin: int = Form(20),
    logo_tile: bool = Form(False),
    logo_file_id: Optional[str] = Form(None),
    # 显式水印
    wm_mode: str = Form("off"),
    wm_text: Optional[str] = Form(None),
    wm_text_color: str = Form("#FFFFFF"),
    wm_text_ratio: float = Form(0.05),
    wm_opacity: float = Form(0.5),
    wm_position: str = Form("right-bottom"),
    wm_tile_direction: str = Form("horizontal"),
    wm_dense_density: int = Form(5),
    # 盲水印
    wm_blind_enabled: bool = Form(False),
    wm_blind_text: Optional[str] = Form(None),
    wm_blind_strength: int = Form(16),
    wm_blind_use_mask: bool = Form(True),
    # 压缩
    compress_enabled: bool = Form(True),
    output_format: str = Form("JPEG"),
    quality: int = Form(85),
    max_file_size_kb: int = Form(0),
    max_width: int = Form(0),
    # 蒙版裁切（用户手绘蒙版；全白/缺失 = no-op）
    mask: Optional[UploadFile] = File(None),
):
    """对已处理结果继续处理（抠图/Logo/水印/盲水印/压缩）"""
    session_id = request.state.session_id
    # 加载已处理的结果文件
    img = None
    for ext in [".jpg", ".png", ".webp"]:
        path = get_output_path(source_image_id, ext, run_id=source_run_id, session_id=session_id)
        if path.exists():
            img = Image.open(path)
            break
    if img is None:
        raise HTTPException(status_code=404, detail="源图片不存在")

    img = img.convert("RGBA")

    # 预读蒙版字节
    mask_bytes: Optional[bytes] = await mask.read() if mask is not None else None

    # 1. 抠图
    if bg_enabled:
        os.environ["ORT_DISABLE_CPU_MEM_ARENA"] = "1" if bg_disable_arena else "0"
        img = remove_background(img, bg_method, api_key, bg_model, bg_threads, bg_disable_arena)
        cutout_path = TEMP_DIR / session_id / f"{source_image_id}_cutout.png"
        cutout_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(img.save, str(cutout_path), "PNG")

    # 2. Logo
    if logo_enabled:
        logo_img = None
        session_logos = logo_store.get(session_id, {})
        if logo_file_id and logo_file_id in session_logos:
            logo_img = Image.open(session_logos[logo_file_id]["path"]).convert("RGBA")
        else:
            logo_path = ASSETS_DIR / "logo.png"
            if logo_path.exists():
                logo_img = Image.open(logo_path).convert("RGBA")
        if logo_img:
            from backend.processors.logo_adder import add_logo
            img = add_logo(img, logo_img, logo_position, logo_ratio, logo_opacity, margin=logo_margin, tile=logo_tile)

    # 3. 显式水印
    if wm_mode in ("position", "tile", "dense") and wm_text:
        img = add_text_watermark(
            img, wm_text, wm_position, wm_text_ratio, wm_opacity,
            wm_text_color, wm_mode in ("tile", "dense"),
            wm_tile_direction, wm_mode == "dense", wm_dense_density,
        )

    # 4. 蒙版裁切（用户手绘蒙版；全白/缺失 = no-op）
    if mask_bytes:
        img = apply_mask_crop(img, mask_bytes)
        # 保存蒙版供「再次编辑」预填
        last_mask_path = TEMP_DIR / session_id / f"{source_image_id}_last_mask.png"
        last_mask_path.parent.mkdir(parents=True, exist_ok=True)
        with open(last_mask_path, "wb") as f:
            f.write(mask_bytes)

    # 6. 压缩
    if compress_enabled:
        data = compress_image(
            img, output_format, quality, max_file_size_kb, max_width,
        )
    else:
        # 所有格式统一走 compress_image（JPEG 高质量 / PNG palette 量化 / WebP 有损）
        fmt = output_format.upper() if output_format else "JPEG"
        data = compress_image(img, fmt, max(quality, 95), 0, 0)

    # 保存新结果
    new_run_id = f"reprocess-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    ext_map = {"JPEG": ".jpg", "JPG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
    ext = ext_map.get(output_format.upper(), ".jpg")
    out_path = get_output_path(source_image_id, ext, run_id=new_run_id, session_id=session_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)

    # 结果缩略图
    out_img = Image.open(out_path)
    thumb_data = generate_thumbnail(out_img)
    session_temp = TEMP_DIR / session_id
    session_temp.mkdir(parents=True, exist_ok=True)
    thumb_path = session_temp / f"{source_image_id}_{new_run_id}_result_thumb.png"
    with open(thumb_path, "wb") as f:
        f.write(thumb_data)

    # 保存结果元数据（持久化）
    _finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    meta_path = session_temp / f"{source_image_id}_{new_run_id}_meta.json"
    try:
        reprocess_features_str = _compute_features_str(
            bg_method=bg_method if bg_enabled else "none",
            logo_enabled=logo_enabled,
            wm_mode=wm_mode,
            wm_text=wm_text,
            wm_blind_enabled=wm_blind_enabled,
            compress_enabled=compress_enabled,
        )
        with open(meta_path, "w") as mf:
            json.dump({
                "id": source_image_id,
                "filename": Path(out_path).name,
                "run_id": new_run_id,
                "features": reprocess_features_str,
                "output_size": len(data),
                "output_url": f"/api/download/{new_run_id}/{source_image_id}",
                "thumbnail_url": f"/api/result-thumbnail/{new_run_id}/{source_image_id}",
                "finished_at": _finished_at,
            }, mf)
    except Exception:
        pass

    return {
        "ok": True,
        "run_id": new_run_id,
        "image_id": source_image_id,
        "output_url": f"/api/download/{new_run_id}/{source_image_id}",
        "thumbnail_url": f"/api/result-thumbnail/{new_run_id}/{source_image_id}",
        "output_size": len(data),
        "filename": Path(out_path).name,
    }


# ─── 手动编辑蒙版 ───

@app.post("/api/edit-mask/{image_id}")
async def edit_mask(
    request: Request,
    image_id: str,
    mask: UploadFile = File(...),
    logo_enabled: bool = Form(False),
    logo_position: str = Form("right-bottom"),
    logo_ratio: float = Form(0.15),
    logo_opacity: float = Form(0.8),
    logo_margin: int = Form(20),
    logo_tile: bool = Form(False),
    logo_file_id: Optional[str] = Form(None),
    wm_mode: str = Form("off"),
    wm_text: Optional[str] = Form(None),
    wm_text_color: str = Form("#FFFFFF"),
    wm_text_ratio: float = Form(0.05),
    wm_opacity: float = Form(0.5),
    wm_position: str = Form("right-bottom"),
    wm_tile_direction: str = Form("horizontal"),
    wm_dense_density: int = Form(5),
    wm_blind_enabled: bool = Form(False),
    wm_blind_text: Optional[str] = Form(None),
    wm_blind_strength: int = Form(16),
    wm_blind_use_mask: bool = Form(True),
    compress_enabled: bool = Form(True),
    output_format: str = Form("JPEG"),
    quality: int = Form(85),
    max_file_size_kb: int = Form(0),
    max_width: int = Form(0),
):
    """接收前端 Canvas 编辑后的蒙版，按蒙版白色像素的最小包围矩形裁切后重新合成。"""
    session_id = request.state.session_id
    meta = image_store.get(session_id, {}).get(image_id)
    if not meta:
        raise HTTPException(status_code=404, detail="图片不存在")

    try:
        # 加载原图（自动修正 EXIF 方向）
        original = await asyncio.to_thread(Image.open, meta["path"])
        original = await asyncio.to_thread(ImageOps.exif_transpose, original)
        original = original.convert("RGBA")

        # 加载蒙版 (黑色=擦除，白色=保留)
        mask_bytes = await mask.read()

        # 蒙版裁切（全白/缺失 = no-op；否则按白色像素 bbox 裁切）
        result_img = original.copy()
        if mask_bytes:
            result_img = await asyncio.to_thread(apply_mask_crop, result_img, mask_bytes)
            # 保存蒙版供「再次编辑」预填
            last_mask_path = TEMP_DIR / session_id / f"{image_id}_last_mask.png"
            last_mask_path.parent.mkdir(parents=True, exist_ok=True)
            with open(last_mask_path, "wb") as f:
                f.write(mask_bytes)

        # 更新 cutout.png（不含 Logo/压缩），供后续再次编辑使用
        cutout_path = TEMP_DIR / session_id / f"{image_id}_cutout.png"
        cutout_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(result_img.save, str(cutout_path), "PNG")

        # Logo (图片型)
        if logo_enabled:
            logo_img = None
            session_logos = logo_store.get(session_id, {})
            if logo_file_id and logo_file_id in session_logos:
                logo_img = Image.open(session_logos[logo_file_id]["path"]).convert("RGBA")
            else:
                logo_path = ASSETS_DIR / "logo.png"
                if logo_path.exists():
                    logo_img = Image.open(logo_path).convert("RGBA")
            if logo_img:
                result_img = add_logo(
                    result_img, logo_img, logo_position,
                    logo_ratio, logo_opacity, margin=logo_margin, tile=logo_tile,
                )

        # 显式水印
        if wm_mode in ("position", "tile", "dense") and wm_text:
            result_img = add_text_watermark(
                result_img, wm_text, wm_position, wm_text_ratio, wm_opacity,
                wm_text_color, wm_mode in ("tile", "dense"),
                wm_tile_direction, wm_mode == "dense", wm_dense_density,
            )

        # 压缩
        if compress_enabled:
            data = compress_image(
                result_img, output_format, quality, max_file_size_kb, max_width,
            )
        else:
            # 所有格式统一走 compress_image（JPEG 高质量 / PNG palette 量化 / WebP 有损）
            fmt = output_format.upper() if output_format else "JPEG"
            data = compress_image(result_img, fmt, max(quality, 95), 0, 0)

        edit_run_id = f"edit-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        ext_map = {"JPEG": ".jpg", "JPG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
        ext = ext_map.get(output_format.upper(), ".jpg")
        out_path = get_output_path(image_id, ext, run_id=edit_run_id, session_id=session_id)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(data)

        # 更新缩略图
        out_img = Image.open(out_path)
        thumb_data = generate_thumbnail(out_img)
        session_temp = TEMP_DIR / session_id
        session_temp.mkdir(parents=True, exist_ok=True)
        thumb_path = session_temp / f"{image_id}_{edit_run_id}_result_thumb.png"
        with open(thumb_path, "wb") as f:
            f.write(thumb_data)

        # 保存结果元数据（持久化）
        _finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        meta_path = session_temp / f"{image_id}_{edit_run_id}_meta.json"
        try:
            edit_features_str = _compute_features_str(
                logo_enabled=logo_enabled,
                wm_mode=wm_mode,
                wm_text=wm_text,
                wm_blind_enabled=wm_blind_enabled,
                compress_enabled=compress_enabled,
            )
            with open(meta_path, "w") as mf:
                json.dump({
                    "id": image_id,
                    "filename": meta.get("filename", Path(out_path).name),
                    "run_id": edit_run_id,
                    "features": edit_features_str,
                    "output_size": len(data),
                    "output_url": f"/api/download/{edit_run_id}/{image_id}",
                    "thumbnail_url": f"/api/result-thumbnail/{edit_run_id}/{image_id}",
                    "finished_at": _finished_at,
                }, mf)
        except Exception:
            pass

        return {
            "ok": True,
            "run_id": edit_run_id,
            "image_id": image_id,
            "output_size": len(data),
            "output_url": f"/api/download/{edit_run_id}/{image_id}",
            "thumbnail_url": f"/api/result-thumbnail/{edit_run_id}/{image_id}",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── 修改抠图（笔刷编辑器）───

@app.post("/api/edit-cutout/{image_id}")
async def edit_cutout(
    request: Request,
    image_id: str,
    mask: UploadFile = File(...),
    logo_enabled: bool = Form(False),
    logo_position: str = Form("right-bottom"),
    logo_ratio: float = Form(0.15),
    logo_opacity: float = Form(0.8),
    logo_margin: int = Form(20),
    logo_tile: bool = Form(False),
    logo_file_id: Optional[str] = Form(None),
    wm_mode: str = Form("off"),
    wm_text: Optional[str] = Form(None),
    wm_text_color: str = Form("#FFFFFF"),
    wm_text_ratio: float = Form(0.05),
    wm_opacity: float = Form(0.5),
    wm_position: str = Form("right-bottom"),
    wm_tile_direction: str = Form("horizontal"),
    wm_dense_density: int = Form(5),
    wm_blind_enabled: bool = Form(False),
    wm_blind_text: Optional[str] = Form(None),
    wm_blind_strength: int = Form(16),
    wm_blind_use_mask: bool = Form(True),
    compress_enabled: bool = Form(True),
    output_format: str = Form("JPEG"),
    quality: int = Form(85),
    max_file_size_kb: int = Form(0),
    max_width: int = Form(0),
):
    """接收 Canvas 笔刷编辑后的抠图蒙版，修改 alpha 后重新合成。"""
    session_id = request.state.session_id
    session_temp = TEMP_DIR / session_id
    source_path = _find_original_path(session_id, image_id)
    if not source_path:
        raise HTTPException(status_code=404, detail="原图不存在")

    alpha_meta = _find_latest_alpha_meta(session_id, image_id)
    alpha_path = _get_alpha_path_from_meta(session_id, alpha_meta, image_id)
    if alpha_path is None and alpha_meta and alpha_meta.get("alpha_storage") == "probe":
        try:
            alpha_path = await asyncio.to_thread(_materialize_alpha_asset, session_id, alpha_meta, image_id)
        except FileNotFoundError:
            alpha_path = None
    cutout_path = get_cutout_path(image_id, session_id=session_id)
    if alpha_path is None:
        if cutout_path.exists():
            with Image.open(cutout_path) as legacy_cutout:
                legacy_cutout.load()
                alpha = legacy_cutout.getchannel("A")
                alpha_path = get_alpha_path(image_id, session_id=session_id)
                alpha.save(alpha_path, "PNG")
        else:
            raise HTTPException(status_code=404, detail="抠图结果不存在，请先进行抠图处理")

    try:
        import numpy as np

        # 加载 alpha 蒙版和编辑 mask
        current_alpha = Image.open(alpha_path).convert("L")
        mask_bytes = await mask.read()
        mask_img = Image.open(io.BytesIO(mask_bytes)).convert("L")
        mask_img = mask_img.resize(current_alpha.size, Image.NEAREST)

        alpha_arr = np.array(current_alpha, dtype=np.uint8)
        mask_arr = np.array(mask_img, dtype=np.uint8)

        # mask = 0 → alpha = 0 (擦除), mask = 255 → alpha = 255 (恢复), mask = 127 → 不变
        alpha_arr = np.where(mask_arr == 0, 0, np.where(mask_arr == 255, 255, alpha_arr))
        updated_alpha = Image.fromarray(alpha_arr, mode="L")

        # 保存更新后的 alpha（alias + 当前运行版本）
        updated_alpha.save(get_alpha_path(image_id, session_id=session_id), "PNG")

        # 保存蒙版供再次编辑
        last_mask_path = session_temp / f"{image_id}_last_cutout_mask.png"
        with open(last_mask_path, "wb") as f:
            f.write(mask_bytes)

        # 合成当前可视 cutout，供后续处理复用
        composed = _compose_rgba_from_source_and_alpha(source_path, get_alpha_path(image_id, session_id=session_id))
        try:
            composed.save(cutout_path, "PNG")  # 兼容缓存

            img = composed.copy()

            # Logo
            if logo_enabled:
                logo_img = None
                session_logos = logo_store.get(session_id, {})
                if logo_file_id and logo_file_id in session_logos:
                    logo_img = Image.open(session_logos[logo_file_id]["path"]).convert("RGBA")
                else:
                    logo_path = ASSETS_DIR / "logo.png"
                    if logo_path.exists():
                        logo_img = Image.open(logo_path).convert("RGBA")
                if logo_img:
                    from backend.processors.logo_adder import add_logo
                    img = add_logo(img, logo_img, logo_position, logo_ratio, logo_opacity, margin=logo_margin, tile=logo_tile)

            # 显式水印
            if wm_mode in ("position", "tile", "dense") and wm_text:
                img = add_text_watermark(
                    img, wm_text, wm_position, wm_text_ratio, wm_opacity,
                    wm_text_color, wm_mode in ("tile", "dense"),
                    wm_tile_direction, wm_mode == "dense", wm_dense_density,
                )

            # 压缩
            if compress_enabled:
                data = compress_image(img, output_format, quality, max_file_size_kb, max_width)
            else:
                fmt = output_format.upper() if output_format else "JPEG"
                data = compress_image(img, fmt, max(quality, 95), 0, 0)

            # 保存结果文件
            new_run_id = f"cutout-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            alpha_run_path = get_alpha_path(image_id, run_id=new_run_id, session_id=session_id)
            updated_alpha.save(alpha_run_path, "PNG")
            ext_map = {"JPEG": ".jpg", "JPG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
            ext = ext_map.get(output_format.upper(), ".jpg")
            out_path = get_output_path(image_id, ext, run_id=new_run_id, session_id=session_id)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(data)

            # 结果缩略图
            out_img = Image.open(out_path)
            thumb_data = generate_thumbnail(out_img)
            session_temp.mkdir(parents=True, exist_ok=True)
            thumb_path = get_result_thumb_path(image_id, run_id=new_run_id, session_id=session_id)
            with open(thumb_path, "wb") as f:
                f.write(thumb_data)

            # 结果元数据（持久化）
            _finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                cutout_features_str = _compute_features_str(
                    bg_method="local",
                    logo_enabled=logo_enabled,
                    wm_mode=wm_mode,
                    wm_text=wm_text,
                    wm_blind_enabled=wm_blind_enabled,
                    compress_enabled=compress_enabled,
                )
                meta_payload = _build_result_meta(
                    image_id,
                    f"{image_id}_cutout.png",
                    new_run_id,
                    cutout_features_str,
                    len(data),
                    _finished_at,
                    protocol_version="alpha-only-v1",
                    source_image_id=image_id,
                    result_kind="alpha-cutout",
                    preview_url=f"/api/preview/{new_run_id}/{image_id}",
                    download_url=f"/api/download/{new_run_id}/{image_id}",
                    alpha_url=f"/api/alpha/{new_run_id}/{image_id}",
                    materialized=True,
                    cutout_editable=True,
                    has_alpha_source=True,
                )
                meta_payload.update({
                    "render_output_format": output_format.upper(),
                    "render_quality": quality,
                    "render_max_file_size_kb": max_file_size_kb,
                    "render_max_width": max_width,
                })
                _save_result_meta(session_id, image_id, new_run_id, meta_payload)
            except Exception:
                pass

            return {
                "ok": True,
                "run_id": new_run_id,
                "image_id": image_id,
                "output_size": len(data),
                "output_url": f"/api/download/{new_run_id}/{image_id}",
                "preview_url": f"/api/preview/{new_run_id}/{image_id}",
                "thumbnail_url": f"/api/result-thumbnail/{new_run_id}/{image_id}",
                "finished_at": _finished_at,
                "filename": f"{image_id}_cutout.png",
                "protocol_version": "alpha-only-v1",
                "cutout_editable": True,
                "has_alpha_source": True,
            }
        finally:
            try:
                composed.close()
            except Exception:
                pass
            try:
                img.close()
            except Exception:
                pass
            try:
                current_alpha.close()
            except Exception:
                pass
            try:
                updated_alpha.close()
            except Exception:
                pass

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── 清理 ───

@app.post("/api/cleanup")
async def cleanup(request: Request):
    session_id = request.state.session_id
    # 清理当前 session 的过期的文件
    for base_dir in [INPUT_DIR, OUTPUT_DIR, TEMP_DIR]:
        session_dir = base_dir / session_id
        if session_dir.exists():
            for f in session_dir.iterdir():
                try:
                    if f.is_file():
                        os.remove(f)
                except OSError:
                    pass
    return {"ok": True}


# ─── 运行时设置 ───

@app.get("/api/config/settings")
async def get_settings():
    """获取运行时设置"""
    return {
        "threads": int(os.environ.get("REMBG_THREADS", 0)),
        "disable_arena": os.environ.get("ORT_DISABLE_CPU_MEM_ARENA", "1") == "1",
    }


@app.post("/api/config/settings")
async def update_settings(
    threads: int = Form(0),
    disable_arena: bool = Form(True),
):
    """更新运行时设置（仅影响新创建的 session，已有 session 不受影响）"""
    os.environ["REMBG_THREADS"] = str(threads)
    os.environ["ORT_DISABLE_CPU_MEM_ARENA"] = "1" if disable_arena else "0"
    return {"ok": True, "threads": threads, "disable_arena": disable_arena}


# ─── API Key 管理 ───

@app.get("/api/config/apikey")
async def get_apikey():
    """获取当前保存的 API Key"""
    from config import REMBG_API_KEY
    # 优先返回持久化的运行时配置，否则使用代码里的默认值
    saved = _load_runtime_config("api_key")
    return {"api_key": saved if saved else REMBG_API_KEY}


@app.post("/api/config/apikey")
async def update_apikey(api_key: str = Form(...)):
    """更新 API Key（保存到可写位置）"""
    _save_runtime_config("api_key", api_key)
    return {"ok": True, "api_key": api_key}


# ─── 默认 Logo 配置管理 ───

@app.get("/api/config/default-logo")
async def get_default_logo_config():
    """获取默认 Logo 配置（优先返回用户保存的运行时配置）"""
    from config import DEFAULT_LOGO_POSITION, DEFAULT_LOGO_RATIO, DEFAULT_LOGO_OPACITY, DEFAULT_LOGO_MARGIN
    saved = _load_runtime_config("default_logo")
    if saved:
        return saved
    return {
        "position": DEFAULT_LOGO_POSITION,
        "ratio": DEFAULT_LOGO_RATIO,
        "opacity": DEFAULT_LOGO_OPACITY,
        "margin": DEFAULT_LOGO_MARGIN,
    }


@app.post("/api/config/default-logo")
async def update_default_logo_config(
    position: str = Form("right-bottom"),
    ratio: float = Form(0.15),
    opacity: float = Form(0.8),
    margin: int = Form(20),
):
    """更新默认 Logo 配置（保存到可写位置）"""
    _save_runtime_config("default_logo", {
        "position": position,
        "ratio": ratio,
        "opacity": opacity,
        "margin": margin,
    })
    return {"ok": True, "position": position, "ratio": ratio, "opacity": opacity, "margin": margin}


@app.post("/api/config/default-logo-image")
async def upload_default_logo_image(file: UploadFile = File(...)):
    """上传新的默认 Logo 图片"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="无效文件")
    try:
        content = await file.read()
        logo_path = ASSETS_DIR / "logo.png"
        with open(logo_path, "wb") as f:
            f.write(content)
        return {"ok": True, "thumbnail_url": "/api/logo-default"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── 默认压缩输出配置管理 ───


@app.get("/api/config/default-compress")
async def get_default_compress_config():
    """获取默认压缩输出设置（优先返回用户保存的运行时配置）"""
    from config import DEFAULT_OUTPUT_FORMAT, DEFAULT_QUALITY, DEFAULT_MAX_WIDTH, DEFAULT_MAX_FILE_SIZE_KB
    saved = _load_runtime_config("default_compress")
    if saved:
        return saved
    return {
        "output_format": DEFAULT_OUTPUT_FORMAT,
        "quality": DEFAULT_QUALITY,
        "max_width": DEFAULT_MAX_WIDTH,
        "max_file_size_kb": DEFAULT_MAX_FILE_SIZE_KB,
    }


@app.post("/api/config/default-compress")
async def update_default_compress_config(
    output_format: str = Form("JPEG"),
    quality: int = Form(90),
    max_width: int = Form(0),
    max_file_size_kb: int = Form(0),
):
    """更新默认压缩输出设置（保存到可写位置）"""
    _save_runtime_config("default_compress", {
        "output_format": output_format,
        "quality": quality,
        "max_width": max_width,
        "max_file_size_kb": max_file_size_kb,
    })
    return {"ok": True, "output_format": output_format, "quality": quality, "max_width": max_width, "max_file_size_kb": max_file_size_kb}
