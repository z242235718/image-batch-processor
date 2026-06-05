# 图片批量处理工具 (Image Batch Processor)

基于 Web 界面的图片批量处理工具，支持压缩、缩放、水印、logo、背景移除、裁切等功能。

## 功能

- 🔧 图片压缩（JPEG/WebP 格式、质量、缩放、文件大小限制）
- 💧 水印添加（文字水印）
- 🖼️ Logo 添加（位置、大小、透明度、边距可调）
- ✂️ 背景移除（基于 rembg + ONNX 本地模型）
- 📐 图片裁切
- ⚡ 批量处理 + WebSocket 实时进度
- 🔄 结果卡片继续处理

## 技术栈

- **后端**: Python / FastAPI / Uvicorn
- **前端**: 原生 HTML + CSS + JavaScript
- **打包**: PyInstaller (Windows / macOS)

---

## Windows 构建

### 前置条件

1. Python 3.12+
2. 项目依赖已安装
3. [Inno Setup](https://jrsoftware.org/isdl.php) 6+（可选，用于制作安装包）

### 构建步骤

```batch
# 方式一：使用构建脚本
build\build.bat

# 方式二：直接运行 PyInstaller
pyinstaller --workpath "build\pyinstaller-work" --distpath "build\dist" "build\image_processor.spec"

# 制作安装包（需安装 Inno Setup）
iscc build\installer.iss
```

### 输出

| 产物 | 路径 | 说明 |
|------|------|------|
| 绿色版 | `build\dist\ImageBatchProcessor\ImageBatchProcessor.exe` | 直接运行 |
| 安装包 | `build\dist\ImageBatchProcessor_Setup_v*.exe` | Inno Setup 打包 |

---

## macOS 构建

> ⚠️ 需要在 macOS 系统上运行构建脚本（Windows 无法交叉编译 macOS 程序）

### 前置条件

```bash
# 1. 确保 Python 已安装
brew install python@3.12

# 2. 安装项目依赖
pip install -r requirements.txt

# 3. 安装 PyInstaller
pip install pyinstaller
```

### 构建步骤

```bash
# 方式一：使用构建脚本
chmod +x build/build_mac.sh
./build/build_mac.sh

# 方式二：手动构建
pyinstaller --workpath "build/pyinstaller-work" --distpath "build/dist" "build/image_processor_mac.spec"
```

### 输出

| 产物 | 路径 | 说明 |
|------|------|------|
| 命令行版 | `build/dist/ImageBatchProcessor/ImageBatchProcessor` | 终端运行，显示日志 |
| .app 版 | `build/dist/ImageBatchProcessor.app` | 双击运行（构建脚本自动创建） |

### 架构支持

构建脚本自动检测当前 Mac 架构：

- **Apple Silicon (M1/M2/M3/M4)**: 构建 arm64 版本
- **Intel Mac**: 构建 x86_64 版本

如需要 Universal Binary：

```bash
# 在 Intel Mac 和 Apple Silicon Mac 上各构建一次
# 然后使用 lipo 合并
lipo -create -output ImageBatchProcessor_universal \
  build/dist/ImageBatchProcessor/ImageBatchProcessor \  # Intel 构建产物
  build/dist/ImageBatchProcessor/ImageBatchProcessor    # ARM 构建产物
```

### DMG 安装包（可选）

```bash
brew install create-dmg
create-dmg \
  --app-drop-link 180 120 \
  --icon ImageBatchProcessor 0 0 \
  build/ImageBatchProcessor.dmg \
  build/dist/ImageBatchProcessor.app
```

---

## 开发模式

```bash
# 后端热重载开发
python run.py

# 或直接启动 uvicorn
uvicorn backend.main:app --reload --port 8000
```

浏览器访问: http://127.0.0.1:8000

---

## 目录结构

```
├── backend/           # Python 后端
│   ├── main.py
│   ├── processors/    # 各处理模块
│   ├── utils/         # 工具函数
│   └── ...
├── frontend/          # 前端静态资源
│   ├── index.html
│   ├── app.js
│   └── style.css
├── assets/            # 资源文件
├── config.py          # 应用配置
├── launcher.py        # 打包入口
├── run.py             # 开发模式入口
├── build/             # 构建配置
│   ├── build.bat                 # Windows 构建脚本
│   ├── image_processor.spec      # Windows PyInstaller spec
│   ├── build_mac.sh              # macOS 构建脚本
│   ├── image_processor_mac.spec  # macOS PyInstaller spec
│   ├── installer.iss             # Inno Setup 安装包配置
│   └── ...
└── runtime_config.json # 运行时配置
```

## 许可

Copyright (C) 2026 w2422. All rights reserved.
