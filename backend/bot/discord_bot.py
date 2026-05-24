import httpx
import discord
import os
import logging
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import datetime, timezone
from discord.ext import tasks

try:
    from services.rag_service import ask_rulebook
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False
    def ask_rulebook(q): return "Rulebook feature coming soon!"
    
from datetime import datetime, timezone

load_dotenv()



intents = discord.Intents.default()
intents.message_content = True  
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

FASTAPI_URL = "http://127.0.0.1:8000"



@bot.event
async def on_message(message):
    # --- THE ANTI-LOOP GUARDRAIL ---
    if message.author.bot:
        return
    
    allowed_channels = ["registration", "general", "bot-testing"]
    
    if getattr(message.channel.category, "name", "") != "🏆 Active Matches" and message.channel.name not in allowed_channels:
        await bot.process_commands(message)
        return
    
    msg_time = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
    discord_id = str(message.author.id)
    content = message.content

    # 1. The Master Log (Logs everything)
    with open("discord_chat_log.txt", "a", encoding="utf-8") as f:
        f.write(f"[{msg_time}] [{message.author.name}]: {content}\n")

    async with httpx.AsyncClient() as client:
        try:
            payload = {
                "message": content,
                "discord_id": discord_id,
                "timestamp": msg_time
            }
            
            response = await client.post(f"{FASTAPI_URL}/tournaments/nlp-parse", json=payload)
            
            if response.status_code == 200:
                data = response.json()
                intent = data.get("intent")
                
                # --- THE INTENT LOGGER ---
                if intent in ["register_team", "report_score", "help"]:
                    with open("detected_intents_log.txt", "a", encoding="utf-8") as intent_file:
                        intent_file.write(f"[{msg_time}] [{message.author.name}] INTENT: {intent} | DATA: {data}\n")
                
                # --- ROUTE 1: REGISTRATION ---
                if intent == "register_team":
                    print(f"🎯 INTENT DETECTED: {message.author.name} wants to register!")
                    active_req = await client.get(f"{FASTAPI_URL}/tournaments/active")
                    if active_req.status_code != 200:
                        await message.channel.send("❌ No active tournament right now!")
                        return
                    
                    tournament_id = active_req.json()["id"]
                    
                    reg_payload = {
                        "tournament_id": tournament_id,
                        "team_name": data.get("team_name") or f"{message.author.name}'s Team", 
                        "contact": data.get("contact") or "Not provided",
                        "players": [{"name": data.get("captain_name") or message.author.name, "game_id": data.get("captain_game_id") or "Unknown", "discord_id": discord_id}]
                    }
                    
                    reg_response = await client.post(f"{FASTAPI_URL}/register/team", json=reg_payload)
                    
                    if reg_response.status_code == 200:
                        await message.channel.send(f"✅ Successfully registered **{data.get('team_name')}**!")
                        
                        # --- AUTO-ROLE ASSIGNMENT DEBUGGING ---
                        print("🛠️ Attempting to assign Captain role...")
                        try:
                            # 1. First, check if the role even exists
                            captain_role = discord.utils.get(message.guild.roles, name="Captain")
                            
                            if not captain_role:
                                print("🚨 ERROR: The role 'Captain' does not exist in this Discord server! You need to create it manually.")
                                await message.channel.send("⚠️ Note: I tried to give you the Captain role, but an admin hasn't created it yet!")
                            else:
                                # 2. Try to assign it
                                await message.author.add_roles(captain_role)
                                print(f"✅ Success: Gave Captain role to {message.author.name}")
                                await message.channel.send(f"👑 **{message.author.name}**, you have been granted the Captain role!")
                                
                        except discord.Forbidden:
                            print("🚨 ERROR: Discord Forbidden. The Bot lacks 'Manage Roles' permission OR the Bot's role is lower than the Captain role.")
                            await message.channel.send("⚠️ Note: I don't have permission to assign the Captain role. An admin needs to fix my settings!")
                        except Exception as e:
                            print(f"🚨 UNKNOWN ROLE ERROR: {e}")

                    else:
                        await message.channel.send(f"⚠️ Registration failed: {reg_response.json().get('detail')}")
                        

                # --- ROUTE 2: SCORE REPORTING ---
                elif intent == "report_score":
                    print(f"🎯 INTENT DETECTED: {message.author.name} is reporting a score!")
                    
                    report_payload = {
                        "discord_id": discord_id,
                        "reported_winner": data.get("reported_winner"), 
                        "reported_loser": data.get("reported_loser"), 
                        "round_number": data.get("round_number"),
                        "match_number": data.get("match_number"),
                        "channel_id": str(message.channel.id)
                    }
                    
                    score_response = await client.post(f"{FASTAPI_URL}/tournaments/nlp-report", json=report_payload)
                    
                    if score_response.status_code == 200:
                        res_data = score_response.json()
                        
                        # --- NEW: Handle the wrong channel warning gracefully ---
                        if res_data.get("status") == "wrong_channel":
                            await message.channel.send(res_data.get("message"))
                        else:
                            success_msg = res_data.get("message")
                            await message.channel.send(f"✅ {success_msg}")
                            
                    elif score_response.status_code == 400:
                        err = score_response.json().get("detail")
                        await message.channel.send(f"⚠️ Report blocked: {err}")
                    elif score_response.status_code == 403:
                        await message.channel.send("🚨 Access Denied: You are not a registered captain in the active tournament!")
                        
                # --- ROUTE 3: THE HELP MENU ---
                elif intent == "help":
                    print(f"ℹ️ {message.author.name} asked for help!")
                    
                    # NOTE: Kept flush to the left wall so Discord doesn't format it as code!
                    help_text = """🤖 **AutoTournament Bot - How to use me!**
I understand natural language, so you can just talk to me like a normal person. Here is what I can do:

📝 **1. Register for the Tournament**
Just tell me your team name and your in-game ID!
*Example:* `"Hey, I want to register Team Ninja. My ID is NinjaMaster99."*

⚔️ **2. Report a Match Score**
Tell me who won or lost. I will automatically update the bracket and wait for the other captain to confirm!
*Example:* `"We won our match against Team Liquid."*
*Example:* `"My team got crushed in round 1 match 2."*

If I ever get confused, just try rephrasing your sentence using your exact Team Name!"""
                    
                    await message.channel.send(help_text)
                    
                # --- ROUTE: RAG RULEBOOK QA ---
                elif intent == "ask_rulebook":
                    print(f"🧠 INTENT DETECTED: {message.author.name} is asking a rulebook question.")
                    
                    # Show a typing indicator because RAG takes ~2 seconds
                    async with message.channel.typing():
                        # We pass the raw Discord message directly to the RAG service
                        answer = ask_rulebook(message.content)
                        await message.channel.send(f"📖 **Rulebook AI:**\n{answer}")
                    
                elif intent == "add_teammate":
                    print(f"🎯 INTENT DETECTED: {message.author.name} is adding a teammate!")
                    
                    new_name = data.get("new_player_name")
                    new_id = data.get("new_player_game_id")

                    if not new_name or not new_id:
                        await message.channel.send("⚠️ I couldn't understand the player's name or game ID. Try: *'Add John to my team, his ID is John123'*")
                        return

                    add_payload = {
                        "discord_id": discord_id,
                        "new_player_name": new_name,
                        "new_player_game_id": new_id
                    }
                    
                    add_response = await client.post(f"{FASTAPI_URL}/register/nlp-add-teammate", json=add_payload)
                    
                    if add_response.status_code == 200:
                        await message.channel.send(f"✅ {add_response.json().get('message')}")
                    else:
                        await message.channel.send(f"🚨 Failed to add player: {add_response.json().get('detail')}")

                elif intent == "edit_player":
                    print(f"🎯 INTENT DETECTED: {message.author.name} is editing a player!")
                    
                    edit_payload = {
                        "discord_id": discord_id,
                        "target_original_identifier": data.get("target_original_identifier"),
                        "new_player_name": data.get("new_player_name"),
                        "new_player_game_id": data.get("new_player_game_id")
                    }
                    
                    edit_response = await client.post(f"{FASTAPI_URL}/register/nlp-edit-player", json=edit_payload)
                    
                    if edit_response.status_code == 200:
                        await message.channel.send(f"✅ {edit_response.json().get('message')}")
                    else:
                        await message.channel.send(f"🚨 Failed to edit player: {edit_response.json().get('detail')}")
                        
                # --- ROUTE 4: RATE LIMITS (Gemini Overwhelmed) ---
                elif intent == "error":
                    print(f"⚠️ API ERROR: Gemini is overwhelmed!")
                    await message.channel.send("⚙️ **System Alert:** I am receiving too many requests right now and my AI brain needs a quick cooldown! Please wait 60 seconds and try sending your message again.")

                # --- ROUTE 5: UNKNOWN INTENT ---
                elif intent == "unknown":
                    print(f"❓ Unknown intent from {message.author.name}")
                    # Optional: You can uncomment the line below if you want the bot to actively reply to confusing messages
                    # await message.channel.send("I'm not quite sure what you mean! Type **help** to see what I can do.")

        except Exception as e:
            print(f"Could not reach FastAPI: {e}")

    # Keep this so any other explicit commands still work
    await bot.process_commands(message)
    
    
# --- THE NEW INTERACTIVE BUTTON PANEL ---
class ReportScoreView(discord.ui.View):
    def __init__(self, tournament_id: str, match_id: str, team_a_id: str, team_b_id: str, team_a_name: str, team_b_name: str):
        super().__init__(timeout=None)
        self.tournament_id = tournament_id
        self.match_id = match_id
        self.team_a_id = team_a_id
        self.team_b_id = team_b_id

        # Create Button A
        btn_a = discord.ui.Button(label=f"🏆 {team_a_name} Won", style=discord.ButtonStyle.success)
        btn_a.callback = self.team_a_clicked
        self.add_item(btn_a)

        # Create Button B
        btn_b = discord.ui.Button(label=f"🏆 {team_b_name} Won", style=discord.ButtonStyle.success)
        btn_b.callback = self.team_b_clicked
        self.add_item(btn_b)

    async def send_report_to_backend(self, interaction: discord.Interaction, reported_winner_id: str):
        # We ping the backend with the score AND the Discord ID of the person who clicked!
        discord_user_id = str(interaction.user.id) 

        await interaction.response.defer(ephemeral=True)

        async with httpx.AsyncClient(timeout=10.0) as client:
            
            try:
                active = await client.get(f"{FASTAPI_URL}/tournaments/active")
                if active.status_code != 200:
                    await interaction.followup.send("No active tournament.", ephemeral=True)
                    return
                tournament_id = active.json()["id"]
                
                response = await client.post(
                    f"{FASTAPI_URL}/tournaments/{self.tournament_id}/matches/{self.match_id}/player-report",
                    json={
                        "reporting_team_id": discord_user_id, # We will update FastAPI to check this next!
                        "reported_winner_id": reported_winner_id,
                        "round_number": None,
                        "match_number": None
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data["status"] == "waiting":
                        await interaction.followup.send("✅ Score recorded! Waiting for the opponent to confirm.", ephemeral=True)
                    elif data["status"] == "completed":
                        await interaction.followup.send("🎉 Both teams agreed! Advancing bracket.", ephemeral=True)
                    elif data["status"] == "disputed":
                        await interaction.followup.send("🚨 Conflict detected! An admin has been notified.", ephemeral=True)
                else:
                    error_msg = response.json().get("detail", "Unknown error")
                    await interaction.followup.send(f"❌ Error: {error_msg}", ephemeral=True)
            except Exception as e:
                await interaction.followup.send("🚨 Error contacting the backend.", ephemeral=True)

    async def team_a_clicked(self, interaction: discord.Interaction):
        await self.send_report_to_backend(interaction, self.team_a_id)

    async def team_b_clicked(self, interaction: discord.Interaction):
        await self.send_report_to_backend(interaction, self.team_b_id)
        
async def create_match_room(guild_id: int, match_id: str, captain_a_id: int, captain_b_id: int, round_num: int, match_num: int, unix_time: int):
    """Creates a private locked channel for a specific match."""
    guild = bot.get_guild(guild_id)
    if not guild:
        return {"success": False, "message": "Bot cannot find the Server. Check DISCORD_GUILD_ID in .env!"}

    # 🔥 PRO-TIP: Use discord.Object to completely bypass Discord caching issues!
    captain_a = discord.Object(id=captain_a_id)
    captain_b = discord.Object(id=captain_b_id)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        captain_a: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        captain_b: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }

    category_name = "🏆 Active Matches"
    category = discord.utils.get(guild.categories, name=category_name)
    if not category:
        category = await guild.create_category(category_name)

    channel_name = f"rd{round_num}-match{match_num}"
    
    try:
        match_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            topic=f"Match {match_num} | Report scores and disputes here."
        )

        welcome_msg = (
            f"⚔️ **MATCH ROOM CREATED** ⚔️\n"
            f"Welcome <@{captain_a_id}> and <@{captain_b_id}>.\n\n"
            f"⏰ **Scheduled Start:** <t:{unix_time}:F> (<t:{unix_time}:R>)\n\n"
            f"Please share server passwords or IPs here. When the match is over, use the `Report Score` button or type your result!"
        )
        await match_channel.send(welcome_msg)
        return {"success": True, "channel_id": str(match_channel.id)}
        
    except Exception as e:
        return {"success": False, "message": f"Discord API Error: {e}"}

# --- FETCH FROM .ENV AND CONVERT TO INTEGER ---
guild_id_str = os.getenv("DISCORD_GUILD_ID")
GUILD_ID = int(guild_id_str) if guild_id_str else None

@tasks.loop(seconds=60)
async def match_room_manager():
    """Wakes up every 60s to Manage Rooms, Delete Old Rooms, and Sync Roles."""
    
    if not GUILD_ID:
        print("🚨 ERROR: DISCORD_GUILD_ID is missing from your .env file!")
        return

    async with httpx.AsyncClient() as client:
        try:
            # ==========================================
            # 1. CREATE NEW MATCH ROOMS
            # ==========================================
            room_resp = await client.get(f"{FASTAPI_URL}/tournaments/matches/need-rooms", timeout=5.0)
            if room_resp.status_code == 200:
                for match in room_resp.json():
                    
                    sched_str = match.get("scheduled_time")
                    if not sched_str:
                        continue
                        
                    # --- THE TIMEZONE FIX ---
                    # If SQLite stripped the timezone, we force it to explicitly state it is UTC
                    if not sched_str.endswith('Z') and '+' not in sched_str:
                        sched_str += '+00:00'
                    else:
                        sched_str = sched_str.replace('Z', '+00:00')
                        
                    sched_time = datetime.fromisoformat(sched_str)
                    now = datetime.now(timezone.utc)
                    # ------------------------
                    
                    # Calculate how many seconds until the match starts (This will no longer crash!)
                    seconds_until_match = (sched_time - now).total_seconds()
                    
                    # ONLY create the room if it is 30 minutes (1800 seconds) or less away!
                    if seconds_until_match <= 1800:
                        print(f"Creating private room for Round {match['round_number']} Match {match['match_number']}...")
                        
                        unix_timestamp = int(sched_time.timestamp())
                        
                        room_data = await create_match_room(
                            guild_id=GUILD_ID, 
                            match_id=match["match_id"],
                            captain_a_id=int(match["captain_a_discord"]),
                            captain_b_id=int(match["captain_b_discord"]),
                            round_num=match["round_number"],
                            match_num=match["match_number"],
                            unix_time=unix_timestamp
                        )
                        
                        if room_data["success"]:
                            await client.put(
                                f"{FASTAPI_URL}/tournaments/matches/{match['match_id']}/room",
                                json={"channel_id": room_data["channel_id"]}
                            )
                        else:
                            print(f"🚨 Room Creation Failed: {room_data.get('message')}")

            # ==========================================
            # 2. DELETE COMPLETED MATCH ROOMS
            # ==========================================
            cleanup_resp = await client.get(f"{FASTAPI_URL}/tournaments/matches/need-cleanup", timeout=5.0)
            print(f"DEBUG: Cleanup check returned: {cleanup_resp.json()}")
            if cleanup_resp.status_code == 200:
                for match in cleanup_resp.json():
                    print(f"🧹 Match {match['match_id'][:6]} completed. Deleting channel...")
                    
                    channel_id = int(match["channel_id"])
                    channel = bot.get_channel(channel_id)
                    
                    if channel:
                        try:
                            # Instead of deleting immediately, lock it so admins can review if needed
                            await channel.set_permissions(channel.guild.default_role, send_messages=False)
                            await channel.send("🔒 **MATCH COMPLETED.** This channel is now locked and will be deleted shortly.")
                            
                            # You can keep the delete command here, or move it to a delayed task!
                            # await channel.delete(reason="Match is totally completed.")
                        except Exception as e:
                            print(f"Failed to manage channel {channel_id}: {e}")
                            
                    # Tell FastAPI to clear the ID from the database so it stops asking
                    await client.put(
                        f"{FASTAPI_URL}/tournaments/matches/{match['match_id']}/room",
                        json={"channel_id": None}
                    )

            # ==========================================
            # 3. SYNC TOURNAMENT CAPTAIN ROLES
            # ==========================================
            role_resp = await client.get(f"{FASTAPI_URL}/tournaments/active-captains", timeout=5.0)
            if role_resp.status_code == 200:
                active_captain_ids = [int(cid) for cid in role_resp.json()]
                
                guild = bot.get_guild(GUILD_ID)
                if guild:
                    captain_role = discord.utils.get(guild.roles, name="Captain")
                    if captain_role:
                        
                        # A. Remove the role from players who shouldn't have it anymore
                        for member in captain_role.members:
                            if member.id not in active_captain_ids:
                                print(f"🔒 Removing Captain role from {member.name} (Tournament changed)")
                                await member.remove_roles(captain_role)
                                
                        # B. Add the role to players who are missing it (failsafe)
                        for cid in active_captain_ids:
                            member = guild.get_member(cid)
                            if member and captain_role not in member.roles:
                                print(f"👑 Restoring Captain role to {member.name}")
                                await member.add_roles(captain_role)

        except httpx.ConnectError:
            pass # Silent fail if FastAPI isn't booted up yet
        except Exception as e:
            print(f"Heartbeat Manager Error: {e}")

@match_room_manager.before_loop
async def before_manager():
    await bot.wait_until_ready() # Wait for the bot to fully boot up first
    
@tasks.loop(seconds=30)
async def tournament_alarm_clock():
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(f"{FASTAPI_URL}/tournaments/active")
            if res.status_code != 200: return
            
            tournament = res.json()
            t_id = tournament["id"]
            
            if tournament.get("scheduled_start"):
                sched_str = tournament["scheduled_start"]
                if not sched_str.endswith('Z') and '+' not in sched_str:
                    sched_str += 'Z'
                    
                start_time = datetime.fromisoformat(sched_str.replace('Z', '+00:00'))
                now = datetime.now(timezone.utc)
                
                # Calculate the difference in seconds
                time_diff = (now - start_time).total_seconds()
                
                # ⏰ Check if 'now' is past the start time, BUT NO MORE than 5 minutes (300s) past it
                if 0 <= time_diff <= 300:
                    match_res = await client.get(f"{FASTAPI_URL}/tournaments/{t_id}/matches")
                    if match_res.status_code == 404:
                        print(f"⏰ IT IS TIME! Generating bracket for {tournament['name']}...")
                        await client.post(f"{FASTAPI_URL}/tournaments/{t_id}/generate-bracket")
        except Exception as e:
            print(f"Alarm Clock Error: {e}")
    
@bot.event
async def on_ready():
    await bot.tree.sync()
    tournament_alarm_clock.start()
    match_room_manager.start()
    print("Bot is online and commands synced!")

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN missing in .env")
    else:
        bot.run(TOKEN)