import { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';

const API_BASE = "http://127.0.0.1:8000";

export default function PublicBracket() {
  const { tournamentId } = useParams();
  const [tournament, setTournament] = useState(null);
  const [matches, setMatches] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchTournamentAndMatches = async () => {
      try {
        // Fetch the specific tournament
        const res = await fetch(`${API_BASE}/tournaments/${tournamentId}`);
        if (res.ok) setTournament(await res.json());

        // Fetch its matches
        const matchRes = await fetch(`${API_BASE}/tournaments/${tournamentId}/matches`);
        if (matchRes.ok) setMatches(await matchRes.json());
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    };
    
    fetchTournamentAndMatches();
    
    // Optional: Auto-refresh the bracket every 10 seconds so players see live updates!
    const interval = setInterval(fetchTournamentAndMatches, 10000);
    return () => clearInterval(interval);
  }, [tournamentId]);

  if (loading) return <div className="p-8 text-emerald-400 font-bold text-center mt-20">Loading Live Bracket...</div>;
  if (!tournament) return <div className="p-8 text-rose-400 font-bold text-center mt-20">Tournament not found.</div>;

  return (
    <div className="min-h-screen bg-slate-950 p-4 md:p-8 font-sans">
      <div className="max-w-4xl mx-auto">
        
        {/* PUBLIC HEADER */}
        <header className="text-center mb-10 border-b border-slate-800 pb-8">
          <h1 className="text-4xl md:text-5xl font-black text-transparent bg-clip-text bg-gradient-to-r from-emerald-400 to-cyan-500 uppercase tracking-widest">
            {tournament.name}
          </h1>
          <p className="text-slate-500 mt-3 font-bold tracking-widest text-sm">LIVE TOURNAMENT BRACKET</p>
        </header>

        {/* BRACKET VIEW */}
        <div className="grid gap-4">
          {matches.length === 0 ? (
            <p className="text-slate-500 text-center italic">Bracket has not been generated yet. Stay tuned!</p>
          ) : (
            matches.map((match) => {
              const teamA = match.team_a_id ? match.team_a_id.substring(0, 8) : "TBD";
              const teamB = match.team_b_id ? match.team_b_id.substring(0, 8) : "TBD";
              
              return (
                <div key={match.id} className="bg-slate-900 p-5 rounded-xl border border-slate-800 shadow-xl">
                  <div className="flex justify-between mb-4 border-b border-slate-800 pb-3">
                    <span className="text-xs text-cyan-500 font-black uppercase tracking-widest">Round {match.round_number}</span>
                    <span className={`text-xs font-bold uppercase tracking-wider ${match.status === 'live' || match.status === 'disputed' ? 'text-rose-400 animate-pulse' : 'text-slate-500'}`}>
                      {match.status}
                    </span>
                  </div>
                  
                  <div className="text-2xl md:text-3xl font-black text-white text-center py-4 tracking-wide">
                    {teamA} <span className="text-slate-600 text-lg mx-4">VS</span> {teamB}
                  </div>

                  {(match.status === "completed" || match.status === "walkover") && (
                    <div className="mt-4 text-center text-emerald-400 font-bold bg-emerald-950/30 py-3 rounded-lg border border-emerald-900/50">
                      🏆 WINNER: {match.winner_id ? match.winner_id.substring(0,8) : "Unknown"}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}