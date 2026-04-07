from fastapi import FastAPI
from dotenv import load_dotenv
from models.database import init_db
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware

from routes.tournament import router as tournament_router
from routes.registration import router as registration_router
from routes.marketing import router as marketing_router


import os
load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup — runs before server accepts requests
    init_db()
    print("Database initialized")

    yield  # server is running and accepting requests here

    # shutdown — runs after server stops
    print("Server shutting down")


app = FastAPI(
    title="AutoTournament AI",
    description="Agentic E-Sports Tournament Platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, you lock this down to your exact domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
init_db()

# Register routes
app.include_router(tournament_router)
app.include_router(registration_router)
app.include_router(marketing_router)


@app.get("/")
def root():
    return {"status": "AutoTournament backend is running"}
