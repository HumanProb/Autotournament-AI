from google import genai
from google.genai import types
import os
import logging
import json
import re
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

REQUIRED_RULES = {
    "instagram_caption": "max 150 chars, hype tone, 3-5 hashtags",
    "discord_announcement": "markdown formatted, mention all details",
    "whatsapp_forward": "casual, short, shareable",
    "poster_image_prompt": "detailed visual description for image AI",
}


def generate_tournament_content(game: str, prize: int, date: str) -> dict:
    """Calls Gemini to generate tournament marketing content.

    Args:
        game: name of the game (e.g. BGMI, Valorant)
        prize: prize pool amount in rupees
        date: tournament date as string

    Returns:
        dict with keys: instagram_caption, discord_announcement,
                        whatsapp_forward, poster_image_prompt
    """
    rules_str = "\n".join(
        [f"- {key}: {value}" for key, value in REQUIRED_RULES.items()]
    )

    prompt = f"""You are a gaming marketing expert. Create promotional content
                for a {game} tournament. Return ONLY a JSON object with exactly
                these keys: instagram_caption, discord_announcement,
                whatsapp_forward, poster_image_prompt.

                Tournament details:
                - Game: {game}
                - Prize pool: Rs.{prize}
                - Date: {date}
                - Format: Single Elimination

                Rules:
                {rules_str}

                Return ONLY the JSON. No explanation. No markdown code blocks."""

    try:
        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        cleaned = clean_llm_response(response.text)
        result = json.loads(cleaned)

        required_keys = set(REQUIRED_RULES.keys())
        if not required_keys.issubset(result.keys()):
            missing = required_keys - result.keys()
            raise ValueError(f"LLM response missing keys: {missing}")

        return result

    except json.JSONDecodeError as e:
        logging.error(f"Failed to parse Gemini response as JSON: {e}")
        raise
    except Exception as e:
        logging.error(f"Gemini API call failed: {e}")
        raise


def clean_llm_response(text: str) -> str:
    """Cleans LLM response by removing Markdown code blocks
    and extra whitespace."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE)
    return cleaned.strip()

def generate_hype_announcement(match_data: str) -> str:
    """Calls Gemini to rewrite raw match data into a hyped esports announcement."""
    
    prompt = f"""
    Raw Match Data:
    {match_data}
    """

    try:
        # We just ask for standard text, no JSON formatting needed!
        response = client.models.generate_content(
            model=GEMINI_MODEL, 
            contents=prompt
        )
        return response.text.strip()
        
    except Exception as e:
        logging.error(f"Gemini Hype Caster failed: {e}")
        # FALLBACK: If the AI fails or times out, return the boring text 
        # so the tournament doesn't crash!
        return match_data