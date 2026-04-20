from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import DispensingRecord, Resident
from routers.admin import _guard
from schemas import ResidentCreate, ResidentResponse, ResidentUpdate

router = APIRouter(prefix="/api/residents", tags=["residents-api"], dependencies=[Depends(_guard)])


@router.get("", response_model=list[ResidentResponse])
def list_residents(db: Session = Depends(get_db)):
    return db.query(Resident).order_by(Resident.last_name).all()


@router.get("/{resident_id}", response_model=ResidentResponse)
def get_resident(resident_id: int, db: Session = Depends(get_db)):
    resident = db.query(Resident).filter(Resident.id == resident_id).first()
    if not resident:
        raise HTTPException(status_code=404, detail="Resident not found")
    return resident


@router.post("", response_model=ResidentResponse, status_code=201)
def create_resident(data: ResidentCreate, db: Session = Depends(get_db)):
    existing = db.query(Resident).filter(Resident.philsys_id == data.philsys_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="PhilSys ID already registered")
    resident = Resident(**data.model_dump())
    db.add(resident)
    db.commit()
    db.refresh(resident)
    return resident


@router.put("/{resident_id}", response_model=ResidentResponse)
def update_resident(resident_id: int, data: ResidentUpdate, db: Session = Depends(get_db)):
    resident = db.query(Resident).filter(Resident.id == resident_id).first()
    if not resident:
        raise HTTPException(status_code=404, detail="Resident not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(resident, key, value)
    resident.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(resident)
    return resident


@router.delete("/{resident_id}")
def delete_resident(resident_id: int, db: Session = Depends(get_db)):
    resident = db.query(Resident).filter(Resident.id == resident_id).first()
    if not resident:
        raise HTTPException(status_code=404, detail="Resident not found")
    name = resident.full_name
    db.query(DispensingRecord).filter(DispensingRecord.resident_id == resident_id).delete()
    db.delete(resident)
    db.commit()
    return {"success": True, "message": f"Resident {name} deleted."}
