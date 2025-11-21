from __future__ import annotations

import os
import secrets
from typing import Dict, Optional
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .models import AdminAccount, ChangePasswordRequest, LoginRequest, LoginResponse, Settings
from .services import (
    hash_password,
    load_admin_account,
    load_processes,
    load_settings,
    load_vendors,
    save_admin_account,
    save_settings,
    verify_password,
)

app = FastAPI(title="3dquote backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CORS_ALLOW_ORIGINS", "*")],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSION_HEADER = "X-Admin-Session"
ADMIN_ACCOUNT = load_admin_account()
SESSIONS: Dict[str, str] = {}


def create_session(username: str) -> str:
    token = uuid4().hex + secrets.token_hex(8)
    SESSIONS[token] = username
    return token


def get_username_from_session_token(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    return SESSIONS.get(token)


def require_admin(token: Optional[str]) -> str:
    username = get_username_from_session_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="未登录或会话已失效")
    return username


@app.get("/api/settings", response_model=Settings)
def get_settings():
    return load_settings()


@app.post("/api/settings", response_model=Settings)
def update_settings(settings: Settings, x_admin_session: Optional[str] = Header(None)):
    if len(settings.materials) == 0:
        raise HTTPException(status_code=400, detail="至少需要一个材料")
    if len(settings.machines) == 0:
        raise HTTPException(status_code=400, detail="至少需要一台设备")

    require_admin(x_admin_session)
    save_settings(settings)
    return settings


@app.get("/api/catalog")
def get_catalog():
    settings = load_settings()
    return {
        "processes": load_processes(),
        "vendors": load_vendors(),
        "materials": [m.dict() for m in settings.materials],
        "devices": [m.dict() for m in settings.machines],
    }


@app.post("/api/admin/login", response_model=LoginResponse)
def admin_login(body: LoginRequest):
    global ADMIN_ACCOUNT

    if body.username != ADMIN_ACCOUNT.username:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not verify_password(body.password, ADMIN_ACCOUNT.salt, ADMIN_ACCOUNT.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_session(ADMIN_ACCOUNT.username)
    return LoginResponse(token=token, username=ADMIN_ACCOUNT.username)


@app.post("/api/admin/logout")
def admin_logout(x_admin_session: Optional[str] = Header(None)):
    if x_admin_session and x_admin_session in SESSIONS:
        del SESSIONS[x_admin_session]
    return {"message": "已退出登录"}


@app.get("/api/admin/status")
def admin_status(x_admin_session: Optional[str] = Header(None)):
    username = get_username_from_session_token(x_admin_session)
    return {
        "authenticated": bool(username),
        "username": username,
    }


@app.post("/api/admin/change-password")
def admin_change_password(body: ChangePasswordRequest, x_admin_session: Optional[str] = Header(None)):
    global ADMIN_ACCOUNT

    require_admin(x_admin_session)

    if not verify_password(body.oldPassword, ADMIN_ACCOUNT.salt, ADMIN_ACCOUNT.password_hash):
        raise HTTPException(status_code=403, detail="旧密码不正确")

    new_salt = secrets.token_hex(16)
    password_hash = hash_password(body.newPassword, new_salt)
    ADMIN_ACCOUNT = AdminAccount(
        username=ADMIN_ACCOUNT.username, salt=new_salt, password_hash=password_hash
    )
    save_admin_account(ADMIN_ACCOUNT)
    SESSIONS.clear()

    return {"message": "密码已更新，请使用新密码重新登录"}


@app.get("/api/health")
def health_check():
    return {"status": "ok"}
