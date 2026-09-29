// Pledgebook staff app: accounts, events, live capture, review and follow-up.

const $ = (id) => document.getElementById(id);
const app = $('app');
const state = {
  me: null, events: null, eventsView: 'active', eventsQuery: '',
  event: null, eventId: null, tab: 'live', stream: null,
  mic: { phase: 'idle', audio: null, worklet: null, sink: null, socket: null, source: null, stream: null },
  registerFilter: 'all', registerQuery: '', guestQuery: '', importPreview: null,
  activity: null, settlement: null, settingsData: null, staff: null,
};

const TABS = [
  ['live', 'Live event', 'view'], ['review', 'Needs review', 'review'], ['register', 'Register', 'view'],
  ['guests', 'Guests', 'guests'], ['follow-up', 'Follow-up', 'follow_up'], ['settlement', 'Settlement', 'follow_up'],
  ['activity', 'Activity', 'run'], ['details', 'Event settings', 'run'],
];
const STATE_LABELS = { provisional: 'Provisional', confirmed: 'Confirmed', corrected: 'Rechecked — changed', flagged: 'Needs checking', rejected: 'Rejected', redeemed: 'Paid in full' };
const STATUS_LABELS = { setup: 'Setting up', live: 'Live', paused: 'Paused', ended: 'Ended', archived: 'Archived' };
const OUTCOME_LABELS = { promised: 'Promised a date', paid: 'Says they paid', disputed: 'Disputed', no_answer: 'No answer', wrong_number: 'Wrong number', left_message: 'Left a message', opted_out: 'Opted out', declined: 'Declined', checkout_opened: 'Opened payment', wrong_person: 'Wrong person', incomplete: 'Incomplete' };

// ------------------------------------------------------------------ helpers

const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]));
const money = (value, currency = 'NGN') => (!currency || currency === 'NGN') ? `₦${Number(value || 0).toLocaleString('en-NG')}` : `${currency} ${Number(value || 0).toLocaleString()}`;
const when = (value) => value ? new Date(value).toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '';
const clock = (value) => value ? new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
const can = (permission) => (state.event?.permissions || state.me?.permissions || []).includes(permission);
const guestName = (g) => [g?.title, g?.name].filter(Boolean).join(' ');
const pledgeName = (p) => p.matched_name || p.heard_name || 'Name unclear';
const pledgeAmount = (p) => p.item ? esc(p.item) : (p.amount == null ? 'Amount unclear' : money(p.amount, p.currency));

const toast = (message) => showError(message, 'info');

function showError(message, kind = 'error') {
  const node = $('error');
  node.className = kind === 'info' ? 'error toast' : 'error';
  node.setAttribute('role', kind === 'info' ? 'status' : 'alert');
  node.textContent = message; node.hidden = false;
  clearTimeout(showError.timer); showError.timer = setTimeout(() => { node.hidden = true; }, 9000);
}

async function api(url, options = {}) {
  const headers = { 'X-Pledgebook': '1', ...(options.body && !(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}), ...(options.headers || {}) };
  const body = options.body && !(options.body instanceof FormData) && typeof options.body !== 'string' ? JSON.stringify(options.body) : options.body;
  const response = await fetch(url, { ...options, headers, body, credentials: 'same-origin' });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401 && url !== '/api/me' && !url.startsWith('/api/auth/') && !url.startsWith('/api/invites/')) { state.me = null; go('#/login'); }
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join(' ') : data.detail;
    throw new Error(detail || data.error || `Request failed (${response.status})`);
  }
  return data;
}

function go(hash) { if (location.hash !== hash) location.hash = hash; else route(); }

function formData(form) {
  const data = Object.fromEntries(new FormData(form));
  form.querySelectorAll('input[type=checkbox]').forEach((box) => { data[box.name] = box.checked; });
  return data;
}

// A small modal form so staff never meet a browser prompt() box.
function ask({ title, body = '', fields = '', submit = 'Save', danger = false, wide = false }) {
  const dialog = $('dialog');
  dialog.className = `dialog${wide ? ' wide' : ''}`;
  dialog.innerHTML = `<form method="dialog" class="dialog-form"><h2>${esc(title)}</h2>${body}<div class="form-grid single">${fields}</div>
    <div class="head-actions"><button class="quiet" value="cancel" formnovalidate>${submit ? 'Cancel' : 'Close'}</button>${submit ? `<button class="${danger ? 'danger' : 'primary'}" value="ok">${esc(submit)}</button>` : ''}</div></form>`;
  dialog.returnValue = '';
  dialog.showModal();
  dialog.querySelector('input,select,textarea')?.focus();
  return new Promise((resolve) => {
    dialog.addEventListener('close', () => {
      resolve(dialog.returnValue === 'ok' ? formData(dialog.querySelector('form')) : null);
    }, { once: true });
  });
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch { return false; }
}

// ------------------------------------------------------------------ routing

async function route() {
  const parts = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  const [section, id, tab] = parts;
  if (section === 'invite') return renderInvite(id);
  if (!state.me) {
    try { state.me = await api('/api/me'); } catch { state.me = null; }
  }
  renderAccountNav();
  if (!state.me) {
    closeStream();
    return section === 'signup' ? renderSignup() : renderLogin();
  }
  if (section === 'login' || section === 'signup' || !section) return go('#/events');
  if (!state.me.organisation) return renderNoOrganisation();
  if (section === 'settings') { closeStream(); return renderSettings(id || 'organisation'); }
  if (section === 'events' && id) return openEvent(id, tab || 'live');
  closeStream();
  return renderEvents();
}

window.addEventListener('hashchange', route);

function renderAccountNav() {
  const nav = $('account-nav');
  nav.hidden = !state.me;
  if (!state.me) return;
  $('account-name').textContent = state.me.user.name;
  const select = $('org-switch');
  select.hidden = state.me.memberships.length < 2;
  select.innerHTML = state.me.memberships.map((m) => `<option value="${esc(m.id)}" ${m.id === state.me.organisation?.id ? 'selected' : ''}>${esc(m.name)} (${esc(m.role)})</option>`).join('');
  const section = location.hash.split('/')[1] || 'events';
  nav.querySelectorAll('[data-nav]').forEach((a) => a.classList.toggle('active', a.dataset.nav === section));
  nav.querySelector('[data-nav=settings]').hidden = !state.me.permissions.includes('run');
}

$('org-switch').addEventListener('change', async (event) => {
  try { state.me = await api('/api/me/organisation', { method: 'POST', body: { org_id: event.target.value } }); go('#/events'); }
  catch (error) { showError(error.message); }
});
$('sign-out').addEventListener('click', async () => {
  stopMic(); closeStream();
  await api('/api/auth/logout', { method: 'POST' }).catch(() => {});
  state.me = null; go('#/login');
});

// ------------------------------------------------------------ sign in / up

function authLayout(inner, intro = '') {
  app.innerHTML = `<section class="setup-layout"><div class="setup-intro"><p class="eyebrow">Live pledge operations</p>
    <h1>Every spoken pledge, captured and accountable.</h1>
    <p class="lede">${intro || 'The MC announces each pledge. Pledgebook writes it down, has a person check anything unclear, and follows up until it is paid.'}</p>
    <div class="trust-row"><span>Live transcription</span><span>Human review</span><span>Guest pledge pages</span></div></div>
    <div class="panel setup-card">${inner}</div></section>`;
}

function renderLogin(invite = '', inviteInfo = null) {
  authLayout(`<p class="step-label">Sign in</p><h2>Welcome back</h2>
    ${inviteInfo ? `<p class="notice">Sign in to join <strong>${esc(inviteInfo.organisation)}</strong> as ${esc(inviteInfo.role)}.</p>` : ''}
    <form id="login-form" class="form-grid single">
      <label>Email<input name="email" type="email" autocomplete="email" required></label>
      <label>Password<input name="password" type="password" autocomplete="current-password" required></label>
      <button class="primary full" type="submit">Sign in</button></form>
    <p class="form-note">New here? <a href="${invite ? `#/invite/${esc(invite)}/signup` : '#/signup'}">Create an account</a></p>`);
  $('login-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const result = await api('/api/auth/login', { method: 'POST', body: { ...formData(event.target), invite } });
      state.me = null; go(result.event_id ? `#/events/${result.event_id}/review` : '#/events');
    } catch (error) { showError(error.message); }
  });
}

function renderSignup(invite = '', inviteInfo = null) {
  authLayout(`<p class="step-label">Create account</p><h2>${inviteInfo ? `Join ${esc(inviteInfo.organisation)}` : 'Set up your organisation'}</h2>
    ${inviteInfo ? `<p class="muted">You were invited as <strong>${esc(inviteInfo.role)}</strong>.</p>` : '<p class="muted">You will be the owner. Invite admins and ushers afterwards.</p>'}
    <form id="signup-form" class="form-grid single">
      <label>Your name<input name="name" autocomplete="name" required></label>
      <label>Email<input name="email" type="email" autocomplete="email" value="${esc(inviteInfo?.email || '')}" required></label>
      <label>Password <span class="optional">At least 10 characters</span><input name="password" type="password" minlength="10" autocomplete="new-password" required></label>
      ${inviteInfo ? '' : '<label>Organisation<input name="organisation" placeholder="Church, school or charity name" required></label>'}
      <button class="primary full" type="submit">Create account</button></form>
    <p class="form-note">Already have an account? <a href="${invite ? `#/invite/${esc(invite)}` : '#/login'}">Sign in</a></p>`);
  $('signup-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const result = await api('/api/auth/signup', { method: 'POST', body: { organisation: '', ...formData(event.target), invite } });
      state.me = null; go(result.event_id ? `#/events/${result.event_id}/review` : '#/events');
    } catch (error) { showError(error.message); }
  });
}

async function renderInvite(token) {
  const wantsSignup = location.hash.endsWith('/signup');
  let info;
  try { info = await api(`/api/invites/${encodeURIComponent(token)}`); }
  catch (error) { authLayout(`<h2>Invitation</h2><p class="inline-error">${esc(error.message)}</p><p><a href="#/login">Go to sign in</a></p>`); return; }
  if (!state.me) { try { state.me = await api('/api/me'); } catch { state.me = null; } }
  renderAccountNav();
  if (state.me) {
    authLayout(`<p class="step-label">Invitation</p><h2>Join ${esc(info.organisation)}</h2><p class="muted">You are signed in as ${esc(state.me.user.email)}. Join as ${esc(info.role)}?</p>
      <button id="accept-invite" class="primary full">Join ${esc(info.organisation)}</button>`);
    $('accept-invite').addEventListener('click', async () => {
      try { const result = await api(`/api/invites/${encodeURIComponent(token)}/accept`, { method: 'POST' }); state.me = null; go(result.event_id ? `#/events/${result.event_id}/review` : '#/events'); }
      catch (error) { showError(error.message); }
    });
    return;
  }
  return wantsSignup ? renderSignup(token, info) : renderLogin(token, info);
}

function renderNoOrganisation() {
  app.innerHTML = `<div class="panel narrow"><h2>You are not part of an organisation</h2><p class="muted">Ask an organiser to send you an invitation link, then open it while signed in.</p></div>`;
}

// ----------------------------------------------------------------- my events

async function renderEvents() {
  app.innerHTML = '<div class="panel">Loading events…</div>';
  try { state.events = await api(`/api/events?view=${state.eventsView}&q=${encodeURIComponent(state.eventsQuery)}`); }
  catch (error) { app.innerHTML = `<div class="panel inline-error">${esc(error.message)}</div>`; return; }
  const { events, counts } = state.events;
  const runner = state.me.permissions.includes('run');
  app.innerHTML = `<div class="dashboard-head"><div><div class="event-kicker"><span class="mode-badge">${esc(state.me.organisation.name)}</span><span>${esc(state.me.organisation.role)}</span></div><h1>My events</h1></div>
    ${runner ? '<div class="head-actions"><button id="new-sample" class="quiet">Practice with a sample event</button><button id="new-event" class="primary">New event</button></div>' : ''}</div>
    <div class="toolbar"><div class="segmented">${['active', 'ended', 'archived'].map((v) => `<button data-events-view="${v}" class="${state.eventsView === v ? 'active' : ''}">${v[0].toUpperCase() + v.slice(1)} <span class="count">${counts[v]}</span></button>`).join('')}</div>
    <input id="event-search" class="search" type="search" placeholder="Search events" value="${esc(state.eventsQuery)}"></div>
    <div class="event-grid">${events.length ? events.map(eventCard).join('') : `<div class="panel empty-list">${state.eventsView === 'active' ? (runner ? 'No active events. Create one to start taking pledges.' : 'No active events yet.') : 'Nothing here.'}</div>`}</div>`;
  app.querySelectorAll('[data-events-view]').forEach((b) => b.addEventListener('click', () => { state.eventsView = b.dataset.eventsView; renderEvents(); }));
  const search = $('event-search');
  search.addEventListener('change', () => { state.eventsQuery = search.value; renderEvents(); });
  $('new-event')?.addEventListener('click', newEventDialog);
  $('new-sample')?.addEventListener('click', async () => {
    try { const created = await api('/api/events/sample', { method: 'POST' }); go(`#/events/${created.event.id}/live`); }
    catch (error) { showError(error.message); }
  });
}

function eventCard(e) {
  const progress = e.target_minor ? Math.min(100, (e.pledged / e.target_minor) * 100) : 0;
  return `<a class="panel event-card" href="#/events/${e.id}/live"><div class="section-head"><span class="state ${e.status}">${STATUS_LABELS[e.status]}</span>${e.sample ? '<span class="mode-badge">Sample</span>' : ''}</div>
    <h2>${esc(e.name)}</h2><p class="muted">${esc(e.organisation)} · ${esc(e.event_date)}</p>
    <div class="card-stats"><div><strong>${money(e.pledged)}</strong><span>pledged</span></div><div><strong>${money(e.received)}</strong><span>received</span></div><div><strong>${e.pledges}</strong><span>pledges</span></div><div><strong>${e.guests}</strong><span>guests</span></div></div>
    ${e.target_minor ? `<div class="progress"><span style="width:${progress}%"></span></div>` : ''}${e.flags ? `<p class="flag-note">${e.flags} line${e.flags === 1 ? '' : 's'} need checking</p>` : ''}</a>`;
}

async function newEventDialog() {
  const today = new Date().toISOString().slice(0, 10);
  const data = await ask({
    title: 'New event', submit: 'Create event',
    fields: `<label>Event name<input name="name" required placeholder="Harvest thanksgiving launching"></label>
      <label>Organisation shown to guests<input name="organisation" value="${esc(state.me.organisation.name)}"></label>
      <label>Date<input name="event_date" type="date" value="${today}" required></label>
      <label>Fundraising target <span class="optional">Optional, in naira</span><input name="target" type="number" min="0"></label>`,
  });
  if (!data) return;
  try {
    const created = await api('/api/events', { method: 'POST', body: { ...data, target: Number(data.target || 0) } });
    go(`#/events/${created.event.id}/guests`);
  } catch (error) { showError(error.message); }
}

// -------------------------------------------------------------- event shell

async function openEvent(id, tab) {
  const switching = state.eventId !== id;
  if (switching) { stopMic(); closeStream(); state.event = null; state.activity = null; state.settlement = null; state.importPreview = null; }
  state.eventId = id; state.tab = tab;
  if (!state.event) {
    app.innerHTML = '<div class="panel">Loading event…</div>';
    try { state.event = await api(`/api/events/${id}`); }
    catch (error) { app.innerHTML = `<div class="panel narrow"><h2>Event not available</h2><p class="muted">${esc(error.message)}</p><a class="button-link" href="#/events">Back to my events</a></div>`; return; }
    openStream(id);
  }
  const allowed = TABS.filter(([, , permission]) => can(permission)).map(([key]) => key);
  if (!allowed.includes(tab)) { go(`#/events/${id}/${allowed.includes('review') && state.event.role === 'usher' ? 'review' : 'live'}`); return; }
  renderEventShell();
  if (tab === 'activity') loadActivity(true);
  if (tab === 'settlement') loadSettlement();
}

function renderEventShell() {
  const { event, role } = state.event;
  const flags = state.event.totals.flags;
  app.innerHTML = `<div class="dashboard-head"><div><div class="event-kicker"><a href="#/events" class="back-link">← My events</a><span class="state ${event.status}">${STATUS_LABELS[event.status]}</span>${event.sample ? '<span class="mode-badge">Sample event</span>' : ''}<span>${esc(event.organisation)} · ${esc(event.event_date)}</span></div><h1>${esc(event.name)}</h1></div>
    <div class="head-actions" id="lifecycle">${can('run') ? lifecycleButtons(event.status) : `<span class="muted">Signed in as ${esc(role)}</span>`}</div></div>
    ${event.sample ? `<div class="demo-banner">Sample event: invented guests, deleted automatically ${when(event.expires_at)}. Nothing here is a real pledge.</div>` : ''}
    <div class="workspace"><nav class="tabs" aria-label="Event sections">${TABS.filter(([, , p]) => can(p)).map(([key, label]) => `<a class="tab ${state.tab === key ? 'active' : ''}" href="#/events/${event.id}/${key}">${label}${key === 'review' && flags ? ` <span class="count">${flags}</span>` : ''}</a>`).join('')}</nav>
    <div class="content" id="tab-content"></div></div>`;
  app.querySelectorAll('[data-lifecycle]').forEach((b) => b.addEventListener('click', () => lifecycle(b.dataset.lifecycle)));
  renderTab();
}

function lifecycleButtons(status) {
  const buttons = {
    setup: [['start', 'Go live', 'primary'], ['end', 'End event', 'quiet']],
    live: [['pause', 'Pause', 'quiet'], ['end', 'End event', 'quiet']],
    paused: [['resume', 'Resume', 'primary'], ['end', 'End event', 'quiet']],
    ended: [['reopen', 'Reopen', 'quiet'], ['archive', 'Archive', 'quiet']],
    archived: [['unarchive', 'Restore', 'quiet']],
  }[status] || [];
  return buttons.map(([action, label, style]) => `<button class="${style}" data-lifecycle="${action}">${label}</button>`).join('');
}

async function lifecycle(action) {
  if (action === 'end') {
    const open = state.event.totals.flags;
    const ok = await ask({ title: 'End this event?', submit: 'End event', body: `<p>Listening stops for everyone. ${open ? `<strong>${open} line${open === 1 ? '' : 's'} still need checking</strong> and will stay in the settlement report until resolved.` : 'All lines have been checked.'} You can reopen it later.</p>` });
    if (!ok) return;
  }
  try { state.event = await api(`/api/events/${state.eventId}/lifecycle`, { method: 'POST', body: { action } }); if (action === 'end') go(`#/events/${state.eventId}/settlement`); else renderEventShell(); }
  catch (error) { showError(error.message); }
}

function renderTab() {
  const node = $('tab-content');
  if (!node) return;
  const renderers = { live: renderLive, review: renderReview, register: renderRegister, guests: renderGuests, 'follow-up': renderFollowUp, settlement: renderSettlement, activity: renderActivity, details: renderDetails };
  node.innerHTML = renderers[state.tab]();
  bindTab(node);
}

function refreshView() {
  if (!state.event) return;
  const head = app.querySelector('.tabs');
  if (!head) return renderEventShell();
  // Keep focus and typing in forms; only re-render when the user is not editing.
  const active = document.activeElement;
  if (active && ['INPUT', 'TEXTAREA', 'SELECT'].includes(active.tagName) && $('tab-content')?.contains(active)) return updateLiveNumbers();
  // Never cut off an evidence clip someone is listening to.
  const playing = [...app.querySelectorAll('audio')].find((a) => !a.paused);
  if (playing) { updateLiveNumbers(); playing.addEventListener('pause', refreshView, { once: true }); return; }
  renderEventShell();
}

async function reloadEvent() {
  try { state.event = await api(`/api/events/${state.eventId}`); refreshView(); } catch (error) { showError(error.message); }
}

// ----------------------------------------------------------- live updates

function openStream(id) {
  closeStream();
  const source = new EventSource(`/api/events/${id}/stream`);
  state.stream = source;
  source.onopen = () => setConnection(state.mic.phase === 'listening' ? 'Microphone live' : 'Live updates on', state.mic.phase === 'listening' ? 'listening' : '');
  source.onerror = () => setConnection('Reconnecting…', 'connecting');
  source.onmessage = (message) => {
    const payload = JSON.parse(message.data);
    if (payload.type === 'realtime') return showLiveWords(payload.event);
    if (payload.type === 'deleted') { closeStream(); showError('This event was deleted.'); go('#/events'); return; }
    if (payload.type === 'error') showError(payload.message);
    if (payload.state) { state.event = payload.state; refreshView(); if (state.tab === 'settlement') loadSettlement(); }
  };
}

function closeStream() { state.stream?.close(); state.stream = null; $('connection').hidden = true; }

function setConnection(label, mode = '') {
  const node = $('connection');
  node.hidden = false; node.className = `connection ${mode}`;
  node.innerHTML = `<span class="status-dot"></span><span>${esc(label)}</span>`;
}

function showLiveWords(realtime) {
  if (!realtime?.transcript) return;
  const words = $('live-text'); const status = $('live-status');
  if (words) words.textContent = realtime.transcript;
  if (status) status.textContent = realtime.end_of_turn ? 'Turn heard' : 'Listening';
}

function updateLiveNumbers() {
  const totals = state.event.totals;
  if ($('total')) $('total').textContent = money(totals.pledged, totals.currency);
  if ($('received-total')) $('received-total').textContent = money(totals.received, totals.currency);
}

// -------------------------------------------------------------- live screen

function renderLive() {
  const { event, pledges, totals, guests, usage } = state.event;
  const progress = event.target_minor ? Math.min(100, (totals.pledged / event.target_minor) * 100) : 0;
  const listening = state.mic.phase === 'listening';
  const others = Object.entries(totals.by_currency || {}).filter(([c]) => c !== totals.currency);
  const audioLeft = usage ? Math.max(0, usage.limits.audio_seconds - usage.used.audio_seconds) : null;
  const micCard = can('run') ? `<div class="panel listen-card"><div class="section-head"><div><p class="eyebrow">MC microphone</p><h2>${listening ? 'Capturing the MC' : event.status === 'live' ? 'Ready to listen' : 'Not recording'}</h2></div><span class="state">${esc(state.mic.phase === 'idle' ? (event.status === 'live' ? 'Ready' : STATUS_LABELS[event.status]) : state.mic.phase)}</span></div>
      <button id="mic" class="mic-button ${listening ? 'active' : ''}" ${event.status !== 'live' || ['connecting', 'stopping'].includes(state.mic.phase) ? 'disabled' : ''}><span class="mic-symbol" aria-hidden="true">●</span><span>${listening ? 'Stop listening' : state.mic.phase === 'connecting' ? 'Connecting…' : state.mic.phase === 'stopping' ? 'Finishing…' : 'Start listening'}</span></button>
      <p class="muted">${event.status === 'live' ? 'Audio goes to AssemblyAI for transcription. Each pledge keeps a short clip as evidence.' : event.status === 'setup' ? 'Press Go live when the launching starts.' : event.status === 'paused' ? 'Resume the event to listen again.' : 'This event is closed to new pledges.'}</p>
      <div class="upload-controls"><input id="audio-upload" type="file" accept=".wav,audio/wav" hidden><button id="upload-audio" class="text-button" type="button" ${event.status !== 'live' ? 'disabled' : ''}>Process a WAV recording</button>${event.sample ? `<button id="sample-audio" class="text-button" type="button" ${event.status !== 'live' ? 'disabled' : ''}>Process the sample recording</button>` : ''}<span id="upload-status" class="muted"></span></div>
      ${audioLeft !== null ? `<p class="muted small-print">Listening time left today for your organisation: ${Math.floor(audioLeft / 60)} min</p>` : ''}</div>` : '';
  return `<div class="big-grid"><div class="panel total-card"><p class="eyebrow">Event total</p><div class="totals-row"><div><span class="total-label">Pledged</span><div id="total" class="total">${money(totals.pledged, totals.currency)}</div></div><div><span class="total-label">Received</span><div id="received-total" class="total received">${money(totals.received, totals.currency)}</div></div></div>
      <div class="progress"><span style="width:${progress}%"></span></div><p class="muted">${event.target_minor ? `Target ${money(event.target_minor)} · ${Math.round(progress)}%` : 'No target set'}${others.length ? ` · Also pledged: ${others.map(([c, t]) => money(t.pledged, c)).join(', ')}` : ''}${totals.in_kind ? ` · ${totals.in_kind} in-kind gift${totals.in_kind === 1 ? '' : 's'}` : ''}</p></div>
      ${micCard}</div>
    <div class="screen-columns"><div class="panel"><div class="section-head"><h2>Newest pledge</h2>${pledges[0] ? `<span class="state ${pledges[0].state}">${STATE_LABELS[pledges[0].state]}</span>` : ''}</div><div class="newest ${pledges[0] ? '' : 'empty'}">${pledges[0] ? `${esc(pledgeName(pledges[0]))} <span class="pledge-amount">${pledgeAmount(pledges[0])}</span>${pledges[0].recognised_from_pledge_id ? '<small class="recognised">Recognised from an usher correction</small>' : ''}` : 'Pledges appear here as the MC announces them.'}</div></div>
      <div class="panel"><div class="section-head"><h2>Live reading</h2><span id="live-status" class="state">Waiting</span></div><div id="live-text" class="live-text">Nothing heard yet.</div></div></div>
    ${!guests.length && can('guests') ? `<div class="panel subtle-notice">Add your guest list first so names are recognised. <a href="#/events/${event.id}/guests">Add guests</a></div>` : ''}
    <div class="panel"><div class="section-head"><h2>Recent pledges</h2><span class="muted">Each line keeps its spoken evidence.</span></div><div class="pledge-feed">${pledges.length ? pledges.slice(0, 12).map((p) => pledgeRow(p)).join('') : '<div class="empty-list">No pledges yet.</div>'}</div></div>
    <div class="panel session-summary"><div class="section-head"><h2>Event activity</h2><span class="muted">Updated live</span></div><div class="summary-grid"><div><strong>${pledges.length}</strong><span>Lines captured</span></div><div><strong>${pledges.filter((p) => p.state === 'corrected').length}</strong><span>Recheck corrections</span></div><div><strong>${totals.flags}</strong><span>Need checking</span></div><div><strong>${pledges.filter((p) => p.recognised_from_pledge_id).length}</strong><span>Recognised after a correction</span></div></div></div>`;
}

function pledgeRow(p, actions = '') {
  return `<div class="pledge-row"><div class="pledge-main"><div class="pledge-name">${esc(pledgeName(p))} <span class="state ${p.state}">${STATE_LABELS[p.state]}</span></div>
    <div class="pledge-sub">#${p.id} · ${clock(p.created_at)} · Heard: ${esc(p.live_text || '—')}${p.recheck_text ? ` · Rechecked: ${esc(p.recheck_text)}` : ''}${p.reason ? ` · ${esc(p.reason)}` : ''}</div></div>
    <div class="row-side"><span class="pledge-amount">${pledgeAmount(p)}</span>${p.received ? `<small class="muted">${money(p.received, p.currency)} received</small>` : ''}${actions}</div></div>`;
}

// ------------------------------------------------------------ microphone

async function startMic() {
  if (state.mic.phase === 'listening') return requestStopMic();
  if (state.mic.phase !== 'idle') return;
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) { showError('Microphone access needs HTTPS, or localhost during development.'); return; }
  state.mic.phase = 'connecting'; renderTab(); setConnection('Connecting microphone', 'connecting');
  const mic = state.mic;
  try {
    mic.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, channelCount: 1 } });
    mic.audio = new AudioContext(); await mic.audio.resume(); await mic.audio.audioWorklet.addModule('/static/pcm-worklet.js');
    mic.source = mic.audio.createMediaStreamSource(mic.stream); mic.worklet = new AudioWorkletNode(mic.audio, 'pledgebook-pcm');
    mic.sink = mic.audio.createGain(); mic.sink.gain.value = 0; mic.worklet.connect(mic.sink); mic.sink.connect(mic.audio.destination);
    const socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/events/${state.eventId}/capture`);
    socket.binaryType = 'arraybuffer'; mic.socket = socket;
    socket.onmessage = (message) => {
      const payload = JSON.parse(message.data);
      if (payload.type === 'connection') {
        mic.phase = 'listening'; renderTab(); setConnection('Microphone live', 'listening');
        mic.source.connect(mic.worklet);
        mic.worklet.port.onmessage = (audioMessage) => { if (socket.readyState === WebSocket.OPEN) socket.send(audioMessage.data); };
      } else if (payload.type === 'realtime') showLiveWords(payload.event);
      else if (payload.type === 'notice') { const node = $('live-status'); if (node) node.textContent = payload.message; }
      else if (payload.type === 'stopped' || payload.type === 'error') { showError(payload.message); }
    };
    socket.onerror = () => showError('The live audio connection could not be opened. Check your connection and try again.');
    socket.onclose = () => { if (mic.socket === socket) { stopMic(); renderTab(); setConnection('Live updates on'); } };
  } catch (error) {
    stopMic(); renderTab();
    showError(error.name === 'NotAllowedError' ? 'Microphone permission was denied. Allow it in your browser settings and try again.' : error.name === 'NotFoundError' ? 'No microphone was found on this device.' : `Microphone could not start: ${error.message}`);
  }
}

function requestStopMic() {
  const mic = state.mic;
  if (mic.phase !== 'listening') return;
  mic.phase = 'stopping'; renderTab();
  if (mic.socket?.readyState === WebSocket.OPEN) mic.socket.send(JSON.stringify({ type: 'stop' })); else stopMic();
}

function stopMic() {
  const mic = state.mic;
  const socket = mic.socket; mic.socket = null;
  if (mic.worklet) { mic.worklet.port.onmessage = null; mic.worklet.disconnect(); }
  mic.sink?.disconnect(); mic.source?.disconnect(); mic.stream?.getTracks().forEach((t) => t.stop()); mic.audio?.close();
  if (socket && socket.readyState < WebSocket.CLOSING) socket.close();
  Object.assign(mic, { phase: 'idle', audio: null, worklet: null, sink: null, source: null, stream: null });
}

async function uploadRecording(file) {
  const status = $('upload-status');
  if (status) status.textContent = 'Sending the recording…';
  try {
    const form = new FormData(); form.append('file', file, file.name);
    const result = await api(`/api/events/${state.eventId}/upload`, { method: 'POST', body: form });
    if ($('upload-status')) $('upload-status').textContent = result.message;
  } catch (error) { if ($('upload-status')) $('upload-status').textContent = ''; showError(error.message); }
}

// ------------------------------------------------------------------ review

function renderReview() {
  const { pledges, event } = state.event;
  const flags = pledges.filter((p) => p.state === 'flagged');
  const invite = can('run') ? `<div class="panel usher-share"><div><strong>Bring in an usher</strong><p class="muted">Ushers sign in on their own phone and see only this review queue and the register — never guest phone numbers or emails.</p></div><button class="quiet" data-invite-usher>Invite an usher</button></div>` : '';
  return `${invite}<div class="panel"><div class="section-head"><h2>Needs checking</h2><span class="muted">A person decides anything unclear. Nothing is guessed.</span></div>
    <div class="review-list">${flags.length ? flags.map(reviewRow).join('') : '<div class="empty-list">Nothing needs checking right now.</div>'}</div></div>
    ${event.status === 'archived' ? '<p class="muted">This event is archived. Restore it to make changes.</p>' : ''}`;
}

function reviewRow(p) {
  const earlier = /pledge #(\d+)/.exec(p.reason || '');
  return `<div class="review-row" data-pledge="${p.id}"><div class="review-main"><strong>${esc(p.heard_name || 'Name unclear')} · ${pledgeAmount(p)}</strong>
    <div class="pledge-sub">#${p.id} · ${esc(p.reason || 'Listen to the clip and choose what you heard.')}</div>
    <div class="pledge-sub">Heard: ${esc(p.live_text || '—')}${p.recheck_text ? ` · Rechecked: ${esc(p.recheck_text)}` : ''}</div>
    ${p.has_audio ? `<audio controls preload="none" src="/api/events/${state.eventId}/pledges/${p.id}/audio"></audio>` : '<p class="muted">No audio clip for this line.</p>'}</div>
    <div class="review-actions"><label class="guest-picker">Choose the guest<input list="guest-options" data-guest-search="${p.id}" placeholder="Type a name"></label>
      <button data-review-guest="${p.id}">Assign guest</button><button data-walk-in="${p.id}">New walk-in</button><button data-anonymous="${p.id}">Anonymous</button>
      <button data-fix-amount="${p.id}">Enter amount</button>${earlier ? `<button data-keep="${p.id}">Keep both</button><button data-replace="${p.id}">Replace #${earlier[1]}</button>` : ''}
      <button class="danger-text" data-reject="${p.id}">Not a pledge</button></div></div>`;
}

function guestOptions() {
  return `<datalist id="guest-options">${state.event.guests.map((g) => `<option value="${esc(guestName(g))}" data-id="${g.id}"></option>`).join('')}</datalist>`;
}

function findGuestByLabel(label) {
  const wanted = label.trim().toLowerCase();
  return state.event.guests.find((g) => guestName(g).toLowerCase() === wanted || g.name.toLowerCase() === wanted);
}

async function resolve(pledgeId, body) {
  try { state.event = await api(`/api/events/${state.eventId}/pledges/${pledgeId}/resolve`, { method: 'POST', body }); refreshView(); }
  catch (error) { showError(error.message); }
}

// ---------------------------------------------------------------- register

function renderRegister() {
  const { pledges } = state.event;
  const query = state.registerQuery.toLowerCase();
  const rows = pledges.filter((p) => (state.registerFilter === 'all' || p.state === state.registerFilter) && (!query || `${pledgeName(p)} ${p.live_text} ${p.id}`.toLowerCase().includes(query)));
  const exports = can('export') ? `<a class="button-link" href="/api/events/${state.eventId}/export.csv">Export register CSV</a>` : '';
  return `<div class="panel"><div class="section-head"><h2>Register</h2>${exports}</div>
    <div class="toolbar"><select id="register-filter">${['all', 'provisional', 'confirmed', 'corrected', 'flagged', 'redeemed', 'rejected'].map((s) => `<option value="${s}" ${state.registerFilter === s ? 'selected' : ''}>${s === 'all' ? 'All lines' : STATE_LABELS[s]}</option>`).join('')}</select>
    <input id="register-search" class="search" type="search" placeholder="Search name, words or number" value="${esc(state.registerQuery)}"></div>
    <div class="register-list">${rows.length ? rows.map((p) => pledgeRow(p, can('run') && p.state !== 'rejected' ? `<div class="row-actions"><button class="text-button" data-fix-amount="${p.id}">Change amount</button><button class="text-button" data-change-guest="${p.id}">Change guest</button>${p.received ? '' : `<button class="text-button danger-text" data-reject="${p.id}">Reject</button>`}</div>` : '')).join('') : '<div class="empty-list">No lines match.</div>'}</div></div>`;
}

// ------------------------------------------------------------------ guests

function renderGuests() {
  const { guests, key_terms: keyTerms, removed_guests: removed, event } = state.event;
  const query = state.guestQuery.toLowerCase();
  const rows = guests.filter((g) => !query || `${guestName(g)} ${g.phone || ''} ${g.email || ''} ${g.group_name || ''}`.toLowerCase().includes(query));
  const locked = event.status === 'archived';
  const preview = state.importPreview;
  return `<div class="two-columns"><div class="panel"><div class="section-head"><div><p class="eyebrow">Directory</p><h2>Guests <span class="muted">${guests.length}</span></h2></div></div>
      <div class="subtle-notice"><strong>${keyTerms.included_count} names are being listened for.</strong> ${keyTerms.overflow_count ? `${keyTerms.overflow_count} more are beyond the recognition limit of ${keyTerms.term_limit} and will be matched only after transcription.` : ''}${removed ? ` ${removed} removed guest${removed === 1 ? '' : 's'} kept for past pledges.` : ''}</div>
      <input id="guest-search" class="search wide" type="search" placeholder="Search name, phone, email or group" value="${esc(state.guestQuery)}">
      <div class="guest-list-items">${rows.length ? rows.map((g) => `<div class="guest-row"><span><strong>${esc(guestName(g))}</strong>${g.group_name ? `<small class="muted"> · ${esc(g.group_name)}</small>` : ''}<br><small class="muted">${[g.phone, g.email].filter(Boolean).map(esc).join(' · ') || 'No contact details'}</small></span>
        <span class="row-side"><span class="muted">${g.consent_to_contact ? 'Follow-up allowed' : 'No follow-up consent'}</span>${locked ? '' : `<span class="row-actions"><button class="text-button" data-edit-guest="${g.id}">Edit</button><button class="text-button" data-guest-history="${g.id}">History</button><button class="text-button danger-text" data-remove-guest="${g.id}">Remove</button></span>`}</span></div>`).join('') : `<div class="empty-list">${guests.length ? 'No guests match.' : 'No guests yet. Add them here or import a CSV.'}</div>`}</div></div>
    <div class="panel">${locked ? '<p class="muted">This event is archived. Restore it to change the guest list.</p>' : `<p class="eyebrow">Add guest</p><h2>Who should we listen for?</h2>
      <form id="guest-form" class="form-grid">${guestFields()}<button class="primary full" type="submit">Add guest</button></form>
      <div class="import-box"><p class="eyebrow">Import a list</p><p class="muted">CSV with a <code>name</code> column. Optional: title, phone, email, consent_to_contact (yes/no), group. You will see every row before anything is added.</p>
      <input id="guest-csv" type="file" accept=".csv,text/csv"></div>
      ${preview ? importPreview(preview) : ''}`}</div></div>`;
}

function guestFields(g = {}) {
  return `<label>Title<input name="title" value="${esc(g.title || '')}" placeholder="Mr, Mrs, Chief, Dr…"></label><label>Full name<input name="name" required value="${esc(g.name || '')}"></label>
    <label>Phone<input name="phone" inputmode="tel" value="${esc(g.phone || '')}" placeholder="0803 123 4567"></label><label>Email<input name="email" type="email" value="${esc(g.email || '')}"></label>
    <label>Group<input name="group" value="${esc(g.group_name || '')}" placeholder="Choir, men's fellowship…"></label>
    <label class="check full"><input type="checkbox" name="consent_to_contact" ${g.consent_to_contact ? 'checked' : ''}> This guest agreed to be contacted about their pledge</label>`;
}

function importPreview(preview) {
  const { rows, counts } = preview;
  return `<div class="import-preview"><div class="section-head"><h3>Check the import</h3><span class="muted">${counts.ok} to add · ${counts.duplicate} duplicate · ${counts.invalid} with problems</span></div>
    <div class="table-wrap"><table><thead><tr><th>Row</th><th>Name</th><th>Contact</th><th>Result</th></tr></thead><tbody>${rows.map((r) => `<tr class="${r.status}"><td>${r.row}</td><td>${esc(guestName(r))}</td><td>${esc([r.phone, r.email].filter(Boolean).join(' · '))}${r.consent_to_contact ? ' · consent' : ''}</td><td>${r.status === 'ok' ? 'Will be added' : esc(r.message)}</td></tr>`).join('')}</tbody></table></div>
    <div class="head-actions"><button class="quiet" data-cancel-import>Cancel</button><button class="primary" data-confirm-import ${counts.ok ? '' : 'disabled'}>Add ${counts.ok} guest${counts.ok === 1 ? '' : 's'}</button></div></div>`;
}

// --------------------------------------------------------------- follow-up

function renderFollowUp() {
  const { pledges, guests, follow_up: follow, payments, email_configured: emailOn } = state.event;
  const accepted = pledges.filter((p) => ['confirmed', 'corrected', 'redeemed'].includes(p.state));
  const mode = payments.mode;
  const rows = accepted.map((p) => {
    const guest = guests.find((g) => g.id === p.guest_id);
    const link = follow.links.find((l) => l.pledge_id === p.id && l.active);
    const deliveries = follow.deliveries.filter((d) => d.pledge_id === p.id);
    const calls = follow.calls.filter((c) => c.pledge_id === p.id);
    const payRows = follow.payments.filter((x) => x.pledge_id === p.id && x.status === 'success');
    const outstanding = p.item ? 0 : Math.max(0, (p.amount || 0) - (p.received || 0));
    const history = [...deliveries.map((d) => ({ at: d.created_at, text: `Page ${d.status === 'sent' ? 'emailed' : d.status === 'copied' ? 'link copied' : `prepared for ${d.channel}`}${d.sent_by ? ` by ${d.sent_by}` : ''}${d.status === 'failed' ? ' — failed' : ''}` })),
      ...calls.map((c) => ({ at: c.created_at, text: `${c.kind === 'phone' ? 'Phone call' : c.kind === 'assistant' ? 'Voice assistant (guest)' : 'Guest page'}: ${OUTCOME_LABELS[c.outcome] || c.outcome}${c.promised_date ? ` ${c.promised_date}` : ''}${c.notes ? ` — ${c.notes}` : ''}` })),
      ...payRows.map((x) => ({ at: x.paid_at || x.created_at, text: `Received ${money(x.amount)}` }))].sort((a, b) => (b.at || '').localeCompare(a.at || '')).slice(0, 4);
    let side;
    if (!guest) side = '<span class="muted">Anonymous — no follow-up</span>';
    else if (p.follow_up_stopped) side = '<span class="muted">Guest asked not to be contacted</span>';
    else if (!guest.consent_to_contact) side = `<span class="muted">No follow-up consent</span> <a class="text-button" href="#/events/${state.eventId}/guests">Update guest</a>`;
    else side = `<div class="row-actions"><button class="quiet small" data-send="${p.id}">Send pledge page</button>${guest.phone ? `<a class="quiet small button-link" href="tel:${esc(guest.phone)}">Call ${esc(guest.phone)}</a>` : ''}<button class="text-button" data-log-call="${p.id}">Log call</button>${!p.item && outstanding ? `<button class="text-button" data-offline="${p.id}">Record payment</button>` : ''}${mode !== 'off' && follow.payments.some((x) => x.pledge_id === p.id && ['initialized', 'pending'].includes(x.status)) ? `<button class="text-button" data-verify="${p.id}">Check Paystack</button>` : ''}${link ? `<button class="text-button" data-copy="${esc(link.url)}">Copy link</button><button class="text-button danger-text" data-close-link="${p.id}">Close page</button>` : ''}</div>`;
    return `<div class="pledge-row follow-row"><div class="pledge-main"><div class="pledge-name">${esc(pledgeName(p))} <span class="state ${p.state}">${STATE_LABELS[p.state]}</span></div>
      <div class="pledge-sub">${pledgeAmount(p)}${p.item ? '' : ` · ${money(p.received, p.currency)} received · ${money(outstanding, p.currency)} outstanding`}${link ? ` · page ${link.opened_at ? `opened ${when(link.opened_at)}` : 'not opened yet'}` : ''}</div>
      ${history.length ? `<ul class="history">${history.map((h) => `<li><span>${when(h.at)}</span> ${esc(h.text)}</li>`).join('')}</ul>` : ''}</div><div class="row-side">${side}</div></div>`;
  });
  return `<div class="panel"><div class="section-head"><div><h2>Follow-up</h2><p class="muted">Send each guest a private pledge page. On it they can hear the moment they pledged, pay all or part, choose a date, report a mistake, or talk to the disclosed voice assistant on their own phone. Calls you make from your own phone can be logged here.</p></div>
      <span class="state">${mode === 'live' ? 'Paystack live' : mode === 'test' ? 'Paystack test mode' : 'Online payment off'}</span></div>
    ${mode === 'test' ? '<p class="notice">Paystack is in test mode: checkouts use test cards and no real money moves. Switch to a live key in the server settings to accept real payments.</p>' : ''}
    ${emailOn ? '' : '<p class="subtle-notice">Email sending is not set up on this server, so pages are sent by SMS or WhatsApp from your own phone, or by copying the link.</p>'}
    <div class="register-list">${rows.length ? rows.join('') : '<div class="empty-list">Confirmed pledges appear here.</div>'}</div></div>`;
}

// -------------------------------------------------------------- settlement

function renderSettlement() {
  const data = state.settlement;
  if (!data) return '<div class="panel">Loading settlement…</div>';
  const { rows, counts, totals } = data;
  return `<div class="panel"><div class="section-head"><div><h2>Settlement</h2><p class="muted">What was promised, what has arrived, and who still needs following up.</p></div>${can('export') ? `<a class="button-link" href="/api/events/${state.eventId}/settlement.csv">Export settlement CSV</a>` : ''}</div>
    <div class="summary-grid settlement-grid"><div><strong>${money(totals.confirmed, totals.currency)}</strong><span>Confirmed pledges</span></div><div><strong>${money(totals.received, totals.currency)}</strong><span>Received</span></div><div><strong>${money(Math.max(0, totals.confirmed - totals.received), totals.currency)}</strong><span>Outstanding</span></div><div><strong>${totals.confirmed ? Math.round((totals.received / totals.confirmed) * 100) : 0}%</strong><span>Collected</span></div></div>
    <p class="muted">${counts.fully_paid} paid in full · ${counts.part_paid} part paid · ${counts.unpaid} unpaid · ${counts.in_kind} in-kind · ${counts.needs_checking ? `<strong>${counts.needs_checking} still need checking</strong>` : 'none need checking'}</p>
    <div class="table-wrap"><table><thead><tr><th>Guest</th><th>Pledged</th><th>Received</th><th>Outstanding</th><th>Status</th><th>Promised</th><th>Last contact</th></tr></thead><tbody>
    ${rows.map((r) => `<tr><td>${esc(r.guest)}<br><small class="muted">#${r.pledge_id} · ${esc(r.follow_up)}</small></td><td>${r.item ? esc(r.item) : r.amount == null ? 'Amount unclear' : money(r.amount, r.currency)}</td><td>${r.item ? '—' : money(r.received, r.currency)}</td><td>${r.item || r.amount == null ? '—' : money(r.outstanding, r.currency)}</td><td><span class="state ${r.state}">${STATE_LABELS[r.state]}</span></td><td>${esc(r.promised_date || '')}</td><td>${r.last_contact ? `${when(r.last_contact)}<br><small class="muted">${esc(OUTCOME_LABELS[r.last_outcome] || r.last_outcome || '')}</small>` : '—'}</td></tr>`).join('') || '<tr><td colspan="7" class="empty-list">No pledges yet.</td></tr>'}</tbody></table></div></div>`;
}

async function loadSettlement() {
  try { state.settlement = await api(`/api/events/${state.eventId}/settlement`); if (state.tab === 'settlement') renderTab(); }
  catch (error) { showError(error.message); }
}

// ---------------------------------------------------------------- activity

function renderActivity() {
  const data = state.activity;
  if (!data) return '<div class="panel">Loading activity…</div>';
  return `<div class="panel"><div class="section-head"><div><h2>Activity</h2><p class="muted">Every change, who made it, and when.</p></div>${can('export') ? `<a class="button-link" href="/api/events/${state.eventId}/activity.csv">Export activity CSV</a>` : ''}</div>
    <ol class="activity">${data.rows.map(activityItem).join('') || '<li class="empty-list">No activity yet.</li>'}</ol>${data.more ? '<button class="quiet" data-more-activity>Show older</button>' : ''}</div>`;
}

function activityItem(row) {
  const d = row.details || {};
  const bits = [];
  if (row.pledge_id) bits.push(`pledge #${row.pledge_id}`);
  for (const key of ['name', 'text', 'reason', 'outcome', 'channel', 'status', 'promised_date', 'what_they_said', 'role', 'error']) if (d[key]) bits.push(`${key.replace('_', ' ')}: ${d[key]}`);
  if (d.amount) bits.push(`amount: ${money(d.amount)}`);
  if (d.from !== undefined && d.to !== undefined && typeof d.to !== 'object') bits.push(`${d.from ?? '—'} → ${d.to}`);
  if (d.imported !== undefined) bits.push(`${d.imported} added, ${d.skipped} skipped`);
  if (d.changes) bits.push(`changed: ${Object.keys(d.changes).join(', ') || 'nothing'}`);
  return `<li><time>${when(row.created_at)}</time><div><strong>${esc(row.label)}</strong>${row.actor ? ` <span class="muted">by ${esc(row.actor)}</span>` : ''}<div class="pledge-sub">${esc(bits.join(' · '))}</div></div></li>`;
}

async function loadActivity(reset = false) {
  try {
    const before = !reset && state.activity?.rows.length ? state.activity.rows[state.activity.rows.length - 1].id : '';
    const page = await api(`/api/events/${state.eventId}/activity?limit=100${before ? `&before=${before}` : ''}`);
    state.activity = reset || !state.activity ? page : { rows: [...state.activity.rows, ...page.rows], more: page.more };
    if (state.tab === 'activity') renderTab();
  } catch (error) { showError(error.message); }
}

// ----------------------------------------------------------- event details

function renderDetails() {
  const { event } = state.event;
  return `<div class="two-columns"><div class="panel"><p class="eyebrow">Event details</p><h2>Settings for this event</h2>
      <form id="details-form" class="form-grid"><label class="full">Event name<input name="name" required value="${esc(event.name)}"></label>
      <label>Organisation shown to guests<input name="organisation" value="${esc(event.organisation)}"></label><label>Date<input name="event_date" type="date" required value="${esc(event.event_date)}"></label>
      <label>Target (₦)<input name="target" type="number" min="0" value="${event.target_minor || ''}"></label><span></span>
      <label>Smallest expected pledge (₦) <span class="optional">Lines below are flagged</span><input name="minimum" type="number" min="0" value="${event.min_minor || ''}"></label>
      <label>Largest expected pledge (₦) <span class="optional">Lines above are flagged</span><input name="maximum" type="number" min="0" value="${event.max_minor || ''}"></label>
      <button class="primary full" type="submit" ${event.status === 'archived' ? 'disabled' : ''}>Save changes</button></form></div>
    <div class="panel danger-zone"><p class="eyebrow">Delete</p><h2>Delete this event</h2><p class="muted">Removes the event, guests, pledges, audio and follow-up records permanently. End the event first. Events with payments can only be deleted by an owner. Consider archiving instead, which keeps the records.</p>
      <button class="danger" data-delete-event ${event.status === 'live' ? 'disabled' : ''}>Delete event…</button></div></div>`;
}

// -------------------------------------------------------------- tab events

function bindTab(node) {
  node.insertAdjacentHTML('beforeend', state.tab === 'review' ? guestOptions() : '');
  $('mic')?.addEventListener('click', startMic);
  $('upload-audio')?.addEventListener('click', () => $('audio-upload').click());
  $('audio-upload')?.addEventListener('change', (e) => { if (e.target.files[0]) uploadRecording(e.target.files[0]); e.target.value = ''; });
  $('sample-audio')?.addEventListener('click', async () => {
    try { const r = await api(`/api/events/${state.eventId}/sample-audio`, { method: 'POST' }); if ($('upload-status')) $('upload-status').textContent = r.message; } catch (error) { showError(error.message); }
  });
  $('register-filter')?.addEventListener('change', (e) => { state.registerFilter = e.target.value; renderTab(); });
  $('register-search')?.addEventListener('input', debounce((e) => { state.registerQuery = e.target.value; renderTab(); $('register-search')?.focus(); }));
  $('guest-search')?.addEventListener('input', debounce((e) => { state.guestQuery = e.target.value; renderTab(); const s = $('guest-search'); s?.focus(); s?.setSelectionRange(s.value.length, s.value.length); }));
  $('guest-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    try { await api(`/api/events/${state.eventId}/guests`, { method: 'POST', body: formData(e.target) }); e.target.reset(); await reloadEvent(); }
    catch (error) { showError(error.message); }
  });
  $('guest-csv')?.addEventListener('change', async (e) => {
    const file = e.target.files[0]; if (!file) return;
    try { const form = new FormData(); form.append('file', file, file.name); state.importPreview = await api(`/api/events/${state.eventId}/guests/import/preview`, { method: 'POST', body: form }); renderTab(); }
    catch (error) { showError(error.message); }
  });
  $('details-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const d = formData(e.target);
    try { state.event = await api(`/api/events/${state.eventId}`, { method: 'PATCH', body: { ...d, target: Number(d.target || 0), minimum: Number(d.minimum || 0), maximum: Number(d.maximum || 0) } }); renderEventShell(); }
    catch (error) { showError(error.message); }
  });
}

function debounce(fn, ms = 250) { let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); }; }

document.addEventListener('click', async (event) => {
  const target = event.target.closest('button,[data-copy]');
  if (!target || !app.contains(target)) return;
  const d = target.dataset;
  const pledgeById = (id) => state.event.pledges.find((p) => p.id === Number(id));
  try {
    if (d.reviewGuest) {
      const input = app.querySelector(`[data-guest-search="${d.reviewGuest}"]`);
      const guest = findGuestByLabel(input?.value || '');
      if (!guest) { showError('Type a guest name from the list, or use New walk-in.'); return; }
      return resolve(d.reviewGuest, { action: 'guest', guest_id: guest.id });
    }
    if (d.changeGuest) {
      const data = await ask({ title: 'Change the guest', fields: `<label>Guest<input name="label" list="all-guests" required placeholder="Type a name"></label><datalist id="all-guests">${state.event.guests.map((g) => `<option value="${esc(guestName(g))}"></option>`).join('')}</datalist>` });
      if (!data) return;
      const guest = findGuestByLabel(data.label);
      if (!guest) { showError('Choose a guest from the list.'); return; }
      return resolve(d.changeGuest, { action: 'guest', guest_id: guest.id });
    }
    if (d.walkIn) {
      const data = await ask({ title: 'Add a walk-in guest', submit: 'Add and assign', fields: '<label>Title <span class="optional">Optional</span><input name="walk_in_title" placeholder="Mr, Chief…"></label><label>Full name<input name="walk_in_name" required></label>', body: '<p class="muted">The name is added to the guest list and the live listening list straight away.</p>' });
      if (data) return resolve(d.walkIn, { action: 'walk_in', ...data });
      return;
    }
    if (d.anonymous) return resolve(d.anonymous, { action: 'anonymous' });
    if (d.keep) return resolve(d.keep, { action: 'keep' });
    if (d.replace) return resolve(d.replace, { action: 'replace_earlier' });
    if (d.fixAmount) {
      const p = pledgeById(d.fixAmount);
      const data = await ask({ title: 'Enter the amount', body: '<p class="muted">Enter the amount the recording clearly says, in naira.</p>', fields: `<label>Amount (₦)<input name="amount" type="number" min="1" required value="${p?.amount ?? ''}"></label>` });
      if (data) return resolve(d.fixAmount, { action: 'amount', amount: Number(data.amount) });
      return;
    }
    if (d.reject) {
      const data = await ask({ title: 'Not a pledge?', submit: 'Reject line', danger: true, fields: '<label>Reason<input name="reason" required placeholder="For example: MC was reading the order of service"></label>' });
      if (data) return resolve(d.reject, { action: 'reject', reason: data.reason });
      return;
    }
    if (d.inviteUsher !== undefined) return inviteDialog('usher', state.eventId);
    if (d.editGuest) {
      const guest = state.event.guests.find((g) => g.id === Number(d.editGuest));
      const data = await ask({ title: `Edit ${guestName(guest)}`, fields: guestFields(guest) });
      if (!data) return;
      await api(`/api/events/${state.eventId}/guests/${guest.id}`, { method: 'PATCH', body: data }); return reloadEvent();
    }
    if (d.removeGuest) {
      const guest = state.event.guests.find((g) => g.id === Number(d.removeGuest));
      if (!await ask({ title: `Remove ${guestName(guest)}?`, submit: 'Remove', danger: true, body: '<p>They leave the guest list and the listening list. Pledges they already made keep their name.</p>' })) return;
      await api(`/api/events/${state.eventId}/guests/${guest.id}`, { method: 'DELETE' }); return reloadEvent();
    }
    if (d.guestHistory) {
      const h = await api(`/api/events/${state.eventId}/guests/${d.guestHistory}/history`);
      await ask({ title: guestName(h.guest), submit: '', wide: true, body: `<p class="muted">${h.pledges.length} pledge${h.pledges.length === 1 ? '' : 's'}: ${h.pledges.map((p) => `#${p.id} ${p.item ? esc(p.item) : money(p.amount, p.currency)} (${STATE_LABELS[p.state]})`).join(', ') || 'none'}</p><ol class="activity">${h.history.map(activityItem).join('') || '<li>No history.</li>'}</ol>` });
      return;
    }
    if (d.cancelImport !== undefined) { state.importPreview = null; return renderTab(); }
    if (d.confirmImport !== undefined) {
      const result = await api(`/api/events/${state.eventId}/guests/import`, { method: 'POST', body: { rows: state.importPreview.rows.filter((r) => r.status === 'ok') } });
      state.importPreview = null; state.event = result.state; toast(`${result.imported} guest${result.imported === 1 ? '' : 's'} added.`); return renderEventShell();
    }
    if (d.send) return sendDialog(Number(d.send));
    if (d.logCall) {
      const data = await ask({ title: 'Log a phone call', body: '<p class="muted">Record the result of a call you made from your own phone.</p>', fields: `<label>Outcome<select name="outcome">${['promised', 'paid', 'disputed', 'no_answer', 'left_message', 'wrong_number', 'declined', 'opted_out'].map((o) => `<option value="${o}">${OUTCOME_LABELS[o]}</option>`).join('')}</select></label><label>Promised date <span class="optional">If they promised</span><input name="promised_date" type="date"></label><label>Notes<textarea name="notes" rows="3"></textarea></label>` });
      if (!data) return;
      await api(`/api/events/${state.eventId}/pledges/${d.logCall}/calls`, { method: 'POST', body: data }); return reloadEvent();
    }
    if (d.offline) {
      const p = pledgeById(d.offline);
      const data = await ask({ title: 'Record a payment', body: '<p class="muted">For money received outside Paystack, such as cash or a bank transfer.</p>', fields: `<label>Amount (₦)<input name="amount" type="number" min="1" required value="${Math.max(0, (p.amount || 0) - (p.received || 0))}"></label><label>Method<select name="method"><option value="transfer">Bank transfer</option><option value="cash">Cash</option><option value="pos">POS</option><option value="cheque">Cheque</option><option value="other">Other</option></select></label><label>Note<input name="note" placeholder="Receipt number or bank reference"></label>` });
      if (!data) return;
      await api(`/api/events/${state.eventId}/pledges/${d.offline}/payments/offline`, { method: 'POST', body: { ...data, amount: Number(data.amount) } }); return reloadEvent();
    }
    if (d.verify) {
      const result = await api(`/api/events/${state.eventId}/pledges/${d.verify}/payment/verify`, { method: 'POST' });
      const summary = result.results.map((r) => r.error || (r.status === 'success' ? 'payment received' : `Paystack says ${r.status}`)).join('; ');
      toast(summary || 'No open checkouts to check.'); return reloadEvent();
    }
    if (d.copy) { toast(await copyText(d.copy) ? 'Link copied.' : d.copy); return; }
    if (d.closeLink) {
      if (!await ask({ title: 'Close this pledge page?', submit: 'Close page', danger: true, body: '<p>The guest will no longer be able to open it. You can send a new one later.</p>' })) return;
      await api(`/api/events/${state.eventId}/pledges/${d.closeLink}/link/close`, { method: 'POST' }); return reloadEvent();
    }
    if (d.moreActivity !== undefined) return loadActivity(false);
    if (d.deleteEvent !== undefined) {
      const data = await ask({ title: 'Delete this event permanently?', submit: 'Delete forever', danger: true, body: `<p>Type <strong>${esc(state.event.event.name)}</strong> to confirm.</p>`, fields: '<label>Event name<input name="confirm_name" required autocomplete="off"></label>' });
      if (!data) return;
      await api(`/api/events/${state.eventId}/delete`, { method: 'POST', body: data });
      closeStream(); state.event = null; state.eventId = null; go('#/events');
    }
  } catch (error) { showError(error.message); }
});

async function sendDialog(pledgeId) {
  const p = state.event.pledges.find((x) => x.id === pledgeId);
  const guest = state.event.guests.find((g) => g.id === p.guest_id);
  const channels = [['whatsapp', 'WhatsApp', !!guest.phone], ['sms', 'SMS', !!guest.phone], ['email', 'Email', !!guest.email && state.event.email_configured], ['copy', 'Copy link', true]];
  const data = await ask({
    title: `Send ${guestName(guest)} their pledge page`, submit: 'Continue',
    body: `<p class="muted">The page is private to this pledge and expires automatically. WhatsApp and SMS open on this device with the message ready for you to send.</p>`,
    fields: `<label>How<select name="channel">${channels.map(([v, label, ok]) => `<option value="${v}" ${ok ? '' : 'disabled'}>${label}${ok ? '' : v === 'email' && guest.email ? ' (not set up on this server)' : ' (no contact detail)'}</option>`).join('')}</select></label>`,
  });
  if (!data) return;
  const result = await api(`/api/events/${state.eventId}/pledges/${pledgeId}/deliver`, { method: 'POST', body: data });
  if (result.open) window.open(result.open, '_blank', 'noopener');
  else if (data.channel === 'copy') toast(await copyText(result.url) ? 'Link copied. Paste it into your message.' : result.url);
  else if (result.ok) toast('Email sent.'); else showError(result.error);
  reloadEvent();
}

async function inviteDialog(role, eventId = '') {
  const data = await ask({ title: role === 'usher' ? 'Invite an usher' : 'Invite staff', submit: 'Create invitation', fields: `${eventId ? '' : '<label>Role<select name="role"><option value="usher">Usher — review queue and register only</option><option value="admin">Admin — runs events</option></select></label>'}<label>Email <span class="optional">Optional; if given, only this email can accept</span><input name="email" type="email"></label>` });
  if (!data) return;
  try {
    const invite = await api('/api/organisation/invites', { method: 'POST', body: { role: data.role || role, email: data.email || '', event_id: eventId } });
    await ask({ title: 'Invitation ready', submit: '', body: `<p class="muted">${invite.emailed ? 'We emailed the invitation. ' : ''}Scan the code on the usher's phone, or send them the link. It works once and expires in 7 days.</p><div class="qr">${invite.qr_svg}</div><p class="copy-line"><code>${esc(invite.url)}</code></p><button type="button" class="quiet" data-copy="${esc(invite.url)}">Copy link</button>` });
    if (location.hash.startsWith('#/settings')) renderSettings('staff');
  } catch (error) { showError(error.message); }
}
$('dialog').addEventListener('click', async (event) => {
  const copy = event.target.closest('[data-copy]');
  if (copy) { event.preventDefault(); copy.textContent = await copyText(copy.dataset.copy) ? 'Copied' : 'Copy failed'; }
});

// ---------------------------------------------------------------- settings

async function renderSettings(tab) {
  const owner = state.me.permissions.includes('settings');
  const tabs = [['organisation', 'Organisation'], ...(owner ? [['staff', 'Staff']] : []), ['usage', 'Usage and services']];
  app.innerHTML = `<div class="dashboard-head"><div><div class="event-kicker"><a href="#/events" class="back-link">← My events</a></div><h1>Settings</h1></div></div>
    <div class="workspace"><nav class="tabs">${tabs.map(([k, l]) => `<a class="tab ${tab === k ? 'active' : ''}" href="#/settings/${k}">${l}</a>`).join('')}</nav><div class="content" id="settings-content"><div class="panel">Loading…</div></div></div>`;
  const node = $('settings-content');
  try {
    const data = await api('/api/organisation');
    if (tab === 'organisation') {
      const o = data.organisation;
      node.innerHTML = `<div class="panel"><p class="eyebrow">Organisation</p><h2>${esc(o.name)}</h2>
        <form id="org-form" class="form-grid"><label class="full">Name<input name="name" required value="${esc(o.name)}" ${owner ? '' : 'disabled'}></label>
        <label>Keep event audio for (days after the event ends)<input name="retention_days" type="number" min="7" max="3650" value="${o.retention_days}" ${owner ? '' : 'disabled'}></label>
        <label>Pledge pages expire after (days)<input name="link_expiry_days" type="number" min="1" max="90" value="${o.link_expiry_days}" ${owner ? '' : 'disabled'}></label>
        <p class="muted full">Currency: Nigerian naira (₦). Pledges heard in other currencies are shown separately and are not collected online. Pledge records, payments and the activity log are kept until you delete the event; audio clips are deleted automatically after the period above. Sample events are deleted after 24 hours.</p>
        ${owner ? '<button class="primary full" type="submit">Save</button>' : '<p class="muted full">Only an owner can change these.</p>'}</form></div>`;
      $('org-form')?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const f = formData(e.target);
        try { await api('/api/organisation', { method: 'PATCH', body: { ...f, retention_days: Number(f.retention_days), link_expiry_days: Number(f.link_expiry_days) } }); state.me = await api('/api/me'); renderAccountNav(); toast('Saved.'); }
        catch (error) { showError(error.message); }
      });
    } else if (tab === 'staff' && owner) {
      const staff = await api('/api/organisation/staff');
      node.innerHTML = `<div class="panel"><div class="section-head"><div><p class="eyebrow">Staff</p><h2>People who can use Pledgebook</h2></div><button class="primary" id="invite-staff">Invite</button></div>
        <p class="muted">Owners manage settings and staff. Admins run events, guests and follow-up. Ushers resolve the review queue and see the register, without guest contact details.</p>
        <div class="register-list">${staff.members.map((m) => `<div class="pledge-row"><div><strong>${esc(m.name)}</strong><div class="pledge-sub">${esc(m.email)} · joined ${when(m.created_at)}</div></div><div class="row-actions">${m.id === state.me.user.id ? `<span class="state">${esc(m.role)} (you)</span>` : `<select data-member-role="${m.id}">${['owner', 'admin', 'usher'].map((r) => `<option ${r === m.role ? 'selected' : ''}>${r}</option>`).join('')}</select><button class="text-button danger-text" data-remove-member="${m.id}">Remove</button>`}</div></div>`).join('')}</div>
        <h3>Open invitations</h3><div class="register-list">${staff.invites.map((i) => `<div class="pledge-row"><div><strong>${esc(i.role)}</strong>${i.email ? ` · ${esc(i.email)}` : ''}${i.event_name ? ` · for ${esc(i.event_name)}` : ''}<div class="pledge-sub">expires ${when(i.expires_at)}</div></div><button class="text-button danger-text" data-revoke-invite="${i.id}">Revoke</button></div>`).join('') || '<div class="empty-list">No open invitations.</div>'}</div></div>`;
      $('invite-staff').addEventListener('click', () => inviteDialog('admin'));
      node.querySelectorAll('[data-member-role]').forEach((s) => s.addEventListener('change', async () => { try { await api(`/api/organisation/members/${s.dataset.memberRole}`, { method: 'PATCH', body: { role: s.value } }); } catch (error) { showError(error.message); renderSettings('staff'); } }));
      node.querySelectorAll('[data-remove-member]').forEach((b) => b.addEventListener('click', async () => { if (!await ask({ title: 'Remove this person?', submit: 'Remove', danger: true, body: '<p>They lose access to all events in this organisation immediately.</p>' })) return; try { await api(`/api/organisation/members/${b.dataset.removeMember}`, { method: 'DELETE' }); renderSettings('staff'); } catch (error) { showError(error.message); } }));
      node.querySelectorAll('[data-revoke-invite]').forEach((b) => b.addEventListener('click', async () => { try { await api(`/api/organisation/invites/${b.dataset.revokeInvite}`, { method: 'DELETE' }); renderSettings('staff'); } catch (error) { showError(error.message); } }));
    } else {
      const u = data.usage;
      const row = (label, used, limit, unit = '') => `<div><strong>${used}${unit} / ${limit}${unit}</strong><span>${label}</span><div class="progress"><span style="width:${Math.min(100, (used / Math.max(1, limit)) * 100)}%"></span></div></div>`;
      node.innerHTML = `<div class="panel"><p class="eyebrow">Today (resets at midnight UTC)</p><h2>Usage</h2><div class="summary-grid">
          ${row('Listening', Math.round(u.used.audio_seconds / 60), Math.round(u.limits.audio_seconds / 60), ' min')}${row('Voice assistant conversations', u.used.assistant_sessions, u.limits.assistant_sessions)}${row('New events', u.used.events_created, u.limits.events_created)}${row('Emails', u.used.emails_sent, u.limits.emails_sent)}</div></div>
        <div class="panel"><p class="eyebrow">Services</p><h2>Payments and messages</h2>
          <p><strong>Paystack:</strong> ${data.payments.mode === 'live' ? 'Live — real payments are accepted.' : data.payments.mode === 'test' ? 'Test mode — checkouts use test cards and no real money moves.' : 'Not configured — guests can still promise dates and staff can record offline payments.'}</p>
          <p class="muted">Paystack notification address (set it under Settings → API Keys & Webhooks in your Paystack dashboard):</p><p class="copy-line"><code>${esc(data.payments.webhook_url)}</code> <button class="text-button" data-copy="${esc(data.payments.webhook_url)}">Copy</button></p>
          <p><strong>Email:</strong> ${data.email.configured ? `Sending from ${esc(data.email.from)}.` : 'Not configured. Pledge pages are sent by WhatsApp, SMS or a copied link from staff phones.'}</p>
          <p class="muted">These services are configured on the server by whoever operates this Pledgebook installation.</p></div>`;
    }
  } catch (error) { node.innerHTML = `<div class="panel inline-error">${esc(error.message)}</div>`; }
}

route();

