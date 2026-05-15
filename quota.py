from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import DispensingRecord, Resident


def current_month_str(today: date | None = None) -> str:
    return (today or date.today()).strftime("%Y-%m")


def month_start(today: date | None = None) -> datetime:
    t = today or date.today()
    return datetime(t.year, t.month, 1)


def month_raw_used(db: Session, resident_id: int) -> float:
    return float(
        db.query(func.coalesce(func.sum(DispensingRecord.volume_ml), 0))
        .filter(
            DispensingRecord.resident_id == resident_id,
            DispensingRecord.started_at >= month_start(),
        )
        .scalar()
    )


def active_offset(resident: Resident) -> int:
    if resident.quota_offset_month == current_month_str():
        return resident.quota_offset_ml or 0
    return 0


def effective_used(db: Session, resident: Resident) -> float:
    return month_raw_used(db, resident.id) + active_offset(resident)


def effective_remaining(db: Session, resident: Resident) -> float:
    return max(0.0, resident.monthly_limit_ml - effective_used(db, resident))


def attach_remaining(db: Session, residents: list[Resident]) -> None:
    for r in residents:
        r.effective_remaining_ml = effective_remaining(db, r)
