from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.database import init_db
from app.observability.logging import configure_logging

configure_logging()

app = FastAPI(title="ResearchPulse", version="0.3.11")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


app.include_router(api_router)


@app.get("/health")
def health():
    return {"status": "ok"}
