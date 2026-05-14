"""Reset residents to match the QR codes in QR Codes/.

Wipes all residents (and their dispensing records) and re-creates the
team's four PhilSys identities. Stations are untouched.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal, create_tables
from models import DispensingRecord, Resident


RESIDENTS = [
    ("2170938143", "Anton",   "Gosiengfiao",       "UP AECH, Velasquez St., UP Diliman, Quezon City"),
    ("4360458298", "Emmerson", "Isip",             "UP AECH, Velasquez St., UP Diliman, Quezon City"),
    ("7352816436", "Jakin",    "Mishle Bacalla",   "UP AECH, Velasquez St., UP Diliman, Quezon City"),
    ("4619436753", "Kharis",   "Arielle Ann Hipe", "UP AECH, Velasquez St., UP Diliman, Quezon City"),
]


def reset():
    create_tables()
    db = SessionLocal()
    try:
        deleted_records = db.query(DispensingRecord).delete()
        deleted_residents = db.query(Resident).delete()
        db.flush()
        for uin, first, last, addr in RESIDENTS:
            db.add(Resident(
                philsys_id=uin,
                first_name=first,
                last_name=last,
                address=addr,
                daily_limit_ml=20_000,
            ))
        db.commit()
        print(f"Removed {deleted_residents} residents and {deleted_records} records.")
        print(f"Added {len(RESIDENTS)} residents from QR codes.")
    finally:
        db.close()


if __name__ == "__main__":
    reset()
