#!/usr/bin/env bash
# kb-manager 常用命令。用法：bash scripts/dev.sh <command>
#   vm-up     启动 VM 上的 kb-postgres / kb-redis
#   vm-down   停止容器（不删除数据）
#   vm-status 查看容器与端口
#   tunnel    建立反向代理隧道（VM 可通过 127.0.0.1:7890 访问外网）
#   backend   本机启动后端 :8000
#   frontend  本机启动前端 :5173
#   build     前端生产构建 + 后端测试
set -euo pipefail

VM_HOST="${VM_HOST:-root@192.168.100.66}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE="docker compose -f /opt/kb-manager/deploy/docker-compose.yml"

case "${1:-}" in
  vm-up)     ssh "$VM_HOST" "cd /opt/kb-manager/deploy && $COMPOSE up -d" ;;
  vm-down)   ssh "$VM_HOST" "cd /opt/kb-manager/deploy && $COMPOSE stop" ;;
  vm-status) ssh "$VM_HOST" "docker ps --filter name=kb- --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'" ;;
  tunnel)    ssh -f -N -o ExitOnForwardFailure=yes -R 7890:127.0.0.1:7890 "$VM_HOST" && echo "VM 代理已就绪：http://127.0.0.1:7890" ;;
  backend)   cd "$ROOT/backend" && uv run python run.py ;;
  frontend)  cd "$ROOT/frontend" && npm run dev ;;
  build)     cd "$ROOT/frontend" && npm run build && cd "$ROOT/backend" && uv run pytest ;;
  *)         sed -n '2,10p' "$0" ;;
esac
