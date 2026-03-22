import httpx, os, logging
from dotenv import load_dotenv

load_dotenv()

WEBHOOK_GENERAL = os.getenv("DISCORD_WEBHOOK_GENERAL")
WEBHOOK_TEST_CHANNEL=os.getenv("DISCORD_WEBHOOK_TEST_CHANNEL")


async def post_announcement(username: str, message: str, webhook_url: str) -> bool:
    """Posts a message to Discord via webhook.
    Returns True if successful, False if failed.
    Never raises — Discord failure must not crash the main flow.
    """

    content = {"username": username, "content": message}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(webhook_url, json=content)
        
        if response.status_code == 204:
            logging.info(f"Posted successfully to webhook")
            return True
        logging.warning(f"Discord post failed: {response.status_code}")
        return False
    
    except httpx.TimeoutException:
        logging.error("Discord webhook timed out")
        return False
    except httpx.RequestError as e:
        logging.error(f"Discord webhook request failed: {e}")
        return False
    

        
    
