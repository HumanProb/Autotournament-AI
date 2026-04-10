from services.bracket_service import generate_full_bracket, update_match_result, advance_winner
from services.discord_service import post_to_channel, DiscordChannel
from services.llm_service import generate_hype_announcement
from models.database import get_db, Tournament, Match, TournamentFormat, MatchStatus, Team

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
    
class PlayerReportScoreRequest(BaseModel):
    reporting_team_id: str
    reported_winner_id: str



# --- Endpoints ---
async def hype_and_post_pipeline(raw_match_data: str):
    """Runs the LLM and the Discord webhook in the background so the UI doesn't freeze."""
    try:
        # Step A: The Brain (Gemini) makes the text awesome
        hype_text = generate_hype_announcement(raw_match_data)
        
        # Step B: The Mouth (Webhook) sends it to Discord
        await post_to_channel(
            username="Tournament AI", 
            message=hype_text, 
            channel=DiscordChannel.ANNOUNCEMENT
        )
    except Exception as e:
        print(f"Background Pipeline Failed: {e}")

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
    # Order by created_at descending so we get the newest one
    tournament = db.query(Tournament).filter(Tournament.is_active == True).order_by(Tournament.created_at.desc()).first()
    if not tournament:
        raise HTTPException(status_code=404, detail="No active tournament found")
    return tournament


@router.get("/{tournament_id}")
def get_tournament(tournament_id: str, db: Session = Depends(get_db)):
    t = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return t

@router.post("/{tournament_id}/generate-bracket")
def generate_bracket(
    tournament_id: str, 
    background_tasks: BackgroundTasks, 
    db: Session = Depends(get_db)
):
    # Build the bracket (takes milliseconds)
    result = generate_full_bracket(db=db, tournament_id=tournament_id)
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message"))
        
    # Grab the boring, raw text
    raw_announcement = result.get("announcement_text")
    
    # --- FIRE AND FORGET! ---
    # Hand the boring text to the background pipeline to process while we reply to React!
    background_tasks.add_task(hype_and_post_pipeline, raw_announcement)
    
    # Instantly reply to the React dashboard
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
def report_match_result(
    tournament_id: str, 
    match_id: str, 
    data: MatchReportRequest, 
    background_tasks: BackgroundTasks, # <--- NEW: We need background tasks to call the Discord webhook
    db: Session = Depends(get_db)
):
    try:
        updated_match = update_match_result(
            match_id=match_id,
            team_a_showed=data.team_a_showed,
            team_b_showed=data.team_b_showed,
            winner_id=data.winner_id,
            db=db
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    if updated_match.winner_id:
        # Check if this was the final match!
        is_finale = advance_winner(match=updated_match, db=db)
        
        if is_finale:
            # --- THE GRAND FINALE FIREWORKS ---
            tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
            winner = db.query(Team).filter(Team.id == updated_match.winner_id).first()
            
            raw_finale_text = f"GRAND FINALE CONCLUDED! The tournament {tournament.name} is officially OVER! The ultimate champion is {winner.name}! They secure the prize pool of Rs.{tournament.prize_pool}! Praise them!"
            
            # Send the boring text to Gemini so it can scream about it in Discord!
            background_tasks.add_task(hype_and_post_pipeline, raw_finale_text)

    return {"success": True, "status": updated_match.status}

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

@router.post("/{tournament_id}/matches/{match_id}/player-report")
def player_report_score(
    tournament_id: str,
    match_id: str,
    data: PlayerReportScoreRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    if match.status not in [MatchStatus.pending, MatchStatus.live]:
        raise HTTPException(status_code=400, detail="Match is already closed or disputed.")

    # 1. Record the vote
    if data.reporting_team_id == match.team_a_id:
        match.team_a_reported_winner_id = data.reported_winner_id
    elif data.reporting_team_id == match.team_b_id:
        match.team_b_reported_winner_id = data.reported_winner_id
    else:
        raise HTTPException(status_code=403, detail="Team is not in this match!")

    db.commit()

    # 2. Check for Agreement
    # If both teams have submitted a report...
    if match.team_a_reported_winner_id and match.team_b_reported_winner_id:
        
        # Did they say the same team won?
        if match.team_a_reported_winner_id == match.team_b_reported_winner_id:
            
            # THE AGREEMENT: They agree! Auto-resolve the match.
            try:
                updated_match = update_match_result(
                    match_id=match.id,
                    team_a_showed=True,
                    team_b_showed=True,
                    winner_id=match.team_a_reported_winner_id,
                    db=db
                )
                advance_winner(match=updated_match, db=db)
                
                # Fire the Hype Bot to celebrate!
                winner_name = "Team A" if updated_match.winner_id == match.team_a_id else "Team B"
                announcement = f"🚨 MATCH RESULT! {winner_name} just secured the bag in Round {match.round_number}! The bracket advances!"
                background_tasks.add_task(hype_and_post_pipeline, announcement)
                
                return {"success": True, "status": "completed", "message": "Both teams agreed. Match resolved!"}
                
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
                
        else:
            # THE CONFLICT: They disagree! Lock the match down.
            match.status = MatchStatus.disputed
            db.commit()
            
            # Ping admins in Discord
            admin_alert = f"⚠️ **ADMIN NEEDED!** Dispute in Round {match.round_number}. Both teams claim they won. Check the dashboard!"
            background_tasks.add_task(post_to_channel, username="AutoTournament Security", message=admin_alert, channel=DiscordChannel.ANNOUNCEMENT)
            
            return {"success": False, "status": "disputed", "message": "Scores conflict. Admins have been notified."}

    return {"success": True, "status": "waiting", "message": "Score recorded. Waiting for opponent to confirm."}