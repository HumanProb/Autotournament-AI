import httpx
import discord
import os
import logging


from discord.ext import commands
from dotenv import load_dotenv
from typing import List

load_dotenv()

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

FASTAPI_URL = "http://127.0.0.1:8000"


@bot.event
async def on_ready():
    await bot.tree.sync()  # This sends the command list to Discord
    print("Bot is online and commands synced!")


@bot.tree.command(
    name="register", description="Register your team for the current tournament"
)
async def register_team(
    interaction: discord.Interaction,
    team_name: str,
    contact: str,
    captain_name: str,
    captain_in_game_id: str,
):
    # Defer the response so Discord doesn't timeout while we talk to the API
    await interaction.response.defer(ephemeral=True)

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            # --- STEP 1: Secretly fetch the active tournament ID ---
            active_req = await client.get(f"{FASTAPI_URL}/tournaments/active")

            if active_req.status_code != 200:
                await interaction.followup.send(
                    "❌ Registration closed: No active tournament found right now!"
                )
                return

            active_data = active_req.json()
            tournament_id = active_data["id"]
            tournament_name = active_data["name"]

            # --- STEP 2: Build the payload and register the team ---
            payload = {
                "tournament_id": tournament_id,
                "team_name": team_name, 
                "contact": contact,
                "players": [
                    {
                        "name": captain_name, 
                        "game_id": captain_in_game_id
                    }
                ]
            }

            # NOTE: Update this URL to exactly match your FastAPI registration route!
            response = await client.post(f"{FASTAPI_URL}/register/team", json=payload)

            if response.status_code == 200:
                await interaction.followup.send(
                    f"✅ Success! **{team_name}** is registered for **{tournament_name}**."
                )
            elif response.status_code == 400:
                await interaction.followup.send(
                    f"⚠️ Registration failed: Team might already exist."
                )
            else:
                await interaction.followup.send("❌ An unknown error occurred.")

        except httpx.RequestError as e:
            logging.error(f"API Connection Error: {e}")
            await interaction.followup.send(
                "🚨 Error: The AutoTournament backend is currently offline."
            )


if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN missing in .env")
    else:
        bot.run(TOKEN)
