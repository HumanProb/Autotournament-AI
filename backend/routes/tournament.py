from services.bracket_service import generate_round_1, update_match_result, advance_winner
from services.discord_service import post_to_channel, DiscordChannel
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


@router.get("/{tournament_id}")
def get_tournament(tournament_id: str, db: Session = Depends(get_db)):
    t = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return t


@router.post("/{tournament_id}/generate-bracket")
def create_tournament_bracket(
    tournament_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    """
    Triggers the algorithm to close registration and generate Round 1.
    """
    result = generate_round_1(db=db, tournament_id=tournament_id)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    # Hand the webhook off to the background worker!
    background_tasks.add_task(
        post_to_channel,
        username="AutoTournament Engine",
        message=result["announcement_text"],
        channel=DiscordChannel.TEST_CHANNEL,
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

@router.post("/matches/{match_id}/report")
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
    
    # 2. Advance the winner to the next bracket slot
    advance_winner(match=updated_match, db=db)
    
    return {
        "success": True, 
        "message": f"Match updated. Winner: {data.winner_id}",
        "status": updated_match.status
    }