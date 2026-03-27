import httpx, os, logging
from dotenv import load_dotenv
from enum import Enum

load_dotenv()


class DiscordChannel(Enum):
    ANNOUNCEMENT = "DISCORD_WEBHOOK_GENERAL"
    TEST_CHANNEL = "DISCORD_WEBHOOK_TEST_CHANNEL"


async def post_to_channel(username: str, message: str, channel: DiscordChannel) -> bool:
    """Post to Channel via webhook"""
    webhook_url = os.getenv(channel.value)
    if not webhook_url:
        logging.error(f"No webhook URL found for channel: {channel.name}")
        return False

    return await post_announcement(
            username=username,
            message=message,
            webhook_url=webhook_url
        )


async def post_announcement(
    username: str, message: str, webhook_url:str
) -> bool:
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
