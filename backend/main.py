import asyncio
import io
import os
import shutil
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, Form, WebSocket, WebSocketDisconnect, Query, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageOps

from config import (
    INPUT_DIR, OUTPUT_DIR, TEMP_DIR, ASSETS_DIR, FRONTEND_DIR,
    CONCURRENT_PROCESS_LIMIT,
)
from backend.models import ProcessResult, TaskStatus
from backend.task_manager import task_manager
from backend.file_manager import save_uploaded_file, delete_result_files, get_output_path, periodic_cleanup
from backend.utils.image_utils import generate_thumbnail
from backend.processors.bg_remover import remove_background
from backend.processors.logo_adder import add_logo
from backend.processors.watermark import add_text_watermark, add_blind_watermark
from backend.processors.compressor import compress_image


def _save_png_lossless(image: Image.Image) -> bytes:
    """保存为 PNG 并做最大无损压缩（保持透明通道，不失真）"""
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True, compress_level=9)
    return buf.getvalue()


app = FastAPI(title="图片批量处理工具")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 内存存储
image_store: Dict[str, dict] = {}
logo_store: Dict[str, dict] = {}

# 静态文件
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")
app.mount("/frontend", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")


@app.on_event("startup")
async def startup():
    asyncio.create_task(periodic_cleanup())


# ─── 页面 ───

@app.get("/")
async def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


# ─── 上传 ───

@app.post("/api/upload")
async def upload_images(files: List[UploadFile] = File(...)):
    uploaded = []
    for file in files:
        if not file.filename:
            continue
        try:
            content = await file.read()
            meta = save_uploaded_file(content, file.filename)
            image_store[meta["id"]] = meta
            uploaded.append(meta)
        except ValueError as e:
            continue  # 跳过不合法文件

    return {"images": uploaded, "total": len(uploaded)}


@app.post("/api/upload-logo")
async def upload_logo(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="无效文件")
    try:
        content = await file.read()
        meta = save_uploaded_file(content, file.filename)
        logo_store[meta["id"]] = meta
        return {"logo_id": meta["id"], "thumbnail_url": meta["thumbnail_url"]}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── 图片管理 ───

@app.get("/api/images")
async def list_images():
    images = list(image_store.values())
    return {"images": images}


@app.delete("/api/images/{image_id}")
async def delete_image(image_id: str):
    if image_id not in image_store:
        raise HTTPException(status_code=404, detail="图片不存在")
    image_store.pop(image_id)
    # 仅移除内存记录，不删除源文件，避免已存在的结果卡片预览失效
    return {"ok": True}


@app.delete("/api/results/{image_id}")
async def delete_result(image_id: str, run_id: str = Query("")):
    """只删除处理结果，保留原始上传图片"""
    delete_result_files(image_id, run_id=run_id)
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
async def get_thumbnail(image_id: str):
    thumb_path = TEMP_DIR / f"{image_id}_thumb.png"
    if thumb_path.exists():
        return FileResponse(thumb_path, media_type="image/png")
    meta = image_store.get(image_id)
    if meta and os.path.exists(meta["path"]):
        return FileResponse(meta["path"])
    raise HTTPException(status_code=404, detail="缩略图不存在")


@app.get("/api/original/{image_id}")
async def get_original(image_id: str):
    meta = image_store.get(image_id)
    if meta and os.path.exists(meta["path"]):
        return FileResponse(meta["path"])
    # 如果内存记录已被删除，直接从磁盘查找文件
    for ext in ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif']:
        path = INPUT_DIR / f"{image_id}{ext}"
        if path.exists():
            return FileResponse(path)
    raise HTTPException(status_code=404, detail="原图不存在")


@app.get("/api/cutout/{image_id}")
async def get_cutout(image_id: str):
    """获取抠图结果 PNG（含透明通道），供编辑器使用"""
    cutout_path = TEMP_DIR / f"{image_id}_cutout.png"
    if cutout_path.exists():
        return FileResponse(cutout_path, media_type="image/png")
    # 没有抠图结果则回退到原图
    meta = image_store.get(image_id)
    if meta and os.path.exists(meta["path"]):
        return FileResponse(meta["path"])
    raise HTTPException(status_code=404, detail="抠图结果不存在")


# ─── 异步处理 ───

@app.post("/api/process")
async def process_images(
    bg_method: str = Form("none"),
    bg_model: str = Form("rmbg-1.4"),
    api_key: str = Form(""),
    bg_threads: int = Form(0),
    bg_disable_arena: bool = Form(True),
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
    compress_enabled: bool = Form(True),
    output_format: str = Form("JPEG"),
    quality: int = Form(85),
    max_file_size_kb: int = Form(0),
    max_width: int = Form(0),
):
    if not image_store:
        raise HTTPException(status_code=400, detail="请先上传图片")

    image_ids = list(image_store.keys())
    filenames = [image_store[iid]["filename"] for iid in image_ids]
    task = task_manager.create_task(image_ids, filenames)
    task.status = TaskStatus.RUNNING

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
        "compress_enabled": compress_enabled,
        "output_format": output_format,
        "quality": quality,
        "max_file_size_kb": max_file_size_kb,
        "max_width": max_width,
    }

    # 加载 Logo
    logo_img = None
    if logo_enabled:
        if logo_file_id and logo_file_id in logo_store:
            logo_img = Image.open(logo_store[logo_file_id]["path"]).convert("RGBA")
        else:
            logo_path = ASSETS_DIR / "logo.png"
            if logo_path.exists():
                logo_img = Image.open(logo_path).convert("RGBA")

    asyncio.create_task(_batch_process(task.batch_id, image_ids, config, logo_img))
    # 保持引用防止被垃圾回收
    asyncio.current_task().add_done_callback(lambda _: None)
    return {"batch_id": task.batch_id, "total": task.total}


async def _batch_process(batch_id: str, image_ids: List[str], config: dict, logo_img):
    semaphore = asyncio.Semaphore(CONCURRENT_PROCESS_LIMIT)

    async def process_one(image_id: str):
        async with semaphore:
            if task_manager.is_cancelled(batch_id):
                return
            meta = image_store.get(image_id)
            if not meta:
                return

            result = ProcessResult(id=image_id, filename=meta["filename"], status="processing")
            try:
                img = await asyncio.to_thread(Image.open, meta["path"])
                img = await asyncio.to_thread(ImageOps.exif_transpose, img)

                # 1. 抠图
                if config["bg_method"] != "none":
                    # 根据设置控制 ONNX 内存预分配
                    os.environ["ORT_DISABLE_CPU_MEM_ARENA"] = "1" if config["bg_disable_arena"] else "0"
                    img = await asyncio.to_thread(
                        remove_background, img, config["bg_method"], config["api_key"],
                        config["bg_model"], config["bg_threads"], config["bg_disable_arena"]
                    )
                    # 始终存一份 PNG 抠图结果（含透明通道），供编辑器使用
                    cutout_path = TEMP_DIR / f"{image_id}_cutout.png"
                    await asyncio.to_thread(img.save, str(cutout_path), "PNG")

                # 2. Logo (图片型)
                if config["logo_enabled"] and logo_img:
                    img = await asyncio.to_thread(
                        add_logo, img, logo_img,
                        config["logo_position"],
                        config["logo_ratio"],
                        config["logo_opacity"],
                        margin=config["logo_margin"],
                        tile=config["logo_tile"],
                    )

                # 3. 显式水印
                if config["wm_mode"] in ("position", "tile", "dense") and config["wm_text"]:
                    img = await asyncio.to_thread(
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

                # 4. 盲水印
                if config["wm_blind_enabled"] and config["wm_blind_text"]:
                    img = await asyncio.to_thread(
                        add_blind_watermark, img, config["wm_blind_text"]
                    )

                # 5. 压缩
                if config["compress_enabled"]:
                    data = await asyncio.to_thread(
                        compress_image, img,
                        config["output_format"],
                        config["quality"],
                        config["max_file_size_kb"],
                        config["max_width"],
                    )
                else:
                    fmt = config.get("output_format", "JPEG").upper()
                    if fmt in ("JPEG", "JPG"):
                        # JPEG: 用选中格式+高质量，避免 RGBA→PNG 体积爆炸
                        data = await asyncio.to_thread(
                            compress_image, img, fmt,
                            max(config.get("quality", 85), 95), 0, 0,
                        )
                    else:
                        # PNG/其他: 存为 PNG 并做最大无损压缩，保持透明度
                        data = await asyncio.to_thread(
                            lambda: _save_png_lossless(img)
                        )

                # 保存
                ext_map = {"JPEG": ".jpg", "JPG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
                ext = ext_map.get(config["output_format"].upper(), ".jpg")
                out_path = get_output_path(image_id, ext, run_id=batch_id)
                with open(out_path, "wb") as f:
                    f.write(data)

                # 生成结果缩略图
                out_img = Image.open(out_path)
                thumb_data = generate_thumbnail(out_img)
                thumb_path = TEMP_DIR / f"{image_id}_{batch_id}_result_thumb.png"
                with open(thumb_path, "wb") as f:
                    f.write(thumb_data)

                result.status = "done"
                result.run_id = batch_id
                result.output_size = len(data)
                result.output_url = f"/api/download/{batch_id}/{image_id}"
                result.thumbnail_url = f"/api/result-thumbnail/{batch_id}/{image_id}"
                result.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                del img, out_img

            except Exception as e:
                result.status = "error"
                result.error_msg = str(e)
                result.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            await task_manager.update_result(batch_id, result)

    # 并发处理
    tasks = [asyncio.create_task(process_one(iid)) for iid in image_ids]
    await asyncio.gather(*tasks, return_exceptions=True)


# ─── WebSocket 进度 ───

@app.websocket("/api/ws/progress/{batch_id}")
async def websocket_progress(websocket: WebSocket, batch_id: str):
    await websocket.accept()
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
async def download_single(image_id: str):
    for ext in [".jpg", ".png", ".webp"]:
        path = get_output_path(image_id, ext)
        if path.exists():
            return FileResponse(path, filename=path.name)
    # 回退到原始文件
    meta = image_store.get(image_id)
    if meta and os.path.exists(meta["path"]):
        return FileResponse(meta["path"], filename=meta["filename"])
    raise HTTPException(status_code=404, detail="文件不存在")


@app.get("/api/download/{run_id}/{image_id}")
async def download_single_run(run_id: str, image_id: str):
    for ext in [".jpg", ".png", ".webp"]:
        path = get_output_path(image_id, ext, run_id=run_id)
        if path.exists():
            return FileResponse(path, filename=path.name)
    raise HTTPException(status_code=404, detail="文件不存在")


@app.get("/api/result-thumbnail/{image_id}")
async def get_result_thumbnail(image_id: str):
    thumb_path = TEMP_DIR / f"{image_id}_result_thumb.png"
    if thumb_path.exists():
        return FileResponse(thumb_path, media_type="image/png")
    raise HTTPException(status_code=404, detail="结果缩略图不存在")


@app.get("/api/result-thumbnail/{run_id}/{image_id}")
async def get_result_thumbnail_run(run_id: str, image_id: str):
    thumb_path = TEMP_DIR / f"{image_id}_{run_id}_result_thumb.png"
    if thumb_path.exists():
        return FileResponse(thumb_path, media_type="image/png")
    raise HTTPException(status_code=404, detail="结果缩略图不存在")


@app.post("/api/download-all")
async def download_all(data: dict):
    """打包当前界面可见的处理结果"""
    items = data.get("items", [])
    if not items:
        raise HTTPException(status_code=400, detail="没有可下载的处理结果")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in items:
            run_id = item.get("run_id", "")
            image_id = item.get("image_id", "")
            for ext in [".jpg", ".png", ".webp"]:
                path = get_output_path(image_id, ext, run_id=run_id)
                if path.exists():
                    zf.write(path, path.name)
                    break
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=processed_images.zip"},
    )


# ─── 继续处理 ───

@app.post("/api/reprocess")
async def reprocess_image(
    source_run_id: str = Form(...),
    source_image_id: str = Form(...),
    # 去除背景
    bg_enabled: bool = Form(False),
    bg_method: str = Form("local"),
    bg_model: str = Form("rmbg-1.4"),
    api_key: str = Form(""),
    bg_threads: int = Form(0),
    bg_disable_arena: bool = Form(True),
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
    # 压缩
    compress_enabled: bool = Form(True),
    output_format: str = Form("JPEG"),
    quality: int = Form(85),
    max_file_size_kb: int = Form(0),
    max_width: int = Form(0),
):
    """对已处理结果继续处理（抠图/Logo/水印/盲水印/压缩）"""
    # 加载已处理的结果文件
    img = None
    for ext in [".jpg", ".png", ".webp"]:
        path = get_output_path(source_image_id, ext, run_id=source_run_id)
        if path.exists():
            img = Image.open(path)
            break
    if img is None:
        raise HTTPException(status_code=404, detail="源图片不存在")

    img = img.convert("RGBA")

    # 1. 抠图
    if bg_enabled:
        os.environ["ORT_DISABLE_CPU_MEM_ARENA"] = "1" if bg_disable_arena else "0"
        img = remove_background(img, bg_method, api_key, bg_model, bg_threads, bg_disable_arena)
        cutout_path = TEMP_DIR / f"{source_image_id}_cutout.png"
        await asyncio.to_thread(img.save, str(cutout_path), "PNG")

    # 2. Logo
    if logo_enabled:
        logo_img = None
        if logo_file_id and logo_file_id in logo_store:
            logo_img = Image.open(logo_store[logo_file_id]["path"]).convert("RGBA")
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

    # 4. 盲水印
    if wm_blind_enabled and wm_blind_text:
        img = add_blind_watermark(img, wm_blind_text)

    # 5. 压缩
    if compress_enabled:
        data = compress_image(img, output_format, quality, max_file_size_kb, max_width)
    else:
        fmt = output_format.upper() if output_format else "JPEG"
        if fmt in ("JPEG", "JPG"):
            # JPEG: 高质量保存，避免 RGBA→PNG 体积爆炸
            data = compress_image(img, fmt, max(quality, 95), 0, 0)
        else:
            # PNG/其他: 无损压缩，保持透明度
            data = _save_png_lossless(img)

    # 保存新结果
    new_run_id = f"reprocess-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    ext_map = {"JPEG": ".jpg", "JPG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
    ext = ext_map.get(output_format.upper(), ".jpg")
    out_path = get_output_path(source_image_id, ext, run_id=new_run_id)
    with open(out_path, "wb") as f:
        f.write(data)

    # 结果缩略图
    out_img = Image.open(out_path)
    thumb_data = generate_thumbnail(out_img)
    thumb_path = TEMP_DIR / f"{source_image_id}_{new_run_id}_result_thumb.png"
    with open(thumb_path, "wb") as f:
        f.write(thumb_data)

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
    compress_enabled: bool = Form(True),
    output_format: str = Form("JPEG"),
    quality: int = Form(85),
    max_file_size_kb: int = Form(0),
    max_width: int = Form(0),
):
    """接收前端 Canvas 编辑后的蒙版，重新合成抠图结果"""
    meta = image_store.get(image_id)
    if not meta:
        raise HTTPException(status_code=404, detail="图片不存在")

    try:
        # 加载原图（自动修正 EXIF 方向）
        original = await asyncio.to_thread(Image.open, meta["path"])
        original = await asyncio.to_thread(ImageOps.exif_transpose, original)
        original = original.convert("RGBA")

        # 加载蒙版 (黑色=擦除，白色=保留)
        mask_bytes = await mask.read()
        mask_img = await asyncio.to_thread(lambda: Image.open(io.BytesIO(mask_bytes)).convert("L"))
        mask_img = mask_img.resize(original.size, Image.NEAREST)

        # 应用蒙版
        result_img = original.copy()
        result_img.putalpha(mask_img)

        # 更新 cutout.png（不含 Logo/压缩），供后续再次编辑使用
        cutout_path = TEMP_DIR / f"{image_id}_cutout.png"
        await asyncio.to_thread(result_img.save, str(cutout_path), "PNG")

        # Logo (图片型)
        if logo_enabled:
            logo_img = None
            if logo_file_id and logo_file_id in logo_store:
                logo_img = Image.open(logo_store[logo_file_id]["path"]).convert("RGBA")
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

        # 盲水印（必须用 PNG 保存，否则 LSB 数据会被 JPEG 压缩损坏）
        if wm_blind_enabled and wm_blind_text:
            result_img = add_blind_watermark(result_img, wm_blind_text)
            output_format = "PNG"

        # 压缩
        if compress_enabled:
            data = compress_image(result_img, output_format, quality, max_file_size_kb, max_width)
        else:
            fmt = output_format.upper() if output_format else "JPEG"
            if fmt in ("JPEG", "JPG"):
                data = compress_image(result_img, fmt, max(quality, 95), 0, 0)
            else:
                data = _save_png_lossless(result_img)

        edit_run_id = f"edit-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        ext_map = {"JPEG": ".jpg", "JPG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
        ext = ext_map.get(output_format.upper(), ".jpg")
        out_path = get_output_path(image_id, ext, run_id=edit_run_id)
        with open(out_path, "wb") as f:
            f.write(data)

        # 更新缩略图
        out_img = Image.open(out_path)
        thumb_data = generate_thumbnail(out_img)
        thumb_path = TEMP_DIR / f"{image_id}_{edit_run_id}_result_thumb.png"
        with open(thumb_path, "wb") as f:
            f.write(thumb_data)

        return {
            "ok": True,
            "output_size": len(data),
            "output_url": f"/api/download/{edit_run_id}/{image_id}",
            "thumbnail_url": f"/api/result-thumbnail/{edit_run_id}/{image_id}",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── 清理 ───

@app.post("/api/cleanup")
async def cleanup():
    from backend.file_manager import cleanup_old_files
    await asyncio.to_thread(cleanup_old_files)
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
    return {"api_key": REMBG_API_KEY if hasattr(__import__('config'), 'REMBG_API_KEY') else ""}


@app.post("/api/config/apikey")
async def update_apikey(api_key: str = Form(...)):
    """更新 API Key 到配置文件"""
    config_path = Path(__file__).resolve().parent.parent / "config.py"
    content = config_path.read_text(encoding="utf-8")
    lines = content.split('\n')
    key_line_found = False
    new_lines = []
    for line in lines:
        if line.strip().startswith('REMBG_API_KEY'):
            new_lines.append(f'REMBG_API_KEY = "{api_key}"')
            key_line_found = True
        else:
            new_lines.append(line)
    if not key_line_found:
        new_lines.append(f'\nREMBG_API_KEY = "{api_key}"')
    config_path.write_text('\n'.join(new_lines), encoding="utf-8")
    return {"ok": True, "api_key": api_key}


# ─── 默认 Logo 配置管理 ───

@app.get("/api/config/default-logo")
async def get_default_logo_config():
    """获取默认 Logo 配置"""
    from config import DEFAULT_LOGO_POSITION, DEFAULT_LOGO_RATIO, DEFAULT_LOGO_OPACITY, DEFAULT_LOGO_MARGIN
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
    """更新默认 Logo 配置到配置文件"""
    config_path = Path(__file__).resolve().parent.parent / "config.py"
    content = config_path.read_text(encoding="utf-8")
    lines = content.split('\n')
    new_lines = []
    for line in lines:
        if line.strip().startswith('DEFAULT_LOGO_POSITION'):
            new_lines.append(f'DEFAULT_LOGO_POSITION = "{position}"')
        elif line.strip().startswith('DEFAULT_LOGO_RATIO'):
            new_lines.append(f'DEFAULT_LOGO_RATIO = {ratio}')
        elif line.strip().startswith('DEFAULT_LOGO_OPACITY'):
            new_lines.append(f'DEFAULT_LOGO_OPACITY = {opacity}')
        elif line.strip().startswith('DEFAULT_LOGO_MARGIN'):
            new_lines.append(f'DEFAULT_LOGO_MARGIN = {margin}')
        else:
            new_lines.append(line)
    config_path.write_text('\n'.join(new_lines), encoding="utf-8")
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
