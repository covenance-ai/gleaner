// --- Pure utility functions (no DOM, no globals — testable) ---

function fmtDur(secs) {
  if (!secs) return '0s';
  if (secs >= 3600) return `${Math.floor(secs/3600)}h ${Math.round((secs%3600)/60)}m`;
  if (secs >= 60) return `${Math.round(secs/60)}m`;
  return `${Math.round(secs)}s`;
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function escAttr(s) {
  return String(s).replace(/&/g,'&amp;').replace(/'/g,'&#39;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function escRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function truncate(s, n) {
  return s.length > n ? s.slice(0, n) + '...' : s;
}

function prettyProject(p) {
  if (!p) return '?';
  return p.replace(/^-+/, '').replace(/^Users-[^-]+-/, '').replace(/-/g, '/') || p;
}

function relativeTime(ts) {
  if (!ts) return '?';
  const now = Date.now();
  const then = new Date(ts).getTime();
  const diff = now - then;
  if (diff < 0) return 'just now';
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(ts).toLocaleDateString();
}

function formatDuration(start, end) {
  if (!start || !end) return '?';
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (ms < 0) return '?';
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  const remMins = mins % 60;
  return `${hours}h ${remMins}m`;
}

function extractBlocks(entry) {
  const msg = entry.message || {};
  const content = msg.content;
  if (typeof content === 'string') return [{ type: 'text', text: content }];
  if (Array.isArray(content)) return content;
  return [];
}

function toolPreview(call) {
  const inp = call.input || {};
  if (call.name === 'Read' || call.name === 'read_file') return inp.file_path || inp.path || '';
  if (call.name === 'Write' || call.name === 'write_file') return inp.file_path || inp.path || '';
  if (call.name === 'Edit') return inp.file_path || inp.path || '';
  if (call.name === 'Bash' || call.name === 'bash') return truncate(inp.command || inp.cmd || '', 80);
  if (call.name === 'Grep' || call.name === 'grep') return `/${inp.pattern || ''}/ ${inp.path || ''}`;
  if (call.name === 'Glob') return inp.pattern || '';
  if (call.name === 'Agent') return truncate(inp.prompt || inp.description || '', 80);
  if (typeof inp === 'string') return truncate(inp, 80);
  const first = Object.values(inp)[0];
  return first ? truncate(String(first), 80) : '';
}

function parseTimestamp(t) {
  if (!t) return null;
  if (typeof t === 'string') return t;
  if (t._seconds) return new Date(t._seconds * 1000).toISOString();
  return null;
}
