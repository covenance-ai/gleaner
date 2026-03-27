// --- Authentication: token login, Google Sign-In, onboarding ---

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
    document.getElementById('auth-error').textContent = 'Access denied \u2014 your Google account is not authorized';
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

function _tryLoginWith(me) {
  if (me.onboarding_required) {
    hideAuthLoading();
    document.getElementById('auth-overlay').classList.add('hidden');
    showOnboarding(me);
    return;
  }
  apiFetch('/api/stats').then(stats => onAuthSuccess(me, stats));
}

// --- Init: Google button + auto-login ---
function initAuth() {
  document.getElementById('token-input').addEventListener('keydown', e => { if (e.key === 'Enter') authenticate(); });

  fetch(BASE + '/api/config').then(r => r.json()).then(cfg => {
    // Google Sign-In button
    if (cfg.google_client_id) {
      (function tryInit() {
        if (!window.google?.accounts?.id) { setTimeout(tryInit, 100); return; }
        google.accounts.id.initialize({ client_id: cfg.google_client_id, callback: handleGoogleSignIn });
        google.accounts.id.renderButton(
          document.getElementById('google-signin-btn'),
          { theme: 'outline', size: 'large', width: 320 }
        );
        document.getElementById('auth-divider').style.display = '';
      })();
    }

    // Auto-login
    if (cfg.mock) {
      TOKEN = 'mock';
      showAuthLoading();
      Promise.all([apiFetch('/api/me'), apiFetch('/api/stats')]).then(([me, stats]) => {
        onAuthSuccess(me, stats);
      }).catch(() => { hideAuthLoading(); });
    } else if (TOKEN) {
      showAuthLoading();
      apiFetch('/api/me').then(_tryLoginWith).catch(() => {
        hideAuthLoading(); TOKEN = '';
        localStorage.removeItem('gleaner_token');
        localStorage.removeItem('gleaner_google_user');
      });
    }
  }).catch(() => {});
}
