from datetime import datetime

from fastapi import APIRouter, Request
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from database import get_db, SessionLocal
from events import event_manager
from models import DispensingRecord, Station

router = APIRouter(prefix="/sse", tags=["sse"])


def _render_station_card(station: Station) -> str:
    """Render a single station card as HTML for SSE push."""
    effective_online = station.is_online_effective
    status_class = "online" if effective_online else "offline"
    status_text = "Online" if effective_online else "Offline"
    level = station.water_level if effective_online else 0
    level_class = "level-good" if level > 30 else ("level-low" if level > 10 else "level-critical")

    heartbeat_text = ""
    if station.last_heartbeat:
        delta = datetime.utcnow() - station.last_heartbeat
        if delta.total_seconds() < 60:
            heartbeat_text = "Just now"
        elif delta.total_seconds() < 3600:
            heartbeat_text = f"{int(delta.total_seconds() // 60)}m ago"
        else:
            heartbeat_text = f"{int(delta.total_seconds() // 3600)}h ago"

    return f'''<div class="station-card {status_class}" id="station-{station.id}">
  <div class="station-header">
    <h3>{station.name}</h3>
    <span class="status-badge {status_class}">{status_text}</span>
  </div>
  <p class="station-location">{station.location or "No location set"}</p>
  <div class="water-level">
    <div class="water-level-bar {level_class}" style="width: {level}%"></div>
    <span class="water-level-text">{level}%</span>
  </div>
  <p class="heartbeat">Last seen: {heartbeat_text or "Never"}</p>
</div>'''


def _render_station_list_html(db: Session) -> str:
    """Render full station list HTML."""
    stations = db.query(Station).order_by(Station.name).all()
    if not stations:
        return '<p class="empty-state">No stations registered yet.</p>'
    return "\n".join(_render_station_card(s) for s in stations)


def _render_dispense_html(db: Session) -> str:
    """Render recent dispensing activity HTML."""
    records = (
        db.query(DispensingRecord)
        .order_by(DispensingRecord.started_at.desc())
        .limit(5)
        .all()
    )
    if not records:
        return '<p class="empty-state">No dispensing activity yet.</p>'

    rows = []
    for r in records:
        rows.append(
            f'<div class="dispense-item">'
            f'<span class="dispense-station">{r.station.name}</span>'
            f'<span class="dispense-volume">{r.volume_ml:.0f} mL</span>'
            f'<span class="dispense-time">{r.started_at.strftime("%H:%M")}</span>'
            f'</div>'
        )
    return "\n".join(rows)


@router.get("/stations")
async def sse_stations(request: Request):
    """SSE stream for station status updates."""

    async def generate():
        # Send initial state
        db = SessionLocal()
        try:
            html = _render_station_list_html(db)
        finally:
            db.close()
        yield {"event": "station-update", "data": html}

        # Stream updates
        async for _ in event_manager.subscribe("stations"):
            if await request.is_disconnected():
                break
            db = SessionLocal()
            try:
                html = _render_station_list_html(db)
            finally:
                db.close()
            yield {"event": "station-update", "data": html}

    return EventSourceResponse(generate())


@router.get("/dispense")
async def sse_dispense(request: Request):
    """SSE stream for dispensing activity updates."""

    async def generate():
        # Send initial state
        db = SessionLocal()
        try:
            html = _render_dispense_html(db)
        finally:
            db.close()
        yield {"event": "dispense-update", "data": html}

        # Stream updates
        async for _ in event_manager.subscribe("dispense"):
            if await request.is_disconnected():
                break
            db = SessionLocal()
            try:
                html = _render_dispense_html(db)
            finally:
                db.close()
            yield {"event": "dispense-update", "data": html}

    return EventSourceResponse(generate())


@router.get("/admin")
async def sse_admin(request: Request):
    """SSE stream for admin dashboard updates."""

    async def generate():
        # Stream updates on any admin-relevant event
        async for _ in event_manager.subscribe("admin"):
            if await request.is_disconnected():
                break
            yield {"event": "admin-update", "data": "refresh"}

    return EventSourceResponse(generate())
