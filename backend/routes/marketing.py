from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# from typing import List
import logging

# import uuid
from services.llm_service import generate_tournament_content
from services.discord_service import post_announcement,WEBHOOK_TEST_CHANNEL
# from services.discord_service import post_announcement, WEBHOOK_TEST_CHANNEL

router = APIRouter(prefix="/marketing", tags=["Marketing"])


class GenerateContentRequest(BaseModel):
    game: str
    prize: int
    date: str


@router.post("/generate")
async def generate_endpoint(content: GenerateContentRequest) -> dict:
    """takes generate class and returns content to be sent to discord instagram whatsapp"""

    try:
        result = generate_tournament_content(content.game, content.prize, content.date)
        
        discord_posted = await post_announcement(
            username="Test Name",
            message=result["discord_announcement"],
            webhook_url=WEBHOOK_TEST_CHANNEL
        )
        
        if not discord_posted:
            logging.warning("Content generated but Discord post failed")
            
        return result
    
    except Exception as e:
        logging.error(f"LLM service failed: {e}")
        raise HTTPException(
            status_code=503,
            detail="Content generation service is currently unavailable",
        )
