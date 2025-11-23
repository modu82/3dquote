from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Literal
from datetime import datetime
import json
import os
import hashlib
import secrets
from uuid import uuid4

app = FastAPI()

# CORS：内网工具，先放开；如果后面挂到域名，可以改成具体 origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],     # 需要更严格控制时改成 ["https://yourdomain.com"]
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

SETTINGS_FILE = "/data/settings.json"
ACCOUNT_FILE = "/data/admin_account.json"
USER_ACCOUNT_FILE = "/data/user_account.json"
QUOTES_FILE = "/data/quotes.json"

# 初始管理员信息（如果 ACCOUNT_FILE 不存在，就用这个创建）
DEFAULT_ADMIN_USER = os.getenv("ADMIN_USER", "admin")
DEFAULT_ADMIN_PASS = os.getenv("ADMIN_PASS", "changeme")

DEFAULT_USER_USER = os.getenv("USER_USER", "user")
DEFAULT_USER_PASS = os.getenv("USER_PASS", "123456")

SESSION_HEADER = "X-Admin-Session"
USER_SESSION_HEADER = "X-User-Session"


# ====== Pydantic 模型 ======

class Material(BaseModel):
    vendor: str          # 厂商
    name: str            # 型号/材料名
    pricePerKg: Optional[float] = None    # 元 / kg（重量计价时必填）
    pricePerCubicMeter: Optional[float] = None  # 元 / m³（体积计价时必填）
    pricingMode: Literal["WEIGHT", "VOLUME"] = "WEIGHT"
    processType: Optional[str] = None  # 加工类型，None 视为通用


class Machine(BaseModel):
    vendor: str          # 厂商
    name: str            # 设备型号/名称
    hourlyRate: float    # 元 / 小时（最终用于报价的值）
    price: float | None = None               # 设备购置价格（元，可选）
    expectedLifeYears: float | None = None   # 预计使用年限（年，可选）
    expectedMonthlyHours: float | None = None  # 每月预计工作小时数（小时，可选）
    powerW: float | None = None              # 运行时平均功率（W，可选）
    processType: Optional[str] = None        # 加工类型，None 视为通用

class PostProcessRule(BaseModel):
    key: str                      # 唯一标识，比如 "NONE" / "BASIC"
    name: str                     # 展示名称，比如 "无处理" / "基础打磨"
    baseMinutes: float            # 每件固定基础时间（分钟）
    minutesPerGram: float         # 每克增加的时间（分钟/克）
    extraMaterialCostPerGram: float = 0.0  # 每克额外材料成本（元/克）
    processType: Optional[str] = None       # 适用的加工工艺（None 表示通用）
    costMultiplier: float = 1.0             # 成本系数，可按工艺调整最终价格


class Settings(BaseModel):
    materials: List[Material]
    machines: List[Machine]
    defaultProfitMargin: float      # 利润率（如 0.4）
    defaultMinPricePerPart: float   # 单件最低价
    setupFee: float                 # 开机/调机费（订单级别）

    # 新增：全局成本参数
    electricityPrice: float = 1.0           # 电价 元/kWh
    laborHourlyCost: float = 25.0           # 操作人工成本 元/人·小时
    machinesPerOperator: float = 3.0        # 每名操作员平均负责几台机
    overheadHourlyPerMachine: float = 2.0   # 其他杂项成本 元/台·小时

    # 新增：后处理规则列表
    postProcessRules: List[PostProcessRule] = []

class AdminAccount(BaseModel):
    username: str
    salt: str
    password_hash: str


class UserAccount(AdminAccount):
    pass


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str


class ChangePasswordRequest(BaseModel):
    oldPassword: str
    newPassword: str


class QuoteRecordCreate(BaseModel):
    processType: str
    processLabel: Optional[str] = None
    quantity: int
    totalPrice: float
    finalPricePerPart: float
    costSumPerPart: float
    profitMargin: float
    materialCostPerPart: float
    machineCostPerPart: float
    postCostPerPart: float
    setupCostPerPart: float
    material: Dict
    machine: Dict
    postProcess: Dict
    weight: Optional[float] = None
    volume: Optional[float] = None
    totalHours: Optional[float] = None


class QuoteRecord(QuoteRecordCreate):
    id: str
    createdAt: str


# ====== 默认配置 ======

DEFAULT_SETTINGS = Settings(
    materials=[
        Material(vendor="通用", name="PLA", pricePerKg=120, processType="FDM_3D_PRINT"),
        Material(vendor="通用", name="PETG", pricePerKg=150, processType="FDM_3D_PRINT"),
        Material(vendor="通用", name="ABS", pricePerKg=160, processType="FDM_3D_PRINT"),
        Material(vendor="通用", name="水洗树脂", pricePerKg=220, processType="RESIN_3D_PRINT"),
        Material(vendor="通用", name="高韧树脂", pricePerKg=260, processType="RESIN_3D_PRINT"),
        Material(
            vendor="通用木料",
            name="桦木板",
            pricingMode="VOLUME",
            pricePerCubicMeter=3800,
            processType="CNC_MILLING",
        ),
        Material(
            vendor="通用木料",
            name="樱桃木板",
            pricingMode="VOLUME",
            pricePerCubicMeter=5200,
            processType="CNC_MILLING",
        ),
        Material(vendor="通用板材", name="亚克力板", pricePerKg=45, processType="CO2_LASER_ENGRAVE_CUT"),
    ],
    machines=[
        Machine(vendor="Bambu Lab", name="A1/桌面机", hourlyRate=10, processType="FDM_3D_PRINT"),
        Machine(vendor="Elegoo", name="Saturn 树脂机", hourlyRate=28, processType="RESIN_3D_PRINT"),
        Machine(vendor="通用木工", name="三轴雕刻机", hourlyRate=80, processType="CNC_MILLING"),
        Machine(vendor="通用激光", name="CO₂ 激光雕刻机", hourlyRate=120, processType="CO2_LASER_ENGRAVE_CUT"),
    ],
    defaultProfitMargin=0.4,
    defaultMinPricePerPart=15.0,
    setupFee=10.0,

    # 新增四个全局参数的默认值，可以按你习惯改
    electricityPrice=1.0,
    laborHourlyCost=25.0,
    machinesPerOperator=3.0,
    overheadHourlyPerMachine=2.0,

    postProcessRules=[
        PostProcessRule(
            key="NONE",
            name="无后处理",
            baseMinutes=0,
            minutesPerGram=0,
            extraMaterialCostPerGram=0,
            costMultiplier=1,
        ),
        PostProcessRule(
            key="BASIC",
            name="基础打磨去支撑",
            baseMinutes=5,
            minutesPerGram=0.02,
            extraMaterialCostPerGram=0.02,
            costMultiplier=1,
        ),
        PostProcessRule(
            key="FINE",
            name="精细打磨+底漆",
            baseMinutes=10,
            minutesPerGram=0.05,
            extraMaterialCostPerGram=0.05,
            costMultiplier=1.1,
        ),
        PostProcessRule(
            key="PAINT",
            name="精细打磨+喷涂上色",
            baseMinutes=20,
            minutesPerGram=0.08,
            extraMaterialCostPerGram=0.10,
            costMultiplier=1.2,
        ),
    ],
)


# ====== 工具函数：设置文件 ======

def _migrate_old_material(m: dict) -> Material:
    """兼容旧版本没有 vendor 字段的材料数据"""
    if "vendor" not in m:
        m["vendor"] = "未分类"
    if "processType" not in m:
        m["processType"] = None
    if "pricingMode" not in m:
        m["pricingMode"] = "WEIGHT"
    if m.get("pricingMode") == "WEIGHT" and "pricePerKg" not in m:
        m["pricePerKg"] = 0
    if m.get("pricingMode") == "VOLUME" and "pricePerCubicMeter" not in m:
        m["pricePerCubicMeter"] = 0
    return Material(**m)


def _migrate_old_machine(m: dict) -> Machine:
    """兼容旧版本没有 vendor 字段的设备数据"""
    if "vendor" not in m:
        m["vendor"] = "未分类"
    if "processType" not in m:
        m["processType"] = None
    return Machine(**m)


def load_settings() -> Settings:
    if not os.path.exists(SETTINGS_FILE):
        return DEFAULT_SETTINGS
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        mats = data.get("materials", [])
        macs = data.get("machines", [])
        post_rules = data.get("postProcessRules")


        materials = [_migrate_old_material(m) for m in mats]
        machines = [_migrate_old_machine(m) for m in macs]

        return Settings(
            materials=materials,
            machines=machines,
            defaultProfitMargin=data.get(
                "defaultProfitMargin", DEFAULT_SETTINGS.defaultProfitMargin
            ),
            defaultMinPricePerPart=data.get(
                "defaultMinPricePerPart", DEFAULT_SETTINGS.defaultMinPricePerPart
            ),
            setupFee=data.get("setupFee", DEFAULT_SETTINGS.setupFee),

            electricityPrice=data.get("electricityPrice", DEFAULT_SETTINGS.electricityPrice),
            laborHourlyCost=data.get("laborHourlyCost", DEFAULT_SETTINGS.laborHourlyCost),
            machinesPerOperator=data.get("machinesPerOperator", DEFAULT_SETTINGS.machinesPerOperator),
            overheadHourlyPerMachine=data.get(
                "overheadHourlyPerMachine", DEFAULT_SETTINGS.overheadHourlyPerMachine
            ),

            # 新增：如果旧文件里没有，就用默认规则
            postProcessRules=(
                [
                    PostProcessRule(
                        **{
                            **r,
                            "costMultiplier": r.get("costMultiplier", 1),
                            "processType": r.get("processType", None),
                        }
                    )
                    for r in post_rules
                ]
                if isinstance(post_rules, list)
                else DEFAULT_SETTINGS.postProcessRules
            ),
        )

    except Exception as e:
        print("Failed to load settings.json:", e)
        return DEFAULT_SETTINGS


def save_settings(settings: Settings):
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings.dict(), f, ensure_ascii=False, indent=2)


# ====== 工具函数：密码 & 管理员账户 ======

def hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def verify_password(password: str, salt: str, password_hash: str) -> bool:
    return hash_password(password, salt) == password_hash


def load_admin_account() -> AdminAccount:
    """从文件读取管理员账户，不存在则用默认用户名/密码创建。"""
    if os.path.exists(ACCOUNT_FILE):
        try:
            with open(ACCOUNT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return AdminAccount(**data)
        except Exception as e:
            print("Failed to load admin_account.json, using default admin:", e)

    # 创建默认账号
    salt = secrets.token_hex(16)
    password_hash = hash_password(DEFAULT_ADMIN_PASS, salt)
    account = AdminAccount(username=DEFAULT_ADMIN_USER, salt=salt, password_hash=password_hash)
    save_admin_account(account)
    print(f"[INIT] Created default admin account username={DEFAULT_ADMIN_USER}, password={DEFAULT_ADMIN_PASS}")
    return account


def save_admin_account(account: AdminAccount):
    os.makedirs(os.path.dirname(ACCOUNT_FILE), exist_ok=True)
    with open(ACCOUNT_FILE, "w", encoding="utf-8") as f:
        json.dump(account.dict(), f, ensure_ascii=False, indent=2)


ADMIN_ACCOUNT: AdminAccount = load_admin_account()


def load_user_account() -> UserAccount:
    """从文件读取普通用户账户，不存在则用默认用户名/密码创建。"""
    if os.path.exists(USER_ACCOUNT_FILE):
        try:
            with open(USER_ACCOUNT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return UserAccount(**data)
        except Exception as e:
            print("Failed to load user_account.json, using default user:", e)

    salt = secrets.token_hex(16)
    password_hash = hash_password(DEFAULT_USER_PASS, salt)
    account = UserAccount(username=DEFAULT_USER_USER, salt=salt, password_hash=password_hash)
    save_user_account(account)
    print(
        f"[INIT] Created default user account username={DEFAULT_USER_USER}, password={DEFAULT_USER_PASS}"
    )
    return account


def save_user_account(account: UserAccount):
    os.makedirs(os.path.dirname(USER_ACCOUNT_FILE), exist_ok=True)
    with open(USER_ACCOUNT_FILE, "w", encoding="utf-8") as f:
        json.dump(account.dict(), f, ensure_ascii=False, indent=2)


USER_ACCOUNT: UserAccount = load_user_account()

# ====== 简单 Session 管理（保存在内存） ======

SESSIONS: Dict[str, Dict[str, str]] = {}  # token -> {username, role}


def load_quote_records() -> List[QuoteRecord]:
    if not os.path.exists(QUOTES_FILE):
        return []
    try:
        with open(QUOTES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        records = []
        for item in data:
            try:
                records.append(QuoteRecord(**item))
            except Exception:
                continue
        return records
    except Exception as e:
        print("Failed to load quotes:", e)
        return []


def save_quote_records(records: List[QuoteRecord]):
    os.makedirs(os.path.dirname(QUOTES_FILE), exist_ok=True)
    with open(QUOTES_FILE, "w", encoding="utf-8") as f:
        json.dump([r.dict() for r in records], f, ensure_ascii=False, indent=2)


def create_session(username: str, role: str) -> str:
    token = uuid4().hex + secrets.token_hex(8)
    SESSIONS[token] = {"username": username, "role": role}
    return token


def get_session_from_token(token: Optional[str]) -> Optional[Dict[str, str]]:
    if not token:
        return None
    return SESSIONS.get(token)


def require_admin(token: Optional[str]) -> Dict[str, str]:
    session = get_session_from_token(token)
    if not session:
        raise HTTPException(status_code=401, detail="未登录或会话已失效")
    if session.get("role") != "admin":
        raise HTTPException(status_code=403, detail="没有管理员权限")
    return session


def require_authenticated(
    user_token: Optional[str], admin_token: Optional[str]
) -> Dict[str, str]:
    session = get_session_from_token(admin_token) or get_session_from_token(user_token)
    if not session:
        raise HTTPException(status_code=401, detail="未登录或会话已失效")
    return session


# ====== API：公开的设置读取 & 受保护的设置修改 ======

@app.get("/api/settings", response_model=Settings)
def get_settings(
    x_user_session: Optional[str] = Header(None),
    x_admin_session: Optional[str] = Header(None),
):
    """登录后才能读取设置（用于报价）。"""
    require_authenticated(x_user_session, x_admin_session)
    return load_settings()


@app.post("/api/settings", response_model=Settings)
def update_settings(
    settings: Settings,
    x_user_session: Optional[str] = Header(None),
    x_admin_session: Optional[str] = Header(None),
):
    """只有登录的管理员才能修改设置。"""
    if len(settings.materials) == 0:
        raise HTTPException(status_code=400, detail="至少需要一个材料")
    if len(settings.machines) == 0:
        raise HTTPException(status_code=400, detail="至少需要一台设备")

    # 权限检查
    require_admin(x_admin_session)

    save_settings(settings)
    return settings


# ====== API：管理员登录 / 登出 / 状态 / 改密码 ======

@app.post("/api/admin/login", response_model=LoginResponse)
def admin_login(body: LoginRequest):
    """管理员登录：传用户名+密码，返回 session token。"""
    global ADMIN_ACCOUNT

    if body.username != ADMIN_ACCOUNT.username:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not verify_password(body.password, ADMIN_ACCOUNT.salt, ADMIN_ACCOUNT.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_session(ADMIN_ACCOUNT.username, "admin")
    return LoginResponse(token=token, username=ADMIN_ACCOUNT.username)


@app.post("/api/admin/logout")
def admin_logout(x_admin_session: Optional[str] = Header(None)):
    """管理员退出登录：失效当前 session。"""
    if x_admin_session and x_admin_session in SESSIONS:
        del SESSIONS[x_admin_session]
    return {"message": "已退出登录"}


@app.get("/api/admin/status")
def admin_status(x_admin_session: Optional[str] = Header(None)):
    """检查当前 session 是否已登录。"""
    session = get_session_from_token(x_admin_session)
    is_admin = bool(session) and session.get("role") == "admin"
    return {
        "authenticated": is_admin,
        "username": session.get("username") if is_admin and session else None,
    }


@app.post("/api/admin/change-password")
def admin_change_password(body: ChangePasswordRequest, x_admin_session: Optional[str] = Header(None)):
    """修改管理员密码：需要已经登录，并提供旧密码、新密码。"""
    global ADMIN_ACCOUNT

    session = require_admin(x_admin_session)

    # 再用旧密码校验一遍
    if not verify_password(body.oldPassword, ADMIN_ACCOUNT.salt, ADMIN_ACCOUNT.password_hash):
        raise HTTPException(status_code=403, detail="旧密码不正确")

    new_salt = secrets.token_hex(16)
    new_hash = hash_password(body.newPassword, new_salt)
    ADMIN_ACCOUNT = AdminAccount(username=session["username"], salt=new_salt, password_hash=new_hash)
    save_admin_account(ADMIN_ACCOUNT)

    # 可选：所有已有 session 失效
    SESSIONS.clear()

    return {"message": "密码已更新，请使用新密码重新登录"}


# ====== 普通用户登录 / 状态 ======


@app.post("/api/user/login", response_model=LoginResponse)
def user_login(body: LoginRequest):
    """普通用户登录：返回用户会话 token。"""
    global USER_ACCOUNT

    if body.username != USER_ACCOUNT.username:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not verify_password(body.password, USER_ACCOUNT.salt, USER_ACCOUNT.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_session(USER_ACCOUNT.username, "user")
    return LoginResponse(token=token, username=USER_ACCOUNT.username)


@app.post("/api/user/logout")
def user_logout(x_user_session: Optional[str] = Header(None)):
    """普通用户退出登录。"""
    if x_user_session and x_user_session in SESSIONS:
        del SESSIONS[x_user_session]
    return {"message": "已退出登录"}


@app.get("/api/user/status")
def user_status(
    x_user_session: Optional[str] = Header(None),
    x_admin_session: Optional[str] = Header(None),
):
    """检查普通用户是否已登录；管理员 token 也视为已登录。"""
    session = get_session_from_token(x_admin_session) or get_session_from_token(x_user_session)
    is_authed = bool(session) and session.get("role") in {"user", "admin"}
    return {
        "authenticated": is_authed,
        "username": session.get("username") if is_authed and session else None,
    }


# ====== 报价记录：创建 / 查询 / 统计 ======


@app.post("/api/quotes", response_model=QuoteRecord)
def create_quote_record(
    body: QuoteRecordCreate,
    x_user_session: Optional[str] = Header(None),
    x_admin_session: Optional[str] = Header(None),
):
    """保存一次报价结果，用于后续对账和统计。"""
    require_authenticated(x_user_session, x_admin_session)
    existing = load_quote_records()
    record = QuoteRecord(
        **body.dict(),
        id=uuid4().hex,
        createdAt=datetime.utcnow().isoformat() + "Z",
    )
    existing.append(record)
    save_quote_records(existing)
    return record


@app.get("/api/quotes")
def list_quote_records(
    page: int = 1,
    pageSize: int = 20,
    month: Optional[str] = None,  # 形如 2024-03
    x_admin_session: Optional[str] = Header(None),
):
    """分页查询报价记录，支持按月份过滤，需管理员登录。"""
    require_admin(x_admin_session)
    page = max(page, 1)
    pageSize = min(max(pageSize, 1), 200)
    all_records = load_quote_records()
    if month:
        filtered = []
        for r in all_records:
            try:
                ts = datetime.fromisoformat(r.createdAt.replace("Z", "+00:00"))
                if ts.strftime("%Y-%m") == month:
                    filtered.append(r)
            except Exception:
                continue
        all_records = filtered
    total = len(all_records)
    start = (page - 1) * pageSize
    end = start + pageSize
    slice_records = all_records[start:end]
    return {
        "total": total,
        "page": page,
        "pageSize": pageSize,
        "items": [r.dict() for r in slice_records],
    }


@app.get("/api/quotes/summary")
def quote_summary(
    year: Optional[int] = None,
    x_admin_session: Optional[str] = Header(None),
):
    """按月份汇总报价数量与金额。需管理员登录。"""
    require_admin(x_admin_session)
    records = load_quote_records()
    summary: Dict[str, Dict[str, float]] = {}
    for r in records:
        try:
            ts = datetime.fromisoformat(r.createdAt.replace("Z", "+00:00"))
        except Exception:
            continue
        if year and ts.year != year:
            continue
        key = ts.strftime("%Y-%m")
        if key not in summary:
            summary[key] = {"count": 0, "amount": 0.0}
        summary[key]["count"] += 1
        summary[key]["amount"] += float(r.totalPrice)
    # 排序输出
    items = [
        {"month": k, "count": v["count"], "amount": round(v["amount"], 2)}
        for k, v in sorted(summary.items())
    ]
    return {"items": items}
