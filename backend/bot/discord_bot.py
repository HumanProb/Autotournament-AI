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
                    team_name = data.get("team_name") or f"{message.author.name}'s Team"
                    
                    reg_payload = {
                        "tournament_id": tournament_id,
                        "team_name": team_name, 
                        "contact": data.get("contact") or "Not provided",
                        "players": [{"name": data.get("captain_name") or message.author.name, "game_id": data.get("captain_game_id") or "Unknown", "discord_id": discord_id}]
                    }
                    
                    reg_response = await client.post(f"{FASTAPI_URL}/register/team", json=reg_payload)
                    
                    if reg_response.status_code == 200:
                        await message.channel.send(f"✅ Successfully registered **{team_name}**!")
                        
                        try:
                            # 🚨 NEW: Create the Custom Team Role!
                            # Generates a random color for the team role to make it look cool
                            team_role = await message.guild.create_role(
                                name=team_name, 
                                color=discord.Color.random(), 
                                reason="Tournament Team Creation",
                                mentionable=True
                            )
                            # Give the role to the captain who registered
                            await message.author.add_roles(team_role)
                            await message.channel.send(f"🎨 Created the custom role <@&{team_role.id}> and assigned it to you!")
                            
                            # 1. First, check if the Captain role exists
                            captain_role = discord.utils.get(message.guild.roles, name="Captain")
                            if captain_role:
                                await message.author.add_roles(captain_role)
                                await message.channel.send(f"👑 **{message.author.name}**, you have been granted the Captain role!")
                                
                        except discord.Forbidden:
                            print("🚨 ERROR: Discord Forbidden. The Bot lacks 'Manage Roles' permission.")
                            await message.channel.send("⚠️ Note: I don't have permission to create Team Roles or assign the Captain role. An admin needs to fix my settings!")
                        

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
                    
                    # 1. Use Discord's native mention detector (Bulletproof!)
                    if not message.mentions:
                        await message.channel.send("⚠️ You must actually PING the user (e.g., @username) to add them!")
                        return
                        
                    pinged_user = message.mentions[0]
                    new_discord_id = str(pinged_user.id)

                    # 2. Get the game ID from the AI
                    new_id = data.get("new_player_game_id")
                    
                    if not new_id:
                        await message.channel.send("⚠️ I couldn't understand their in-game ID. Try: *'Add @friend to my team, his game ID is John123'*")
                        return
                        
                    # 3. If the AI didn't find a "real name", just use their Discord name
                    new_name = data.get("new_player_name") or pinged_user.display_name

                    add_payload = {
                        "discord_id": discord_id,
                        "new_player_name": new_name,
                        "new_player_game_id": new_id,
                        "new_player_discord_mention": f"<@{new_discord_id}>" # Send the exact format the backend expects
                    }
                    
                    add_response = await client.post(f"{FASTAPI_URL}/register/nlp-add-teammate", json=add_payload)
                    
                    if add_response.status_code == 200:
                        res_data = add_response.json()
                        team_name = res_data.get("team_name")
                        
                        # Generate the Interactive Invite!
                        view = TeamInviteView(
                            captain_id=discord_id,
                            new_user_id=new_discord_id,
                            player_name=new_name,
                            game_id=new_id,
                            team_name=team_name
                        )
                        await message.channel.send(f"Hey <@{new_discord_id}>! <@{discord_id}> wants you to join their team: **{team_name}**. Do you accept?", view=view)
                        
                    else:
                        await message.channel.send(f"🚨 Failed to invite player: {add_response.json().get('detail')}")

                elif intent == "edit_team":
                    print(f"INTENT DETECTED: {message.author.name} is editing a team name!")
                    
                    new_team_name = data.get("new_team_name")
                    
                    if not new_team_name:
                        await message.channel.send("I understood you want to change your team name, but I couldn't figure out the new name. Try: *'Change my team name to Team Alpha'*")
                        return

                    edit_team_payload = {
                        "discord_id": discord_id,
                        "new_team_name": new_team_name,
                        "target_original_identifier": data.get("target_original_identifier")
                    }
                    
                    edit_team_response = await client.post(f"{FASTAPI_URL}/register/nlp-edit-team", json=edit_team_payload)
                    
                    if edit_team_response.status_code == 200:
                        await message.channel.send(f"Success: {edit_team_response.json().get('message')}")
                        
                        # Optional: Try to update the Discord Role name if you created one earlier
                        try:
                            # Note: This is an advanced feature and requires finding the exact role
                            # If you skip this, only the database updates, which is perfectly fine.
                            pass 
                        except Exception:
                            pass
                    else:
                        await message.channel.send(f"Failed to edit team: {edit_team_response.json().get('detail')}")
                        
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
        # 1. TIMEOUT MUST BE NONE FOR PERSISTENCE
        super().__init__(timeout=None) 
        self.tournament_id = tournament_id
        self.match_id = match_id
        self.team_a_id = team_a_id
        self.team_b_id = team_b_id

        # 2. ASSIGN UNIQUE CUSTOM_IDs
        # We append the match_id to ensure the bot knows which match is being reported
        btn_a = discord.ui.Button(
            label=f"🏆 {team_a_name} Won", 
            style=discord.ButtonStyle.success,
            custom_id=f"win_a_{match_id}" 
        )
        btn_a.callback = self.team_a_clicked
        self.add_item(btn_a)

        btn_b = discord.ui.Button(
            label=f"🏆 {team_b_name} Won", 
            style=discord.ButtonStyle.success,
            custom_id=f"win_b_{match_id}"
        )
        btn_b.callback = self.team_b_clicked
        self.add_item(btn_b)
        
    @discord.ui.button(label="🚨 Call Admin / Dispute", style=discord.ButtonStyle.danger, custom_id="call_admin_btn")
    async def call_admin(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Optional: You can fetch an @Admin role here to ping them specifically
        admin_role = discord.utils.get(interaction.guild.roles, name="Admin")
        ping = f"<@&{admin_role.id}>" if admin_role else "@here"
        
        await interaction.response.send_message(
            f"{ping} 🛑 **ADMIN ASSISTANCE REQUIRED!** 🛑\nA team has raised a dispute or needs a score correction in this match. Please investigate.",
            allowed_mentions=discord.AllowedMentions(roles=True, everyone=True)
        )

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
                        "reporting_team_discord_id": str(interaction.user.id), # PASS DISCORD ID
                        "reported_winner_id": reported_winner_id
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

# --- TEAM INVITE BUTTON PANEL ---
class TeamInviteView(discord.ui.View):
    def __init__(self, captain_id: str, new_user_id: str, player_name: str, game_id: str, team_name: str):
        super().__init__(timeout=86400) # Invite expires in 24 hours
        self.captain_id = captain_id
        self.new_user_id = new_user_id
        self.player_name = player_name
        self.game_id = game_id
        self.team_name = team_name

    @discord.ui.button(label="Accept Invite", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.new_user_id:
            await interaction.response.send_message("This invite is not for you!", ephemeral=True)
            return

        await interaction.response.defer()
        
        payload = {
            "captain_discord_id": self.captain_id,
            "new_player_name": self.player_name,
            "new_player_game_id": self.game_id,
            "new_discord_id": self.new_user_id
        }
        
        async with httpx.AsyncClient() as client:
            try:
                res = await client.post(f"{FASTAPI_URL}/register/confirm-teammate", json=payload)
                
                # Check status code before parsing JSON
                if res.status_code == 200:
                    data = res.json()
                    for child in self.children:
                        child.disabled = True
                    
                    team_role = discord.utils.get(interaction.guild.roles, name=self.team_name)
                    if team_role:
                        await interaction.user.add_roles(team_role)
                    
                    await interaction.edit_original_response(
                        content=f"{interaction.user.mention} has joined **{self.team_name}**!", 
                        view=self
                    )
                else:
                    # Provide the specific error detail if available
                    try:
                        error_detail = res.json().get("detail", "Unknown server error")
                    except:
                        error_detail = "Server error"
                    await interaction.followup.send(f"Error: {error_detail}", ephemeral=True)
                    
            except Exception as e:
                await interaction.followup.send(f"Critical error: {e}", ephemeral=True)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.new_user_id:
            await interaction.response.send_message("This invite is not for you!", ephemeral=True)
            return
        
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content=f"<@{self.new_user_id}> declined the invite to join **{self.team_name}**.", view=self)
        
        
        
async def create_match_room(guild_id: int, match_id: str, team_a_name: str, team_b_name: str, 
                            round_num: int, match_num: int, unix_time: int, view: discord.ui.View = None):
    guild = bot.get_guild(guild_id)
    if not guild:
        return {"success": False, "message": "Bot cannot find the Server."}

    role_a = discord.utils.get(guild.roles, name=team_a_name)
    role_b = discord.utils.get(guild.roles, name=team_b_name)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }
    
    if role_a: overwrites[role_a] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
    if role_b: overwrites[role_b] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

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

        # ← Safe mention: use role mention if role exists, otherwise use team name as plain text
        team_a_mention = f"<@&{role_a.id}>" if role_a else f"**{team_a_name}**"
        team_b_mention = f"<@&{role_b.id}>" if role_b else f"**{team_b_name}**"

        welcome_msg = (
            f"⚔️ **MATCH ROOM CREATED** ⚔️\n"
            f"Welcome {team_a_mention} and {team_b_mention}.\n\n"
            f"⏰ **Scheduled Start:** <t:{unix_time}:F> (<t:{unix_time}:R>)\n\n"
            f"Please share server passwords or IPs here. When the match is over, use the buttons below!"
        )
        
        await match_channel.send(welcome_msg, view=view)
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
                    if not sched_str: continue
                        
                    # Timezone fix
                    if not sched_str.endswith('Z') and '+' not in sched_str:
                        sched_str += '+00:00'
                    else:
                        sched_str = sched_str.replace('Z', '+00:00')
                        
                    sched_time = datetime.fromisoformat(sched_str)
                    now = datetime.now(timezone.utc)
                    seconds_until_match = (sched_time - now).total_seconds()
                    
                    if seconds_until_match <= 180:
                        print(f"Creating private room for Round {match['round_number']} Match {match['match_number']}...")
                        unix_timestamp = int(sched_time.timestamp())
                        
                        view = ReportScoreView(
                            tournament_id=match["tournament_id"], 
                            match_id=match["match_id"],
                            team_a_id=match["team_a_id"],
                            team_b_id=match["team_b_id"],
                            team_a_name=match["team_a_name"],
                            team_b_name=match["team_b_name"]
                        )
                        
                        room_data = await create_match_room(
                            guild_id=GUILD_ID, 
                            match_id=match["match_id"],
                            team_a_name=match["team_a_name"],
                            team_b_name=match["team_b_name"],
                            round_num=match["round_number"],
                            match_num=match["match_number"],
                            unix_time=unix_timestamp,
                            view=view
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
            if cleanup_resp.status_code == 200:
                for match in cleanup_resp.json():
                    channel_id = int(match["channel_id"])
                    channel = bot.get_channel(channel_id)
                    
                    if channel:
                        try:
                            await channel.set_permissions(channel.guild.default_role, send_messages=False)
                            print(f"🧹 Deleting channel {channel.name}...")
                            await channel.delete(reason="Match is totally completed.")
                            print(f"✅ Channel {channel.name} successfully deleted.")
                        except discord.Forbidden:
                            print("🚨 PERMISSION ERROR: The bot does not have 'Manage Channels' permission!")
                        except Exception as e:
                            print(f"Failed to delete channel {channel_id}: {e}")
                            
                    await client.put(
                        f"{FASTAPI_URL}/tournaments/matches/{match['match_id']}/room",
                        json={"channel_id": None}
                    )

            # ==========================================
            # 3. SYNC TOURNAMENT ROLES (CAPTAINS & TEAMS)
            # ==========================================
            active_res = await client.get(f"{FASTAPI_URL}/tournaments/active", timeout=5.0)
            if active_res.status_code == 200:
                active_tourney = active_res.json()
                t_id = active_tourney["id"]

                # --- 🛠️ THE NEW SYNC LOGIC TRIGGER ---
                # --- 3. SYNC TOURNAMENT ROLES (CAPTAINS & TEAMS) ---
                if active_tourney.get("sync_roles_requested"):
                    print("👑 Admin requested Force Sync of ALL Roles...")
                    roster_resp = await client.get(f"{FASTAPI_URL}/tournaments/{t_id}/rosters", timeout=15.0)
                    
                    if roster_resp.status_code == 200:
                        rosters = roster_resp.json()
                        guild = bot.get_guild(GUILD_ID)
                        if guild:
                            # 1. Clean up Duplicates FIRST
                            print("🧹 Cleaning up duplicate roles...")
                            for team in rosters:
                                team_name = team["team_name"]
                                # Find all roles with this name
                                roles_found = [r for r in guild.roles if r.name == team_name]
                                if len(roles_found) > 1:
                                    # Sort by member count (keep the one with most members, delete the rest)
                                    roles_found.sort(key=lambda r: len(r.members), reverse=True)
                                    for extra_role in roles_found[1:]:
                                        try:
                                            await extra_role.delete(reason="Cleanup duplicate role")
                                            print(f"🗑️ Deleted duplicate: {extra_role.name}")
                                        except Exception as e:
                                            print(f"Could not delete duplicate {extra_role.name}: {e}")

                            # 2. Proceed to Sync
                            captain_role = discord.utils.get(guild.roles, name="Captain")
                            active_captain_ids = [int(t["captain_discord_id"]) for t in rosters if t["captain_discord_id"]]

                            for team in rosters:
                                team_name = team["team_name"]
                                cap_id = team["captain_discord_id"]
                                player_ids = [int(p) for p in team["player_discord_ids"] if p]

                                # Get the ONE remaining role
                                team_role = discord.utils.get(guild.roles, name=team_name)
                                if not team_role:
                                    team_role = await guild.create_role(name=team_name, color=discord.Color.random(), mentionable=True)

                                # Remove role from people not in DB
                                for member in team_role.members:
                                    if member.id not in player_ids and member.id != int(cap_id):
                                        await member.remove_roles(team_role)
                                        print(f"➖ Removed {member.name} from {team_name}")

                                # Add role to people in DB
                                for pid in player_ids + ([int(cap_id)] if cap_id else []):
                                    member = guild.get_member(pid) or await guild.fetch_member(pid)
                                    if member and team_role not in member.roles:
                                        await member.add_roles(team_role)
                                        print(f"➕ Added {member.name} to {team_name}")

                                # Captain Specifics
                                if cap_id and captain_role:
                                    cap_member = guild.get_member(int(cap_id)) or await guild.fetch_member(int(cap_id))
                                    if cap_member and captain_role not in cap_member.roles:
                                        await cap_member.add_roles(captain_role)
                                        print(f"👑 Added Captain role to {cap_member.name}")

                            # Remove Captain role from retired captains
                            if captain_role:
                                for member in captain_role.members:
                                    if member.id not in active_captain_ids:
                                        await member.remove_roles(captain_role)
                                        print(f"➖ Removed old captain role: {member.name}")

                    await client.post(f"{FASTAPI_URL}/tournaments/{t_id}/admin/reset-flags", json={"roles": True})

                # --- 🧹 THE CHANNELS SYNC TRIGGER ---
                if active_tourney.get("sync_channels_requested"):
                    print("🧹 Admin requested Force Sync of Channels...")
                    await client.post(f"{FASTAPI_URL}/tournaments/{t_id}/admin/force-reset-channels")
                    await client.post(f"{FASTAPI_URL}/tournaments/{t_id}/admin/reset-flags", json={"channels": True})

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
                time_diff = (now - start_time).total_seconds()
                
                if 0 <= time_diff <= 300:
                    match_res = await client.get(f"{FASTAPI_URL}/tournaments/{t_id}/matches")
                    if match_res.status_code == 404:  # ← only generate if no bracket exists
                        print(f"⏰ IT IS TIME! Generating bracket for {tournament['name']}...")
                        result = await client.post(f"{FASTAPI_URL}/tournaments/{t_id}/generate-bracket")
                        if result.status_code == 400:
                            print(f"Auto-bracket failed: {result.json().get('detail')}")
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