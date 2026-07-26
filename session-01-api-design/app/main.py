from fastapi import FastAPI

from app.api.v1 import router as v1_router

app = FastAPI(title="session-01-api-design")
app.include_router(v1_router)
