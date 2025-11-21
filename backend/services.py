from __future__ import annotations

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

from .models import AdminAccount, Material, Machine, PostProcessRule, Settings

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))

SETTINGS_FILE = Path(os.getenv("SETTINGS_FILE", DATA_DIR / "settings.json"))
ACCOUNT_FILE = Path(os.getenv("ACCOUNT_FILE", DATA_DIR / "admin_account.json"))

DEFAULT_ADMIN_USER = os.getenv("ADMIN_USER", "admin")
DEFAULT_ADMIN_PASS = os.getenv("ADMIN_PASS", "changeme")

DEFAULT_POST_PROCESS_RULES: List[PostProcessRule] = [
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
]


def _load_json_file(path: Path) -> Optional[dict | list]:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _migrate_material(raw: Dict) -> Material:
    if "vendor" not in raw:
        raw["vendor"] = "未分类"
    if "processType" not in raw:
        raw["processType"] = None
    if raw.get("pricePerCubicMeter") and not raw.get("billingMethod"):
        raw["billingMethod"] = "volume"
    if raw.get("pricePerKg") and not raw.get("billingMethod"):
        raw["billingMethod"] = "weight"
    return Material(**raw)


def _migrate_machine(raw: Dict) -> Machine:
    if "vendor" not in raw:
        raw["vendor"] = "未分类"
    if "processType" not in raw:
        raw["processType"] = None
    return Machine(**raw)


def _default_materials() -> List[Material]:
    config_data = _load_json_file(CONFIG_DIR / "materials.json") or []
    if config_data:
        return [_migrate_material(m) for m in config_data]
    return [
        Material(vendor="通用", name="PLA", pricePerKg=120, processType="FDM_3D_PRINT"),
        Material(vendor="通用", name="PETG", pricePerKg=150, processType="FDM_3D_PRINT"),
        Material(vendor="通用", name="ABS", pricePerKg=160, processType="FDM_3D_PRINT"),
        Material(
            vendor="通用", name="水洗树脂", pricePerKg=220, processType="RESIN_3D_PRINT"
        ),
        Material(
            vendor="通用", name="高韧树脂", pricePerKg=260, processType="RESIN_3D_PRINT"
        ),
        Material(
            vendor="通用木料",
            name="桦木板",
            pricePerCubicMeter=3600,
            density=0.65,
            processType="CNC_MILLING",
        ),
        Material(
            vendor="通用木料",
            name="樱桃木板",
            pricePerCubicMeter=5200,
            density=0.7,
            processType="CNC_MILLING",
        ),
        Material(
            vendor="通用板材",
            name="亚克力板",
            pricePerKg=45,
            processType="CO2_LASER_ENGRAVE_CUT",
        ),
    ]


def _default_machines() -> List[Machine]:
    config_data = _load_json_file(CONFIG_DIR / "devices.json") or []
    if config_data:
        return [_migrate_machine(m) for m in config_data]
    return [
        Machine(vendor="Bambu Lab", name="A1/桌面机", hourlyRate=10, processType="FDM_3D_PRINT"),
        Machine(vendor="Elegoo", name="Saturn 树脂机", hourlyRate=28, processType="RESIN_3D_PRINT"),
        Machine(vendor="通用木工", name="三轴雕刻机", hourlyRate=80, processType="CNC_MILLING"),
        Machine(
            vendor="通用激光",
            name="CO₂ 激光雕刻机",
            hourlyRate=120,
            processType="CO2_LASER_ENGRAVE_CUT",
        ),
    ]


def load_processes() -> List[dict]:
    data = _load_json_file(CONFIG_DIR / "processes.json")
    if isinstance(data, list) and data:
        return data
    return [
        {"value": "FDM_3D_PRINT", "label": "FDM 3D 打印"},
        {"value": "RESIN_3D_PRINT", "label": "光固化 3D 打印"},
        {"value": "CNC_MILLING", "label": "CNC 雕刻 / 铣削"},
        {"value": "CO2_LASER_ENGRAVE_CUT", "label": "CO₂ 激光雕刻 / 切割"},
    ]


def load_vendors() -> List[str]:
    data = _load_json_file(CONFIG_DIR / "vendors.json")
    if isinstance(data, list):
        return data
    vendors = {m.vendor for m in _default_materials()} | {m.vendor for m in _default_machines()}
    return sorted(vendors)


def load_settings() -> Settings:
    if SETTINGS_FILE.exists():
        try:
            with SETTINGS_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
            materials = [_migrate_material(m) for m in data.get("materials", [])]
            machines = [_migrate_machine(m) for m in data.get("machines", [])]
            post_rules_raw = data.get("postProcessRules")
            post_rules = (
                [
                    PostProcessRule(
                        **{
                            **rule,
                            "costMultiplier": rule.get("costMultiplier", 1),
                            "processType": rule.get("processType", None),
                        }
                    )
                    for rule in post_rules_raw
                ]
                if isinstance(post_rules_raw, list)
                else DEFAULT_POST_PROCESS_RULES
            )
            return Settings(
                materials=materials or _default_materials(),
                machines=machines or _default_machines(),
                defaultProfitMargin=data.get("defaultProfitMargin", 0.4),
                defaultMinPricePerPart=data.get("defaultMinPricePerPart", 15.0),
                setupFee=data.get("setupFee", 10.0),
                electricityPrice=data.get("electricityPrice", 1.0),
                laborHourlyCost=data.get("laborHourlyCost", 25.0),
                machinesPerOperator=data.get("machinesPerOperator", 3.0),
                overheadHourlyPerMachine=data.get("overheadHourlyPerMachine", 2.0),
                postProcessRules=post_rules,
            )
        except Exception:
            pass

    return Settings(
        materials=_default_materials(),
        machines=_default_machines(),
        defaultProfitMargin=0.4,
        defaultMinPricePerPart=15.0,
        setupFee=10.0,
        electricityPrice=1.0,
        laborHourlyCost=25.0,
        machinesPerOperator=3.0,
        overheadHourlyPerMachine=2.0,
        postProcessRules=DEFAULT_POST_PROCESS_RULES,
    )


def save_settings(settings: Settings) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with SETTINGS_FILE.open("w", encoding="utf-8") as f:
        json.dump(settings.dict(), f, ensure_ascii=False, indent=2)


def hash_password(password: str, salt: str) -> str:
    import hashlib

    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def verify_password(password: str, salt: str, password_hash: str) -> bool:
    return hash_password(password, salt) == password_hash


def load_admin_account() -> AdminAccount:
    if ACCOUNT_FILE.exists():
        try:
            with ACCOUNT_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return AdminAccount(**data)
        except Exception:
            pass

    salt = os.urandom(16).hex()
    password_hash = hash_password(DEFAULT_ADMIN_PASS, salt)
    account = AdminAccount(username=DEFAULT_ADMIN_USER, salt=salt, password_hash=password_hash)
    save_admin_account(account)
    return account


def save_admin_account(account: AdminAccount) -> None:
    ACCOUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with ACCOUNT_FILE.open("w", encoding="utf-8") as f:
        json.dump(account.dict(), f, ensure_ascii=False, indent=2)


