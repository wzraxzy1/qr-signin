# DEVGUIDE — 动态二维码签到系统 开发规范

> 本文档是团队的代码质量基线。所有 PR 必须对照「PR 门禁清单」自查。
> 目标：可维护、可测试、安全、可运维。由资深开发工程师维护。

---

## 1. 架构原则

- **后端已拆分为 `backend/app/` 包**（2026-08-04 完成，原单体 `app.py` 930 行已拆除）。各文件单一职责：
  - `app/__init__.py` —— **门面/装配层**：仅创建 FastAPI 实例、配置 CORS、include_router 装配、挂载前端静态资源、启动时 `init_db()`；并重新导出测试所需函数（`init_db`/`get_db`/`hash_password` 等），保证 `import app` 对外契约不变。
  - `app/config.py` —— 配置单一来源（SECRET_KEY 生产强制校验、DB 路径、前端产物路径、限流/token 常量）。
  - `app/crypto.py` —— **纯函数层**：密码哈希、token 签发/校验（仅依赖 SECRET_KEY，不碰 DB，便于单测）。
  - `app/db.py` —— SQLite 连接（WAL + busy_timeout）与 `init_db`（建表/迁移/播种超管）。
  - `app/auth_utils.py` —— 认证依赖（`get_current_user`/`require_super_admin`）、登录限流、身份证脱敏、QR token 轮转。
  - `app/schemas.py` —— Pydantic 请求/响应模型。
  - `app/routers/` —— 按业务域拆分：`auth.py`（登录/当前用户）、`users.py`（用户管理+自助改密）、`sessions.py`（会话 CRUD/QR/公开/记录/导出）、`signin.py`（公开签到提交，单独成文件以突出其无需登录的安全边界）。
  - **循环依赖规避**：`db.py` 需要 `hash_password` 而不反向依赖 `auth_utils`，故把纯密码/token 函数抽到独立的 `crypto.py`，打破 `db ↔ auth_utils` 环。
  - **启动契约不变**：部署仍用 `uvicorn app:app`（`app` 即 `app/__init__.py` 导出的 FastAPI 实例）。新增/修改路由一律在对应 `routers/*.py` 内以 `APIRouter` 形式提交，禁止再出现巨型单体文件。
- **前后端同域部署**：前端 `API='/api'` 为相对路径，正确。不要改回写死 `http://localhost:8000`。
- 静态资源由 FastAPI 托管（`FRONTEND_DIST`），无独立前端服务器。

## 2. 安全基线（P0/P1 必须修）

1. **SECRET_KEY 禁止有默认兜底**（`app.py:26` 当前有硬编码默认值）。
   - 生产环境必须 `export SECRET_KEY=...`，缺失则启动失败，绝不回退到公开可猜的默认值。
   - 部署脚本已生成随机 SECRET_KEY 到 `.secret_key`，保持。
2. **CORS 配置错误**（`app.py:47-53`）：`allow_origins=["*"]` + `allow_credentials=True` 组合既无效又危险。
   - 同域部署场景**直接删除 CORS 中间件**。如需跨域，显式列出白名单域名。
3. **身份证号等敏感 PII 明文落库 + 明文导出**：`field_data` JSON 与 CSV 导出含身份证号（`app.py:748,819`）。
   - 遵守《个人信息保护法》：导出 CSV 时对身份证号做掩码（如 `3301**********1234`）；禁止写入日志。
4. **登录接口无频率限制**（`app.py:310`）：`/api/auth/login` 可被暴力破解（默认密码 `admin123`）。
   - 加失败计数 / 限流（如 5 次/分钟封 5 分钟）；首次登录强制改密。
5. **默认管理员密码写死在代码兜底**（`app.py:198`）：仅允许通过环境变量 `DEFAULT_ADMIN_PASSWORD` 注入，代码内不留默认明文。

## 3. 数据完整性 / 并发（P1）

6. **SQLite 必须开启 WAL + busy_timeout**（`get_db`，`app.py:127-130`）：
   ```python
   conn = sqlite3.connect(DB_PATH, timeout=5)
   conn.execute("PRAGMA journal_mode=WAL")
   conn.execute("PRAGMA busy_timeout=5000")
   conn.row_factory = sqlite3.Row
   ```
   uvicorn 默认多线程，不加会出现间歇性 `database is locked`。
7. **人数上限存在 TOCTOU 竞态**（`app.py:738-743`）：`COUNT` 与 `INSERT` 之间并发请求可超额。
   - 修复：在事务内 `BEGIN IMMEDIATE` 写锁，或单条 `INSERT ... WHERE (SELECT COUNT(*)) < max_signins`。
8. SQL 一律参数化（当前已做到，保持）。`field_data` 的 key 虽拼入 `json_extract(field_data, ?)` 但作为绑定值传入，安全；后续重构需保持此模式。

## 4. 可测试性（P0 团队级）

9. **当前零自动化测试**。每次改动靠手测 + 临时脚本（已删），不可持续。
   - 必须引入 `pytest` + `pytest-asyncio`，对以下逻辑写单测：
     - `submit_signin`：复合键去重、强唯一字段去重、人数上限、时间窗口（`start_at`/`expires_at`）、token 过期。
     - `verify_token` / `create_token`：签名校验、过期、`password_version` 失效。
     - `hash_password` / `verify_password`：恒定时间比较、salt 随机。
10. 测试数据库用临时文件（`tempfile`），不碰生产 `signin.db`。

## 5. CI / PR 门禁（P1）

11. ✅ 已建 `.github/workflows/ci.yml`：push/PR 自动跑两个 job——`backend-tests`（`pip install -r requirements` + `pytest`，`APP_ENV=test` 用临时 DB 隔离）与 `frontend-build`（`npm ci` + `vite build`）。任一失败即阻断合并/部署。
12. **PR 门禁清单（提交前自查）**：
    - [ ] 后端 `python -m py_compile` 通过；`pytest` 全绿
    - [ ] 前端 `npm run build` 通过
    - [ ] 无新增 SQL 字符串拼接（全部参数化）
    - [ ] 无敏感信息写入日志 / 提交（身份证号等）
    - [ ] 新接口在 `backend/app/routers/` 对应文件内实现，并在 PR 描述说明
    - [ ] 破坏性 DB 变更走 `init_db` 的 `ALTER TABLE ... try/except` 迁移，向后兼容

## 6. 可运维性（P1）

13. **无结构化日志**：`app.py` 全程靠抛 `HTTPException`，无访问/签到事件日志。
    - 引入 `logging`，输出 JSON 或带时间戳的文本；关键事件（登录成功/失败、签到成功、去重拦截、超额拦截）必须留痕，便于审计与排查。
14. 保留 `/api/health` 健康检查（已存在，`app.py:471`）。

## 7. 前端约定

15. 所有鉴权请求走 `auth.js` 的 axios 拦截器（自动带 Bearer、401 跳转），**禁止** `window.open` 直接打受保护接口（已踩坑修复导出）。
16. 服务端错误用统一 toast；组件内 `try/catch` 仅做本地状态处理，不吞掉错误。
17. 管理面板「时间窗口 / 人数上限」等设置项改完必须 `PUT` 回后端并 `onBack` 刷新，不留前端-only 状态。

---

## 当前已知缺陷清单（按优先级）

| 优先级 | 位置 | 问题 | 状态 |
|---|---|---|---|
| P0 | app.py:26 | SECRET_KEY 硬编码默认 | ✅ 已修（生产强制校验+开发临时密钥，2026-08-04） |
| P0 | config.py:36 | FRONTEND_DIST 路径少往上一层，SPA 路由全没注册，GET / 404 | ✅ 已修（_project_root = grandparent of config.py；显式 @app.get("/") 根路由；test_spa.py 回归，2026-08-05） |
| P0 | 全仓 | 零自动化测试 | ✅ 已建 pytest 套件（test_security + test_signin，12 用例全绿，2026-08-04） |
| P1 | app.py:47-53 | CORS * + credentials 错误 | ✅ 已修（`allow_origins` 改为显式来源列表，禁止 `*` 与 credentials 共用，2026-08-05） |
| P1 | app.py:127-130 | SQLite 未开 WAL/busy_timeout | ✅ 已修（WAL + busy_timeout=10s，2026-08-04） |
| P1 | app.py:738-743 | 人数上限 TOCTOU 竞态 | 待认领 |
| P1 | app.py:748,819 | 身份证号明文落库/导出 | ✅ 已修（导出 CSV 对 id_card 脱敏，保留前4后4，2026-08-04） |
| P1 | app.py:310 | 登录无限流 | ✅ 已修（按用户名+来源IP双维度内存限流：5次/5分钟窗口，超限锁5分钟，2026-08-04） |
| P1 | app.py:198 | 默认管理员密码兜底 | ✅ 已修（禁止回退 `admin123`；未设 `DEFAULT_ADMIN_PASSWORD` 时生成一次性随机密码并写入启动日志，不再拒绝启动，2026-08-05） |
| P1 | 架构 | 单体 852 行未拆分 | ✅ 已拆为 `backend/app/` 包（config/crypto/db/auth_utils/schemas/routers + 门面 `__init__.py`，2026-08-04） |
| P1 | CI | 无 PR 门禁 | ✅ 已建 .github/workflows/ci.yml（push/PR 自动跑 pytest + 前端 build，2026-08-04） |
| P1 | 运维 | 无结构化日志 | 待认领 |
| P2 | app.py:109-116 | get_current_user 每次请求开 DB 连接 | 待认领 |
| P2 | schemas | field_data 无长度校验 | 待认领 |
| P1 | signin | 签到后返回上一页可重复签到（匿名表单无去重；前端无防重） | ✅ 已修（匿名表单同 token 单次使用 + 前端 localStorage「已签到」守卫，2026-08-05） |

---

## 8. 日常操作指引（如何新增接口 / 部署）

### 8.1 新增一个后端接口（标准流程）
1. 判断归属：认证相关 → `routers/auth.py`；用户管理 → `routers/users.py`；会话/记录/导出 → `routers/sessions.py`；公开签到 → `routers/signin.py`。
2. 在该文件顶部已有 `router = APIRouter()`，直接加装饰器即可，例如：
   ```python
   @router.get("/api/sessions/{session_id}/something")
   async def something(session_id: str, user: dict = Depends(get_current_user)):
       ...
   ```
3. 需要 DB：从 `..db` 导入 `get_db`；需要鉴权：`from ..auth_utils import get_current_user, require_super_admin`；纯密码/token：从 `..crypto` 导入。
4. `__init__.py` 已经 `include_router`，**无需手动注册**——只要写在 routers 文件里，路由自动生效。
5. 加对应 pytest（参照 `tests/test_signin.py` 的 `_login`/`_create_session`/`_submit` 辅助函数）。
6. 跑 `python -m pytest -q` 与 `npm run build` 确认绿，再提交。

### 8.2 本地启动
```bash
cd backend
# 方式一（推荐，等价原 python app.py）
python -m uvicorn app:app --host 0.0.0.0 --port 8000
# 方式二
python -m app
```

### 8.3 部署到腾讯云（后端改动无需重打前端）
```bash
# 在服务器上（SSH 后）
cd /opt/qr-signin
git pull
sudo systemctl restart qr-signin
# 查看状态
systemctl status qr-signin
```
> 注意：如果改了 `frontend/`（前端）才需要 `cd frontend && npm run build` 重新构建；纯后端改动只 restart 服务即可，因为 `uvicorn app:app` 启动契约保持不变。

#### 8.3.1 生产必填 / 可选环境变量
- `SECRET_KEY`（必填，生产）：token 签名密钥，缺失则**拒绝启动**。用 `python -c "import secrets;print(secrets.token_hex(32))"` 生成。
- `DEFAULT_ADMIN_PASSWORD`（可选；生产建议设）：首次启动播种超管的初始密码。未设置时**不再回退 `admin123`**，而是生成一次性随机密码并打印到启动日志（仅显示一次），请在管理面板尽快修改。
- `DEFAULT_ADMIN_USER`（可选，默认 `admin`）：超管用户名。
- `CORS_ORIGINS`（可选，逗号分隔）：允许跨域访问的前端来源。同源部署（SPA 由本后端挂载）无需设置；仅当浏览器从**不同域名/端口**直连 API 时才需填写，例如 `https://app.example.com,http://localhost:5173`。**切勿设成 `*`**（与 `allow_credentials=True` 冲突，浏览器会拒绝）。
- `APP_ENV`（可选，默认 `development`）：设为 `production` 时启用上述强制校验；CI/测试用 `test`。

> 已上线的旧实例若当初用的是默认 `admin123`，请尽快在管理面板修改超管密码（新代码只约束「全新首次播种」，不会自动改已有账户）。

### 8.4 常见部署坑（踩过即记，下次直接查表）

#### 坑 1：本地 8000 端口被旧 uvicorn 占用（改了代码但新接口一直 404）
**现象**：改完 `routers/` 后本地起服务，请求新接口返回 `404`，但代码明明已经写好。
**根因**：上一次启动的 uvicorn 进程还活着，新的服务根本没起来（或起在了别的端口），请求打到的还是旧进程。Windows 上会直接报 `OSError: [WinError 10048] 通常每个套接字地址只允许使用一次`。
**排查 / 修复（Windows PowerShell）**：
```powershell
# 查谁占了 8000
$pid = (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue).OwningProcess
if ($pid) { Stop-Process -Id $pid -Force; Start-Sleep 1 }
# 再用 --reload 起，代码改动会自动重载，不用反复手动重启
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```
**Linux 服务器同理**：
```bash
pkill -f "uvicorn app:app"; sleep 1
sudo systemctl restart qr-signin
```
**防呆**：本地开发一律加 `--reload`；部署后改完代码必须 `restart`，否则新接口永远 404。

#### 坑 2：服务器重启后 `Failed to restart qr-signin.service: Unit qr-signin.service not found`
**现象**：`sudo systemctl restart qr-signin` 报 `Unit qr-signin.service not found`，服务根本没注册。
**根因**：systemd 的 unit 文件 `/etc/systemd/system/qr-signin.service` 从未创建（或机器重装/迁移后丢失）。
**修复（SSH 到服务器后执行）**：
```bash
sudo tee /etc/systemd/system/qr-signin.service > /dev/null <<'EOF'
[Unit]
Description=QR Sign-in Backend
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/qr-signin/backend
Environment=PYTHONUNBUFFERED=1
Environment=SECRET_KEY=$(cat /opt/qr-signin/.secret_key 2>/dev/null)
ExecStart=/opt/qr-signin/venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable qr-signin
sudo systemctl restart qr-signin
# 验证
curl -s http://localhost:8000/api/health   # 期望 {"status":"ok"}
systemctl status qr-signin
```
> 注：`WorkingDirectory` 与 `ExecStart` 里的路径要和服务器实际目录一致；`SECRET_KEY` 走 `.secret_key` 文件，生产环境缺失会直接启动失败（见 `app/config.py` 的强制校验）。

#### 坑 3：服务跑着、`/api/health` 也是 200，但浏览器打开首页全空白/404
**现象**：服务正常（`curl /api/health` → `{"status":"ok"}`），但访问 `http://<服务器>:8000/` 或浏览器打开页面是空白或 404。**API 能调但 SPA 打不开**。
**根因**（任一即可触发）：
1. `FRONTEND_DIST` 路径错（`config.py` 的 `_project_root` 少往上一层）→ 找不到 `frontend/dist`，SPA 路由压根不注册，所有非 API 路径全 404。
2. 只有 `@app.get("/{full_path:path}")` 而没有显式的 `@app.get("/")` → 首页空路径不匹配，404（`path` 转换器要求至少一个字符）。
3. 服务器/本地没构建前端：`frontend/dist/` 不存在。
**排查**：
```bash
# 在服务器上
ls /opt/qr-signin/frontend/dist/index.html    # 必须存在；否则 cd frontend && npm run build
curl -sI http://localhost:8000/                # 期望 200 + Content-Type: text/html
```
**修复**：
- 修代码：`config._project_root` 取 `grandparent(config.py)`；`__init__.py` 显式注册 `@app.get("/")`。
- 服务器构建：`cd /opt/qr-signin/frontend && npm run build`（看 deploy 脚本是否已包含）。
- 验证：`curl -s http://localhost:8000/` 首行应是 `<!DOCTYPE html>` 或 `<html`。
