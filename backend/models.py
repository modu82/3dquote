from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, validator


class Material(BaseModel):
    vendor: str
    name: str
    billingMethod: str = Field(
        "weight", description="计价方式：weight 按重量，volume 按体积"
    )
    pricePerKg: Optional[float] = Field(
        None, description="重量计价：元/千克"
    )
    pricePerCubicMeter: Optional[float] = Field(
        None, description="体积计价：元/立方米"
    )
    density: Optional[float] = Field(
        None, description="材料密度（g/cm³），用于重量/体积互转"
    )
    processType: Optional[str] = Field(
        None, description="加工类型，None 视为通用"
    )

    @validator("billingMethod", pre=True, always=True)
    def set_billing_method(cls, v, values):
        if v:
            return v
        if values.get("pricePerCubicMeter"):
            return "volume"
        return "weight"


class Machine(BaseModel):
    vendor: str
    name: str
    hourlyRate: float
    price: Optional[float] = None
    expectedLifeYears: Optional[float] = None
    expectedMonthlyHours: Optional[float] = None
    powerW: Optional[float] = None
    processType: Optional[str] = None


class PostProcessRule(BaseModel):
    key: str
    name: str
    baseMinutes: float
    minutesPerGram: float
    extraMaterialCostPerGram: float = 0.0
    processType: Optional[str] = None
    costMultiplier: float = 1.0


class Settings(BaseModel):
    materials: List[Material]
    machines: List[Machine]
    defaultProfitMargin: float
    defaultMinPricePerPart: float
    setupFee: float
    electricityPrice: float = 1.0
    laborHourlyCost: float = 25.0
    machinesPerOperator: float = 3.0
    overheadHourlyPerMachine: float = 2.0
    postProcessRules: List[PostProcessRule] = []


class AdminAccount(BaseModel):
    username: str
    salt: str
    password_hash: str


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str


class ChangePasswordRequest(BaseModel):
    oldPassword: str
    newPassword: str


class Catalog(BaseModel):
    processes: List[dict]
    vendors: List[str]
