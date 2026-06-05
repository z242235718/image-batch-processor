#!/bin/bash
# ============================================
#   图片批量处理工具 - macOS 打包脚本
# ============================================
# 使用方式：
#   chmod +x build/build_mac.sh
#   ./build/build_mac.sh
#
# 前置条件：
#   1. macOS 系统 (Intel 或 Apple Silicon)
#   2. Python 3.12+ 已安装
#   3. pip install pyinstaller
#   4. 项目依赖已安装: pip install -r requirements.txt
#   5. 如需 .app 图标，准备 assets/icon.icns
#
# 输出：
#   build/dist/ImageBatchProcessor/   (命令行版)
#   build/dist/ImageBatchProcessor.app (可选 GUI 版)
# ============================================

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 项目根目录（脚本所在目录的上一级）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}  图片批量处理工具 - macOS 打包脚本${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# 检查 Python
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}[错误] 未找到 Python3，请确保已安装${NC}"
    echo "  brew install python@3.12"
    exit 1
fi

PYTHON=$(command -v python3)
echo -e "${GREEN}[信息] Python: $($PYTHON --version)${NC}"

# 检查 PyInstaller
if ! $PYTHON -c "import PyInstaller" 2>/dev/null; then
    echo -e "${YELLOW}[信息] 正在安装 PyInstaller...${NC}"
    $PYTHON -m pip install pyinstaller
fi

PYINSTALLER_VERSION=$($PYTHON -m PyInstaller --version 2>/dev/null)
echo -e "${GREEN}[信息] PyInstaller: $PYINSTALLER_VERSION${NC}"

# 检测架构
ARCH=$(uname -m)
echo -e "${GREEN}[信息] 当前架构: ${ARCH}${NC}"
if [ "$ARCH" = "arm64" ]; then
    TARGET_ARCH="arm64"
    echo -e "${YELLOW}[提示] 构建 Apple Silicon (ARM64) 版本${NC}"
else
    TARGET_ARCH="x86_64"
    echo -e "${YELLOW}[提示] 构建 Intel (x86_64) 版本${NC}"
fi

# 清理旧构建
echo ""
echo -e "${YELLOW}[信息] 清理旧构建...${NC}"
rm -rf "build/dist" "build/pyinstaller-work"

# 检查 icon
ICON_PATH=""
if [ -f "assets/icon.icns" ]; then
    ICON_PATH="assets/icon.icns"
    echo -e "${GREEN}[信息] 找到图标: ${ICON_PATH}${NC}"
else
    echo -e "${YELLOW}[警告] 未找到 assets/icon.icns，将使用默认图标${NC}"
    echo -e "${YELLOW}  如需自定义图标:${NC}"
    echo -e "${YELLOW}    1. 准备 1024x1024 PNG${NC}"
    echo -e "${YELLOW}    2. 安装 iconutil: brew install iconutil${NC}"
    echo -e "${YELLOW}    3. 转换: iconutil -c icns icon.iconset -o assets/icon.icns${NC}"
fi

# ============================================
# 命令行版本 (CLI) - 运行在终端中
# ============================================
echo ""
echo -e "${BLUE}[步骤 1/2] 构建命令行版本...${NC}"
echo -e "${BLUE}------------------------------------${NC}"

CLI_ARGS=(
    --workpath "build/pyinstaller-work"
    --distpath "build/dist"
    --clean
    --noconfirm
)

if [ -n "$ICON_PATH" ]; then
    CLI_ARGS+=(--icon "$ICON_PATH")
fi

CLI_ARGS+=("build/image_processor_mac.spec")

$PYTHON -m PyInstaller "${CLI_ARGS[@]}"

echo ""
echo -e "${GREEN}[成功] 命令行版本构建完成${NC}"
echo -e "${GREEN}  输出: build/dist/ImageBatchProcessor/ImageBatchProcessor${NC}"

# ============================================
# .app 版本 (可选) - 双击运行，浏览器自动打开
# ============================================
echo ""
echo -e "${BLUE}[步骤 2/2] 构建 .app 版本（可选）...${NC}"
echo -e "${BLUE}------------------------------------${NC}"

# 修改 spec 为 .app 模式: 使用 --windowed 创建 .app
APP_SPEC="build/image_processor_mac.spec"

# 用 sed 切换 console=True -> console=False 构建 .app
# 先备份原始 spec
cp "$APP_SPEC" "${APP_SPEC}.cli_backup"

# 创建 .app 版本的 spec
APP_SPEC_APP="build/image_processor_mac_app.spec"
cp "$APP_SPEC" "$APP_SPEC_APP"

# macOS 下 sed 替换
sed -i '' 's/console=True/console=False/g' "$APP_SPEC_APP"
sed -i '' "s/name=\"ImageBatchProcessor\"/name=\"ImageBatchProcessor\"/g" "$APP_SPEC_APP"

# 构建 .app
APP_ARGS=(
    --workpath "build/pyinstaller-work-app"
    --distpath "build/dist"
    --clean
    --noconfirm
)

if [ -n "$ICON_PATH" ]; then
    APP_ARGS+=(--icon "$ICON_PATH")
fi

APP_ARGS+=("$APP_SPEC_APP")

$PYTHON -m PyInstaller "${APP_ARGS[@]}" 2>&1 || {
    echo -e "${YELLOW}[警告] .app 构建跳过或失败${NC}"
    echo -e "${YELLOW}  命令行版本仍可用${NC}"
}

# 恢复原始 spec（控制台版本）
cp "${APP_SPEC}.cli_backup" "$APP_SPEC"
rm -f "${APP_SPEC}.cli_backup"

# ============================================
# 输出摘要
# ============================================
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  构建完成！${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo -e "  架构: ${YELLOW}${ARCH}${NC}"

if [ -f "build/dist/ImageBatchProcessor/ImageBatchProcessor" ]; then
    echo -e "  命令行版本: ${GREEN}build/dist/ImageBatchProcessor/ImageBatchProcessor${NC}"
    FILE_SIZE=$(du -sh "build/dist/ImageBatchProcessor/" 2>/dev/null | cut -f1)
    echo -e "  目录大小: ${YELLOW}${FILE_SIZE}${NC}"
    echo ""
    echo -e "  运行方式:"
    echo -e "    ./build/dist/ImageBatchProcessor/ImageBatchProcessor"
    echo -e "    然后浏览器访问 http://127.0.0.1:8000"
fi

if [ -d "build/dist/ImageBatchProcessor.app" ]; then
    echo ""
    echo -e "  .app 版本: ${GREEN}build/dist/ImageBatchProcessor.app${NC}"
    echo -e "  直接双击运行 (会自动打开浏览器)"
fi

echo ""
echo -e "${YELLOW}提示:${NC}"
echo -e "  - 首次使用背景移除功能会自动下载模型 (~1GB)"
echo -e "  - 数据存储在 ~/Library/Application Support/ImageProcessor/"
echo -e "  - 如需分发给其他 Mac 用户，可以:"
echo -e "    1. 压缩 build/dist/ImageBatchProcessor.app 为 .zip"
echo -e "    2. 或使用 create-dmg 制作安装包:"
echo -e "       brew install create-dmg"
echo -e "       create-dmg --app-drop-link 180 120 --icon ImageBatchProcessor 0 0 build/ImageBatchProcessor.dmg build/dist/ImageBatchProcessor.app"
echo ""
