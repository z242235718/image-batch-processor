from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class LogoConfig(BaseModel):
    enabled: bool = False
    position: str = "right-bottom"
    ratio: float = Field(0.15, ge=0.01, le=0.5)
    opacity: float = Field(0.8, ge=0.0, le=1.0)
    tile: bool = False
    logo_file_id: Optional[str] = None
    # 文字水印
    text: Optional[str] = None
    text_color: str = "#000000"
    text_font_size: int = Field(36, ge=8, le=200)


class CompressConfig(BaseModel):
    enabled: bool = True
    output_format: str = "JPEG"
    quality: int = Field(85, ge=1, le=100)
    max_file_size_kb: int = Field(0, ge=0)
    max_width: int = Field(0, ge=0)
    # 裁切/蒙版裁切由调用方在 compress_image 之前完成（蒙版走 /api/edit-mask 等端点）


class ProcessConfig(BaseModel):
    bg_method: str = "none"  # none | local | api
    api_key: str = ""
    logo: LogoConfig = LogoConfig()
    compress: CompressConfig = CompressConfig()


class ImageMeta(BaseModel):
    id: str
    filename: str
    width: int = 0
    height: int = 0
    file_size: int = 0
    thumbnail_url: str = ""


class ProcessResult(BaseModel):
    id: str
    filename: str
    run_id: str = ""
    output_size: int = 0
    output_url: str = ""
    thumbnail_url: str = ""
    status: str = "pending"
    error_msg: str = ""
    finished_at: str = ""


class BatchTask(BaseModel):
    batch_id: str
    total: int = 0
    done: int = 0
    failed: int = 0
    status: TaskStatus = TaskStatus.PENDING
    results: List[ProcessResult] = []
    errors: List[Dict[str, Any]] = []
