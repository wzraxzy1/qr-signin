#!/bin/bash
# ============================================================
# 腾讯云一键部署脚本：二维码签到系统 (FastAPI + React)
# 适用于 腾讯云轻量应用服务器 / CVM (Linux)
#
# 用法：
#   1) 仅用 公网IP:端口 访问（最简单）：
#        sudo bash deploy_tencent.sh
#   2) 绑定域名并启用 HTTPS（自动申请免费证书）：
#        sudo DOMAIN=sign.example.com EMAIL=you@example.com bash deploy_tencent.sh
#
# 说明：
#   - 腾讯云磁盘持久化，SQLite 直接落盘，无需额外挂载磁盘。
#   - 自动安装 Python3 + Node18 + Nginx，拉取代码、构建前端、配置 systemd 开机自启。
#   - 申请免费 Let's Encrypt 证书需要域名已解析到本服务器公网 IP。
# ============================================================
set -e

APP_NAME="qr-signin"
APP_DIR="${APP_DIR:-/opt/$APP_NAME}"
REPO_URL="https://github.com/wzraxzy1/qr-signin.git"
APP_USER="qrsignin"
PORT="${PORT:-8000}"
DOMAIN="${DOMAIN:-}"
EMAIL="${EMAIL:-}"

if [ "$EUID" -ne 0 ]; then
  echo "请使用 root 运行： sudo bash $0" >&2
  exit 1
fi

echo "==> 检测系统 / 包管理器"
. /etc/os-release
if command -v apt-get >/dev/null 2>&1; then PKG=apt
elif command -v dnf >/dev/null 2>&1; then PKG=dnf
elif command -v yum >/dev/null 2>&1; then PKG=yum
else echo "不支持的发行版，请手动部署" >&2; exit 1
fi
echo "系统: $PRETTY_NAME | 包管理器: $PKG"

echo "==> 安装系统依赖 (git/python3/nginx)"
if [ "$PKG" = "apt" ]; then
  apt-get update -y
  apt-get install -y git curl python3 python3-venv python3-pip nginx
elif [ "$PKG" = "dnf" ]; then
  dnf install -y -q git curl python3 python3-pip nginx
elif [ "$PKG" = "yum" ]; then
  yum install -y git curl python3 python3-pip nginx
fi

# Python 解释器（优先 3.12，否则系统 python3）
PYBIN="$(command -v python3.12 || command -v python3)"
echo "Python: $($PYBIN --version 2>&1) ($PYBIN)"

# Node 18（仅用于构建前端；已存在则跳过）
if command -v node >/dev/null 2>&1; then
  echo "Node 已存在: $(node --version)"
else
  echo "==> 安装 Node 18"
  if [ "$PKG" = "apt" ]; then
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
    apt-get install -y nodejs
  else
    curl -fsSL https://rpm.nodesource.com/setup_18.x | bash -
    $PKG install -y nodejs
  fi
fi

echo "==> 获取代码"
if [ -f "$APP_DIR/backend/app.py" ]; then
  echo "检测到 $APP_DIR，执行 git pull 更新"
  git -C "$APP_DIR" pull --ff-only || true
else
  git clone "$REPO_URL" "$APP_DIR"
fi

echo "==> 创建运行用户 $APP_USER"
id -u "$APP_USER" >/dev/null 2>&1 || useradd -r -s /usr/sbin/nologin "$APP_USER"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "==> 安装后端依赖 (venv)"
VENV="$APP_DIR/venv"
if [ ! -d "$VENV" ]; then "$PYBIN" -m venv "$VENV"; fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$APP_DIR/backend/requirements.txt"

echo "==> 构建前端"
if [ -d "$APP_DIR/frontend/dist" ]; then
  echo "dist 已存在，跳过构建"
else
  ( cd "$APP_DIR/frontend" && npm install && npm run build )
fi

echo "==> 生成 SECRET_KEY（仅首次）"
SECRET_KEY_FILE="$APP_DIR/.secret_key"
if [ ! -f "$SECRET_KEY_FILE" ]; then
  python3 -c "import secrets; print(secrets.token_hex(32))" > "$SECRET_KEY_FILE"
fi
chown "$APP_USER:$APP_USER" "$SECRET_KEY_FILE"
chmod 600 "$SECRET_KEY_FILE"
SECRET_KEY="$(cat "$SECRET_KEY_FILE")"

echo "==> 写入 systemd 服务"
cat > "/etc/systemd/system/${APP_NAME}.service" <<EOF
[Unit]
Description=QR Sign-in System
After=network.target

[Service]
User=${APP_USER}
WorkingDirectory=${APP_DIR}/backend
Environment=PORT=${PORT}
Environment=SECRET_KEY=${SECRET_KEY}
ExecStart=${VENV}/bin/uvicorn app:app --host 0.0.0.0 --port ${PORT}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$APP_NAME"
systemctl restart "$APP_NAME"

if [ -n "$DOMAIN" ]; then
  echo "==> 配置 Nginx + HTTPS ($DOMAIN)"
  if [ "$PKG" = "apt" ]; then
    apt-get install -y certbot python3-certbot-nginx
  else
    $PKG install -y certbot
  fi
  cat > "/etc/nginx/conf.d/${APP_NAME}.conf" <<EOF
server {
    listen 80;
    server_name ${DOMAIN};
    location / {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
  systemctl enable nginx
  systemctl restart nginx
  if [ -n "$EMAIL" ]; then
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" \
      || echo "⚠️ 证书申请失败，请确认域名已解析到本机公网 IP 后手动运行：certbot --nginx -d $DOMAIN"
  fi
  echo "✅ 部署完成，访问： https://$DOMAIN"
else
  echo "✅ 部署完成，访问： http://<服务器公网IP>:$PORT"
  echo "   ⚠️ 记得在腾讯云控制台开放 $PORT 端口（轻量应用服务器→防火墙 / CVM→安全组）"
fi

echo "==> 查看运行状态： systemctl status $APP_NAME"
