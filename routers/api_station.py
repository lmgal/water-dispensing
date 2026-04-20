from datetime import datetime, date

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from events import event_manager
from models import DispensingRecord, Resident, Station
from mosip import verify_qr
from schemas import AuthRequest, AuthResponse, DispenseRequest, DispenseResponse, HeartbeatRequest

router = APIRouter(prefix="/api", tags=["hardware"])


def _get_api_key(x_api_key: str = Header(..., description="Station API key")) -> str:
    return x_api_key


def require_station_key(
    api_key: str = Depends(_get_api_key),
    db: Session = Depends(get_db),
) -> Station:
    """Validate X-API-Key header and return the matching station."""
    station = db.query(Station).filter(Station.api_key == api_key).first()
    if not station:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return station


def _get_today_usage(db: Session, resident_id: int) -> float:
    today = date.today()
    result = db.query(func.coalesce(func.sum(DispensingRecord.volume_ml), 0)).filter(
        DispensingRecord.resident_id == resident_id,
        func.date(DispensingRecord.started_at) == today,
    ).scalar()
    return float(result)


@router.post("/auth", response_model=AuthResponse)
async def auth_scan(req: AuthRequest, station: Station = Depends(require_station_key), db: Session = Depends(get_db)):
    """QR scan verification — called by ESP8266 after scanning PhilSys ID."""
    # Verify QR via simulated MOSIP
    mosip_result = await verify_qr(req.qr_data)
    if not mosip_result.verified:
        return AuthResponse(authorized=False, reason=mosip_result.message)

    # Look up resident by MOSIP individual ID (= PhilSys ID)
    resident = db.query(Resident).filter(
        Resident.philsys_id == mosip_result.individual_id
    ).first()
    if not resident:
        return AuthResponse(authorized=False, reason="Resident not registered in system.")

    if not resident.is_active:
        return AuthResponse(authorized=False, reason="Resident account is deactivated.")

    # Check daily limit
    used_today = _get_today_usage(db, resident.id)
    remaining = max(0, resident.daily_limit_ml - used_today)
    if remaining <= 0:
        return AuthResponse(authorized=False, reason="Daily water allocation exhausted.")

    # Publish auth event for SSE
    await event_manager.publish("dispense", f"auth:{resident.id}:{station.id}")

    return AuthResponse(
        authorized=True,
        resident_id=resident.id,
        remaining_ml=remaining,
    )


@router.post("/dispense", response_model=DispenseResponse)
async def record_dispense(req: DispenseRequest, station: Station = Depends(require_station_key), db: Session = Depends(get_db)):
    """Record completed dispensing — called by ESP8266 when pump stops."""
    resident = db.query(Resident).filter(Resident.id == req.resident_id).first()
    if not resident:
        return DispenseResponse(success=False, remaining_ml=0, message="Resident not found.")

    # Create dispensing record
    now = datetime.utcnow()
    record = DispensingRecord(
        resident_id=req.resident_id,
        station_id=req.station_id,
        volume_ml=req.volume_ml,
        status="completed",
        started_at=now,
        completed_at=now,
    )
    db.add(record)
    db.commit()

    # Calculate remaining
    used_today = _get_today_usage(db, req.resident_id)
    remaining = max(0, resident.daily_limit_ml - used_today)

    # Publish events for SSE
    await event_manager.publish("dispense", f"complete:{req.resident_id}:{req.station_id}:{req.volume_ml}")
    await event_manager.publish("admin", "dispense_update")

    return DispenseResponse(
        success=True,
        remaining_ml=remaining,
        message=f"Recorded {req.volume_ml:.0f} mL dispensed.",
    )


@router.post("/station/heartbeat")
async def station_heartbeat(req: HeartbeatRequest, station: Station = Depends(require_station_key), db: Session = Depends(get_db)):
    """Station heartbeat — called by ESP8266 every ~30 seconds."""
    station.is_online = True
    station.water_level = req.water_level
    station.last_heartbeat = datetime.utcnow()
    db.commit()

    # Publish station update for SSE
    await event_manager.publish("stations", f"heartbeat:{req.station_id}")

    return {"success": True}


@router.get("/station/{station_id}/status")
def station_status(station_id: int, station: Station = Depends(require_station_key), db: Session = Depends(get_db)):
    """Get station status — for ESP8266 or any client."""
    target = db.query(Station).filter(Station.id == station_id).first()
    if not target:
        return {"error": "Station not found"}
    return {
        "id": target.id,
        "name": target.name,
        "is_online": target.is_online,
        "water_level": target.water_level,
        "last_heartbeat": target.last_heartbeat.isoformat() if target.last_heartbeat else None,
    }
