# DEVGUIDE — 动态二维码签到系统 开发规范

> 本文档是团队的代码质量基线。所有 PR 必须对照「PR 门禁清单」自查。
> 目标：可维护、可测试、安全、可运维。由资深开发工程师维护。

---

## 1. 架构原则

- **后端当前为单体单文件 `backend/app.py`（852 行）**。这是最大的可维护性瓶颈。
  - 下一阶段必须拆分为 `backend/app/` 包：`routers/`（auth、sessions、signin）、`db.py`、`auth.py`、`schemas.py`、`models.py`。
  - 拆分前禁止继续往 `app.py` 堆功能；新功能一律以独立 router 形式提交，由资深开发合并时统一迁移。
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

11. 加 `.github/workflows/ci.yml`：push/PR 时跑 `pytest` + 前端 `npm run build`。
12. **PR 门禁清单（提交前自查）**：
    - [ ] 后端 `python -m py_compile` 通过；`pytest` 全绿
    - [ ] 前端 `npm run build` 通过
    - [ ] 无新增 SQL 字符串拼接（全部参数化）
    - [ ] 无敏感信息写入日志 / 提交（身份证号等）
    - [ ] 新接口在 `backend/app.py` 路由清单有注释说明
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
| P0 | 全仓 | 零自动化测试 | ✅ 已建 pytest 套件（test_security + test_signin，12 用例全绿，2026-08-04） |
| P1 | app.py:47-53 | CORS * + credentials 错误 | 待认领 |
| P1 | app.py:127-130 | SQLite 未开 WAL/busy_timeout | ✅ 已修（WAL + busy_timeout=10s，2026-08-04） |
| P1 | app.py:738-743 | 人数上限 TOCTOU 竞态 | 待认领 |
| P1 | app.py:748,819 | 身份证号明文落库/导出 | ✅ 已修（导出 CSV 对 id_card 脱敏，保留前4后4，2026-08-04） |
| P1 | app.py:310 | 登录无限流 | ✅ 已修（按用户名+来源IP双维度内存限流：5次/5分钟窗口，超限锁5分钟，2026-08-04） |
| P1 | app.py:198 | 默认管理员密码兜底 | 待认领 |
| P1 | 架构 | 单体 852 行未拆分 | 待认领 |
| P1 | CI | 无 PR 门禁 | 待认领（需加 .github/workflows/ci.yml） |
| P1 | 运维 | 无结构化日志 | 待认领 |
| P2 | app.py:109-116 | get_current_user 每次请求开 DB 连接 | 待认领 |
| P2 | schemas | field_data 无长度校验 | 待认领 |
