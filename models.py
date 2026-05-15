import secrets
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from config import STATION_OFFLINE_THRESHOLD_SECONDS
from database import Base


class Resident(Base):
    __tablename__ = "residents"

    id = Column(Integer, primary_key=True, index=True)
    philsys_id = Column(String(20), unique=True, nullable=False, index=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    address = Column(Text, default="")
    is_active = Column(Boolean, default=True)
    monthly_limit_ml = Column(Integer, default=20_000)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    dispensing_records = relationship("DispensingRecord", back_populates="resident")

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class Station(Base):
    __tablename__ = "stations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)
    location = Column(String(200), default="")
    api_key = Column(String(64), unique=True, nullable=False, default=lambda: secrets.token_hex(32))
    is_online = Column(Boolean, default=False)
    water_level = Column(Integer, default=100)
    last_heartbeat = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    dispensing_records = relationship("DispensingRecord", back_populates="station")

    @property
    def is_online_effective(self) -> bool:
        if not self.is_online or self.last_heartbeat is None:
            return False
        return (datetime.utcnow() - self.last_heartbeat).total_seconds() <= STATION_OFFLINE_THRESHOLD_SECONDS


class DispensingRecord(Base):
    __tablename__ = "dispensing_records"

    id = Column(Integer, primary_key=True, index=True)
    resident_id = Column(Integer, ForeignKey("residents.id"), nullable=False)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    volume_ml = Column(Float, default=0)
    status = Column(String(20), default="completed")
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    resident = relationship("Resident", back_populates="dispensing_records")
    station = relationship("Station", back_populates="dispensing_records")
