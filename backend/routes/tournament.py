from services.bracket_service import generate_full_bracket, update_match_result, advance_winner
from services.discord_service import post_to_channel, DiscordChannel
from services.llm_service import generate_hype_announcement
from models.database import get_db, Tournament, Match, TournamentFormat

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
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
    
class MatchReportRequest(BaseModel):
    team_a_showed: bool = True
    team_b_showed: bool = True
    winner_id: str | None = None  # None if it was a double forfeit



# --- Endpoints ---


@router.post("/create")
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

@router.get("/active")
def get_active_tournament(db: Session = Depends(get_db)):
    """
    Returns the currently active tournament.
    """
    # Now we explicitly filter for is_active == True!
    tournament = db.query(Tournament).filter(Tournament.is_active == True).first()
        
    if not tournament:
        raise HTTPException(status_code=404, detail="No active tournaments found.")
        
    return {
        "id": tournament.id, 
        "name": tournament.name
    }


@router.get("/{tournament_id}")
def get_tournament(tournament_id: str, db: Session = Depends(get_db)):
    t = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return t

@router.post("/{tournament_id}/generate-bracket")
def create_tournament_bracket(
    tournament_id: str, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    result = generate_full_bracket(db=db, tournament_id=tournament_id)
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
        
    # --- NEW: AI INTERCEPTION ---
    # Give the boring text to Gemini to spice up
    hyped_text = generate_hype_announcement(result["announcement_text"])
    
    # Send the HYPED text to Discord in the background
    background_tasks.add_task(
        post_to_channel,
        username="AI Shoutcaster",
        message=hyped_text,
        channel=DiscordChannel.TEST_CHANNEL
    )
        
    return result

@router.get("/{tournament_id}/matches")
def get_tournament_matches(tournament_id: str, db: Session = Depends(get_db)):
    """
    Fetches all generated matches for a specific tournament.
    """
    matches = db.query(Match).filter(Match.tournament_id == tournament_id).all()

    if not matches:
        raise HTTPException(
            status_code=404, detail="No matches found for this tournament yet."
        )

    return matches



@router.post("/{tournament_id}/matches/{match_id}/report")
def report_match_result(match_id: str, data: MatchReportRequest, db: Session = Depends(get_db)):
    """
    Host-only endpoint to report a match result. 
    Updates the match and advances the winner.
    """
    # 1. Update the match in the database
    updated_match = update_match_result(
        match_id=match_id,
        team_a_showed=data.team_a_showed,
        team_b_showed=data.team_b_showed,
        winner_id=data.winner_id,
        db=db
    )
    
    # 2. Only advance if someone actually won!
    if updated_match.winner_id:
        advance_winner(match=updated_match, db=db)
    
    return {
        "success": True, 
        "message": f"Match updated. Winner: {data.winner_id}",
        "status": updated_match.status
    }
    

@router.delete("/{tournament_id}/matches")
def reset_tournament_bracket(tournament_id: str, db: Session = Depends(get_db)):
    """
    DANGER ZONE: Deletes all matches associated with a tournament 
    so the host can generate a fresh bracket.
    """
    # 1. Find all matches for this specific tournament
    matches = db.query(Match).filter(Match.tournament_id == tournament_id).all()
    
    if not matches:
        raise HTTPException(status_code=404, detail="No bracket exists to delete.")
        
    # 2. Delete them one by one
    for match in matches:
        db.delete(match)
        
    # 3. Save the empty state to the database
    db.commit()
    
    return {"success": True, "message": "Bracket successfully wiped!"}