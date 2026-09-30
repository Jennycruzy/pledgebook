// Pledgebook staff app: public site, accounts, events, live capture, review,
// follow-up, reports and the big screen for the hall.

import { avatar, icon, logo } from './icons.js';

const root = document.getElementById('root');
const state = {
  me: null, events: null, eventsView: 'active', eventsQuery: '',
  event: null, eventId: null, tab: 'live', stream: null, seen: new Set(), lastTotals: {},
  mic: { stage: 'idle', audio: null, worklet: null, sink: null, socket: null, source: null, stream: null, analyser: null, raf: 0 },
  liveWords: '', registerFilter: 'all', registerQuery: '', guestQuery: '', importPreview: null,
  activity: null, settlement: null, connection: 'idle',
};

const TABS = [
  ['live', 'Live console', 'wave', 'view'], ['review', 'Needs review', 'review', 'review'], ['register', 'Register', 'list', 'view'],
  ['guests', 'Guests', 'users', 'guests'], ['follow-up', 'Follow-up', 'send', 'follow_up'], ['settlement', 'Settlement', 'receipt', 'follow_up'],
  ['activity', 'Activity', 'activity', 'run'], ['details', 'Event settings', 'sliders', 'run'],
];
const STATE_LABELS = { provisional: 'Heard', confirmed: 'Confirmed', corrected: 'Rechecked', flagged: 'Needs checking', rejected: 'Rejected', redeemed: 'Paid in full' };
const STATUS_LABELS = { setup: 'Setting up', live: 'Live', paused: 'Paused', ended: 'Ended', archived: 'Archived' };
const OUTCOME_LABELS = { promised: 'Promised a date', paid: 'Says they paid', disputed: 'Disputed', no_answer: 'No answer', wrong_number: 'Wrong number', left_message: 'Left a message', opted_out: 'Opted out', declined: 'Declined', checkout_opened: 'Opened payment', wrong_person: 'Wrong person', incomplete: 'Incomplete' };

// ------------------------------------------------------------------ helpers

const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]));
const money = (value, currency = 'NGN') => (!currency || currency === 'NGN') ? `₦${Number(value || 0).toLocaleString('en-NG')}` : `${currency} ${Number(value || 0).toLocaleString()}`;
const compact = (value) => value >= 1e6 ? `₦${(value / 1e6).toFixed(value % 1e6 ? 1 : 0)}m` : value >= 1e3 ? `₦${Math.round(value / 1e3)}k` : money(value);
const when = (value) => value ? new Date(value).toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '';
const clock = (value) => value ? new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
const longDate = (value) => value ? new Date(`${value}T12:00:00`).toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' }) : '';
const shortDate = (value) => value ? new Date(`${value}T12:00:00`).toLocaleDateString([], { day: 'numeric', month: 'short' }) : '';
const ago = (value) => {
  if (!value) return '';
  const s = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
  if (s < 60) return 'just now'; if (s < 3600) return `${Math.floor(s / 60)} min ago`; if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return when(value);
};
const can = (permission) => (state.event?.permissions || state.me?.permissions || []).includes(permission);
const guestName = (g) => [g?.title, g?.name].filter(Boolean).join(' ');
const pledgeName = (p) => p.matched_name || p.heard_name || 'Name unclear';
const pledgeAmount = (p) => p.item ? esc(p.item) : (p.amount == null ? 'Amount unclear' : money(p.amount, p.currency));
const chip = (st) => `<span class="chip state-${st}">${st === 'live' ? '<i class="dot"></i>' : ''}${esc(STATE_LABELS[st] || STATUS_LABELS[st] || st)}</span>`;
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

function toast(message, kind = 'info') {
  const node = document.createElement('div');
  node.className = `toast ${kind}`;
  node.innerHTML = `${icon(kind === 'error' ? 'alert' : 'checkCircle')}<div>${esc(message)}</div>`;
  $('toasts').append(node);
  setTimeout(() => { node.classList.add('leaving'); setTimeout(() => node.remove(), 260); }, kind === 'error' ? 7000 : 3800);
}
const showError = (message) => toast(message, 'error');

async function api(url, options = {}) {
  const isForm = options.body instanceof FormData;
  const headers = { 'X-Pledgebook': '1', ...(options.body && !isForm ? { 'Content-Type': 'application/json' } : {}), ...(options.headers || {}) };
  const body = options.body && !isForm && typeof options.body !== 'string' ? JSON.stringify(options.body) : options.body;
  const response = await fetch(url, { ...options, headers, body, credentials: 'same-origin' });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401 && url !== '/api/me' && !url.startsWith('/api/auth/') && !url.startsWith('/api/invites/')) { state.me = false; go('#/login'); }
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
async function copyText(text) { try { await navigator.clipboard.writeText(text); return true; } catch { return false; } }

// Count a number up (or down) to its new value, so totals feel alive.
function countUp(node, to, format = money) {
  if (!node) return;
  const from = Number(node.dataset.from ?? to);
  node.dataset.from = to;
  if (from === to || reduced()) { node.textContent = format(to); return; }
  const start = performance.now(); const duration = 900;
  node.classList.remove('flash'); void node.offsetWidth; node.classList.add('flash');
  const step = (now) => {
    const t = Math.min(1, (now - start) / duration); const eased = 1 - Math.pow(1 - t, 3);
    node.textContent = format(Math.round(from + (to - from) * eased));
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
function animateNumbers() {
  document.querySelectorAll('[data-count]').forEach((node) => {
    const key = node.dataset.key; const to = Number(node.dataset.count);
    node.dataset.from = state.lastTotals[key] ?? to;
    countUp(node, to, node.dataset.format === 'plain' ? (v) => v.toLocaleString() : money);
    state.lastTotals[key] = to;
  });
}

// A small modal form so staff never meet a browser prompt() box.
function ask({ title, body = '', fields = '', submit = 'Save', danger = false, wide = false, iconName = '' }) {
  const dialog = $('dialog');
  dialog.className = `dialog${wide ? ' wide' : ''}`;
  dialog.innerHTML = `<form method="dialog" class="dialog-form"><div class="section-title">${iconName ? `<span class="icon-tile">${icon(iconName)}</span>` : ''}<h2>${esc(title)}</h2></div>
    <div class="dialog-body">${body}${fields ? `<div class="form-grid single">${fields}</div>` : ''}</div>
    <div class="dialog-actions"><button class="btn btn-ghost" value="cancel" formnovalidate>${submit ? 'Cancel' : 'Close'}</button>${submit ? `<button class="btn ${danger ? 'btn-danger' : 'btn-primary'}" value="ok">${esc(submit)}</button>` : ''}</div></form>`;
  dialog.returnValue = '';
  dialog.showModal();
  dialog.querySelector('input:not([type=hidden]):not([type=radio]),select,textarea')?.focus();
  return new Promise((resolve) => {
    dialog.addEventListener('close', () => resolve(dialog.returnValue === 'ok' ? formData(dialog.querySelector('form')) : null), { once: true });
  });
}
$('dialog').addEventListener('click', async (event) => {
  const copy = event.target.closest('[data-copy]');
  if (copy) { event.preventDefault(); copy.innerHTML = `${icon('check')} ${await copyText(copy.dataset.copy) ? 'Copied' : 'Copy failed'}`; }
});

function skeleton(rows = 3) {
  return `<div class="card">${'<div class="skeleton sk-line" style="width:40%"></div><div class="skeleton sk-line"></div><div class="skeleton sk-line" style="width:75%"></div>'.repeat(rows)}</div>`;
}
const ART = {
  mic: '<svg class="art" viewBox="0 0 120 90" fill="none"><circle cx="60" cy="45" r="40" fill="var(--brand-soft)"/><rect x="50" y="20" width="20" height="36" rx="10" fill="var(--brand)"/><path d="M40 44a20 20 0 0 0 40 0" stroke="var(--brand)" stroke-width="4" stroke-linecap="round"/><path d="M60 64v10" stroke="var(--brand)" stroke-width="4" stroke-linecap="round"/><path d="M22 40v10M14 36v18M98 40v10M106 36v18" stroke="var(--gold)" stroke-width="4" stroke-linecap="round"/></svg>',
  check: '<svg class="art" viewBox="0 0 120 90" fill="none"><circle cx="60" cy="45" r="40" fill="var(--brand-soft)"/><circle cx="60" cy="45" r="24" fill="var(--brand)"/><path d="m49 45 7 7 14-15" stroke="#fff" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/><circle cx="100" cy="20" r="4" fill="var(--gold)"/><circle cx="18" cy="66" r="3" fill="var(--gold)"/></svg>',
  people: '<svg class="art" viewBox="0 0 120 90" fill="none"><circle cx="60" cy="45" r="40" fill="var(--brand-soft)"/><circle cx="48" cy="38" r="10" fill="var(--brand)"/><path d="M30 66a18 18 0 0 1 36 0" fill="var(--brand)"/><circle cx="74" cy="40" r="8" fill="var(--gold)"/><path d="M60 66a14 14 0 0 1 28 0" fill="var(--gold)"/></svg>',
  receipt: '<svg class="art" viewBox="0 0 120 90" fill="none"><circle cx="60" cy="45" r="40" fill="var(--gold-soft)"/><path d="M42 16h36v58l-6-4-6 4-6-4-6 4-6-4-6 4z" fill="var(--surface)" stroke="var(--gold)" stroke-width="3" stroke-linejoin="round"/><path d="M50 32h20M50 42h20M50 52h12" stroke="var(--gold)" stroke-width="3" stroke-linecap="round"/></svg>',
  calendar: '<svg class="art" viewBox="0 0 120 90" fill="none"><circle cx="60" cy="45" r="40" fill="var(--brand-soft)"/><rect x="36" y="22" width="48" height="46" rx="8" fill="var(--surface)" stroke="var(--brand)" stroke-width="3"/><path d="M36 36h48" stroke="var(--brand)" stroke-width="3"/><circle cx="50" cy="50" r="4" fill="var(--gold)"/><circle cx="62" cy="50" r="4" fill="var(--brand)"/><circle cx="74" cy="50" r="4" fill="var(--brand)"/></svg>',
};
const empty = (art, title, text, action = '') => `<div class="empty">${ART[art] || ''}<h3>${esc(title)}</h3><p>${text}</p>${action}</div>`;

// ------------------------------------------------------------------ routing

async function route() {
  const parts = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  const [section, id, tab] = parts;
  if (section === 'invite') return renderInvite(id, tab === 'signup');
  if (state.me === null) {
    try { state.me = await api('/api/me'); } catch { state.me = false; }
  }
  if (!state.me) {
    stopEverything();
    if (section === 'login') return renderLogin();
    if (section === 'signup') return renderSignup();
    location.replace('/'); return;
  }
  if (!section || section === 'login' || section === 'signup') return go('#/events');
  if (!state.me.organisation) return renderShell(`<div class="card">${empty('people', 'You are not part of an organisation yet', 'Ask an organiser to send you an invitation link, then open it while signed in.')}</div>`);
  if (section === 'settings') { stopEverything(); return renderSettings(id || 'organisation'); }
  if (section === 'events' && id) return openEvent(id, tab || 'live');
  stopEverything();
  return renderEvents();
}
window.addEventListener('hashchange', route);

function stopEverything() { stopMic(); closeStream(); state.event = null; state.eventId = null; }

// --------------------------------------------------------------- public site

const DEMO_LINES = [
  { name: 'Chief Adaeze Nnamdi', amount: 250000, words: 'Chief Adaeze Nnamdi — two hundred and fifty thousand naira! Clap for her!', end: 'ok' },
  { name: 'Engr. Bayo Adekunle', amount: 100000, words: 'Engineer Bayo Adekunle, one hundred thousand naira.', end: 'ok' },
  { name: 'Mrs. Hauwa Sani', amount: null, words: 'Mrs. Hauwa Sani, fifty thousand — sorry, seventy thousand.', end: 'flag' },
  { name: 'Dr. Kunle Martins', amount: 500000, words: 'Dr. Kunle Martins, half a million naira! God bless you, sir.', end: 'ok' },
  { name: 'A daughter of the soil', amount: 200000, words: 'A daughter of the soil, two hundred thousand naira.', end: 'ok' },
];
let previewTimer = 0;

function renderLanding() {
  document.title = 'Pledgebook — every spoken pledge, checked and collected';
  root.innerHTML = `
  <header class="site-nav" id="site-nav"><a class="brand" href="/">${logo(32)} Pledgebook</a>
    <nav><a class="link" href="#how" data-scroll>How it works</a><a class="link" href="#safety" data-scroll>Safety</a><a class="link" href="#guests" data-scroll>For guests</a>
      <a class="btn btn-quiet" href="#/login">Sign in</a><a class="btn btn-primary" href="#/signup">Get started ${icon('arrowRight')}</a></nav></header>
  <main>
    <section class="hero">
      <div>
        <span class="hero-badge"><span class="chip brand">Two-pass</span> Built on AssemblyAI Realtime, Sync and Voice Agent</span>
        <h1>Every pledge called in the hall, <span class="accent">counted and collected.</span></h1>
        <p class="lede">The MC calls it. Pledgebook hears it live, rechecks the exact clip, asks an usher whenever anything is unclear, and follows each guest up until the money arrives.</p>
        <div class="hero-cta"><a class="btn btn-primary btn-lg" href="#/signup">Start your first launching ${icon('arrowRight')}</a><a class="btn btn-ghost btn-lg" href="#how" data-scroll>${icon('play')} See how it works</a></div>
        <div class="hero-proof"><span>${icon('shield')} Nothing credited on a guess</span><span>${icon('wave')} Audio evidence for every line</span><span>${icon('wallet')} Part payments welcome</span></div>
      </div>
      <div class="preview" aria-label="An illustration of a live launching in Pledgebook" role="img">
        <span class="chip gold">Illustrative preview</span>
        <div class="pv-top"><span>Harvest Thanksgiving Launching</span><span class="pv-live"><i></i> Listening</span></div>
        <div class="pv-total"><small>Pledged so far</small><span id="pv-total" class="num">₦1,250,000</span></div>
        <div class="pv-bar"><span id="pv-bar"></span></div>
        <div class="pv-wave">${Array.from({ length: 36 }, (_, i) => `<i style="height:${30 + ((i * 37) % 70)}%;animation-delay:${(i % 9) * -0.12}s"></i>`).join('')}</div>
        <div class="pv-heard" id="pv-heard">…</div>
        <div class="pv-feed" id="pv-feed"></div>
        <div class="pv-float"><div class="t">Private page · Chief Adaeze</div><div class="a">₦250,000</div><div class="bar gold"><span style="width:64%"></span></div><div class="t" style="margin-top:8px">₦160,000 paid · rest promised for Friday</div></div>
      </div>
    </section>
    <section class="section alt" id="how">
      <div class="section-head"><span class="eyebrow">How it works</span><h2>From a shout across the hall to money in the account.</h2><p>Speech does not become financial truth just because it was heard once. Every pledge passes two independent listens, and anything uncertain goes to a person.</p></div>
      <div class="steps">
        <div class="step"><div class="tile">${icon('mic')}</div><h3>Realtime hears the room</h3><p>The MC's microphone streams to AssemblyAI Realtime with your guest list as key terms. Provisional words appear as the service returns them.</p></div>
        <div class="step"><div class="tile">${icon('rotate')}</div><h3>Sync rechecks the clip</h3><p>The exact seconds of speech are rechecked independently with word timings. Agreement confirms the line; disagreement stops it.</p></div>
        <div class="step"><div class="tile">${icon('users')}</div><h3>Ushers settle doubts</h3><p>Unknown names, two amounts in one breath, repeats — an usher listens to the clip on their phone and decides. The name is learned for its next mention.</p></div>
        <div class="step"><div class="tile">${icon('wallet')}</div><h3>Guests pay their way</h3><p>Each guest gets a private page to hear their moment, pay all or part with Paystack, pick a date, or say something is wrong.</p></div>
      </div>
    </section>
    <section class="section" id="safety">
      <div class="split">
        <div><span class="eyebrow">Built for money, not transcripts</span><h2 class="split-title">Rules that hold even when the room is loud.</h2>
          <p class="muted split-lede">We made 21 deliberate attempts to break these rules on the live service. Every one was refused.</p>
          <ul class="ticks"><li>${icon('check')} Ushers never see guest phone numbers or emails.</li><li>${icon('check')} The voice assistant cannot change an amount — the tool does not exist.</li><li>${icon('check')} A payment is counted exactly once, even when Paystack notifies twice.</li><li>${icon('check')} A guest only hears audio when nobody else's name is in the clip.</li></ul></div>
        <div class="rules single">
          <div class="rule">${icon('shield')}<div><h3>Two passes, one ledger</h3><p>Realtime and Sync must agree on the guest and amount before a line is confirmed.</p></div></div>
          <div class="rule">${icon('flag')}<div><h3>Flags, never guesses</h3><p>An amount spoken before a name, a self-correction, a stranger's name — each becomes a question for a person.</p></div></div>
          <div class="rule">${icon('wave')}<div><h3>Evidence you can replay</h3><p>Every line keeps the clip of the exact words, the live reading and the recheck, side by side.</p></div></div>
          <div class="rule">${icon('activity')}<div><h3>A full activity trail</h3><p>Every correction, message and payment is logged with who did it and when.</p></div></div>
        </div>
      </div>
    </section>
    <section class="section alt" id="guests">
      <div class="split">
        <div class="phone" aria-hidden="true"><div class="phone-screen"><div class="ps-head"><small>St. Luke's Parish · Harvest launching</small><h4>Thank you, Chief Adaeze Nnamdi</h4><div class="amt">₦250,000</div></div>
          <div class="ps-body"><div class="ps-card"><b>The moment you pledged</b><div class="wave-player mini"><span class="play">${icon('play')}</span><div class="wave-bars">${Array.from({ length: 26 }, (_, i) => `<i class="${i < 9 ? 'on' : ''}" style="height:${25 + ((i * 53) % 70)}%"></i>`).join('')}</div></div></div>
          <div class="ps-card"><b>Pay now</b><div class="gp-chips"><button class="on" tabindex="-1">Full ₦250,000</button><button tabindex="-1">Half</button></div></div>
          <div class="ps-card"><b>Talk it through</b><p class="muted tiny">A clearly disclosed voice assistant on your own phone.</p></div></div></div></div>
        <div><span class="eyebrow gold">For your guests</span><h2 class="split-title">A private page, not a pressure call.</h2>
          <p class="muted split-lede">Send it by WhatsApp, SMS or email. Guests hear the moment they pledged, pay in parts when they need to, or tell you if something was misheard. No automated calls.</p>
          <ul class="ticks"><li>${icon('check')} Paystack checkout with part payments</li><li>${icon('check')} Choose a date to pay, or stop reminders</li><li>${icon('check')} A voice assistant that always says it is automated</li></ul></div>
      </div>
    </section>
  </main>
  <section class="cta-band"><div><h2>Your next launching deserves a ledger you can trust.</h2><p>Set up your organisation in a minute. Rehearse with a sample launching before your big day.</p></div><a class="btn btn-gold btn-lg" href="#/signup">Create your organisation ${icon('arrowRight')}</a></section>
  <footer class="site-foot"><a class="brand" href="/">${logo(24)} Pledgebook</a><span>Speech by AssemblyAI · Payments by Paystack · Audio deleted on your schedule</span></footer>`;
  const nav = $('site-nav');
  addEventListener('scroll', () => nav?.classList.toggle('scrolled', scrollY > 8), { passive: true });
  root.querySelectorAll('[data-scroll]').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); document.querySelector(a.getAttribute('href'))?.scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth' }); }));
  runPreview();
}

function runPreview() {
  clearTimeout(previewTimer);
  let index = 0; let total = 1250000;
  const tick = async () => {
    const feed = $('pv-feed'); const heard = $('pv-heard');
    if (!feed || !heard) return;
    const line = DEMO_LINES[index % DEMO_LINES.length]; index += 1;
    heard.textContent = '';
    for (const word of line.words.split(' ')) { if (!$('pv-heard')) return; heard.textContent += `${word} `; await new Promise((r) => setTimeout(r, reduced() ? 0 : 110)); }
    const row = document.createElement('div');
    row.className = 'pv-row';
    row.innerHTML = `${avatar(line.name, 'sm')}<span class="who">${esc(line.name)}</span><span class="amt num">${line.amount ? compact(line.amount) : '—'}</span><span class="st prov">Heard</span>`;
    feed.prepend(row);
    while (feed.children.length > 3) feed.lastElementChild.remove();
    await new Promise((r) => setTimeout(r, 1300));
    const st = row.querySelector('.st');
    if (line.end === 'ok') {
      st.className = 'st ok'; st.textContent = 'Confirmed';
      const node = $('pv-total'); if (node) { node.dataset.from = total; total += line.amount; countUp(node, total); }
      const bar = $('pv-bar'); if (bar) bar.style.width = `${Math.min(96, 20 + (total / 4000000) * 76)}%`;
    } else { st.className = 'st flag'; st.textContent = 'Needs checking'; }
    if (total > 3200000) total = 1250000;
    previewTimer = setTimeout(tick, 1600);
  };
  previewTimer = setTimeout(tick, 500);
}

// ------------------------------------------------------------- sign in / up

function authLayout(inner) {
  root.innerHTML = `<div class="auth"><aside class="auth-side"><a class="brand" href="/">${logo(32)} Pledgebook</a>
    <div><h2>Every pledge called in the hall, counted and collected.</h2>
      <ul><li>${icon('mic')} Live transcription with your guest list</li><li>${icon('rotate')} An independent recheck of every clip</li><li>${icon('users')} Ushers settle anything unclear from their phones</li><li>${icon('wallet')} Private guest pages with part payments</li></ul></div>
    <p class="auth-foot">Speech by AssemblyAI · Payments by Paystack</p></aside>
    <main class="auth-main"><div class="auth-card">${inner}</div></main></div>`;
}

function renderLogin(invite = '', info = null) {
  document.title = 'Sign in · Pledgebook';
  authLayout(`<a class="brand auth-brand" href="/">${logo(28)} Pledgebook</a>
    <div><h1>Welcome back</h1><p class="muted">${info ? `Sign in to join <b>${esc(info.organisation)}</b> as ${esc(info.role)}.` : 'Sign in to your organisation.'}</p></div>
    <form id="login-form" class="form-grid single">
      <label class="field">Email<input name="email" type="email" autocomplete="email" required></label>
      <label class="field">Password<input name="password" type="password" autocomplete="current-password" required></label>
      <button class="btn btn-primary btn-lg btn-block" type="submit">Sign in ${icon('arrowRight')}</button></form>
    <p class="switch">New to Pledgebook? <a href="${invite ? `#/invite/${esc(invite)}/signup` : '#/signup'}">Create an account</a></p>`);
  $('login-form').addEventListener('submit', async (event) => {
    event.preventDefault(); const button = event.target.querySelector('button'); button.disabled = true;
    try {
      const result = await api('/api/auth/login', { method: 'POST', body: { ...formData(event.target), invite } });
      state.me = null; go(result.event_id ? `#/events/${result.event_id}/review` : '#/events');
    } catch (error) { showError(error.message); button.disabled = false; }
  });
}

function renderSignup(invite = '', info = null) {
  document.title = 'Create your account · Pledgebook';
  authLayout(`<a class="brand auth-brand" href="/">${logo(28)} Pledgebook</a>
    <div><h1>${info ? `Join ${esc(info.organisation)}` : 'Set up your organisation'}</h1><p class="muted">${info ? `You were invited as <b>${esc(info.role)}</b>.` : 'You will be the owner. Invite admins and ushers afterwards.'}</p></div>
    <form id="signup-form" class="form-grid single">
      <label class="field">Your name<input name="name" autocomplete="name" required></label>
      <label class="field">Email<input name="email" type="email" autocomplete="email" value="${esc(info?.email || '')}" required></label>
      <label class="field">Password <span class="hint">At least 10 characters</span><input name="password" type="password" minlength="10" autocomplete="new-password" required></label>
      ${info ? '' : '<label class="field">Organisation<input name="organisation" placeholder="St. Luke\'s Parish, Lekki" required></label>'}
      <button class="btn btn-primary btn-lg btn-block" type="submit">Create account ${icon('arrowRight')}</button></form>
    <p class="switch">Already have an account? <a href="${invite ? `#/invite/${esc(invite)}` : '#/login'}">Sign in</a></p>`);
  $('signup-form').addEventListener('submit', async (event) => {
    event.preventDefault(); const button = event.target.querySelector('button'); button.disabled = true;
    try {
      const result = await api('/api/auth/signup', { method: 'POST', body: { organisation: '', ...formData(event.target), invite } });
      state.me = null; go(result.event_id ? `#/events/${result.event_id}/review` : '#/events');
    } catch (error) { showError(error.message); button.disabled = false; }
  });
}

async function renderInvite(token, wantsSignup) {
  let info;
  try { info = await api(`/api/invites/${encodeURIComponent(token)}`); }
  catch (error) { authLayout(`<div>${empty('people', 'This invitation cannot be used', esc(error.message), '<a class="btn btn-ghost" href="#/login">Go to sign in</a>')}</div>`); return; }
  if (state.me === null) { try { state.me = await api('/api/me'); } catch { state.me = false; } }
  if (state.me) {
    authLayout(`<div class="section-title"><span class="icon-tile">${icon('userPlus')}</span><h1>Join ${esc(info.organisation)}</h1></div>
      <p class="muted">You are signed in as ${esc(state.me.user.email)}. Join as <b>${esc(info.role)}</b>?</p>
      <button id="accept-invite" class="btn btn-primary btn-lg btn-block">Join ${esc(info.organisation)}</button>`);
    $('accept-invite').addEventListener('click', async () => {
      try { const result = await api(`/api/invites/${encodeURIComponent(token)}/accept`, { method: 'POST' }); state.me = null; go(result.event_id ? `#/events/${result.event_id}/review` : '#/events'); }
      catch (error) { showError(error.message); }
    });
    return;
  }
  return wantsSignup ? renderSignup(token, info) : renderLogin(token, info);
}

// -------------------------------------------------------------- app shell

function renderShell(inner, section = 'events') {
  clearTimeout(previewTimer);
  const me = state.me;
  const orgs = me.memberships.map((m) => `<button data-switch-org="${esc(m.id)}" class="${m.id === me.organisation?.id ? 'current' : ''}">${icon('building')} <span>${esc(m.name)}</span> <span class="faint tiny push">${esc(m.role)}</span></button>`).join('');
  root.innerHTML = `<header class="topbar"><a class="brand" href="#/events">${logo(30)} <span class="brand-word">Pledgebook</span></a>
    <nav class="nav-links"><a href="#/events" class="${section === 'events' ? 'active' : ''}">${icon('calendar')} <span>Events</span></a>${me.permissions.includes('run') ? `<a href="#/settings" class="${section === 'settings' ? 'active' : ''}">${icon('sliders')} <span>Settings</span></a>` : ''}</nav>
    <span class="spacer"></span><span id="conn" class="conn" hidden><i></i><span>Ready</span></span>
    <div class="menu"><button class="menu-button" id="menu-button" aria-haspopup="true" aria-expanded="false">${avatar(me.user.name, 'sm')}<span class="who"><b>${esc(me.user.name)}</b><span>${esc(me.organisation?.name || '')}</span></span>${icon('chevronDown')}</button>
      <div class="menu-list" id="menu-list" hidden><div class="label">Organisations</div>${orgs}<hr>${me.permissions.includes('run') ? `<a href="#/settings">${icon('sliders')} Settings</a>` : ''}<button data-theme-toggle>${icon('sparkles')} Light or dark</button><button data-sign-out>${icon('logout')} Sign out</button></div></div></header>
  <main class="page" id="page">${inner}</main>`;
  setConnection(state.connection);
}
function closeMenu() { const list = $('menu-list'); if (list) { list.hidden = true; $('menu-button')?.setAttribute('aria-expanded', 'false'); } }

function setConnection(kind, label) {
  state.connection = kind;
  const node = $('conn'); if (!node) return;
  const labels = { idle: 'Ready', on: 'Live updates on', rec: 'Microphone live', wait: 'Reconnecting…' };
  node.hidden = !state.eventId;
  node.className = `conn ${kind}`;
  node.querySelector('span').textContent = label || labels[kind] || '';
}

// ----------------------------------------------------------------- my events

async function renderEvents() {
  document.title = 'Events · Pledgebook';
  const head = (actions = '') => `<div class="page-head"><div><div class="meta">${icon('building')} ${esc(state.me.organisation.name)} · ${esc(state.me.organisation.role)}</div><h1>${greeting()}, ${esc(state.me.user.name.split(' ')[0])}</h1></div>${actions}</div>`;
  renderShell(`${head()}${skeleton(2)}`);
  try { state.events = await api(`/api/events?view=${state.eventsView}&q=${encodeURIComponent(state.eventsQuery)}`); }
  catch (error) { $('page').innerHTML = `<div class="card">${empty('calendar', 'Events could not load', esc(error.message))}</div>`; return; }
  const { events, counts } = state.events;
  const runner = state.me.permissions.includes('run');
  const showNew = runner && state.eventsView === 'active';
  $('page').innerHTML = `${head(runner ? `<div class="actions"><button id="new-sample" class="btn btn-ghost">${icon('sparkles')} Rehearse with a sample</button><button id="new-event" class="btn btn-primary">${icon('plus')} New event</button></div>` : '')}
    ${runner && !counts.active && !counts.ended && !counts.archived ? `<div class="card onboard"><div><span class="eyebrow">Getting started</span><h2>Ready your first launching in three steps</h2></div>
      <ol class="onboard-steps"><li><span class="icon-tile">${icon('sparkles')}</span><div><b>Rehearse</b><p class="muted small">Run a sample launching with a real recording and see flags, reviews and pledge pages.</p></div></li>
      <li><span class="icon-tile">${icon('users')}</span><div><b>Add your guests</b><p class="muted small">Create the event and import your guest list so names are heard correctly.</p></div></li>
      <li><span class="icon-tile">${icon('userPlus')}</span><div><b>Invite your ushers</b><p class="muted small">They settle anything unclear from their own phones during the event.</p></div></li></ol></div>` : ''}
    <div class="toolbar"><div class="segmented">${['active', 'ended', 'archived'].map((v) => `<button data-events-view="${v}" class="${state.eventsView === v ? 'active' : ''}">${v[0].toUpperCase() + v.slice(1)} <span class="faint">${counts[v]}</span></button>`).join('')}</div>
      <div class="search-box">${icon('search')}<input id="event-search" class="input" type="search" placeholder="Search events" value="${esc(state.eventsQuery)}"></div></div>
    <div class="event-grid">${events.map(eventCard).join('')}${showNew ? `<button class="new-card" id="new-event-card"><span class="tile">${icon('plus')}</span><b>Plan a new launching</b><span class="small">Add guests now, go live on the day.</span></button>` : ''}</div>
    ${!events.length && !showNew ? `<div class="card">${empty('calendar', 'Nothing here yet', state.eventsView === 'active' ? 'Your organiser has not created an event yet.' : 'Events you end or archive will appear here.')}</div>` : ''}`;
  root.querySelectorAll('[data-events-view]').forEach((b) => b.addEventListener('click', () => { state.eventsView = b.dataset.eventsView; renderEvents(); }));
  $('event-search').addEventListener('change', (e) => { state.eventsQuery = e.target.value; renderEvents(); });
  $('new-event')?.addEventListener('click', newEventDialog);
  $('new-event-card')?.addEventListener('click', newEventDialog);
  $('new-sample')?.addEventListener('click', async () => {
    try { const created = await api('/api/events/sample', { method: 'POST' }); toast('Sample launching ready. Go live and play the sample recording.'); go(`#/events/${created.event.id}/live`); } catch (error) { showError(error.message); }
  });
}
function greeting() { const h = new Date().getHours(); return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'; }

function eventCard(e) {
  const progress = e.target_minor ? Math.min(100, (e.pledged / e.target_minor) * 100) : 0;
  const collected = e.pledged ? Math.round((e.received / e.pledged) * 100) : 0;
  return `<a class="event-card" href="#/events/${e.id}/${e.status === 'ended' || e.status === 'archived' ? 'settlement' : 'live'}">
    <div class="row">${chip(e.status)}${e.sample ? '<span class="chip gold">Sample</span>' : ''}<span class="spacer"></span>${e.flags ? `<span class="chip amber">${icon('flag')} ${e.flags}</span>` : ''}</div>
    <div><h3>${esc(e.name)}</h3><p class="muted small">${esc(e.organisation)} · ${longDate(e.event_date)}</p></div>
    <div class="stats"><div><b class="num">${money(e.pledged)}</b><span>pledged</span></div><div><b class="num">${money(e.received)}</b><span>received · ${collected}%</span></div></div>
    ${e.target_minor ? `<div><div class="row small muted between"><span>Target ${money(e.target_minor)}</span><span>${Math.round(progress)}%</span></div><div class="bar"><span style="width:${progress}%"></span></div></div>` : `<div class="row small muted">${icon('users')} ${plural(e.guests, 'guest')} · ${plural(e.pledges, 'line')}</div>`}</a>`;
}

async function newEventDialog() {
  const today = new Date().toISOString().slice(0, 10);
  const data = await ask({
    title: 'Plan a new event', submit: 'Create event', iconName: 'calendar',
    fields: `<label class="field">Event name<input name="name" required placeholder="Harvest Thanksgiving Launching"></label>
      <label class="field">Organisation shown to guests<input name="organisation" value="${esc(state.me.organisation.name)}"></label>
      <div class="form-grid"><label class="field">Date<input name="event_date" type="date" value="${today}" required></label>
      <label class="field">Target <span class="hint">Optional, ₦</span><input name="target" type="number" min="0" inputmode="numeric"></label></div>`,
  });
  if (!data) return;
  try { const created = await api('/api/events', { method: 'POST', body: { ...data, target: Number(data.target || 0) } }); toast('Event created. Add your guests next.'); go(`#/events/${created.event.id}/guests`); }
  catch (error) { showError(error.message); }
}

// -------------------------------------------------------------- event shell

async function openEvent(id, tab) {
  if (state.eventId !== id) { stopMic(); closeStream(); state.event = null; state.activity = null; state.settlement = null; state.importPreview = null; state.seen = new Set(); state.lastTotals = {}; state.liveWords = ''; }
  state.eventId = id; state.tab = tab;
  if (!state.event) {
    if (tab !== 'screen') renderShell(`${skeleton(1)}<div class="gap"></div>${skeleton(3)}`);
    try { state.event = await api(`/api/events/${id}`); }
    catch (error) { state.eventId = null; renderShell(`<div class="card">${empty('calendar', 'This event is not available', esc(error.message), '<a class="btn btn-ghost" href="#/events">Back to your events</a>')}</div>`); return; }
    state.event.pledges.forEach((p) => state.seen.add(p.id));
    openStream(id);
  }
  if (tab === 'screen') return renderBigScreen();
  const allowed = TABS.filter(([, , , permission]) => can(permission)).map(([key]) => key);
  if (!allowed.includes(tab)) { go(`#/events/${id}/${state.event.role === 'usher' ? 'review' : 'live'}`); return; }
  renderEventShell();
  if (tab === 'activity') loadActivity(true);
  if (tab === 'settlement') loadSettlement();
}

function renderEventShell() {
  if (state.tab === 'screen') return renderBigScreen();
  const { event, totals } = state.event;
  document.title = `${event.name} · Pledgebook`;
  const flags = totals.flags;
  renderShell(`<div class="page-head"><div><div class="meta"><a class="crumb" href="#/events">${icon('arrowLeft')} Events</a><span class="faint">/</span>${chip(event.status)}${event.sample ? '<span class="chip gold">Sample</span>' : ''}<span>${esc(event.organisation)} · ${longDate(event.event_date)}</span></div><h1>${esc(event.name)}</h1></div>
    <div class="actions"><a class="btn btn-ghost" href="#/events/${event.id}/screen" title="Show totals on the projector">${icon('monitor')} Big screen</a>${can('run') ? lifecycleButtons(event.status) : `<span class="chip">${icon('lock')} ${esc(state.event.role)}</span>`}</div></div>
    ${event.sample ? `<div class="banner">${icon('sparkles')}<span>Rehearsal with invented guests. It deletes itself ${when(event.expires_at)} — nothing here is a real pledge.</span></div>` : ''}
    <div class="workspace"><nav class="side-nav" aria-label="Event sections">${TABS.filter(([, , , p]) => can(p)).map(([key, label, ic], i) => `${i === 3 ? '<div class="sep"></div>' : ''}<a class="${state.tab === key ? 'active' : ''}" href="#/events/${event.id}/${key}">${icon(ic)} ${label}${key === 'review' && flags ? ` <span class="count">${flags}</span>` : ''}</a>`).join('')}</nav>
    <div class="content" id="tab-content"></div></div>`, 'events');
  root.querySelectorAll('[data-lifecycle]').forEach((b) => b.addEventListener('click', () => lifecycle(b.dataset.lifecycle)));
  renderTab();
}

function lifecycleButtons(status) {
  const buttons = {
    setup: [['start', 'Go live', 'btn-primary', 'zap'], ['end', 'End', 'btn-ghost', 'stop']],
    live: [['pause', 'Pause', 'btn-ghost', 'pause'], ['end', 'End event', 'btn-ghost', 'stop']],
    paused: [['resume', 'Resume', 'btn-primary', 'play'], ['end', 'End event', 'btn-ghost', 'stop']],
    ended: [['reopen', 'Reopen', 'btn-ghost', 'rotate'], ['archive', 'Archive', 'btn-ghost', 'archive']],
    archived: [['unarchive', 'Restore', 'btn-ghost', 'rotate']],
  }[status] || [];
  return buttons.map(([action, label, style, ic]) => `<button class="btn ${style}" data-lifecycle="${action}">${icon(ic)} ${label}</button>`).join('');
}

async function lifecycle(action) {
  if (action === 'end') {
    const open = state.event.totals.flags;
    const ok = await ask({ title: 'End this event?', submit: 'End event', iconName: 'stop', body: `<p>Listening stops for everyone.</p>${open ? `<div class="notice amber">${icon('flag')}<span><b>${plural(open, 'line')} still need checking.</b> They stay in the settlement report until resolved.</span></div>` : `<div class="notice">${icon('checkCircle')}<span>Every line has been checked.</span></div>`}<p class="muted small">You can reopen it later.</p>` });
    if (!ok) return;
  }
  try {
    state.event = await api(`/api/events/${state.eventId}/lifecycle`, { method: 'POST', body: { action } });
    toast({ start: 'You are live. Start listening when the MC begins.', pause: 'Paused. Microphones are closed.', resume: 'Live again.', end: 'Event ended. Here is your settlement.', reopen: 'Event reopened and paused.', archive: 'Archived.', unarchive: 'Restored.' }[action]);
    if (action === 'end') go(`#/events/${state.eventId}/settlement`); else renderEventShell();
  } catch (error) { showError(error.message); }
}

function renderTab() {
  const node = $('tab-content'); if (!node) return;
  const renderers = { live: renderLive, review: renderReview, register: renderRegister, guests: renderGuests, 'follow-up': renderFollowUp, settlement: renderSettlement, activity: renderActivity, details: renderDetails };
  node.innerHTML = renderers[state.tab]();
  bindTab();
  animateNumbers();
  hydrateWaves(node);
  state.event.pledges.forEach((p) => state.seen.add(p.id));
}

function refreshView() {
  if (!state.event) return;
  if (state.tab === 'screen') return renderBigScreen(true);
  if (!$('tab-content')) return renderEventShell();
  const active = document.activeElement;
  if (active && ['INPUT', 'TEXTAREA', 'SELECT'].includes(active.tagName) && $('tab-content').contains(active)) return;
  if ($('dialog').open || window.__pbPlaying) return;
  const scroll = scrollY;
  renderEventShell();
  scrollTo(0, scroll);
}
async function reloadEvent() { try { state.event = await api(`/api/events/${state.eventId}`); refreshView(); } catch (error) { showError(error.message); } }

// ----------------------------------------------------------- live updates

function openStream(id) {
  closeStream();
  const source = new EventSource(`/api/events/${id}/stream`);
  state.stream = source;
  source.onopen = () => setConnection(state.mic.stage === 'listening' ? 'rec' : 'on');
  source.onerror = () => setConnection('wait');
  source.onmessage = (message) => {
    const payload = JSON.parse(message.data);
    if (payload.type === 'realtime') return showLiveWords(payload.event);
    if (payload.type === 'deleted') { stopEverything(); showError('This event was deleted.'); go('#/events'); return; }
    if (payload.type === 'error') showError(payload.message);
    if (payload.state) { state.event = payload.state; refreshView(); if (state.tab === 'settlement') loadSettlement(); }
  };
}
function closeStream() { state.stream?.close(); state.stream = null; setConnection('idle'); }

function showLiveWords(realtime) {
  if (!realtime?.transcript) return;
  state.liveWords = realtime.transcript;
  const node = $('live-words');
  if (node) { node.classList.remove('idle'); node.innerHTML = `${esc(realtime.transcript)}${realtime.end_of_turn ? '' : '<span class="caret"></span>'}`; }
}

// -------------------------------------------------------------- live console

function renderLive() {
  const { event, pledges, totals, guests, usage } = state.event;
  const progress = event.target_minor ? Math.min(100, (totals.pledged / event.target_minor) * 100) : 0;
  const listening = state.mic.stage === 'listening';
  const others = Object.entries(totals.by_currency || {}).filter(([c]) => c !== totals.currency);
  const audioLeft = usage ? Math.max(0, usage.limits.audio_seconds - usage.used.audio_seconds) : null;
  const confirmedCount = pledges.filter((p) => ['confirmed', 'corrected', 'redeemed'].includes(p.state)).length;
  const kpis = `<div class="kpis">
    <div class="kpi hero-kpi"><div class="label">${icon('sparkles')} Pledged</div><div class="value num" data-count="${totals.pledged}" data-key="pledged">${money(totals.pledged)}</div>
      ${event.target_minor ? `<div class="bar"><span style="width:${progress}%"></span></div><div class="sub">${Math.round(progress)}% of the ${money(event.target_minor)} target</div>` : `<div class="sub">${others.length ? `Also ${others.map(([c, t]) => money(t.pledged, c)).join(', ')} · ` : ''}${totals.in_kind ? `${plural(totals.in_kind, 'in-kind gift')} · ` : ''}No target set</div>`}</div>
    <div class="kpi"><div class="label">${icon('wallet')} Received</div><div class="value num" data-count="${totals.received}" data-key="received">${money(totals.received)}</div><div class="sub">${totals.pledged ? Math.round((totals.received / totals.pledged) * 100) : 0}% collected</div></div>
    <div class="kpi"><div class="label">${icon('checkCircle')} Confirmed lines</div><div class="value num" data-count="${confirmedCount}" data-key="confirmed-lines" data-format="plain">${confirmedCount}</div><div class="sub">${totals.flags ? `<a href="#/events/${event.id}/review">${plural(totals.flags, 'line')} need checking</a>` : 'Nothing waiting for review'}</div></div></div>`;
  const micDisabled = event.status !== 'live' || ['connecting', 'stopping'].includes(state.mic.stage);
  const micHelp = { live: 'Audio is transcribed by AssemblyAI. Every pledge keeps its clip.', setup: 'Press Go live when the launching starts.', paused: 'Resume the event to listen again.' }[event.status] || 'This event is closed to new pledges.';
  const micCard = can('run') ? `<div class="card mic-card"><div class="section-title"><span class="icon-tile">${icon('mic')}</span><div><h2>MC microphone</h2><p class="muted small">${micHelp}</p></div></div>
      <button id="mic" class="mic-button ${listening ? 'recording' : ''}" ${micDisabled ? 'disabled' : ''}><span class="mic-orb">${icon(listening ? 'stop' : 'mic')}</span>${listening ? 'Stop listening' : state.mic.stage === 'connecting' ? 'Connecting…' : state.mic.stage === 'stopping' ? 'Saving the last words…' : 'Start listening'}</button>
      <div class="meter ${listening ? 'on' : ''}" id="meter" aria-hidden="true">${'<i></i>'.repeat(28)}</div>
      <div class="row wrap"><input id="audio-upload" type="file" accept=".wav,audio/wav" hidden><button id="upload-audio" class="btn btn-ghost btn-sm" type="button" ${event.status !== 'live' ? 'disabled' : ''}>${icon('upload')} Process a recording</button>${event.sample ? `<button id="sample-audio" class="btn btn-ghost btn-sm" type="button" ${event.status !== 'live' ? 'disabled' : ''}>${icon('play')} Play the sample launching</button>` : ''}<span class="spacer"></span>${audioLeft !== null ? `<span class="faint tiny">${Math.floor(audioLeft / 60)} min listening left today</span>` : ''}</div>
      <div id="upload-status" class="notice plain small" hidden></div></div>` : '';
  const newest = pledges[0];
  const reading = `<div class="card reading-card"><div class="section-title"><span class="icon-tile">${icon('wave')}</span><div><h2>Live reading</h2><p class="muted small">What Realtime is hearing right now</p></div></div>
      <div id="live-words" class="live-words ${state.liveWords ? '' : 'idle'}">${state.liveWords ? esc(state.liveWords) : 'Words appear here as the MC speaks.'}</div>
      ${newest ? `<div class="notice plain">${avatar(pledgeName(newest), 'sm')}<div class="grow"><b>${esc(pledgeName(newest))}</b> <span class="faint">· newest</span><div class="small muted">${pledgeAmount(newest)} · ${STATE_LABELS[newest.state]}</div></div></div>` : ''}</div>`;
  return `${kpis}<div class="console ${micCard ? '' : 'solo'}">${micCard}${reading}</div>
    ${!guests.length && can('guests') ? `<div class="notice gold">${icon('users')}<span>Add your guest list first so names are recognised. <a href="#/events/${event.id}/guests">Add guests</a></span></div>` : ''}
    <div class="card"><div class="card-head"><div><h2>Pledges</h2><p class="muted small">Newest first. Every line keeps its spoken evidence.</p></div><a class="btn btn-quiet btn-sm" href="#/events/${event.id}/register">Full register ${icon('chevronRight')}</a></div>
      <div class="feed">${pledges.length ? pledges.slice(0, 12).map((p) => pledgeRow(p)).join('') : empty('mic', 'Waiting for the first pledge', 'When the MC announces a guest and an amount, it appears here within seconds.')}</div></div>`;
}

function pledgeRow(p, actions = '') {
  const isNew = !state.seen.has(p.id);
  const anonymous = p.matched_name === 'Anonymous donor';
  return `<div class="prow ${isNew ? 'enter' : ''}">${anonymous ? `<span class="avatar anon">${icon('heart')}</span>` : avatar(pledgeName(p))}
    <div class="who"><b>${esc(pledgeName(p))} ${chip(p.state)}${p.recognised_from_pledge_id ? `<span class="tag">${icon('sparkles')} Learned</span>` : ''}</b>
      <div class="said">${clock(p.created_at)} · <q>${esc(p.recheck_text || p.live_text || '—')}</q>${p.reason ? ` · <span class="${p.state === 'flagged' ? 'warn' : 'faint'}">${esc(p.reason)}</span>` : ''}</div></div>
    <div class="side"><span class="amt num">${pledgeAmount(p)}</span>${p.received ? `<span class="chip brand">${money(p.received, p.currency)} paid</span>` : ''}${actions}</div></div>`;
}

// ------------------------------------------------------------ microphone

async function startMic() {
  if (state.mic.stage === 'listening') return requestStopMic();
  if (state.mic.stage !== 'idle') return;
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) { showError('The microphone needs a secure (HTTPS) connection.'); return; }
  const mic = state.mic;
  mic.stage = 'connecting'; renderTab(); setConnection('wait', 'Connecting microphone');
  try {
    mic.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, channelCount: 1 } });
    mic.audio = new AudioContext(); await mic.audio.resume(); await mic.audio.audioWorklet.addModule('/static/pcm-worklet.js');
    mic.source = mic.audio.createMediaStreamSource(mic.stream); mic.worklet = new AudioWorkletNode(mic.audio, 'pledgebook-pcm');
    mic.analyser = mic.audio.createAnalyser(); mic.analyser.fftSize = 64; mic.source.connect(mic.analyser);
    mic.sink = mic.audio.createGain(); mic.sink.gain.value = 0; mic.worklet.connect(mic.sink); mic.sink.connect(mic.audio.destination);
    const socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/events/${state.eventId}/capture`);
    socket.binaryType = 'arraybuffer'; mic.socket = socket;
    socket.onmessage = (message) => {
      const payload = JSON.parse(message.data);
      if (payload.type === 'connection') {
        mic.stage = 'listening'; renderTab(); setConnection('rec'); toast('Listening. Pledges appear as the MC announces them.');
        mic.source.connect(mic.worklet);
        mic.worklet.port.onmessage = (audioMessage) => { if (socket.readyState === WebSocket.OPEN) socket.send(audioMessage.data); };
        drawMeter();
      } else if (payload.type === 'realtime') showLiveWords(payload.event);
      else if (payload.type === 'stopped' || payload.type === 'error') showError(payload.message);
    };
    socket.onerror = () => showError('The live audio connection could not be opened. Check your connection and try again.');
    socket.onclose = () => { if (mic.socket === socket) { stopMic(); renderTab(); setConnection(state.stream ? 'on' : 'idle'); } };
  } catch (error) {
    stopMic(); renderTab();
    showError(error.name === 'NotAllowedError' ? 'Microphone permission was denied. Allow it in your browser settings and try again.' : error.name === 'NotFoundError' ? 'No microphone was found on this device.' : `The microphone could not start: ${error.message}`);
  }
}

function drawMeter() {
  const mic = state.mic;
  cancelAnimationFrame(mic.raf);
  const data = new Uint8Array(32);
  const frame = () => {
    if (!mic.analyser || mic.stage !== 'listening') return;
    mic.analyser.getByteFrequencyData(data);
    document.querySelectorAll('#meter i').forEach((bar, i) => { const v = data[Math.min(31, Math.floor(i * 1.1))] / 255; bar.style.height = `${Math.max(8, v * 100)}%`; });
    mic.raf = requestAnimationFrame(frame);
  };
  frame();
}

function requestStopMic() {
  const mic = state.mic; if (mic.stage !== 'listening') return;
  mic.stage = 'stopping'; renderTab();
  if (mic.socket?.readyState === WebSocket.OPEN) mic.socket.send(JSON.stringify({ type: 'stop' })); else stopMic();
}

function stopMic() {
  const mic = state.mic; const socket = mic.socket; mic.socket = null;
  cancelAnimationFrame(mic.raf);
  if (mic.worklet) { mic.worklet.port.onmessage = null; mic.worklet.disconnect(); }
  mic.sink?.disconnect(); mic.source?.disconnect(); mic.analyser?.disconnect(); mic.stream?.getTracks().forEach((t) => t.stop()); mic.audio?.close();
  if (socket && socket.readyState < WebSocket.CLOSING) socket.close();
  Object.assign(mic, { stage: 'idle', audio: null, worklet: null, sink: null, source: null, stream: null, analyser: null });
}

async function sendRecording(file, label) {
  const status = $('upload-status');
  if (status) { status.hidden = false; status.innerHTML = `${icon('upload')} Sending ${esc(label)}…`; }
  try {
    let result;
    if (file) { const form = new FormData(); form.append('file', file, file.name); result = await api(`/api/events/${state.eventId}/upload`, { method: 'POST', body: form }); }
    else result = await api(`/api/events/${state.eventId}/sample-audio`, { method: 'POST' });
    toast(result.message);
    const node = $('upload-status'); if (node) node.innerHTML = `${icon('wave')} Listening to the recording at real speed — pledges will appear below.`;
  } catch (error) { const node = $('upload-status'); if (node) node.hidden = true; showError(error.message); }
}

// ------------------------------------------------------------------ review

function highlight(text) {
  return esc(text || '—').replace(/(₦\s?[\d,.]+\s?(?:million|k|K)?|\b\d[\d,]*(?:\.\d+)?\s?(?:million|thousand|k)?\b)/g, '<mark>$1</mark>');
}

function renderReview() {
  const { pledges, event } = state.event;
  const flags = pledges.filter((p) => p.state === 'flagged');
  const invite = can('run') ? `<div class="card tight"><div class="row wrap"><span class="section-title"><span class="icon-tile">${icon('qr')}</span><span><b>Bring in an usher</b><br><span class="muted small">They join on their own phone and see only this queue and the register — never contact details.</span></span></span><span class="spacer"></span><button class="btn btn-ghost" data-invite-usher>${icon('userPlus')} Invite an usher</button></div></div>` : '';
  return `${invite}<div class="card"><div class="card-head"><div><h2>Needs checking ${flags.length ? `<span class="count">${flags.length}</span>` : ''}</h2><p class="muted small">Listen, compare both passes, then decide. Nothing here is counted until a person settles it.</p></div></div>
    <div class="stack">${flags.length ? flags.map(reviewCard).join('') : empty('check', 'All clear', 'Every line has been checked. New questions appear here the moment they are heard.')}</div></div>
    ${event.status === 'archived' ? `<div class="notice plain">${icon('archive')}<span>This event is archived. Restore it to make changes.</span></div>` : ''}`;
}

function reviewCard(p) {
  const earlier = /pledge #(\d+)/.exec(p.reason || '');
  // A bare small number from the recheck ("250") is exactly what was flagged, so it is never offered.
  const recheckAmount = p.recheck_amount_minor >= 1000 && p.recheck_amount_minor !== p.amount ? p.recheck_amount_minor : null;
  return `<div class="review-card" data-card="${p.id}"><div class="review-top">${avatar(p.heard_name || '?')}<div class="grow"><h3>${esc(p.heard_name || 'Name unclear')} <span class="faint">·</span> <span class="num">${pledgeAmount(p)}</span> <span class="faint tiny">#${p.id} · ${clock(p.created_at)}</span></h3>
      <div class="review-reason">${icon('flag')}<span>${esc(p.reason || 'Listen to the clip and choose what you heard.')}</span></div></div></div>
    ${p.has_audio ? `<div class="wave-player" data-src="/api/events/${state.eventId}/pledges/${p.id}/audio"></div>` : `<div class="notice plain">${icon('info')}<span>No audio clip for this line.</span></div>`}
    <div class="passes"><div class="pass"><div class="label">${icon('wave')} Live reading</div>${highlight(p.live_text)}</div><div class="pass"><div class="label">${icon('rotate')} Recheck</div>${p.recheck_text ? highlight(p.recheck_text) : '<span class="faint">Not rechecked yet</span>'}</div></div>
    <div class="resolve-bar"><div class="guest-picker"><div class="search-box">${icon('search')}<input class="input" data-picker="${p.id}" placeholder="Who pledged? Type a guest's name" autocomplete="off"></div><div class="picker-list" data-picker-list="${p.id}" hidden></div></div>
      <div class="row wrap">${p.guest_id && (p.amount != null || p.item) && !recheckAmount ? `<button class="btn btn-primary btn-sm" data-keep="${p.id}">${icon('check')} Confirm ${esc(pledgeName(p))} · ${pledgeAmount(p)}</button>` : ''}${recheckAmount ? `<button class="btn btn-primary btn-sm" data-use-recheck="${p.id}" data-value="${recheckAmount}">${icon('check')} Use ${money(recheckAmount)} from the recheck</button>` : ''}
        <button class="btn btn-ghost btn-sm" data-fix-amount="${p.id}">${icon('pencil')} Enter amount</button><button class="btn btn-ghost btn-sm" data-walk-in="${p.id}">${icon('userPlus')} New walk-in</button><button class="btn btn-ghost btn-sm" data-anonymous="${p.id}">${icon('heart')} Anonymous</button>
        ${earlier && !p.guest_id ? `<button class="btn btn-ghost btn-sm" data-keep="${p.id}">Keep both</button><button class="btn btn-ghost btn-sm" data-replace="${p.id}">Replace #${earlier[1]}</button>` : ''}<span class="spacer"></span><button class="btn btn-danger-quiet btn-sm" data-reject="${p.id}">${icon('x')} Not a pledge</button></div></div></div>`;
}

function renderPicker(input) {
  const id = input.dataset.picker; const list = root.querySelector(`[data-picker-list="${id}"]`);
  const q = input.value.trim().toLowerCase();
  const matches = state.event.guests.filter((g) => !q || guestName(g).toLowerCase().includes(q)).slice(0, 8);
  list.hidden = false;
  list.innerHTML = matches.length ? matches.map((g, i) => `<button type="button" class="${i === 0 ? 'hl' : ''}" data-pick="${id}" data-guest="${g.id}">${avatar(guestName(g), 'sm')} ${esc(guestName(g))}</button>`).join('') : `<div class="none">No guest matches “${esc(input.value)}”. Use New walk-in to add them.</div>`;
}

async function resolve(pledgeId, body) {
  root.querySelector(`[data-card="${pledgeId}"]`)?.classList.add('resolving');
  try { state.event = await api(`/api/events/${state.eventId}/pledges/${pledgeId}/resolve`, { method: 'POST', body }); toast('Saved. The line has been updated.'); renderEventShell(); }
  catch (error) { root.querySelector(`[data-card="${pledgeId}"]`)?.classList.remove('resolving'); showError(error.message); }
}

// ---------------------------------------------------------------- register

function renderRegister() {
  const { pledges } = state.event;
  const query = state.registerQuery.toLowerCase();
  const rows = pledges.filter((p) => (state.registerFilter === 'all' || p.state === state.registerFilter) && (!query || `${pledgeName(p)} ${p.live_text} ${p.id}`.toLowerCase().includes(query)));
  const counts = pledges.reduce((acc, p) => { acc[p.state] = (acc[p.state] || 0) + 1; return acc; }, {});
  const filters = ['all', 'confirmed', 'corrected', 'provisional', 'flagged', 'redeemed', 'rejected'].filter((s) => s === 'all' || counts[s]);
  return `<div class="card"><div class="card-head"><div><h2>Register</h2><p class="muted small">${plural(pledges.length, 'line')} captured. Search, filter and correct.</p></div>${can('export') ? `<a class="btn btn-ghost btn-sm" href="/api/events/${state.eventId}/export.csv">${icon('download')} Export CSV</a>` : ''}</div>
    <div class="toolbar"><div class="segmented scroll">${filters.map((s) => `<button data-filter="${s}" class="${state.registerFilter === s ? 'active' : ''}">${s === 'all' ? 'All' : STATE_LABELS[s]} <span class="faint">${s === 'all' ? pledges.length : counts[s]}</span></button>`).join('')}</div>
      <div class="search-box">${icon('search')}<input id="register-search" class="input" type="search" placeholder="Search names, words or line number" value="${esc(state.registerQuery)}"></div></div>
    <div class="feed">${rows.length ? rows.map((p) => pledgeRow(p, can('run') && p.state !== 'rejected' ? `<div class="actions"><button class="btn btn-quiet btn-sm" data-fix-amount="${p.id}" title="Change amount" aria-label="Change amount">${icon('pencil')}</button><button class="btn btn-quiet btn-sm" data-change-guest="${p.id}" title="Change guest" aria-label="Change guest">${icon('users')}</button>${p.received ? '' : `<button class="btn btn-danger-quiet btn-sm" data-reject="${p.id}" title="Reject" aria-label="Reject">${icon('x')}</button>`}</div>` : '')).join('') : empty('mic', pledges.length ? 'No lines match' : 'The register is empty', pledges.length ? 'Try another filter or search.' : 'Lines appear here as soon as the MC announces pledges.')}</div></div>`;
}

// ------------------------------------------------------------------ guests

function renderGuests() {
  const { guests, key_terms: keyTerms, removed_guests: removed, event } = state.event;
  const query = state.guestQuery.toLowerCase();
  const rows = guests.filter((g) => !query || `${guestName(g)} ${g.phone || ''} ${g.email || ''} ${g.group_name || ''}`.toLowerCase().includes(query));
  const locked = event.status === 'archived';
  const consented = guests.filter((g) => g.consent_to_contact).length;
  const preview = state.importPreview;
  return `<div class="kpis three">
      <div class="kpi"><div class="label">${icon('users')} Guests</div><div class="value num">${guests.length}</div><div class="sub">${removed ? `${removed} removed, kept for past pledges` : 'On the listening list'}</div></div>
      <div class="kpi"><div class="label">${icon('wave')} Listened for</div><div class="value num">${keyTerms.included_count}</div><div class="sub">${keyTerms.overflow_count ? `${keyTerms.overflow_count} beyond the limit of ${keyTerms.term_limit}` : `Up to ${keyTerms.term_limit} names`}</div></div>
      <div class="kpi"><div class="label">${icon('send')} Can be followed up</div><div class="value num">${consented}</div><div class="sub">Consent recorded</div></div></div>
    <div class="console wide-left">
      <div class="card"><div class="card-head"><div><h2>Guest list</h2><p class="muted small">Names here are sent to the speech model so they are heard correctly.</p></div></div>
        <div class="search-box mb">${icon('search')}<input id="guest-search" class="input" type="search" placeholder="Search name, phone, email or group" value="${esc(state.guestQuery)}"></div>
        <div>${rows.length ? rows.map((g) => `<div class="guest-row">${avatar(guestName(g), 'sm')}<div class="grow"><b>${esc(guestName(g))}</b>${g.group_name ? ` <span class="faint small">· ${esc(g.group_name)}</span>` : ''}</div>
          <div class="contact">${[g.phone, g.email].filter(Boolean).map(esc).join(' · ') || '<span class="faint">No contact details</span>'}</div>
          <span class="consent">${g.consent_to_contact ? `<span class="chip brand">${icon('check')} Follow-up</span>` : '<span class="chip">No consent</span>'}</span>
          ${locked ? '<span></span>' : `<div class="row tight-row"><button class="btn btn-quiet btn-icon" data-edit-guest="${g.id}" title="Edit" aria-label="Edit">${icon('pencil')}</button><button class="btn btn-quiet btn-icon" data-guest-history="${g.id}" title="History" aria-label="History">${icon('clock')}</button><button class="btn btn-danger-quiet btn-icon" data-remove-guest="${g.id}" title="Remove" aria-label="Remove">${icon('trash')}</button></div>`}</div>`).join('') : empty('people', guests.length ? 'No guests match' : 'No guests yet', guests.length ? 'Try a different search.' : 'Add guests one by one or import your list from a spreadsheet.')}</div></div>
      <div class="stack top">${locked ? `<div class="card">${empty('calendar', 'Archived', 'Restore the event to change its guest list.')}</div>` : `
        <div class="card"><div class="section-title mb"><span class="icon-tile">${icon('userPlus')}</span><h2>Add a guest</h2></div>
          <form id="guest-form" class="form-grid">${guestFields()}<button class="btn btn-primary btn-block full" type="submit">${icon('plus')} Add guest</button></form></div>
        <div class="card"><div class="section-title mb"><span class="icon-tile">${icon('file')}</span><div><h2>Import a list</h2><p class="muted small">CSV with a <code>name</code> column. Optional: title, phone, email, consent_to_contact, group.</p></div></div>
          <label class="dropzone" id="dropzone">${icon('upload')}<b>Drop a CSV here or choose a file</b><span class="small">You will see every row before anything is added.</span><input id="guest-csv" type="file" accept=".csv,text/csv" hidden></label>
          ${preview ? importPreview(preview) : ''}</div>`}</div></div>`;
}

function guestFields(g = {}) {
  return `<label class="field">Title<input name="title" value="${esc(g.title || '')}" placeholder="Chief, Mrs, Dr…"></label><label class="field">Full name<input name="name" required value="${esc(g.name || '')}" placeholder="Adaeze Nnamdi"></label>
    <label class="field">Phone<input name="phone" inputmode="tel" value="${esc(g.phone || '')}" placeholder="0803 123 4567"></label><label class="field">Email<input name="email" type="email" value="${esc(g.email || '')}" placeholder="name@example.com"></label>
    <label class="field full">Group <span class="hint">Optional</span><input name="group" value="${esc(g.group_name || '')}" placeholder="Choir, men's fellowship…"></label>
    <label class="check-field full"><input type="checkbox" name="consent_to_contact" ${g.consent_to_contact ? 'checked' : ''}><span>This guest agreed to be contacted about their pledge</span></label>`;
}

function importPreview(preview) {
  const { rows, counts } = preview;
  return `<div class="import-preview"><div class="row wrap"><span class="chip brand">${counts.ok} to add</span>${counts.duplicate ? `<span class="chip amber">${counts.duplicate} duplicate</span>` : ''}${counts.invalid ? `<span class="chip red">${counts.invalid} with problems</span>` : ''}</div>
    <div class="table-wrap scroll-y"><table><thead><tr><th>Row</th><th>Name</th><th>Result</th></tr></thead><tbody>${rows.map((r) => `<tr class="${r.status}"><td class="faint">${r.row}</td><td><b>${esc(guestName(r))}</b><div class="tiny muted">${esc([r.phone, r.email].filter(Boolean).join(' · '))}</div></td><td class="small">${r.status === 'ok' ? '<span class="ok-text">Will be added</span>' : esc(r.message)}</td></tr>`).join('')}</tbody></table></div>
    <div class="dialog-actions"><button class="btn btn-ghost" data-cancel-import>Cancel</button><button class="btn btn-primary" data-confirm-import ${counts.ok ? '' : 'disabled'}>${icon('check')} Add ${plural(counts.ok, 'guest')}</button></div></div>`;
}

// --------------------------------------------------------------- follow-up

function renderFollowUp() {
  const { pledges, guests, follow_up: follow, payments, email_configured: emailOn } = state.event;
  const accepted = pledges.filter((p) => ['confirmed', 'corrected', 'redeemed'].includes(p.state));
  const mode = payments.mode;
  const owing = accepted.filter((p) => !p.item && (p.amount || 0) > (p.received || 0));
  const outstandingTotal = owing.reduce((sum, p) => sum + (p.amount - (p.received || 0)), 0);
  const cards = accepted.map((p) => {
    const guest = guests.find((g) => g.id === p.guest_id);
    const link = follow.links.find((l) => l.pledge_id === p.id && l.active);
    const deliveries = follow.deliveries.filter((d) => d.pledge_id === p.id);
    const calls = follow.calls.filter((c) => c.pledge_id === p.id);
    const payRows = follow.payments.filter((x) => x.pledge_id === p.id && x.status === 'success');
    const outstanding = p.item ? 0 : Math.max(0, (p.amount || 0) - (p.received || 0));
    const pct = p.amount ? Math.min(100, ((p.received || 0) / p.amount) * 100) : 0;
    const history = [...deliveries.map((d) => ({ at: d.created_at, text: `Pledge page ${d.status === 'sent' ? 'emailed' : d.status === 'copied' ? 'link copied' : `prepared for ${d.channel === 'whatsapp' ? 'WhatsApp' : 'SMS'}`}${d.sent_by ? ` by ${d.sent_by}` : ''}${d.status === 'failed' ? ' — failed' : ''}` })),
      ...calls.map((c) => ({ at: c.created_at, text: `${c.kind === 'phone' ? 'Phone call' : c.kind === 'assistant' ? 'Voice assistant' : 'Guest page'}: ${OUTCOME_LABELS[c.outcome] || c.outcome}${c.promised_date ? ` · ${shortDate(c.promised_date)}` : ''}${c.notes ? ` — ${c.notes}` : ''}` })),
      ...payRows.map((x) => ({ at: x.paid_at || x.created_at, text: `Received ${money(x.amount)}` })),
      ...(link?.opened_at ? [{ at: link.opened_at, text: 'Guest opened their pledge page' }] : [])].sort((a, b) => (b.at || '').localeCompare(a.at || '')).slice(0, 4);
    let actions;
    if (!guest) actions = `<span class="chip">${icon('heart')} Anonymous — no follow-up</span>`;
    else if (p.follow_up_stopped) actions = `<span class="chip">${icon('eyeOff')} Asked not to be contacted</span>`;
    else if (!guest.consent_to_contact) actions = `<a class="btn btn-ghost btn-sm" href="#/events/${state.eventId}/guests">${icon('lock')} No consent recorded</a>`;
    else actions = `<button class="btn btn-primary btn-sm" data-send="${p.id}">${icon('send')} Send pledge page</button>${guest.phone ? `<a class="btn btn-ghost btn-sm" href="tel:${esc(guest.phone)}">${icon('phone')} Call</a>` : ''}<button class="btn btn-ghost btn-sm" data-log-call="${p.id}">${icon('pencil')} Log call</button>${!p.item && outstanding ? `<button class="btn btn-ghost btn-sm" data-offline="${p.id}">${icon('wallet')} Record payment</button>` : ''}${mode !== 'off' && follow.payments.some((x) => x.pledge_id === p.id && ['initialized', 'pending'].includes(x.status)) ? `<button class="btn btn-ghost btn-sm" data-verify="${p.id}">${icon('rotate')} Check Paystack</button>` : ''}${link ? `<button class="btn btn-quiet btn-sm" data-copy="${esc(link.url)}">${icon('link')} Copy link</button><button class="btn btn-danger-quiet btn-sm" data-close-link="${p.id}">Close page</button>` : ''}`;
    return `<div class="fu-card"><div class="fu-top">${p.matched_name === 'Anonymous donor' ? `<span class="avatar anon">${icon('heart')}</span>` : avatar(pledgeName(p))}<div class="grow"><b>${esc(pledgeName(p))}</b> ${chip(p.state)}<div class="small muted">${guest ? [guest.phone, guest.email].filter(Boolean).map(esc).join(' · ') : ''}</div></div><span class="amt-lg num">${pledgeAmount(p)}</span></div>
      ${p.item ? '' : `<div class="fu-money"><div class="bar ${pct >= 100 ? '' : 'gold'}"><span style="width:${pct}%"></span></div><div class="nums"><span>${money(p.received, p.currency)} received</span><span>${outstanding ? `${money(outstanding, p.currency)} to go` : 'Paid in full'}</span></div></div>`}
      ${history.length ? `<ul class="timeline">${history.map((h) => `<li><time>${when(h.at)}</time><span>${esc(h.text)}</span></li>`).join('')}</ul>` : ''}
      <div class="fu-actions">${actions}</div></div>`;
  });
  return `<div class="kpis three">
      <div class="kpi"><div class="label">${icon('receipt')} To collect</div><div class="value num">${money(outstandingTotal)}</div><div class="sub">across ${plural(owing.length, 'pledge')}</div></div>
      <div class="kpi"><div class="label">${icon('send')} Pages sent</div><div class="value num">${new Set(follow.deliveries.map((d) => d.pledge_id)).size}</div><div class="sub">${follow.links.filter((l) => l.opened_at).length} opened by guests</div></div>
      <div class="kpi"><div class="label">${icon('wallet')} Payments</div><div class="value num">${follow.payments.filter((x) => x.status === 'success').length}</div><div class="sub">${mode === 'live' ? 'Paystack live' : mode === 'test' ? 'Paystack test mode' : 'Offline only'}</div></div></div>
    ${mode === 'test' ? `<div class="notice gold">${icon('info')}<span><b>Paystack test mode.</b> Checkouts use test cards and no real money moves. Switch to a live key in the server settings to accept real payments.</span></div>` : ''}
    ${emailOn ? '' : `<div class="notice plain">${icon('message')}<span>Pages go out by WhatsApp or SMS from your own phone, or as a copied link. Email sending is not set up on this server.</span></div>`}
    <div class="card"><div class="card-head"><div><h2>Follow-up</h2><p class="muted small">Send each guest a private pledge page. They can hear the moment they pledged, pay in parts, choose a date, or talk to the disclosed voice assistant on their own phone.</p></div></div>
      <div class="stack">${cards.length ? cards.join('') : empty('receipt', 'No confirmed pledges yet', 'Confirmed pledges appear here, ready to follow up.')}</div></div>`;
}

// -------------------------------------------------------------- settlement

function renderSettlement() {
  const data = state.settlement;
  if (!data) return skeleton(3);
  const { rows, counts, totals } = data;
  const pct = totals.confirmed ? Math.round((totals.received / totals.confirmed) * 100) : 0;
  const circumference = 2 * Math.PI * 80;
  return `<div class="card"><div class="card-head"><div><h2>Settlement</h2><p class="muted small">What was promised, what has arrived, and who still needs a nudge.</p></div>${can('export') ? `<a class="btn btn-ghost btn-sm" href="/api/events/${state.eventId}/settlement.csv">${icon('download')} Export CSV</a>` : ''}</div>
    <div class="settle-top"><div class="donut"><svg viewBox="0 0 200 200"><circle class="track" cx="100" cy="100" r="80"/><circle class="got" cx="100" cy="100" r="80" stroke-dasharray="${(pct / 100) * circumference} ${circumference}"/></svg><div class="center"><div><strong class="num">${pct}%</strong><span>collected</span></div></div></div>
      <div class="legend"><div><b class="num">${money(totals.confirmed, totals.currency)}</b><span>Confirmed pledges</span></div><div><b class="num ok-text">${money(totals.received, totals.currency)}</b><span>Received</span></div>
        <div><b class="num gold-text">${money(Math.max(0, totals.confirmed - totals.received), totals.currency)}</b><span>Outstanding</span></div><div><b class="num">${counts.fully_paid} / ${counts.pledges}</b><span>Paid in full${counts.part_paid ? ` · ${counts.part_paid} part paid` : ''}</span></div></div></div>
    ${counts.needs_checking ? `<div class="notice amber mt">${icon('flag')}<span><b>${plural(counts.needs_checking, 'line')} still need checking</b> and are not counted as confirmed. <a href="#/events/${state.eventId}/review">Review them</a></span></div>` : ''}</div>
    <div class="card"><div class="card-head"><h2>Every pledge</h2></div><div class="table-wrap"><table><thead><tr><th>Guest</th><th>Pledged</th><th>Received</th><th>Outstanding</th><th>Status</th><th>Promised</th><th>Last contact</th></tr></thead><tbody>
    ${rows.map((r) => `<tr><td><div class="cell-who">${avatar(r.guest, 'sm')}<div><b>${esc(r.guest)}</b><div class="tiny faint">#${r.pledge_id} · ${esc(r.follow_up)}</div></div></div></td><td class="num">${r.item ? esc(r.item) : r.amount == null ? '<span class="faint">Unclear</span>' : money(r.amount, r.currency)}</td><td class="num">${r.item ? '—' : money(r.received, r.currency)}</td><td class="num">${r.item || r.amount == null ? '—' : money(r.outstanding, r.currency)}</td><td>${chip(r.state)}</td><td>${r.promised_date ? shortDate(r.promised_date) : '<span class="faint">—</span>'}</td><td>${r.last_contact ? `${ago(r.last_contact)}<div class="tiny faint">${esc(OUTCOME_LABELS[r.last_outcome] || r.last_outcome || '')}</div>` : '<span class="faint">—</span>'}</td></tr>`).join('') || `<tr><td colspan="7">${empty('receipt', 'Nothing to settle yet', 'Pledges appear here once they are heard.')}</td></tr>`}</tbody></table></div></div>`;
}
async function loadSettlement() { try { state.settlement = await api(`/api/events/${state.eventId}/settlement`); if (state.tab === 'settlement') renderTab(); } catch (error) { showError(error.message); } }

// ---------------------------------------------------------------- activity

const ACTIVITY_ICONS = { live_pledge: ['wave', 'ai'], rechecked: ['rotate', 'ai'], recheck_failed: ['alert', ''], usher_review: ['review', 'person'], listening_list_updated: ['sparkles', 'ai'], guest_added: ['userPlus', 'guest'], guest_edited: ['pencil', 'guest'], guest_removed: ['trash', 'guest'], guests_imported: ['file', 'guest'], payment_received: ['wallet', 'money'], checkout_started: ['wallet', 'money'], payment_promised: ['calendar', 'money'], pledge_page_delivery: ['send', 'person'], pledge_page_opened: ['link', 'guest'], phone_call_logged: ['phone', 'person'], assistant_started: ['message', 'ai'], identity_checked: ['shield', 'ai'], payment_disputed: ['flag', ''], listening_started: ['mic', 'person'], listening_stopped: ['stop', 'person'], live_repeat_ignored: ['copy', 'ai'] };
function renderActivity() {
  const data = state.activity;
  if (!data) return skeleton(3);
  return `<div class="card"><div class="card-head"><div><h2>Activity</h2><p class="muted small">Every change, who made it, and when — people, AssemblyAI and Paystack.</p></div>${can('export') ? `<a class="btn btn-ghost btn-sm" href="/api/events/${state.eventId}/activity.csv">${icon('download')} Export CSV</a>` : ''}</div>
    <ol class="activity">${data.rows.map(activityItem).join('') || `<li class="block">${empty('calendar', 'No activity yet', 'Changes appear here as they happen.')}</li>`}</ol>${data.more ? '<div class="center mt"><button class="btn btn-ghost" data-more-activity>Show older</button></div>' : ''}</div>`;
}
function activityItem(row) {
  const d = row.details || {}; const bits = [];
  if (row.pledge_id) bits.push(`line #${row.pledge_id}`);
  for (const key of ['name', 'text', 'reason', 'outcome', 'channel', 'status', 'promised_date', 'what_they_said', 'role', 'error']) if (d[key]) bits.push(`${key.replace('_', ' ')}: ${d[key]}`);
  if (d.amount) bits.push(money(d.amount));
  if (d.from !== undefined && d.to !== undefined && typeof d.to !== 'object') bits.push(`${d.from ?? '—'} → ${d.to}`);
  if (d.imported !== undefined) bits.push(`${d.imported} added, ${d.skipped} skipped`);
  if (d.changes) bits.push(`changed ${Object.keys(d.changes).join(', ') || 'nothing'}`);
  const [ic, kind] = ACTIVITY_ICONS[row.action] || (row.action.startsWith('event_') ? ['calendar', 'person'] : ['activity', '']);
  return `<li><span class="a-icon ${kind}">${icon(ic)}</span><div><b>${esc(row.label)}</b>${row.actor ? ` <span class="muted small">by ${esc(row.actor)}</span>` : ''}<div class="detail">${esc(bits.join(' · '))}</div></div><time title="${esc(when(row.created_at))}">${ago(row.created_at)}</time></li>`;
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
  return `<div class="card"><div class="section-title mb"><span class="icon-tile">${icon('sliders')}</span><div><h2>Event details</h2><p class="muted small">Shown to guests on their pledge pages.</p></div></div>
      <form id="details-form" class="form-grid"><label class="field full">Event name<input name="name" required value="${esc(event.name)}"></label>
      <label class="field">Organisation shown to guests<input name="organisation" value="${esc(event.organisation)}"></label><label class="field">Date<input name="event_date" type="date" required value="${esc(event.event_date)}"></label>
      <label class="field">Target <span class="hint">₦</span><input name="target" type="number" min="0" value="${event.target_minor || ''}"></label><span></span>
      <label class="field">Smallest expected pledge <span class="hint">Lines below are flagged</span><input name="minimum" type="number" min="0" value="${event.min_minor || ''}"></label>
      <label class="field">Largest expected pledge <span class="hint">Lines above are flagged</span><input name="maximum" type="number" min="0" value="${event.max_minor || ''}"></label>
      <div class="full"><button class="btn btn-primary" type="submit" ${event.status === 'archived' ? 'disabled' : ''}>${icon('check')} Save changes</button></div></form></div>
    <div class="card danger-card"><div class="section-title mb"><span class="icon-tile danger">${icon('trash')}</span><div><h2>Delete this event</h2><p class="muted small">Removes guests, pledges, audio and follow-up records permanently. End the event first. Only an owner can delete an event with payments. Archiving keeps the records.</p></div></div>
      <button class="btn btn-danger" data-delete-event ${event.status === 'live' ? 'disabled' : ''}>${icon('trash')} Delete event…</button></div>`;
}

// --------------------------------------------------------- big screen view

function renderBigScreen(update = false) {
  const { event, pledges, totals } = state.event;
  document.title = `${event.name} · Big screen`;
  const shown = pledges.filter((p) => ['provisional', 'confirmed', 'corrected', 'redeemed'].includes(p.state));
  const newest = shown[0];
  const progress = event.target_minor ? Math.min(100, (totals.pledged / event.target_minor) * 100) : 0;
  const isNew = newest && !state.seen.has(newest.id);
  const name = (p) => p.matched_name === 'Anonymous donor' ? 'A son or daughter of the soil' : pledgeName(p);
  if (!update || !$('bs-root')) {
    root.innerHTML = `<div class="bigscreen" id="bs-root"><a class="btn btn-ghost btn-sm bs-exit" href="#/events/${event.id}/live">${icon('x')} Exit</a>
      <div class="bs-top"><span class="brand">${logo(36)} Pledgebook</span><div class="bs-title"><small>${esc(event.organisation)}</small><h1>${esc(event.name)}</h1></div><button class="btn btn-sm bs-full" data-fullscreen>${icon('maximize')} Full screen</button></div>
      <div class="bs-main"><div class="bs-total"><small>Pledged tonight</small><div class="num" id="bs-total" data-from="${totals.pledged}">${money(totals.pledged)}</div>
        <div class="bs-bar"><span id="bs-bar"></span></div><div class="bs-sub"><span id="bs-target"></span><span id="bs-count"></span></div></div>
        <div class="bs-newest" id="bs-newest"></div></div>
      <div class="bs-ticker" id="bs-ticker"></div></div>`;
  }
  countUp($('bs-total'), totals.pledged);
  $('bs-bar').style.width = `${event.target_minor ? progress : 0}%`;
  $('bs-bar').parentElement.classList.toggle('none', !event.target_minor);
  $('bs-target').textContent = event.target_minor ? `${Math.round(progress)}% of ${money(event.target_minor)}` : '';
  $('bs-count').textContent = plural(shown.length, 'pledge');
  const card = $('bs-newest');
  card.innerHTML = newest ? `<small>${isNew ? 'Just pledged' : 'Latest pledge'}</small><h2>${esc(name(newest))}</h2><div class="amt num">${pledgeAmount(newest)}</div>` : '<small>Ready</small><h2>The first pledge will appear here</h2>';
  if (isNew) { card.classList.remove('pop'); void card.offsetWidth; card.classList.add('pop'); sparkle(card); }
  $('bs-ticker').innerHTML = shown.slice(1, 12).map((p) => `<div>${esc(name(p))} <b class="num">${pledgeAmount(p)}</b></div>`).join('');
  pledges.forEach((p) => state.seen.add(p.id));
}

function sparkle(node) {
  if (reduced()) return;
  const colours = ['#f2b544', '#2fbf8a', '#ffffff', '#7de3b7'];
  for (let i = 0; i < 26; i += 1) {
    const s = document.createElement('span'); s.className = 'spark';
    s.style.left = '50%'; s.style.top = '50%'; s.style.background = colours[i % colours.length];
    const angle = (Math.PI * 2 * i) / 26; const dist = 140 + Math.random() * 160;
    s.style.setProperty('--dx', `${Math.cos(angle) * dist}px`); s.style.setProperty('--dy', `${Math.sin(angle) * dist}px`);
    node.append(s); setTimeout(() => s.remove(), 1500);
  }
}

// ---------------------------------------------------------- waveform player

const waveCache = new Map();
const waveObserver = 'IntersectionObserver' in window ? new IntersectionObserver((entries) => entries.forEach((e) => { if (e.isIntersecting) { waveObserver.unobserve(e.target); loadWave(e.target); } }), { rootMargin: '120px' }) : null;

function hydrateWaves(scope) {
  scope.querySelectorAll('.wave-player[data-src]:not([data-ready])').forEach((node) => {
    node.dataset.ready = '1';
    node.innerHTML = `<button class="play" type="button" aria-label="Play the clip">${icon('play')}</button><div class="wave-bars">${'<i></i>'.repeat(48)}</div><span class="time num">0:00</span>`;
    if (waveObserver) waveObserver.observe(node); else loadWave(node);
  });
}

async function loadWave(node) {
  const src = node.dataset.src;
  try {
    let entry = waveCache.get(src);
    if (!entry) {
      const response = await fetch(src, { credentials: 'same-origin' });
      if (!response.ok) throw new Error('unavailable');
      const blob = await response.blob();
      const ctx = new OfflineAudioContext(1, 2, 16000);
      const buffer = await ctx.decodeAudioData(await blob.arrayBuffer());
      const data = buffer.getChannelData(0); const bars = 48; const size = Math.floor(data.length / bars) || 1;
      const peaks = Array.from({ length: bars }, (_, i) => { let m = 0; for (let j = i * size; j < (i + 1) * size && j < data.length; j += 4) m = Math.max(m, Math.abs(data[j])); return m; });
      const top = Math.max(...peaks) || 1;
      entry = { url: URL.createObjectURL(blob), peaks: peaks.map((p) => p / top), duration: buffer.duration };
      waveCache.set(src, entry);
    }
    const barNodes = node.querySelectorAll('.wave-bars i');
    entry.peaks.forEach((p, i) => { if (barNodes[i]) barNodes[i].style.height = `${Math.max(10, p * 100)}%`; });
    node.querySelector('.time').textContent = fmt(entry.duration);
    node.entry = entry;
  } catch { node.classList.add('error'); const t = node.querySelector('.time'); if (t) t.textContent = '—'; }
}
const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

function setPlayIcon(node, playing) { const b = node.querySelector('.play'); b.innerHTML = icon(playing ? 'pause' : 'play'); b.classList.toggle('playing', playing); }
function toggleWave(node, seekRatio = null) {
  const entry = node.entry; if (!entry) return;
  if (!node.audio) {
    node.audio = new Audio(entry.url);
    node.audio.addEventListener('timeupdate', () => {
      const r = node.audio.currentTime / (entry.duration || 1);
      node.querySelectorAll('.wave-bars i').forEach((bar, i, all) => bar.classList.toggle('on', i / all.length <= r));
      node.querySelector('.time').textContent = fmt(node.audio.currentTime);
    });
    node.audio.addEventListener('ended', () => { window.__pbPlaying = null; setPlayIcon(node, false); node.querySelectorAll('.wave-bars i').forEach((b) => b.classList.remove('on')); node.querySelector('.time').textContent = fmt(entry.duration); });
    node.audio.addEventListener('pause', () => { if (window.__pbPlaying === node.audio) window.__pbPlaying = null; setPlayIcon(node, false); });
  }
  if (seekRatio !== null) node.audio.currentTime = seekRatio * (entry.duration || 0);
  if (node.audio.paused || seekRatio !== null) {
    document.querySelectorAll('.wave-player').forEach((other) => { if (other !== node && other.audio && !other.audio.paused) other.audio.pause(); });
    node.audio.play(); window.__pbPlaying = node.audio; setPlayIcon(node, true);
  } else node.audio.pause();
}

// -------------------------------------------------------------- tab binding

function bindTab() {
  $('mic')?.addEventListener('click', startMic);
  $('upload-audio')?.addEventListener('click', () => $('audio-upload').click());
  $('audio-upload')?.addEventListener('change', (e) => { if (e.target.files[0]) sendRecording(e.target.files[0], 'the recording'); e.target.value = ''; });
  $('sample-audio')?.addEventListener('click', () => sendRecording(null, 'the sample launching'));
  $('register-search')?.addEventListener('input', debounce((e) => { state.registerQuery = e.target.value; renderTab(); focusEnd('register-search'); }));
  $('guest-search')?.addEventListener('input', debounce((e) => { state.guestQuery = e.target.value; renderTab(); focusEnd('guest-search'); }));
  root.querySelectorAll('[data-filter]').forEach((b) => b.addEventListener('click', () => { state.registerFilter = b.dataset.filter; renderTab(); }));
  $('guest-form')?.addEventListener('submit', async (e) => {
    e.preventDefault(); const button = e.target.querySelector('button[type=submit]'); button.disabled = true;
    try { const guest = await api(`/api/events/${state.eventId}/guests`, { method: 'POST', body: formData(e.target) }); toast(`${guestName(guest)} added to the guest list.`); e.target.reset(); await reloadEvent(); }
    catch (error) { showError(error.message); button.disabled = false; }
  });
  const drop = $('dropzone');
  if (drop) {
    const take = async (file) => {
      if (!file) return;
      try { const form = new FormData(); form.append('file', file, file.name); state.importPreview = await api(`/api/events/${state.eventId}/guests/import/preview`, { method: 'POST', body: form }); renderTab(); }
      catch (error) { showError(error.message); }
    };
    $('guest-csv').addEventListener('change', (e) => take(e.target.files[0]));
    drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('over'));
    drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('over'); take(e.dataTransfer.files[0]); });
  }
  $('details-form')?.addEventListener('submit', async (e) => {
    e.preventDefault(); const d = formData(e.target);
    try { state.event = await api(`/api/events/${state.eventId}`, { method: 'PATCH', body: { ...d, target: Number(d.target || 0), minimum: Number(d.minimum || 0), maximum: Number(d.maximum || 0) } }); toast('Event details saved.'); renderEventShell(); }
    catch (error) { showError(error.message); }
  });
  root.querySelectorAll('[data-picker]').forEach((input) => {
    input.addEventListener('focus', () => renderPicker(input));
    input.addEventListener('input', () => renderPicker(input));
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); root.querySelector(`[data-picker-list="${input.dataset.picker}"] [data-pick]`)?.click(); } if (e.key === 'Escape') root.querySelector(`[data-picker-list="${input.dataset.picker}"]`).hidden = true; });
    input.addEventListener('blur', () => setTimeout(() => { const list = root.querySelector(`[data-picker-list="${input.dataset.picker}"]`); if (list) list.hidden = true; }, 180));
  });
}
function debounce(fn, ms = 250) { let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); }; }
function focusEnd(id) { const s = $(id); if (s) { s.focus(); s.setSelectionRange(s.value.length, s.value.length); } }

// -------------------------------------------------------------- click actions

document.addEventListener('click', async (event) => {
  const menuButton = event.target.closest('#menu-button');
  if (menuButton) { const list = $('menu-list'); list.hidden = !list.hidden; menuButton.setAttribute('aria-expanded', String(!list.hidden)); return; }
  if (!event.target.closest('.menu')) closeMenu();
  const bars = event.target.closest('.wave-bars');
  if (bars && bars.closest('.wave-player')?.entry) { const node = bars.closest('.wave-player'); const rect = bars.getBoundingClientRect(); toggleWave(node, Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width))); return; }
  const target = event.target.closest('button,[data-copy]');
  if (!target || !root.contains(target)) return;
  const d = target.dataset;
  const pledgeById = (id) => state.event?.pledges.find((p) => p.id === Number(id));
  try {
    if (d.signOut !== undefined) { stopEverything(); await api('/api/auth/logout', { method: 'POST' }).catch(() => {}); state.me = false; location.href = '/'; return; }
    if (d.themeToggle !== undefined) { const dark = document.documentElement.dataset.theme === 'dark' || (!document.documentElement.dataset.theme && matchMedia('(prefers-color-scheme: dark)').matches); document.documentElement.dataset.theme = dark ? 'light' : 'dark'; try { localStorage.setItem('pb-theme', document.documentElement.dataset.theme); } catch { /* storage unavailable */ } closeMenu(); return; }
    if (d.switchOrg) { state.me = await api('/api/me/organisation', { method: 'POST', body: { org_id: d.switchOrg } }); stopEverything(); if (location.hash === '#/events') route(); else go('#/events'); return; }
    if (d.fullscreen !== undefined) { if (document.fullscreenElement) document.exitFullscreen(); else $('bs-root')?.requestFullscreen?.(); return; }
    const wave = target.closest('.wave-player');
    if (wave && target.classList.contains('play')) { toggleWave(wave); return; }
    if (d.pick) return resolve(d.pick, { action: 'guest', guest_id: Number(d.guest) });
    if (d.changeGuest) {
      const data = await ask({ title: 'Change the guest', iconName: 'users', fields: `<label class="field">Guest<input name="label" list="all-guests" required placeholder="Type a name"></label><datalist id="all-guests">${state.event.guests.map((g) => `<option value="${esc(guestName(g))}"></option>`).join('')}</datalist>` });
      if (!data) return;
      const wanted = data.label.trim().toLowerCase();
      const guest = state.event.guests.find((g) => guestName(g).toLowerCase() === wanted || g.name.toLowerCase() === wanted);
      if (!guest) { showError('Choose a guest from the list.'); return; }
      return resolve(d.changeGuest, { action: 'guest', guest_id: guest.id });
    }
    if (d.walkIn) {
      const data = await ask({ title: 'Add a walk-in guest', iconName: 'userPlus', submit: 'Add and assign', body: '<p class="muted">They join the guest list and the live listening list straight away, so their next mention is recognised.</p>', fields: '<div class="form-grid"><label class="field">Title <span class="hint">Optional</span><input name="walk_in_title" placeholder="Chief, Mrs…"></label><label class="field">Full name<input name="walk_in_name" required></label></div>' });
      if (data) return resolve(d.walkIn, { action: 'walk_in', ...data });
      return;
    }
    if (d.useRecheck) return resolve(d.useRecheck, { action: 'amount', amount: Number(d.value) });
    if (d.anonymous) return resolve(d.anonymous, { action: 'anonymous' });
    if (d.keep) return resolve(d.keep, { action: 'keep' });
    if (d.replace) return resolve(d.replace, { action: 'replace_earlier' });
    if (d.fixAmount) {
      const p = pledgeById(d.fixAmount);
      const data = await ask({ title: 'Enter the amount', iconName: 'pencil', body: '<p class="muted">The amount the recording clearly says, in naira.</p>', fields: `<label class="field">Amount<div class="amount-input"><span>₦</span><input class="input" name="amount" type="number" min="1" required value="${p?.amount ?? ''}"></div></label>` });
      if (data) return resolve(d.fixAmount, { action: 'amount', amount: Number(data.amount) });
      return;
    }
    if (d.reject) {
      const data = await ask({ title: 'Not a pledge?', iconName: 'x', submit: 'Reject line', danger: true, fields: '<label class="field">Reason<input name="reason" required placeholder="For example: the MC was reading the order of service"></label>' });
      if (data) return resolve(d.reject, { action: 'reject', reason: data.reason });
      return;
    }
    if (d.inviteUsher !== undefined) return inviteDialog('usher', state.eventId);
    if (d.editGuest) {
      const guest = state.event.guests.find((g) => g.id === Number(d.editGuest));
      const data = await ask({ title: `Edit ${guestName(guest)}`, iconName: 'pencil', fields: `<div class="form-grid">${guestFields(guest)}</div>` });
      if (!data) return;
      await api(`/api/events/${state.eventId}/guests/${guest.id}`, { method: 'PATCH', body: data }); toast('Guest updated.'); return reloadEvent();
    }
    if (d.removeGuest) {
      const guest = state.event.guests.find((g) => g.id === Number(d.removeGuest));
      if (!await ask({ title: `Remove ${guestName(guest)}?`, iconName: 'trash', submit: 'Remove', danger: true, body: '<p>They leave the guest list and the listening list. Pledges they already made keep their name.</p>' })) return;
      await api(`/api/events/${state.eventId}/guests/${guest.id}`, { method: 'DELETE' }); toast('Guest removed.'); return reloadEvent();
    }
    if (d.guestHistory) {
      const h = await api(`/api/events/${state.eventId}/guests/${d.guestHistory}/history`);
      await ask({ title: guestName(h.guest), iconName: 'clock', submit: '', wide: true, body: `<div class="row wrap">${h.pledges.map((p) => `<span class="chip">#${p.id} ${p.item ? esc(p.item) : money(p.amount, p.currency)} · ${STATE_LABELS[p.state]}</span>`).join('') || '<span class="muted">No pledges yet.</span>'}</div><ol class="activity">${h.history.map(activityItem).join('') || '<li class="block">No history.</li>'}</ol>` });
      return;
    }
    if (d.cancelImport !== undefined) { state.importPreview = null; return renderTab(); }
    if (d.confirmImport !== undefined) {
      const result = await api(`/api/events/${state.eventId}/guests/import`, { method: 'POST', body: { rows: state.importPreview.rows.filter((r) => r.status === 'ok') } });
      state.importPreview = null; state.event = result.state; toast(`${plural(result.imported, 'guest')} added.`); return renderEventShell();
    }
    if (d.send) return sendDialog(Number(d.send));
    if (d.logCall) {
      const data = await ask({ title: 'Log a phone call', iconName: 'phone', body: '<p class="muted">Record what happened on a call you made from your own phone.</p>', fields: `<label class="field">Outcome<select name="outcome">${['promised', 'paid', 'disputed', 'no_answer', 'left_message', 'wrong_number', 'declined', 'opted_out'].map((o) => `<option value="${o}">${OUTCOME_LABELS[o]}</option>`).join('')}</select></label><label class="field">Promised date <span class="hint">If they promised</span><input name="promised_date" type="date"></label><label class="field">Notes<textarea name="notes" rows="3"></textarea></label>` });
      if (!data) return;
      await api(`/api/events/${state.eventId}/pledges/${d.logCall}/calls`, { method: 'POST', body: data }); toast('Call logged.'); return reloadEvent();
    }
    if (d.offline) {
      const p = pledgeById(d.offline);
      const data = await ask({ title: 'Record a payment', iconName: 'wallet', body: '<p class="muted">For money received outside Paystack, such as cash or a bank transfer.</p>', fields: `<label class="field">Amount<div class="amount-input"><span>₦</span><input class="input" name="amount" type="number" min="1" required value="${Math.max(0, (p.amount || 0) - (p.received || 0))}"></div></label><label class="field">Method<select name="method"><option value="transfer">Bank transfer</option><option value="cash">Cash</option><option value="pos">POS</option><option value="cheque">Cheque</option><option value="other">Other</option></select></label><label class="field">Note<input name="note" placeholder="Receipt number or bank reference"></label>` });
      if (!data) return;
      const result = await api(`/api/events/${state.eventId}/pledges/${d.offline}/payments/offline`, { method: 'POST', body: { ...data, amount: Number(data.amount) } });
      toast(result.redeemed ? 'Payment recorded. This pledge is paid in full.' : 'Payment recorded.'); return reloadEvent();
    }
    if (d.verify) {
      const result = await api(`/api/events/${state.eventId}/pledges/${d.verify}/payment/verify`, { method: 'POST' });
      toast(result.results.map((r) => r.error || (r.status === 'success' ? 'Payment received' : `Paystack says ${r.status}`)).join('; ') || 'No open checkouts to check.'); return reloadEvent();
    }
    if (d.copy) { toast(await copyText(d.copy) ? 'Link copied.' : d.copy); return; }
    if (d.closeLink) {
      if (!await ask({ title: 'Close this pledge page?', iconName: 'lock', submit: 'Close page', danger: true, body: '<p>The guest will no longer be able to open it. You can send a new one later.</p>' })) return;
      await api(`/api/events/${state.eventId}/pledges/${d.closeLink}/link/close`, { method: 'POST' }); toast('Pledge page closed.'); return reloadEvent();
    }
    if (d.moreActivity !== undefined) return loadActivity(false);
    if (d.deleteEvent !== undefined) {
      const data = await ask({ title: 'Delete this event permanently?', iconName: 'trash', submit: 'Delete forever', danger: true, body: `<p>Type <b>${esc(state.event.event.name)}</b> to confirm.</p>`, fields: '<label class="field">Event name<input name="confirm_name" required autocomplete="off"></label>' });
      if (!data) return;
      await api(`/api/events/${state.eventId}/delete`, { method: 'POST', body: data });
      stopEverything(); toast('Event deleted.'); go('#/events');
    }
  } catch (error) { showError(error.message); }
});

async function sendDialog(pledgeId) {
  const p = state.event.pledges.find((x) => x.id === pledgeId);
  const guest = state.event.guests.find((g) => g.id === p.guest_id);
  const channels = [['whatsapp', 'WhatsApp', 'message', !!guest.phone], ['sms', 'SMS', 'phone', !!guest.phone], ['email', 'Email', 'mail', !!guest.email && state.event.email_configured], ['copy', 'Copy link', 'link', true]];
  const first = channels.findIndex((c) => c[3]);
  const data = await ask({
    title: `Send ${guestName(guest)} their pledge page`, iconName: 'send', submit: 'Continue',
    body: '<p class="muted">The page is private to this pledge and expires automatically. WhatsApp and SMS open on this device with the message ready for you to send.</p>',
    fields: `<div class="channels">${channels.map(([v, label, ic, ok], i) => `<label class="channel ${ok ? '' : 'off'}"><input type="radio" name="channel" value="${v}" ${ok ? '' : 'disabled'} ${i === first ? 'checked' : ''}><span>${icon(ic)} ${label}</span></label>`).join('')}</div>${!guest.phone ? '<p class="tiny faint">Add a phone number to send by WhatsApp or SMS.</p>' : ''}`,
  });
  if (!data) return;
  const result = await api(`/api/events/${state.eventId}/pledges/${pledgeId}/deliver`, { method: 'POST', body: data });
  if (result.open) window.open(result.open, '_blank', 'noopener');
  else if (data.channel === 'copy') toast(await copyText(result.url) ? 'Link copied. Paste it into your message.' : result.url);
  else if (result.ok) toast('Email sent.'); else showError(result.error);
  reloadEvent();
}

async function inviteDialog(role, eventId = '') {
  const data = await ask({ title: role === 'usher' ? 'Invite an usher' : 'Invite staff', iconName: 'userPlus', submit: 'Create invitation', fields: `${eventId ? '' : '<label class="field">Role<select name="role"><option value="usher">Usher — review queue and register only</option><option value="admin">Admin — runs events</option></select></label>'}<label class="field">Email <span class="hint">Optional; only this email can accept</span><input name="email" type="email"></label>` });
  if (!data) return;
  try {
    const invite = await api('/api/organisation/invites', { method: 'POST', body: { role: data.role || role, email: data.email || '', event_id: eventId } });
    await ask({ title: 'Invitation ready', iconName: 'qr', submit: '', body: `<p class="muted">${invite.emailed ? 'We emailed the invitation. ' : ''}Scan the code on their phone, or send the link. It works once and expires in 7 days.</p><div class="qr-frame">${invite.qr_svg}</div><p><code>${esc(invite.url)}</code></p><button type="button" class="btn btn-ghost" data-copy="${esc(invite.url)}">${icon('copy')} Copy link</button>` });
    if (location.hash.startsWith('#/settings')) renderSettings('staff');
  } catch (error) { showError(error.message); }
}

// ---------------------------------------------------------------- settings

async function renderSettings(tab) {
  document.title = 'Settings · Pledgebook';
  const owner = state.me.permissions.includes('settings');
  const tabs = [['organisation', 'Organisation', 'building'], ...(owner ? [['staff', 'Team', 'users']] : []), ['usage', 'Usage and services', 'zap']];
  renderShell(`<div class="page-head"><div><div class="meta">${icon('building')} ${esc(state.me.organisation.name)}</div><h1>Settings</h1></div></div>
    <div class="workspace"><nav class="side-nav">${tabs.map(([k, l, ic]) => `<a class="${tab === k ? 'active' : ''}" href="#/settings/${k}">${icon(ic)} ${l}</a>`).join('')}</nav><div class="content" id="settings-content">${skeleton(2)}</div></div>`, 'settings');
  const node = $('settings-content');
  try {
    const data = await api('/api/organisation');
    if (tab === 'organisation') {
      const o = data.organisation;
      node.innerHTML = `<div class="card"><div class="section-title mb"><span class="icon-tile">${icon('building')}</span><div><h2>${esc(o.name)}</h2><p class="muted small">Created ${when(o.created_at)}</p></div></div>
        <form id="org-form" class="form-grid"><label class="field full">Name<input name="name" required value="${esc(o.name)}" ${owner ? '' : 'disabled'}></label>
        <label class="field">Keep event audio for <span class="hint">days after the event ends</span><input name="retention_days" type="number" min="7" max="3650" value="${o.retention_days}" ${owner ? '' : 'disabled'}></label>
        <label class="field">Pledge pages expire after <span class="hint">days</span><input name="link_expiry_days" type="number" min="1" max="90" value="${o.link_expiry_days}" ${owner ? '' : 'disabled'}></label>
        <div class="notice plain full">${icon('shield')}<span>Currency is Nigerian naira. Pledges heard in other currencies are shown separately and settled offline. Ledger, payment and activity records stay until you delete an event; audio is deleted on the schedule above. Sample events delete themselves after 24 hours.</span></div>
        ${owner ? `<div class="full"><button class="btn btn-primary" type="submit">${icon('check')} Save</button></div>` : '<p class="muted full">Only an owner can change these.</p>'}</form></div>`;
      $('org-form')?.addEventListener('submit', async (e) => {
        e.preventDefault(); const f = formData(e.target);
        try { await api('/api/organisation', { method: 'PATCH', body: { ...f, retention_days: Number(f.retention_days), link_expiry_days: Number(f.link_expiry_days) } }); state.me = await api('/api/me'); toast('Organisation saved.'); renderSettings('organisation'); }
        catch (error) { showError(error.message); }
      });
    } else if (tab === 'staff' && owner) {
      const staff = await api('/api/organisation/staff');
      node.innerHTML = `<div class="card"><div class="card-head"><div><h2>Team</h2><p class="muted small">Owners manage settings and the team. Admins run events, guests and follow-up. Ushers resolve the review queue without seeing contact details.</p></div><button class="btn btn-primary" id="invite-staff">${icon('userPlus')} Invite</button></div>
        ${staff.members.map((m) => `<div class="member-row">${avatar(m.name)}<div class="grow"><b>${esc(m.name)}</b>${m.id === state.me.user.id ? ' <span class="chip brand">You</span>' : ''}<div class="small muted">${esc(m.email)} · joined ${when(m.created_at)}</div></div>${m.id === state.me.user.id ? `<span class="chip">${esc(m.role)}</span>` : `<div class="row"><select class="input compact" data-member-role="${m.id}" aria-label="Role">${['owner', 'admin', 'usher'].map((r) => `<option ${r === m.role ? 'selected' : ''}>${r}</option>`).join('')}</select><button class="btn btn-danger-quiet btn-icon" data-remove-member="${m.id}" title="Remove" aria-label="Remove">${icon('trash')}</button></div>`}</div>`).join('')}</div>
        <div class="card"><div class="card-head"><h2>Open invitations</h2></div>${staff.invites.map((i) => `<div class="member-row"><span class="avatar sm anon">${icon('mail')}</span><div class="grow"><b>${esc(i.role)}</b>${i.email ? ` · ${esc(i.email)}` : ''}${i.event_name ? ` · for ${esc(i.event_name)}` : ''}<div class="small muted">expires ${when(i.expires_at)}</div></div><button class="btn btn-danger-quiet btn-sm" data-revoke-invite="${i.id}">Revoke</button></div>`).join('') || empty('people', 'No open invitations', 'Invitations you create appear here until they are used.')}</div>`;
      $('invite-staff').addEventListener('click', () => inviteDialog('admin'));
      node.querySelectorAll('[data-member-role]').forEach((s) => s.addEventListener('change', async () => { try { await api(`/api/organisation/members/${s.dataset.memberRole}`, { method: 'PATCH', body: { role: s.value } }); toast('Role updated.'); } catch (error) { showError(error.message); renderSettings('staff'); } }));
      node.querySelectorAll('[data-remove-member]').forEach((b) => b.addEventListener('click', async () => { if (!await ask({ title: 'Remove this person?', iconName: 'trash', submit: 'Remove', danger: true, body: '<p>They lose access to every event in this organisation immediately.</p>' })) return; try { await api(`/api/organisation/members/${b.dataset.removeMember}`, { method: 'DELETE' }); toast('Removed.'); renderSettings('staff'); } catch (error) { showError(error.message); } }));
      node.querySelectorAll('[data-revoke-invite]').forEach((b) => b.addEventListener('click', async () => { try { await api(`/api/organisation/invites/${b.dataset.revokeInvite}`, { method: 'DELETE' }); toast('Invitation revoked.'); renderSettings('staff'); } catch (error) { showError(error.message); } }));
    } else {
      const u = data.usage;
      const item = (label, ic, used, limit, unit = '') => `<div class="usage-item"><div class="row between"><span class="row">${icon(ic)} ${label}</span><span class="num muted">${used}${unit} of ${limit}${unit}</span></div><div class="bar"><span style="width:${Math.min(100, (used / Math.max(1, limit)) * 100)}%"></span></div></div>`;
      const modeText = data.payments.mode === 'live' ? ['brand', 'Live', 'Real payments are accepted.'] : data.payments.mode === 'test' ? ['gold', 'Test mode', 'Checkouts use test cards and no real money moves.'] : ['', 'Not configured', 'Guests can still promise dates and staff can record offline payments.'];
      node.innerHTML = `<div class="settings-grid"><div class="card"><div class="card-head"><div><h2>Today's usage</h2><p class="muted small">Resets at midnight UTC.</p></div></div><div class="usage-list">
          ${item('Listening', 'mic', Math.round(u.used.audio_seconds / 60), Math.round(u.limits.audio_seconds / 60), ' min')}${item('Voice assistant conversations', 'message', u.used.assistant_sessions, u.limits.assistant_sessions)}${item('New events', 'calendar', u.used.events_created, u.limits.events_created)}${item('Emails', 'mail', u.used.emails_sent, u.limits.emails_sent)}</div></div>
        <div class="card"><div class="card-head"><h2>Payments and messages</h2></div><div class="stack">
          <div class="row wrap"><b>Paystack</b><span class="chip ${modeText[0]}">${modeText[1]}</span><span class="muted small">${modeText[2]}</span></div>
          <div class="field">Notification address <span class="hint">Set under Settings → API Keys &amp; Webhooks in Paystack</span><div class="row"><code class="grow">${esc(data.payments.webhook_url)}</code><button class="btn btn-ghost btn-sm" data-copy="${esc(data.payments.webhook_url)}" aria-label="Copy">${icon('copy')}</button></div></div>
          <div class="row wrap"><b>Email</b><span class="chip ${data.email.configured ? 'brand' : ''}">${data.email.configured ? 'On' : 'Off'}</span><span class="muted small">${data.email.configured ? `Sending from ${esc(data.email.from)}` : 'Pages go by WhatsApp, SMS or a copied link.'}</span></div>
          <p class="faint small">These services are configured on the server by whoever runs this Pledgebook installation.</p></div></div></div>`;
    }
  } catch (error) { node.innerHTML = `<div class="card">${empty('calendar', 'Settings could not load', esc(error.message))}</div>`; }
}

try { const saved = localStorage.getItem('pb-theme'); if (saved) document.documentElement.dataset.theme = saved; } catch { /* storage unavailable */ }
route();
