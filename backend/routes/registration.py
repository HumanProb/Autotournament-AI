from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from models.database import get_db, Team, Player, Tournament
from typing import List
import uuid

router = APIRouter(prefix="/register", tags=["Registration"])

class PlayerInput(BaseModel):
    name: str
    game_id: str

class RegisterTeamRequest(BaseModel):
    tournament_id: str
    team_name: str
    contact: str
    players: List[PlayerInput]

@router.post("/team")
def team_register(data: RegisterTeamRequest, db: Session = Depends(get_db)):
    """creates a neew team in database if tournamnet not found or team already exists or player name already exists sends error"""
    tournament = db.query(Tournament).filter(Tournament.id == data.tournament_id).first()
    if not tournament:
        raise HTTPException(status_code=404,detail="Tournamnet not found")
    
    existing = db.query(Team).filter(
        Team.tournament_id == data.tournament_id,
        Team.name == data.team_name
    ).first()
    if existing:
        raise HTTPException(status_code=400,detail="Team already exists change the name of your team")
    
    team = Team(
        id=str(uuid.uuid4()),
        tournament_id=data.tournament_id,
        name=data.team_name,
        contact=data.contact     
    )
    db.add(team)

    for p in data.players:  
        player = Player(
            id=str(uuid.uuid4()),
            team_id=team.id,
            name=p.name,
            game_id=p.game_id
        )
        db.add(player)
    
    db.commit()
    return {"message":"Team successfullt Registered","team_id":team.id}


@router.get("/teams/{tournament_id}")
def list_teams(tournament_id: str, db: Session = Depends(get_db)):
    teams = db.query(Team).filter(Team.tournament_id == tournament_id).all()
    return teams

