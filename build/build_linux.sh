#!/bin/bash
# ============================================
#   图片批量处理工具 - Linux 打包脚本
# ============================================
# 使用方式：
#   chmod +x build/build_linux.sh
#   ./build/build_linux.sh
#
# 前置条件：
#   1. Linux 系统 (Ubuntu 20.04+, Debian 11+, CentOS 8+, 或其他 glibc 2.28+ 的发行版)
#   2. Python 3.10+ 已安装: sudo apt install python3 python3-pip python3-venv
#   3. pip install pyinstaller
#   4. 项目依赖已安装: pip install -r requirements.txt
#   5. 可选: patchelf (用于 strip 减小体积): sudo apt install patchelf
#
# 输出：
#   build/dist/ImageBatchProcessor/   (包含可执行文件及其依赖)
#
# 运行方式：
#   ./build/dist/ImageBatchProcessor/ImageBatchProcessor
#   然后浏览器访问 http://127.0.0.1:8000
#
# 分发说明：
#   编译后的目录可以整体打包分发，接收方无需安装 Python。
#  ⚠️ glibc 版本需与构建系统相同或更高（兼容性向下不兼容）
#   建议在尽量低的 glibc 版本上构建以扩大兼容性：
#     - Ubuntu 20.04 → glibc 2.31 (兼容性好)
#     - Ubuntu 22.04 → glibc 2.35
#     - CentOS 7 → glibc 2.17 (兼容性最好，但需要 Python 3.10+ 自行编译)
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
echo -e "${BLUE}  图片批量处理工具 - Linux 打包脚本${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

# 检查 Python
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON=$(command -v "$cmd")
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo -e "${RED}[错误] 未找到 Python3，请确保已安装${NC}"
    echo "  sudo apt install python3 python3-pip python3-venv"
    exit 1
fi

PYTHON_VERSION=$($PYTHON --version 2>&1 | grep -oP '\d+\.\d+')
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
if [ "$ARCH" = "x86_64" ]; then
    echo -e "${YELLOW}[提示] 构建 AMD64/x86_64 版本${NC}"
elif [ "$ARCH" = "aarch64" ]; then
    echo -e "${YELLOW}[提示] 构建 ARM64 (aarch64) 版本${NC}"
    echo -e "${YELLOW}  ⚠️ onnxruntime 需要安装 ARM64 版本: pip install onnxruntime-arm64${NC}"
else
    echo -e "${YELLOW}[提示] 构建 ${ARCH} 版本${NC}"
    echo -e "${YELLOW}  ⚠️ 请确保 ONNX Runtime 支持此架构${NC}"
fi

# 检查系统包
echo ""
echo -e "${BLUE}[检查] 系统环境...${NC}"

# 检查 glibc 版本
LIBC_VERSION=$(ldd --version 2>&1 | head -1 | grep -oP '\d+\.\d+$' || echo "unknown")
echo -e "${GREEN}[信息] glibc 版本: ${LIBC_VERSION}${NC}"
if [ "$(echo "$LIBC_VERSION" | cut -d. -f1)" -lt 2 ] || { [ "$(echo "$LIBC_VERSION" | cut -d. -f1)" -eq 2 ] && [ "$(echo "$LIBC_VERSION" | cut -d. -f2)" -lt 28 ]; }; then
    echo -e "${YELLOW}[警告] glibc 版本过低 (< 2.28)，可能某些依赖无法正常工作${NC}"
fi

# 清理旧构建
echo ""
echo -e "${YELLOW}[信息] 清理旧构建...${NC}"
rm -rf "build/dist" "build/pyinstaller-work"

# ============================================
# PyInstaller 构建
# ============================================
echo ""
echo -e "${BLUE}[步骤] 正在使用 PyInstaller 打包应用...${NC}"
echo -e "${BLUE}------------------------------------${NC}"
echo -e "${YELLOW}[信息] 这可能需要 1-5 分钟，请耐心等待...${NC}"

# 收集所有需要包含的数据文件
PYINSTALLER_ARGS=(
    --workpath "build/pyinstaller-work"
    --distpath "build/dist"
    --clean
    --noconfirm
)

PYINSTALLER_ARGS+=("build/image_processor_linux.spec")

$PYTHON -m PyInstaller "${PYINSTALLER_ARGS[@]}"

# ============================================
# 验证构建输出
# ============================================
echo ""
echo -e "${BLUE}[验证] 构建输出...${NC}"

if [ -f "build/dist/ImageBatchProcessor/ImageBatchProcessor" ]; then
    echo -e "${GREEN}[成功] 构建完成！${NC}"
    echo ""
    echo -e "  可执行文件: ${GREEN}build/dist/ImageBatchProcessor/ImageBatchProcessor${NC}"
    FILE_SIZE=$(du -sh "build/dist/ImageBatchProcessor/" 2>/dev/null | cut -f1)
    echo -e "  目录大小: ${YELLOW}${FILE_SIZE}${NC}"
    echo ""

    # 检查文件类型
    echo -e "${BLUE}[信息] 文件信息:${NC}"
    file "build/dist/ImageBatchProcessor/ImageBatchProcessor"

    echo ""
    echo -e "  运行方式:"
    echo -e "    ${GREEN}./build/dist/ImageBatchProcessor/ImageBatchProcessor${NC}"
    echo -e "    然后浏览器访问 ${GREEN}http://127.0.0.1:8000${NC}"
    echo ""
    echo -e "  首次使用背景移除功能会自动下载模型 (~1GB)"
    echo ""
    echo -e "  分发方式:"
    echo -e "    cd build/dist"
    echo -e "    tar czf ImageBatchProcessor-linux-${ARCH}.tar.gz ImageBatchProcessor/"
    echo ""
else
    echo -e "${RED}[错误] 未找到输出可执行文件${NC}"
    echo -e "${RED}  检查 build/dist/ 目录内容:${NC}"
    ls -la "build/dist/"
    exit 1
fi

echo ""
echo -e "${YELLOW}提示:${NC}"
echo -e "  - 数据存储在 ~/.local/share/ImageProcessor/"
echo -e "  - 如需系统级安装，请创建 .desktop 文件和符号链接"
echo ""

exit 0
