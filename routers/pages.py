from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import DispensingRecord, Resident, Station

router = APIRouter(tags=["pages"])


@router.get("/")
def index(request: Request, db: Session = Depends(get_db)):
    stations = db.query(Station).order_by(Station.name).all()
    online_count = sum(1 for s in stations if s.is_online_effective)

    today_volume = db.query(func.coalesce(func.sum(DispensingRecord.volume_ml), 0)).filter(
        func.date(DispensingRecord.started_at) == date.today()
    ).scalar()

    return request.app.state.templates.TemplateResponse(
        request, "index.html",
        context={
            "stations": stations,
            "online_count": online_count,
            "total_stations": len(stations),
            "today_volume": float(today_volume),
        },
    )


@router.get("/history/search")
def history_search(request: Request, q: str = "", db: Session = Depends(get_db)):
    records = []
    resident = None
    if q.strip():
        resident = db.query(Resident).filter(Resident.philsys_id == q.strip()).first()
        if resident:
            records = (
                db.query(DispensingRecord)
                .filter(DispensingRecord.resident_id == resident.id)
                .order_by(DispensingRecord.started_at.desc())
                .limit(50)
                .all()
            )

    return request.app.state.templates.TemplateResponse(
        request, "partials/history_table.html",
        context={
            "records": records,
            "resident": resident,
            "query": q.strip(),
        },
    )
