import React, { useState, useEffect } from 'react';

interface Agent {
  id: number;
  name: str;
  description: str;
  system_prompt: str;
  escalation_marker: str;
  fallback_responses: str;
  is_active: number;
}

const AgentEditor: React.FC = () => {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<number | null>(null);
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAgents();
  }, []);

  const fetchAgents = async () => {
    setLoading(true);
    try {
      const token = localStorage.getItem('hermes_token') || 'hermes_dashboard_2024';
      const res = await fetch('http://localhost:8080/api/agents', {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (!res.ok) throw new Error('Failed to fetch agents');
      const data = await res.json();
      setAgents(data);
      
      const active = data.find((a: Agent) => a.is_active === 1);
      if (active) {
        setSelectedAgentId(active.id);
        setEditingAgent({ ...active });
      } else if (data.length > 0) {
        setSelectedAgentId(data[0].id);
        setEditingAgent({ ...data[0] });
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleAgentSelect = (id: number) => {
    const agent = agents.find(a => a.id === id);
    if (agent) {
      setSelectedAgentId(id);
      setEditingAgent({ ...agent });
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    if (!editingAgent) return;
    const { name, value } = e.target;
    setEditingAgent({ ...editingAgent, [name]: value });
  };

  const handleSave = async () => {
    if (!editingAgent) return;
    setSaving(true);
    try {
      const token = localStorage.getItem('hermes_token') || 'hermes_dashboard_2024';
      const res = await fetch(`http://localhost:8080/api/agents/${editingAgent.id}`, {
        method: 'PUT',
        headers: { 
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(editingAgent)
      });
      if (!res.ok) throw new Error('Failed to save agent');
      await fetchAgents();
      alert('Agente guardado con éxito');
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleActivate = async () => {
    if (!selectedAgentId) return;
    setSaving(true);
    try {
      const token = localStorage.getItem('hermes_token') || 'hermes_dashboard_2024';
      const res = await fetch(`http://localhost:8080/api/agents/${selectedAgentId}/activate`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (!res.ok) throw new Error('Failed to activate agent');
      await fetchAgents();
      alert('Agente activado con éxito');
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleNewAgent = async () => {
    const name = prompt('Nombre del nuevo agente:');
    if (!name) return;

    setSaving(true);
    try {
      const token = localStorage.getItem('hermes_token') || 'hermes_dashboard_2024';
      const res = await fetch('http://localhost:8080/api/agents', {
        method: 'POST',
        headers: { 
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          name,
          description: 'Nuevo agente',
          system_prompt: 'Eres un asistente servicial.',
          fallback_responses: '{}'
        })
      });
      if (!res.ok) throw new Error('Failed to create agent');
      await fetchAgents();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="p-8 text-center text-gray-400">Cargando agentes...</div>;

  return (
    <div className="flex flex-col h-full w-full bg-gray-900 text-gray-100 overflow-hidden">
      <div className="p-6 border-b border-gray-800 flex justify-between items-center bg-gray-900/50 backdrop-blur-md sticky top-0 z-10">
        <div>
          <h2 className="text-2xl font-bold bg-gradient-to-r from-emerald-400 to-cyan-400 bg-clip-text text-transparent">Configuración de Agente AI</h2>
          <p className="text-gray-400 text-sm">Gestiona los prompts y comportamientos del bot</p>
        </div>
        <div className="flex gap-3">
          <button 
            onClick={handleNewAgent}
            className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-200 rounded-lg transition-all border border-gray-700 flex items-center gap-2"
          >
            <span>+</span> Nuevo Agente
          </button>
          <button 
            onClick={handleSave}
            disabled={saving || !editingAgent}
            className="px-6 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-lg font-medium transition-all shadow-lg shadow-emerald-900/20"
          >
            {saving ? 'Guardando...' : 'Guardar Cambios'}
          </button>
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden min-h-0">
        {/* Sidebar */}
        <div className="w-72 border-r border-gray-800 p-4 space-y-2 overflow-y-auto">
          <label className="text-xs font-semibold text-gray-500 uppercase tracking-wider px-2">Mis Agentes</label>
          {agents.map(agent => (
            <button
              key={agent.id}
              onClick={() => handleAgentSelect(agent.id)}
              className={`w-full text-left px-4 py-3 rounded-xl transition-all flex flex-col gap-1 ${
                selectedAgentId === agent.id 
                ? 'bg-emerald-500/10 border border-emerald-500/30 ring-1 ring-emerald-500/20' 
                : 'hover:bg-gray-800/50 border border-transparent'
              }`}
            >
              <div className="flex items-center justify-between">
                <span className={`font-semibold ${selectedAgentId === agent.id ? 'text-emerald-400' : 'text-gray-200'}`}>
                  {agent.name}
                </span>
                {agent.is_active === 1 && (
                  <span className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse shadow-[0_0_8px_rgba(16,185,129,0.6)]"></span>
                )}
              </div>
              <span className="text-xs text-gray-500 truncate">{agent.description}</span>
            </button>
          ))}
        </div>

        {/* Editor Area */}
        <div className="flex-1 overflow-y-auto p-8 custom-scrollbar">
          {error && (
            <div className="mb-6 p-4 bg-red-900/20 border border-red-500/30 text-red-400 rounded-xl flex items-center gap-3">
              <span>⚠️</span> {error}
            </div>
          )}

          {editingAgent && (
            <div className="max-w-4xl space-y-8">
              <div className="grid grid-cols-2 gap-6">
                <div className="space-y-2">
                  <label className="text-sm font-medium text-gray-400">Nombre del Agente</label>
                  <input
                    name="name"
                    value={editingAgent.name}
                    onChange={handleInputChange}
                    className="w-full bg-gray-800/50 border border-gray-700 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-emerald-500/40 transition-all"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium text-gray-400">Estado</label>
                  <div className="flex items-center gap-4 h-[50px]">
                    {editingAgent.is_active === 1 ? (
                      <span className="px-3 py-1 bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 rounded-full text-xs font-bold uppercase">Activo Ahora</span>
                    ) : (
                      <button 
                        onClick={handleActivate}
                        className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg text-sm transition-all border border-gray-700"
                      >
                        Activar este agente
                      </button>
                    )}
                  </div>
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium text-gray-400">Descripción</label>
                <input
                  name="description"
                  value={editingAgent.description}
                  onChange={handleInputChange}
                  className="w-full bg-gray-800/50 border border-gray-700 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-emerald-500/40 transition-all"
                />
              </div>

              <div className="space-y-2">
                <div className="flex justify-between items-end">
                  <label className="text-sm font-medium text-gray-400">System Prompt</label>
                  <span className="text-[10px] text-gray-600 font-mono">Este prompt define la personalidad y reglas del bot</span>
                </div>
                <textarea
                  name="system_prompt"
                  value={editingAgent.system_prompt}
                  onChange={handleInputChange}
                  rows={15}
                  className="w-full bg-gray-950/50 border border-gray-800 rounded-xl px-4 py-4 focus:outline-none focus:ring-2 focus:ring-emerald-500/40 transition-all font-mono text-sm leading-relaxed text-emerald-50/80 custom-scrollbar shadow-inner"
                />
              </div>

              <div className="grid grid-cols-2 gap-6">
                <div className="space-y-2">
                  <label className="text-sm font-medium text-gray-400">Escalation Marker</label>
                  <input
                    name="escalation_marker"
                    value={editingAgent.escalation_marker}
                    onChange={handleInputChange}
                    className="w-full bg-gray-800/50 border border-gray-700 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-emerald-500/40 transition-all font-mono text-sm"
                  />
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium text-gray-400">Fallback Responses (JSON)</label>
                <textarea
                  name="fallback_responses"
                  value={editingAgent.fallback_responses}
                  onChange={handleInputChange}
                  rows={8}
                  className="w-full bg-gray-950/50 border border-gray-800 rounded-xl px-4 py-4 focus:outline-none focus:ring-2 focus:ring-emerald-500/40 transition-all font-mono text-sm text-gray-300 shadow-inner"
                />
              </div>
            </div>
          )}
        </div>
      </div>
      <style jsx>{`
        .custom-scrollbar::-webkit-scrollbar {
          width: 6px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background: #1f2937;
          border-radius: 10px;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
          background: #374151;
        }
      `}</style>
    </div>
  );
};

export default AgentEditor;
