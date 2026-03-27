const BASE = window.location.pathname.replace(/\/+$/, '');
let TOKEN = localStorage.getItem('gleaner_token') || '';
let currentSessionId = null;
let transcriptHtmlOriginal = '';

// --- Theme ---
function initTheme() {
  const saved = localStorage.getItem('gleaner_theme');
  const theme = saved || (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
  applyTheme(theme);
}
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  document.getElementById('theme-btn').innerHTML = theme === 'dark' ? '&#9788;' : '&#9790;';
  localStorage.setItem('gleaner_theme', theme);
}
function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'dark';
  applyTheme(current === 'dark' ? 'light' : 'dark');
}
initTheme();

// --- Auth ---
function onAuthSuccess(me, stats) {
  localStorage.setItem('gleaner_token', TOKEN);
  document.getElementById('auth-overlay').classList.add('hidden');
  showUserAvatar();
  showHome(me);
  showStats(stats);
  loadSessions();
  loadSettings();
}
function showAuthLoading(msg) {
  document.getElementById('auth-error').textContent = '';
  const box = document.querySelector('.auth-box');
  box.querySelectorAll('input,button,.auth-divider,#google-signin-btn').forEach(el => el.style.display = 'none');
  let lbl = document.getElementById('auth-loading');
  if (!lbl) { lbl = document.createElement('div'); lbl.id = 'auth-loading'; lbl.className = 'loading'; box.appendChild(lbl); }
  lbl.textContent = msg || 'Signing in...';
  lbl.style.display = '';
}
function hideAuthLoading() {
  const lbl = document.getElementById('auth-loading');
  if (lbl) lbl.style.display = 'none';
  document.querySelector('.auth-box').querySelectorAll('input,button,.auth-divider,#google-signin-btn').forEach(el => el.style.display = '');
}
function authenticate() {
  const input = document.getElementById('token-input');
  TOKEN = input.value.trim();
  if (!TOKEN) return;
  showAuthLoading();
  Promise.all([apiFetch('/api/me'), apiFetch('/api/stats')]).then(([me, stats]) => {
    onAuthSuccess(me, stats);
  }).catch(() => {
    hideAuthLoading();
    document.getElementById('auth-error').textContent = 'Invalid token';
  });
}
function logout() {
  TOKEN = '';
  localStorage.removeItem('gleaner_token');
  localStorage.removeItem('gleaner_google_user');
  document.getElementById('user-avatar').style.display = 'none';
  if (window.google?.accounts?.id) { google.accounts.id.disableAutoSelect(); google.accounts.id.cancel(); }
  document.getElementById('auth-overlay').classList.remove('hidden');
  document.getElementById('auth-error').textContent = '';
  document.getElementById('token-input').value = '';
}
document.getElementById('token-input').addEventListener('keydown', e => { if (e.key === 'Enter') authenticate(); });

// Google Sign-In
function handleGoogleSignIn(response) {
  TOKEN = response.credential;
  try {
    const p = JSON.parse(atob(TOKEN.split('.')[1]));
    localStorage.setItem('gleaner_google_user', JSON.stringify({
      name: p.name || '', email: p.email || '', picture: p.picture || ''
    }));
  } catch(e) {}
  showAuthLoading();
  apiFetch('/api/me').then(me => {
    if (me.onboarding_required) {
      hideAuthLoading();
      document.getElementById('auth-overlay').classList.add('hidden');
      showOnboarding(me);
      return;
    }
    return apiFetch('/api/stats').then(stats => onAuthSuccess(me, stats));
  }).catch(() => {
    hideAuthLoading();
    document.getElementById('auth-error').textContent = 'Access denied — your Google account is not authorized';
    TOKEN = '';
  });
}

function showUserAvatar() {
  try {
    const user = JSON.parse(localStorage.getItem('gleaner_google_user') || 'null');
    if (user?.picture) {
      const av = document.getElementById('user-avatar');
      av.src = user.picture;
      av.title = user.name || user.email || '';
      av.style.display = '';
    }
  } catch(e) {}
}

// Init Google Sign-In button
fetch(BASE + '/api/config').then(r => r.json()).then(cfg => {
  if (!cfg.google_client_id) return;
  function tryInit() {
    if (!window.google?.accounts?.id) { setTimeout(tryInit, 100); return; }
    google.accounts.id.initialize({
      client_id: cfg.google_client_id,
      callback: handleGoogleSignIn,
    });
    google.accounts.id.renderButton(
      document.getElementById('google-signin-btn'),
      { theme: 'outline', size: 'large', width: 320 }
    );
    document.getElementById('auth-divider').style.display = '';
  }
  tryInit();
}).catch(() => {});

// Auto-login: mock mode or stored token
fetch(BASE + '/api/config').then(r => r.json()).then(cfg => {
  if (cfg.mock) {
    TOKEN = 'mock';
    showAuthLoading();
    Promise.all([apiFetch('/api/me'), apiFetch('/api/stats')]).then(([me, stats]) => {
      onAuthSuccess(me, stats);
    }).catch(() => { hideAuthLoading(); });
    return;
  }
  if (TOKEN) {
    showAuthLoading();
    apiFetch('/api/me').then(me => {
      if (me.onboarding_required) {
        hideAuthLoading();
        document.getElementById('auth-overlay').classList.add('hidden');
        showOnboarding(me);
        return;
      }
      return apiFetch('/api/stats').then(stats => onAuthSuccess(me, stats));
    }).catch(() => { hideAuthLoading(); TOKEN = ''; localStorage.removeItem('gleaner_token'); localStorage.removeItem('gleaner_google_user'); });
  }
}).catch(() => {});

// --- API ---
function apiFetch(path) {
  return fetch(BASE + path, { headers: { 'Authorization': 'Bearer ' + TOKEN } })
    .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });
}

// --- Tabs ---
document.querySelectorAll('nav button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
    document.getElementById('detail-view').style.display = 'none';
  });
});

// --- Home (personal) ---
function showHome(data) {
  document.getElementById('home-loading').style.display = 'none';
  const content = document.getElementById('home-content');
  content.style.display = '';
  renderProfile(data, content, true);
}

function renderProfile(data, containerEl, isOwn) {
  const ls = data.last_session;
  const greeting = isOwn ? `Welcome back, ${esc(data.user)}` : esc(data.user);
  const lastInfo = ls
    ? `Last session ${relativeTime(ls.first_timestamp)} on <b>${esc((ls.provenance||{}).host || '?')}</b> in <b>${esc(prettyProject(ls.project||''))}</b>`
    : 'No sessions uploaded yet';

  let html = `<div class="greeting-bar"><div>${greeting}</div><div class="sub">${lastInfo}</div></div>`;

  if (ls) {
    const dur = formatDuration(ls.first_timestamp, ls.last_timestamp);
    const size = ls.transcript_size ? (ls.transcript_size / 1024).toFixed(0) + ' KB' : '?';
    const cwd = ls.cwd || prettyProject(ls.project || '');
    html += `<div class="hero-card" onclick="showDetail('${escAttr(ls.session_id)}')">
      <div class="hero-topic">${esc(ls.topic || 'Untitled session')}</div>
      <div class="hero-meta">
        <span>${esc((ls.provenance||{}).host || '?')}</span>
        <span>${esc(cwd)}</span>
        <span>${dur}</span>
        <span>${ls.message_count || 0} messages</span>
        <span>${ls.tool_use_count || 0} tool uses</span>
        <span>${size}</span>
      </div></div>`;
  }

  const ws = data.week_stats;
  const delta = ws.sessions - ws.sessions_prev_week;
  const deltaClass = delta > 0 ? 'positive' : delta < 0 ? 'negative' : 'zero';
  const deltaStr = delta > 0 ? `+${delta}` : `${delta}`;
  html += `<div class="stats-grid">
    <div class="stat-card"><div class="label">Sessions this week</div>
      <div class="value accent">${ws.sessions}<span class="delta ${deltaClass}">${deltaStr}</span></div></div>
    <div class="stat-card"><div class="label">Messages this week</div>
      <div class="value">${ws.messages.toLocaleString()}</div></div>
    <div class="stat-card"><div class="label">Avg session duration</div>
      <div class="value purple">${fmtDur(ws.avg_duration_seconds)}</div></div>
    <div class="stat-card"><div class="label">Top project</div>
      <div class="value green" style="font-size:1em">${esc(prettyProject(ws.most_active_project || '\u2014'))}</div></div>
  </div>`;

  html += `<div class="panel" style="margin-bottom:24px"><h3>Activity</h3><div class="profile-activity"></div></div>`;

  html += `<div class="panel-grid">
    <div class="panel"><h3>This Week</h3>
      <div class="insights-grid">
        <div class="insight-item"><div class="insight-value accent">${ws.active_days || 0}<span style="font-size:0.5em;color:var(--text2)"> / 7 days</span></div><div class="insight-label">Active days</div></div>
        <div class="insight-item"><div class="insight-value">${fmtDur(ws.total_duration_seconds || 0)}</div><div class="insight-label">Time in Claude</div></div>
        <div class="insight-item"><div class="insight-value purple">${data.avg_messages_per_session || 0}</div><div class="insight-label">Avg msgs / session</div></div>
        <div class="insight-item"><div class="insight-value">${(data.total_sessions || 0).toLocaleString()}</div><div class="insight-label">All-time sessions</div></div>
      </div>
    </div>
    <div class="panel"><h3>Projects</h3>
      <div class="bar-chart profile-projects"></div>
    </div>
  </div>`;

  const recent = data.recent_sessions || [];
  html += `<div class="panel" style="margin-top:24px"><h3>Recent Sessions</h3><div class="recent-list">`;
  html += recent.map(s => {
    const topic = s.topic || 'No topic';
    const time = s.first_timestamp ? relativeTime(s.first_timestamp) : '?';
    const dur = formatDuration(s.first_timestamp, s.last_timestamp);
    return `<div class="recent-item" onclick="showDetail('${escAttr(s.session_id)}')">
      <span class="topic" title="${esc(topic)}">${esc(topic)}</span>
      <span class="meta">${s.message_count||0} msgs &middot; ${dur} &middot; ${time}</span>
    </div>`;
  }).join('') || '<div style="color:var(--text2);font-size:13px;padding:12px">No sessions yet</div>';
  html += '</div></div>';

  containerEl.innerHTML = html;
  renderActivity(data.heatmap, containerEl.querySelector('.profile-activity'));

  const projEl = containerEl.querySelector('.profile-projects');
  if (projEl) {
    const entries = Object.entries(data.project_usage || {}).slice(0, 15);
    const max = entries.length ? entries[0][1] : 1;
    projEl.innerHTML = entries.map(([name, count]) =>
      `<div class="bar-row project" onclick="filterByProject('${escAttr(name)}')">
        <span class="name" title="${esc(name)}">${esc(prettyProject(name))}</span>
        <div class="bar" style="width:${Math.max(count/max*100, 1)}%"></div>
        <span class="count">${count.toLocaleString()}</span>
      </div>`
    ).join('') || '<div style="color:var(--text2);font-size:13px">No data</div>';
  }
}

function renderActivity(days, el) {
  if (!days || !days.length) { el.innerHTML = ''; return; }
  const max = Math.max(...days.map(d => d.count), 1);
  const t1 = Math.ceil(max * 0.25), t2 = Math.ceil(max * 0.5), t3 = Math.ceil(max * 0.75);
  function lvl(c) { return c === 0 ? '' : c <= t1 ? 'l1' : c <= t2 ? 'l2' : c <= t3 ? 'l3' : 'l4'; }
  const lookup = {};
  days.forEach(d => { lookup[d.date] = d.count; });
  const firstDate = new Date(days[0].date + 'T12:00:00');
  const lastDate = new Date(days[days.length - 1].date + 'T12:00:00');
  const lastIso = days[days.length - 1].date;
  let html = '';
  let y = firstDate.getFullYear(), m = firstDate.getMonth();
  const endY = lastDate.getFullYear(), endM = lastDate.getMonth();
  while (y < endY || (y === endY && m <= endM)) {
    const dim = new Date(y, m + 1, 0).getDate();
    const dow1 = (new Date(y, m, 1).getDay() + 6) % 7;
    const title = new Date(y, m, 15).toLocaleDateString(undefined, { month: 'short', year: 'numeric' });
    html += '<div class="activity-month"><div class="activity-month-title">' + title + '</div><div class="activity-month-grid">';
    ['Mo','Tu','We','Th','Fr','Sa','Su'].forEach(h => { html += '<div class="activity-day-header">' + h + '</div>'; });
    for (let i = 0; i < dow1; i++) html += '<div class="activity-day empty"></div>';
    for (let d = 1; d <= dim; d++) {
      const iso = y + '-' + String(m+1).padStart(2,'0') + '-' + String(d).padStart(2,'0');
      if (iso > lastIso) break;
      const count = lookup[iso] || 0;
      html += '<div class="activity-day ' + lvl(count) + '" data-tip="' + iso + ': ' + count + '"></div>';
    }
    html += '</div></div>';
    if (++m > 11) { m = 0; y++; }
  }
  el.innerHTML = '<div class="activity-months">' + html + '</div>';
}

// --- Stats / Team ---
function showStats(data) {
  document.getElementById('stats-loading').style.display = 'none';
  document.getElementById('stats-content').style.display = '';

  const avgMsgs = data.total_sessions ? Math.round(data.total_messages / data.total_sessions) : 0;
  document.getElementById('stats-grid').innerHTML = `
    <div class="stat-card"><div class="label">Sessions</div><div class="value accent">${data.total_sessions.toLocaleString()}</div></div>
    <div class="stat-card"><div class="label">Messages</div><div class="value">${data.total_messages.toLocaleString()}</div></div>
    <div class="stat-card"><div class="label">Avg Duration</div><div class="value purple">${fmtDur(data.avg_duration_seconds)}</div></div>
    <div class="stat-card"><div class="label">Avg Msgs/Session</div><div class="value">${avgMsgs}</div></div>
    <div class="stat-card"><div class="label">Users</div><div class="value green">${data.unique_users}</div></div>
    <div class="stat-card"><div class="label">Active This Week</div><div class="value green">${data.active_this_week || 0}</div></div>
  `;

  // Activity timeline
  const timeline = data.timeline || [];
  const maxDay = Math.max(...timeline.map(d => d.count), 1);
  document.getElementById('activity-timeline').innerHTML = timeline.map(d => {
    const pct = Math.max((d.count / maxDay) * 100, d.count > 0 ? 3 : 0);
    const cls = d.count === 0 ? 'day zero' : 'day';
    const label = new Date(d.date + 'T12:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    return `<div class="${cls}" style="height:${pct}%" title="${label}: ${d.count}"><div class="tooltip">${label}: ${d.count} session${d.count !== 1 ? 's' : ''}</div></div>`;
  }).join('');

  const labels = document.getElementById('timeline-labels');
  if (timeline.length) {
    const first = new Date(timeline[0].date + 'T12:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    const last = new Date(timeline[timeline.length - 1].date + 'T12:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    labels.innerHTML = `<span>${first}</span><span>${last}</span>`;
  }

  // User cards
  document.getElementById('user-cards').innerHTML = Object.entries(data.user_stats || {}).map(([name, s]) => {
    const lastActive = s.last_active ? relativeTime(s.last_active) : 'never';
    return `<div class="user-card" onclick="showUserProfile('${escAttr(name)}')">
      <div class="uc-name">${esc(name)}</div>
      <div class="uc-meta">
        <span>Last active ${lastActive}</span>
        <span><span style="color:var(--accent);font-weight:600">${s.active_days_this_week || 0}d</span> this week &middot; ${s.sessions.toLocaleString()} sessions</span>
        <span>Avg ${fmtDur(s.avg_duration_seconds)} &middot; ${esc(prettyProject(s.top_project || ''))}</span>
      </div>
    </div>`;
  }).join('') || '<div style="color:var(--text2);font-size:13px;padding:12px">No team members</div>';

  // Project activity
  document.getElementById('project-activity').innerHTML = Object.entries(data.project_stats || {}).slice(0, 15).map(([name, s]) => {
    const users = (s.users || []).map(u => `<span class="user-tag">${esc(u)}</span>`).join(' ');
    return `<div class="recent-item" onclick="filterByProject('${escAttr(name)}')">
      <span class="topic" title="${esc(name)}">${esc(prettyProject(name))}</span>
      <span style="flex-shrink:0">${users}</span>
      <span class="meta">${s.sessions} sessions</span>
    </div>`;
  }).join('') || '<div style="color:var(--text2);font-size:13px;padding:12px">No projects</div>';
}

function showUserProfile(username) {
  document.getElementById('stats-content').style.display = 'none';
  const profile = document.getElementById('user-profile');
  profile.style.display = '';
  document.getElementById('user-profile-content').innerHTML = '<div class="loading">Loading profile...</div>';
  apiFetch('/api/user/' + encodeURIComponent(username) + '/stats').then(data => {
    renderProfile(data, document.getElementById('user-profile-content'), false);
  }).catch(() => {
    document.getElementById('user-profile-content').innerHTML = '<div class="empty">Could not load profile</div>';
  });
}

function hideUserProfile() {
  document.getElementById('user-profile').style.display = 'none';
  document.getElementById('stats-content').style.display = '';
}

// --- Sessions ---
function loadSessions() {
  const user = document.getElementById('filter-user').value.trim();
  const project = document.getElementById('filter-project').value.trim();
  const limit = document.getElementById('filter-limit').value;
  let url = `/api/sessions?limit=${limit}`;
  if (user) url += `&user=${encodeURIComponent(user)}`;
  if (project) url += `&project=${encodeURIComponent(project)}`;

  // Show active filters
  const filtersEl = document.getElementById('active-filters');
  let filterHtml = '';
  if (user) filterHtml += `<span class="filter-tag">user: ${esc(user)} <span class="x" onclick="clearFilter('user')">&times;</span></span> `;
  if (project) filterHtml += `<span class="filter-tag">project: ${esc(prettyProject(project))} <span class="x" onclick="clearFilter('project')">&times;</span></span> `;
  filtersEl.innerHTML = filterHtml ? `<div class="filters">${filterHtml}</div>` : '';

  document.getElementById('sessions-content').innerHTML = '<div class="loading">Loading...</div>';

  apiFetch(url).then(data => {
    const sessions = data.sessions || [];
    if (!sessions.length) {
      document.getElementById('sessions-content').innerHTML = '<div class="empty">No sessions found</div>';
      return;
    }
    let html = `<table><thead><tr>
      <th>Topic</th><th>User</th><th>Project</th><th>Messages</th><th>Tools</th><th>Duration</th><th>When</th><th>Size</th>
    </tr></thead><tbody>`;
    for (const s of sessions) {
      const topic = s.topic || '';
      const topicClass = topic ? 'topic-cell' : 'topic-cell empty';
      const topicText = topic || 'untitled';
      const duration = formatDuration(s.first_timestamp, s.last_timestamp);
      const when = s.first_timestamp ? relativeTime(s.first_timestamp) : '?';
      const size = s.transcript_size ? (s.transcript_size/1024).toFixed(0) + ' KB' : '?';
      const user = s.provenance?.user || '?';
      const project = s.project || '';
      html += `<tr onclick="showDetail('${s.session_id}')">
        <td class="${topicClass}" title="${esc(topic)}">${esc(topicText.length > 60 ? topicText.slice(0,60)+'...' : topicText)}</td>
        <td><span class="clickable-tag" onclick="event.stopPropagation();filterByUser('${escAttr(user)}')">${esc(user)}</span></td>
        <td><span class="clickable-tag" onclick="event.stopPropagation();filterByProject('${escAttr(project)}')" title="${esc(project)}">${esc(prettyProject(project))}</span></td>
        <td><span class="badge">${s.message_count||0}</span></td>
        <td>${s.tool_use_count||0}</td>
        <td class="mono">${duration}</td>
        <td title="${s.first_timestamp||''}">${when}</td>
        <td class="mono">${size}</td>
      </tr>`;
    }
    html += '</tbody></table>';
    document.getElementById('sessions-content').innerHTML = html;
  });
}

function filterByUser(user) {
  document.getElementById('filter-user').value = user;
  document.getElementById('filter-project').value = '';
  // Switch to sessions tab
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelector('nav button[data-tab="sessions"]').classList.add('active');
  document.getElementById('tab-sessions').classList.add('active');
  document.getElementById('detail-view').style.display = 'none';
  loadSessions();
}

function filterByProject(project) {
  document.getElementById('filter-project').value = project;
  document.getElementById('filter-user').value = '';
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelector('nav button[data-tab="sessions"]').classList.add('active');
  document.getElementById('tab-sessions').classList.add('active');
  document.getElementById('detail-view').style.display = 'none';
  loadSessions();
}

function clearFilter(type) {
  document.getElementById('filter-' + type).value = '';
  loadSessions();
}

// --- Detail ---
function showDetail(sid) {
  currentSessionId = sid;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  const dv = document.getElementById('detail-view');
  dv.style.display = 'block';

  document.getElementById('detail-title').textContent = 'Loading...';
  document.getElementById('detail-meta').innerHTML = '';
  document.getElementById('detail-tools').innerHTML = '';
  document.getElementById('detail-transcript').innerHTML = '<div class="loading">Loading transcript...</div>';
  document.getElementById('transcript-search').value = '';
  document.getElementById('match-count').textContent = '';

  apiFetch(`/api/session/${sid}`).then(s => {
    const start = s.first_timestamp ? new Date(s.first_timestamp).toLocaleString() : '?';
    const end = s.last_timestamp ? new Date(s.last_timestamp).toLocaleString() : '?';
    const user = s.provenance?.user || '?';
    const host = s.provenance?.host || '?';
    const duration = formatDuration(s.first_timestamp, s.last_timestamp);
    const title = s.topic || prettyProject(s.project || sid);

    document.getElementById('detail-title').textContent = title;
    document.getElementById('detail-meta').innerHTML = `
      <span>User: <b>${esc(user)}</b></span>
      <span>Host: <b>${esc(host)}</b></span>
      <span>Duration: <b>${duration}</b></span>
      <span>Start: <b>${start}</b></span>
      <span>Messages: <b>${s.message_count||0}</b></span>
      <span>Tools: <b>${s.tool_use_count||0}</b></span>
      <span>Size: <b>${((s.transcript_size||0)/1024).toFixed(0)} KB</b></span>
    `;

    const tools = Object.entries(s.tool_counts || {}).sort((a,b) => b[1]-a[1]);
    const maxT = tools.length ? tools[0][1] : 1;
    document.getElementById('detail-tools').innerHTML = tools.map(([name, count]) =>
      `<div class="bar-row">
        <span class="name">${name}</span>
        <div class="bar" style="width:${Math.max(count/maxT*100, 1)}%"></div>
        <span class="count">${count}</span>
      </div>`
    ).join('') || '<div style="color:var(--text2);font-size:13px">No tool usage recorded</div>';

    loadTranscript(sid);
  });
}

function loadTranscript(sid) {
  fetch(BASE + `/api/session/${sid}/raw`, { headers: { 'Authorization': 'Bearer ' + TOKEN } })
    .then(r => r.blob())
    .then(blob => {
      const ds = new DecompressionStream('gzip');
      const reader = blob.stream().pipeThrough(ds).getReader();
      let chunks = [];
      return reader.read().then(function process({ done, value }) {
        if (done) return new Blob(chunks).text();
        chunks.push(value);
        return reader.read().then(process);
      });
    })
    .then(text => {
      const lines = text.trim().split('\n').filter(Boolean);
      const container = document.getElementById('detail-transcript');
      let html = '';
      let count = 0;
      let pendingTools = {};

      for (const line of lines) {
        try {
          const entry = JSON.parse(line);
          const type = entry.type || 'unknown';

          if (type === 'user') {
            const blocks = extractBlocks(entry);
            for (const b of blocks) {
              if (b.type === 'text' && b.text) {
                html += `<div class="msg user"><div class="role">User</div><div class="content"><pre>${esc(b.text)}</pre></div></div>`;
                count++;
              } else if (b.type === 'tool_result') {
                const toolId = b.tool_use_id;
                const call = toolId && pendingTools[toolId];
                if (call) {
                  html += renderToolGroup(call, b);
                  count++;
                  delete pendingTools[toolId];
                }
              }
            }
          } else if (type === 'assistant') {
            // Flush unmatched tool calls
            for (const id of Object.keys(pendingTools)) {
              html += renderToolGroup(pendingTools[id], null);
              count++;
            }
            pendingTools = {};

            const blocks = extractBlocks(entry);
            for (const b of blocks) {
              if (b.type === 'text' && b.text) {
                html += `<div class="msg assistant"><div class="role">Assistant</div><div class="content"><pre>${esc(b.text)}</pre></div></div>`;
                count++;
              } else if (b.type === 'tool_use') {
                pendingTools[b.id] = { name: b.name, input: b.input };
              }
            }
          }
        } catch(e) {}
      }

      // Flush remaining
      for (const id of Object.keys(pendingTools)) {
        html += renderToolGroup(pendingTools[id], null);
        count++;
      }

      if (!count) html = '<div class="empty">No messages to display</div>';
      container.innerHTML = html;
      transcriptHtmlOriginal = html;

      // Wire up collapsible tool groups
      container.querySelectorAll('.tool-header').forEach(header => {
        header.addEventListener('click', () => {
          header.classList.toggle('open');
          header.nextElementSibling.classList.toggle('open');
        });
      });
    })
    .catch(() => {
      document.getElementById('detail-transcript').innerHTML = '<div class="empty">Could not load transcript</div>';
    });
}

function renderToolGroup(call, result) {
  const name = call.name || '?';
  const inp = typeof call.input === 'string' ? call.input : JSON.stringify(call.input || {}, null, 2);
  const preview = toolPreview(call);
  const hasError = result && result.is_error;
  const statusIcon = result ? (hasError ? '<span style="color:var(--red)">&#10007;</span>' : '<span style="color:var(--green)">&#10003;</span>') : '<span style="color:var(--text2)">&#8943;</span>';

  let resultHtml = '';
  if (result) {
    const out = typeof result.content === 'string' ? result.content :
      Array.isArray(result.content) ? result.content.map(c => c.text || '').join('\n') :
      JSON.stringify(result.content || '', null, 2);
    resultHtml = `<div class="msg tool"><div class="role">Result${hasError ? ' (error)' : ''}</div><div class="content"><pre>${esc(truncate(out, 4000))}</pre></div></div>`;
  }

  return `<div class="tool-group">
    <div class="tool-header">
      <span class="chevron">&#9654;</span>
      <span class="tool-name">${esc(name)}</span>
      <span class="tool-preview">${esc(preview)}</span>
      <span class="tool-status">${statusIcon}</span>
    </div>
    <div class="tool-body">
      <div class="msg tool"><div class="role">Input</div><div class="content"><pre>${esc(truncate(inp, 4000))}</pre></div></div>
      ${resultHtml}
    </div>
  </div>`;
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

function searchTranscript() {
  const query = document.getElementById('transcript-search').value.trim();
  const container = document.getElementById('detail-transcript');
  const countEl = document.getElementById('match-count');

  if (!query) {
    container.innerHTML = transcriptHtmlOriginal;
    countEl.textContent = '';
    // Re-wire collapsible
    container.querySelectorAll('.tool-header').forEach(header => {
      header.addEventListener('click', () => {
        header.classList.toggle('open');
        header.nextElementSibling.classList.toggle('open');
      });
    });
    return;
  }

  // Highlight matches in the original HTML text content
  const re = new RegExp(escRegex(query), 'gi');
  let matchCount = 0;

  // Walk text nodes and highlight
  container.innerHTML = transcriptHtmlOriginal;
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  const textNodes = [];
  while (walker.nextNode()) textNodes.push(walker.currentNode);

  for (const node of textNodes) {
    const text = node.textContent;
    if (!re.test(text)) continue;
    re.lastIndex = 0;
    const frag = document.createDocumentFragment();
    let lastIdx = 0;
    let match;
    while ((match = re.exec(text)) !== null) {
      matchCount++;
      if (match.index > lastIdx) frag.appendChild(document.createTextNode(text.slice(lastIdx, match.index)));
      const mark = document.createElement('mark');
      mark.textContent = match[0];
      frag.appendChild(mark);
      lastIdx = re.lastIndex;
    }
    if (lastIdx < text.length) frag.appendChild(document.createTextNode(text.slice(lastIdx)));
    node.parentNode.replaceChild(frag, node);
  }

  countEl.textContent = matchCount ? `${matchCount} match${matchCount !== 1 ? 'es' : ''}` : 'No matches';

  // Open tool groups that contain matches
  container.querySelectorAll('.tool-body').forEach(body => {
    if (body.querySelector('mark')) {
      body.classList.add('open');
      body.previousElementSibling.classList.add('open');
    }
  });

  // Re-wire collapsible
  container.querySelectorAll('.tool-header').forEach(header => {
    header.addEventListener('click', () => {
      header.classList.toggle('open');
      header.nextElementSibling.classList.toggle('open');
    });
  });
}

function downloadRaw() {
  if (!currentSessionId) return;
  fetch(BASE + `/api/session/${currentSessionId}/raw`, { headers: { 'Authorization': 'Bearer ' + TOKEN } })
    .then(r => r.blob())
    .then(blob => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${currentSessionId}.jsonl.gz`;
      a.click();
      URL.revokeObjectURL(url);
    });
}

function hideDetail() {
  document.getElementById('detail-view').style.display = 'none';
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  document.querySelector('nav button[data-tab="sessions"]').classList.add('active');
  document.getElementById('tab-sessions').classList.add('active');
}

function extractBlocks(entry) {
  const msg = entry.message || {};
  const content = msg.content;
  if (typeof content === 'string') return [{ type: 'text', text: content }];
  if (Array.isArray(content)) return content;
  return [];
}

// --- Helpers ---
function fmtDur(secs) {
  if (!secs) return '0s';
  if (secs >= 3600) return `${Math.floor(secs/3600)}h ${Math.round((secs%3600)/60)}m`;
  if (secs >= 60) return `${Math.round(secs/60)}m`;
  return `${Math.round(secs)}s`;
}
function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function escAttr(s) { return String(s).replace(/&/g,'&amp;').replace(/'/g,'&#39;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function escRegex(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
function truncate(s, n) { return s.length > n ? s.slice(0, n) + '...' : s; }

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

// --- Onboarding wizard ---
let obData = null;
let obToken = null;
let obUsername = '';
const OB_STEPS = 3;

function showOnboarding(data) {
  obData = data;
  obUsername = data.suggested_username || '';
  document.getElementById('onboard-overlay').classList.add('active');
  obStep(1);
}

function obProgress(step) {
  let h = '';
  for (let i = 1; i <= OB_STEPS; i++) {
    const cls = i < step ? 'pip done' : i === step ? 'pip current' : 'pip';
    h += `<div class="${cls}"></div>`;
  }
  document.getElementById('ob-progress').innerHTML = h;
}

function obStep(step) {
  obProgress(step);
  const el = document.getElementById('ob-content');
  const name = obData.display_name ? esc(obData.display_name.split(' ')[0]) : '';

  if (step === 1) {
    el.innerHTML = `
      <h1>Welcome${name ? ', ' + name : ''}!</h1>
      <p class="sub">Set up your Gleaner account to start tracking Claude Code sessions.</p>
      <div class="ob-step-title">Choose your username</div>
      <div class="ob-field">
        <input type="text" id="ob-username" value="${escAttr(obUsername)}" placeholder="username" maxlength="20"
          oninput="obCheckUsername(this.value)">
        <div class="ob-hint muted" id="ob-user-hint">Letters, numbers, hyphens, underscores. 2-20 chars.</div>
      </div>
      <div class="ob-actions">
        <button class="btn-p" id="ob-next-1" onclick="obSubmitUsername()">Continue</button>
      </div>`;
    // Check initial suggestion
    setTimeout(() => obCheckUsername(obUsername), 100);
  }

  else if (step === 2) {
    const serverUrl = window.location.origin + BASE;
    el.innerHTML = `
      <h1>Create an API token</h1>
      <p class="sub">
        When a Claude Code session ends, a hook uploads the transcript to Gleaner.
        The token authenticates those uploads. Create one per machine so you can revoke independently.
      </p>
      <div class="ob-step-title">Token name</div>
      <div class="ob-field">
        <input type="text" id="ob-token-name" value="default" placeholder="e.g. laptop, work-desktop">
      </div>
      <div id="ob-token-display"></div>
      <div id="ob-setup-block" style="display:none">
        <div class="ob-step-title" style="margin-top:20px">Install and configure</div>
        <p style="font-size:13px;color:var(--text2);margin-bottom:8px">
          Run these two commands. The first installs the CLI
          (<a href="https://docs.astral.sh/uv/getting-started/installation/" target="_blank">uv</a> required),
          the second saves your credentials and adds the session hook to Claude Code.
        </p>
        <div class="code-block" id="cb-install">
          <button class="cb-copy" onclick="obCopy('cb-install')">Copy</button>
uv tool install git+https://github.com/covenance-ai/gleaner</div>
        <div class="code-block" id="cb-setup">
          <button class="cb-copy" onclick="obCopy('cb-setup')">Copy</button>
gleaner setup ${esc(serverUrl)} <span id="ob-setup-token">gl_your_token</span></div>
        <p style="font-size:12px;color:var(--text2);margin-top:8px">
          This writes config to <code>~/.config/gleaner.json</code> and installs the session hook in <code>~/.claude/settings.json</code>.
          Check with <code>gleaner status</code>. Disable anytime with <code>gleaner off</code>.
        </p>
      </div>
      <div class="ob-actions">
        <button class="btn-p" id="ob-gen-btn" onclick="obGenerateToken()">Generate Token</button>
        <button class="btn-p" id="ob-next-2" onclick="obStep(3)" style="display:none">Continue</button>
      </div>`;
  }

  else if (step === 3) {
    el.innerHTML = `
      <h1>Upload existing sessions</h1>
      <p class="sub">Backfill your past Claude Code conversations to Gleaner.</p>
      <div class="code-block" id="cb-backfill">
        <button class="cb-copy" onclick="obCopy('cb-backfill')">Copy</button>
gleaner backfill</div>
      <p style="font-size:12px;color:var(--text2);margin-top:8px">
        Scans <code>~/.claude/projects/</code> and uploads sessions not already on the server.
        Use <code>--dry-run</code> to preview first.
      </p>
      <div class="ob-actions">
        <button class="btn-p" onclick="obFinish()">Go to Dashboard</button>
        <button class="btn-s" onclick="obFinish()">Skip for now</button>
      </div>`;
  }
}

let obCheckTimer = null;
function obCheckUsername(val) {
  obUsername = val.trim().toLowerCase();
  const hint = document.getElementById('ob-user-hint');
  const btn = document.getElementById('ob-next-1');
  if (!obUsername || obUsername.length < 2) {
    hint.textContent = 'Letters, numbers, hyphens, underscores. 2-20 chars.';
    hint.className = 'ob-hint muted';
    btn.disabled = true;
    return;
  }
  if (!/^[a-z0-9][a-z0-9_-]*$/.test(obUsername)) {
    hint.textContent = 'Must start with a letter or number. Only a-z, 0-9, - and _ allowed.';
    hint.className = 'ob-hint err';
    btn.disabled = true;
    return;
  }
  hint.textContent = 'Checking...';
  hint.className = 'ob-hint muted';
  btn.disabled = true;
  clearTimeout(obCheckTimer);
  obCheckTimer = setTimeout(() => {
    apiFetch('/api/username-check/' + encodeURIComponent(obUsername)).then(r => {
      if (document.getElementById('ob-username')?.value.trim().toLowerCase() !== obUsername) return;
      if (r.available) {
        hint.textContent = obUsername + ' is available';
        hint.className = 'ob-hint ok';
        btn.disabled = false;
      } else {
        hint.textContent = r.reason || 'Username is taken';
        hint.className = 'ob-hint err';
        btn.disabled = true;
      }
    }).catch(() => {
      hint.textContent = 'Could not check availability';
      hint.className = 'ob-hint err';
    });
  }, 300);
}

function obSubmitUsername() {
  const btn = document.getElementById('ob-next-1');
  btn.disabled = true;
  btn.textContent = 'Creating account...';
  fetch(BASE + '/api/onboard', {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: obUsername })
  }).then(r => {
    if (!r.ok) return r.json().then(e => { throw new Error(e.detail || 'Failed'); });
    return r.json();
  }).then(() => {
    obStep(2);
  }).catch(err => {
    btn.disabled = false;
    btn.textContent = 'Continue';
    const hint = document.getElementById('ob-user-hint');
    hint.textContent = err.message || 'Something went wrong';
    hint.className = 'ob-hint err';
  });
}

function obGenerateToken() {
  const btn = document.getElementById('ob-gen-btn');
  const nameInput = document.getElementById('ob-token-name');
  btn.disabled = true;
  btn.textContent = 'Generating...';
  fetch(BASE + '/api/tokens', {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: nameInput.value.trim() || 'default' })
  }).then(r => {
    if (!r.ok) throw new Error('Failed to create token');
    return r.json();
  }).then(data => {
    obToken = data.token;
    btn.style.display = 'none';
    nameInput.closest('.ob-field').style.display = 'none';
    document.getElementById('ob-token-display').innerHTML = `
      <div class="token-display">
        <code>${esc(obToken)}</code>
        <button class="copy-btn" onclick="obCopyToken()">Copy</button>
      </div>
      <div class="ob-warn">Save this token now — it will not be shown again.</div>`;
    // Show setup block with actual token
    document.getElementById('ob-setup-block').style.display = '';
    const setupTok = document.getElementById('ob-setup-token');
    if (setupTok) setupTok.textContent = obToken;
    document.getElementById('ob-next-2').style.display = '';
  }).catch(() => {
    btn.disabled = false;
    btn.textContent = 'Generate Token';
  });
}

function obCopyToken() {
  navigator.clipboard.writeText(obToken).then(() => {
    const btn = document.querySelector('.token-display .copy-btn');
    btn.textContent = 'Copied!';
    setTimeout(() => { btn.textContent = 'Copy'; }, 1500);
  });
}

function obCopy(id) {
  const el = document.getElementById(id);
  // Get text content excluding labels and buttons
  const clone = el.cloneNode(true);
  clone.querySelectorAll('.cb-copy, .cb-label').forEach(n => n.remove());
  navigator.clipboard.writeText(clone.textContent.trim()).then(() => {
    const btn = el.querySelector('.cb-copy');
    btn.textContent = 'Copied!';
    setTimeout(() => { btn.textContent = 'Copy'; }, 1500);
  });
}

function obFinish() {
  document.getElementById('onboard-overlay').classList.remove('active');
  showAuthLoading();
  Promise.all([apiFetch('/api/me'), apiFetch('/api/stats')]).then(([me, stats]) => {
    onAuthSuccess(me, stats);
  }).catch(() => { hideAuthLoading(); });
}

// --- Settings / Token management ---

function loadSettings() {
  // Profile
  const profileEl = document.getElementById('settings-profile');
  try {
    const gu = JSON.parse(localStorage.getItem('gleaner_google_user') || 'null');
    if (gu) {
      profileEl.innerHTML = `<div class="profile-card">
        ${gu.picture ? '<img src="' + esc(gu.picture) + '" referrerpolicy="no-referrer">' : ''}
        <div class="pc-info">
          <div class="pc-name">${esc(gu.name || '')}</div>
          <div class="pc-email">${esc(gu.email || '')}</div>
        </div>
      </div>`;
    }
  } catch(e) { profileEl.innerHTML = ''; }

  // Tokens
  loadTokenList();

  // Setup instructions
  renderSetupInstructions();
}

function loadTokenList() {
  const el = document.getElementById('token-list');
  apiFetch('/api/tokens').then(data => {
    const tokens = data.tokens || [];
    if (!tokens.length) {
      el.innerHTML = '<div style="color:var(--text2);font-size:13px;padding:8px 0">No tokens yet. Create one to start uploading sessions.</div>';
      return;
    }
    let html = '<table class="token-table"><thead><tr><th>Prefix</th><th>Name</th><th>Created</th><th>Last Used</th><th>Uses</th><th>Status</th><th></th></tr></thead><tbody>';
    for (const t of tokens) {
      const created = t.created_at ? relativeTime(typeof t.created_at === 'string' ? t.created_at : new Date(t.created_at._seconds ? t.created_at._seconds * 1000 : t.created_at).toISOString()) : '?';
      const lastUsed = t.last_used_at ? relativeTime(typeof t.last_used_at === 'string' ? t.last_used_at : new Date(t.last_used_at._seconds ? t.last_used_at._seconds * 1000 : t.last_used_at).toISOString()) : 'never';
      const active = t.active !== false;
      html += `<tr>
        <td class="tk-prefix">${esc(t.prefix || '?')}...</td>
        <td>${esc(t.notes || t.name || '')}</td>
        <td>${created}</td>
        <td>${lastUsed}</td>
        <td>${t.usage_count || 0}</td>
        <td><span class="${active ? 'tk-active' : 'tk-revoked'}">${active ? 'Active' : 'Revoked'}</span></td>
        <td>${active ? '<button class="tk-revoke-btn" onclick="revokeSettingsToken(\'' + escAttr(t.id) + '\')">Revoke</button>' : ''}</td>
      </tr>`;
    }
    html += '</tbody></table>';
    el.innerHTML = html;
  }).catch(() => {
    el.innerHTML = '<div style="color:var(--text2);font-size:13px">Sign in with Google to manage tokens.</div>';
  });
}

function toggleNewTokenForm() {
  const form = document.getElementById('new-token-form');
  form.classList.toggle('active');
  document.getElementById('new-token-result').innerHTML = '';
  if (form.classList.contains('active')) {
    document.getElementById('new-token-name').focus();
  }
}

function createSettingsToken() {
  const nameInput = document.getElementById('new-token-name');
  const resultEl = document.getElementById('new-token-result');
  fetch(BASE + '/api/tokens', {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: nameInput.value.trim() || 'default' })
  }).then(r => {
    if (!r.ok) throw new Error('Failed');
    return r.json();
  }).then(data => {
    resultEl.innerHTML = `
      <div class="token-display" style="margin-top:12px">
        <code>${esc(data.token)}</code>
        <button class="copy-btn" onclick="navigator.clipboard.writeText('${escAttr(data.token)}').then(()=>{this.textContent='Copied!';setTimeout(()=>{this.textContent='Copy'},1500)})">Copy</button>
      </div>
      <div class="ob-warn">Save this token now — it will not be shown again.</div>`;
    nameInput.value = '';
    loadTokenList();
  }).catch(() => {
    resultEl.innerHTML = '<div style="color:var(--red);font-size:13px;margin-top:8px">Failed to create token</div>';
  });
}

function revokeSettingsToken(tokenId) {
  fetch(BASE + '/api/tokens/' + encodeURIComponent(tokenId), {
    method: 'DELETE',
    headers: { 'Authorization': 'Bearer ' + TOKEN }
  }).then(r => {
    if (!r.ok) throw new Error('Failed');
    loadTokenList();
  }).catch(() => {
    alert('Failed to revoke token');
  });
}

function renderSetupInstructions() {
  const el = document.getElementById('setup-instructions');
  const serverUrl = window.location.origin + BASE;
  el.innerHTML = `
    <div class="code-block" id="cb-setup-install">
      <button class="cb-copy" onclick="obCopy('cb-setup-install')">Copy</button>
      <span class="cb-label">Install the CLI (<a href="https://docs.astral.sh/uv/getting-started/installation/" target="_blank">uv</a> required)</span>
uv tool install git+https://github.com/covenance-ai/gleaner</div>
    <div class="code-block" id="cb-setup-cmd" style="margin-top:12px">
      <button class="cb-copy" onclick="obCopy('cb-setup-cmd')">Copy</button>
      <span class="cb-label">Configure and install the session hook</span>
gleaner setup ${esc(serverUrl)} gl_your_token_here</div>
    <p style="font-size:12px;color:var(--text2);margin-top:8px">
      Replace <code>gl_your_token_here</code> with one of your tokens above.
      Check with <code>gleaner status</code>. Disable anytime with <code>gleaner off</code>.
    </p>`;
}
