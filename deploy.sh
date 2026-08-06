#!/usr/bin/env bash
#
# QR 签到系统 · 一键部署 + 四件套自动核对
# 用法（在服务器 /opt/qr-signin 目录或任意位置，需有 sudo 权限）：
#   bash deploy.sh
#
# 脚本会依次：拉代码 → 装后端依赖 → 构建前端 → 重启服务 → 打印核对结果。
# 任一关键步骤失败会立即退出并提示，不会带病继续。
#
set -euo pipefail

PROJECT_DIR="/opt/qr-signin"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"
VENV_PIP="$PROJECT_DIR/venv/bin/pip"
PORT="${PORT:-8000}"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✅ $1${NC}"; }
bad()  { echo -e "${RED}❌ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $1${NC}"; }

echo "=================================================="
echo " QR 签到系统 部署脚本"
echo " 项目目录: $PROJECT_DIR"
echo "=================================================="

# 0. 进入项目目录
if [ ! -d "$PROJECT_DIR" ]; then
  bad "项目目录 $PROJECT_DIR 不存在，请确认路径"
  exit 1
fi
cd "$PROJECT_DIR"

# 1. 拉取最新代码（腾讯云直连 GitHub 不稳时，服务器应已配好 SSH-over-443 远程）
echo ""
echo ">>> [1/5] git pull"
if ! git pull; then
  bad "git pull 失败。若直连 GitHub 超时，请确认远程是否为 ssh://git@ssh.github.com:443/...（SSH over 443）。"
  exit 1
fi
ok "代码已更新到：$(git log -1 --oneline)"

# 2. 后端依赖
echo ""
echo ">>> [2/5] 安装后端依赖"
cd "$BACKEND_DIR"
if [ -f "$VENV_PIP" ]; then
  "$VENV_PIP" install -r requirements.txt
else
  warn "未找到 venv pip（$VENV_PIP），尝试系统 pip"
  pip install -r requirements.txt
fi
ok "后端依赖就绪"

# 3. 构建前端
echo ""
echo ">>> [3/5] 构建前端"
cd "$FRONTEND_DIR"

# 腾讯地图 key 注入（构建期环境变量 VITE_TMAP_KEY）
# 地图点选功能依赖它；未提供则前端自动降级为手动填经纬度（GCJ-02）。
# 用法：VITE_TMAP_KEY="你的key" bash deploy.sh
if [ -n "${VITE_TMAP_KEY:-}" ]; then
  printf 'VITE_TMAP_KEY=%s\n' "$VITE_TMAP_KEY" > "$FRONTEND_DIR/.env"
  ok "已写入腾讯地图 key 到 frontend/.env（首4位: ${VITE_TMAP_KEY:0:4}***，已 gitignore 不会提交）"
elif [ -f "$FRONTEND_DIR/.env" ] && grep -q '^VITE_TMAP_KEY=' "$FRONTEND_DIR/.env"; then
  ok "沿用 frontend/.env 中已有的腾讯地图 key"
else
  warn "未提供 VITE_TMAP_KEY：前端将降级为「手动填 GCJ-02 经纬度」，无地图点选。如需地图点选，运行：VITE_TMAP_KEY=你的key bash deploy.sh"
fi

npm install
npm run build
ok "前端构建完成"

# 4. 重启服务
echo ""
echo ">>> [4/5] 重启 systemd 服务"
sudo systemctl restart qr-signin
sleep 2   # 给服务一点启动时间

# 5. 四件套核对
echo ""
echo ">>> [5/5] 部署核对（四件套）"
echo "--------------------------------------------------"

# 件1：提交号
COMMIT=$(git -C "$PROJECT_DIR" log -1 --format=%H)
COMMIT_SHORT=$(git -C "$PROJECT_DIR" log -1 --oneline)
echo "① 提交号: $COMMIT_SHORT"

# 件2：构建产物 js hash
BUILD_JS=$(ls "$FRONTEND_DIR"/dist/assets/*.js 2>/dev/null | head -1 | xargs -r basename)
if [ -n "$BUILD_JS" ]; then
  ok "② 构建产物: $BUILD_JS"
else
  bad "② 未找到前端构建产物，npm run build 可能失败"
fi

# 件3：后端实际引用的 js hash（绕过浏览器缓存的关键）
# 兼容直连 uvicorn 与 nginx 反代两种部署：依次尝试多个端口
fetch_index_js() {
  for p in "${TRY_PORTS[@]}"; do
    local html
    html=$(curl -s --max-time 3 "http://localhost:$p/" || true)
    local js
    js=$(echo "$html" | grep -o 'index-[A-Za-z0-9_-]*\.js' | head -1 || true)
    if [ -n "$js" ]; then
      SERVED_VIA_PORT="$p"
      echo "$js"
      return 0
    fi
  done
  return 1
}

TRY_PORTS=(8000 80)
SERVED_VIA_PORT=""
if SERVED_JS=$(fetch_index_js); then
  ok "③ 后端引用: $SERVED_JS (via 端口 $SERVED_VIA_PORT)"
else
  warn "③ 未从首页抓到 index-*.js 引用（尝试过 ${TRY_PORTS[*]} 端口，均无果）"
fi

# 件3 自动比对：构建 vs 实际引用
if [ -n "$BUILD_JS" ] && [ -n "$SERVED_JS" ]; then
  if [ "$BUILD_JS" = "$SERVED_JS" ]; then
    ok "   构建 hash 与 后端引用 hash 一致 ✅（新代码已真正 serve）"
  else
    bad "   构建 hash($BUILD_JS) ≠ 后端引用($SERVED_JS) —— 服务可能没真正重启或 dist 未刷新！"
  fi
fi

# 件4：健康检查（双端口 fallback，避免打到 nginx 80 拿 404）
HEALTH=""
HEALTH_VIA_PORT=""
for try_port in 8000 80; do
  HEALTH=$(curl -s --max-time 3 "http://localhost:$try_port/api/health" || true)
  if echo "$HEALTH" | grep -q '"status" *: *"ok"'; then
    HEALTH_VIA_PORT="$try_port"
    break
  fi
done

if [ -n "$HEALTH_VIA_PORT" ]; then
  ok "④ /api/health (port $HEALTH_VIA_PORT): $HEALTH"
  # 如果 8000 端口不通、仅 nginx 80 通，给个温馨提示
  if [ "$HEALTH_VIA_PORT" != "8000" ]; then
    warn "   nginx 反代似乎没配 /api/ → uvicorn 的 proxy_pass，建议加 location /api/ { proxy_pass http://127.0.0.1:8000; }"
  fi
else
  bad "④ /api/health 异常: 8000/80 都未返回 ok"
fi

# 件5：进程状态
if systemctl is-active --quiet qr-signin; then
  ok "⑤ systemctl: active (running)"
else
  bad "⑤ systemctl: 非 active，请执行 journalctl -u qr-signin -n 50 排查"
fi

# 件6：腾讯地图 key（决定能否地图点选，还是降级手动填经纬度）
if [ -f "$FRONTEND_DIR/.env" ] && grep -q '^VITE_TMAP_KEY=' "$FRONTEND_DIR/.env"; then
  MAP_VAL=$(grep '^VITE_TMAP_KEY=' "$FRONTEND_DIR/.env" | head -1 | cut -d= -f2-)
  MAP_MASK="${MAP_VAL:0:4}***（共 ${#MAP_VAL} 位）"
  ok "⑥ 腾讯地图 key: 已配置（${MAP_MASK}）→ 管理后台可用地图点选+拖拽半径"
else
  warn "⑥ 腾讯地图 key: 未配置 → 仅手动填 GCJ-02 经纬度；要地图点选请 VITE_TMAP_KEY=你的key bash deploy.sh"
fi

echo "--------------------------------------------------"
echo "部署流程结束。"
warn "最后一步：在微信/浏览器打开签到页，按 Ctrl+Shift+R（Mac: Cmd+Shift+R）强刷，清掉旧 JS 缓存。"
echo "=================================================="
