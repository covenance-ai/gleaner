// --- Team tab: aggregate stats, user cards, project activity ---

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
