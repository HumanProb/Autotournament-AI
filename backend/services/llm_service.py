from google import genai
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


def generate_tournament_content(game: str, prize: float, entry_fee: float, date: str) -> dict:
    """Calls Gemini to generate tournament marketing content."""
    
    rules_str = "\n".join(
        [f"- {key}: {value}" for key, value in REQUIRED_RULES.items()]
    )

    fee_text = f"Rs.{entry_fee}" if entry_fee > 0 else "FREE to enter!"

    prompt = f"""You are a gaming marketing expert. Create promotional content
                for a {game} tournament. Return ONLY a JSON object with exactly
                these keys: instagram_caption, discord_announcement,
                whatsapp_forward, poster_image_prompt.

                Tournament details:
                - Game: {game}
                - Prize pool: Rs.{prize}
                - Entry Fee: {fee_text}
                - Date: {date}

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
    
    prompt = f"""You are a maximum-energy esports shoutcaster announcing tournament brackets on Discord.

RULES:
- Use ALL CAPS for team names and key phrases
- Use emojis aggressively (🔥 💥 💀 🏆 ⚔️ 👑)
- Make it feel like a WWE announcement
- If a team has a Bye, tell them to REST UP because their opponents are coming
- Keep it under 1800 characters so Discord doesn't cut it off
- Do NOT invent fake teams or details
- Return ONLY the final Discord message, no explanation

Raw bracket data to hype up:
{match_data}"""

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt
        )
        return response.text.strip()
    except Exception as e:
        logging.error(f"Gemini Hype Caster failed: {e}")
        return match_data  # fallback to raw text


def generate_analytics_report(event_log_text: str):
    import json
    
    # 1. Validation
    if not event_log_text.strip():
        return {"summary": "Not enough data yet.", "mvp": "TBD", "intensity": "Low"}
        
    prompt = f"""
    You are an expert esports analyst. Review the following tournament event logs and provide a quick analysis.
    
    Event Logs:
    {event_log_text}
    
    Respond STRICTLY with a valid JSON object matching this structure:
    {{
        "summary": "A 2-sentence summary of how the tournament is going.",
        "mvp": "The team name that appears to be doing the best, or 'Too early to tell'.",
        "intensity": "Low, Medium, or High (based on disputes and walkovers)"
    }}
    """
    
    try:
        # 2. Use the global 'client' and 'GEMINI_MODEL' already defined at the top
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt
        )
        
        # 3. Use the helper function you already wrote
        cleaned = clean_llm_response(response.text)
        return json.loads(cleaned)
        
    except Exception as e:
        print(f"Analytics Generation Failed: {e}")
        return {"summary": "Error generating insights.", "mvp": "Unknown", "intensity": "Unknown"}
    
    
def parse_discord_intent(user_message: str) -> dict:
    """Uses Gemini to extract structured intent data."""
    
    prompt = f"""You are an intelligent data-extraction engine for an esports tournament bot.
    Read the user's message and determine what they are trying to do. 
    
    CRITICAL RULE: Return ONLY a valid JSON object. No markdown formatting.

    Allowed Intents:
    1. "register_team": User wants to join the tournament.
    2. "report_score": User is reporting the result of a match.
    3. "add_teammate": User is asking to add a new player.
    4. "edit_player": User is asking to fix a typo in a player name/ID.
    5. "edit_team": User is asking to change their Team's name.
    6. "ask_rulebook": User is asking a question about tournament rules.
    7. "help": User is asking how to use the bot itself.
    8. "unknown": Cannot determine intent.

    Expected JSON Schema:
    {{
      "intent": "register_team" | "report_score" | "add_teammate" | "edit_player" | "edit_team" | "ask_rulebook" | "help" | "unknown",
      
      "team_name": "extracted team name" | null,
      "captain_name": "extracted captain name" | null,
      "contact": "extracted contact info" | null,
      "captain_game_id": "extracted in-game username" | null,
      
      "reported_winner": "name of the team that WON" | null,
      "reported_loser": "name of the team that LOST" | null,
      "round_number": integer | null,
      "match_number": integer | null,

      "new_player_name": "extracted real name of the new teammate" | null,
      "new_player_game_id": "extracted in-game ID of the new teammate" | null,
      "new_team_name": "The new name they want for their team" | null,
      "target_original_identifier": "The old name or old ID they want to change" | null
    }}

    User Message: "{user_message}"
    """

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL, 
            contents=prompt
        )
        cleaned = clean_llm_response(response.text)
        return json.loads(cleaned)
    except Exception as e:
        logging.error(f"Intent parsing failed: {e}")
        return {"intent": "error"}