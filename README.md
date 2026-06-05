# 🖼️ 图片批量处理工具 (Image Batch Processor)

> 基于 Web 界面的本地图片批量处理工具，所有处理均在用户本机完成，无需联网，注重隐私保护。提供浏览器端 UI，支持批量背景移除(结果手动修改)、Logo 添加、水印嵌入、裁剪、压缩等功能。

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS-lightgrey)
![License](https://img.shields.io/badge/License-BSL--1.1-orange)
![Version](https://img.shields.io/badge/Version-1.0.0-brightgreen)

---

## ✨ 功能特性

### 核心处理

| 功能 | 说明 |
|------|------|
| 🎨 **去除背景（抠图）** | 基于 rembg + ONNX Runtime 本地推理，智能识别主体。支持 `rmbg-1.4` / `isnet-general` / `u2net` 模型，可调线程数。**无需联网，本地运算** |
| 🖼️ **添加 Logo** | 支持自定义 Logo 图片，可调整位置、大小比例、透明度、边距，支持平铺模式 |
| 💧 **显式水印** | 文字水印，支持位置、字体大小、透明度、颜色调节，疏散/密集两种布局，支持多方向平铺 |
| 🔏 **盲水印** | 开发中... |
| ✂️ **图片裁切** | Canvas 手绘蒙版，按保留区域的最小包围矩形裁切（擦除模式），支持蒙版保存与重新编辑 |
| 📦 **压缩输出** | 支持 JPEG / PNG / WebP 格式输出，可调节质量、最大文件大小、最大宽高限制。JPG 抠图可自动逼近原图大小 |

### 交互体验

- **批量处理**: 多张图片一次处理，异步并行，不阻塞界面
- **实时进度**: WebSocket 推送每张图片的处理进度与状态
- **结果卡片**: 每张图片的处理结果独立展示，缩略图预览、下载、提取盲水印
- **继续处理**: 对已处理的图片追加 Logo、水印、裁切等操作，无需重新抠图
- **笔刷编辑**: 抠图结果支持 Canvas 笔刷修复（恢复/擦除），所见即所得
- **预览对比**: 原图与处理结果并排对比，全尺寸预览
- **批量下载**: 一键打包下载所有处理结果（ZIP）
- **Session 隔离**: 浏览器隔离，自动清理过期会话

### 技术亮点

- **抠图内存优化**: `alpha-only` 快速路径，仅保存透明通道而非全分辨率 RGBA，大文件图片抠图内存占用减少 1/4
- **堆紧缩 (HeapCompact)**: 处理大图后主动归还 C 堆内存给操作系统，防止内存只升不降
- **惰性导出**: alpha-only 结果在首次下载时才按需生成全尺寸文件，避免所有图片同时解压
- **ONNX 串行推理**: 背景移除使用独立信号量控制并发，避免多张全分辨率图片同时推理导致 OOM

---

## 🚀 快速开始

### 开发模式

```bash
# 克隆仓库
git clone https://github.com/w2422/image-processor.git
cd image-processor

# 安装依赖
pip install -r requirements.txt

# 启动开发服务器（自动热重载）
python run.py

# 浏览器访问
# http://127.0.0.1:8000
```

### 生产部署

通过 PyInstaller 打包为独立可执行文件，无需 Python 环境。

**Windows:**

```batch
pyinstaller --workpath "build\pyinstaller-work" --distpath "build\dist" "build\image_processor.spec"

# 可选：制作安装包（需安装 Inno Setup 6+）
iscc build\installer.iss
```

**macOS:**

```bash
chmod +x build/build_mac.sh
./build/build_mac.sh
```

---

## 📁 目录结构

```
├── backend/                    # Python 后端
│   ├── main.py                 # FastAPI 主应用（API 路由 + 处理调度）
│   ├── models.py               # 数据模型
│   ├── task_manager.py          # 任务管理与 WebSocket 推送
│   ├── session_manager.py      # Session ID 管理与过期清理
│   ├── file_manager.py         # 文件路径管理与清理
│   ├── processors/             # 各处理模块
│   │   ├── bg_remover.py       # 背景移除（rembg + ONNX）
│   │   ├── compressor.py       # 图片压缩（尺寸/质量/文件大小）
│   │   ├── dct_watermark.py    # DCT 域盲水印
│   │   ├── logo_adder.py       # Logo 叠加
│   │   ├── mask_cropper.py     # 蒙版裁切
│   │   └── watermark.py        # 显式文字水印
│   └── utils/                  # 工具函数
│       ├── ecc.py              # 纠错码（盲水印）
│       ├── image_utils.py      # 图像工具（缩略图等）
│       ├── perceptual_hash.py  # 感知哈希
│       └── validators.py       # 文件格式验证
├── frontend/                   # 前端静态资源
│   ├── index.html              # 主页面
│   ├── app.js                  # 前端交互逻辑
│   └── style.css               # 样式
├── assets/                     # 资源文件（Logo 等）
├── build/                      # 构建配置
│   ├── image_processor.spec    # Windows PyInstaller spec
│   ├── image_processor_mac.spec# macOS PyInstaller spec
│   ├── build.bat               # Windows 构建脚本
│   ├── build_mac.sh            # macOS 构建脚本
│   └── installer.iss           # Inno Setup 安装包配置
├── config.py                   # 应用配置
├── launcher.py                 # 打包入口（端口查找 + 自动打开浏览器）
├── run.py                      # 开发模式入口（热重载）
└── requirements.txt            # Python 依赖
```

---

## 🛠️ 技术栈

| 层级 | 技术 |
|------|------|
| **后端框架** | Python 3.10+ / FastAPI / Uvicorn |
| **图片处理** | Pillow (PIL) / rembg / ONNX Runtime / numpy / scipy / scikit-image |
| **图片压缩** | Pillow 高质量 JPEG 量化 + WebP 有损/无损 |
| **盲水印** | DCT 中频系数嵌入 + Reed-Solomon 纠错编码 + pHash 感知哈希兜底 |
| **前端** | 原生 HTML5 / CSS3 / JavaScript (ES6+) / Canvas |
| **实时通信** | WebSocket (asyncio) |
| **打包分发** | PyInstaller (onedir), Inno Setup (Windows), create-dmg (macOS) |
| **许可证** | Business Source License 1.1 (2031 年转为 GPL v2.0+) |

---

## ⚙️ 配置说明

主要配置位于 `config.py`，支持运行时通过 API 修改：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `CONCURRENT_PROCESS_LIMIT` | 4 | 非抠图任务并发处理数 |
| `CONCURRENT_BG_LIMIT` | 1 | 抠图 ONNX 推理并发数（OOM 防护） |
| `SESSION_TIMEOUT_HOURS` | 8 | Session 无活动过期时间 |
| `CLEANUP_AGE_HOURS` | 168 | 结果文件保留时间（7 天） |
| `MAX_UPLOAD_SIZE_MB` | 50 | 单文件上传大小限制 |
| `MAX_TOTAL_UPLOADS` | 200 | 单次上传文件数量限制 |

运行时可通过界面"设置"面板调整 ONNX 线程数和内存 Arena 开关。

---

## 📄 许可

**Business Source License 1.1 (BSL-1.1)**

Copyright (C) 2026 w2422. All rights reserved.

Licensor: w2422 (z242235718@163.com)

Licensed Work: 图片批量处理工具 (Image Batch Processor)

**附加使用条款：**
- 本软件可用于任何非生产性目的（个人学习、研究、评估）
- 商业用途（企业内部使用、对外提供服务等）需获得授权
- 未经许可，不得将本软件或其衍生作品作为云服务向第三方提供

**Change Date:** 2031-01-01

Change License: GNU General Public License v2.0 or later

根据 BSL 1.1 条款，在 Change Date 之后，本软件将自动转换为 GPL v2.0 或后续版本授权。详情请参见 [Business Source License](https://mariadb.com/bsl-faq-mariadb/) 官方 FAQ。

---

## 📬 联系方式

- 作者: w2422
- 邮箱: z242235718@163.com
- 网站: [https://www.gvnote.com](https://www.gvnote.com)
