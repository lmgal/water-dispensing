import hashlib
import hmac
from datetime import datetime, date, timedelta

from fastapi import APIRouter, Cookie, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from config import ADMIN_USERNAME, ADMIN_PASSWORD, SECRET_KEY, STATION_OFFLINE_THRESHOLD_SECONDS
from database import get_db
from events import event_manager
from models import DispensingRecord, Resident, Station

router = APIRouter(prefix="/admin", tags=["admin"])


def _tpl(request: Request, name: str, context: dict = {}):
    return request.app.state.templates.TemplateResponse(request, name, context=context)


def _make_token(username: str) -> str:
    return hmac.new(SECRET_KEY.encode(), username.encode(), hashlib.sha256).hexdigest()


def require_admin(request: Request, session_token: str = Cookie(default="")):
    expected = _make_token(ADMIN_USERNAME)
    if not session_token or not hmac.compare_digest(session_token, expected):
        return None  # signal: not authenticated
    return True


def _guard(auth=Depends(require_admin)):
    """Dependency that redirects to login if not authenticated."""
    if auth is None:
        raise _LoginRequired()


class _LoginRequired(Exception):
    pass


# --- Login / Logout (no auth required) ---

@router.get("/login")
def login_page(request: Request):
    return _tpl(request, "admin/login.html")


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        response = RedirectResponse("/admin", status_code=303)
        response.set_cookie("session_token", _make_token(username), httponly=True, samesite="lax")
        return response
    return _tpl(request, "admin/login.html", {"error": "Invalid username or password."})


@router.get("/logout")
def logout():
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie("session_token")
    return response


# --- Dashboard ---

@router.get("", dependencies=[Depends(_guard)])
def dashboard(request: Request, db: Session = Depends(get_db)):
    resident_count = db.query(Resident).filter(Resident.is_active == True).count()
    station_count = db.query(Station).count()
    cutoff = datetime.utcnow() - timedelta(seconds=STATION_OFFLINE_THRESHOLD_SECONDS)
    online_count = db.query(Station).filter(
        Station.is_online == True,
        Station.last_heartbeat != None,
        Station.last_heartbeat >= cutoff,
    ).count()

    today_volume = db.query(func.coalesce(func.sum(DispensingRecord.volume_ml), 0)).filter(
        func.date(DispensingRecord.started_at) == date.today()
    ).scalar()

    today_transactions = db.query(DispensingRecord).filter(
        func.date(DispensingRecord.started_at) == date.today()
    ).count()

    recent_records = (
        db.query(DispensingRecord)
        .order_by(DispensingRecord.started_at.desc())
        .limit(10)
        .all()
    )

    return _tpl(request, "admin/dashboard.html", {
        "resident_count": resident_count,
        "station_count": station_count,
        "online_count": online_count,
        "today_volume": float(today_volume),
        "today_transactions": today_transactions,
        "recent_records": recent_records,
    })


# --- Residents ---

@router.get("/residents", dependencies=[Depends(_guard)])
def residents_page(request: Request, db: Session = Depends(get_db)):
    residents = db.query(Resident).order_by(Resident.last_name).all()
    return _tpl(request, "admin/residents.html", {"residents": residents})


@router.get("/residents/search", dependencies=[Depends(_guard)])
def residents_search(request: Request, q: str = "", db: Session = Depends(get_db)):
    query = db.query(Resident)
    if q.strip():
        search = f"%{q.strip()}%"
        query = query.filter(
            (Resident.first_name.ilike(search))
            | (Resident.last_name.ilike(search))
            | (Resident.philsys_id.ilike(search))
        )
    residents = query.order_by(Resident.last_name).all()
    return _tpl(request, "partials/resident_table.html", {"residents": residents})


@router.post("/residents", dependencies=[Depends(_guard)])
async def create_resident(
    request: Request,
    philsys_id: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    address: str = Form(""),
    daily_limit_ml: int = Form(20_000),
    db: Session = Depends(get_db),
):
    existing = db.query(Resident).filter(Resident.philsys_id == philsys_id).first()
    if existing:
        return HTMLResponse(
            '<div id="toast" hx-swap-oob="innerHTML:#toast">'
            '<div class="toast error" x-data x-init="setTimeout(() => $el.remove(), 3000)">PhilSys ID already registered.</div>'
            '</div>',
        )

    resident = Resident(
        philsys_id=philsys_id,
        first_name=first_name,
        last_name=last_name,
        address=address,
        daily_limit_ml=daily_limit_ml,
    )
    db.add(resident)
    db.commit()
    db.refresh(resident)

    return _tpl(request, "partials/resident_row.html", {"r": resident})


@router.get("/residents/{resident_id}/edit", dependencies=[Depends(_guard)])
def edit_resident_form(resident_id: int, request: Request, db: Session = Depends(get_db)):
    resident = db.query(Resident).filter(Resident.id == resident_id).first()
    return _tpl(request, "partials/resident_form.html", {"r": resident})


@router.put("/residents/{resident_id}", dependencies=[Depends(_guard)])
async def update_resident(
    resident_id: int,
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    address: str = Form(""),
    daily_limit_ml: int = Form(20_000),
    db: Session = Depends(get_db),
):
    resident = db.query(Resident).filter(Resident.id == resident_id).first()
    if not resident:
        return HTMLResponse("Not found", status_code=404)

    resident.first_name = first_name
    resident.last_name = last_name
    resident.address = address
    resident.daily_limit_ml = daily_limit_ml
    resident.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(resident)

    return _tpl(request, "partials/resident_row.html", {"r": resident})


@router.delete("/residents/{resident_id}", dependencies=[Depends(_guard)])
async def delete_resident(resident_id: int, request: Request, db: Session = Depends(get_db)):
    resident = db.query(Resident).filter(Resident.id == resident_id).first()
    if not resident:
        return HTMLResponse("Not found", status_code=404)

    db.query(DispensingRecord).filter(DispensingRecord.resident_id == resident_id).delete()
    db.delete(resident)
    db.commit()

    return HTMLResponse("")


# --- Dispensing Log ---

@router.get("/dispensing", dependencies=[Depends(_guard)])
def dispensing_page(request: Request, db: Session = Depends(get_db)):
    records = (
        db.query(DispensingRecord)
        .order_by(DispensingRecord.started_at.desc())
        .limit(100)
        .all()
    )
    stations = db.query(Station).order_by(Station.name).all()
    return _tpl(request, "admin/dispensing.html", {
        "records": records,
        "stations": stations,
    })


@router.get("/dispensing/filter", dependencies=[Depends(_guard)])
def dispensing_filter(
    request: Request,
    station_id: int = 0,
    q: str = "",
    db: Session = Depends(get_db),
):
    query = db.query(DispensingRecord)
    if station_id:
        query = query.filter(DispensingRecord.station_id == station_id)
    if q.strip():
        search = f"%{q.strip()}%"
        query = query.join(Resident).filter(
            (Resident.first_name.ilike(search))
            | (Resident.last_name.ilike(search))
            | (Resident.philsys_id.ilike(search))
        )
    records = query.order_by(DispensingRecord.started_at.desc()).limit(100).all()
    return _tpl(request, "partials/dispense_table.html", {"records": records})


# --- Stations Management ---

@router.get("/stations", dependencies=[Depends(_guard)])
def stations_page(request: Request, db: Session = Depends(get_db)):
    stations = db.query(Station).order_by(Station.name).all()
    return _tpl(request, "admin/stations.html", {"stations": stations})


@router.post("/stations", dependencies=[Depends(_guard)])
async def create_station(
    request: Request,
    name: str = Form(...),
    location: str = Form(""),
    db: Session = Depends(get_db),
):
    existing = db.query(Station).filter(Station.name == name).first()
    if existing:
        return HTMLResponse(
            '<div id="toast" hx-swap-oob="innerHTML:#toast">'
            '<div class="toast error" x-data x-init="setTimeout(() => $el.remove(), 3000)">Station name already exists.</div>'
            '</div>',
        )

    station = Station(name=name, location=location)
    db.add(station)
    db.commit()

    await event_manager.publish("stations", f"new:{station.id}")

    stations = db.query(Station).order_by(Station.name).all()
    return _tpl(request, "partials/station_table_admin.html", {"stations": stations})


@router.put("/stations/{station_id}", dependencies=[Depends(_guard)])
async def update_station(
    station_id: int,
    request: Request,
    name: str = Form(...),
    location: str = Form(""),
    db: Session = Depends(get_db),
):
    station = db.query(Station).filter(Station.id == station_id).first()
    if not station:
        return HTMLResponse("Not found", status_code=404)

    station.name = name
    station.location = location
    db.commit()

    await event_manager.publish("stations", f"update:{station_id}")

    stations = db.query(Station).order_by(Station.name).all()
    return _tpl(request, "partials/station_table_admin.html", {"stations": stations})


@router.delete("/stations/{station_id}", dependencies=[Depends(_guard)])
async def delete_station(station_id: int, request: Request, db: Session = Depends(get_db)):
    station = db.query(Station).filter(Station.id == station_id).first()
    if not station:
        return HTMLResponse("Not found", status_code=404)

    db.delete(station)
    db.commit()

    await event_manager.publish("stations", f"delete:{station_id}")

    stations = db.query(Station).order_by(Station.name).all()
    return _tpl(request, "partials/station_table_admin.html", {"stations": stations})
