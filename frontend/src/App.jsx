import { useState, useEffect } from "react";
import AdminSyncControls from './AdminSyncControls';

const API_BASE = "http://127.0.0.1:8000";

// --- THE MAGIC TIMEZONE FIXER ---
const getUtcString = (isoString) => {
  if (!isoString) return "";
  // If SQLite stripped the timezone, force it back to UTC
  return isoString.endsWith('Z') || isoString.includes('+') ? isoString : isoString + 'Z';
};

const formatTimeOnly = (isoString) => {
  if (!isoString) return "";
  return new Date(getUtcString(isoString)).toLocaleString('en-IN', { 
      timeZone: 'Asia/Kolkata', 
      weekday: 'short', 
      hour: 'numeric', 
      minute: '2-digit' 
  });
};

const formatFullDate = (isoString) => {
  if (!isoString) return "No Date Set";
  return new Date(getUtcString(isoString)).toLocaleString('en-IN', { 
      timeZone: 'Asia/Kolkata',
      dateStyle: 'medium', 
      timeStyle: 'short' 
  });
};
// --------------------------------

function App() {
  const [tournament, setTournament] = useState(null);
  const [matches, setMatches] = useState([]);
  const [teams, setTeams] = useState([]); 
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("bracket"); 
  const [newTFormat, setNewTFormat] = useState("single_elimination");
  
  // Form variables
  const [scheduledStart, setScheduledStart] = useState("");
  const [minutesBetweenRounds, setMinutesBetweenRounds] = useState(120);
  const [prepTime, setPrepTime] = useState(30);
  const [tournaments, setTournaments] = useState([]);
  const [newTName, setNewTName] = useState("");
  const [newTGame, setNewTGame] = useState("");
  const [newTMinPlayers, setNewTMinPlayers] = useState(5);
  const [newTPrize, setNewTPrize] = useState("");
  const [newTFee, setNewTFee] = useState("");
  
  // Data arrays
  const [standings, setStandings] = useState([]);
  const [aiLogs, setAiLogs] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  
  // Expandable UI States
  const [expandedTeams, setExpandedTeams] = useState({});
  const [expandedTournaments, setExpandedTournaments] = useState({});
  const [editSchedules, setEditSchedules] = useState({});

  useEffect(() => {
    const initializeDashboard = async () => {
      try {
        await fetchActiveTournament();
        await fetchTournaments();
      } catch (error) {
        console.error("Failed to talk to the backend:", error);
      } finally {
        setLoading(false);
      }
    };
    initializeDashboard();
  }, []);
  
  useEffect(() => {
    if (tournament) {
      fetchTeams(tournament.id);
      fetchMatches(tournament.id);
      fetchAiLogs(tournament.id);
      fetchStandings(tournament.id);
      fetchAnalytics(tournament.id);
    }
  }, [tournament]);

  const fetchStandings = async (tournamentId) => {
    try {
      const res = await fetch(`${API_BASE}/tournaments/${tournamentId}/standings`);
      if (res.ok) setStandings(await res.json());
    } catch (err) { console.error(err); }
  };

  const fetchActiveTournament = async () => {
    try {
      const res = await fetch(`${API_BASE}/tournaments/active`);
      if (res.ok) setTournament(await res.json()); 
      else setTournament(null); 
    } catch (err) { setTournament(null); }
  };

  const fetchMatches = async (tournamentId) => {
    try {
      const res = await fetch(`${API_BASE}/tournaments/${tournamentId}/matches`);
      if (res.ok) setMatches(await res.json());
      else setMatches([]);
    } catch (err) { console.error(err); }
  };

  const fetchTeams = async (tournamentId) => {
    try {
      const res = await fetch(`${API_BASE}/register/teams/${tournamentId}`);
      if (res.ok) setTeams(await res.json());
    } catch (err) { console.error(err); }
  };

  const fetchAiLogs = async (tournamentId) => {
    try {
      const res = await fetch(`${API_BASE}/tournaments/${tournamentId}/logs`);
      if (res.ok) setAiLogs(await res.json());
    } catch (err) { console.error(err); }
  };

  const fetchTournaments = async () => {
    try {
      const res = await fetch(`${API_BASE}/tournaments/`);
      if (res.ok) setTournaments(await res.json());
    } catch (err) { console.error(err); }
  };

  const toggleRoster = (teamId) => {
    setExpandedTeams(prev => ({ ...prev, [teamId]: !prev[teamId] }));
  };

  const toggleTournamentDetails = (t) => {
    setExpandedTournaments(prev => ({ ...prev, [t.id]: !prev[t.id] }));
    
    if (!expandedTournaments[t.id]) {
      setEditSchedules(prev => ({
        ...prev,
        [t.id]: {
          start: t.scheduled_start 
            ? new Date(getUtcString(t.scheduled_start))
                .toLocaleString('sv-SE', { timeZone: 'Asia/Kolkata' })
                .replace(' ', 'T')
                .substring(0, 16)
            : "",
          prep: t.prep_time || 30,
          rounds: t.minutes_between_rounds || 120
        }
      }));
    }
  };

  const fetchAnalytics = async (tournamentId) => {
    try {
        const res = await fetch(`${API_BASE}/tournaments/${tournamentId}/analytics`);
        if (res.ok) setAnalytics(await res.json());
    } catch (err) { console.error(err); }
};

  const toggleVerification = async (teamId, currentStatus) => {
    try {
      const res = await fetch(`${API_BASE}/register/teams/${teamId}/verify`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_verified: !currentStatus }),
      });
      if (!res.ok) {
        const errData = await res.json();
        alert(`🚨 Cannot Lock Roster: ${errData.detail}`);
        return;
      }
      if (res.ok) fetchTeams(tournament.id); 
    } catch (err) { alert("Failed to update verification."); }
  };

  const togglePlayerVerification = async (playerId, currentStatus) => {
    try {
      const res = await fetch(`${API_BASE}/register/players/${playerId}/verify`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_verified: !currentStatus }),
      });
      if (res.ok) fetchTeams(tournament.id);
    } catch (err) { alert("Failed to update player verification."); }
  };

  const changeTournamentStatus = async (id, newStatus) => {
    try {
      await fetch(`${API_BASE}/tournaments/${id}/status`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: newStatus })
      });
      fetchTournaments(); 
    } catch (err) { console.error("Failed to change status", err); }
  };

  const activateTournament = async (id) => {
    await fetch(`${API_BASE}/tournaments/${id}/activate`, { method: "PUT" });
    fetchTournaments(); 
    fetchActiveTournament(); 
    setActiveTab("bracket"); 
  };

  const announceTournament = async () => {
    try {
      const res = await fetch(`${API_BASE}/tournaments/${tournament.id}/announce`, { method: "POST" });
      const data = await res.json();
      if (data.success) {
        fetchAiLogs(tournament.id);
        setActiveTab("aifeed"); 
      } else { alert("⚠️ Failed to announce."); }
    } catch (err) { console.error(err); }
  };

  const generateBracket = async () => {
    if (!tournament.scheduled_start) {
        if (!confirm("No start time set. Generate bracket with default times?")) return;
    }
    try {
      const res = await fetch(`${API_BASE}/tournaments/${tournament.id}/generate-bracket`, { method: "POST" });
      if (res.ok) {
        fetchMatches(tournament.id);
        fetchStandings(tournament.id);
        setActiveTab("bracket"); 
        alert("Bracket Generated! Matches scheduled based on your timings.");
      } else {
        const err = await res.json();
        alert("Failed to generate: " + err.detail);
      }
    } catch (error) { alert("Server error."); }
  };

  const resetBracket = async () => {
    if (!confirm("⚠️ WARNING: Delete the entire bracket?")) return;
    if (prompt("🚨 FINAL WARNING: Type 'DELETE' to permanently erase this bracket.") !== "DELETE") return;

    try {
      const res = await fetch(`${API_BASE}/tournaments/${tournament.id}/matches`, { method: "DELETE" });
      if (res.ok) {
        fetchMatches(tournament.id);
        alert("Bracket wiped clean.");
      }
    } catch (error) { alert("Server error."); }
  };

  const createTournament = async () => {
    if (!newTName || !newTGame) return alert("Need name and game!");
    await fetch(`${API_BASE}/tournaments/create`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ 
        name: newTName, 
        game: newTGame, 
        format: newTFormat,
        prize_pool: parseFloat(newTPrize) || 0,
        entry_fee: parseFloat(newTFee) || 0,
        min_players_per_team: parseInt(newTMinPlayers) || 1,
        scheduled_start: scheduledStart ? new Date(scheduledStart).toISOString() : null,
        minutes_between_rounds: parseInt(minutesBetweenRounds) || 120,
        prep_time: parseInt(prepTime) || 30
      }),
    });
    
    setNewTName(""); setNewTGame(""); setNewTPrize(""); setNewTFee(""); setScheduledStart(""); 
    fetchTournaments(); 
    setActiveTab("bracket");
    fetchActiveTournament();
  };

  const reportMatch = async (matchId, winnerId, teamAShowed = true, teamBShowed = true) => {
    try {
      const response = await fetch(`${API_BASE}/tournaments/${tournament.id}/matches/${matchId}/report`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            team_a_showed: teamAShowed,
            team_b_showed: teamBShowed,
            winner_id: winnerId === "DRAW" ? null : winnerId,
          }),
        });

      if (!response.ok) {
        const errorData = await response.json();
        alert(`Backend Error: ${errorData.detail}`);
        return;
      }
      fetchMatches(tournament.id);
      fetchStandings(tournament.id);
    } catch (err) { console.error(err); }
  };

  const pingCaptains = async (matchId) => {
    try {
      const res = await fetch(`${API_BASE}/tournaments/${tournament.id}/matches/${matchId}/ping`, { method: "POST" });
      const data = await res.json();
      if (data.success) { alert("✅ " + data.message); } 
      else { alert("⚠️ " + data.message); }
    } catch (err) { console.error(err); }
  };

  const undoMatch = async (matchId) => {
    if (!window.confirm("Are you sure you want to undo this match? This will remove the winner from the next round.")) return;
    try {
      const res = await fetch(`${API_BASE}/tournaments/${tournament.id}/matches/${matchId}/undo`, { method: "POST" });
      const data = await res.json();
      if (data.success) {
        fetchMatches(tournament.id); 
        fetchStandings(tournament.id);
      } else { alert("⚠️ " + data.detail); }
    } catch (err) { console.error(err); }
  };

  const saveTournamentSchedule = async (tId) => {
    const edits = editSchedules[tId];
    if (!edits || !edits.start) return alert("Please set a valid start date/time.");

    const localDate = new Date(edits.start);
    
    try {
        const response = await fetch(`${API_BASE}/tournaments/${tId}/schedule`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                scheduled_start: localDate.toISOString(), 
                prep_time: parseInt(edits.prep) || 30,
                minutes_between_rounds: parseInt(edits.rounds) || 120
            })
        });

        if (response.ok) {
            alert("✅ Schedule updated! Matches shifted.");
            fetchTournaments();
            if (tournament && tournament.id === tId) fetchMatches(tId);
        } else {
            const err = await response.json();
            alert("❌ Failed to update: " + err.detail);
        }
    } catch (error) { console.error(error); }
  };

  const updateIndividualMatchTime = async (matchId, currentIso) => {
      const rawCurrent = currentIso 
        ? new Date(getUtcString(currentIso))
            .toLocaleString('sv-SE', { timeZone: 'Asia/Kolkata' })
            .replace(' ', 'T')
            .substring(0, 16)
        : "";
      const newVal = prompt("Enter new time for this specific match (YYYY-MM-DDTHH:MM):", rawCurrent);
      if (!newVal) return;

      try {
          const response = await fetch(`${API_BASE}/tournaments/${tournament.id}/matches/${matchId}/time`, {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ scheduled_time: new Date(newVal).toISOString() })
          });
          
          if (response.ok) fetchMatches(tournament.id);
          else alert("Failed to update individual time.");
      } catch (err) { console.error(err); }
  };

  if (loading) return <div className="p-8 text-emerald-400 font-bold text-center mt-20">Loading Command Center...</div>;

  return (
    <div className="max-w-5xl mx-auto p-8 font-sans">
      
      {tournament && (
        <header className="flex justify-between items-center mb-6 border-b border-slate-700 pb-4">
          <h1 className="text-4xl font-bold text-emerald-400">
            🏆 {tournament.name} Dashboard
          </h1>
          <div className="flex gap-3">
            <button onClick={announceTournament} className="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded font-bold transition shadow-lg shadow-indigo-900/50">
              📣 Announce Event
            </button>
            <button onClick={generateBracket} className="bg-emerald-500 hover:bg-emerald-600 text-white px-4 py-2 rounded font-bold transition">
              ⚡ Generate Bracket
            </button>
            <button onClick={resetBracket} className="bg-rose-600 hover:bg-rose-700 text-white px-4 py-2 rounded font-bold transition">
              🗑️ Reset Bracket
            </button>
          </div>
        </header>
      )}

      {/* TABS NAVIGATION */}
      <div className="flex gap-4 mb-8">
        <button onClick={() => setActiveTab("tournaments")} className={`px-4 py-2 rounded font-bold ${activeTab === "tournaments" ? "bg-emerald-600 text-white" : "bg-slate-800 text-slate-400 hover:bg-slate-700"}`}>
          ⚙️ Tournaments
        </button>
        
        {tournament && (
          <>
            <button onClick={() => setActiveTab("teams")} className={`px-4 py-2 rounded font-bold transition ${activeTab === "teams" ? "bg-slate-700 text-white" : "text-slate-400 hover:bg-slate-800"}`}>
              📋 Team Management ({teams.length})
            </button>
            <button onClick={() => setActiveTab("bracket")} className={`px-4 py-2 rounded font-bold transition ${activeTab === "bracket" ? "bg-slate-700 text-white" : "text-slate-400 hover:bg-slate-800"}`}>
              ⚔️ Live Bracket
            </button>
            <button onClick={() => { setActiveTab("aifeed"); fetchAiLogs(tournament.id); }} className={`px-4 py-2 rounded font-bold transition ${activeTab === "aifeed" ? "bg-slate-700 text-white" : "text-slate-400 hover:bg-slate-800"}`}>
              📢 AI Feed
            </button>
            <button onClick={() => setActiveTab("analytics")} className={`px-4 py-2 rounded font-bold transition ${activeTab === "analytics" ? "bg-slate-700 text-white" : "text-slate-400 hover:bg-slate-800"}`}>
              📊 Analytics
            </button> 
            
          </>
        )}
      </div>

      {/* TEAM MANAGEMENT VIEW */}
      {activeTab === "teams" && tournament && (
        <div className="grid gap-4">
          <p className="text-slate-400 mb-2">
            Only verified teams will be pulled into the bracket generator. 
            <strong className="text-rose-400 ml-2">Requires {tournament.min_players_per_team} verified players to lock a roster.</strong>
          </p>
          {teams.length === 0 ? (
            <p className="text-slate-500 italic">No teams registered yet.</p>
          ) : null}

          {teams.map((team) => (
            <div key={team.id} className="bg-slate-800 p-4 rounded-lg border border-slate-700 shadow-md transition-all">
              <div className="flex justify-between items-start">
                <div>
                  <h3 className="text-xl font-bold text-emerald-300">{team.name}</h3>
                  <p className="text-sm text-slate-400 mt-1">Contact: {team.contact}</p>
                  
                  <button onClick={() => toggleRoster(team.id)} className="mt-3 flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-cyan-400 hover:text-cyan-300 transition">
                    {expandedTeams[team.id] ? "▼ Hide Roster" : "▶ View Roster"} ({team.player_count} Members)
                  </button>
                </div>

                <button onClick={() => toggleVerification(team.id, team.is_verified)} className={`px-4 py-2 rounded font-bold border-2 transition ${team.is_verified ? "bg-emerald-900/50 border-emerald-500 text-emerald-400 hover:bg-emerald-900" : "bg-slate-900 border-slate-600 text-slate-400 hover:border-slate-400"}`}>
                  {team.is_verified ? "✅ Verified" : "Pending..."}
                </button>
              </div>

              {expandedTeams[team.id] && (
                <div className="mt-4 pt-4 border-t border-slate-700/50 space-y-2">
                    {team.players.length > 0 && (
                      <div className="flex justify-between items-center bg-emerald-900/20 p-2 rounded border border-emerald-700/30 shadow-inner">
                        <div className="flex items-center gap-3">
                          <span className="text-sm font-bold text-emerald-400">👑 {team.players[0].name} <span className="text-[10px] text-emerald-600 uppercase tracking-widest ml-2">Captain</span></span>
                          <span className="text-xs font-mono text-slate-400 bg-slate-900 px-2 py-1 rounded">{team.players[0].game_id}</span>
                        </div>
                        <button onClick={() => togglePlayerVerification(team.players[0].id, team.players[0].is_verified)} className={`text-[10px] px-2 py-1 rounded font-bold uppercase tracking-widest transition-colors ${team.players[0].is_verified ? "bg-emerald-600 hover:bg-emerald-500 text-white" : "bg-slate-700 hover:bg-slate-600 text-slate-300"}`}>
                          {team.players[0].is_verified ? "✅ Approved" : "Pending"}
                        </button>
                      </div>
                    )}
                    
                    {team.players.slice(1).map((p) => (
                      <div key={p.id} className="flex justify-between items-center bg-slate-900/50 p-2 rounded border border-slate-700/50 ml-4">
                        <div className="flex items-center gap-3">
                          <span className="text-sm text-slate-300">👤 {p.name}</span>
                          <span className="text-xs font-mono text-slate-500 bg-slate-950 px-2 py-1 rounded">{p.game_id}</span>
                        </div>
                        <button onClick={() => togglePlayerVerification(p.id, p.is_verified)} className={`text-[10px] px-2 py-1 rounded font-bold uppercase tracking-widest transition-colors ${p.is_verified ? "bg-emerald-600 hover:bg-emerald-500 text-white" : "bg-slate-700 hover:bg-slate-600 text-slate-300"}`}>
                          {p.is_verified ? "✅ Approved" : "Pending"}
                        </button>
                      </div>
                    ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* BRACKET VIEW */}
      {activeTab === "bracket" && (
        <div className="w-full">
          {!tournament ? (
            <div className="bg-slate-900 border border-slate-700 rounded-xl p-12 text-center shadow-2xl mt-10">
              <div className="text-6xl mb-6">🏆</div>
              <h2 className="text-3xl font-black text-white mb-4">Welcome to AutoTournament AI</h2>
              <button onClick={() => setActiveTab("tournaments")} className="bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-4 px-10 rounded-lg shadow-lg shadow-emerald-900/50 transition-all hover:scale-105 text-lg uppercase tracking-wider">
                🚀 Launch First Tournament
              </button>
            </div>
          ) : (
            <div className="space-y-6">
              <div className="bg-slate-900 p-6 rounded-xl border border-slate-700 shadow-lg flex justify-between items-center">
                <h2 className="text-2xl font-black text-transparent bg-clip-text bg-gradient-to-r from-emerald-400 to-cyan-500 uppercase tracking-wider">
                  {tournament.name}
                </h2>
                <button onClick={generateBracket} className="bg-cyan-600 hover:bg-cyan-500 px-6 py-2 rounded font-bold transition text-white">
                  Generate Bracket
                </button>
              </div>

              {standings.length > 0 && (
                <div className="bg-slate-900 p-6 rounded-xl border border-slate-700 shadow-lg mb-6">
                  <h3 className="text-xl font-bold text-cyan-400 mb-4 flex items-center gap-2">
                    {tournament.format === "round_robin" ? "🏆 Live Leaderboard" : "📊 Team Statistics"}
                  </h3>
                  <table className="w-full text-left text-sm text-slate-300">
                    <thead className="bg-slate-800 text-slate-400 uppercase font-bold text-xs">
                      <tr><th className="px-4 py-3">Rank</th><th className="px-4 py-3">Team</th><th className="px-4 py-3 text-center">Played</th><th className="px-4 py-3 text-center text-emerald-400">W</th><th className="px-4 py-3 text-center text-rose-400">L</th><th className="px-4 py-3 text-center text-cyan-400">Pts</th></tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/50">
                      {standings.map((team, index) => (
                        <tr key={team.id} className={`${index === 0 && tournament.format === "round_robin" ? "bg-emerald-900/10" : "hover:bg-slate-800/50"} transition-colors`}>
                          <td className="px-4 py-3 font-bold text-slate-500">#{index + 1}</td>
                          <td className={`px-4 py-3 font-bold ${index === 0 && tournament.format === "round_robin" ? "text-emerald-400" : "text-white"}`}>{index === 0 && tournament.format === "round_robin" && "🏆 "} {team.name}</td>
                          <td className="px-4 py-3 text-center">{team.played}</td>
                          <td className="px-4 py-3 text-center font-bold text-emerald-400/80">{team.wins}</td>
                          <td className="px-4 py-3 text-center text-rose-400/80">{team.losses}</td>
                          <td className="px-4 py-3 text-center font-black text-cyan-400">{team.points}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

                <div className="grid gap-4">
                  {matches.length === 0 ? (
                     <p className="text-slate-500 text-center italic py-10">Bracket has not been generated yet. Click the button above!</p>
                  ) : (
                    (() => {
                      const pendingMatches = matches.filter(m => m.status === "pending" || m.status === "disputed");
                      const activeRound = pendingMatches.length > 0 ? Math.min(...pendingMatches.map(m => m.round_number)) : 999;

                      return matches.map((match) => {
                        const teamA = match.team_a_id 
                          ? (teams.find(t => t.id === match.team_a_id)?.name || match.team_a_id.substring(0, 8)): "TBD";
                        const teamB = match.team_b_id 
                          ? (teams.find(t => t.id === match.team_b_id)?.name || match.team_b_id.substring(0, 8)): "TBD"
                        const isCurrentRound = match.round_number === activeRound;

                        let cardColor = "bg-slate-900 border-slate-800 opacity-50"; 
                        if (match.status === "completed" || match.status === "walkover") { cardColor = "bg-emerald-900/30 border-emerald-500 opacity-100"; }
                        else if (match.status === "disputed") { cardColor = "bg-rose-950/30 border-rose-500 animate-pulse opacity-100"; }
                        else if (match.status === "pending") {
                          if (match.team_a_id && match.team_b_id && match.team_a_id.length > 5 && match.team_b_id.length > 5) {
                             cardColor = isCurrentRound ? "bg-orange-950/30 border-orange-500 shadow-orange-900/20 shadow-lg opacity-100" : "bg-slate-800 border-slate-700 opacity-75"; 
                          } else { cardColor = "bg-slate-800 border-slate-700 opacity-75"; }
                        }

                        return (
                          <div key={match.id} className={`p-4 rounded-lg border transition-all ${cardColor}`}>
                            <div className="flex justify-between items-center mb-2">
                              
                              <span className="text-xs text-slate-300 font-bold uppercase tracking-wider flex items-center">
                                Round {match.round_number} 
                                {match.scheduled_time && (
                                  <span className="ml-2 bg-slate-950 px-2 py-1 rounded text-[10px] text-cyan-400 border border-slate-700 flex items-center">
                                    🕒 {formatTimeOnly(match.scheduled_time)}
                                    <button onClick={() => updateIndividualMatchTime(match.id, match.scheduled_time)} className="ml-2 text-slate-500 hover:text-white transition">✏️</button>
                                  </span>
                                )}
                              </span>
                              
                              <div className="flex gap-2 items-center">
                                {match.status === "pending" && match.team_a_id && match.team_b_id && isCurrentRound && (
                                  <button onClick={() => pingCaptains(match.id)} className="bg-indigo-600 hover:bg-indigo-500 text-white text-[10px] px-2 py-1 rounded uppercase font-bold tracking-widest">🔔 Ping</button>
                                )}
                                <span className={`text-xs font-bold uppercase ${match.status === "disputed" ? "text-rose-400" : "text-slate-400"}`}>{match.status}</span>
                              </div>
                            </div>

                            <div className="text-xl font-bold mb-4 text-white">
                              {teamA} <span className="text-slate-500 text-sm mx-2">VS</span> {teamB}
                            </div>

                            {match.status === "pending" && isCurrentRound && (
                              <div className="flex gap-2 border-t border-slate-700 pt-3">
                                {match.team_a_id && match.team_b_id && (
                                  <>
                                    <button onClick={() => reportMatch(match.id, match.team_a_id, true, true)} className="flex-1 bg-emerald-600 hover:bg-emerald-500 py-2 rounded text-sm font-bold transition text-white">🏆 {teamA}</button>
                                    <button onClick={() => reportMatch(match.id, match.team_b_id, true, true)} className="flex-1 bg-emerald-600 hover:bg-emerald-500 py-2 rounded text-sm font-bold transition text-white">🏆 {teamB}</button>
                                    <button onClick={() => reportMatch(match.id, "DRAW", false, false)} className="flex-1 bg-slate-700 hover:bg-slate-600 py-2 rounded text-sm font-bold border border-slate-600 transition text-white">Double DQ</button>
                                  </>
                                )}
                                {match.team_a_id && !match.team_b_id && (
                                  <button onClick={() => reportMatch(match.id, match.team_a_id, true, false)} className="w-full bg-blue-600 hover:bg-blue-500 py-2 rounded text-sm font-bold transition text-white">🚶 {teamA} Walkover</button>
                                )}
                                {!match.team_a_id && match.team_b_id && (
                                  <button onClick={() => reportMatch(match.id, match.team_b_id, false, true)} className="w-full bg-blue-600 hover:bg-blue-500 py-2 rounded text-sm font-bold transition text-white">🚶 {teamB} Walkover</button>
                                )}
                              </div>
                            )}

                            {match.status === "disputed" && (
                              <div className="border-t border-rose-700 pt-3 mt-2">
                                <p className="text-rose-400 font-bold text-xs mb-2 uppercase tracking-wide">🚨 Admin Override</p>
                                <div className="flex gap-2">
                                  <button onClick={() => reportMatch(match.id, match.team_a_id, true, true)} className="flex-1 bg-rose-600 hover:bg-rose-500 py-2 rounded text-sm font-bold transition text-white">Force {teamA} Win</button>
                                  <button onClick={() => reportMatch(match.id, match.team_b_id, true, true)} className="flex-1 bg-rose-600 hover:bg-rose-500 py-2 rounded text-sm font-bold transition text-white">Force {teamB} Win</button>
                                </div>
                              </div>
                            )}

                            {(match.status === "completed" || match.status === "walkover" || match.status === "double_forfeit") && (
                              <div className="flex justify-between items-center border-t border-slate-700 pt-3 mt-2">
                                <div className="text-sm text-emerald-400 font-bold">
                                    Winner: {match.winner_id 
                                      ? (teams.find(t => t.id === match.winner_id)?.name || "Unknown")
                                      : "None"}
                                  </div>
                                <button onClick={() => undoMatch(match.id)} className="bg-slate-700 hover:bg-rose-600 text-slate-300 hover:text-white text-[10px] px-2 py-1 rounded uppercase font-bold tracking-widest transition-colors">⏪ Undo</button>
                              </div>
                            )}
                          </div>
                        );
                      });
                    })()
                  )}
                </div>
            </div>
          )}
        </div>
      )}

      {/* THE AI FEED */}
      {activeTab === "aifeed" && tournament && (
        <div className="bg-slate-950 border border-slate-800 rounded-xl p-6 shadow-2xl font-mono">
          <div className="flex justify-between items-center mb-6 border-b border-slate-800 pb-4">
            <h2 className="text-xl font-bold text-cyan-400 flex items-center gap-2"><span className="animate-pulse">🟢</span> Agent Memory Stream</h2>
            <button onClick={() => fetchAiLogs(tournament.id)} className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-1 rounded">🔄 Refresh Log</button>
          </div>
          <div className="space-y-4 max-h-[600px] overflow-y-auto pr-2 custom-scrollbar">
            {aiLogs.length === 0 ? <p className="text-slate-600 text-center italic py-10">System is quiet. No actions logged yet.</p> : (
              aiLogs.map((log) => {
                let icon = "⚙️"; let color = "text-slate-400";
                if (log.platform === "discord") { icon = "👾"; color = "text-indigo-400"; }
                if (log.platform === "whatsapp") { icon = "💬"; color = "text-emerald-400"; }
                if (log.platform === "instagram") { icon = "📸"; color = "text-pink-400"; }
                return (
                  <div key={log.id} className="bg-slate-900 border-l-2 border-slate-700 p-4 rounded-r shadow-sm">
                    <div className="flex justify-between items-start mb-2">
                      <span className={`text-xs font-bold uppercase tracking-widest flex items-center gap-2 ${color}`}>{icon} {log.platform} Broadcast</span>
                      <span className="text-xs text-slate-500">{formatFullDate(log.timestamp)}</span>
                    </div>
                    <div className="text-sm text-slate-300 whitespace-pre-wrap leading-relaxed">{log.content}</div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}

      {/* TOURNAMENTS DB */}
      {activeTab === "tournaments" && (
        <div className="space-y-8">
          
          <div className="bg-slate-900 border border-slate-700 p-6 rounded-xl shadow-lg">
            <h2 className="text-xl font-bold text-white mb-4">🚀 Launch New Tournament</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
              <input type="text" placeholder="Tournament Name" value={newTName} onChange={(e) => setNewTName(e.target.value)} className="bg-slate-800 border border-slate-600 rounded p-2 text-white" />
              <input type="text" placeholder="Game" value={newTGame} onChange={(e) => setNewTGame(e.target.value)} className="bg-slate-800 border border-slate-600 rounded p-2 text-white" />
              <select value={newTFormat} onChange={(e) => setNewTFormat(e.target.value)} className="bg-slate-800 border border-slate-600 rounded p-2 text-white">
                <option value="single_elimination">Single Elimination</option>
                <option value="double_elimination">Double Elimination</option>
                <option value="round_robin">Round Robin</option>
              </select>
            </div>

            <div className="flex gap-4 mb-4">
                <div className="flex-1">
                    <label className="block text-xs font-bold text-slate-400 uppercase tracking-wide mb-1">Start Time</label>
                    <input type="datetime-local" value={scheduledStart} onChange={(e) => setScheduledStart(e.target.value)} className="w-full bg-slate-800 border border-slate-600 rounded p-2 text-white focus:border-cyan-500 outline-none" />
                </div>
                <div className="flex-1">
                    <label className="block text-xs font-bold text-slate-400 uppercase tracking-wide mb-1">Bracket Prep (Mins)</label>
                    <input type="number" value={prepTime} onChange={(e) => setPrepTime(e.target.value)} className="w-full bg-slate-800 border border-slate-600 rounded p-2 text-white focus:border-cyan-500 outline-none" min="0" />
                </div>
                <div className="flex-1">
                    <label className="block text-xs font-bold text-slate-400 uppercase tracking-wide mb-1">Round Length (Mins)</label>
                    <input type="number" value={minutesBetweenRounds} onChange={(e) => setMinutesBetweenRounds(e.target.value)} className="w-full bg-slate-800 border border-slate-600 rounded p-2 text-white focus:border-cyan-500 outline-none" min="10" />
                </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-center border-t border-slate-700 pt-4">
              <input type="number" placeholder="Prize Pool (Rs)" value={newTPrize} onChange={(e) => setNewTPrize(e.target.value)} className="bg-slate-800 border border-slate-600 rounded p-2 text-white" />
              <input type="number" placeholder="Entry Fee (Rs)" value={newTFee} onChange={(e) => setNewTFee(e.target.value)} className="bg-slate-800 border border-slate-600 rounded p-2 text-white" />
              <div className="flex items-center gap-2">
                <span className="text-sm text-slate-400">Min Players:</span>
                <input type="number" min="1" value={newTMinPlayers} onChange={(e) => setNewTMinPlayers(e.target.value)} className="w-16 bg-slate-800 border border-slate-600 rounded p-2 text-white text-center" />
              </div>
              <button onClick={createTournament} className="bg-cyan-600 hover:bg-cyan-500 px-6 py-2 rounded font-bold text-white transition">Create Event</button>
            </div>
          </div>

          <div className="bg-slate-900 border border-slate-700 p-6 rounded-xl shadow-lg">
            <h2 className="text-xl font-bold text-white mb-4">🗄️ Tournament Database</h2>
            <div className="space-y-3">
              {tournaments.map(t => (
                <div key={t.id} className={`p-4 rounded-lg border transition-all ${t.is_active ? 'bg-emerald-900/20 border-emerald-500/50' : 'bg-slate-800 border-slate-700 hover:border-slate-500'}`}>
                  
                  {/* TOP ROW */}
                  <div className="flex justify-between items-start cursor-pointer" onClick={() => toggleTournamentDetails(t)}>
                    <div>
                      <div className="text-lg font-bold text-white flex items-center gap-2">
                        {t.name} {t.is_active && <span className="bg-emerald-500 text-slate-950 text-[10px] px-2 py-0.5 rounded-full uppercase tracking-wider font-black shadow-[0_0_10px_rgba(16,185,129,0.5)]">Active</span>}
                      </div>
                      <div className="text-sm text-slate-400 mt-2 flex flex-wrap items-center gap-4">
                        <span className="flex items-center gap-1 text-cyan-300">🎮 {t.game}</span>
                        <span className="flex items-center gap-1">📅 {formatFullDate(t.scheduled_start)}</span>
                      </div>
                    </div>
                    
                    <div className="flex flex-col items-end gap-2">
                      <select value={t.status} onClick={(e) => e.stopPropagation()} onChange={(e) => changeTournamentStatus(t.id, e.target.value)} className="bg-slate-900 border border-slate-600 text-xs text-white rounded px-2 py-1 outline-none focus:border-cyan-500 transition cursor-pointer">
                        <option value="draft">Draft</option>
                        <option value="registration_open">Registration Open</option>
                        <option value="in_progress">In Progress</option>
                        <option value="live">Live</option>
                        <option value="completed">Completed</option>
                      </select>
                      <span className="text-xs font-bold text-cyan-400 mt-1 hover:text-cyan-300 transition">{expandedTournaments[t.id] ? "▼ Hide Details" : "▶ Show Details"}</span>
                    </div>
                  </div>

                  {/* EXPANDED PANEL */}
                  {expandedTournaments[t.id] && (
                    <div className="mt-4 pt-4 border-t border-slate-700/50 animate-in fade-in slide-in-from-top-2 duration-200">
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                        <div><p className="text-[10px] uppercase tracking-wider text-slate-500 font-bold mb-1">Prize Pool</p><p className="text-sm text-emerald-400 font-mono font-bold">₹{t.prize_pool}</p></div>
                        <div><p className="text-[10px] uppercase tracking-wider text-slate-500 font-bold mb-1">Entry Fee</p><p className="text-sm text-white font-mono font-bold">₹{t.entry_fee}</p></div>
                        <div><p className="text-[10px] uppercase tracking-wider text-slate-500 font-bold mb-1">Team Limits</p><p className="text-sm text-white font-mono font-bold">{t.max_teams} Max <span className="text-slate-500 font-sans text-xs">({t.min_players_per_team}v{t.min_players_per_team})</span></p></div>
                        {!t.is_active && (
                          <button onClick={(e) => { e.stopPropagation(); activateTournament(t.id); }} className="bg-slate-700 hover:bg-slate-600 text-white px-2 py-1 rounded text-[10px] uppercase tracking-widest font-bold h-full">📡 Set Active</button>
                        )}
                      </div>
                      <AdminSyncControls 
                          tournamentId={t.id} 
                          apiBaseUrl={API_BASE} 
                      />
                      {/* INLINE SCHEDULE EDITOR */}
                      <div className="bg-slate-950/50 p-3 rounded border border-slate-800" onClick={(e) => e.stopPropagation()}>
                        <p className="text-[10px] uppercase tracking-wider text-slate-400 font-bold mb-2">Update Timings</p>
                        <div className="flex gap-2 items-end">
                           <div className="flex-1">
                             <label className="text-[10px] text-slate-500">Start Time</label>
                             <input type="datetime-local" value={editSchedules[t.id]?.start || ""} onChange={(e) => setEditSchedules({...editSchedules, [t.id]: {...editSchedules[t.id], start: e.target.value}})} className="w-full bg-slate-900 border border-slate-700 rounded p-1.5 text-xs text-white outline-none focus:border-cyan-500" />
                           </div>
                           <div className="w-16">
                             <label className="text-[10px] text-slate-500">Prep(m)</label>
                             <input type="number" value={editSchedules[t.id]?.prep || ""} onChange={(e) => setEditSchedules({...editSchedules, [t.id]: {...editSchedules[t.id], prep: e.target.value}})} className="w-full bg-slate-900 border border-slate-700 rounded p-1.5 text-xs text-white text-center outline-none focus:border-cyan-500" />
                           </div>
                           <div className="w-16">
                             <label className="text-[10px] text-slate-500">Round(m)</label>
                             <input type="number" value={editSchedules[t.id]?.rounds || ""} onChange={(e) => setEditSchedules({...editSchedules, [t.id]: {...editSchedules[t.id], rounds: e.target.value}})} className="w-full bg-slate-900 border border-slate-700 rounded p-1.5 text-xs text-white text-center outline-none focus:border-cyan-500" />
                           </div>
                           <button onClick={() => saveTournamentSchedule(t.id)} className="bg-cyan-600 hover:bg-cyan-500 text-white px-3 py-1.5 rounded text-xs font-bold transition h-[32px]">Save</button>
                        </div>
                      </div>

                    </div>
                  )}
                  
                </div>
              ))}
            </div>
          </div>
          
        </div>
      )}
        {/* ANALYTICS VIEW */}
        {activeTab === "analytics" && tournament && analytics && (
        <div className="space-y-6">
            <div className="grid grid-cols-3 gap-4">
                <div className="bg-slate-900 border border-slate-700 p-6 rounded-xl text-center">
                    <h3 className="text-slate-400 text-xs font-bold uppercase tracking-wider mb-2">Completion</h3>
                    <p className="text-4xl font-black text-emerald-400">{analytics.stats.progress}%</p>
                    <p className="text-xs text-slate-500 mt-2">{analytics.stats.matches_played} Matches Played</p>
                </div>
                <div className="bg-slate-900 border border-slate-700 p-6 rounded-xl text-center">
                    <h3 className="text-slate-400 text-xs font-bold uppercase tracking-wider mb-2">Disputes</h3>
                    <p className="text-4xl font-black text-rose-400">{analytics.stats.disputes}</p>
                </div>
                <div className="bg-slate-900 border border-slate-700 p-6 rounded-xl text-center">
                    <h3 className="text-slate-400 text-xs font-bold uppercase tracking-wider mb-2">Intensity Level</h3>
                    <p className="text-4xl font-black text-cyan-400">{analytics.insights.intensity}</p>
                </div>
            </div>

            <div className="bg-slate-900 border border-slate-700 p-6 rounded-xl">
                <h3 className="text-xl font-bold text-white mb-4">🤖 AI Tournament Report</h3>
                <p className="text-slate-300 mb-4">{analytics.insights.summary}</p>
                <div className="bg-slate-950 p-4 rounded border border-slate-800 inline-block">
                    <span className="text-slate-500 text-xs font-bold uppercase tracking-wider">Current MVP Prediction:</span>
                    <span className="ml-2 font-bold text-emerald-400">{analytics.insights.mvp}</span>
                </div>
            </div>
        </div>
        )}
    </div>
  );
}

export default App;