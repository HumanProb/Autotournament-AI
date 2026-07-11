from services.bracket_service import generate_full_bracket, update_match_result, advance_winner
from services.discord_service import post_to_channel, DiscordChannel
from services.llm_service import generate_hype_announcement, parse_discord_intent
from models.database import get_db, Tournament, Match, TournamentFormat, MatchStatus, Team
from models.database import AgentMemory, PlatformType

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone, timedelta

import uuid
import httpx
import os

router = APIRouter(prefix="/tournaments", tags=["Tournaments"])

# --- Request schema ---

class CreateTournamentRequest(BaseModel):
    name: str
    game: str
    format: str = "single_elimination"
    prize_pool: float = 0.0
    entry_fee: float = 0.0
    max_teams: int = 16
    min_players_per_team: int = 1
    max_players_per_team: int = 5
    scheduled_start: Optional[datetime] = None
    minutes_between_rounds: int = 120
    prep_time: int = 30
    
class UpdateMatchTimeRequest(BaseModel):
    scheduled_time: datetime
   
class TournamentScheduleUpdate(BaseModel):
    scheduled_start: datetime
    minutes_between_rounds: int
    prep_time: int
    
class MatchReportRequest(BaseModel):
    team_a_showed: bool = True
    team_b_showed: bool = True
    winner_id: str | None = None
    
class PlayerReportScoreRequest(BaseModel):
    reporting_team_discord_id: str
    reported_winner_id: str

class NLPRequest(BaseModel):
    message: str
    discord_id: str
    timestamp: str

class UpdateStatusRequest(BaseModel):
    status: str
    
class NLPScoreReport(BaseModel):
    discord_id: str
    reported_winner: Optional[str] = None
    reported_loser: Optional[str] = None 
    round_number: Optional[int] = None
    match_number: Optional[int] = None
    channel_id: Optional[str] = None
    
class MatchReport(BaseModel):
    team_a_showed: bool
    team_b_showed: bool
    winner_id: Optional[str] = None
    
class UpdateRoomRequest(BaseModel):
    channel_id: Optional[str] = None
    
class EditTeamRequest(BaseModel):
    discord_id: str
    new_team_name: str
    target_original_identifier: Optional[str] = None
    new_player_discord_mention: Optional[str] = None

class SyncFlags(BaseModel):
    roles: bool = False
    channels: bool = False

# --- Helper function ---
    
def log_analytics_event(db: Session, tournament_id: str, event_type: str, description: str):
    from models.database import TournamentEventLog
    import uuid
    from datetime import datetime, timezone
    
    event = TournamentEventLog(
        id=str(uuid.uuid4()),
        tournament_id=tournament_id,
        event_type=event_type,
        description=description,
        timestamp=datetime.now(timezone.utc)
    )
    db.add(event)
    db.commit()  

def process_consensus_logic(db: Session, match, team_id: str, winner_id: str):
    from models.database import MatchStatus
    
    if team_id == match.team_a_id:
        match.team_a_reported_winner_id = winner_id
    else:
        match.team_b_reported_winner_id = winner_id
    db.commit()

    vote_a = match.team_a_reported_winner_id
    vote_b = match.team_b_reported_winner_id
    
    if vote_a and vote_b:
        if vote_a == vote_b:
            match.winner_id = vote_a
            match.loser_id = match.team_a_id if vote_a == match.team_b_id else match.team_b_id
            match.status = "completed"
            db.commit()
            return {"status": "completed", "winner_id": vote_a}
        else:
            match.status = MatchStatus.disputed
            db.commit()
            return {"status": "disputed"}
            
    return {"status": "waiting"}

# --- Endpoints ---
def hype_and_post_pipeline(tournament_id: str, raw_match_data: str):
    from models.database import SessionLocal, PlatformType
    db = SessionLocal() 
    try:
        hype_text = generate_hype_announcement(raw_match_data)
        log_and_broadcast(tournament_id=tournament_id, content=hype_text, db=db, platform="discord")
    except Exception as e:
        print(f"Background Pipeline Failed: {e}")
    finally:
        db.close() 

def log_and_broadcast(tournament_id: str, content: str, db: Session, platform: str = "discord"):
    """Saves to memory and adds a task for the Discord Bot to pick up."""
    new_id = str(uuid.uuid4())
    new_memory = AgentMemory(
        id=new_id,
        tournament_id=tournament_id,
        platform=platform,
        content=content
    )
    db.add(new_memory)
    
    if platform == "discord":
        from models.database import PendingDiscordTask
        task = PendingDiscordTask(tournament_id=tournament_id, task_type=f"broadcast_{new_id}")
        db.add(task)
        
    db.commit()

# ==========================================
# FRONTEND TASK QUEUE & CONTEXT ENDPOINTS
# ==========================================

class SetContextRequest(BaseModel):
    tournament_id: str

@router.put("/users/{discord_id}/context")
def set_user_context(discord_id: str, data: SetContextRequest, db: Session = Depends(get_db)):
    from models.database import UserSession
    session = db.query(UserSession).filter(UserSession.discord_id == discord_id).first()
    if not session:
        session = UserSession(discord_id=discord_id, last_tournament_id=data.tournament_id)
        db.add(session)
    else:
        session.last_tournament_id = data.tournament_id
    db.commit()
    return {"success": True}

@router.get("/users/{discord_id}/context")
def get_user_context(discord_id: str, db: Session = Depends(get_db)):
    from models.database import UserSession, Tournament
    session = db.query(UserSession).filter(UserSession.discord_id == discord_id).first()
    if not session or not session.last_tournament_id:
        raise HTTPException(status_code=404, detail="No context")
    
    t = db.query(Tournament).filter(Tournament.id == session.last_tournament_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return {"tournament_id": t.id, "tournament_name": t.name}

@router.post("/{tournament_id}/post-join-link")
def post_join_link(tournament_id: str, db: Session = Depends(get_db)):
    from models.database import PendingDiscordTask
    task = PendingDiscordTask(tournament_id=tournament_id, task_type="post_join_button")
    db.add(task)
    db.commit()
    return {"success": True, "message": "Signal sent to Discord bot."}

@router.get("/admin/pending-tasks")
def get_pending_tasks(db: Session = Depends(get_db)):
    from models.database import PendingDiscordTask
    tasks = db.query(PendingDiscordTask).all()
    return [{"id": t.id, "tournament_id": t.tournament_id, "task_type": t.task_type} for t in tasks]

@router.delete("/admin/pending-tasks/{task_id}")
def clear_pending_task(task_id: str, db: Session = Depends(get_db)):
    from models.database import PendingDiscordTask
    task = db.query(PendingDiscordTask).filter(PendingDiscordTask.id == task_id).first()
    if task:
        db.delete(task)
        db.commit()
    return {"success": True}

@router.get("/admin/trash-bin")
def get_trash_bin(db: Session = Depends(get_db)):
    from models.database import ChannelTrashBin
    items = db.query(ChannelTrashBin).all()
    return [{"id": item.id, "channel_id": item.discord_channel_id} for item in items]

@router.delete("/admin/trash-bin/{trash_id}")
def delete_trash_item(trash_id: str, db: Session = Depends(get_db)):
    from models.database import ChannelTrashBin
    item = db.query(ChannelTrashBin).filter(ChannelTrashBin.id == trash_id).first()
    if item:
        db.delete(item)
        db.commit()
    return {"success": True}


# ==========================================
# STANDARD TOURNAMENT ENDPOINTS
# ==========================================

@router.post("/create")
def create_tournament(data: CreateTournamentRequest, db: Session = Depends(get_db)):
    existing_tournaments = db.query(Tournament).count()
    make_active = existing_tournaments == 0 

    new_tournament = Tournament(
        id=str(uuid.uuid4()),
        name=data.name,
        game=data.game,
        format=data.format,
        prize_pool=data.prize_pool,
        entry_fee=data.entry_fee,
        min_players_per_team=data.min_players_per_team,
        max_players_per_team=data.max_players_per_team,
        is_active=make_active,
        status="draft",
        scheduled_start=data.scheduled_start,
        minutes_between_rounds=data.minutes_between_rounds,
        prep_time=data.prep_time
    )
    db.add(new_tournament)
    db.commit()
    db.refresh(new_tournament)
    
    return new_tournament

@router.get("/")
def list_tournaments(db: Session = Depends(get_db)):
    return db.query(Tournament).all()

@router.get("/active")
def get_active_tournament(db: Session = Depends(get_db)):
    tournament = db.query(Tournament).filter(Tournament.is_active == True).order_by(Tournament.created_at.desc()).first()
    if not tournament:
        raise HTTPException(status_code=404, detail="No active tournament found")
    return tournament

@router.get("/active-captains")
def get_active_captains(db: Session = Depends(get_db)):
    from models.database import Tournament, Team
    active_tourney = db.query(Tournament).filter(Tournament.is_active == True).first()
    if not active_tourney: return [] 
    teams = db.query(Team).filter(Team.tournament_id == active_tourney.id).all()
    return [t.captain_discord_id for t in teams if t.captain_discord_id]

@router.get("/matches/need-rooms")
def get_matches_needing_rooms(db: Session = Depends(get_db)):
    from models.database import Match, Team
    matches = db.query(Match).filter(
        Match.discord_channel_id == None,
        Match.team_a_id != None,
        Match.team_b_id != None,
        Match.status == "pending"
    ).all()

    results = []
    for m in matches:
        team_a = db.query(Team).filter(Team.id == m.team_a_id).first()
        team_b = db.query(Team).filter(Team.id == m.team_b_id).first()
        
        if team_a and team_b:
            results.append({
                "match_id": m.id,
                "tournament_id": m.tournament_id,
                "team_a_name": team_a.name,
                "team_b_name": team_b.name,
                "team_a_id": m.team_a_id,
                "team_b_id": m.team_b_id,
                "captain_a_discord": team_a.captain_discord_id,
                "captain_b_discord": team_b.captain_discord_id,
                "round_number": m.round_number,
                "match_number": m.match_number,
                "scheduled_time": m.scheduled_time.isoformat() if m.scheduled_time else None
            })
    return results

@router.get("/matches/need-cleanup")
def get_matches_needing_cleanup(db: Session = Depends(get_db)):
    from models.database import Match, Team
    
    # 🚨 STRICT FILTER: Only grab matches that definitely have a channel ID
    matches = db.query(Match).filter(
        Match.discord_channel_id.isnot(None),
        Match.discord_channel_id != "",
        Match.status.in_(["completed", "walkover", "double_forfeit", "bye"])
    ).all()
    
    results = []
    for m in matches:
        winner_name = "Nobody"
        if m.winner_id:
            winner_team = db.query(Team).filter(Team.id == m.winner_id).first()
            if winner_team: winner_name = winner_team.name
            
        results.append({
            "match_id": m.id, 
            "channel_id": m.discord_channel_id,
            "winner_name": winner_name
        })
        
    return results

@router.put("/matches/{match_id}/room")
def update_match_room(match_id: str, data: UpdateRoomRequest, db: Session = Depends(get_db)):   
    from models.database import Match
    match = db.query(Match).filter(Match.id == match_id).first()
    if match:
        match.discord_channel_id = data.channel_id
        db.commit()
    return {"success": True}

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
    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found.")
        
    if tournament.status in ["in_progress", "live", "completed"]:
        raise HTTPException(
            status_code=400, 
            detail="Cannot generate a new bracket! The tournament has already started."
        )
        
    if tournament.status == "draft" or tournament.status == "registration_open":
        tournament.status = "in_progress"
        db.commit()

    result = generate_full_bracket(db=db, tournament_id=tournament_id)
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message"))

    log_analytics_event(db, tournament_id, "bracket_generated", f"Bracket generated with {tournament.format}.")

    from models.database import Match, Team
    r1_matches = db.query(Match).filter(
        Match.tournament_id == tournament_id,
        Match.round_number == 1
    ).order_by(Match.match_number.asc()).all()

    if r1_matches:
        schedule_msg = f"**{tournament.name} BRACKET GENERATED**\nRound 1 match schedules are officially set:\n\n"
        for m in r1_matches:
            team_a = db.query(Team).filter(Team.id == m.team_a_id).first()
            team_b = db.query(Team).filter(Team.id == m.team_b_id).first()
            name_a = team_a.name if team_a else "TBD"
            name_b = team_b.name if team_b else "TBD"
            
            time_str = f"<t:{int(m.scheduled_time.timestamp())}:t>" if m.scheduled_time else "TBD"
            schedule_msg += f"• **Match {m.match_number}:** {name_a} vs {name_b} **{time_str}**\n"
            
        schedule_msg += "\nPrivate match rooms are spawning. Get ready players!"
        log_and_broadcast(tournament_id=tournament_id, content=schedule_msg, db=db, platform="discord")

    return result

@router.get("/{tournament_id}/matches")
def get_tournament_matches(tournament_id: str, db: Session = Depends(get_db)):
    matches = db.query(Match).filter(Match.tournament_id == tournament_id).all()
    if not matches:
        raise HTTPException(
            status_code=404, detail="No matches found for this tournament yet."
        )
    return matches

@router.get("/{tournament_id}/standings")
def get_tournament_standings(tournament_id: str, db: Session = Depends(get_db)):
    from models.database import Team, Match
    
    teams = db.query(Team).filter(Team.tournament_id == tournament_id).all()
    matches = db.query(Match).filter(
        Match.tournament_id == tournament_id,
        Match.status.in_(["completed", "walkover"]) 
    ).all()

    scoreboard = {
        team.id: {"id": team.id, "name": team.name, "wins": 0, "losses": 0, "points": 0, "played": 0} 
        for team in teams
    }

    for match in matches:
        if match.winner_id and match.winner_id in scoreboard:
            scoreboard[match.winner_id]["wins"] += 1
            scoreboard[match.winner_id]["points"] += 3
            scoreboard[match.winner_id]["played"] += 1
            
        if match.loser_id and match.loser_id in scoreboard:
            scoreboard[match.loser_id]["losses"] += 1
            scoreboard[match.loser_id]["played"] += 1

    sorted_standings = sorted(scoreboard.values(), key=lambda x: (x["points"], x["wins"]), reverse=True)
    return sorted_standings

@router.get("/{tournament_id}/logs")
def get_tournament_logs(tournament_id: str, db: Session = Depends(get_db)):
    from models.database import AgentMemory
    logs = db.query(AgentMemory).filter(
        AgentMemory.tournament_id == tournament_id
    ).order_by(AgentMemory.timestamp.desc()).all()
    return logs

@router.post("/{tournament_id}/announce")
def announce_tournament_start(tournament_id: str, db: Session = Depends(get_db)):
    from models.database import Tournament, PlatformType, AgentMemory, PendingDiscordTask
    from services.llm_service import generate_tournament_content
    
    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")

    date_str = tournament.scheduled_start.strftime("%Y-%m-%d %H:%M") if tournament.scheduled_start else "Coming Soon!"
    
    content_dict = generate_tournament_content(
        game=tournament.game, 
        prize=float(tournament.prize_pool), 
        entry_fee=float(tournament.entry_fee),
        date=date_str
    )

    if "discord_announcement" in content_dict:
        new_memory = AgentMemory(
            tournament_id=tournament.id,
            platform="discord",
            content=content_dict["discord_announcement"]
        )
        db.add(new_memory)
        task = PendingDiscordTask(tournament_id=tournament.id, task_type="post_announcement")
        db.add(task)

    if "instagram_caption" in content_dict:
        log_and_broadcast(tournament_id=tournament.id, content=content_dict["instagram_caption"], db=db, platform="instagram")
        
    if "whatsapp_forward" in content_dict:
        log_and_broadcast(tournament_id=tournament.id, content=content_dict["whatsapp_forward"], db=db, platform="whatsapp")
        
    if "poster_image_prompt" in content_dict:
        log_and_broadcast(tournament_id=tournament.id, content=content_dict["poster_image_prompt"], db=db, platform="poster")

    db.commit()
    return {"success": True, "message": "Campaign generated! Discord bot will post the Join Link shortly."}

@router.get("/{tournament_id}/analytics")
def get_tournament_analytics(tournament_id: str, db: Session = Depends(get_db)):
    from models.database import TournamentEventLog, Match
    
    total_matches = db.query(Match).filter(Match.tournament_id == tournament_id).count()
    completed_matches = db.query(Match).filter(
        Match.tournament_id == tournament_id, 
        Match.status.in_(["completed", "walkover", "double_forfeit", "bye"]) 
    ).count()
    
    disputes = db.query(TournamentEventLog).filter(
        TournamentEventLog.tournament_id == tournament_id,
        TournamentEventLog.event_type == "dispute"
    ).count()
    
    progress_percentage = (completed_matches / total_matches * 100) if total_matches > 0 else 0
    
    logs = db.query(TournamentEventLog).filter(
        TournamentEventLog.tournament_id == tournament_id
    ).order_by(TournamentEventLog.timestamp.asc()).all()
    
    log_text = "\n".join([f"[{l.timestamp.strftime('%H:%M')}] {l.description}" for l in logs])
    
    try:
        from services.llm_service import generate_analytics_report 
        llm_insights = generate_analytics_report(log_text)
    except (ImportError, Exception) as e:
        llm_insights = f"Analytics AI unavailable: {e}"
    
    return {
        "stats": {
            "progress": round(progress_percentage, 1),
            "matches_played": completed_matches,
            "disputes": disputes
        },
        "insights": llm_insights
    }

@router.put("/{tournament_id}/schedule")
def update_tournament_schedule(
    tournament_id: str, 
    data: TournamentScheduleUpdate,
    db: Session = Depends(get_db)
):
    from models.database import Tournament, Match, MatchStatus
    from datetime import datetime, timezone, timedelta
    
    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
        
    start_time = data.scheduled_start
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    
    tournament.scheduled_start = start_time
    tournament.minutes_between_rounds = data.minutes_between_rounds
    tournament.prep_time = data.prep_time
    
    matches = db.query(Match).filter(Match.tournament_id == tournament.id).all()
    for match in matches:
        if match.status in [MatchStatus.pending, MatchStatus.disputed]:
            minutes_offset = (match.round_number - 1) * data.minutes_between_rounds
            match.scheduled_time = start_time + timedelta(minutes=data.prep_time) + timedelta(minutes=minutes_offset)
            
    db.commit()
    return {"success": True, "message": "Schedule updated."}

@router.get("/{tournament_id}/rosters")
def get_tournament_rosters(tournament_id: str, db: Session = Depends(get_db)):
    from models.database import Team, Player
    
    teams = db.query(Team).filter(Team.tournament_id == tournament_id).all()
    result = []
    
    for t in teams:
        players = db.query(Player).filter(Player.team_id == t.id).all()
        result.append({
            "team_name": t.name,
            "captain_discord_id": t.captain_discord_id,
            "player_discord_ids": [p.discord_id for p in players if p.discord_id],
            "verified_player_ids": [p.discord_id for p in players if p.discord_id and p.is_verified]
        })
        
    return result

@router.put("/{tournament_id}/matches/{match_id}/time")
def update_individual_match_time(
    tournament_id: str, 
    match_id: str, 
    data: UpdateMatchTimeRequest, 
    db: Session = Depends(get_db)
):
    from models.database import Match
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
        
    scheduled_time = data.scheduled_time
    if scheduled_time.tzinfo is None:
        scheduled_time = scheduled_time.replace(tzinfo=timezone.utc)
        
    match.scheduled_time = scheduled_time
    db.commit()
    
    return {"success": True, "message": "Individual match time updated!"}

@router.post("/{tournament_id}/admin/sync-roles")
def request_role_sync(tournament_id: str, db: Session = Depends(get_db)):
    t = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if t:
        t.sync_roles_requested = True
        db.commit()
    return {"success": True, "message": "Role sync requested!"}

@router.post("/{tournament_id}/admin/sync-channels")
def request_channel_sync(tournament_id: str, db: Session = Depends(get_db)):
    t = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if t:
        t.sync_channels_requested = True
        db.commit()
    return {"success": True, "message": "Channel sync requested!"}

@router.post("/{tournament_id}/admin/force-reset-channels")
def force_reset_channels(tournament_id: str, db: Session = Depends(get_db)):
    from models.database import Match
    matches = db.query(Match).filter(Match.tournament_id == tournament_id).all()
    
    count = 0
    for m in matches:
        if m.status in ["pending", "live"]:
            m.discord_channel_id = None
            count += 1
            
    db.commit()
    return {"success": True, "message": f"Wiped {count} channel IDs."}

# 🚨 THE MISSING ENDPOINT THAT CAUSED THE INFINITE ERROR LOOP 🚨
@router.post("/{tournament_id}/admin/reset-flags")
def reset_admin_flags(tournament_id: str, data: SyncFlags, db: Session = Depends(get_db)):
    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if tournament:
        if data.roles:
            tournament.sync_roles_requested = False
        if data.channels:
            tournament.sync_channels_requested = False
        db.commit()
    return {"success": True}

@router.delete("/{tournament_id}/matches")
def reset_tournament_bracket(tournament_id: str, db: Session = Depends(get_db)):
    from models.database import Match, ChannelTrashBin
    
    matches = db.query(Match).filter(Match.tournament_id == tournament_id).all()
    if not matches:
        raise HTTPException(status_code=404, detail="No bracket exists to delete.")
        
    for match in matches:
        if match.discord_channel_id:
            trash = ChannelTrashBin(discord_channel_id=match.discord_channel_id)
            db.add(trash)
        db.delete(match)
        
    db.commit()
    return {"success": True, "message": "Bracket wiped! Discord channels will be deleted shortly."}

@router.post("/{tournament_id}/matches/{match_id}/report")
def admin_report_match(tournament_id: str, match_id: str, data: MatchReport, db: Session = Depends(get_db)):
    from models.database import Match, Team, PlatformType
    import asyncio
    
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    match.winner_id = data.winner_id
    if data.winner_id:
        match.loser_id = match.team_a_id if data.winner_id == match.team_b_id else match.team_b_id
        match.status = "completed"
    else:
        match.status = "double_forfeit" 
    
    db.commit()
    
    team_a = db.query(Team).filter(Team.id == match.team_a_id).first()
    team_b = db.query(Team).filter(Team.id == match.team_b_id).first()
    team_a_name = team_a.name if team_a else "TBD"
    team_b_name = team_b.name if team_b else "TBD"
    winner_name = team_a_name if data.winner_id == match.team_a_id else team_b_name
    loser_name = team_b_name if data.winner_id == match.team_a_id else team_a_name
    
    if data.winner_id:
        log_analytics_event(db, tournament_id, "match_complete", f"{winner_name} defeated {loser_name} via Admin Override in Round {match.round_number}.")
    else:
        log_analytics_event(db, tournament_id, "dispute", f"Double forfeit/DQ declared in Round {match.round_number}.")

    next_match = None
    if match.next_match_id and data.winner_id:
        next_match = db.query(Match).filter(Match.id == match.next_match_id).first()
        if next_match:
            if not next_match.team_a_id:
                next_match.team_a_id = data.winner_id
            elif not next_match.team_b_id:
                next_match.team_b_id = data.winner_id
            db.commit()
    
    loser_next_id = getattr(match, "loser_next_match_id", None)
    if loser_next_id and match.loser_id:
        loser_match = db.query(Match).filter(Match.id == loser_next_id).first()
        if loser_match:
            if not loser_match.team_a_id:
                loser_match.team_a_id = match.loser_id
            elif not loser_match.team_b_id:
                loser_match.team_b_id = match.loser_id
            db.commit()

    if data.winner_id:
        result_msg = f"**ADMIN OVERRIDE**\n**{winner_name}** has defeated **{loser_name}** in Round {match.round_number}!"
        next_match_msg = ""
        if next_match:
            opp_id = next_match.team_b_id if next_match.team_a_id == data.winner_id else next_match.team_a_id
            if opp_id:
                opponent = db.query(Team).filter(Team.id == opp_id).first()
                opp_name = opponent.name if opponent else "TBD"
                next_match_msg = f"\n\n**UP NEXT:** **{winner_name}** vs **{opp_name}** in Round {next_match.round_number}!"
            else:
                next_match_msg = f"\n\n**{winner_name}** advances to Round {next_match.round_number} and is waiting for an opponent."

        full_announcement = result_msg + next_match_msg
        log_and_broadcast(tournament_id=tournament_id, content=full_announcement, db=db, platform="discord")

        total_pending = db.query(Match).filter(
            Match.tournament_id == tournament_id,
            Match.status.in_(["pending", "live", "disputed"])
        ).count()

        if total_pending == 0:
            tourney = db.query(Tournament).filter(Tournament.id == tournament_id).first()
            if tourney:
                tourney.status = "completed"
                db.commit()
                
            tourney_msg = f"**TOURNAMENT COMPLETE!**\nCongratulations to **{winner_name}** for winning the championship!"
            log_and_broadcast(tournament_id=tournament_id, content=tourney_msg, db=db, platform="discord")
            
        else:
            pending_in_round = db.query(Match).filter(
                Match.tournament_id == tournament_id,
                Match.round_number == match.round_number,
                Match.status.in_(["pending", "live", "disputed"])
            ).count()

            if pending_in_round == 0:
                round_msg = f"**ROUND {match.round_number} IS OFFICIALLY COMPLETE!**\nAll scores have been reported and verified. Get ready for the next round!"
                log_and_broadcast(tournament_id=tournament_id, content=round_msg, db=db, platform="discord")

    return {"success": True, "message": "Match updated, logged to memory, and announced!"}

@router.post("/{tournament_id}/matches/{match_id}/undo")
def admin_undo_match(tournament_id: str, match_id: str, db: Session = Depends(get_db)):
    from models.database import Match, MatchStatus
    
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    if match.status in [MatchStatus.pending, MatchStatus.live]:
        raise HTTPException(status_code=400, detail="This match is not completed yet!")

    if match.next_match_id:
        next_match = db.query(Match).filter(Match.id == match.next_match_id).first()
        if next_match:
            if next_match.status not in [MatchStatus.pending]:
                raise HTTPException(
                    status_code=400, 
                    detail="Cannot undo! The winner has already started playing their NEXT match. You must undo that match first."
                )
            
            if next_match.team_a_id == match.winner_id:
                next_match.team_a_id = None
            elif next_match.team_b_id == match.winner_id:
                next_match.team_b_id = None
                
    loser_next_id = getattr(match, "loser_next_match_id", None)
    if loser_next_id and match.loser_id:
        loser_match = db.query(Match).filter(Match.id == loser_next_id).first()
        if loser_match:
            if loser_match.team_a_id == match.loser_id:
                loser_match.team_a_id = None
            elif loser_match.team_b_id == match.loser_id:
                loser_match.team_b_id = None

    match.winner_id = None
    match.loser_id = None
    match.team_a_reported_winner_id = None
    match.team_b_reported_winner_id = None
    match.status = MatchStatus.pending

    db.commit()

    undo_msg = f"**ADMIN ROLLBACK**\nThe results for Match {match.match_number} (Round {match.round_number}) have been undone. The match is live again!"
    log_and_broadcast(tournament_id=tournament_id, content=undo_msg, db=db, platform="discord")

    return {"success": True, "message": "Match successfully undone and bracket rolled back."}

@router.post("/{tournament_id}/matches/{match_id}/player-report")
def player_report_score(
    tournament_id: str,
    match_id: str,
    data: PlayerReportScoreRequest,
    db: Session = Depends(get_db)
):
    import asyncio
    from models.database import Team, MatchStatus, PlatformType
    
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    reporting_team = db.query(Team).filter(
        Team.captain_discord_id == data.reporting_team_discord_id,
        (Team.id == match.team_a_id) | (Team.id == match.team_b_id)
    ).first()

    if not reporting_team:
        raise HTTPException(status_code=403, detail="You must be the captain of a team in this match to report.")

    if reporting_team.id != match.team_a_id and reporting_team.id != match.team_b_id:
        raise HTTPException(status_code=403, detail="Your team is not in this match!")

    if match.status not in [MatchStatus.pending, MatchStatus.live]:
        raise HTTPException(status_code=400, detail="Match is already closed or disputed.")

    result = process_consensus_logic(db, match, reporting_team.id, data.reported_winner_id)
    
    if result["status"] == "completed":
        advance_winner(match, db) 
        team_a = db.query(Team).filter(Team.id == match.team_a_id).first()
        team_b = db.query(Team).filter(Team.id == match.team_b_id).first()
        winner_id = result["winner_id"]
        
        winner_name = team_a.name if winner_id == team_a.id else team_b.name
        loser_name = team_b.name if winner_id == team_a.id else team_a.name
        
        log_analytics_event(db, tournament_id, "match_complete", f"{winner_name} defeated {loser_name} in Round {match.round_number}.")
        
        announcement = f"**MATCH RESULT**\n**{winner_name}** has defeated **{loser_name}** in Round {match.round_number}! The bracket advances!"
        log_and_broadcast(tournament_id=tournament_id, content=announcement, db=db, platform="discord")
        
        total_pending = db.query(Match).filter(
            Match.tournament_id == tournament_id,
            Match.status.in_(["pending", "live", "disputed"])
        ).count()

        if total_pending == 0:
            tourney = db.query(Tournament).filter(Tournament.id == tournament_id).first()
            if tourney:
                tourney.status = "completed"
                db.commit()
                
            tourney_msg = f"**TOURNAMENT COMPLETE!**\nCongratulations to **{winner_name}** for winning the championship!"
            log_and_broadcast(tournament_id=tournament_id, content=tourney_msg, db=db, platform="discord")
            
        else:
            pending_in_round = db.query(Match).filter(
                Match.tournament_id == tournament_id,
                Match.round_number == match.round_number,
                Match.status.in_(["pending", "live", "disputed"])
            ).count()

            if pending_in_round == 0:
                round_msg = f"**ROUND {match.round_number} IS OFFICIALLY COMPLETE!**\nGet ready for the next round!"
                log_and_broadcast(tournament_id=tournament_id, content=round_msg, db=db, platform="discord")

        return {"success": True, "status": "completed", "message": "Both teams agreed!"}
        
    elif result["status"] == "disputed":
        team_a = db.query(Team).filter(Team.id == match.team_a_id).first()
        team_b = db.query(Team).filter(Team.id == match.team_b_id).first()
        
        log_analytics_event(db, tournament_id, "dispute", f"Dispute in Round {match.round_number} between {team_a.name} and {team_b.name}.")
        
        admin_alert = f"**ADMIN NEEDED!** Dispute in Round {match.round_number}. Check the dashboard!"
        log_and_broadcast(tournament_id=tournament_id, content=admin_alert, db=db, platform="discord")
        
        return {"success": False, "status": "disputed", "message": "Conflict! Admins have been notified."}

    return {"success": True, "status": "waiting", "message": "Vote recorded."}

@router.post("/{tournament_id}/matches/{match_id}/ping")
def ping_match_captains(tournament_id: str, match_id: str, db: Session = Depends(get_db)):
    from models.database import Match, PlatformType 
    
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    team_a = db.query(Team).filter(Team.id == match.team_a_id).first()
    team_b = db.query(Team).filter(Team.id == match.team_b_id).first()

    ping_str = ""
    if team_a and team_a.captain_discord_id:
        ping_str += f"<@{team_a.captain_discord_id}> "
    if team_b and team_b.captain_discord_id:
        ping_str += f"and <@{team_b.captain_discord_id}>"

    if not ping_str:
        return {"success": False, "message": "Neither team has a Discord ID registered."}

    final_message = f"**MATCH READY**\nHey {ping_str.strip()}! Your match for Round {match.round_number} is ready. Please play your game and report the result here!"

    log_and_broadcast(tournament_id=tournament_id, content=final_message, db=db, platform="discord")
    
    return {"success": True, "message": "Ping sent directly to Discord and logged to memory!"}

@router.post("/nlp-parse")
def parse_natural_language(data: NLPRequest):
    parsed_data = parse_discord_intent(data.message)
    parsed_data["discord_id"] = data.discord_id
    parsed_data["timestamp"] = data.timestamp
    return parsed_data

@router.post("/nlp-report")
async def process_nlp_score(data: NLPScoreReport, db: Session = Depends(get_db)):
    from models.database import UserSession
    user_session = db.query(UserSession).filter(UserSession.discord_id == data.discord_id).first()
    if not user_session or not user_session.last_tournament_id:
        raise HTTPException(status_code=400, detail="Please click a 'Join' button in the server first so I know which tournament you mean!")
        
    active_tourney = db.query(Tournament).filter(Tournament.id == user_session.last_tournament_id).first()
    if not active_tourney:
        raise HTTPException(status_code=400, detail="The tournament you selected is no longer valid.")
        
    if active_tourney.status != "in_progress":
        raise HTTPException(
            status_code=400, 
            detail=f"Score reporting is locked! The tournament is currently '{active_tourney.status}'."
        )

    user_teams = db.query(Team).filter(
        Team.tournament_id == active_tourney.id,
        Team.captain_discord_id == data.discord_id
    ).all()

    if not user_teams:
        raise HTTPException(status_code=403, detail="You are not a registered captain in this tournament!")
        
    user_team_ids = [t.id for t in user_teams]

    query = db.query(Match).filter(
        Match.tournament_id == active_tourney.id,
        Match.status.in_(["pending", "live"]),
        (Match.team_a_id.in_(user_team_ids)) | (Match.team_b_id.in_(user_team_ids)),
        Match.team_a_id != None, 
        Match.team_b_id != None  
    )

    if data.round_number: query = query.filter(Match.round_number == data.round_number)
    if data.match_number: query = query.filter(Match.match_number == data.match_number)

    active_match = query.order_by(Match.round_number.asc()).first()

    if not active_match:
        raise HTTPException(status_code=400, detail="You have no matches ready to report.")
        
    if active_match.discord_channel_id and data.channel_id:
        if str(active_match.discord_channel_id) != str(data.channel_id):
            return {"success": False, "status": "wrong_channel", "message": f"Report in <#{active_match.discord_channel_id}>"}

    reporting_team = next((t for t in user_teams if t.id in [active_match.team_a_id, active_match.team_b_id]), None)
    team_a = db.query(Team).filter(Team.id == active_match.team_a_id).first()
    team_b = db.query(Team).filter(Team.id == active_match.team_b_id).first()

    import re
    def clean_name(name): return re.sub(r'[^a-zA-Z0-9]', '', str(name)).lower()

    clean_winner = clean_name(data.reported_winner) if data.reported_winner else None
    clean_loser = clean_name(data.reported_loser) if data.reported_loser else None
    clean_a, clean_b = clean_name(team_a.name), clean_name(team_b.name)
    clean_reporting = clean_name(reporting_team.name)

    winner_id = None
    if clean_winner and clean_winner != "none":
        if clean_winner in clean_a or clean_a in clean_winner: winner_id = team_a.id
        elif clean_winner in clean_b or clean_b in clean_winner: winner_id = team_b.id
        elif "we" in clean_winner or clean_reporting in clean_winner: winner_id = reporting_team.id
    elif clean_loser and clean_loser != "none":
        if clean_loser in clean_a or clean_a in clean_loser: winner_id = team_b.id
        elif clean_loser in clean_b or clean_b in clean_loser: winner_id = team_a.id
        elif "we" in clean_loser or clean_reporting in clean_loser: winner_id = team_b.id if reporting_team.id == team_a.id else team_a.id

    if not winner_id:
        raise HTTPException(status_code=400, detail="I couldn't figure out who won or lost.")

    result = process_consensus_logic(db, active_match, reporting_team.id, winner_id)

    if result["status"] == "completed":
        winner_name = team_a.name if winner_id == team_a.id else team_b.name
        loser_name = team_b.name if winner_id == team_a.id else team_a.name
        
        advance_winner(active_match, db) 
        
        announcement = f"**MATCH RESULT**\n**{winner_name}** has defeated **{loser_name}** in Round {active_match.round_number}!"
        log_and_broadcast(tournament_id=active_tourney.id, content=announcement, db=db, platform="discord")
        
        total_pending = db.query(Match).filter(
            Match.tournament_id == active_tourney.id,
            Match.status.in_(["pending", "live", "disputed"])
        ).count()

        import asyncio
        if total_pending == 0:
            await asyncio.sleep(1.5)
            active_tourney.status = "completed"
            db.commit()
            
            tourney_msg = f"**TOURNAMENT COMPLETE!**\nCongratulations to **{winner_name}** for winning the championship!"
            log_and_broadcast(tournament_id=active_tourney.id, content=tourney_msg, db=db, platform="discord")
        else:
            pending_in_round = db.query(Match).filter(
                Match.tournament_id == active_tourney.id,
                Match.round_number == active_match.round_number,
                Match.status.in_(["pending", "live", "disputed"])
            ).count()

            if pending_in_round == 0:
                await asyncio.sleep(1.5)
                round_msg = f"**ROUND {active_match.round_number} IS OFFICIALLY COMPLETE!**\nGet ready for the next round!"
                log_and_broadcast(tournament_id=active_tourney.id, content=round_msg, db=db, platform="discord")
        
        return {"success": True, "status": "completed", "message": f"Consensus reached! {winner_name} wins."}
        
    elif result["status"] == "disputed":
        log_and_broadcast(tournament_id=active_tourney.id, content=f"Dispute in match {active_match.match_number}!", db=db, platform="discord")
        return {"success": False, "status": "disputed", "message": "Scores conflict. Admins notified."}

    return {"success": True, "status": "waiting", "message": "Score recorded. Waiting for opponent."}

@router.put("/{tournament_id}/activate")
def set_active_tournament(tournament_id: str, db: Session = Depends(get_db)):
    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
        
    tournament.is_active = not tournament.is_active
    db.commit()
    
    status = "active" if tournament.is_active else "inactive"
    return {"success": True, "message": f"{tournament.name} is now {status}!"}

@router.put("/{tournament_id}/status")
def update_tournament_status(
    tournament_id: str, 
    data: UpdateStatusRequest, 
    db: Session = Depends(get_db)
):
    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not tournament:
        raise HTTPException(status_code=404, detail="Tournament not found")
        
    valid_statuses = ["draft", "registration_open", "in_progress", "live", "completed"]
    if data.status not in valid_statuses:
         raise HTTPException(status_code=400, detail="Invalid status type")
         
    tournament.status = data.status
    db.commit()
    
    return {"success": True, "message": f"Tournament status changed to {data.status}"}