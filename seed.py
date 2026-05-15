"""Seed demo data into the database."""

from datetime import datetime, timedelta
import random
import sys
import os

# Ensure the script can find local modules
sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal, create_tables
from models import DispensingRecord, Resident, Station


RESIDENTS = [
    ("PSN-2024-00001", "Juan", "Dela Cruz", "123 Rizal St, Brgy. Uno, Manila"),
    ("PSN-2024-00002", "Maria", "Santos", "45 Bonifacio Ave, Brgy. Dos, Manila"),
    ("PSN-2024-00003", "Jose", "Reyes", "78 Mabini Rd, Brgy. Tres, Manila"),
    ("PSN-2024-00004", "Ana", "Garcia", "12 Luna St, Brgy. Cuatro, Manila"),
    ("PSN-2024-00005", "Pedro", "Ramos", "56 Aguinaldo Blvd, Brgy. Cinco, Manila"),
    ("PSN-2024-00006", "Rosa", "Mendoza", "90 Del Pilar St, Brgy. Seis, Manila"),
    ("PSN-2024-00007", "Carlos", "Villanueva", "34 Quezon Ave, Brgy. Siete, Manila"),
    ("PSN-2024-00008", "Elena", "Bautista", "67 Magsaysay St, Brgy. Ocho, Manila"),
]

STATIONS = [
    ("Station Alpha", "UP AECH, Velasquez St., UP Diliman, Quezon City"),
]


def seed():
    create_tables()
    db = SessionLocal()
    try:
        # Check if already seeded
        if db.query(Resident).count() > 0:
            print("Database already has data. Skipping seed.")
            return

        # Seed residents
        residents = []
        for philsys_id, first, last, addr in RESIDENTS:
            r = Resident(
                philsys_id=philsys_id,
                first_name=first,
                last_name=last,
                address=addr,
                monthly_limit_ml=20_000,
            )
            db.add(r)
            residents.append(r)
        db.flush()
        print(f"Seeded {len(residents)} residents.")

        # Seed stations
        stations = []
        for name, location in STATIONS:
            s = Station(
                name=name,
                location=location,
                is_online=True,
                water_level=random.randint(40, 95),
                last_heartbeat=datetime.utcnow() - timedelta(seconds=random.randint(5, 30)),
            )
            db.add(s)
            stations.append(s)
        db.flush()
        print(f"Seeded {len(stations)} stations.")

        # Seed dispensing records (past few days)
        records = []
        for day_offset in range(5):
            base_time = datetime.utcnow() - timedelta(days=day_offset)
            num_records = random.randint(3, 8)
            for _ in range(num_records):
                r = random.choice(residents)
                s = random.choice(stations)
                started = base_time.replace(
                    hour=random.randint(6, 18),
                    minute=random.randint(0, 59),
                )
                volume = random.randint(1000, 8000)
                record = DispensingRecord(
                    resident_id=r.id,
                    station_id=s.id,
                    volume_ml=volume,
                    status="completed",
                    started_at=started,
                    completed_at=started + timedelta(seconds=volume // 50),
                )
                db.add(record)
                records.append(record)

        db.commit()
        print(f"Seeded {len(records)} dispensing records.")
        print("Done!")

    finally:
        db.close()


if __name__ == "__main__":
    seed()
