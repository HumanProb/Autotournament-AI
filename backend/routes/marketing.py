from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# from typing import List
import logging

# import uuid
from services.llm_service import generate_tournament_content

router = APIRouter(prefix="/marketing", tags=["Marketing"])


class GenerateContentRequest(BaseModel):
    game: str
    prize: int
    date: str


@router.post("/generate")
def generate_endpoint(content: GenerateContentRequest) -> dict:
    """takes generate class and returns content to be sent to discord instagram whatsapp"""

    try:
        result = generate_tournament_content(content.game, content.prize, content.date)
        return result
    except Exception as e:
        logging.error(f"LLM service failed: {e}")
        raise HTTPException(
            status_code=503,
            detail="Content generation service is currently unavailable",
        )
