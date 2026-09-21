/* SPDX-License-Identifier: AGPL-3.0-only */
'use strict';
const $ = id => document.getElementById(id);
let token = sessionStorage.getItem('decrumb-token') || '';
let initialized = false, busy = false, qrURL = '';
const messages = {
  preparing: ['Getting ready', 'Downloading and verifying the Signal helper. First setup can take a few minutes.'],
  setup_error: ['Setup needs attention', 'The Signal helper is not ready yet.'],
  unlinked: ['Connect your Signal account', 'Link Decrumb as another device. Your phone keeps using the regular Signal app.'],
  pairing: ['Scan with your phone', 'Waiting for Signal to finish linking.'],
  starting: ['Connecting to Signal', 'Cleaning will start automatically when the connection is ready.'],
  running: ['Cleaning is running', 'Incoming links are cleaned and saved to your Note to Self.'],
  paused: ['Cleaning is paused', 'Start cleaning when you are ready. This pause survives server restarts.'],
  error: ['Connection needs attention', 'Decrumb will retry automatically. You can also retry now.'],
  stale: ['Connection needs attention', 'The helper has stopped reporting. Decrumb will restart it.'],
  stopped: ['Reconnecting', 'Decrumb is recovering the connection.']
};
function notice(text, error = false) { $('notice').textContent = text; $('notice').hidden = !text; $('notice').classList.toggle('error', error); }
function discardQR() { if (qrURL) URL.revokeObjectURL(qrURL); qrURL = ''; $('qr').removeAttribute('src'); $('qr').hidden = true; }
function lock() {
  token = ''; sessionStorage.removeItem('decrumb-token'); initialized = false;
  $('dashboard').hidden = true; $('login-panel').hidden = false; $('logout').hidden = true;
  $('sample').value = ''; $('preview-result').textContent = ''; discardQR();
  $('diagnostic-report').value = ''; $('diagnostic-preview').hidden = true;
}
async function api(path, data) {
  const response = await fetch('/api/' + path, {method: data === undefined ? 'GET' : 'POST',
    headers: {'Authorization': 'Bearer ' + token, ...(data === undefined ? {} : {'Content-Type': 'application/json'})},
    ...(data === undefined ? {} : {body: JSON.stringify(data)}), cache: 'no-store', credentials: 'same-origin'});
  const result = await response.json();
  if (!response.ok) { if (response.status === 401 && path !== 'login') lock(); throw new Error(result.error || 'Decrumb could not complete the request.'); }
  return result;
}
function rows(id) { return $(id).value.split('\n').map(v => v.trim()).filter(Boolean); }
function cleaning() { return {mode: $('mode').value, baseURLs: rows('sites'), excludedURLs: rows('excluded'), rules: JSON.parse($('rules').value)}; }
function showOptions() {
  $('selected-sites').hidden = $('mode').value !== 'selected';
  $('lifetime-row').hidden = $('cleanup-mode').value !== 'lifetime';
  $('sweep-row').hidden = $('cleanup-mode').value !== 'schedule';
}
function fill(status) {
  $('mode').value = status.settings.mode; $('sites').value = status.settings.baseURLs.join('\n');
  $('excluded').value = (status.settings.excludedURLs || []).join('\n'); $('rules').value = JSON.stringify(status.settings.rules || [], null, 2);
  $('commands').checked = status.phone_commands.enabled; $('sender').checked = status.notes.include_sender;
  $('cleanup-mode').value = status.notes.cleanup_mode; $('lifetime').value = status.notes.lifetime_hours;
  $('sweep').value = status.notes.sweep_hours; $('discard').checked = status.notes.discard_on_pause;
  showOptions(); initialized = true;
}
async function refresh() {
  if (!token || busy) return;
  try {
    const state = await api('status');
    $('dashboard').hidden = false; $('login-panel').hidden = true; $('logout').hidden = false;
    const message = messages[state.state] || ['Checking connection', 'Waiting for the helper.'];
    $('status-title').textContent = message[0]; $('status-detail').textContent = state.state === 'running' && state.settings.mode === 'off' ? 'Connected. Link cleaning is off in your settings.' : message[1];
    $('state').textContent = state.state === 'running' ? (state.settings.mode === 'off' ? 'Cleaning off' : 'Online') : state.state.replace('_', ' ');
    $('service-error').textContent = state.error || ''; $('service-error').hidden = !state.error;
    $('pair').hidden = state.state !== 'unlinked'; $('cancel-pair').hidden = state.state !== 'pairing';
    $('retry-setup').hidden = state.state !== 'setup_error'; $('pairing').hidden = state.state !== 'pairing';
    $('pause').hidden = !state.linked || state.state === 'paused' || state.state === 'preparing';
    $('resume').hidden = !state.linked || !['paused', 'error', 'stale', 'stopped'].includes(state.state);
    $('resume').textContent = state.state === 'paused' ? 'Start cleaning' : 'Retry connection';
    for (const key of ['sent', 'pending', 'uncertain']) $(key).textContent = state.counts[key] || 0;
    $('notes-count').textContent = `${state.note_counts.manageable || 0} notes eligible for management. ${state.note_counts.total || 0} tracked receipts.`;
    if (!initialized) fill(state);
    if (!state.qr_ready) discardQR();
    else if (!qrURL) {
      const response = await fetch('/api/qr', {headers: {'Authorization': 'Bearer ' + token}, cache: 'no-store', credentials: 'same-origin'});
      if (response.ok) { qrURL = URL.createObjectURL(await response.blob()); $('qr').src = qrURL; $('qr').hidden = false; }
    }
  } catch (error) { notice(error.message, true); discardQR(); }
}
async function perform(work) {
  if (busy) return;
  busy = true;
  document.querySelectorAll('button').forEach(button => button.disabled = true);
  try { await work(); } catch (error) { notice(error instanceof SyntaxError ? 'Check the JSON in advanced cleaning rules.' : error.message, true); }
  finally { busy = false; document.querySelectorAll('button').forEach(button => button.disabled = false); await refresh(); }
}
$('login-form').addEventListener('submit', event => { event.preventDefault(); perform(async () => {
  const result = await api('login', {password: $('password').value}); $('password').value = '';
  token = result.token; sessionStorage.setItem('decrumb-token', token); notice('');
}); });
$('logout').addEventListener('click', () => perform(async () => { try { await api('logout', {}); } finally { lock(); notice(''); } }));
for (const action of ['pair', 'cancel-pair', 'retry-setup', 'pause', 'resume', 'cleanup', 'clear-queue']) {
  $(action).addEventListener('click', () => {
    if (action === 'cleanup' && !confirm('Request removal of every eligible note generated by this Decrumb installation? Original messages are unaffected.')) return;
    if (action === 'clear-queue' && !confirm('Discard links waiting to be sent? Already sent notes stay in Signal.')) return;
    perform(async () => { await api(action, {}); notice(action === 'cleanup' ? 'Removal requested. Cleaning must be running to send removal requests.' : action === 'clear-queue' ? 'Queued links cleared.' : ''); });
  });
}
$('settings-form').addEventListener('submit', event => { event.preventDefault(); perform(async () => {
  await api('settings', {settings: cleaning(), phone_commands: {enabled: $('commands').checked}, notes: {
    include_sender: $('sender').checked, cleanup_mode: $('cleanup-mode').value, lifetime_hours: Number($('lifetime').value),
    sweep_hours: Number($('sweep').value), discard_on_pause: $('discard').checked}});
  initialized = false; notice('Settings saved.');
}); });
$('preview-form').addEventListener('submit', event => { event.preventDefault(); perform(async () => {
  const result = await api('preview', {text: $('sample').value, settings: cleaning()});
  $('preview-result').textContent = result.changes.length ? result.changes.map(change => `${change.original}\n→ ${change.cleaned}\nRemoved: ${change.removed.join(', ') || 'nothing'}`).join('\n\n') : 'No supported links found.';
  $('preview-result').hidden = false;
}); });
$('mode').addEventListener('change', showOptions); $('cleanup-mode').addEventListener('change', showOptions);
for (const action of ['diagnostics', 'clear-diagnostics']) {
  $(action).addEventListener('click', () => perform(async () => {
    const report = await api(action, {});
    $('diagnostic-report').value = JSON.stringify(report, null, 2);
    $('diagnostic-preview').hidden = false;
    notice(action === 'clear-diagnostics' ? 'Local error history cleared.' : 'Review the report before sharing.');
  }));
}
$('copy-diagnostics').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText($('diagnostic-report').value);
    notice('Diagnostic report copied. Share it only if you choose.');
  } catch {
    $('diagnostic-report').focus(); $('diagnostic-report').select();
    notice('Report selected. Use your browser’s Copy command.');
  }
});
window.addEventListener('pagehide', discardQR);
refresh(); setInterval(() => { if (!document.hidden) refresh(); }, 3000);
