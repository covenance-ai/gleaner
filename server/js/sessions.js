// --- Sessions tab: list, filters, detail view, transcript viewer ---

let currentSessionId = null;
let transcriptHtmlOriginal = '';

function loadSessions() {
  const user = document.getElementById('filter-user').value.trim();
  const project = document.getElementById('filter-project').value.trim();
  const dateVal = document.getElementById('filter-date').value;
  const limit = document.getElementById('filter-limit').value;
  let url = `/api/sessions?limit=${limit}`;
  if (user) url += `&user=${encodeURIComponent(user)}`;
  if (project) url += `&project=${encodeURIComponent(project)}`;
  if (dateVal) url += `&date=${encodeURIComponent(dateVal)}`;

  // Active filter tags
  const filtersEl = document.getElementById('active-filters');
  let filterHtml = '';
  if (user) filterHtml += `<span class="filter-tag">user: ${esc(user)} <span class="x" onclick="clearFilter('user')">&times;</span></span> `;
  if (project) filterHtml += `<span class="filter-tag">project: ${esc(prettyProject(project))} <span class="x" onclick="clearFilter('project')">&times;</span></span> `;
  if (dateVal) filterHtml += `<span class="filter-tag">date: ${esc(dateVal)} <span class="x" onclick="clearFilter('date')">&times;</span></span> `;
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

function _switchToSessionsTab() {
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelector('nav button[data-tab="sessions"]').classList.add('active');
  document.getElementById('tab-sessions').classList.add('active');
  document.getElementById('detail-view').style.display = 'none';
}

function filterByUser(user) {
  document.getElementById('filter-user').value = user;
  document.getElementById('filter-project').value = '';
  _switchToSessionsTab();
  loadSessions();
}

function filterByProject(project) {
  document.getElementById('filter-project').value = project;
  document.getElementById('filter-user').value = '';
  _switchToSessionsTab();
  loadSessions();
}

function filterByDate(date) {
  document.getElementById('filter-date').value = date;
  _switchToSessionsTab();
  loadSessions();
}

function clearFilter(type) {
  document.getElementById('filter-' + type).value = '';
  loadSessions();
}

// --- Detail view ---

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

      for (const id of Object.keys(pendingTools)) {
        html += renderToolGroup(pendingTools[id], null);
        count++;
      }

      if (!count) html = '<div class="empty">No messages to display</div>';
      container.innerHTML = html;
      transcriptHtmlOriginal = html;
      _wireCollapsible(container);
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

function _wireCollapsible(container) {
  container.querySelectorAll('.tool-header').forEach(header => {
    header.addEventListener('click', () => {
      header.classList.toggle('open');
      header.nextElementSibling.classList.toggle('open');
    });
  });
}

function searchTranscript() {
  const query = document.getElementById('transcript-search').value.trim();
  const container = document.getElementById('detail-transcript');
  const countEl = document.getElementById('match-count');

  if (!query) {
    container.innerHTML = transcriptHtmlOriginal;
    countEl.textContent = '';
    _wireCollapsible(container);
    return;
  }

  const re = new RegExp(escRegex(query), 'gi');
  let matchCount = 0;

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

  container.querySelectorAll('.tool-body').forEach(body => {
    if (body.querySelector('mark')) {
      body.classList.add('open');
      body.previousElementSibling.classList.add('open');
    }
  });
  _wireCollapsible(container);
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
