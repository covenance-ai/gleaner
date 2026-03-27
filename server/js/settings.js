// --- Settings tab: profile, token management, setup instructions ---

function loadSettings() {
  // Profile card
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

  loadTokenList();
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
      const created = t.created_at ? relativeTime(parseTimestamp(t.created_at)) : '?';
      const lastUsed = t.last_used_at ? relativeTime(parseTimestamp(t.last_used_at)) : 'never';
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
  apiPost('/api/tokens', { name: nameInput.value.trim() || 'default' }).then(data => {
    resultEl.innerHTML = `
      <div class="token-display" style="margin-top:12px">
        <code>${esc(data.token)}</code>
        <button class="copy-btn" onclick="copyToClipboard('${escAttr(data.token)}', this)">Copy</button>
      </div>
      <div class="ob-warn">Save this token now \u2014 it will not be shown again.</div>`;
    nameInput.value = '';
    loadTokenList();
  }).catch(() => {
    resultEl.innerHTML = '<div style="color:var(--red);font-size:13px;margin-top:8px">Failed to create token</div>';
  });
}

function revokeSettingsToken(tokenId) {
  apiDelete('/api/tokens/' + encodeURIComponent(tokenId)).then(() => {
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
