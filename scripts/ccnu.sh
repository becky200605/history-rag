#!/usr/bin/env bash
set -euo pipefail

# Uses the current network/VPN route to the server; credentials stay in SSH.
SERVER="root@10.222.10.21"
CONTROL_PATH="$HOME/.ssh/history-rag-ccnu-%C"
SSH_OPTIONS=(
  -p 22
  -o ConnectTimeout=10
  -o ConnectionAttempts=1
  -o ServerAliveInterval=30
  -o ServerAliveCountMax=3
  -o StrictHostKeyChecking=ask
  -o ControlMaster=auto
  -o ControlPersist=15m
  -o "ControlPath=$CONTROL_PATH"
)

usage() {
  cat <<'HELP'
用法：
  ./scripts/ccnu.sh                    打开服务器终端
  ./scripts/ccnu.sh status             查看负载、磁盘和 Docker 状态
  ./scripts/ccnu.sh logs gateway       跟踪服务日志（Ctrl+C 退出）
  ./scripts/ccnu.sh run 'docker ps -a'  执行一条远程命令
  ./scripts/ccnu.sh close              关闭复用连接

日志服务：frontend、gateway、langgraph、nginx、mysql、qdrant。
首次连接按 SSH 提示登录；空闲连接保留 15 分钟，期间复用登录。
需要本机网络/VPN能访问 10.222.10.21:22；脚本不保存密码。
HELP
}

action="${1:-shell}"
if [[ $# -gt 0 ]]; then shift; fi
case "$action" in
  help|-h|--help)
    usage
    exit 0
    ;;
  shell|status|close)
    [[ $# -eq 0 ]] || { usage >&2; exit 2; }
    ;;
  logs)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    case "$1" in
      frontend|gateway|langgraph|nginx|mysql) container="history-rag-prod-$1-1" ;;
      qdrant) container=qdrant ;;
      *) usage >&2; exit 2 ;;
    esac
    ;;
  run)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    ;;
  *) usage >&2; exit 2 ;;
esac

umask 077
mkdir -p "$HOME/.ssh"
case "$action" in
  shell)
    exec ssh "${SSH_OPTIONS[@]}" "$SERVER"
    ;;
  status)
    exec ssh "${SSH_OPTIONS[@]}" "$SERVER" 'hostname
uptime
free -h
df -h /
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
docker stats --no-stream'
    ;;
  logs)
    exec ssh "${SSH_OPTIONS[@]}" "$SERVER" "docker logs --timestamps --tail 100 -f $container"
    ;;
  run)
    exec ssh "${SSH_OPTIONS[@]}" "$SERVER" "$1"
    ;;
  close)
    exec ssh "${SSH_OPTIONS[@]}" -O exit "$SERVER"
    ;;
esac
