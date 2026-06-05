# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for Image Processor (Linux)
# Build: pyinstaller --workpath "build/pyinstaller-work" --distpath "build/dist" "build/image_processor_linux.spec"
#
# Linux 构建说明：
#   1. 需要在 Linux 系统上运行 PyInstaller (Ubuntu 20.04+, Debian 11+, etc.)
#   2. 前置条件：
#      sudo apt install python3 python3-pip
#      pip install -r requirements.txt pyinstaller
#   3. 构建后的可执行文件在 build/dist/ImageBatchProcessor/ImageBatchProcessor
#   4. 由于 rembg/ONNX 依赖较多，推荐使用 --onedir 模式（默认）
#      onefile 模式可能有兼容性问题，不推荐
#
#   5. 如需减小体积，可以安装 patchelf: sudo apt install patchelf
#      然后设置 strip=True

import sys
from pathlib import Path

# 从 spec 文件位置推导项目根目录
PROJECT_ROOT = Path(sys.argv[0] if sys.argv[0] and sys.argv[0] != "." else ".").resolve().parent.parent

block_cipher = None

a = Analysis(
    [str(PROJECT_ROOT / "launcher.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        # 静态文件目录
        (str(PROJECT_ROOT / "frontend"), "frontend"),
        (str(PROJECT_ROOT / "assets"), "assets"),
    ],
    hiddenimports=[
        # 应用模块
        "backend.main",
        "backend.models",
        "backend.task_manager",
        "backend.file_manager",
        "backend.session_manager",
        "backend.processors",
        "backend.processors.bg_remover",
        "backend.processors.compressor",
        "backend.processors.dct_watermark",
        "backend.processors.logo_adder",
        "backend.processors.mask_cropper",
        "backend.processors.watermark",
        "backend.utils",
        "backend.utils.ecc",
        "backend.utils.image_utils",
        "backend.utils.perceptual_hash",
        "backend.utils.validators",
        # uvicorn 子模块
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.middleware",
        "uvicorn.middleware.asgi",
        # Web 框架
        "fastapi",
        "starlette",
        "starlette.middleware",
        "starlette.middleware.cors",
        "starlette.staticfiles",
        "starlette.templating",
        "pydantic",
        "pydantic_core",
        "multipart",
        # 网络 / IO
        "websockets",
        "websockets.legacy",
        "httpx",
        "aiofiles",
        # 图片处理
        "PIL",
        "PIL._imaging",
        "PIL._webp",
        "PIL.Image",
        "PIL.ImageDraw",
        "PIL.ImageFont",
        "PIL.ImageFilter",
        "PIL.ImageOps",
        "PIL.ImageChops",
        "PIL.ImageEnhance",
        "PIL.ImageFile",
        "PIL.JpegImagePlugin",
        "PIL.PngImagePlugin",
        "PIL.WebPImagePlugin",
        "PIL.BmpImagePlugin",
        "PIL.TiffImagePlugin",
        "PIL.GifImagePlugin",
        "PIL.ExifTags",
        "PIL.IptcImagePlugin",
        "PIL.MpoImagePlugin",
        "PIL.MspImagePlugin",
        "PIL.PalmImagePlugin",
        "PIL.PcdImagePlugin",
        "PIL.PcxImagePlugin",
        "PIL.PdfImagePlugin",
        "PIL.PixarImagePlugin",
        "PIL.PpmImagePlugin",
        "PIL.PsdImagePlugin",
        "PIL.SgiImagePlugin",
        "PIL.SunImagePlugin",
        "PIL.TgaImagePlugin",
        "PIL.XbmImagePlugin",
        "PIL.XpmImagePlugin",
        "PIL.BufrStubImagePlugin",
        "PIL.FitsStubImagePlugin",
        "PIL.FliImagePlugin",
        "PIL.FpxImagePlugin",
        "PIL.GbrImagePlugin",
        "PIL.GribStubImagePlugin",
        "PIL.Hdf5StubImagePlugin",
        "PIL.IcnsImagePlugin",
        "PIL.IcoImagePlugin",
        "PIL.ImImagePlugin",
        "PIL.ImtImagePlugin",
        "PIL.IptcImagePlugin",
        "PIL.Jpeg2KImagePlugin",
        "PIL.McIdasImagePlugin",
        "PIL.MicImagePlugin",
        "PIL.MpegImagePlugin",
        "PIL.MpoImagePlugin",
        "PIL.MspImagePlugin",
        "PIL.PalmImagePlugin",
        "PIL.PcdImagePlugin",
        "PIL.PcxImagePlugin",
        "PIL.PdfImagePlugin",
        "PIL.PixarImagePlugin",
        "PIL.PpmImagePlugin",
        "PIL.PsdImagePlugin",
        "PIL.SgiImagePlugin",
        "PIL.SunImagePlugin",
        "PIL.TgaImagePlugin",
        "PIL.XbmImagePlugin",
        "PIL.XpmImagePlugin",
        # 数值计算
        "numpy",
        "scipy.ndimage",
        "scipy.special",
        # rembg 依赖链
        "skimage",
        "skimage.morphology",
        "skimage.measure",
        "skimage.color",
        "skimage.util",
        "skimage.filters",
        "skimage.segmentation",
        "skimage.transform",
        "pymatting",
        "pooch",
        # 纠错码
        "reedsolo",
        # Linux 特有
        "grp",
        "pwd",
        "resource",
    ],
    hookspath=[str(PROJECT_ROOT / "build")],
    hooksconfig={},
    excludes=[
        # GUI 工具包（不需要）
        "tkinter",
        # 测试 / 构建工具
        "test",
        "distutils",
        "distutils.command",
        "setuptools",
        "pip",
        "venv",
        "ensurepip",
        # 不需要的标准库
        "curses",
        "lib2to3",
        "http.server",
        "xml.dom",
        "xml.dom.minidom",
        "xml.dom.pulldom",
        "xml.etree",
        "xmlrpc",
        "xmlrpc.client",
        "xmlrpc.server",
        # Windows/macOS 专有排除
        "win32com",
        "win32com.client",
        "win32api",
        "msvcrt",
        "ctypes.macholib",
        # macOS GUI
        "PyObjCTools",
        "Foundation",
        "AppKit",
    ],
    runtime_hooks=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="ImageBatchProcessor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_trailer=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

# 清理不必要的测试数据
for d in list(a.datas):
    if d[0].startswith("tests") or d[0].startswith("test_"):
        a.datas.remove(d)

# --onedir 模式
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ImageBatchProcessor",
)
