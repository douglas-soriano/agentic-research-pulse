from fastapi import APIRouter
from .topics import router as topics_router
from .reviews import router as reviews_router
from .traces import router as traces_router
from .stream import router as stream_router
from .metrics import router as metrics_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(topics_router)
api_router.include_router(reviews_router)
api_router.include_router(traces_router)
api_router.include_router(stream_router)
api_router.include_router(metrics_router)
