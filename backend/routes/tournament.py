from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from models.database import get_db, Tournament, TournamentFormat
from datetime import datetime
import uuid

router = APIRouter(prefix="/tournaments", tags=["Tournaments"])


# --- Request schema ---

class CreateTournamentRequest(BaseModel):
    name: str
    game: str
    format: str = "single_elimination"
    prize_pool: float = 0.0
    max_teams: int = 16


# --- Endpoints ---

@router.post("/")
def create_tournament(data: CreateTournamentRequest, db: Session = Depends(get_db)):
    tournament = Tournament(
        id=str(uuid.uuid4()),
        name=data.name,
        game=data.game,
        format=data.format,
        prize_pool=data.prize_pool,
        max_teams=data.max_teams,
    )
    db.add(tournament)
    db.commit()
    db.refresh(tournament)
    return {"message": "Tournament created", "tournament_id": tournament.id}


@router.get("/")
def list_tournaments(db: Session = Depends(get_db)):
    return db.query(Tournament).all()


@router.get("/{tournament_id}")
def get_tournament(tournament_id: str, db: Session = Depends(get_db)):
    t = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return t