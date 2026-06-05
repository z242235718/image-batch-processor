# 🖼️ 图片批量处理工具 v1.0.0

> **基于 Web 界面的本地图片批量处理工具** — 所有处理均在您本机完成，无需联网，注重隐私安全。

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)
![License](https://img.shields.io/badge/License-BSL--1.1-orange)

---

## 📥 下载

| 平台 | 架构 | 下载 | 大小 |
|------|------|------|------|
| 🪟 **Windows** | x86_64 | [ImageBatchProcessor-windows-x86_64.zip](https://github.com/w2422/image-processor/releases/download/v1.0.0/ImageBatchProcessor-windows-x86_64.zip) | ~130 MB |
| 🍎 **macOS** | Apple Silicon (M1~M4) | [ImageBatchProcessor-macos-arm64.tar.gz](https://github.com/w2422/image-processor/releases/download/v1.0.0/ImageBatchProcessor-macos-arm64.tar.gz) | ~130 MB |
| 🍎 **macOS** | Intel | [ImageBatchProcessor-macos-x86_64.tar.gz](https://github.com/w2422/image-processor/releases/download/v1.0.0/ImageBatchProcessor-macos-x86_64.tar.gz) | ~130 MB |
| 🐧 **Linux** | x86_64 | [ImageBatchProcessor-linux-x86_64.tar.gz](https://github.com/w2422/image-processor/releases/download/v1.0.0/ImageBatchProcessor-linux-x86_64.tar.gz) | ~130 MB |

> ⚠️ **下载说明：**
> - 解压后运行 `ImageBatchProcessor.exe`（Windows）或 `ImageBatchProcessor`（macOS/Linux）
> - 浏览器会自动打开 `http://127.0.0.1:8000`
> - 首次使用 **背景移除** 功能会自动下载模型文件（~1 GB），请耐心等待

---

## ✨ 功能特性

### 🎨 核心处理

| 功能 | 说明 |
|------|------|
| **去除背景（抠图）** | 基于 rembg + ONNX Runtime 本地推理，智能识别主体。支持 `rmbg-1.4` / `isnet-general` / `u2net` 三种模型，可调推理线程数。**无需联网，本地运算** |
| **添加 Logo** | 支持自定义 Logo 图片，可调整位置（9 宫格）、大小比例、透明度、边距，支持平铺模式 |
| **显式水印** | 文字水印，支持位置、字体大小、透明度、颜色调节，疏散/密集两种布局，多方向平铺 |
| **盲水印** | DCT 域盲水印嵌入与提取，Reed-Solomon 纠错编码，抗 JPEG 压缩。嵌入后图片肉眼无差异，可溯源版权 |
| **图片裁切** | Canvas 手绘蒙版（擦除模式），按保留区域的最小包围矩形自动裁切，支持蒙版保存与重新编辑 |
| **压缩输出** | 支持 JPEG / PNG / WebP 格式输出，可调节质量、最大文件大小、最大宽高限制。JPEG 抠图可自动逼近原图大小 |

### 💡 交互体验

- **📤 批量处理** — 多张图片一次上传，异步并行处理，不阻塞界面
- **📡 实时进度** — WebSocket 实时推送每张图片的处理进度与状态
- **🃏 结果卡片** — 每张图片处理结果独立展示，缩略图预览、下载、提取盲水印
- **🔄 继续处理** — 对已处理的图片追加 Logo、水印、裁切等操作，无需重新抠图
- **✏️ 笔刷编辑** — 抠图结果支持 Canvas 笔刷修复（恢复/擦除），所见即所得
- **👀 预览对比** — 原图与处理结果并排对比，全尺寸预览，带"原图/处理后"标签
- **📦 批量下载** — 一键打包下载所有处理结果（ZIP）
- **🔒 Session 隔离** — 浏览器 Cookie 隔离，8 小时无活动自动清理，隐私安全

### ⚡ 技术亮点

| 亮点 | 说明 |
|------|------|
| **Alpha-only 快速路径** | 抠图仅保存透明通道而非全分辨率 RGBA，大图处理内存占用减少约 3/4 |
| **堆紧缩 (HeapCompact)** | 处理大图后主动归还 C 堆内存给操作系统，防止内存只升不降 |
| **惰性导出** | Alpha-only 结果在首次下载时才按需生成全尺寸文件，避免所有图片同时膨胀 |
| **ONNX 串行推理** | 独立信号量控制 ONNX 并发（默认 1），防止多张大图同时推理导致 OOM |
| **DCT 盲水印** | 频域嵌入 + RS 纠错码 + 感知哈希兜底，抗 JPEG 压缩、裁剪等常见攻击 |

---

## 🚀 快速开始

### 解压即用

```bash
# Windows
解压 ImageBatchProcessor-windows-x86_64.zip
双击运行 ImageBatchProcessor.exe

# macOS
tar xzf ImageBatchProcessor-macos-arm64.tar.gz
./ImageBatchProcessor/ImageBatchProcessor

# Linux
tar xzf ImageBatchProcessor-linux-x86_64.tar.gz
./ImageBatchProcessor/ImageBatchProcessor
```

浏览器自动打开 [http://127.0.0.1:8000](http://127.0.0.1:8000) 即可使用。

### 开发模式

```bash
git clone https://github.com/w2422/image-processor.git
cd image-processor
pip install -r requirements.txt
python run.py
```

---

## 🛠️ 技术栈

| 层级 | 技术 |
|------|------|
| **后端框架** | Python 3.10+ / FastAPI / Uvicorn |
| **图片处理** | Pillow / rembg / ONNX Runtime / NumPy / SciPy / scikit-image |
| **图片压缩** | Pillow 高质量 JPEG 量化 + WebP 有损/无损 |
| **盲水印** | DCT 中频系数嵌入 + Reed-Solomon 纠错编码 + pHash 感知哈希兜底 |
| **前端** | 原生 HTML5 / CSS3 / JavaScript (ES6+) / Canvas |
| **实时通信** | WebSocket (asyncio) |
| **打包分发** | PyInstaller (onedir) / Inno Setup / create-dmg |

---

## ⚙️ 配置一览

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `CONCURRENT_PROCESS_LIMIT` | 4 | 非抠图任务并发处理数 |
| `CONCURRENT_BG_LIMIT` | 1 | 抠图 ONNX 推理并发数（OOM 防护） |
| `SESSION_TIMEOUT_HOURS` | 8 | Session 无活动过期时间 |
| `MAX_UPLOAD_SIZE_MB` | 50 | 单文件上传大小限制 |
| `MAX_TOTAL_UPLOADS` | 200 | 单次上传文件数量限制 |

运行时可通过界面 **设置** 面板调整 ONNX 线程数和内存 Arena 开关。

---

## 🏗️ 项目结构

```
image-processor/
├── backend/
│   ├── main.py                 # FastAPI 主应用（API + 处理调度）
│   ├── models.py               # 数据模型
│   ├── task_manager.py          # 任务管理与 WebSocket 推送
│   ├── session_manager.py       # Session ID 管理与过期清理
│   ├── file_manager.py          # 文件路径管理与清理
│   ├── processors/
│   │   ├── bg_remover.py        # 背景移除（rembg + ONNX）
│   │   ├── compressor.py        # 图片压缩
│   │   ├── dct_watermark.py     # DCT 域盲水印
│   │   ├── logo_adder.py        # Logo 叠加
│   │   ├── mask_cropper.py      # 蒙版裁切
│   │   └── watermark.py         # 显式文字水印
│   └── utils/
│       ├── ecc.py               # 纠错码（盲水印）
│       ├── image_utils.py       # 图像工具
│       ├── perceptual_hash.py   # 感知哈希
│       └── validators.py        # 文件格式验证
├── frontend/
│   ├── index.html               # 主页面
│   ├── app.js                   # 前端交互逻辑
│   └── style.css                # 样式
├── assets/                      # 资源文件
├── build/
│   ├── image_processor.spec     # Windows PyInstaller 配置
│   ├── image_processor_mac.spec # macOS PyInstaller 配置
│   ├── image_processor_linux.spec # Linux PyInstaller 配置
│   ├── build.bat                # Windows 构建脚本
│   ├── build_mac.sh             # macOS 构建脚本
│   ├── build_linux.sh           # Linux 构建脚本
│   └── installer.iss            # Inno Setup 安装包配置
├── config.py                    # 应用配置
├── launcher.py                  # 打包入口（端口查找 + 自动打开浏览器）
├── run.py                       # 开发模式入口（热重载）
└── requirements.txt             # Python 依赖
```

---

## 📄 许可协议

**Business Source License 1.1 (BSL-1.1)**

Copyright (C) 2026 w2422. All rights reserved.

- ✅ **非生产性使用**（个人学习、研究、评估）— 免费
- ❌ **商业用途**（企业内部使用、对外提供服务等）— 需获得授权
- ❌ 未经许可，不得将本软件或其衍生作品作为云服务向第三方提供

**Change Date:** 2029-01-01 → 自动转换为 **GNU General Public License v2.0 or later**

---

## 📬 联系我们

- 作者: [w2422](https://www.gvnote.com)
- 邮箱: [z242235718@163.com](mailto:z242235718@163.com)
- 项目地址: [https://github.com/w2422/image-processor](https://github.com/w2422/image-processor)

---

> **提示：** 使用过程中遇到任何 Bug 或功能建议，请提交 [Issue](https://github.com/w2422/image-processor/issues) 或发送邮件。感谢您的支持！🙏
