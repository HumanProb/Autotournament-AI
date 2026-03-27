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


@bot.tree.command(name="register", description="Register your team for a tournament")
async def my_command_function(
    interaction: discord.Interaction,
    tournament_id: str,
    team_name: str,
    contact: str,
    captain_name: str,
    captain_in_game_id: str,
):
    # tournament_id: str
    # team_name: str
    # contact: str
    # players: List[PlayerInput]
    # name: str
    # game_id: str
    # if not captain_name in player_list or not captain_id in game_id:
    #     logging.warning("Player List Doesn't contains the Captain")
    #     return
    await interaction.response.defer(ephemeral=True)

    payload = {
        "tournament_id": tournament_id,
        "team_name": team_name,
        "contact": contact,
        "players": [{"name": captain_name, "game_id": captain_in_game_id}],
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(f"{FASTAPI_URL}/register/team", json=payload)
            
            if response.status_code == 200:
                await interaction.followup.send(f"✅ Success! Team **{team_name}** has been registered.")
            elif response.status_code == 400:
                await interaction.followup.send(f"⚠️ Registration failed: Team name already exists.")
            elif response.status_code == 404:
                await interaction.followup.send(f"❌ Error: Tournament ID not found.")
            else:
                await interaction.followup.send("❌ An unknown error occurred.")

        except httpx.RequestError:
            await interaction.followup.send(
                "🚨 Error: The AutoTournament backend is currently offline."
            )


if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN missing in .env")
    else:
        bot.run(TOKEN)
