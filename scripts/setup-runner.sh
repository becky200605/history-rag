#!/usr/bin/env bash
# 一键在本机安装 GitHub Actions self-hosted runner（macOS）
# 用法：bash scripts/setup-runner.sh

set -euo pipefail

REPO="histroy-llm/history-rag"
RUNNER_VERSION="2.334.0"
RUNNER_DIR="$HOME/actions-runner"

ARCH="$(uname -m)"
case "$ARCH" in
  arm64)  PLATFORM="osx-arm64" ;;
  x86_64) PLATFORM="osx-x64" ;;
  *)
    echo "不支持的架构: $ARCH"
    exit 1
    ;;
esac

TARBALL="actions-runner-${PLATFORM}-${RUNNER_VERSION}.tar.gz"
DOWNLOAD_URL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${TARBALL}"

echo "=============================="
echo " GitHub Actions Self-hosted Runner 安装脚本"
echo " 仓库:   $REPO"
echo " 版本:   $RUNNER_VERSION"
echo " 平台:   $PLATFORM"
echo " 安装目录: $RUNNER_DIR"
echo "=============================="
echo ""

# 1. 先去 GitHub 拿 token
echo "第 1 步：获取注册 Token"
echo "  请在浏览器打开：https://github.com/${REPO}/settings/actions/runners/new?runnerOs=macOS"
echo "  页面上有一段 '--token XXXXX' 命令，把 token 复制过来。"
echo ""
read -rp "粘贴你的 Runner Token（AAXXXX...）: " RUNNER_TOKEN
echo ""

# 2. 下载 & 解压
echo "第 2 步：下载 runner $RUNNER_VERSION..."
mkdir -p "$RUNNER_DIR"
cd "$RUNNER_DIR"

if [[ -f "$TARBALL" ]]; then
  echo "  已存在 $TARBALL，跳过下载。"
else
  curl -fSL -o "$TARBALL" "$DOWNLOAD_URL"
fi

tar xzf "$TARBALL"
echo "  解压完成。"

# 3. 配置
echo ""
echo "第 3 步：配置 runner..."
./config.sh \
  --url "https://github.com/${REPO}" \
  --token "$RUNNER_TOKEN" \
  --name "$(hostname)-local" \
  --labels "self-hosted,macOS" \
  --work "_work" \
  --unattended \
  --replace

echo ""
echo "第 4 步：安装为 launchd 服务（开机自启）..."
./svc.sh install
./svc.sh start

echo ""
echo "=============================="
echo " 安装完成！Runner 已在后台运行。"
echo ""
echo " 常用命令（在 $RUNNER_DIR 目录下执行）："
echo "   查看状态: ./svc.sh status"
echo "   停止:     ./svc.sh stop"
echo "   启动:     ./svc.sh start"
echo "   卸载服务: ./svc.sh uninstall"
echo "   前台运行（调试）: ./run.sh"
echo ""
echo " GitHub 上可以看到：https://github.com/${REPO}/settings/actions/runners"
echo "=============================="
