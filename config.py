from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
TEMP_DIR = BASE_DIR / "temp"
ASSETS_DIR = BASE_DIR / "assets"
FRONTEND_DIR = BASE_DIR / "frontend"

# 上传限制
MAX_UPLOAD_SIZE_MB = 50
MAX_TOTAL_UPLOADS = 200
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}

# 处理控制
CONCURRENT_PROCESS_LIMIT = 4

# 文件清理
CLEANUP_AGE_HOURS = 24

# remove.bg API Key (用于云端抠图)
REMBG_API_KEY = ""

# 文件签名 (magic bytes) 用于验证上传文件类型
FILE_SIGNATURES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"RIFF": "image/webp",  # 需进一步检查 WEBP 标识
    b"BM": "image/bmp",
    b"MM\x00\x2a": "image/tiff",
    b"II\x2a\x00": "image/tiff",
}

# 确保目录存在
for d in [INPUT_DIR, OUTPUT_DIR, TEMP_DIR]:
    d.mkdir(exist_ok=True)
