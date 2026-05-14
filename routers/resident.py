import calendar
import hashlib
import hmac
from datetime import date, datetime

from fastapi import APIRouter, Cookie, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from config import SECRET_KEY
from database import get_db
from models import DispensingRecord, Resident
from mosip import verify_qr

router = APIRouter(prefix="/resident", tags=["resident"])


def _tpl(request: Request, name: str, context: dict | None = None):
    return request.app.state.templates.TemplateResponse(request, name, context=context or {})


def _make_token(philsys_id: str) -> str:
    msg = f"resident:{philsys_id}".encode()
    return hmac.new(SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()


def _get_session_resident(
    db: Session,
    philsys_id: str | None,
    token: str | None,
) -> Resident | None:
    if not philsys_id or not token:
        return None
    if not hmac.compare_digest(token, _make_token(philsys_id)):
        return None
    resident = db.query(Resident).filter(Resident.philsys_id == philsys_id).first()
    if not resident or not resident.is_active:
        return None
    return resident


def _month_window(today: date) -> tuple[datetime, int]:
    """Return (month_start_datetime, days_in_month) for the month containing today."""
    start = datetime(today.year, today.month, 1)
    days = calendar.monthrange(today.year, today.month)[1]
    return start, days


@router.get("/login")
def login_page(request: Request):
    return _tpl(request, "resident/login.html")


@router.post("/login")
async def login_submit(
    request: Request,
    qr_data: str = Form(...),
    db: Session = Depends(get_db),
):
    result = await verify_qr(qr_data)
    if not result.verified:
        return _tpl(request, "resident/login.html", {"error": result.message or "Verification failed."})

    resident = db.query(Resident).filter(Resident.philsys_id == result.individual_id).first()
    if not resident:
        return _tpl(request, "resident/login.html", {
            "error": f"PhilSys ID {result.individual_id} is not registered with the water dispensing system.",
        })
    if not resident.is_active:
        return _tpl(request, "resident/login.html", {"error": "Your account has been deactivated."})

    response = RedirectResponse("/resident/portal", status_code=303)
    response.set_cookie(
        "resident_id",
        resident.philsys_id,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 8,
    )
    response.set_cookie(
        "resident_token",
        _make_token(resident.philsys_id),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 8,
    )
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse("/resident/login", status_code=303)
    response.delete_cookie("resident_id")
    response.delete_cookie("resident_token")
    return response


@router.get("/portal")
def portal(
    request: Request,
    resident_id: str = Cookie(default=""),
    resident_token: str = Cookie(default=""),
    db: Session = Depends(get_db),
):
    resident = _get_session_resident(db, resident_id or None, resident_token or None)
    if resident is None:
        return RedirectResponse("/resident/login", status_code=303)

    today = date.today()
    month_start, days_in_month = _month_window(today)
    month_label = today.strftime("%B %Y")

    monthly_quota_ml = resident.daily_limit_ml * days_in_month
    month_used_ml = float(
        db.query(func.coalesce(func.sum(DispensingRecord.volume_ml), 0))
        .filter(
            DispensingRecord.resident_id == resident.id,
            DispensingRecord.started_at >= month_start,
        )
        .scalar()
    )
    today_used_ml = float(
        db.query(func.coalesce(func.sum(DispensingRecord.volume_ml), 0))
        .filter(
            DispensingRecord.resident_id == resident.id,
            func.date(DispensingRecord.started_at) == today,
        )
        .scalar()
    )
    month_remaining_ml = max(0.0, monthly_quota_ml - month_used_ml)
    today_remaining_ml = max(0.0, resident.daily_limit_ml - today_used_ml)
    pct_used = min(100.0, (month_used_ml / monthly_quota_ml * 100) if monthly_quota_ml else 0.0)

    records = (
        db.query(DispensingRecord)
        .filter(
            DispensingRecord.resident_id == resident.id,
            DispensingRecord.started_at >= month_start,
        )
        .order_by(DispensingRecord.started_at.desc())
        .all()
    )

    return _tpl(request, "resident/portal.html", {
        "resident": resident,
        "month_label": month_label,
        "monthly_quota_ml": monthly_quota_ml,
        "month_used_ml": month_used_ml,
        "month_remaining_ml": month_remaining_ml,
        "today_used_ml": today_used_ml,
        "today_remaining_ml": today_remaining_ml,
        "pct_used": pct_used,
        "records": records,
    })
