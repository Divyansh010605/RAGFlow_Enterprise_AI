import React, { FormEvent, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

// ── Types ────────────────────────────────────────────────────────────────────
type Message = { role: string; content: string; agent_id?: string; citations?: Citation[]; confidence?: number };
type Citation = { source: string; document_id?: string; score: number };
type Document = { id: string; filename: string; status: string; created_at: string };
type Agent = { id: string; status: string; description: string; run_count: number; last_run?: string };
type AgentRun = { id: string; query: string; status: string; latency_ms: number; agent_id?: string; created_at: string };
type Stats = { documents: number; queries: number; active_agents: number; average_latency_ms: number; success_rate: number };

const AGENT_CHIPS = [
  { id: 'supervisor', name: 'Auto Supervisor', icon: '⚡' },
  { id: 'planner', name: 'Planner Agent', icon: '📋' },
  { id: 'query_analyzer', name: 'Query Analyzer', icon: '🔍' },
  { id: 'rag', name: 'Document RAG', icon: '📄' },
  { id: 'sql', name: 'Sales SQL', icon: '📊' },
  { id: 'graph', name: 'Knowledge Graph', icon: '🕸️' },
  { id: 'evidence', name: 'Evidence Scorer', icon: '🎯' },
  { id: 'critic', name: 'Quality Critic', icon: '🔬' },
  { id: 'response', name: 'Response Synthesizer', icon: '✍️' },
];

const AGENT_PLACEHOLDERS: Record<string, string> = {
  supervisor: "Ask anything -- Auto Supervisor will orchestrate the best agents...",
  planner: "Enter a question or topic to generate a step-by-step retrieval plan...",
  query_analyzer: "Enter a query to classify intent, complexity, and target data sources...",
  rag: "Ask a question about your uploaded documents (.pdf, .docx, .txt, .csv)...",
  sql: "Ask about sales figures, regional performance, or top quarter metrics...",
  graph: "Ask about who manages which region or organizational relationships...",
  evidence: "Enter a query to evaluate and rank retrieved context evidence...",
  critic: "Enter a query to evaluate retrieval precision and context relevance...",
  response: "Ask anything -- Response Synthesizer will produce a direct cited answer...",
};

// ── API helper ───────────────────────────────────────────────────────────────
async function api(path: string, opts: RequestInit = {}, token = '') {
  const r = await fetch(path, {
    ...opts,
    headers: { ...opts.headers, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  const body = await r.json().catch(() => ({ detail: `HTTP ${r.status}` }));
  if (!r.ok) {
    const err = new Error(body.detail || 'Request failed') as Error & { status: number };
    err.status = r.status;
    throw err;
  }
  return body;
}

// ── App ───────────────────────────────────────────────────────────────────────
function App() {
  const [token, setToken] = useState(() => localStorage.getItem('token') || '');
  const [user, setUser] = useState<{ name: string; role: string } | null>(null);
  const [page, setPage] = useState('Chat');

  // Auth form state
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [isRegister, setIsRegister] = useState(false);

  // Chat state
  const [query, setQuery] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState('supervisor');

  // Upload state
  const [uploading, setUploading] = useState(false);

  // Data state
  const [docs, setDocs] = useState<Document[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [agentRuns, setAgentRuns] = useState<AgentRun[]>([]);

  // Notice state
  const [notice, setNotice] = useState('');
  const [noticeError, setNoticeError] = useState(false);
  const noticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function showNotice(msg: string, isError = false) {
    if (noticeTimer.current) clearTimeout(noticeTimer.current);
    setNotice(msg);
    setNoticeError(isError);
    noticeTimer.current = setTimeout(() => setNotice(''), 5000);
  }
  function dismissNotice() { setNotice(''); if (noticeTimer.current) clearTimeout(noticeTimer.current); }

  function navigate(p: string) { setPage(p); dismissNotice(); }

  function signOut() {
    localStorage.removeItem('token');
    setToken('');
    setUser(null);
    setMessages([]);
    setDocs([]);
    setStats(null);
    setAgentRuns([]);
  }

  async function load() {
    if (!token) return;
    try {
      const [d, s, ar] = await Promise.all([
        api('/api/documents', {}, token),
        api('/api/analytics/overview', {}, token),
        api('/api/agents/runs', {}, token),
      ]);
      setDocs(d); setStats(s); setAgentRuns(ar);
    } catch (e) {
      const err = e as Error & { status?: number };
      if (err.status === 401) { signOut(); return; }
      showNotice(err.message, true);
    }
  }

  useEffect(() => { load(); }, [token]);

  // ── Auth ─────────────────────────────────────────────────────────────────
  async function auth(e: FormEvent) {
    e.preventDefault();
    try {
      const r = await api(
        isRegister ? '/api/auth/register' : '/api/auth/login',
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(isRegister ? { name, email, password } : { email, password }) }
      );
      localStorage.setItem('token', r.access_token);
      setToken(r.access_token);
      setUser(r.user);
      setNotice('');
      if (isRegister) {
        showNotice(`Welcome, ${r.user.name}! Assigned role: ${r.user.role}.`);
      }
    } catch (e) { showNotice((e as Error).message, true); }
  }

  // ── Chat ─────────────────────────────────────────────────────────────────
  async function ask(e: FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    const question = query;
    setQuery('');
    setMessages(x => [...x, { role: 'user', content: question }]);
    setBusy(true);
    try {
      const r = await api('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query: question, agent_id: selectedAgent }) }, token);
      setMessages(x => [...x, { role: 'assistant', content: r.answer, agent_id: r.agent_id || selectedAgent, citations: r.citations, confidence: r.confidence }]);
      load();
    } catch (e) {
      const err = e as Error & { status?: number };
      if (err.status === 401) { signOut(); return; }
      setMessages(x => [...x, { role: 'assistant', content: `Error: ${err.message}`, agent_id: selectedAgent }]);
    } finally { setBusy(false); }
  }

  // ── Upload ───────────────────────────────────────────────────────────────
  async function upload(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = (form.elements.namedItem('file') as HTMLInputElement).files?.[0];
    if (!f) return;
    const fd = new FormData(); fd.append('file', f);
    setUploading(true);
    try {
      const r = await api('/api/documents/upload', { method: 'POST', body: fd }, token);
      showNotice(`✓ Indexed "${r.filename}" into ${r.chunks} chunks.`);
      if (form) form.reset();
      load();
    } catch (e) {
      const err = e as Error & { status?: number };
      if (err.status === 401) { signOut(); return; }
      showNotice(err.message, true);
    } finally { setUploading(false); }
  }

  // ── Delete doc ───────────────────────────────────────────────────────────
  async function remove(id: string) {
    try {
      await api(`/api/documents/${id}`, { method: 'DELETE' }, token);
      setDocs(x => x.filter(d => d.id !== id));
    } catch (e) { showNotice((e as Error).message, true); }
  }

  // ── Auth screen ──────────────────────────────────────────────────────────
  if (!token) return (
    <main className="auth">
      <section>
        <p className="eyebrow">RAGFlow Enterprise AI</p>
        <h1>Enterprise intelligence, grounded in evidence.</h1>
        <p>Secure agentic retrieval across documents, data, and relationships.</p>
      </section>
      <form onSubmit={auth}>
        <h2>{isRegister ? 'Create workspace account' : 'Welcome back'}</h2>
        {isRegister && <input placeholder="Full name" value={name} onChange={e => setName(e.target.value)} required />}
        <input placeholder="Email" value={email} onChange={e => setEmail(e.target.value)} type="email" autoComplete="email" required />
        <input placeholder="Password (8+ characters)" value={password} onChange={e => setPassword(e.target.value)} type="password" minLength={8} autoComplete={isRegister ? 'new-password' : 'current-password'} required />
        <button type="submit">{isRegister ? 'Register' : 'Sign in'}</button>
        <a onClick={() => { setIsRegister(!isRegister); dismissNotice(); }}>
          {isRegister ? 'Already registered? Sign in' : 'New here? Create an account'}
        </a>
        {notice && <small className={noticeError ? 'error' : ''}>{notice}</small>}
      </form>
    </main>
  );

  // ── Authenticated app ────────────────────────────────────────────────────
  const pageTitle = page === 'Chat' ? 'Ask enterprise intelligence' : page;
  const currentAgentObj = AGENT_CHIPS.find(a => a.id === selectedAgent);

  return (
    <main className="app">
      {/* ── Desktop sidebar ── */}
      <aside>
        <p className="eyebrow">RAGFlow</p>
        <h2>Enterprise AI</h2>
        <nav>
          {['Chat', 'Documents', 'Analytics', 'Settings'].map(item => (
            <button key={item} className={page === item ? 'selected' : ''} onClick={() => navigate(item)}>{item}</button>
          ))}
        </nav>
        <button className="ghost" onClick={signOut}>Sign out</button>
      </aside>

      {/* Mobile top bar */}
      <div className="mobile-bar">
        <span className="eyebrow">RAGFlow</span>
        <select value={page} onChange={e => navigate(e.target.value)}>
          {['Chat', 'Documents', 'Analytics', 'Settings'].map(item => (
            <option key={item}>{item}</option>
          ))}
        </select>
        <button className="ghost" onClick={signOut}>Sign out</button>
      </div>

      <section className="workspace">
        <header>
          <div>
            <p className="eyebrow">Agentic RAG Workspace</p>
            <h1>{pageTitle}</h1>
          </div>
          {page === 'Chat' && (
            <form className="upload" onSubmit={upload}>
              <input name="file" type="file" accept=".txt,.md,.csv,.json,.pdf,.docx,.xlsx" disabled={uploading} />
              <button type="submit" disabled={uploading}>{uploading ? 'Uploading…' : 'Upload'}</button>
            </form>
          )}
        </header>

        {notice && (
          <div className={`notice${noticeError ? ' error' : ''}`}>
            <span>{notice}</span>
            <button className="notice-close" onClick={dismissNotice} title="Dismiss">×</button>
          </div>
        )}

        {/* ── Chat page with integrated Agent Selector ── */}
        {page === 'Chat' && (
          <>
            <div className="messages">
              {!messages.length && (
                <div className="empty">
                  <h2>Start with a question</h2>
                  <p>Select an Agent chip below or ask Auto Supervisor.<br />Upload reports, PDFs, CSVs, or Word documents for grounded answers.</p>
                </div>
              )}
              {messages.map((m, i) => (
                <article key={i} className={m.role}>
                  <div className="msg-header">
                    <label>{m.role === 'user' ? 'You' : 'RAGFlow Assistant'}</label>
                    {m.role === 'assistant' && (
                      <span className="msg-agent-tag">
                        {(m.agent_id || selectedAgent).replace(/_/g, ' ')}
                      </span>
                    )}
                  </div>
                  <p>{m.content}</p>
                  {m.role === 'assistant' && m.confidence !== undefined && (
                    <div className="msg-confidence">Confidence: {Math.round((m.confidence ?? 0) * 100)}%</div>
                  )}
                  {m.role === 'assistant' && m.citations && m.citations.length > 0 && (
                    <div className="msg-citations">
                      <span>Sources:</span>
                      {m.citations.map((c, j) => (
                        <span key={j} className="citation-chip" title={`Score: ${c.score}`}>{c.source || 'unknown'}</span>
                      ))}
                    </div>
                  )}
                </article>
              ))}
              {busy && (
                <article className="assistant">
                  <div className="msg-header">
                    <label>RAGFlow Assistant</label>
                    <span className="msg-agent-tag">{selectedAgent.replace(/_/g, ' ')}</span>
                  </div>
                  <div className="typing"><span /><span /><span /></div>
                </article>
              )}
            </div>

            {/* Sticky composer section with attached Agent Chips right above text input */}
            <div className="composer-section">
              <div className="agent-selector-bar">
                <span className="agent-chip-label">Agents:</span>
                {AGENT_CHIPS.map(a => (
                  <button
                    key={a.id}
                    type="button"
                    className={`agent-chip${selectedAgent === a.id ? ' active' : ''}`}
                    onClick={() => setSelectedAgent(a.id)}
                  >
                    <span>{a.icon}</span>
                    <span>{a.name}</span>
                  </button>
                ))}
              </div>

              {selectedAgent !== 'supervisor' && currentAgentObj && (
                <div className="active-agent-banner">
                  <span>{currentAgentObj.icon} Active Agent: <strong>{currentAgentObj.name}</strong></span>
                  <button type="button" onClick={() => setSelectedAgent('supervisor')}>Reset to Auto Supervisor ✕</button>
                </div>
              )}

              <form className="composer" onSubmit={ask}>
                <input
                  value={query}
                  onChange={e => setQuery(e.target.value)}
                  placeholder={AGENT_PLACEHOLDERS[selectedAgent] || 'Ask a question about your enterprise knowledge…'}
                  disabled={busy}
                />
                <button type="submit" disabled={busy || !query.trim()}>Send</button>
              </form>
            </div>

            {/* Recent Agent Execution Activity */}
            {agentRuns.length > 0 && (
              <div className="runs-section" style={{ marginTop: 28 }}>
                <h3>📋 Workspace Agent Activity <span style={{ fontWeight: 400, fontSize: 12, color: '#65716a' }}>(Recent runs)</span></h3>
                {agentRuns.slice(0, 5).map(r => (
                  <div className="run-row" key={r.id}>
                    <span className="run-agent">{(r.agent_id || 'supervisor').replace(/_/g, ' ')}</span>
                    <span className="run-query" title={r.query}>{r.query}</span>
                    <span className="run-latency">{r.latency_ms} ms</span>
                    <span className="run-time">{r.created_at ? new Date(r.created_at.endsWith('Z') ? r.created_at : r.created_at + 'Z').toLocaleTimeString() : '—'}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {/* ── Documents page ── */}
        {page === 'Documents' && (
          <div className="panel">
            <h2>Indexed documents</h2>
            {docs.length ? docs.map(d => (
              <div className="row" key={d.id}>
                <span>
                  <b>{d.filename}</b>
                  <small>{d.status} · {d.created_at ? new Date(d.created_at.endsWith('Z') ? d.created_at : d.created_at + 'Z').toLocaleString() : '—'}</small>
                </span>
                <button onClick={() => remove(d.id)}>Delete</button>
              </div>
            )) : (
              <div>
                <p style={{ color: '#65716a', marginTop: 0 }}>No documents uploaded yet.</p>
                <p style={{ fontSize: 14, color: '#65716a' }}>
                  ← Switch to the <strong>Chat</strong> tab and use the <strong>Upload</strong> button in the top-right to index your first document.
                </p>
              </div>
            )}
          </div>
        )}

        {/* ── Analytics page ── */}
        {page === 'Analytics' && (
          <div className="grid">
            {([
              ['Documents', stats?.documents],
              ['Queries', stats?.queries],
              ['Active agents', stats?.active_agents],
              ['Avg latency', `${stats?.average_latency_ms ?? 0} ms`],
              ['Success rate', `${stats?.success_rate ?? 0}%`],
            ] as [string, string | number | undefined][]).map(([label, value]) => (
              <div className="card" key={String(label)}>
                <p className="eyebrow">{label}</p>
                <h2>{value ?? '—'}</h2>
              </div>
            ))}
          </div>
        )}

        {/* ── Settings page ── */}
        {page === 'Settings' && (
          <div className="panel">
            <h2>Workspace settings</h2>
            <p>
              Authentication, document access, safe SQL execution, prompt-injection screening, and audit logging are enabled.
              Configure service URLs and LLM credentials in <code>.env</code> for deployment.
            </p>
            {user && (
              <div className="row">
                <span><b>Signed in as</b><small>{user.name} — role: {user.role}</small></span>
                <button className="ghost" style={{ border: '1px solid #547062', background: 'none', color: '#17201c' }} onClick={signOut}>Sign out</button>
              </div>
            )}
          </div>
        )}
      </section>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
