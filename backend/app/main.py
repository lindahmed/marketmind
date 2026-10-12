from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import router
from app.auth import Db, enforce_origin
from app.config import get_settings

app = FastAPI(title="MarketMind AI", version="0.1.0", dependencies=[Depends(enforce_origin)])
app.add_middleware(CORSMiddleware, allow_origins=get_settings().allowed_origins,
                   allow_credentials=True, allow_methods=["GET", "POST", "PUT"],
                   allow_headers=["Content-Type", "X-Workspace-ID"])
app.include_router(router)


@app.get("/health")
def health(db: Db):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
