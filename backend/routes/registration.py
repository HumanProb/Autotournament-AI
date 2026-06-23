from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
import uuid

from models.database import get_db, Team, Player, Tournament

router = APIRouter(prefix="/register", tags=["Registration"])

# --- Schemas ---
class PlayerInput(BaseModel):
    name: str
    game_id: str
    discord_id: Optional[str] = None

class RegisterTeamRequest(BaseModel):
    tournament_id: str
    team_name: str
    contact: str
    players: List[PlayerInput]
    
class VerifyTeamRequest(BaseModel):
    is_verified: bool
    
class NLPAddPlayerRequest(BaseModel):
    discord_id: str
    new_player_name: str
    new_player_game_id: str
    
class VerifyPlayerRequest(BaseModel):
    is_verified: bool
    
class NLPEditPlayerRequest(BaseModel):
    discord_id: str
    target_original_identifier: Optional[str] = None
    new_player_name: Optional[str] = None
    new_player_game_id: Optional[str] = None
    
class AddTeammateRequest(BaseModel):
    discord_id: str
    new_player_name: str
    new_player_game_id: str
    new_player_discord_mention: Optional[str] = None
  
class ConfirmTeammateRequest(BaseModel):
    captain_discord_id: str
    new_player_name: str
    new_player_game_id: str
    new_discord_id: str
    
# --- Endpoints ---

@router.post("/team")
def team_register(data: RegisterTeamRequest, db: Session = Depends(get_db)):
    tournament = db.query(Tournament).filter(Tournament.id == data.tournament_id).first()
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    
    if tournament.status != "registration_open":
        raise HTTPException(
            status_code=400, 
            detail=f"Registration is closed. Current status is '{tournament.status}'."
        )
    
    if not data.players:
        raise HTTPException(status_code=400, detail="A team must have at least one player.")
    
    captain_discord_id = data.players[0].discord_id
    
    existing_team = db.query(Team).filter(
        Team.tournament_id == data.tournament_id,
        Team.name.ilike(data.team_name)
    ).first()
    
    if existing_team:
        raise HTTPException(
            status_code=400, 
            detail=f"The team name '{data.team_name}' is already taken!"
        )
        
    if captain_discord_id:
        existing_captain = db.query(Team).filter(
            Team.tournament_id == data.tournament_id,
            Team.captain_discord_id == captain_discord_id
        ).first()
        
        if existing_captain:
            raise HTTPException(
                status_code=400, 
                detail=f"You are already registered as captain of '{existing_captain.name}'."
            )
    
    team = Team(
        id=str(uuid.uuid4()),
        tournament_id=data.tournament_id,
        name=data.team_name,
        contact=data.contact,
        is_verified=False,
        captain_discord_id=captain_discord_id,
        player_count=len(data.players)  # ← put back so list_teams works
    )
    db.add(team)

    for p in data.players:  
        player = Player(
            id=str(uuid.uuid4()),
            team_id=team.id,
            name=p.name,
            game_id=p.game_id,
            discord_id=p.discord_id
        )
        db.add(player)
        
    db.commit()
    return {"message": "Team successfully Registered", "team_id": team.id}


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
            "player_count": t.player_count,
            "players": [{"id": p.id, "name": p.name, "game_id": p.game_id, "is_verified": p.is_verified} for p in t.players]
        })
    return result


@router.put("/teams/{team_id}/verify")
def verify_team(team_id: str, data: VerifyTeamRequest, db: Session = Depends(get_db)):
    """Admin endpoint to approve/reject a team. Now cascades to players!"""
    from models.database import Tournament, Player
    
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    
    tournament = db.query(Tournament).filter(Tournament.id == team.tournament_id).first()
    min_required = tournament.min_players_per_team or 1
    
    if data.is_verified:
        players = db.query(Player).filter(Player.team_id == team.id).all()
        
        if len(players) < min_required:
            raise HTTPException(
                status_code=400, 
                detail=f"Cannot verify! This team only has {len(players)} player(s), but requires {min_required}."
            )
        
        for p in players:
            p.is_verified = True
            
    team.is_verified = data.is_verified
    db.commit()
    
    return {
        "success": True, 
        "message": f"Team verification set to: {data.is_verified}",
        "is_verified": team.is_verified
    }

@router.put("/players/{player_id}/verify")
def verify_single_player(player_id: str, data: VerifyPlayerRequest, db: Session = Depends(get_db)):
    """Approves a single player and auto-syncs the Team status!"""
    from models.database import Player, Team, Tournament
    
    player = db.query(Player).filter(Player.id == player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    
    player.is_verified = data.is_verified
    db.commit()
    
    team = db.query(Team).filter(Team.id == player.team_id).first()
    tournament = db.query(Tournament).filter(Tournament.id == team.tournament_id).first()
    min_required = tournament.min_players_per_team or 1
    
    verified_count = db.query(Player).filter(
        Player.team_id == team.id, 
        Player.is_verified == True
    ).count()
    
    if data.is_verified and verified_count >= min_required:
        team.is_verified = True
    elif not data.is_verified and verified_count < min_required:
        team.is_verified = False
        
    db.commit()
    
    return {"success": True, "message": f"Player set to {data.is_verified}. Team synced!"}

@router.post("/nlp-add-teammate")
def nlp_add_teammate(data: AddTeammateRequest, db: Session = Depends(get_db)):
    from models.database import Team, Player
    import re
    
    team = db.query(Team).filter(Team.captain_discord_id == data.discord_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="You are not a registered captain!")

    clean_discord_id = None
    if data.new_player_discord_mention:
        match = re.search(r'\d+', data.new_player_discord_mention)
        if match:
            clean_discord_id = match.group()
            
    if not clean_discord_id:
        raise HTTPException(status_code=400, detail="You must ping the user in Discord to add them!")
        
    if clean_discord_id == data.discord_id:
        raise HTTPException(status_code=400, detail="You cannot invite yourself!")

    existing_player = db.query(Player).join(Team).filter(
        Team.tournament_id == team.tournament_id,
        Player.discord_id == clean_discord_id
    ).first()

    if existing_player:
        raise HTTPException(status_code=400, detail="This player is already registered in a team for this tournament!")

    return {
        "success": True, 
        "status": "pending_invite",
        "clean_discord_id": clean_discord_id,
        "team_name": team.name
    }

@router.post("/confirm-teammate")
def confirm_teammate(data: ConfirmTeammateRequest, db: Session = Depends(get_db)):
    from models.database import Team, Player
    import uuid
    
    team = db.query(Team).filter(Team.captain_discord_id == data.captain_discord_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Captain's team not found.")

    existing = db.query(Player).join(Team).filter(
        Team.tournament_id == team.tournament_id,
        Player.discord_id == data.new_discord_id
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Player joined another team while this invite was pending!")

    new_player = Player(
        id=str(uuid.uuid4()),
        team_id=team.id,
        name=data.new_player_name,
        game_id=data.new_player_game_id,
        discord_id=data.new_discord_id
    )
    db.add(new_player)
    team.player_count += 1
    db.commit()

    return {"success": True, "team_name": team.name}
    
@router.post("/nlp-edit-player")
def nlp_edit_player(data: NLPEditPlayerRequest, db: Session = Depends(get_db)):
    active_tourney = db.query(Tournament).filter(Tournament.is_active == True).first()
    if not active_tourney:
        raise HTTPException(status_code=400, detail="No active tournament.")

    team = db.query(Team).filter(
        Team.tournament_id == active_tourney.id,
        Team.captain_discord_id == data.discord_id
    ).first()

    if not team:
        raise HTTPException(status_code=403, detail="Access Denied: You are not a registered captain.")

    target_player = None
    identifier = str(data.target_original_identifier).lower()

    if identifier in ["me", "my", "myself", "captain", "none", "null"]:
        target_player = team.players[0]
    else:
        for p in team.players:
            if identifier in p.name.lower() or identifier in p.game_id.lower():
                target_player = p
                break
                
    if not target_player:
        raise HTTPException(
            status_code=404, 
            detail=f"Could not find a player matching '{data.target_original_identifier}' on your roster."
        )

    if data.new_player_game_id and data.new_player_game_id != target_player.game_id:
        duplicate = db.query(Player).join(Team).filter(
            Team.tournament_id == active_tourney.id,
            Player.game_id == data.new_player_game_id
        ).first()

        if duplicate:
            raise HTTPException(
                status_code=400,
                detail=f"Duplicate ID! '{data.new_player_game_id}' is already registered on '{duplicate.team.name}'."
            )
        target_player.game_id = data.new_player_game_id

    if data.new_player_name:
        target_player.name = data.new_player_name

    target_player.is_verified = False
    team.is_verified = False
    
    db.commit()

    return {
        "success": True, 
        "message": f"Successfully updated player to **{target_player.name} ({target_player.game_id})**. Your team is now Pending Verification by the Admin."
    }