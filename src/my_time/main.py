import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from .api import router
from .work_api import router as work_router
from .hr_api import router as hr_router
from .config import settings
from .website import router as website_router
from .portfolio import router as portfolio_router
from .google_reviews import router as reviews_router
from .jobs.scheduler import run_scheduler


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(run_scheduler()) if settings.RUN_SCHEDULER else None
    yield
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="my_time API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS,
                   allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])
app.include_router(router)
app.include_router(work_router)
app.include_router(hr_router)
app.include_router(website_router)
app.include_router(portfolio_router)
app.include_router(reviews_router)


@app.exception_handler(IntegrityError)
async def constraint_conflict(request, exc):
    # Includes conflicts raised during flush, before a route reaches save().
    return JSONResponse(status_code=409, content={"detail":"Record conflicts with existing data"})


@app.get("/healthz")
def health():
    return {"status": "ok"}
