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
SETTINGS_BACKUP_FILE = "/data/settings.backup.json"
FULL_BACKUP_FILE = "/data/full_backup.json"
ACCOUNT_FILE = "/data/admin_account.json"
USER_ACCOUNT_FILE = "/data/user_account.json"
ACCOUNTS_FILE = "/data/accounts.json"
QUOTES_FILE = "/data/quotes.json"
PROJECTS_FILE = "/data/projects.json"

# 初始管理员信息（如果 ACCOUNT_FILE 不存在，就用这个创建）
DEFAULT_ADMIN_USER = os.getenv("ADMIN_USER", "admin")
DEFAULT_ADMIN_PASS = os.getenv("ADMIN_PASS", "changeme")

DEFAULT_USER_USER = os.getenv("USER_USER", "user")
DEFAULT_USER_PASS = os.getenv("USER_PASS", "123456")

SESSION_HEADER = "X-Admin-Session"
USER_SESSION_HEADER = "X-User-Session"
GENERIC_SESSION_HEADER = "X-Session"


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
    hourlyRateIncludesOperational: Optional[bool] = None  # 小时费率是否已含人工/电费/杂项

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
    laborHourlyCost: float = 25.0           # 操作人工成本 元/人·小时（兼容旧版全局）
    machinesPerOperator: float = 3.0        # 每名操作员平均负责几台机（兼容旧版全局）
    overheadHourlyPerMachine: float = 2.0   # 其他杂项成本 元/台·小时（兼容旧版全局）

    # 按工艺的成本参数
    processCosts: Dict[str, Dict[str, float]] | None = None

    # 新增：后处理规则列表
    postProcessRules: List[PostProcessRule] = []

class Account(BaseModel):
    username: str
    salt: str
    password_hash: str
    role: Literal["admin", "user"] = "user"
    active: bool = True
    recordEnabled: bool = True
    canViewRecords: bool = False


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    role: Literal["admin", "user"]
    recordEnabled: bool
    canViewRecords: bool


class ChangePasswordRequest(BaseModel):
    oldPassword: str
    newPassword: str


class ChangeUsernameRequest(BaseModel):
    password: str
    newUsername: str


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
    projectId: Optional[str] = None
    projectName: Optional[str] = None
    weight: Optional[float] = None
    volume: Optional[float] = None
    totalHours: Optional[float] = None
    visibility: Literal["admin_only", "all_users", "owner_only"] = "admin_only"
    adopted: bool = False


class QuoteRecord(QuoteRecordCreate):
    id: str
    createdAt: str
    createdBy: str


class QuoteRecordUpdate(BaseModel):
    visibility: Optional[Literal["admin_only", "all_users", "owner_only"]] = None
    adopted: Optional[bool] = None


class Project(BaseModel):
    id: str
    name: str
    clientName: Optional[str] = None
    code: Optional[str] = None
    status: Optional[str] = None
    remark: Optional[str] = None
    createdAt: str
    updatedAt: str


class FullBackup(BaseModel):
    """全量备份：覆盖配置、账户、报价与项目。"""

    createdAt: str
    settings: Settings
    accounts: List[Account]
    quotes: List[QuoteRecord]
    projects: List[Project]


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
        Machine(vendor="Bambu Lab", name="A1/桌面机", hourlyRate=10, processType="FDM_3D_PRINT", hourlyRateIncludesOperational=True),
        Machine(vendor="Elegoo", name="Saturn 树脂机", hourlyRate=28, processType="RESIN_3D_PRINT", hourlyRateIncludesOperational=True),
        Machine(vendor="通用木工", name="三轴雕刻机", hourlyRate=80, processType="CNC_MILLING", hourlyRateIncludesOperational=True),
        Machine(vendor="通用激光", name="CO₂ 激光雕刻机", hourlyRate=120, processType="CO2_LASER_ENGRAVE_CUT", hourlyRateIncludesOperational=True),
    ],
    defaultProfitMargin=0.4,
    defaultMinPricePerPart=15.0,
    setupFee=10.0,

    # 新增四个全局参数的默认值，可以按你习惯改
    electricityPrice=1.0,
    laborHourlyCost=25.0,
    machinesPerOperator=3.0,
    overheadHourlyPerMachine=2.0,

    processCosts={
        "FDM_3D_PRINT": {
            "laborHourlyCost": 25.0,
            "machinesPerOperator": 3.0,
            "overheadHourlyPerMachine": 2.0,
        },
        "RESIN_3D_PRINT": {
            "laborHourlyCost": 30.0,
            "machinesPerOperator": 2.0,
            "overheadHourlyPerMachine": 3.0,
        },
        "CNC_MILLING": {
            "laborHourlyCost": 35.0,
            "machinesPerOperator": 1.0,
            "overheadHourlyPerMachine": 5.0,
        },
        "CO2_LASER_ENGRAVE_CUT": {
            "laborHourlyCost": 28.0,
            "machinesPerOperator": 2.0,
            "overheadHourlyPerMachine": 3.0,
        },
    },

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
    has_depreciation = (
        isinstance(m.get("price"), (int, float))
        and m.get("price") is not None
        and m.get("price") > 0
        and isinstance(m.get("expectedLifeYears"), (int, float))
        and m.get("expectedLifeYears") is not None
        and m.get("expectedLifeYears") > 0
        and isinstance(m.get("expectedMonthlyHours"), (int, float))
        and m.get("expectedMonthlyHours") is not None
        and m.get("expectedMonthlyHours") > 0
    )
    if "hourlyRateIncludesOperational" not in m:
        # 旧数据的小时成本默认包含人工/电费/杂项；若填写了折旧参数则视为不包含
        m["hourlyRateIncludesOperational"] = False if has_depreciation else True
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

        loaded_process_costs = data.get("processCosts")

        # 兼容旧版：如果没有 processCosts，就用全局值填充所有工艺
        default_process_costs = DEFAULT_SETTINGS.processCosts or {}
        merged_process_costs = {}
        if isinstance(loaded_process_costs, dict):
            merged_process_costs = {
                k: {
                    "laborHourlyCost": v.get(
                        "laborHourlyCost", data.get("laborHourlyCost", DEFAULT_SETTINGS.laborHourlyCost)
                    ),
                    "machinesPerOperator": v.get(
                        "machinesPerOperator",
                        data.get("machinesPerOperator", DEFAULT_SETTINGS.machinesPerOperator),
                    ),
                    "overheadHourlyPerMachine": v.get(
                        "overheadHourlyPerMachine",
                        data.get("overheadHourlyPerMachine", DEFAULT_SETTINGS.overheadHourlyPerMachine),
                    ),
                }
                for k, v in loaded_process_costs.items()
                if isinstance(v, dict)
            }
        else:
            merged_process_costs = {
                k: {
                    "laborHourlyCost": data.get("laborHourlyCost", DEFAULT_SETTINGS.laborHourlyCost),
                    "machinesPerOperator": data.get("machinesPerOperator", DEFAULT_SETTINGS.machinesPerOperator),
                    "overheadHourlyPerMachine": data.get(
                        "overheadHourlyPerMachine", DEFAULT_SETTINGS.overheadHourlyPerMachine
                    ),
                }
                for k in default_process_costs.keys()
            }

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

            processCosts=merged_process_costs or DEFAULT_SETTINGS.processCosts,
        )

    except Exception as e:
        print("Failed to load settings.json:", e)
        return DEFAULT_SETTINGS


def save_settings(settings: Settings):
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings.dict(), f, ensure_ascii=False, indent=2)


def save_settings_backup(settings: Settings):
    os.makedirs(os.path.dirname(SETTINGS_BACKUP_FILE), exist_ok=True)
    with open(SETTINGS_BACKUP_FILE, "w", encoding="utf-8") as f:
        json.dump(settings.dict(), f, ensure_ascii=False, indent=2)


def load_settings_backup() -> Settings:
    if not os.path.exists(SETTINGS_BACKUP_FILE):
        raise FileNotFoundError("备份不存在")
    try:
        with open(SETTINGS_BACKUP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Settings(**data)
    except Exception as exc:
        raise RuntimeError(f"无法读取备份：{exc}") from exc


def save_full_backup(payload: FullBackup):
    os.makedirs(os.path.dirname(FULL_BACKUP_FILE), exist_ok=True)
    with open(FULL_BACKUP_FILE, "w", encoding="utf-8") as f:
        json.dump(payload.dict(), f, ensure_ascii=False, indent=2)


def load_full_backup() -> FullBackup:
    if not os.path.exists(FULL_BACKUP_FILE):
        raise FileNotFoundError("全量备份不存在")
    try:
        with open(FULL_BACKUP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return FullBackup(**data)
    except Exception as exc:
        raise RuntimeError(f"无法读取全量备份：{exc}") from exc


# ====== 校验函数 ======


def ensure_settings_valid(settings: Settings):
    if len(settings.materials) == 0:
        raise HTTPException(status_code=400, detail="至少需要一个材料")
    if len(settings.machines) == 0:
        raise HTTPException(status_code=400, detail="至少需要一台设备")


# ====== 工具函数：密码 & 账户 ======

def hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def verify_password(password: str, salt: str, password_hash: str) -> bool:
    return hash_password(password, salt) == password_hash


def save_accounts(accounts: List[Account]):
    os.makedirs(os.path.dirname(ACCOUNTS_FILE), exist_ok=True)
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump([a.dict() for a in accounts], f, ensure_ascii=False, indent=2)


def load_accounts() -> List[Account]:
    # 优先读取新的多账户文件
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f) or []
            loaded = [Account(**item) for item in data]
            if any(acc.role == "admin" and acc.active for acc in loaded):
                return loaded
        except Exception as e:
            print("Failed to load accounts.json, fallback to defaults:", e)

    migrated: List[Account] = []
    # 兼容旧版的 admin_account.json
    if os.path.exists(ACCOUNT_FILE):
        try:
            with open(ACCOUNT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            migrated.append(Account(**data, role="admin", active=True))
        except Exception as e:
            print("Failed to migrate admin account:", e)
    # 兼容旧版的 user_account.json
    if os.path.exists(USER_ACCOUNT_FILE):
        try:
            with open(USER_ACCOUNT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            migrated.append(Account(**data, role="user", active=True))
        except Exception as e:
            print("Failed to migrate user account:", e)

    if migrated:
        save_accounts(migrated)
        return migrated

    # 默认初始化至少一个管理员与一个普通用户
    salt_admin = secrets.token_hex(16)
    salt_user = secrets.token_hex(16)
    defaults = [
        Account(
            username=DEFAULT_ADMIN_USER,
            salt=salt_admin,
            password_hash=hash_password(DEFAULT_ADMIN_PASS, salt_admin),
            role="admin",
            active=True,
            recordEnabled=True,
            canViewRecords=True,
        ),
        Account(
            username=DEFAULT_USER_USER,
            salt=salt_user,
            password_hash=hash_password(DEFAULT_USER_PASS, salt_user),
            role="user",
            active=True,
            recordEnabled=True,
            canViewRecords=False,
        ),
    ]
    save_accounts(defaults)
    print(
        f"[INIT] Created default admin={DEFAULT_ADMIN_USER}/{DEFAULT_ADMIN_PASS}, user={DEFAULT_USER_USER}/{DEFAULT_USER_PASS}"
    )
    return defaults


ACCOUNTS: List[Account] = load_accounts()

# ====== 简单 Session 管理（保存在内存） ======

SESSIONS: Dict[str, Dict[str, str]] = {}  # token -> {username, role}


def get_account(username: str) -> Optional[Account]:
    for acc in ACCOUNTS:
        if acc.username == username:
            return acc
    return None


def load_quote_records() -> List[QuoteRecord]:
    if not os.path.exists(QUOTES_FILE):
        return []
    try:
        with open(QUOTES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        records = []
        for item in data:
            try:
                defaults = {
                    "visibility": item.get("visibility", "admin_only"),
                    "adopted": item.get("adopted", False),
                    "createdBy": item.get("createdBy") or item.get("username") or "unknown",
                }
                merged = {**item, **defaults}
                if merged["visibility"] not in ("admin_only", "all_users", "owner_only"):
                    merged["visibility"] = "admin_only"
                records.append(QuoteRecord(**merged))
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


def load_projects() -> List[Project]:
    if not os.path.exists(PROJECTS_FILE):
        return []
    try:
        with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f) or []
        projects: List[Project] = []
        for item in data:
            try:
                projects.append(Project(**item))
            except Exception:
                continue
        return projects
    except Exception as exc:
        print("Failed to load projects:", exc)
        return []


def save_projects(projects: List[Project]):
    os.makedirs(os.path.dirname(PROJECTS_FILE), exist_ok=True)
    with open(PROJECTS_FILE, "w", encoding="utf-8") as f:
        json.dump([p.dict() for p in projects], f, ensure_ascii=False, indent=2)


def reassign_quote_owners(old_username: str, new_username: str) -> int:
    """把报价记录的创建人从旧用户名迁移到新用户名，返回受影响的记录数。"""
    if not old_username or not new_username or old_username == new_username:
        return 0

    records = load_quote_records()
    updated_records: List[QuoteRecord] = []
    changed = 0
    for record in records:
        if record.createdBy == old_username:
            updated_records.append(record.copy(update={"createdBy": new_username}))
            changed += 1
        else:
            updated_records.append(record)

    if changed:
        save_quote_records(updated_records)
    return changed


def create_session(username: str, role: str) -> str:
    token = uuid4().hex + secrets.token_hex(8)
    SESSIONS[token] = {"username": username, "role": role}
    return token


def get_session_from_token(token: Optional[str]) -> Optional[Dict[str, str]]:
    if not token:
        return None
    session = SESSIONS.get(token)
    if not session:
        return None
    acc = get_account(session.get("username", ""))
    if not acc or not acc.active or acc.role != session.get("role"):
        return None
    return session


def require_admin(
    admin_token: Optional[str], user_token: Optional[str] = None, generic_token: Optional[str] = None
) -> Dict[str, str]:
    session = (
        get_session_from_token(admin_token)
        or get_session_from_token(generic_token)
        or get_session_from_token(user_token)
    )
    if not session:
        raise HTTPException(status_code=401, detail="未登录或会话已失效")
    if session.get("role") != "admin":
        raise HTTPException(status_code=403, detail="没有管理员权限")
    return session


def require_authenticated(
    user_token: Optional[str], admin_token: Optional[str], generic_token: Optional[str] = None
) -> Dict[str, str]:
    session = (
        get_session_from_token(admin_token)
        or get_session_from_token(generic_token)
        or get_session_from_token(user_token)
    )
    if not session:
        raise HTTPException(status_code=401, detail="未登录或会话已失效")
    return session


# ====== API：公开的设置读取 & 受保护的设置修改 ======

@app.get("/api/settings", response_model=Settings)
def get_settings(
    x_user_session: Optional[str] = Header(None),
    x_admin_session: Optional[str] = Header(None),
    x_session: Optional[str] = Header(None),
):
    """登录后才能读取设置（用于报价）。"""
    require_authenticated(x_user_session, x_admin_session, x_session)
    return load_settings()


@app.post("/api/settings", response_model=Settings)
def update_settings(
    settings: Settings,
    x_user_session: Optional[str] = Header(None),
    x_admin_session: Optional[str] = Header(None),
    x_session: Optional[str] = Header(None),
):
    """只有登录的管理员才能修改设置。"""
    # 权限检查
    require_admin(x_admin_session, x_user_session, x_session)

    ensure_settings_valid(settings)

    save_settings(settings)
    return settings


@app.get("/api/settings/export", response_model=Settings)
def export_settings(
    x_user_session: Optional[str] = Header(None),
    x_admin_session: Optional[str] = Header(None),
    x_session: Optional[str] = Header(None),
):
    """导出当前配置，仅管理员可用。"""
    require_admin(x_admin_session, x_user_session, x_session)
    return load_settings()


@app.post("/api/settings/backup", response_model=Settings)
def backup_settings(
    x_user_session: Optional[str] = Header(None),
    x_admin_session: Optional[str] = Header(None),
    x_session: Optional[str] = Header(None),
):
    """将当前配置写入备份文件。"""
    require_admin(x_admin_session, x_user_session, x_session)
    current = load_settings()
    save_settings_backup(current)
    return current


@app.post("/api/settings/import", response_model=Settings)
def import_settings(
    settings: Settings,
    x_user_session: Optional[str] = Header(None),
    x_admin_session: Optional[str] = Header(None),
    x_session: Optional[str] = Header(None),
):
    """从上传内容导入配置，写入当前配置与备份文件。"""
    require_admin(x_admin_session, x_user_session, x_session)

    ensure_settings_valid(settings)
    save_settings(settings)
    save_settings_backup(settings)
    return settings


@app.post("/api/settings/restore", response_model=Settings)
def restore_from_backup(
    x_user_session: Optional[str] = Header(None),
    x_admin_session: Optional[str] = Header(None),
    x_session: Optional[str] = Header(None),
):
    """从备份恢复配置。"""
    require_admin(x_admin_session, x_user_session, x_session)
    try:
        restored = load_settings_backup()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="未找到备份，请先备份配置")
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    save_settings(restored)
    return restored


@app.post("/api/backup/full", response_model=FullBackup)
def backup_all(
    x_user_session: Optional[str] = Header(None),
    x_admin_session: Optional[str] = Header(None),
    x_session: Optional[str] = Header(None),
):
    """将当前全部关键数据写入全量备份文件。"""

    require_admin(x_admin_session, x_user_session, x_session)
    backup = FullBackup(
        createdAt=datetime.utcnow().isoformat() + "Z",
        settings=load_settings(),
        accounts=load_accounts(),
        quotes=load_quote_records(),
        projects=load_projects(),
    )
    save_full_backup(backup)
    return backup


@app.post("/api/backup/full/restore", response_model=FullBackup)
def restore_full_backup(
    x_user_session: Optional[str] = Header(None),
    x_admin_session: Optional[str] = Header(None),
    x_session: Optional[str] = Header(None),
):
    """从全量备份恢复全部关键数据。"""

    require_admin(x_admin_session, x_user_session, x_session)
    try:
        backup = load_full_backup()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="未找到全量备份，请先执行全量备份")
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    ensure_settings_valid(backup.settings)
    save_settings(backup.settings)
    save_settings_backup(backup.settings)
    save_quote_records(backup.quotes)
    save_projects(backup.projects)
    save_accounts(backup.accounts)
    global ACCOUNTS
    ACCOUNTS = backup.accounts
    SESSIONS.clear()
    return backup


@app.post("/api/settings/restore-factory", response_model=Settings)
def restore_factory_settings(
    x_user_session: Optional[str] = Header(None),
    x_admin_session: Optional[str] = Header(None),
    x_session: Optional[str] = Header(None),
):
    """恢复出厂默认配置。"""
    require_admin(x_admin_session, x_user_session, x_session)
    save_settings(DEFAULT_SETTINGS)
    return DEFAULT_SETTINGS


# ====== 统一登录 / 登出 / 状态 ======


def _persist_accounts(accounts: List[Account]):
    global ACCOUNTS
    ACCOUNTS = accounts
    save_accounts(accounts)


def invalidate_sessions_for(username: str):
    to_delete = [token for token, session in SESSIONS.items() if session.get("username") == username]
    for token in to_delete:
        del SESSIONS[token]


@app.post("/api/auth/login", response_model=LoginResponse)
def auth_login(body: LoginRequest):
    """统一的登录接口，支持管理员和普通用户。"""
    account = next((a for a in ACCOUNTS if a.username == body.username and a.active), None)
    if not account:
        raise HTTPException(status_code=401, detail="用户名或密码错误或已被禁用")

    if not verify_password(body.password, account.salt, account.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_session(account.username, account.role)
    return LoginResponse(
        token=token,
        username=account.username,
        role=account.role,
        recordEnabled=account.recordEnabled,
        canViewRecords=account.canViewRecords,
    )


@app.post("/api/auth/logout")
def auth_logout(
    x_session: Optional[str] = Header(None),
    x_admin_session: Optional[str] = Header(None),
    x_user_session: Optional[str] = Header(None),
):
    for token in [x_session, x_admin_session, x_user_session]:
        if token and token in SESSIONS:
            del SESSIONS[token]
    return {"message": "已退出登录"}


@app.get("/api/auth/status")
def auth_status(
    x_session: Optional[str] = Header(None),
    x_admin_session: Optional[str] = Header(None),
    x_user_session: Optional[str] = Header(None),
):
    session = (
        get_session_from_token(x_session)
        or get_session_from_token(x_admin_session)
        or get_session_from_token(x_user_session)
    )
    is_authed = bool(session) and session.get("role") in {"user", "admin"}
    account = get_account(session.get("username")) if session else None
    return {
        "authenticated": is_authed,
        "username": session.get("username") if is_authed and session else None,
        "role": session.get("role") if is_authed and session else None,
        "recordEnabled": account.recordEnabled if account else None,
        "canViewRecords": account.canViewRecords if account else None,
    }


@app.post("/api/admin/change-password")
def admin_change_password(
    body: ChangePasswordRequest,
    x_admin_session: Optional[str] = Header(None),
    x_user_session: Optional[str] = Header(None),
    x_session: Optional[str] = Header(None),
):
    """管理员修改自身密码。"""
    session = require_admin(x_admin_session, x_user_session, x_session)
    account = get_account(session["username"])
    if not account:
        raise HTTPException(status_code=400, detail="账号不存在")

    if not verify_password(body.oldPassword, account.salt, account.password_hash):
        raise HTTPException(status_code=403, detail="旧密码不正确")

    new_salt = secrets.token_hex(16)
    new_hash = hash_password(body.newPassword, new_salt)
    updated_accounts: List[Account] = []
    for acc in ACCOUNTS:
        if acc.username == account.username:
            updated_accounts.append(
                Account(
                    username=acc.username,
                    salt=new_salt,
                    password_hash=new_hash,
                    role=acc.role,
                    active=acc.active,
                    recordEnabled=acc.recordEnabled,
                    canViewRecords=acc.canViewRecords,
                )
            )
        else:
            updated_accounts.append(acc)

    _persist_accounts(updated_accounts)
    invalidate_sessions_for(account.username)
    return {"message": "密码已更新，请使用新密码重新登录"}


@app.post("/api/account/change-password")
def account_change_password(
    body: ChangePasswordRequest,
    x_session: Optional[str] = Header(None),
    x_admin_session: Optional[str] = Header(None),
    x_user_session: Optional[str] = Header(None),
):
    """普通用户或管理员修改自己的密码。"""
    session = require_authenticated(x_user_session, x_admin_session, x_session)
    account = get_account(session["username"])
    if not account:
        raise HTTPException(status_code=400, detail="账号不存在")

    if not verify_password(body.oldPassword, account.salt, account.password_hash):
        raise HTTPException(status_code=403, detail="旧密码不正确")

    new_salt = secrets.token_hex(16)
    new_hash = hash_password(body.newPassword, new_salt)
    updated_accounts: List[Account] = []
    for acc in ACCOUNTS:
        if acc.username == account.username:
            updated_accounts.append(
                Account(
                    username=acc.username,
                    salt=new_salt,
                    password_hash=new_hash,
                    role=acc.role,
                    active=acc.active,
                    recordEnabled=acc.recordEnabled,
                    canViewRecords=acc.canViewRecords,
                )
            )
        else:
            updated_accounts.append(acc)
    _persist_accounts(updated_accounts)
    invalidate_sessions_for(account.username)
    return {"message": "密码已更新，请使用新密码重新登录"}


@app.post("/api/account/change-username")
def account_change_username(
    body: ChangeUsernameRequest,
    x_session: Optional[str] = Header(None),
    x_admin_session: Optional[str] = Header(None),
    x_user_session: Optional[str] = Header(None),
):
    """普通用户或管理员修改自己的用户名。"""
    session = require_authenticated(x_user_session, x_admin_session, x_session)
    account = get_account(session["username"])
    if not account:
        raise HTTPException(status_code=400, detail="账号不存在")

    new_username = body.newUsername.strip()
    if not new_username:
        raise HTTPException(status_code=400, detail="新用户名不能为空")

    if get_account(new_username):
        raise HTTPException(status_code=400, detail="目标用户名已存在")

    if not verify_password(body.password, account.salt, account.password_hash):
        raise HTTPException(status_code=403, detail="密码验证失败")

    updated_accounts: List[Account] = []
    for acc in ACCOUNTS:
        if acc.username == account.username:
            updated_accounts.append(
                Account(
                    username=new_username,
                    salt=acc.salt,
                    password_hash=acc.password_hash,
                    role=acc.role,
                    active=acc.active,
                    recordEnabled=acc.recordEnabled,
                    canViewRecords=acc.canViewRecords,
                )
            )
        else:
            updated_accounts.append(acc)

    _persist_accounts(updated_accounts)
    reassign_quote_owners(account.username, new_username)
    invalidate_sessions_for(account.username)
    return {"message": "用户名已更新，请使用新用户名重新登录"}


class UserPublic(BaseModel):
    username: str
    role: Literal["admin", "user"]
    active: bool
    recordEnabled: bool
    canViewRecords: bool


class ManageUserCreate(BaseModel):
    username: str
    password: str
    role: Literal["admin", "user"] = "user"
    active: bool = True
    recordEnabled: bool = True
    canViewRecords: bool = False


class ManageUserToggle(BaseModel):
    active: bool


class ManageUserReset(BaseModel):
    newPassword: str


class ManageUserUpdate(BaseModel):
    newUsername: Optional[str] = None
    role: Optional[Literal["admin", "user"]] = None
    recordEnabled: Optional[bool] = None
    canViewRecords: Optional[bool] = None


@app.get("/api/admin/users", response_model=List[UserPublic])
def list_users(
    x_admin_session: Optional[str] = Header(None),
    x_user_session: Optional[str] = Header(None),
    x_session: Optional[str] = Header(None),
):
    require_admin(x_admin_session, x_user_session, x_session)
    return [
        UserPublic(
            username=a.username,
            role=a.role,
            active=a.active,
            recordEnabled=a.recordEnabled,
            canViewRecords=a.canViewRecords,
        )
        for a in ACCOUNTS
    ]


@app.post("/api/admin/users", response_model=UserPublic)
def create_user(
    body: ManageUserCreate,
    x_admin_session: Optional[str] = Header(None),
    x_user_session: Optional[str] = Header(None),
    x_session: Optional[str] = Header(None),
):
    require_admin(x_admin_session, x_user_session, x_session)
    if get_account(body.username):
        raise HTTPException(status_code=400, detail="用户名已存在")
    salt = secrets.token_hex(16)
    pwd_hash = hash_password(body.password, salt)
    new_account = Account(
        username=body.username,
        salt=salt,
        password_hash=pwd_hash,
        role=body.role,
        active=body.active,
        recordEnabled=body.recordEnabled,
        canViewRecords=body.canViewRecords,
    )
    updated = ACCOUNTS + [new_account]
    _persist_accounts(updated)
    return UserPublic(
        username=new_account.username,
        role=new_account.role,
        active=new_account.active,
        recordEnabled=new_account.recordEnabled,
        canViewRecords=new_account.canViewRecords,
    )


@app.post("/api/admin/users/{username}/toggle", response_model=UserPublic)
def toggle_user(
    username: str,
    body: ManageUserToggle,
    x_admin_session: Optional[str] = Header(None),
    x_user_session: Optional[str] = Header(None),
    x_session: Optional[str] = Header(None),
):
    require_admin(x_admin_session, x_user_session, x_session)
    account = get_account(username)
    if not account:
        raise HTTPException(status_code=404, detail="用户不存在")
    if account.role == "admin" and not body.active:
        # 确保至少一个管理员处于启用状态
        other_active_admin = any(
            a.username != username and a.role == "admin" and a.active for a in ACCOUNTS
        )
        if not other_active_admin:
            raise HTTPException(status_code=400, detail="至少需要保留一名启用的管理员")

    updated_accounts: List[Account] = []
    for acc in ACCOUNTS:
        if acc.username == username:
            updated_accounts.append(
                Account(
                    username=acc.username,
                    salt=acc.salt,
                    password_hash=acc.password_hash,
                    role=acc.role,
                    active=body.active,
                    recordEnabled=acc.recordEnabled,
                    canViewRecords=acc.canViewRecords,
                )
            )
        else:
            updated_accounts.append(acc)

    _persist_accounts(updated_accounts)
    if not body.active:
        invalidate_sessions_for(username)
    return UserPublic(
        username=username,
        role=account.role,
        active=body.active,
        recordEnabled=account.recordEnabled,
        canViewRecords=account.canViewRecords,
    )


@app.post("/api/admin/users/{username}/reset-password")
def reset_user_password(
    username: str,
    body: ManageUserReset,
    x_admin_session: Optional[str] = Header(None),
    x_user_session: Optional[str] = Header(None),
    x_session: Optional[str] = Header(None),
):
    require_admin(x_admin_session, x_user_session, x_session)
    account = get_account(username)
    if not account:
        raise HTTPException(status_code=404, detail="用户不存在")
    new_salt = secrets.token_hex(16)
    new_hash = hash_password(body.newPassword, new_salt)
    updated_accounts: List[Account] = []
    for acc in ACCOUNTS:
        if acc.username == username:
            updated_accounts.append(
                Account(
                    username=acc.username,
                    salt=new_salt,
                    password_hash=new_hash,
                    role=acc.role,
                    active=acc.active,
                    recordEnabled=acc.recordEnabled,
                    canViewRecords=acc.canViewRecords,
                )
            )
        else:
            updated_accounts.append(acc)
    _persist_accounts(updated_accounts)
    invalidate_sessions_for(username)
    return {"message": "密码已重置"}


@app.put("/api/admin/users/{username}", response_model=UserPublic)
def update_user(
    username: str,
    body: ManageUserUpdate,
    x_admin_session: Optional[str] = Header(None),
    x_user_session: Optional[str] = Header(None),
    x_session: Optional[str] = Header(None),
):
    require_admin(x_admin_session, x_user_session, x_session)
    account = get_account(username)
    if not account:
        raise HTTPException(status_code=404, detail="用户不存在")

    new_username = body.newUsername.strip() if body.newUsername else account.username
    new_role = body.role or account.role
    new_record_enabled = account.recordEnabled if body.recordEnabled is None else bool(body.recordEnabled)
    new_view_permission = account.canViewRecords if body.canViewRecords is None else bool(body.canViewRecords)

    if new_username != username and get_account(new_username):
        raise HTTPException(status_code=400, detail="用户名已存在")

    if account.role == "admin" and new_role != "admin":
        other_active_admin = any(
            a.username != username and a.role == "admin" and a.active for a in ACCOUNTS
        )
        if not other_active_admin:
            raise HTTPException(status_code=400, detail="至少需要保留一名启用的管理员")

    updated_accounts: List[Account] = []
    for acc in ACCOUNTS:
        if acc.username == username:
            updated_accounts.append(
                Account(
                    username=new_username,
                    salt=acc.salt,
                    password_hash=acc.password_hash,
                    role=new_role,
                    active=acc.active,
                    recordEnabled=new_record_enabled,
                    canViewRecords=new_view_permission,
                )
            )
        else:
            updated_accounts.append(acc)
    _persist_accounts(updated_accounts)
    if new_username != username:
        reassign_quote_owners(username, new_username)
        invalidate_sessions_for(username)
    if new_role != account.role:
        invalidate_sessions_for(new_username)
    return UserPublic(
        username=new_username,
        role=new_role,
        active=account.active,
        recordEnabled=new_record_enabled,
        canViewRecords=new_view_permission,
    )


@app.delete("/api/admin/users/{username}")
def delete_user(
    username: str,
    x_admin_session: Optional[str] = Header(None),
    x_user_session: Optional[str] = Header(None),
    x_session: Optional[str] = Header(None),
):
    require_admin(x_admin_session, x_user_session, x_session)
    account = get_account(username)
    if not account:
        raise HTTPException(status_code=404, detail="用户不存在")
    if account.role == "admin":
        other_admin = [a for a in ACCOUNTS if a.username != username and a.role == "admin" and a.active]
        if not other_admin:
            raise HTTPException(status_code=400, detail="至少需要保留一名启用的管理员")
    updated_accounts = [acc for acc in ACCOUNTS if acc.username != username]
    _persist_accounts(updated_accounts)
    invalidate_sessions_for(username)
    return {"deleted": username}


# ====== 项目管理 ======


class ProjectCreate(BaseModel):
    name: str
    clientName: Optional[str] = None
    code: Optional[str] = None
    status: Optional[str] = None
    remark: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    clientName: Optional[str] = None
    code: Optional[str] = None
    status: Optional[str] = None
    remark: Optional[str] = None


@app.get("/api/projects", response_model=List[Project])
def list_projects(keyword: Optional[str] = None, x_user_session: Optional[str] = Header(None), x_admin_session: Optional[str] = Header(None), x_session: Optional[str] = Header(None)):
    require_authenticated(x_user_session, x_admin_session, x_session)
    projects = load_projects()
    if keyword:
        lowered = keyword.strip().lower()
        projects = [p for p in projects if lowered in p.name.lower() or (p.clientName and lowered in p.clientName.lower()) or (p.code and lowered in p.code.lower())]
    return projects


@app.post("/api/projects", response_model=Project)
def create_project(body: ProjectCreate, x_user_session: Optional[str] = Header(None), x_admin_session: Optional[str] = Header(None), x_session: Optional[str] = Header(None)):
    require_authenticated(x_user_session, x_admin_session, x_session)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="项目名称不能为空")
    projects = load_projects()
    now = datetime.utcnow().isoformat() + "Z"
    new_project = Project(
        id=uuid4().hex,
        name=name,
        clientName=body.clientName.strip() if body.clientName else None,
        code=body.code.strip() if body.code else None,
        status=body.status.strip() if body.status else None,
        remark=body.remark.strip() if body.remark else None,
        createdAt=now,
        updatedAt=now,
    )
    projects.append(new_project)
    save_projects(projects)
    return new_project


@app.put("/api/projects/{project_id}", response_model=Project)
def update_project(project_id: str, body: ProjectUpdate, x_admin_session: Optional[str] = Header(None), x_user_session: Optional[str] = Header(None), x_session: Optional[str] = Header(None)):
    require_admin(x_admin_session, x_user_session, x_session)
    projects = load_projects()
    updated_list: List[Project] = []
    target: Optional[Project] = None
    for p in projects:
        if p.id == project_id:
            new_name = body.name.strip() if body.name is not None else p.name
            if not new_name:
                raise HTTPException(status_code=400, detail="项目名称不能为空")
            def _strip_optional(val: Optional[str], original: Optional[str]):
                if val is None:
                    return original
                val = val.strip()
                return val if val else None
            target = Project(
                **p.dict(),
                name=new_name,
                clientName=_strip_optional(body.clientName, p.clientName),
                code=_strip_optional(body.code, p.code),
                status=_strip_optional(body.status, p.status),
                remark=_strip_optional(body.remark, p.remark),
                updatedAt=datetime.utcnow().isoformat() + "Z",
            )
            updated_list.append(target)
        else:
            updated_list.append(p)
    if not target:
        raise HTTPException(status_code=404, detail="项目不存在")
    save_projects(updated_list)
    return target


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str, x_admin_session: Optional[str] = Header(None), x_user_session: Optional[str] = Header(None), x_session: Optional[str] = Header(None)):
    require_admin(x_admin_session, x_user_session, x_session)
    projects = load_projects()
    remaining = [p for p in projects if p.id != project_id]
    if len(remaining) == len(projects):
        raise HTTPException(status_code=404, detail="项目不存在")
    # 若有报价引用该项目则阻止删除
    records = load_quote_records()
    if any(r.projectId == project_id for r in records):
        raise HTTPException(status_code=400, detail="该项目已有报价记录关联，无法删除")
    save_projects(remaining)
    return {"deleted": project_id}


# ====== 报价记录：创建 / 查询 / 统计 ======


@app.post("/api/quotes", response_model=QuoteRecord)
def create_quote_record(
    body: QuoteRecordCreate,
    x_user_session: Optional[str] = Header(None),
    x_admin_session: Optional[str] = Header(None),
    x_session: Optional[str] = Header(None),
):
    """保存一次报价结果，用于后续对账和统计。"""
    session = require_authenticated(x_user_session, x_admin_session, x_session)
    account = get_account(session.get("username", ""))
    if not account or not account.recordEnabled:
        raise HTTPException(status_code=403, detail="当前账号的报价记录功能已被禁用")
    is_admin = session.get("role") == "admin"
    visibility = (
        body.visibility if is_admin and body.visibility in ("admin_only", "all_users", "owner_only") else None
    )
    # 普通用户不允许自定义可见范围，默认仅创建人可见；管理员可选择
    visibility = visibility or ("admin_only" if is_admin else "owner_only")

    project_name: Optional[str] = None
    if body.projectId:
        matched = next((p for p in load_projects() if p.id == body.projectId), None)
        if not matched:
            raise HTTPException(status_code=400, detail="关联的项目不存在")
        project_name = matched.name
    elif body.projectName:
        project_name = body.projectName

    existing = load_quote_records()
    record_data = body.dict(exclude={"visibility", "adopted", "projectName"})
    record = QuoteRecord(
        **record_data,
        id=uuid4().hex,
        createdAt=datetime.utcnow().isoformat() + "Z",
        createdBy=session.get("username", "unknown"),
        visibility=visibility,
        adopted=bool(body.adopted) if is_admin else False,
        projectName=project_name,
    )
    existing.append(record)
    save_quote_records(existing)
    return record


@app.get("/api/quotes")
def list_quote_records(
    page: int = 1,
    pageSize: int = 20,
    month: Optional[str] = None,  # 形如 2024-03
    creator: Optional[str] = None,
    projectId: Optional[str] = None,
    adopted: Optional[bool] = None,
    visibility: Optional[Literal["admin_only", "all_users", "owner_only"]] = None,
    x_admin_session: Optional[str] = Header(None),
    x_user_session: Optional[str] = Header(None),
    x_session: Optional[str] = Header(None),
):
    """分页查询报价记录，支持按月份、创建人、采用状态与可见性过滤。"""
    session = require_authenticated(x_user_session, x_admin_session, x_session)
    account = get_account(session.get("username", ""))
    if session.get("role") != "admin" and (not account or not account.canViewRecords):
        raise HTTPException(status_code=403, detail="无权查看报价记录")
    if session.get("role") != "admin":
        visibility = None
    page = max(page, 1)
    pageSize = min(max(pageSize, 1), 200)
    all_records = load_quote_records()

    if session.get("role") != "admin":
        allowed = []
        for r in all_records:
            if r.visibility == "all_users":
                allowed.append(r)
            elif r.visibility == "owner_only" and r.createdBy == session.get("username"):
                allowed.append(r)
        all_records = allowed

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

    if creator:
        all_records = [r for r in all_records if r.createdBy == creator]

    if projectId:
        all_records = [r for r in all_records if r.projectId == projectId]

    if adopted is not None:
        all_records = [r for r in all_records if bool(r.adopted) == bool(adopted)]

    if visibility:
        all_records = [r for r in all_records if r.visibility == visibility]
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
    x_user_session: Optional[str] = Header(None),
    x_session: Optional[str] = Header(None),
):
    """按月份汇总报价数量与金额。需管理员登录。"""
    require_admin(x_admin_session, x_user_session, x_session)
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


@app.patch("/api/quotes/{quote_id}", response_model=QuoteRecord)
def update_quote_record(
    quote_id: str,
    body: QuoteRecordUpdate,
    x_admin_session: Optional[str] = Header(None),
    x_user_session: Optional[str] = Header(None),
    x_session: Optional[str] = Header(None),
):
    require_admin(x_admin_session, x_user_session, x_session)
    records = load_quote_records()
    updated_records: List[QuoteRecord] = []
    target: Optional[QuoteRecord] = None
    for r in records:
        if r.id == quote_id:
            visibility = r.visibility
            if body.visibility in ("admin_only", "all_users", "owner_only"):
                visibility = body.visibility
            adopted = r.adopted if body.adopted is None else bool(body.adopted)
            updated = QuoteRecord(**{**r.dict(), "visibility": visibility, "adopted": adopted})
            updated_records.append(updated)
            target = updated
        else:
            updated_records.append(r)
    if not target:
        raise HTTPException(status_code=404, detail="记录不存在")
    save_quote_records(updated_records)
    return target


@app.delete("/api/quotes/{quote_id}")
def delete_quote_record(
    quote_id: str,
    x_admin_session: Optional[str] = Header(None),
    x_user_session: Optional[str] = Header(None),
    x_session: Optional[str] = Header(None),
):
    require_admin(x_admin_session, x_user_session, x_session)
    records = load_quote_records()
    remaining = [r for r in records if r.id != quote_id]
    if len(remaining) == len(records):
        raise HTTPException(status_code=404, detail="记录不存在")
    save_quote_records(remaining)
    return {"deleted": quote_id}
