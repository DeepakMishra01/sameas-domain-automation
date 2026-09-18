"""DERE HTTP application entry point."""

from fastapi import FastAPI

from apps.api.routes.features import router as features_router
from apps.api.routes.health import router as health_router
from apps.api.routes.matching import router as matching_router
from apps.api.routes.observations import router as observations_router
from apps.api.routes.resolution import router as resolution_router

app = FastAPI(title="Domain Entity Resolution System", version="0.1.0")
app.include_router(health_router)
app.include_router(observations_router)
app.include_router(features_router)
app.include_router(matching_router)
app.include_router(resolution_router)
