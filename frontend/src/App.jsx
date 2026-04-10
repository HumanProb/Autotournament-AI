import { useState, useEffect } from 'react';

const API_BASE = "http://127.0.0.1:8000";

function App() {
  const [tournament, setTournament] = useState(null);
  const [matches, setMatches] = useState([]);
  const [teams, setTeams] = useState([]); // --- NEW: Store the teams ---
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("teams"); // --- NEW: Tab State ---

  useEffect(() => {
    fetchActiveTournament();
  }, []);

  const fetchActiveTournament = async () => {
    try {
      const res = await fetch(`${API_BASE}/tournaments/active`);
      if (!res.ok) throw new Error("No active tournament");
      const data = await res.json();
      setTournament(data);
      fetchMatches(data.id);
      fetchTeams(data.id); // Fetch the teams on load!
    } catch (err) {
      console.error(err);
      setLoading(false);
    }
  };

  const fetchMatches = async (tournamentId) => {
    try {
      const res = await fetch(`${API_BASE}/tournaments/${tournamentId}/matches`);
      if (res.ok) setMatches(await res.json());
      else setMatches([]);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  // --- NEW: Fetch Teams Function ---
  const fetchTeams = async (tournamentId) => {
    try {
      const res = await fetch(`${API_BASE}/register/teams/${tournamentId}`);
      if (res.ok) setTeams(await res.json());
    } catch (err) {
      console.error(err);
    }
  };

  // --- NEW: Toggle Verification Function ---
  const toggleVerification = async (teamId, currentStatus) => {
    try {
      const res = await fetch(`${API_BASE}/register/teams/${teamId}/verify`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_verified: !currentStatus })
      });
      if (res.ok) fetchTeams(tournament.id); // Refresh the list
    } catch (err) {
      alert("Failed to update verification.");
    }
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
    } catch (err) {
      console.error(err);
    }
  };

  const generateBracket = async () => {
    try {
      const res = await fetch(`${API_BASE}/tournaments/${tournament.id}/generate-bracket`, { method: 'POST' });
      if (res.ok) {
        fetchMatches(tournament.id);
        setActiveTab("bracket"); // Instantly switch to the bracket tab!
        alert("Bracket Generated with Verified Teams! AI Announcement sent to Discord.");
      } else {
        const err = await res.json();
        alert("Failed to generate: " + err.detail);
      }
    } catch (error) {
      alert("Server error.");
    }
  };

  const resetBracket = async () => {
    const first = confirm("⚠️ WARNING: Delete the entire bracket?");
    if (!first) return;
    const second = prompt("🚨 FINAL WARNING: Type 'DELETE' to permanently erase this bracket.");
    if (second !== "DELETE") return;
    
    try {
      const res = await fetch(`${API_BASE}/tournaments/${tournament.id}/matches`, { method: 'DELETE' });
      if (res.ok) {
        fetchMatches(tournament.id);
        alert("Bracket wiped clean.");
      }
    } catch (error) {
      alert("Server error.");
    }
  };

  if (loading) return <div className="p-8 text-emerald-400">Loading Command Center...</div>;
  if (!tournament) return <div className="p-8 text-rose-400">No Active Tournament Found in Database.</div>;

  return (
    <div className="max-w-5xl mx-auto p-8 font-sans">
      
      {/* HEADER */}
      <header className="flex justify-between items-center mb-6 border-b border-slate-700 pb-4">
        <h1 className="text-3xl font-bold text-emerald-400">🏆 {tournament.name} Dashboard</h1>
        <div className="flex gap-3">
          <button onClick={generateBracket} className="bg-emerald-500 hover:bg-emerald-600 text-white px-4 py-2 rounded font-bold transition">
            ⚡ Generate Bracket
          </button>
          <button onClick={resetBracket} className="bg-rose-600 hover:bg-rose-700 text-white px-4 py-2 rounded font-bold transition">
            🗑️ Reset Bracket
          </button>
        </div>
      </header>

      {/* --- NEW: TABS NAVIGATION --- */}
      <div className="flex gap-4 mb-8">
        <button 
          onClick={() => setActiveTab("teams")}
          className={`px-4 py-2 rounded font-bold transition ${activeTab === "teams" ? "bg-slate-700 text-white" : "text-slate-400 hover:bg-slate-800"}`}
        >
          📋 Team Management ({teams.length})
        </button>
        <button 
          onClick={() => setActiveTab("bracket")}
          className={`px-4 py-2 rounded font-bold transition ${activeTab === "bracket" ? "bg-slate-700 text-white" : "text-slate-400 hover:bg-slate-800"}`}
        >
          ⚔️ Live Bracket
        </button>
      </div>

      {/* --- NEW: TEAM MANAGEMENT VIEW --- */}
      {activeTab === "teams" && (
        <div className="grid gap-4">
          <p className="text-slate-400 mb-2">Only verified teams will be pulled into the bracket generator (Max {tournament.max_teams}).</p>
          {teams.length === 0 ? <p className="text-slate-500 italic">No teams registered yet.</p> : null}
          
          {teams.map(team => (
            <div key={team.id} className="bg-slate-800 p-4 rounded-lg border border-slate-700 flex justify-between items-center shadow-md">
              <div>
                <h3 className="text-xl font-bold text-emerald-300">{team.name}</h3>
                <p className="text-sm text-slate-400 mt-1">Contact: {team.contact}</p>
                <div className="mt-2 text-xs text-slate-500">
                  <span className="font-bold text-slate-300">Roster ({team.player_count}):</span>{' '}
                  {team.players.map(p => `${p.name} (${p.game_id})`).join(", ")}
                </div>
              </div>
              
              <button 
                onClick={() => toggleVerification(team.id, team.is_verified)}
                className={`px-4 py-2 rounded font-bold border-2 transition ${
                  team.is_verified 
                  ? "bg-emerald-900/50 border-emerald-500 text-emerald-400 hover:bg-emerald-900" 
                  : "bg-slate-900 border-slate-600 text-slate-400 hover:border-slate-400"
                }`}
              >
                {team.is_verified ? "✅ Verified" : "Pending..."}
              </button>
            </div>
          ))}
        </div>
      )}

      {/* BRACKET VIEW */}
      {activeTab === "bracket" && (
        <div className="grid gap-4">
          {matches.length === 0 ? (
            <p className="text-slate-400 italic">No matches exist yet. Click Generate Bracket!</p>
          ) : (
            matches.map((match) => {
              const teamA = match.team_a_id ? match.team_a_id.substring(0, 8) : "TBD";
              const teamB = match.team_b_id ? match.team_b_id.substring(0, 8) : "TBD";
              
              return (
                <div key={match.id} className={`p-4 rounded-lg border shadow-md transition-all ${match.status === 'disputed' ? 'bg-rose-950/30 border-rose-500' : 'bg-slate-800 border-slate-700'}`}>
                  <div className="flex justify-between mb-2">
                    <span className="text-xs text-emerald-500 font-bold uppercase tracking-wider">Round {match.round_number}</span>
                    
                    {/* --- UPDATED: Make the status glow red if disputed! --- */}
                    <span className={`text-xs font-bold uppercase ${match.status === 'disputed' ? 'text-rose-400 animate-pulse' : 'text-slate-400'}`}>
                      {match.status}
                    </span>
                  </div>
                  
                  <div className="text-xl font-bold mb-4 text-white">
                    {teamA} <span className="text-slate-500 text-sm mx-2">VS</span> {teamB}
                  </div>

                  {/* STANDARD PENDING BUTTONS */}
                  {match.status === "pending" && (
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

                  {/* --- NEW: THE ADMIN OVERRIDE PANEL --- */}
                  {match.status === "disputed" && (
                    <div className="border-t border-rose-700 pt-3 mt-2">
                      <p className="text-rose-400 font-bold text-xs mb-2 uppercase tracking-wide">🚨 Admin Override Required</p>
                      <div className="flex gap-2">
                        <button onClick={() => reportMatch(match.id, match.team_a_id, true, true)} className="flex-1 bg-rose-600 hover:bg-rose-500 py-2 rounded text-sm font-bold transition text-white">Force {teamA} Win</button>
                        <button onClick={() => reportMatch(match.id, match.team_b_id, true, true)} className="flex-1 bg-rose-600 hover:bg-rose-500 py-2 rounded text-sm font-bold transition text-white">Force {teamB} Win</button>
                      </div>
                    </div>
                  )}

                  {(match.status === "completed" || match.status === "walkover") && (
                    <div className="text-sm text-emerald-400 font-bold border-t border-slate-700 pt-3">
                      Winner: {match.winner_id ? match.winner_id.substring(0,8) : "Unknown"}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}

export default App;