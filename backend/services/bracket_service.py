from sqlalchemy.orm import Session

from models.database import Team, Match , MatchStatus, Tournament
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv


import random
import os
import enum
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
        raise HTTPException(status_code=404, detail="Match not found")
        
    # --- GUARDRAILS ---
    if match.status == MatchStatus.bye:
        raise HTTPException(status_code=400, detail="This is a Bye. It auto-completes, you cannot report it.")
        
    # --- NEW: THE WALKOVER EXCEPTION ---
    # 1. If BOTH teams are missing, it's completely empty.
    if match.team_a_id is None and match.team_b_id is None:
        raise HTTPException(status_code=400, detail="Match is completely empty.")

    # 2. If ONE team is missing, only block it if they aren't trying to walkover the existing team.
    if match.team_a_id is None or match.team_b_id is None:
        if winner_id != match.team_a_id and winner_id != match.team_b_id:
            raise HTTPException(status_code=400, detail="Match is not ready! Waiting for previous rounds to finish.")
    # -----------------------------------
        
    if match.status in [MatchStatus.completed, MatchStatus.walkover, MatchStatus.double_forfeit]:
        raise HTTPException(status_code=400, detail="Match has already been reported.")
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

def advance_winner(match: Match, db: Session):
    """Puts the winner into their next match slot"""
    
    if not match.next_match_id:
        # no next match = this was the final
        return
    
    if not match.winner_id:
        # double forfeit — nobody advances
        # propagate_forfeit(match.next_match_id, match.id, db) #for future me
        return
    
    # fetch the next match
    next_match = db.query(Match).filter(
        Match.id == match.next_match_id
    ).first()
    
    # figure out which slot to fill
    # matches are linked — current match's position determines slot
    if next_match.team_a_id is None:
        next_match.team_a_id = match.winner_id
    else:
        next_match.team_b_id = match.winner_id
    
    db.commit()
    db.refresh(next_match)
        
    
def generate_full_bracket(db: Session, tournament_id: str):
    """
    Generates a complete single-elimination bracket, calculates byes, 
    and links all future rounds together.
    """
    tournament = db.query(Tournament).filter(Tournament.id == tournament_id).first()
    if not tournament:
        return {"success": False, "message": "Tournament not found."}
    
    teams = db.query(Team).filter(
        Team.tournament_id == tournament_id,
        Team.is_verified == True
    ).limit(tournament.max_teams).all()
    
    if len(teams) < 2:
        return {"success": False, "message": "Need at least 2 teams to generate a bracket."}
    

    # 1. THE MATH
    P = next_power_of_two(len(teams))
    num_rounds = int(math.log2(P))
    byes_needed = P - len(teams)

    # 2. FAIR SEEDING ALGORITHM (Preventing None vs None)
    random.shuffle(teams)
    round_1_pairings = []
    
    # Assign the byes to random teams first
    for _ in range(byes_needed):
        round_1_pairings.append((teams.pop(0), None))
        
    # Pair up the remaining teams against each other
    while len(teams) >= 2:
        round_1_pairings.append((teams.pop(0), teams.pop(0)))
        
    # Shuffle the matches so the byes are scattered across the bracket
    random.shuffle(round_1_pairings)

    matches_by_round = {}
    announcement = "🏆 **THE BRACKET IS SET! Round 1 Matchups:** 🏆\n\n"
    
    match_number = 1
    # 3. BUILD ROUND 1
    round_1_matches = []
    for team_a, team_b in round_1_pairings:
        if team_b:
            announcement += f"🥊 **{team_a.name}** vs **{team_b.name}**\n"
        else:
            announcement += f"🌟 **{team_a.name}** gets a Bye! (Auto-advances)\n"

        match_id = str(uuid.uuid4()) # Explicitly generate ID now so we can link it later
        
        m = Match(
            id=match_id,
            tournament_id=tournament_id,
            team_a_id=team_a.id,
            team_b_id=team_b.id if team_b else None,
            round_number=1,
            match_number=match_number,
            status=MatchStatus.pending
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

        # Step through the previous round 2 matches at a time
        for i in range(0, len(prev_round_matches), 2):
            match_a = prev_round_matches[i]
            match_b = prev_round_matches[i+1]

            # Create an empty match for the future round
            new_match_id = str(uuid.uuid4())
            new_match = Match(
                id=new_match_id,
                tournament_id=tournament_id,
                team_a_id=None, # Empty! Winners will flow into these slots
                team_b_id=None,
                round_number=round_num,
                status=MatchStatus.pending
            )
            db.add(new_match)

            # THE MAGIC: Link the previous matches to this new one
            match_a.next_match_id = new_match_id
            match_b.next_match_id = new_match_id

            current_round_matches.append(new_match)

        matches_by_round[round_num] = current_round_matches
        
    db.commit()
        
    for m in round_1_matches:
        if m.status == MatchStatus.bye:
            advance_winner(match=m, db=db)

    db.commit()
    
    return {
        "success": True, 
        "message": f"Generated {num_rounds} rounds of linked matches!",
        "announcement_text": announcement
    }



