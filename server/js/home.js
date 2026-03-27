// --- Home tab: personal profile, activity heatmap ---

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
