import React, { useState } from 'react';

const AdminSyncControls = ({ tournamentId, apiBaseUrl }) => {
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');

  const triggerSync = async (syncType) => {
    setLoading(true);
    setMessage(`Requesting ${syncType} sync...`);

    try {
      const endpoint = syncType === 'roles' ? 'sync-roles' : 'sync-channels';
      const response = await fetch(`${apiBaseUrl}/tournaments/${tournamentId}/admin/${endpoint}`, {
        method: 'POST',
      });

      if (response.ok) {
        setMessage(`✅ Success: Sync command sent.`);
      } else {
        setMessage(`❌ Error: Failed to sync.`);
      }
    } catch (error) {
      setMessage(`❌ Error: ${error.message}`);
    } finally {
      setLoading(false);
      setTimeout(() => setMessage(''), 3000); // Clear message after 3 seconds
    }
  };

  return (
    <div className="bg-slate-950 p-4 rounded border border-slate-700 mt-4">
      <h3 className="text-sm font-bold text-slate-300 uppercase tracking-wider mb-3">Admin Sync</h3>
      <div className="flex gap-2">
        <button 
          onClick={() => triggerSync('roles')} 
          disabled={loading}
          className="bg-indigo-700 hover:bg-indigo-600 text-white text-xs font-bold px-3 py-2 rounded transition disabled:opacity-50"
        >
          Sync Roles
        </button>
        <button 
          onClick={() => triggerSync('channels')} 
          disabled={loading}
          className="bg-cyan-700 hover:bg-cyan-600 text-white text-xs font-bold px-3 py-2 rounded transition disabled:opacity-50"
        >
          Sync Channels
        </button>
      </div>
      {message && <p className="mt-2 text-[10px] text-emerald-400 font-bold">{message}</p>}
    </div>
  );
};

export default AdminSyncControls;