import httpx
import discord
import os
import sys
import re
import asyncio
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import datetime, timezone

try:
    from services.rag_service import ask_rulebook
    RAG_AVAILABLE = True
except ImportError:
    RAG_AVAILABLE = False
    def ask_rulebook(q): return "Rulebook feature coming soon!"

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True  
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

FASTAPI_URL = "http://127.0.0.1:8000"
guild_id_str = os.getenv("DISCORD_GUILD_ID")
GUILD_ID = int(guild_id_str) if guild_id_str else None


# --- UI VIEWS ---
class ReportScoreView(discord.ui.View):
    def __init__(self, tournament_id: str, match_id: str, team_a_id: str, team_b_id: str, team_a_name: str, team_b_name: str):
        super().__init__(timeout=None) 
        self.tournament_id = tournament_id
        self.match_id = match_id
        self.team_a_id = team_a_id
        self.team_b_id = team_b_id

        btn_a = discord.ui.Button(label=f"🏆 {team_a_name} Won", style=discord.ButtonStyle.success, custom_id=f"win_a_{match_id}")
        btn_a.callback = self.team_a_clicked
        self.add_item(btn_a)

        btn_b = discord.ui.Button(label=f"🏆 {team_b_name} Won", style=discord.ButtonStyle.success, custom_id=f"win_b_{match_id}")
        btn_b.callback = self.team_b_clicked
        self.add_item(btn_b)
        
    @discord.ui.button(label="🚨 Call Admin / Dispute", style=discord.ButtonStyle.danger, custom_id="call_admin_btn")
    async def call_admin(self, interaction: discord.Interaction, button: discord.ui.Button):
        admin_role = discord.utils.get(interaction.guild.roles, name="Admin")
        ping = f"<@&{admin_role.id}>" if admin_role else "@here"
        
        await interaction.response.send_message(
            f"{ping} 🛑 **ADMIN ASSISTANCE REQUIRED!** 🛑\nA team has raised a dispute or needs a score correction in this match. Please investigate.",
            allowed_mentions=discord.AllowedMentions(roles=True, everyone=True)
        )

    async def send_report_to_backend(self, interaction: discord.Interaction, reported_winner_id: str):
        await interaction.response.defer(ephemeral=True)
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(
                    f"{FASTAPI_URL}/tournaments/{self.tournament_id}/matches/{self.match_id}/player-report",
                    json={"reporting_team_discord_id": str(interaction.user.id), "reported_winner_id": reported_winner_id}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data["status"] == "waiting": await interaction.followup.send("✅ Score recorded! Waiting for the opponent to confirm.", ephemeral=True)
                    elif data["status"] == "completed": await interaction.followup.send("🎉 Both teams agreed! Advancing bracket.", ephemeral=True)
                    elif data["status"] == "disputed": await interaction.followup.send("🚨 Conflict detected! An admin has been notified.", ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ Error: {response.json().get('detail', 'Unknown error')}", ephemeral=True)
            except Exception as e:
                await interaction.followup.send("🚨 Error contacting the backend.", ephemeral=True)

    async def team_a_clicked(self, interaction: discord.Interaction): await self.send_report_to_backend(interaction, self.team_a_id)
    async def team_b_clicked(self, interaction: discord.Interaction): await self.send_report_to_backend(interaction, self.team_b_id)


class TeamInviteView(discord.ui.View):
    def __init__(self, captain_id: str, new_user_id: str, player_name: str, game_id: str, team_name: str, tournament_name: str):
        super().__init__(timeout=86400) 
        self.captain_id = captain_id
        self.new_user_id = new_user_id
        self.player_name = player_name
        self.game_id = game_id
        self.team_name = team_name
        self.tournament_name = tournament_name

    @discord.ui.button(label="Accept Invite", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.new_user_id:
            await interaction.response.send_message("This invite is not for you!", ephemeral=True)
            return

        await interaction.response.defer()
        payload = {
            "captain_discord_id": self.captain_id, "new_player_name": self.player_name,
            "new_player_game_id": self.game_id, "new_discord_id": self.new_user_id
        }
        
        async with httpx.AsyncClient() as client:
            try:
                res = await client.post(f"{FASTAPI_URL}/register/confirm-teammate", json=payload)
                if res.status_code == 200:
                    for child in self.children: child.disabled = True
                    
                    guild = interaction.client.get_guild(GUILD_ID)
                    if guild:
                        member = guild.get_member(int(interaction.user.id)) or await guild.fetch_member(int(interaction.user.id))
                        if member:
                            prefixed_role_name = f"{self.tournament_name}-{self.team_name}"
                            team_role = discord.utils.get(guild.roles, name=prefixed_role_name)
                            if not team_role:
                                team_role = await guild.create_role(name=prefixed_role_name, color=discord.Color.random(), mentionable=True)
                            await member.add_roles(team_role)
                    
                    verification_msg = (
                        f"✅ You have successfully joined **{self.team_name}** in {self.tournament_name}!\n\n"
                        f"**ACTION REQUIRED:** Please complete your player verification here:\n"
                        f"https://your-verification-portal.com/verify"
                    )
                    await interaction.edit_original_response(content=verification_msg, view=self)
                else:
                    await interaction.followup.send(f"Error: {res.json().get('detail', 'Server error')}", ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"Critical error: {e}", ephemeral=True)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.new_user_id:
            await interaction.response.send_message("This invite is not for you!", ephemeral=True)
            return
        for child in self.children: child.disabled = True
        await interaction.response.edit_message(content=f"You declined the invite to join **{self.team_name}**.", view=self)

# --- COMMANDS & HELPERS ---

@bot.command(name="setup_join")
@commands.has_permissions(administrator=True)
async def setup_join_channel(ctx, tournament_id: str):
    async with httpx.AsyncClient() as client:
        res = await client.get(f"{FASTAPI_URL}/tournaments/{tournament_id}")
        if res.status_code != 200:
            await ctx.send("❌ Could not find a tournament with that ID in the database.")
            return
        t_name = res.json().get("name")
    
    view = discord.ui.View(timeout=None)
    btn = discord.ui.Button(label=f"Register / Manage: {t_name}", style=discord.ButtonStyle.primary, custom_id=f"join_t_{tournament_id}")
    view.add_item(btn)
    
    await ctx.send(f"🏆 **{t_name}**\nClick below to register or manage your team for this specific tournament!", view=view)
    await ctx.message.delete()

async def create_match_room(guild_id: int, match_id: str, team_a_name: str, team_b_name: str, round_num: int, match_num: int, unix_time: int, tournament_name: str, view: discord.ui.View = None):
    guild = bot.get_guild(guild_id)
    if not guild: return {"success": False, "message": "Bot cannot find the Server."}

    category_name = f"🏆 {tournament_name}"
    category = discord.utils.get(guild.categories, name=category_name)
    if not category:
        category = await guild.create_category(category_name)

    base_name = f"rd{round_num}-match{match_num}"

    existing_channel = discord.utils.get(category.text_channels, name=base_name)
    if existing_channel:
        existing_vc = discord.utils.get(category.voice_channels, name=f"{base_name} VC")
        vc_id = existing_vc.id if existing_vc else ""
        return {"success": True, "channel_id": f"{existing_channel.id},{vc_id}"}

    role_a = discord.utils.get(guild.roles, name=f"{tournament_name}-{team_a_name}")
    role_b = discord.utils.get(guild.roles, name=f"{tournament_name}-{team_b_name}")

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False, connect=False),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True)
    }
    
    if role_a: overwrites[role_a] = discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True, speak=True, stream=True)
    if role_b: overwrites[role_b] = discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True, speak=True, stream=True)
    
    try:
        match_channel = await guild.create_text_channel(name=base_name, category=category, overwrites=overwrites, topic=f"Match {match_num} | Report scores here.")
        voice_channel = await guild.create_voice_channel(name=f"{base_name} VC", category=category, overwrites=overwrites)

        team_a_mention = f"<@&{role_a.id}>" if role_a else f"**{team_a_name}**"
        team_b_mention = f"<@&{role_b.id}>" if role_b else f"**{team_b_name}**"

        welcome_msg = (
            f"⚔️ **MATCH ROOM CREATED** ⚔️\n"
            f"Welcome {team_a_mention} and {team_b_mention}.\n\n"
            f"⏰ **Scheduled Start:** <t:{unix_time}:F>\n"
            f"🎙️ **Voice Channel:** <#{voice_channel.id}>\n\n"
            f"Please share server passwords or IPs here. Stream your games in the Voice Channel above. When the match is over, report the score below!"
        )
        
        await match_channel.send(welcome_msg, view=view)
        return {"success": True, "channel_id": f"{match_channel.id},{voice_channel.id}"}
        
    except Exception as e:
        return {"success": False, "message": f"Discord API Error: {e}"}


# --- EVENTS ---

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.component:
        custom_id = interaction.data.get("custom_id", "")
        
        if custom_id.startswith("join_t_"):
            tournament_id = custom_id.replace("join_t_", "")
            
            async with httpx.AsyncClient() as client:
                await client.put(f"{FASTAPI_URL}/tournaments/users/{interaction.user.id}/context", json={"tournament_id": tournament_id})
                res = await client.get(f"{FASTAPI_URL}/tournaments/{tournament_id}")
                t_name = res.json().get("name", "the tournament")
            
            try:
                await interaction.user.send(
                    f"✅ **Context Set: {t_name}**\n\n"
                    f"I now know you are talking about **{t_name}**! All DM commands you send me will apply to this tournament.\n\n"
                    "**1. Register:** 'I want to register Team Alpha. My ID is PlayerOne123 and phone is 555-0199.'\n"
                    "**2. Add Player:** 'Add my friend. Their Discord ID is 123456789012345678 and Game ID is Ninja99.'\n"
                    "**3. Edit Player:** 'Change my teammate Ninja99's game ID to SuperNinja.'\n"
                    "**4. Remove Player:** 'Remove Ninja99 from my team.'\n"
                    "**5. My Info:** 'Please tell me my information.'\n"
                )
                await interaction.response.send_message(f"📬 Check your DMs! Your focus is now set to **{t_name}**.", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message("🚨 I tried to send you a DM, but your privacy settings are blocking it.", ephemeral=True)
                
    if not interaction.response.is_done():
        try:
            await bot.process_application_commands(interaction)
        except: pass

@bot.event
async def on_message(message):
    if message.author.bot: return
    is_dm = isinstance(message.channel, discord.DMChannel)
    
    if not is_dm:
        allowed_channels = ["registration", "general", "bot-testing", "join-tournament"]
        if "🏆" not in getattr(message.channel.category, "name", "") and message.channel.name not in allowed_channels:
            await bot.process_commands(message)
            return
    
    discord_id = str(message.author.id)
    content = message.content

    with open("discord_chat_log.txt", "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] [{message.author.name}]: {content}\n")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            payload = {"message": content, "discord_id": discord_id, "timestamp": str(datetime.now(timezone.utc))}
            response = await client.post(f"{FASTAPI_URL}/tournaments/nlp-parse", json=payload)
            
            if response.status_code == 200:
                data = response.json()
                intent = data.get("intent")
                
                if intent == "register_team":
                    if not is_dm:
                        await message.channel.send("⚠️ Please manage registration inside my DMs to keep the server clean!")
                        return

                    context_req = await client.get(f"{FASTAPI_URL}/tournaments/users/{discord_id}/context")
                    if context_req.status_code != 200:
                        await message.channel.send("❌ You haven't selected a tournament yet! Go to the server and click the 'Register' button for the tournament you want to join.")
                        return
                    
                    tournament_id = context_req.json()["tournament_id"]
                    t_name = context_req.json()["tournament_name"]
                    
                    team_name = data.get("team_name") or f"{message.author.name}'s Team"
                    contact_info = data.get("contact") or "Not provided"

                    reg_payload = {
                        "tournament_id": tournament_id, "team_name": team_name, "contact": contact_info,
                        "players": [{"name": data.get("captain_name") or message.author.name, "game_id": data.get("captain_game_id") or "Unknown", "discord_id": discord_id}]
                    }
                    reg_response = await client.post(f"{FASTAPI_URL}/register/team", json=reg_payload)
                    
                    if reg_response.status_code == 200:
                        guild = bot.get_guild(GUILD_ID)
                        if guild:
                            member = guild.get_member(int(discord_id)) or await guild.fetch_member(int(discord_id))
                            if member:
                                team_role_name = f"{t_name}-{team_name}"
                                cap_role_name = f"{t_name}-Captain"
                                
                                team_role = discord.utils.get(guild.roles, name=team_role_name)
                                if not team_role: team_role = await guild.create_role(name=team_role_name, color=discord.Color.random(), mentionable=True)
                                await member.add_roles(team_role)
                                
                                captain_role = discord.utils.get(guild.roles, name=cap_role_name)
                                if not captain_role: captain_role = await guild.create_role(name=cap_role_name, color=discord.Color.gold(), mentionable=True)
                                await member.add_roles(captain_role)

                        success_msg = (
                            f"✅ Successfully registered **{team_name}** for **{t_name}**! Your roles have been updated.\n\n"
                            f"**ACTION REQUIRED:** To complete your team's verification, please visit our portal:\n"
                            f"https://your-verification-portal.com/verify"
                        )
                        await message.channel.send(success_msg)
                    else:
                        await message.channel.send(f"🚨 Failed: {reg_response.json().get('detail')}")

                elif intent == "report_score":
                    if is_dm:
                        await message.channel.send("⚠️ Scores must be reported directly inside your Match Room channel, not in DMs!")
                        return
                    report_payload = {"discord_id": discord_id, "reported_winner": data.get("reported_winner"), "reported_loser": data.get("reported_loser"), "channel_id": str(message.channel.id)}
                    score_response = await client.post(f"{FASTAPI_URL}/tournaments/nlp-report", json=report_payload)
                    if score_response.status_code == 200: await message.channel.send(score_response.json().get("message"))
                    else: await message.channel.send(f"⚠️ Report blocked: {score_response.json().get('detail')}")

                elif intent == "add_teammate":
                    if not is_dm:
                        await message.channel.send("⚠️ Please manage your team via DMs to keep the server clean!")
                        return

                    context_req = await client.get(f"{FASTAPI_URL}/tournaments/users/{discord_id}/context")
                    if context_req.status_code != 200:
                        await message.channel.send("❌ You haven't selected a tournament yet! Go click a Join button first.")
                        return
                    t_name = context_req.json()["tournament_name"]

                    extracted_numbers = re.findall(r'\d{17,20}', content)
                    if not extracted_numbers:
                        await message.channel.send("⚠️ I could not find a valid Discord ID in your message.")
                        return
                        
                    new_discord_id = extracted_numbers[0]
                    guild = bot.get_guild(GUILD_ID)
                    if not guild: return
                    
                    member = guild.get_member(int(new_discord_id))
                    if not member:
                        try: member = await guild.fetch_member(int(new_discord_id))
                        except discord.NotFound:
                            await message.channel.send(f"❌ **Error:** The user must join the server before you can add them to your team!")
                            return

                    new_id = data.get("new_player_game_id") or "Unknown"
                    new_name = data.get("new_player_name") or member.display_name

                    add_payload = {
                        "discord_id": discord_id, "new_player_name": new_name,
                        "new_player_game_id": new_id, "new_player_discord_mention": new_discord_id
                    }
                    add_response = await client.post(f"{FASTAPI_URL}/register/nlp-add-teammate", json=add_payload)
                    if add_response.status_code == 200:
                        team_name = add_response.json().get("team_name")
                        view = TeamInviteView(captain_id=discord_id, new_user_id=new_discord_id, player_name=new_name, game_id=new_id, team_name=team_name, tournament_name=t_name)
                        try:
                            await member.send(f"👋 Hey! <@{discord_id}> wants you to join **{team_name}** for **{t_name}**. Do you accept?", view=view)
                            await message.channel.send(f"✅ I sent an invite directly to their DMs!")
                        except:
                            await message.channel.send(f"⚠️ I found them, but their DMs are closed. Ask them to open their DMs and try again.")
                    else:
                        await message.channel.send(f"🚨 Failed: {add_response.json().get('detail')}")

                elif intent in ["edit_team", "edit_player", "remove_player"]:
                    if not is_dm:
                        await message.channel.send("⚠️ Please manage your team via DMs!")
                        return
                    endpoint_map = {"edit_team": "nlp-edit-team", "edit_player": "nlp-edit-player", "remove_player": "nlp-remove-player"}
                    res = await client.post(f"{FASTAPI_URL}/register/{endpoint_map[intent]}", json={"discord_id": discord_id, **data})
                    if res.status_code == 200: await message.channel.send(f"✅ Success: {res.json().get('message')}")
                    else: await message.channel.send(f"❌ Failed: {res.json().get('detail')}")

                elif intent == "get_info":
                    if not is_dm:
                        await message.channel.send("⚠️ Please DM me to check your private info!")
                        return

                    context_req = await client.get(f"{FASTAPI_URL}/tournaments/users/{discord_id}/context")
                    if context_req.status_code != 200:
                        await message.channel.send("❌ You haven't selected a tournament yet! Go click a Join button first.")
                        return
                    
                    tournament_id = context_req.json()["tournament_id"]
                    info_req = await client.get(f"{FASTAPI_URL}/register/my-info?discord_id={discord_id}&tournament_id={tournament_id}")
                    if info_req.status_code == 200:
                        data = info_req.json()
                        role = "👑 Captain" if data.get("is_captain") else "👤 Player"
                        roster_list = "\n".join([f"• {p}" for p in data["roster"]])
                        
                        msg = (
                            f"📋 **YOUR TOURNAMENT INFO** 📋\n\n"
                            f"**Team:** {data['team_name']}\n"
                            f"**Role:** {role}\n\n"
                            f"👥 **Roster:**\n{roster_list}\n\n"
                            f"⚔️ **Next Match:**\n{data['match_info']}"
                        )
                        await message.channel.send(msg)
                    else:
                        await message.channel.send(f"🚨 {info_req.json().get('detail')}")

                elif intent == "help":
                    await message.channel.send("🤖 **AutoTournament Bot**\nAll team management happens inside DMs. Tell me what you want to do (e.g., 'Register Team Alpha', 'Remove player Ninja99', 'What is my info?').")

        except Exception as e: print(f"FastAPI Error: {e}")

    await bot.process_commands(message)


# --- BACKGROUND TASKS ---
@tasks.loop(seconds=5)
async def match_room_manager():
    if not GUILD_ID: return
    async with httpx.AsyncClient() as client:
        try:
            # 1. CREATE NEW MATCH ROOMS
            room_resp = await client.get(f"{FASTAPI_URL}/tournaments/matches/need-rooms", timeout=5.0)
            if room_resp.status_code == 200:
                for match in room_resp.json():
                    sched_str = match.get("scheduled_time")
                    if not sched_str: continue
                        
                    if not sched_str.endswith('Z') and '+' not in sched_str: sched_str += '+00:00'
                    else: sched_str = sched_str.replace('Z', '+00:00')
                        
                    sched_time = datetime.fromisoformat(sched_str)
                    if (sched_time - datetime.now(timezone.utc)).total_seconds() <= 180:
                        
                        t_resp = await client.get(f"{FASTAPI_URL}/tournaments/{match['tournament_id']}")
                        t_name = t_resp.json().get("name", "Tournament") if t_resp.status_code == 200 else "Tournament"
                        
                        view = ReportScoreView(
                            tournament_id=match["tournament_id"], match_id=match["match_id"],
                            team_a_id=match["team_a_id"], team_b_id=match["team_b_id"],
                            team_a_name=match["team_a_name"], team_b_name=match["team_b_name"]
                        )
                        room_data = await create_match_room(
                            guild_id=GUILD_ID, match_id=match["match_id"], team_a_name=match["team_a_name"],
                            team_b_name=match["team_b_name"], round_num=match["round_number"],
                            match_num=match["match_number"], unix_time=int(sched_time.timestamp()), 
                            tournament_name=t_name, view=view
                        )
                        if room_data["success"]:
                            await client.put(f"{FASTAPI_URL}/tournaments/matches/{match['match_id']}/room", json={"channel_id": room_data["channel_id"]})

            # 2. 🚨 INSTANT INLINE DELETION FOR MATCH ROOMS 🚨
            cleanup_resp = await client.get(f"{FASTAPI_URL}/tournaments/matches/need-cleanup", timeout=5.0)
            if cleanup_resp.status_code == 200:
                for match in cleanup_resp.json():
                    match_id = match["match_id"]
                    channel_data = match.get("channel_id")
                    winner_name = match.get("winner_name", "The winning team")
                    
                    if channel_data:
                        channel_parts = [c.strip() for c in channel_data.split(",") if c.strip()]
                        target_category = None
                        
                        print(f"\n🗑️ INITIATING INSTANT CLEANUP FOR MATCH: {match_id}")
                        
                        for cid in channel_parts:
                            try:
                                channel = bot.get_channel(int(cid)) or await bot.fetch_channel(int(cid))
                                if channel:
                                    target_category = channel.category
                                    channel_name = channel.name
                                    
                                    # Send brief goodbye message if it's a text channel
                                    if isinstance(channel, discord.TextChannel):
                                        try:
                                            await channel.send(f"🛡️ **MATCH COMPLETED** 🛡️\n**{winner_name}** won! Closing room...")
                                            await asyncio.sleep(2) # Give players 2 seconds to see it
                                        except Exception: pass
                                        
                                    await channel.delete(reason="Match completed.")
                                    print(f"✅ Deleted Channel: {channel_name}")
                            except discord.Forbidden:
                                print(f"❌ PERMISSION ERROR: The bot does not have 'Manage Channels' permission to delete {cid}!")
                            except Exception as e:
                                print(f"⚠️ Could not delete channel {cid}: {e}")
                        
                        if target_category:
                            try:
                                await asyncio.sleep(1) # tiny pause for Discord servers to sync
                                fresh_cat = bot.get_channel(target_category.id) or await bot.fetch_channel(target_category.id)
                                if fresh_cat and len(fresh_cat.channels) == 0:
                                    cat_name = fresh_cat.name
                                    await fresh_cat.delete(reason="All tournament matches closed.")
                                    print(f"✅ Deleted Empty Category: {cat_name}")
                            except discord.Forbidden:
                                print(f"❌ PERMISSION ERROR: The bot does not have 'Manage Channels' permission for Category {target_category.name}!")
                            except Exception as e:
                                print(f"⚠️ Category skip: {e}")
                                
                        # Unbind from backend instantly so it doesn't loop again
                        await client.put(f"{FASTAPI_URL}/tournaments/matches/{match_id}/room", json={"channel_id": None})
                        print(f"✅ Cleared match {match_id} from database.\n")

            # 3. ROLE SYNC, PURGE & AUTO-CLEANUP 
            tournaments_resp = await client.get(f"{FASTAPI_URL}/tournaments/", timeout=5.0)
            if tournaments_resp.status_code == 200:
                for tourney in tournaments_resp.json():
                    t_id = tourney["id"]
                    t_name = tourney["name"]
                    
                    # 🚨 3.5 AUTO-CLEANUP EXPIRED TOURNAMENT ROLES
                    if tourney.get("status") == "completed" or tourney.get("is_active") is False:
                        guild = bot.get_guild(GUILD_ID)
                        if guild:
                            for role in guild.roles:
                                if role.name.startswith(f"{t_name}-"):
                                    try:
                                        role_name = role.name
                                        await role.delete(reason=f"Tournament {t_name} is inactive/completed. Auto-cleaning roles.")
                                        print(f"🧹 Auto-deleted expired role: {role_name}")
                                    except discord.Forbidden:
                                        print(f"❌ PERMISSION ERROR: Bot cannot delete role {role.name}.")
                                    except Exception:
                                        pass
                        continue # Skip the rest of the sync if the tournament is expired!
                    
                    # Normal Active Sync
                    if tourney.get("sync_roles_requested"):
                        roster_resp = await client.get(f"{FASTAPI_URL}/tournaments/{t_id}/rosters", timeout=15.0)
                        if roster_resp.status_code == 200:
                            guild = bot.get_guild(GUILD_ID)
                            if guild:
                                rosters = roster_resp.json()
                                
                                captain_role_name = f"{t_name}-Captain"
                                verified_role_name = f"{t_name}-Verified"
                                valid_team_roles = [f"{t_name}-{team['team_name']}" for team in rosters]
                                
                                active_cap_ids = [int(t["captain_discord_id"]) for t in rosters if t["captain_discord_id"]]
                                verified_ids = []
                                for t in rosters: verified_ids.extend([int(vid) for vid in t.get("verified_player_ids", [])])

                                for role in guild.roles:
                                    if role.name.startswith(f"{t_name}-"):
                                        if role.name not in valid_team_roles and role.name not in [captain_role_name, verified_role_name]:
                                            try:
                                                await role.delete(reason=f"Tournament Sync: Purging old roles for {t_name}")
                                            except Exception: pass

                                captain_role = discord.utils.get(guild.roles, name=captain_role_name) or await guild.create_role(name=captain_role_name, color=discord.Color.gold(), mentionable=True)
                                verified_role = discord.utils.get(guild.roles, name=verified_role_name) or await guild.create_role(name=verified_role_name, color=discord.Color.green())

                                for team in rosters:
                                    team_role_name = f"{t_name}-{team['team_name']}"
                                    cap_id = team["captain_discord_id"]
                                    team_role = discord.utils.get(guild.roles, name=team_role_name) or await guild.create_role(name=team_role_name, mentionable=True)
                                    player_ids = [int(p) for p in team["player_discord_ids"] if p]

                                    for member in team_role.members:
                                        if member.id not in player_ids and member.id != (int(cap_id) if cap_id else None):
                                            try: await member.remove_roles(team_role)
                                            except: pass

                                    for pid in player_ids + ([int(cap_id)] if cap_id else []):
                                        member = guild.get_member(pid) or await guild.fetch_member(pid)
                                        if member and team_role not in member.roles:
                                            try: await member.add_roles(team_role)
                                            except: pass

                                    if cap_id:
                                        cap_member = guild.get_member(int(cap_id)) or await guild.fetch_member(int(cap_id))
                                        if cap_member and captain_role not in cap_member.roles:
                                            try: await cap_member.add_roles(captain_role)
                                            except: pass

                                for member in captain_role.members:
                                    if member.id not in active_cap_ids:
                                        try: await member.remove_roles(captain_role)
                                        except: pass
                                        
                                for member in verified_role.members:
                                    if member.id not in verified_ids:
                                        try: await member.remove_roles(verified_role)
                                        except: pass
                                        
                                for vid in verified_ids:
                                    member = guild.get_member(vid) or await guild.fetch_member(vid)
                                    if member and verified_role not in member.roles:
                                        try: await member.add_roles(verified_role)
                                        except: pass
                                            
                        await client.post(f"{FASTAPI_URL}/tournaments/{t_id}/admin/reset-flags", json={"roles": True})

                    if tourney.get("sync_channels_requested"):
                        await client.post(f"{FASTAPI_URL}/tournaments/{t_id}/admin/force-reset-channels")
                        await client.post(f"{FASTAPI_URL}/tournaments/{t_id}/admin/reset-flags", json={"channels": True})

            # 4. TASK LISTENER FOR ANNOUNCEMENTS & PINGS
            task_resp = await client.get(f"{FASTAPI_URL}/tournaments/admin/pending-tasks", timeout=5.0)
            if task_resp.status_code == 200:
                for task in task_resp.json():
                    task_type = task["task_type"]
                    t_id = task["tournament_id"]
                    
                    if task_type == "post_announcement":
                        t_resp = await client.get(f"{FASTAPI_URL}/tournaments/{t_id}")
                        logs_resp = await client.get(f"{FASTAPI_URL}/tournaments/{t_id}/logs")
                        
                        if t_resp.status_code == 200 and logs_resp.status_code == 200:
                            t_name = t_resp.json().get("name", "Tournament")
                            logs = logs_resp.json()
                            
                            discord_logs = [l for l in logs if l["platform"] == "discord"]
                            announcement_text = discord_logs[0]["content"] if discord_logs else f"Registrations are OPEN for **{t_name}**!"
                            
                            guild = bot.get_guild(GUILD_ID)
                            if guild:
                                reg_channel = discord.utils.get(guild.text_channels, name="join-tournament")
                                if not reg_channel: reg_channel = await guild.create_text_channel("join-tournament")
                                    
                                view = discord.ui.View(timeout=None)
                                btn = discord.ui.Button(label=f"Register / Manage: {t_name}", style=discord.ButtonStyle.primary, custom_id=f"join_t_{t_id}")
                                view.add_item(btn)
                                await reg_channel.send(content=announcement_text, view=view)
                                
                    elif task_type.startswith("broadcast_"):
                        memory_id = task_type.split("broadcast_")[1]
                        logs_resp = await client.get(f"{FASTAPI_URL}/tournaments/{t_id}/logs")
                        if logs_resp.status_code == 200:
                            logs = logs_resp.json()
                            memory = next((l for l in logs if l["id"] == memory_id), None)
                            if memory:
                                guild = bot.get_guild(GUILD_ID)
                                if guild:
                                    target_channel = discord.utils.get(guild.text_channels, name="general") or discord.utils.get(guild.text_channels, name="join-tournament")
                                    if target_channel: 
                                        await target_channel.send(memory["content"])
                                        
                    await client.delete(f"{FASTAPI_URL}/tournaments/admin/pending-tasks/{task['id']}")
        except Exception as e:
            pass

@match_room_manager.before_loop
async def before_manager(): await bot.wait_until_ready() 

@tasks.loop(seconds=30)
async def tournament_alarm_clock():
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(f"{FASTAPI_URL}/tournaments/active")
            if res.status_code != 200: return
            
            tournament = res.json()
            if tournament.get("scheduled_start"):
                sched_str = tournament["scheduled_start"]
                if not sched_str.endswith('Z') and '+' not in sched_str: sched_str += 'Z'
                start_time = datetime.fromisoformat(sched_str.replace('Z', '+00:00'))
                
                if 0 <= (datetime.now(timezone.utc) - start_time).total_seconds() <= 300:
                    match_res = await client.get(f"{FASTAPI_URL}/tournaments/{tournament['id']}/matches")
                    if match_res.status_code == 404: 
                        print(f"Generating bracket for {tournament['name']}...")
                        await client.post(f"{FASTAPI_URL}/tournaments/{tournament['id']}/generate-bracket")
        except Exception as e: pass

@bot.event
async def on_ready():
    await bot.tree.sync()
    tournament_alarm_clock.start()
    match_room_manager.start()
    print("Bot is online and ready!")

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if TOKEN: bot.run(TOKEN)