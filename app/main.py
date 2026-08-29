import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .database import Base, engine
from .routers import assign, experiments, results, track

logging.basicConfig(level=logging.INFO)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Experiment Platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(experiments.router)
app.include_router(assign.router)
app.include_router(track.router)
app.include_router(results.router)

app.mount("/", StaticFiles(directory="static", html=True), name="static")
