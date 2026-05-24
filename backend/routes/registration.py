from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
import uuid

from models.database import get_db, Team, Player, Tournament, TournamentStatus 
    
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
    
    
  
    
    
# --- Endpoints ---

@router.post("/team")
def team_register(data: RegisterTeamRequest, db: Session = Depends(get_db)):
    """Creates a new team. Prevents registration if closed or if player already registered."""
    tournament = db.query(Tournament).filter(Tournament.id == data.tournament_id).first()
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
    
    if tournament.status != TournamentStatus.registration_open:
        raise HTTPException(
            status_code=400, 
            detail=f"Registration is closed. Current status: {tournament.status}"
        )
    
    # --- SAFETY CHECK: Ensure they sent at least one player! ---
    if not data.players:
        raise HTTPException(status_code=400, detail="A team must have at least one player.")
    
    captain_discord_id = data.players[0].discord_id
    
    # --- THE ANTI-SMURF GUARDRAIL ---
    if captain_discord_id:
        existing_team = db.query(Team).filter(
            Team.tournament_id == data.tournament_id,
            Team.captain_discord_id == captain_discord_id
        ).first()
        
        if existing_team:
            raise HTTPException(
                status_code=400, 
                detail=f"You are already registered! You are the captain of '{existing_team.name}'."
            )
    
    # Create the Team
    team = Team(
        id=str(uuid.uuid4()),
        tournament_id=data.tournament_id,
        name=data.team_name,
        contact=data.contact,
        is_verified=False,
        captain_discord_id=captain_discord_id 
    )
    db.add(team)

    # Create the Players
    for p in data.players:  
        player = Player(
            id=str(uuid.uuid4()),
            team_id=team.id,
            name=p.name,
            game_id=p.game_id
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
            "player_count": len(t.players),
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
        # 1. Count total players on the roster
        players = db.query(Player).filter(Player.team_id == team.id).all()
        
        # 2. Guardrail: Do they even have enough players to be verified?
        if len(players) < min_required:
            raise HTTPException(
                status_code=400, 
                detail=f"Cannot verify! This team only has {len(players)} player(s), but requires {min_required}."
            )
        
        # 3. Auto-Verify all players! (The "Approve All" feature)
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
    
    # 1. Update the individual player
    player.is_verified = data.is_verified
    db.commit()
    
    # 2. Auto-Sync the Team Status!
    team = db.query(Team).filter(Team.id == player.team_id).first()
    tournament = db.query(Tournament).filter(Tournament.id == team.tournament_id).first()
    min_required = tournament.min_players_per_team or 1
    
    verified_count = db.query(Player).filter(
        Player.team_id == team.id, 
        Player.is_verified == True
    ).count()
    
    # If they hit the minimum, auto-lock the team!
    if data.is_verified and verified_count >= min_required:
        team.is_verified = True
    
    # If they drop below the minimum, instantly break the team lock!
    elif not data.is_verified and verified_count < min_required:
        team.is_verified = False
        
    db.commit()
    
    return {"success": True, "message": f"Player set to {data.is_verified}. Team synced!"}
    
# @router.post("/teams/{team_id}/players")
# def add_player_to_team(team_id: str, data: PlayerInput, db: Session = Depends(get_db)):
#     """Admin endpoint to add a new player to an existing team with strict duplicate checks."""
    
#     # 1. Find the team to ensure it exists
#     team = db.query(Team).filter(Team.id == team_id).first()
#     if not team:
#         raise HTTPException(status_code=404, detail="Team not found")

#     # 2. THE ANTI-CLONE GUARDRAIL
#     # We join the Player and Team tables to check if this Game ID is 
#     # already registered ANYWHERE in this specific tournament!
#     duplicate_player = db.query(Player).join(Team).filter(
#         Team.tournament_id == team.tournament_id,
#         Player.game_id == data.game_id
#     ).first()

#     if duplicate_player:
#         raise HTTPException(
#             status_code=400,
#             detail=f"Duplicate detected! The ID '{data.game_id}' is already registered on '{duplicate_player.team.name}'."
#         )

#     # 3. Add the new player
#     new_player = Player(
#         id=str(uuid.uuid4()),
#         team_id=team.id,
#         name=data.name,
#         game_id=data.game_id
#     )
#     db.add(new_player)
#     db.commit()

#     return {"success": True, "message": f"{data.name} successfully added to the roster!"}


@router.post("/nlp-add-teammate")
def nlp_add_teammate(data: NLPAddPlayerRequest, db: Session = Depends(get_db)):
    # 1. Ensure a tournament is active
    active_tourney = db.query(Tournament).filter(Tournament.is_active == True).first()
    if not active_tourney:
        raise HTTPException(status_code=400, detail="There is no active tournament right now.")

    # 2. Verify the sender is actually a captain
    team = db.query(Team).filter(
        Team.tournament_id == active_tourney.id,
        Team.captain_discord_id == data.discord_id
    ).first()

    if not team:
        raise HTTPException(status_code=403, detail="Access Denied: You are not a registered captain in this tournament.")

    # 3. STRICT ROSTER INTEGRITY (Anti-Duplicate Check)
    duplicate_player = db.query(Player).join(Team).filter(
        Team.tournament_id == active_tourney.id,
        Player.game_id == data.new_player_game_id
    ).first()

    if duplicate_player:
        raise HTTPException(
            status_code=400,
            detail=f"Duplicate ID! The player '{data.new_player_game_id}' is already registered on '{duplicate_player.team.name}'."
        )

    # 4. Add the new player
    new_player = Player(
        id=str(uuid.uuid4()),
        team_id=team.id,
        name=data.new_player_name,
        game_id=data.new_player_game_id
    )
    db.add(new_player)

    # 5. REVOKE VERIFICATION FOR ADMIN REVIEW
    team.is_verified = False
    
    db.commit()

    return {
        "success": True, 
        "message": f"Successfully added {data.new_player_name} to your roster! Your team has been flagged as 'Pending Verification' for the Admin to review."
    }
    
@router.post("/nlp-edit-player")
def nlp_edit_player(data: NLPEditPlayerRequest, db: Session = Depends(get_db)):
    # 1. Active tournament & Captain check
    active_tourney = db.query(Tournament).filter(Tournament.is_active == True).first()
    if not active_tourney:
        raise HTTPException(status_code=400, detail="No active tournament.")

    team = db.query(Team).filter(
        Team.tournament_id == active_tourney.id,
        Team.captain_discord_id == data.discord_id
    ).first()

    if not team:
        raise HTTPException(status_code=403, detail="Access Denied: You are not a registered captain.")

    # 2. SMART TARGETING: Find the player they want to edit
    target_player = None
    identifier = str(data.target_original_identifier).lower()

    if identifier in ["me", "my", "myself", "captain", "none", "null"]:
        # The captain is always the first player created on the team
        target_player = team.players[0]
    else:
        # Search the roster for the old name or old ID
        for p in team.players:
            if identifier in p.name.lower() or identifier in p.game_id.lower():
                target_player = p
                break
                
    if not target_player:
        raise HTTPException(
            status_code=404, 
            detail=f"Could not find a player matching '{data.target_original_identifier}' on your roster."
        )

    # 3. ANTI-DUPLICATE GUARDRAIL (Only if they are changing the Game ID)
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

    # 4. Apply changes
    if data.new_player_name:
        target_player.name = data.new_player_name

    # 5. SECURITY LOCK: Revoke verification because details changed!
    target_player.is_verified = False
    team.is_verified = False
    
    db.commit()

    return {
        "success": True, 
        "message": f"Successfully updated player to **{target_player.name} ({target_player.game_id})**. Your team is now Pending Verification by the Admin."
    }
    
# @router.put("/players/{player_id}/verify")
# def verify_single_player(player_id: str, data: VerifyPlayerRequest, db: Session = Depends(get_db)):
#     """Admin endpoint to approve or reject a specific player's Game ID."""
#     from models.database import Player
    
#     player = db.query(Player).filter(Player.id == player_id).first()
#     if not player:
#         raise HTTPException(status_code=404, detail="Player not found")
    
#     player.is_verified = data.is_verified
#     db.commit()
    
#     return {"success": True, "message": f"Player verification set to {data.is_verified}"}