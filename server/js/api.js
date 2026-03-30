// --- API and state ---

const BASE = window.location.pathname.replace(/\/+$/, '');
let TOKEN = localStorage.getItem('gleaner_token') || '';

function apiFetch(path) {
  return fetch(BASE + path, { headers: { 'Authorization': 'Bearer ' + TOKEN } })
    .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });
}

function apiPost(path, body) {
  return fetch(BASE + path, {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(r => {
    if (!r.ok) return r.json().catch(() => ({})).then(e => { throw new Error(e.detail || r.statusText); });
    return r.json();
  });
}

function apiDelete(path) {
  return fetch(BASE + path, {
    method: 'DELETE',
    headers: { 'Authorization': 'Bearer ' + TOKEN },
  }).then(r => {
    if (!r.ok) throw new Error(r.status);
    return r.json();
  });
}

function copyToClipboard(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    const orig = btn.textContent;
    btn.textContent = 'Copied!';
    setTimeout(() => { btn.textContent = orig; }, 1500);
  });
}

function obCopy(id) {
  const el = document.getElementById(id);
  const clone = el.cloneNode(true);
  clone.querySelectorAll('.cb-copy, .cb-label').forEach(n => n.remove());
  copyToClipboard(clone.textContent.trim(), el.querySelector('.cb-copy'));
}
