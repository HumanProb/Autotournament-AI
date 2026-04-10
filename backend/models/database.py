from sqlalchemy import create_engine, Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from dotenv import load_dotenv
from datetime import datetime,timezone
import os
import enum
import uuid

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./autotournament.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


# --- Enums ---

class TournamentStatus(str, enum.Enum):
    draft = "draft"
    registration_open = "registration_open"
    in_progress = "in_progress"
    live ="live"
    completed = "completed"

class TournamentFormat(str, enum.Enum):
    single_elimination = "single_elimination"
    double_elimination = "double_elimination"
    round_robin = "round_robin"

class MatchStatus(str, enum.Enum):
    pending = "pending"  # waiting to be played
    live = "live"  # currently being played
    completed = "completed"  # played, winner determined
    walkover = "walkover"  # one team no-show, other advances
    double_forfeit = "double_forfeit"  # both no-show, both disqualified
    bye = "bye"  # only one team, auto-advances
    disputed = "disputed" 

# --- Models ---

class Tournament(Base):
    __tablename__ = "tournaments"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    game = Column(String, nullable=False)
    format = Column(String, default=TournamentFormat.single_elimination)
    status = Column(String, default=TournamentStatus.draft)
    prize_pool = Column(Float, default=0.0)
    max_teams = Column(Integer, default=16)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    is_active = Column(Boolean, default=True)

    teams = relationship("Team", back_populates="tournament")
    matches = relationship("Match", back_populates="tournament")


class Team(Base):
    __tablename__ = "teams"

    id = Column(String, primary_key=True)
    tournament_id = Column(String, ForeignKey("tournaments.id"))
    name = Column(String, nullable=False)
    contact = Column(String)
    payment_status = Column(Boolean, default=False)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    tournament = relationship("Tournament", back_populates="teams")
    players = relationship("Player", back_populates="team")


class Player(Base):
    __tablename__ = "players"

    id = Column(String, primary_key=True)
    team_id = Column(String, ForeignKey("teams.id"))
    name = Column(String, nullable=False)
    game_id = Column(String, nullable=False)  # in-game username/ID

    team = relationship("Team", back_populates="players")

    
class Match(Base):
    __tablename__ = "matches"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tournament_id = Column(String, ForeignKey("tournaments.id"))
    team_a_id = Column(String, ForeignKey("teams.id"), nullable=True)
    team_b_id = Column(String, ForeignKey("teams.id"), nullable=True)
    winner_id = Column(String, nullable=True)
    loser_id = Column(String, nullable=True)
    round_number = Column(Integer)
    match_number = Column(Integer)
    next_match_id = Column(String, ForeignKey("matches.id"), nullable=True)
    team_a_reported_winner_id = Column(String, nullable=True)
    team_b_reported_winner_id = Column(String, nullable=True)
    status = Column(String, default=MatchStatus.pending)
    scheduled_time = Column(DateTime, nullable=True)
    forfeit_team_a = Column(Boolean, default=False)
    forfeit_team_b = Column(Boolean, default=False)
    tournament = relationship("Tournament", back_populates="matches")
    
    


# --- DB init function ---

def init_db():
    Base.metadata.create_all(bind=engine)


# --- Dependency for routes ---

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()