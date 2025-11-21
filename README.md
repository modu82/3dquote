# 3dquote · 加工报价小工具

一个用于 3D 打印、CNC 雕刻、激光雕刻/切割等工艺的轻量化报价工具。项目包含分离的前后端，以及可配置的材料/设备数据，方便独立迭代。

## 目录结构

```
3dquote/
├── backend/               # FastAPI 后端
│   ├── quote_api.py       # API 入口，加载配置与管理员认证
│   ├── models.py          # Pydantic 模型
│   ├── services.py        # 配置、账号读写与默认数据
│   └── config/            # 设备/材料/工艺/厂商配置（JSON）
├── frontend/              # 前端静态页面
│   ├── index.html         # 报价与管理界面
│   └── assets/
│       ├── main.js        # 业务逻辑（报价、分页、配置管理）
│       └── style.css      # 样式
├── docker-compose.yml
├── requirements.txt
└── .env                   # 服务端口等环境变量
```

## 功能亮点

- 按体积/重量计算材料成本，木材等体积采购材料基于体积（cm³→m³）计价，可用密度自动在重量/体积间互算。
- 独立的设备/材料/工艺 JSON 配置，新增工艺或厂商无需改代码，只需调整 `backend/config/*.json`。
- 管理页分栏+分页：全局参数、后处理、材料、设备分页面切换；材料和设备列表支持每页数量自定义。
- 管理员模式：登录后可在线调整配置、修改密码；配置持久化在 `/data/settings.json`。

## 快速开始

### 使用 Docker Compose
1. 准备 Docker 与 Docker Compose。
2. 根据需要修改 `.env`（端口、CORS 等）。
3. 运行：
   ```bash
   docker-compose up -d
   ```
   后端默认监听 `${API_PORT:-8000}`，配置文件挂载到 `./data`。
4. 打开 `frontend/index.html`（本地文件或任意静态服务器），如需远程接口可在浏览器控制台设置 `window.API_BASE` 覆盖默认 `http://localhost:8000/api`。

### 本地运行（无容器）
1. 安装依赖：`pip install -r requirements.txt`。
2. 启动服务：`uvicorn backend.quote_api:app --host 0.0.0.0 --port 8000`。
3. 同样在前端页面中将 `API_BASE` 指向实际服务地址。

### 配置文件
- `backend/config/materials.json`：材料列表，支持 `billingMethod` 为 `weight`(元/kg) 或 `volume`(元/m³)，可附带 `density`(g/cm³) 用于重量/体积互算。
- `backend/config/devices.json`：设备与小时成本。
- `backend/config/processes.json`：工艺枚举（前端下拉展示）。
- `backend/config/vendors.json`：预置厂商列表。

首次运行会将上述配置与环境变量生成的管理员账号落盘到 `/data` 目录，后续可通过管理界面修改并保存。
