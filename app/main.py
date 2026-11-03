from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.v1 import mines, batches

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(mines.router, prefix=f"{settings.API_V1_STR}/mines", tags=["Mines"])
app.include_router(batches.router, prefix=f"{settings.API_V1_STR}/sample-batches", tags=["Sample Batches"])

@app.get("/")
def root():
    return {"status": "ok", "message": "Chromite API Backend is running"}