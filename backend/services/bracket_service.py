from sqlalchemy.orm import Session

from models.database import Team, Match , MatchStatus
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

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./autotournament.db")

router = APIRouter(prefix="/brackets", tags=["Brackets"])

# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# class MatchStatus(str, enum.Enum):
#     pending = "pending"  # waiting to be played
#     live = "live"  # currently being played
#     completed = "completed"  # played, winner determined
#     walkover = "walkover"  # one team no-show, other advances
#     double_forfeit = "double_forfeit"  # both no-show, both disqualified
#     bye = "bye"  # only one team, auto-advances


# class Match(Base):
#     __tablename__ = "matches"
#     id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
#     tournament_id = Column(String, ForeignKey("tournaments.id"))
#     team_a_id = Column(String, ForeignKey("teams.id"), nullable=True)
#     team_b_id = Column(String, ForeignKey("teams.id"), nullable=True)
#     winner_id = Column(String, nullable=True)
#     loser_id = Column(String, nullable=True)
#     round_number = Column(Integer)
#     match_number = Column(Integer)
#     next_match_id = Column(String, ForeignKey("matches.id"), nullable=True)
#     status = Column(String, default=MatchStatus.pending)
#     scheduled_time = Column(DateTime, nullable=True)
#     forfeit_team_a = Column(Boolean, default=False)
#     forfeit_team_b = Column(Boolean, default=False)
#     tournament = relationship("Tournament", back_populates="matches")


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
    
    if team_a_showed and team_b_showed:
        match.status = MatchStatus.completed
        match.winner_id = winner_id
        match.loser_id = (
            match.team_b_id if winner_id == match.team_a_id 
            else match.team_a_id
        )

    if team_a_showed and not team_b_showed:
        match.status = MatchStatus.walkover
        match.winner_id = match.team_a_id
        match.forfeit_team_b = True
        
    if team_b_showed and not team_a_showed:
        match.status = MatchStatus.walkover
        match.winner_id = match.team_b_id
        match.forfeit_team_a = True
    
    if not team_a_showed and not team_b_showed:
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
        
        
# def generate_round_1(db: Session, tournament_id: str):
#     """
#     Fetches all teams, shuffles them, and pairs them into Round 1 matches.
#     """
#     # 1. Fetch all registered teams for this tournament
#     teams = db.query(Team).filter(Team.tournament_id == tournament_id).all()
    
#     if len(teams) < 2:
#         return {"success": False, "message": "Need at least 2 teams to generate a bracket."}

#     # 2. Shuffle the array for fair, randomized seeding
#     random.shuffle(teams)

#     matches_created = []
    
#     announcement = "🏆 **THE BRACKET IS SET! Round 1 Matchups:** 🏆\n\n"
    
#     # 3. Step through the array 2 at a time to create pairs
#     for i in range(0, len(teams), 2):
#         team1 = teams[i]
        
#         team2 = teams[i+1] if (i + 1) < len(teams) else None
        
#         if team2:
#             announcement += f"🥊 **{team1.name}** vs **{team2.name}**\n"
#         else:
#             announcement += f"🌟 **{team1.name}** gets a Bye! (Auto-advances to Round 2)\n"
            
#         # Handle odd numbers: If there is no team2, they get a None (a "Bye")
#         team2 = teams[i+1] if (i + 1) < len(teams) else None 
        
#         # 4. Create the Match record
#         new_match = Match(
#             tournament_id=tournament_id,
#             team_a_id=team1.id,
#             team_b_id=team2.id if team2 else None,
#             round_number=1
#         )
#         db.add(new_match)
#         matches_created.append(new_match)
        
#     # 5. Save everything to the database
#     db.commit()
    
#     return {
#         "success": True, 
#         "message": f"Generated {len(matches_created)} matches for Round 1!",
#         "match_count": len(matches_created),
#         "announcement_text": announcement
#     }
    
def generate_full_bracket(db: Session, tournament_id: str):
    """
    Generates a complete single-elimination bracket, calculates byes, 
    and links all future rounds together.
    """
    teams = db.query(Team).filter(Team.tournament_id == tournament_id).all()
    
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
            status=MatchStatus.pending
        )
        
        # If it's a Bye, auto-complete the match so advance_winner() works later!
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
    
    return {
        "success": True, 
        "message": f"Generated {num_rounds} rounds of linked matches!",
        "announcement_text": announcement
    }