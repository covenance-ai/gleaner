// --- App init: theme, tabs, startup ---

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

function initTabs() {
  document.querySelectorAll('nav button').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
      document.getElementById('detail-view').style.display = 'none';
    });
  });
}

function applyLocalMode() {
  document.querySelectorAll('nav button[data-tab="team"], nav button[data-tab="settings"], .logout-btn')
    .forEach(el => { el.style.display = 'none'; });
}

// --- Bootstrap ---
initTheme();
initTabs();
initAuth();
