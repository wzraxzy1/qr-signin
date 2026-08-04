# 动态二维码签到系统

## 功能特点

- **动态二维码**：二维码按设定间隔自动刷新，防止截图代签
- **可配置刷新间隔**：管理员可选 5秒 / 10秒 / 15秒
- **自定义签到字段**：管理员可设置签到者需提交的字段（姓名、手机号、部门等）
- **签到记录管理**：实时查看签到记录，支持 CSV 导出
- **防重复签到**：基于关键字段自动检测重复签到
- **过期令牌验证**：扫码后二维码过期则拒绝签到
- **签到时间窗口**：管理员可设置开始时间 / 停止时间（可选，留空=不限制）；未到开始时间显示「签到尚未开始」、超过停止时间显示「签到已结束」，后台强制拦截
- **手机端免登录拉取**：签到页通过公开接口 `GET /api/sessions/{id}/public` 加载表单，无需登录即可使用
- **登录认证**：管理面板需登录后才能访问
- **用户管理**：超级管理员可创建/编辑/删除用户、重置密码、分配角色
- **密码管理**：登录用户可在页头「修改密码」自助改密（需验证当前密码）；超级管理员可在用户管理中重置任意用户密码

## 默认账号

| 账号 | 密码 | 角色 |
|------|------|------|
| admin | admin123 | 超级管理员 |

> ⚠️ 部署后请立即修改默认密码！可在 Render 环境变量 `DEFAULT_ADMIN_PASSWORD` 设置初始密码，或登录后点击页头「修改密码」自助修改，也可在"用户管理"中由超管重置。

密码规则：至少 6 位；自助改密时新密码不能与当前密码相同。

角色说明：
- **超级管理员**：可管理用户（创建/编辑/删除/重置密码），可管理所有签到会话
- **管理员**：可管理签到会话，无用户管理权限

## 技术栈

- 后端：Python FastAPI + SQLite
- 前端：React 18 + Vite + qrcode.react
- 单体部署：FastAPI 同时提供 API 和静态文件服务

## 使用方法

### 启动系统

双击 `start.bat` 即可启动，浏览器自动打开 http://localhost:9000

### 管理员操作流程

1. **创建会话**：在管理面板点击「创建会话」
   - 填写会话名称（如"周一晨会签到"）
   - 选择二维码刷新间隔（5/10/15秒）
   - 配置签到字段（字段名、标签、类型、是否必填）

2. **显示二维码**：点击「显示二维码」进入 QR 展示页
   - 二维码自动按间隔刷新
   - 进度条显示当前剩余有效时间

3. **查看与导出**：点击「查看/导出」
   - 实时刷新签到记录
   - 统计签到人数
   - 导出 CSV 文件

### 签到者操作流程

1. 用手机扫描管理员屏幕上的二维码
2. 在打开的页面填写所需信息
3. 点击「确认签到」
4. 看到成功提示即完成

## 目录结构

```
qr-signin/
├── backend/
│   ├── app.py          # FastAPI 后端（API + 静态文件服务）
│   ├── requirements.txt
│   └── signin.db       # SQLite 数据库（自动生成）
├── frontend/
│   ├── src/
│   │   ├── App.jsx     # 路由配置
│   │   ├── main.jsx    # 入口
│   │   ├── styles.css  # 全局样式
│   │   └── components/
│   │       ├── AdminPanel.jsx   # 管理面板
│   │       ├── QRDisplay.jsx    # 二维码展示
│   │       └── SignInPage.jsx   # 签到页面
│   ├── package.json
│   ├── vite.config.js
│   └── dist/           # 构建产物（已构建）
└── start.bat           # 启动脚本
```

## 开发模式

如需修改前端代码：

```bash
cd frontend
npm install
npm run dev    # 开发服务器，API 代理到 localhost:8000
npm run build  # 重新构建到 dist/
```

后端开发：

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app:app --host 0.0.0.0 --port 9000 --reload
```

## Render 部署

### 方式一：Blueprint 部署（推荐）

1. 将 `qr-signin/` 目录推送到 GitHub 仓库
2. 登录 [Render Dashboard](https://dashboard.render.com)
3. 点击 **New** → **Blueprint**
4. 选择你的 GitHub 仓库，Render 会自动读取 `render.yaml` 配置
5. 点击 **Apply** 开始部署

### 方式二：手动部署

1. 在 Render 创建 **New Web Service** → 选择 GitHub 仓库
2. 配置：
   - **Runtime**: Python 3
   - **Build Command**: `bash build.sh`
   - **Start Command**: `cd backend && python -m uvicorn app:app --host 0.0.0.0 --port $PORT`
3. 添加环境变量：
   - `PYTHON_VERSION` = `3.12.10`
   - `NODE_VERSION` = `18.17.0`
4. 点击 **Create Web Service**

### 数据持久化

- **免费版（Free）**：SQLite 数据存在内存磁盘上，每次部署或重启后数据会被重置。适合临时演示和测试。
- **付费版（Starter $7/月）**：可挂载 1GB 持久磁盘，数据在部署/重启后保留。在 `render.yaml` 中取消注释 `disk` 配置即可。

### 访问方式

部署成功后，Render 会分配一个 URL（如 `https://qr-signin-xxxx.onrender.com`）：
- 管理面板：直接访问该 URL
- 签到二维码：URL 自动包含正确的域名，手机扫码即可打开签到页面
