from sqlalchemy.orm import Session
from models.database import Team, Match , MatchStatus, Tournament, TournamentStatus, TournamentFormat
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone

import itertools
import random
import math
import uuid

def next_power_of_two(n: int) -> int:
    return 2 ** math.ceil(math.log2(n))

load_dotenv()


def update_match_result(
    match_id: str,
    team_a_showed: bool,
    team_b_showed: bool,
    winner_id: str,
    db: Session
) -> Match:
    """update database for a match if one failed to show up other team wins 
        it should be called after match have happened"""
        
    match = db.query(Match).filter(Match.id == match_id).first()
    
    if not match:
        raise ValueError("Match not found")
        
    # --- GUARDRAILS ---
    if match.status == MatchStatus.bye:
        raise ValueError("This is a Bye. It auto-completes, you cannot report it.")
        
    # 1. If BOTH teams are missing, it's completely empty.
    if match.team_a_id is None and match.team_b_id is None:
        raise ValueError("Match is completely empty.")

    # 2. If ONE team is missing, only block it if they aren't trying to walkover the existing team.
    if match.team_a_id is None or match.team_b_id is None:
        if winner_id != match.team_a_id and winner_id != match.team_b_id:
            raise ValueError("Match is not ready! Waiting for previous rounds to finish.")
            
    if match.status in [MatchStatus.completed, MatchStatus.walkover, MatchStatus.double_forfeit]:
        raise ValueError("Match has already been reported.")
    # ----------------------
    
    if team_a_showed and team_b_showed:
        match.status = MatchStatus.completed
        match.winner_id = winner_id
        match.loser_id = (
            match.team_b_id if winner_id == match.team_a_id 
            else match.team_a_id
        )

    elif team_a_showed and not team_b_showed:
        match.status = MatchStatus.walkover
        match.winner_id = match.team_a_id
        match.forfeit_team_b = True
        
    elif team_b_showed and not team_a_showed:
        match.status = MatchStatus.walkover
        match.winner_id = match.team_b_id
        match.forfeit_team_a = True
    
    else:
        match.status = MatchStatus.double_forfeit
        match.forfeit_team_a = True
        match.forfeit_team_b = True
        match.winner_id = None
        
    db.commit()
    db.refresh(match)
    return match

def advance_winner(match: Match, db: Session) -> bool:
    """Puts the winner into their next match slot, and routes the loser to the lower bracket."""
    
    # --- 1. ROUTE THE WINNER ---
    if match.next_match_id and match.winner_id:
        next_match = db.query(Match).filter(Match.id == match.next_match_id).first()
        if next_match:
            if next_match.team_a_id is None:
                next_match.team_a_id = match.winner_id
            else:
                next_match.team_b_id = match.winner_id
            
    # --- 2. ROUTE THE LOSER (DOUBLE ELIM ONLY) ---
    loser_next_id = getattr(match, "loser_next_match_id", None)
    if loser_next_id and match.loser_id:
        loser_match = db.query(Match).filter(Match.id == loser_next_id).first()
        if loser_match:
            if loser_match.team_a_id is None:
                loser_match.team_a_id = match.loser_id
            else:
                loser_match.team_b_id = match.loser_id

    # --- 3. CHECK IF IT WAS THE GRAND FINALE ---
    if not match.next_match_id and not loser_next_id:
        tournament = db.query(Tournament).filter(Tournament.id == match.tournament_id).first()
        if tournament:
            tournament.status = TournamentStatus.completed
            db.commit()
        return True 

    db.commit()
    return False
        
def generate_full_bracket(db: Session, tournament_id: str):
    """
    The Strategy Router. Checks the tournament format and sends the database 
    session to the correct mathematical generator.
    """
    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not tournament:
        return {"success": False, "message": "Tournament not found."}

    format_val = tournament.format.value if hasattr(tournament.format, "value") else tournament.format
    
    # --- SMART TIME INJECTION ---
    from datetime import datetime, timezone, timedelta
    
    # If the admin didn't set a time, default to tomorrow.
    base_start_time = tournament.scheduled_start or (datetime.now(timezone.utc) + timedelta(days=1))
    
    # The moment the bracket triggers, we wait for "prep_time" before Round 1 actually begins
    prep = tournament.prep_time if tournament.prep_time else 30
    actual_match_start = base_start_time + timedelta(minutes=prep)
    
    if format_val == "single_elimination":
        return _generate_single_elim(db, tournament, actual_match_start)
    elif format_val == "double_elimination":
        return _generate_double_elim(db, tournament, actual_match_start)
    elif format_val == "round_robin":
        return _generate_round_robin(db, tournament, actual_match_start)
    
    return {"success": False, "message": f"Unsupported format: {format_val}"}


def _generate_single_elim(db: Session, tournament: Tournament, start_date: datetime):
    """Generates a complete single-elimination bracket with byes, linked rounds, and schedules."""
    teams = db.query(Team).filter(
        Team.tournament_id == tournament.id,
        Team.is_verified == True
    ).limit(tournament.max_teams).all()
    
    if len(teams) < 2:
        return {"success": False, "message": "Need at least 2 verified teams to generate a bracket."}
    
    # 1. THE MATH
    P = next_power_of_two(len(teams))
    num_rounds = int(math.log2(P))
    byes_needed = P - len(teams)

    # 2. FAIR SEEDING ALGORITHM
    random.shuffle(teams)
    round_1_pairings = []
    
    for _ in range(byes_needed):
        round_1_pairings.append((teams.pop(0), None))
        
    while len(teams) >= 2:
        round_1_pairings.append((teams.pop(0), teams.pop(0)))
        
    random.shuffle(round_1_pairings)

    matches_by_round = {}
    announcement = f"🏆 **THE {tournament.name} BRACKET IS SET! Round 1 Matchups:** 🏆\n\n"
    
    match_number = 1
    # 3. BUILD ROUND 1
    round_1_matches = []
    for team_a, team_b in round_1_pairings:
        if team_b:
            announcement += f"🥊 **{team_a.name}** vs **{team_b.name}**\n"
        else:
            announcement += f"🌟 **{team_a.name}** gets a Bye! (Auto-advances)\n"

        m = Match(
            id=str(uuid.uuid4()),
            tournament_id=tournament.id,
            team_a_id=team_a.id,
            team_b_id=team_b.id if team_b else None,
            round_number=1,
            match_number=match_number,
            status=MatchStatus.pending,
            scheduled_time=start_date # <--- Round 1 Schedule Injection
        )
        match_number += 1
        
        if not team_b:
            m.status = MatchStatus.bye
            m.winner_id = team_a.id
            
        db.add(m)
        round_1_matches.append(m)

    matches_by_round[1] = round_1_matches

    # 4. BUILD FUTURE ROUNDS AND LINK THEM
    for round_num in range(2, num_rounds + 1):
        prev_round_matches = matches_by_round[round_num - 1]
        current_round_matches = []
        
        # Uses minutes_between_rounds properly
        round_time = start_date + timedelta(minutes=(round_num - 1) * tournament.minutes_between_rounds)

        for i in range(0, len(prev_round_matches), 2):
            match_a = prev_round_matches[i]
            match_b = prev_round_matches[i+1]

            new_match = Match(
                id=str(uuid.uuid4()),
                tournament_id=tournament.id,
                team_a_id=None, 
                team_b_id=None,
                round_number=round_num,
                match_number=match_number,
                status=MatchStatus.pending,
                scheduled_time=round_time # <--- Future Round Schedule Injection
            )
            db.add(new_match)
            match_number += 1

            match_a.next_match_id = new_match.id
            match_b.next_match_id = new_match.id

            current_round_matches.append(new_match)

        matches_by_round[round_num] = current_round_matches
        
    db.commit()
        
    for m in round_1_matches:
        if m.status == MatchStatus.bye:
            advance_winner(match=m, db=db) 
            
    tournament.status = "in_progress"
    db.commit()
    
    return {
        "success": True, 
        "message": f"Generated {num_rounds} rounds of linked matches!",
        "announcement_text": announcement
    }

def _generate_round_robin(db: Session, tournament: Tournament, start_date: datetime):
    """Generates a league format where every team plays every other team."""
    teams = db.query(Team).filter(
        Team.tournament_id == tournament.id,
        Team.is_verified == True
    ).all()
    
    if len(teams) < 2:
        return {"success": False, "message": "Need at least 2 verified teams for Round Robin."}
    
    all_combinations = list(itertools.combinations(teams, 2))
    
    announcement = f"🏆 **{tournament.name} ROUND ROBIN IS LIVE!** Every team plays every team. ({len(all_combinations)} Total Matches) 🏆\n\n"
    
    for i, (team_a, team_b) in enumerate(all_combinations):
        # FIX: Uses minutes_between_rounds instead of hardcoded hours
        match_time = start_date + timedelta(minutes=i * tournament.minutes_between_rounds)
        
        new_match = Match(
            id=str(uuid.uuid4()),
            tournament_id=tournament.id,
            team_a_id=team_a.id,
            team_b_id=team_b.id,
            round_number=1, 
            match_number=i + 1,
            status=MatchStatus.pending,
            scheduled_time=match_time
        )
        db.add(new_match)
        announcement += f"🥊 **{team_a.name}** vs **{team_b.name}**\n"
    
    tournament.status = "in_progress"
    db.commit()
    
    return {
        "success": True, 
        "message": f"Generated {len(all_combinations)} Round Robin matches!",
        "announcement_text": announcement
    }

def _generate_double_elim(db: Session, tournament: Tournament, start_date: datetime):
    """Generates a Double Elimination bracket with accurate scheduling for upper and lower brackets."""
    teams = db.query(Team).filter(
        Team.tournament_id == tournament.id,
        Team.is_verified == True
    ).limit(tournament.max_teams).all()
    
    if len(teams) < 4:
        return {"success": False, "message": "Need at least 4 verified teams to run a proper Double Elimination."}

    P = next_power_of_two(len(teams))
    num_wb_rounds = int(math.log2(P))
    byes_needed = P - len(teams)

    random.shuffle(teams)
    round_1_pairings = [(teams.pop(0), None) for _ in range(byes_needed)]
    while len(teams) >= 2:
        round_1_pairings.append((teams.pop(0), teams.pop(0)))
    random.shuffle(round_1_pairings)

    wb_matches_by_round = {}
    match_number = 1
    
    # Grab the interval to avoid typing it repeatedly
    interval = tournament.minutes_between_rounds

    # ==========================================
    # PHASE 1: BUILD THE WINNERS BRACKET (WB)
    # ==========================================
    wb_round_1 = []
    for team_a, team_b in round_1_pairings:
        m = Match(
            id=str(uuid.uuid4()),
            tournament_id=tournament.id,
            team_a_id=team_a.id if team_a else None,
            team_b_id=team_b.id if team_b else None,
            round_number=1,
            match_number=match_number,
            status=MatchStatus.pending,
            is_losers_bracket=False,
            scheduled_time=start_date # <--- WB Round 1 Schedule Injection
        )
        if not team_b:
            m.status = MatchStatus.bye
            m.winner_id = team_a.id
        db.add(m)
        wb_round_1.append(m)
        match_number += 1
    wb_matches_by_round[1] = wb_round_1

    for round_num in range(2, num_wb_rounds + 1):
        prev_round = wb_matches_by_round[round_num - 1]
        curr_round = []
        
        # FIX: Replaced hardcoded 'hours=2'
        round_time = start_date + timedelta(minutes=(round_num - 1) * interval)
        
        for i in range(0, len(prev_round), 2):
            new_match = Match(
                id=str(uuid.uuid4()),
                tournament_id=tournament.id,
                round_number=round_num,
                match_number=match_number,
                status=MatchStatus.pending,
                is_losers_bracket=False,
                scheduled_time=round_time # <--- WB Future Round Schedule Injection
            )
            db.add(new_match)
            prev_round[i].next_match_id = new_match.id
            prev_round[i+1].next_match_id = new_match.id
            curr_round.append(new_match)
            match_number += 1
        wb_matches_by_round[round_num] = curr_round

    # ==========================================
    # PHASE 2: BUILD THE LOSERS BRACKET (LB)
    # ==========================================
    lb_matches_by_round = {}
    
    # LB Round 1 catches the losers from WB Round 1
    lb_round_1 = []
    # FIX: Replaced hardcoded 'hours=2'
    lb_round_1_time = start_date + timedelta(minutes=interval)
    
    for i in range(0, len(wb_round_1), 2):
        lb_match = Match(
            id=str(uuid.uuid4()),
            tournament_id=tournament.id,
            round_number=1, 
            match_number=match_number,
            status=MatchStatus.pending,
            is_losers_bracket=True,
            scheduled_time=lb_round_1_time # <--- LB Round 1 Schedule Injection
        )
        db.add(lb_match)
        
        wb_round_1[i].loser_next_match_id = lb_match.id
        wb_round_1[i+1].loser_next_match_id = lb_match.id
        
        lb_round_1.append(lb_match)
        match_number += 1
        
    lb_matches_by_round[1] = lb_round_1
    
    current_lb_round = 2
    prev_lb_matches = lb_round_1
    
    for wb_round_num in range(2, num_wb_rounds):
        wb_drop_matches = wb_matches_by_round[wb_round_num]
        
        # MAJOR LB ROUND: LB Survivors vs WB Drop-downs
        major_lb_round = []
        # FIX: Replaced hardcoded 'hours=...'
        major_lb_time = start_date + timedelta(minutes=(current_lb_round * interval))
        
        for i in range(len(prev_lb_matches)):
            lb_match = Match(
                id=str(uuid.uuid4()),
                tournament_id=tournament.id,
                round_number=current_lb_round,
                match_number=match_number,
                status=MatchStatus.pending,
                is_losers_bracket=True,
                scheduled_time=major_lb_time # <--- LB Major Round Schedule Injection
            )
            db.add(lb_match)
            
            prev_lb_matches[i].next_match_id = lb_match.id
            wb_drop_matches[i].loser_next_match_id = lb_match.id 
            
            major_lb_round.append(lb_match)
            match_number += 1
            
        current_lb_round += 1
        
        # MINOR LB ROUND: LB Survivors vs LB Survivors
        minor_lb_round = []
        # FIX: Replaced hardcoded 'hours=...'
        minor_lb_time = start_date + timedelta(minutes=(current_lb_round * interval))
        
        if len(major_lb_round) > 1:
            for i in range(0, len(major_lb_round), 2):
                lb_match = Match(
                    id=str(uuid.uuid4()),
                    tournament_id=tournament.id,
                    round_number=current_lb_round,
                    match_number=match_number,
                    status=MatchStatus.pending,
                    is_losers_bracket=True,
                    scheduled_time=minor_lb_time # <--- LB Minor Round Schedule Injection
                )
                db.add(lb_match)
                major_lb_round[i].next_match_id = lb_match.id
                major_lb_round[i+1].next_match_id = lb_match.id
                minor_lb_round.append(lb_match)
                match_number += 1
            prev_lb_matches = minor_lb_round
            current_lb_round += 1
        else:
            prev_lb_matches = major_lb_round

    # ==========================================
    # PHASE 3: THE GRAND FINALS
    # ==========================================
    # FIX: Replaced hardcoded 'hours=...'
    grand_finals_time = start_date + timedelta(minutes=(current_lb_round * interval) + interval)
    
    grand_final = Match(
        id=str(uuid.uuid4()),
        tournament_id=tournament.id,
        round_number=99,
        match_number=match_number,
        status=MatchStatus.pending,
        is_losers_bracket=False,
        scheduled_time=grand_finals_time # <--- Grand Finals Schedule Injection
    )
    db.add(grand_final)
    
    wb_matches_by_round[num_wb_rounds][0].next_match_id = grand_final.id
    prev_lb_matches[0].next_match_id = grand_final.id
    wb_matches_by_round[num_wb_rounds][0].loser_next_match_id = prev_lb_matches[0].id

    db.commit()
    
    for m in wb_round_1:
        if m.status == MatchStatus.bye:
            advance_winner(match=m, db=db)

    tournament.status = "in_progress"
    db.commit()
    
    return {
        "success": True, 
        "message": "Double Elimination Bracket Generated with automatic scheduling!",
        "announcement_text": f"🔥 **THE DOUBLE ELIMINATION BRACKET IS LIVE!** 🔥\nMatches start tomorrow. Check the bracket for your designated match time!"
    }