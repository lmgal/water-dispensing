from datetime import datetime
from typing import Optional

from pydantic import BaseModel


# --- Resident ---

class ResidentCreate(BaseModel):
    philsys_id: str
    first_name: str
    last_name: str
    address: str = ""
    daily_limit_ml: int = 20_000


class ResidentUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    address: Optional[str] = None
    is_active: Optional[bool] = None
    daily_limit_ml: Optional[int] = None


class ResidentResponse(BaseModel):
    id: int
    philsys_id: str
    first_name: str
    last_name: str
    address: str
    is_active: bool
    daily_limit_ml: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --- Station ---

class StationCreate(BaseModel):
    name: str
    location: str = ""


class StationUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None


class StationResponse(BaseModel):
    id: int
    name: str
    location: str
    is_online: bool
    water_level: int
    last_heartbeat: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


# --- Hardware API ---

class AuthRequest(BaseModel):
    station_id: int
    qr_data: str


class AuthResponse(BaseModel):
    authorized: bool
    resident_id: Optional[int] = None
    remaining_ml: Optional[float] = None
    reason: Optional[str] = None


class DispenseRequest(BaseModel):
    station_id: int
    resident_id: int
    volume_ml: float


class DispenseResponse(BaseModel):
    success: bool
    remaining_ml: float
    message: str = ""


class HeartbeatRequest(BaseModel):
    station_id: int
    water_level: int


# --- Dispensing Record ---

class DispensingRecordResponse(BaseModel):
    id: int
    resident_id: int
    station_id: int
    volume_ml: float
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    resident_name: str = ""
    station_name: str = ""

    class Config:
        from_attributes = True
