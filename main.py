from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from database import create_tables, engine
from routers import admin, api_resident, api_station, pages, resident, sse
from routers.admin import _LoginRequired

BASE_DIR = Path(__file__).resolve().parent


def _migrate_daily_to_monthly() -> None:
    with engine.connect() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(residents)").fetchall()}
        if "daily_limit_ml" in cols and "monthly_limit_ml" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE residents RENAME COLUMN daily_limit_ml TO monthly_limit_ml"
            )
            conn.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _migrate_daily_to_monthly()
    create_tables()
    yield


app = FastAPI(title="AquaTrack — Water Dispensing System", lifespan=lifespan)

# Static files & templates
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.state.templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Include routers
app.include_router(pages.router)
app.include_router(admin.router)
app.include_router(resident.router)
app.include_router(api_station.router)
app.include_router(api_resident.router)
app.include_router(sse.router)


@app.exception_handler(_LoginRequired)
async def login_required_handler(request: Request, exc: _LoginRequired):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Authentication required"}, status_code=401)
    return RedirectResponse("/admin/login", status_code=303)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
