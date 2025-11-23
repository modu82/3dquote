# 3dquote · 加工报价小工具

一个用于 3D 打印、CNC 雕刻、激光雕刻/切割等工艺的轻量化报价工具。项目包含：

- **纯前端单页**（`3d_quote.html`）：输入模型信息，调用后端获取材料/设备配置，计算报价并展示结果。
- **FastAPI 后端**（`quote_api.py`）：提供报价配置读取/写入接口、管理员登录及密码修改接口。
- **Docker 支持**：`docker-compose.yml` 帮助快速启动后端并持久化配置。

---

## 功能亮点

- 💰 按体积/时间自动估算成本与报价，支持单件最低价与开机费。
- 🧵 支持多种工艺与厂商：FDM/光固化 3D 打印、CNC 雕刻、CO₂ 激光雕刻/切割等，可按厂商和工艺分类材料、设备。
- ⚙️ 细致的成本参数：材料单价、设备小时费用、电费、人工/管理成本、人机比等。
- 🧩 后处理规则：按重量/件数估算打磨、上色等额外耗时与成本，可按工艺区分并设置成本系数。
- 🔐 管理员模式：登录后可在线调整配置、修改密码；配置信息与管理员账号保存在 `./data/` 目录。

---

## 项目结构

```text
3dquote/
├── 3d_quote.html      # 前端页面：表单输入 + 报价结果展示 + 调用后端 API
├── quote_api.py       # FastAPI 后端：报价配置读取/写入、管理员登录、密码修改
└── docker-compose.yml # Docker 启动配置，挂载代码和数据目录
```

---

## 快速开始

### 方式一：使用 Docker Compose（推荐）
1. 确保已安装 Docker 与 Docker Compose。
2. 在项目根目录执行：
   ```bash
   docker-compose up -d
   ```
   后端会在 `0.0.0.0:8000` 启动，配置文件保存在 `./data/`。
3. 打开 `3d_quote.html`，将文件中 `const API_BASE = "http://10.1.1.21:8000/api";` 修改为实际后端地址（例如 `http://localhost:8000/api`），然后在浏览器直接打开该 HTML 文件或用任意静态服务器访问。

### 方式二：本地运行 Python 服务
1. 准备 Python 3.11+。
2. 安装依赖并启动：
   ```bash
   pip install fastapi uvicorn
   uvicorn quote_api:app --host 0.0.0.0 --port 8000
   ```
3. 同样在 `3d_quote.html` 内将 `API_BASE` 指向你的后端地址。

> 可通过环境变量 `ADMIN_USER` 和 `ADMIN_PASS` 调整默认管理员账号（默认 `admin / changeme`）。首次启动时会在 `./data/admin_account.json` 中生成账号文件，后续修改需删除该文件或使用管理员界面改密。

---

## API 概览

- `GET /api/settings`：公开获取当前报价配置（材料、设备、利润率、后处理规则等）。
- `POST /api/settings`：更新报价配置，需在请求头携带 `X-Admin-Session`。
- `POST /api/admin/login`：管理员登录，返回 `token`，后续请求需放入 `X-Admin-Session` 头。
- `POST /api/admin/logout`：注销当前会话。
- `GET /api/admin/status`：查询 session 是否有效。
- `POST /api/admin/change-password`：修改管理员密码，需有效会话并提供旧密码。
- `POST /api/quotes`：保存一次报价记录，便于后续统计（对所有用户开放）。
- `GET /api/quotes`：管理员查看报价记录，支持分页与按月份筛选。
- `GET /api/quotes/summary`：管理员查看按月汇总的报价数量与金额。

配置持久化文件位于 `./data/settings.json` 与 `./data/admin_account.json`，可备份或通过 Docker 卷挂载到其他路径。

---

## 使用小贴士

- 前端页面默认填充了演示材料、设备和后处理参数，访问时会尝试从后端 `/api/settings` 读取最新配置。
- 通过页面右上角的“管理员登录”按钮输入凭证后，可在“参数配置”区域增删材料/设备、调整利润率和后处理规则；保存会调用 `POST /api/settings`。
- 如需在局域网部署，请确保浏览器能访问后端地址并相应更新 `API_BASE`。

