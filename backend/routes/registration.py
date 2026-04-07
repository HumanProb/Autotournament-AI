from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
# ---> We added TournamentStatus to your imports here!
from models.database import get_db, Team, Player, Tournament, TournamentStatus 
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
    
class VerifyTeamRequest(BaseModel):
    is_verified: bool

@router.post("/team")
def team_register(data: RegisterTeamRequest, db: Session = Depends(get_db)):
    """creates a new team in database if tournament not found or team already exists sends error"""
    tournament = db.query(Tournament).filter(Tournament.id == data.tournament_id).first()
    if not tournament:
        raise HTTPException(status_code=404,detail="Tournament not found")
        
    # --- NEW: THE LOCKDOWN ---
    # Reject registrations if the admin hasn't opened the gates!
    if tournament.status != TournamentStatus.registration_open:
        raise HTTPException(
            status_code=400, 
            detail=f"Registration is closed. Current status: {tournament.status}"
        )
    # -------------------------
    
    # Your excellent anti-collision check
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
        contact=data.contact,
        is_verified=False
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
    return {"message":"Team successfully Registered","team_id":team.id}

@router.get("/teams/{tournament_id}")
def list_teams(tournament_id: str, db: Session = Depends(get_db)):
    """Fetches all teams and packages their players so the dashboard can see them."""
    teams = db.query(Team).filter(Team.tournament_id == tournament_id).all()
    
    result = []
    for t in teams:
        result.append({
            "id": t.id,
            "name": t.name,
            "contact": t.contact,
            "is_verified": t.is_verified,
            "player_count": len(t.players),
            "players": [{"name": p.name, "game_id": p.game_id} for p in t.players]
        })
    return result

@router.put("/teams/{team_id}/verify")
def verify_team(team_id: str, data: VerifyTeamRequest, db: Session = Depends(get_db)):
    """Admin endpoint to approve or reject a team."""
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    
    team.is_verified = data.is_verified
    db.commit()
    return {"success": True, "message": f"Team verification set to: {data.is_verified}"}