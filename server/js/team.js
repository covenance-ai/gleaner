// --- Team tab: per-user expandable cards ---

let _expandedUser = null;
const _userDataCache = {};

function showStats(data) {
  document.getElementById('stats-loading').style.display = 'none';
  document.getElementById('stats-content').style.display = '';

  document.getElementById('stats-grid').innerHTML = `
    <div class="stat-card"><div class="label">Sessions</div><div class="value accent">${data.total_sessions.toLocaleString()}</div></div>
    <div class="stat-card"><div class="label">Messages</div><div class="value">${data.total_messages.toLocaleString()}</div></div>
    <div class="stat-card"><div class="label">Users</div><div class="value green">${data.unique_users}</div></div>
    <div class="stat-card"><div class="label">Active This Week</div><div class="value green">${data.active_this_week || 0}</div></div>
  `;

  const entries = Object.entries(data.user_stats || {});
  document.getElementById('user-cards').innerHTML = entries.map(([name, s]) => {
    const lastActive = s.last_active ? relativeTime(s.last_active) : 'never';
    return `<div class="team-user-card" id="team-card-${escAttr(name)}">
      <div class="tuc-header" onclick="toggleUserCard('${escAttr(name)}')">
        <div class="tuc-info">
          <div class="tuc-name">${esc(name)}</div>
          <div class="tuc-summary">
            Last active ${lastActive} &middot;
            <span style="color:var(--accent);font-weight:600">${s.active_days_this_week || 0}d</span> this week &middot;
            ${s.sessions.toLocaleString()} sessions &middot;
            Avg ${fmtDur(s.avg_duration_seconds)}
          </div>
        </div>
        <div class="tuc-chevron">&#9654;</div>
      </div>
      <div class="tuc-body" id="team-body-${escAttr(name)}"></div>
    </div>`;
  }).join('') || '<div style="color:var(--text2);font-size:13px;padding:12px">No team members</div>';
}

function toggleUserCard(username) {
  const card = document.getElementById('team-card-' + username);
  const body = document.getElementById('team-body-' + username);

  if (card.classList.contains('expanded')) {
    card.classList.remove('expanded');
    body.innerHTML = '';
    _expandedUser = null;
    return;
  }

  // Collapse previous
  if (_expandedUser) {
    const prev = document.getElementById('team-card-' + _expandedUser);
    if (prev) { prev.classList.remove('expanded'); }
    const prevBody = document.getElementById('team-body-' + _expandedUser);
    if (prevBody) { prevBody.innerHTML = ''; }
  }

  card.classList.add('expanded');
  _expandedUser = username;
  body.innerHTML = '<div class="loading" style="padding:20px">Loading...</div>';

  if (_userDataCache[username]) {
    renderUserExpanded(username, _userDataCache[username]);
    return;
  }

  apiFetch('/api/user/' + encodeURIComponent(username) + '/stats').then(data => {
    _userDataCache[username] = data;
    renderUserExpanded(username, data);
  }).catch(() => {
    body.innerHTML = '<div style="color:var(--text2);padding:20px">Could not load profile</div>';
  });
}

function renderUserExpanded(username, data) {
  const body = document.getElementById('team-body-' + username);
  if (!body) return;

  const hosts = [...new Set(
    (data.recent_sessions || [])
      .map(s => (s.provenance || {}).host)
      .filter(Boolean)
  )];

  const ws = data.week_stats;
  let html = '';

  // Week stats
  html += `<div class="tuc-stats">
    <div class="tuc-stat"><div class="tuc-stat-value accent">${ws.sessions}</div><div class="tuc-stat-label">Sessions this week</div></div>
    <div class="tuc-stat"><div class="tuc-stat-value">${ws.messages.toLocaleString()}</div><div class="tuc-stat-label">Messages this week</div></div>
    <div class="tuc-stat"><div class="tuc-stat-value purple">${fmtDur(ws.avg_duration_seconds)}</div><div class="tuc-stat-label">Avg duration</div></div>
    <div class="tuc-stat"><div class="tuc-stat-value">${ws.active_days || 0}<span style="font-size:0.5em;color:var(--text2)"> / 7</span></div><div class="tuc-stat-label">Active days</div></div>
  </div>`;

  // Activity heatmap
  html += `<div class="tuc-section"><h4>Activity</h4><div class="tuc-activity"></div></div>`;

  // Two columns: Projects + Machines
  html += `<div class="tuc-columns">`;

  html += `<div class="tuc-section"><h4>Projects</h4><div class="bar-chart tuc-projects"></div></div>`;

  html += `<div class="tuc-section"><h4>Machines</h4>`;
  if (hosts.length) {
    html += hosts.map(h => `<div class="tuc-host">${esc(h)}</div>`).join('');
  } else {
    html += '<div style="color:var(--text2);font-size:13px">No data</div>';
  }
  html += `</div></div>`;

  // Recent sessions
  const recent = data.recent_sessions || [];
  html += `<div class="tuc-section"><h4>Recent Sessions</h4><div class="recent-list">`;
  html += recent.slice(0, 8).map(s => {
    const topic = s.topic || 'No topic';
    const time = s.first_timestamp ? relativeTime(s.first_timestamp) : '?';
    const dur = formatDuration(s.first_timestamp, s.last_timestamp);
    return `<div class="recent-item" onclick="showDetail('${escAttr(s.session_id)}')">
      <span class="topic" title="${esc(topic)}">${esc(topic)}</span>
      <span class="meta">${s.message_count || 0} msgs &middot; ${dur} &middot; ${time}</span>
    </div>`;
  }).join('') || '<div style="color:var(--text2);font-size:13px">No sessions</div>';
  html += '</div></div>';

  body.innerHTML = html;

  renderActivity(data.heatmap, body.querySelector('.tuc-activity'));

  const projEl = body.querySelector('.tuc-projects');
  const projEntries = Object.entries(data.project_usage || {}).slice(0, 10);
  const max = projEntries.length ? projEntries[0][1] : 1;
  projEl.innerHTML = projEntries.map(([name, count]) =>
    `<div class="bar-row project">
      <span class="name" title="${esc(name)}">${esc(prettyProject(name))}</span>
      <div class="bar" style="width:${Math.max(count / max * 100, 1)}%"></div>
      <span class="count">${count.toLocaleString()}</span>
    </div>`
  ).join('') || '<div style="color:var(--text2);font-size:13px">No data</div>';
}

function showUserProfile(username) { toggleUserCard(username); }
function hideUserProfile() { if (_expandedUser) toggleUserCard(_expandedUser); }
