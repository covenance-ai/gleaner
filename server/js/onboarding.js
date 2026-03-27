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
  apiPost('/api/onboard', { username: obUsername }).then(() => {
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
  apiPost('/api/tokens', { name: nameInput.value.trim() || 'default' }).then(data => {
    obToken = data.token;
    btn.style.display = 'none';
    nameInput.closest('.ob-field').style.display = 'none';
    document.getElementById('ob-token-display').innerHTML = `
      <div class="token-display">
        <code>${esc(obToken)}</code>
        <button class="copy-btn" onclick="copyToClipboard('${escAttr(obToken)}', this)">Copy</button>
      </div>
      <div class="ob-warn">Save this token now \u2014 it will not be shown again.</div>`;
    document.getElementById('ob-setup-block').style.display = '';
    const setupTok = document.getElementById('ob-setup-token');
    if (setupTok) setupTok.textContent = obToken;
    document.getElementById('ob-next-2').style.display = '';
  }).catch(() => {
    btn.disabled = false;
    btn.textContent = 'Generate Token';
  });
}

function obFinish() {
  document.getElementById('onboard-overlay').classList.remove('active');
  showAuthLoading();
  Promise.all([apiFetch('/api/me'), apiFetch('/api/stats')]).then(([me, stats]) => {
    onAuthSuccess(me, stats);
  }).catch(() => { hideAuthLoading(); });
}
