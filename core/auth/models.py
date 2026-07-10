"""Auth & multi-tenancy data models for Accord."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class Tenant(BaseModel):
    tenant_id: str
    name: str
    plan: str
    products: list[str]
    settings: dict = {}
    logo_url: Optional[str] = None


class User(BaseModel):
    user_id: UUID
    tenant_id: str
    email: str
    name: str
    role: str
    is_active: bool = True
    last_login: Optional[datetime] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: User
    tenant: Tenant


class SignupRequest(BaseModel):
    tenant_name: str
    email: str
    password: str
    name: str


# Which products each role may access (drives the nav + route guards).
# Front-line ops roles (processor/closer) work the pipeline; senior_uw is a
# broad decision-maker; the rest match the original gating.
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "super_admin": ["platform_studio", "pipeline", "analytics", "simulation", "audit", "settings"],
    "admin": ["pipeline", "analytics", "simulation", "audit", "settings"],
    "manager": ["pipeline", "analytics", "simulation", "audit"],
    "senior_uw": ["pipeline", "analytics", "simulation", "audit"],
    "underwriter": ["pipeline", "simulation"],
    "processor": ["pipeline"],
    "closer": ["pipeline"],
    "compliance": ["pipeline", "audit"],
    "viewer": ["pipeline"],
}
