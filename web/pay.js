// The guest's private pledge page: hear the moment, pay, promise, raise a problem,
// or talk to the disclosed voice assistant on this device.

import { icon, logo } from './icons.js';

const token = location.pathname.split('/').filter(Boolean).pop();
const page = document.getElementById('page');
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]));
const money = (value, currency = 'NGN') => currency === 'NGN' ? `₦${Number(value || 0).toLocaleString('en-NG')}` : `${currency} ${Number(value || 0).toLocaleString()}`;
const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
let data = null;
let payAmount = null;
const voice = { socket: null, audio: null, worklet: null, sink: null, source: null, stream: null, playback: null, nextTime: 0, pending: [], session: null };

async function api(path, body) {
  const response = await fetch(`/api/pay/${token}${path}`, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Pledgebook': '1' }, body: JSON.stringify(body),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw Object.assign(new Error(result.detail || `Something went wrong (${response.status})`), { status: response.status });
  return result;
}

function toast(message, kind = 'info') {
  const node = document.createElement('div');
  node.className = `toast ${kind}`;
  node.innerHTML = `${icon(kind === 'error' ? 'alert' : 'checkCircle')}<div>${esc(message)}</div>`;
  document.getElementById('toasts').append(node);
  setTimeout(() => { node.classList.add('leaving'); setTimeout(() => node.remove(), 260); }, kind === 'error' ? 7000 : 4000);
}

function hero(inner) {
  return `<div class="gp-hero"><div><span class="brand">${logo(26)} Pledgebook</span>${inner}</div></div>`;
}

async function load() {
  try { data = await api(''); }
  catch (error) {
    page.innerHTML = `${hero('<div class="gp-org">Private pledge page</div><h1>This page is not available</h1>')}<div class="gp-shell"><div class="card"><p>${esc(error.message)}</p></div></div>`;
    return;
  }
  render();
  const reference = new URLSearchParams(location.search).get('reference');
  if (reference) {
    history.replaceState(null, '', location.pathname);
    toast('Checking your payment with Paystack…');
    try {
      const result = await api('/verify', { reference });
      data = await api('');
      if (result.status === 'success') { render(true); }
      else { render(); toast(`Paystack reports this payment as ${result.status}. If money left your account, please contact the organiser.`, 'error'); }
    } catch (error) { toast(error.message, 'error'); }
  }
}

function render(justPaid = false) {
  const { event, guest, pledge, payments, assistant } = data;
  const paidUp = !pledge.item && pledge.outstanding === 0;
  const pct = pledge.amount ? Math.min(100, (pledge.received / pledge.amount) * 100) : 0;
  if (payAmount === null || payAmount > pledge.outstanding) payAmount = pledge.outstanding;
  const half = Math.max(100, Math.round(pledge.outstanding / 2 / 100) * 100);
  const today = new Date().toISOString().slice(0, 10);
  page.innerHTML = `${hero(`<div class="gp-org">${esc(event.organisation)}</div><h1>Thank you, ${esc(guest.name)}</h1><p>${esc(event.name)} · ${new Date(`${event.event_date}T12:00:00`).toLocaleDateString([], { day: 'numeric', month: 'long', year: 'numeric' })}</p>`)}
  <div class="gp-shell">
    ${justPaid ? `<div class="card center stack"><div class="success-check">${icon('check')}</div><h2>Payment received</h2><p class="muted">${paidUp ? 'Your pledge is paid in full. Thank you for your generosity.' : `Thank you. ${money(pledge.outstanding)} remains whenever you are ready.`}</p></div>` : ''}
    <div class="card"><div class="gp-amount"><div><span class="eyebrow">Your pledge</span><div class="big num">${pledge.item ? esc(pledge.item) : money(pledge.amount, pledge.currency)}</div>
      ${pledge.item ? '<p class="muted small">An in-kind gift. The organiser will arrange it with you.</p>' : `<p class="muted small">${money(pledge.received)} received · ${paidUp ? 'paid in full' : `${money(pledge.outstanding)} to go`}</p>`}</div>
      ${pledge.item ? '' : `<div class="ring" style="--p:${pct}"><div><strong class="num">${Math.round(pct)}%</strong><span>paid</span></div></div>`}</div>
      <hr class="rule-line"><span class="eyebrow">The moment you pledged</span>
      ${pledge.audio ? `<div class="wave-player" id="moment"><button class="play" type="button" aria-label="Play the moment you pledged">${icon('play')}</button><div class="wave-bars">${'<i></i>'.repeat(48)}</div><span class="time num">0:00</span></div>` : `<div class="notice plain mt-sm">${icon('eyeOff')}<span>${esc(pledge.audio_reason)}</span></div>`}
      <p class="said-quote">“${esc(pledge.words || '—')}”</p></div>
    ${!paidUp && payments.available ? `<div class="card stack"><div class="section-title"><span class="icon-tile">${icon('wallet')}</span><div><h2>Pay now</h2><p class="muted small">Pay it all, or part of it today.</p></div></div>
      ${payments.mode === 'test' ? `<div class="notice gold">${icon('info')}<span>This organiser is still testing. Payments here use Paystack test cards and no real money moves.</span></div>` : ''}
      <div class="gp-chips"><button type="button" data-amount="${pledge.outstanding}" class="${payAmount === pledge.outstanding ? 'on' : ''}">Full ${money(pledge.outstanding)}</button>${pledge.outstanding >= 200 ? `<button type="button" data-amount="${half}" class="${payAmount === half ? 'on' : ''}">Half ${money(half)}</button>` : ''}</div>
      <form id="pay-form" class="form-grid single"><label class="field">Amount to pay now<div class="amount-input"><span>₦</span><input class="input" name="amount" type="number" min="100" max="${pledge.outstanding}" value="${payAmount}" required inputmode="numeric"></div></label>
      ${guest.email_known ? '' : '<label class="field">Email for your receipt<input name="email" type="email" required autocomplete="email" placeholder="you@example.com"></label>'}
      <button class="btn btn-primary btn-lg btn-block" type="submit">${icon('lock')} Pay securely with Paystack</button></form>
      <p class="secure">${icon('shield')} Card details go straight to Paystack, never to Pledgebook</p>
      ${payments.mode === 'test' ? '<p class="faint tiny center">Test card 4084 0840 8408 4081 · any future expiry · CVV 408</p>' : ''}</div>` : ''}
    ${paidUp && !justPaid ? `<div class="card center stack"><div class="success-check">${icon('check')}</div><h2>Paid in full</h2><p class="muted">Thank you for your generosity.</p></div>` : ''}
    ${!paidUp ? `<div class="card stack"><div class="section-title"><span class="icon-tile">${icon('calendar')}</span><div><h2>Pay later</h2><p class="muted small">${pledge.promised_date ? `You planned to pay on ${new Date(`${pledge.promised_date}T12:00:00`).toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' })}.` : 'Let the organiser know when to expect it.'}</p></div></div>
      <form id="promise-form" class="inline-form"><label class="field grow">I plan to pay on<input name="promised_date" type="date" min="${today}" required></label><button class="btn btn-ghost" type="submit">${icon('check')} Save date</button></form></div>` : ''}
    ${assistant.available && !paidUp ? `<div class="card stack"><div class="section-title"><span class="icon-tile">${icon('message')}</span><div><h2>Talk it through</h2><p class="muted small">Speak with an <b>automated voice assistant</b> on this device. It uses a generated voice and your microphone, can take you to payment, note a date, record a concern or stop reminders — and it cannot change your pledge. Up to 3 conversations a day on this page.</p></div></div>
      <div class="orb" id="orb" hidden></div><div class="transcript" id="transcript" hidden></div>
      <div class="row wrap"><button id="voice-start" class="btn btn-ghost">${icon('mic')} Start talking</button><button id="voice-end" class="btn btn-danger-quiet" hidden>${icon('stop')} End conversation</button></div>
      <div id="voice-pay" hidden></div></div>` : ''}
    <div class="card"><details class="plain"><summary>${icon('flag')} Something not right? ${icon('chevronDown')}</summary>
      <form id="dispute-form" class="form-grid single mt"><label class="field">Tell the organiser what is wrong<textarea name="what_they_said" rows="3" minlength="3" required placeholder="For example: I pledged ₦50,000, not ₦500,000"></textarea></label><button class="btn btn-ghost" type="submit">${icon('send')} Send to the organiser</button></form>
      ${pledge.stopped ? '<p class="muted small mt">You will not receive more reminders about this pledge.</p>' : `<p class="mt"><button id="stop" class="btn btn-quiet btn-sm" type="button">${icon('eyeOff')} Stop reminders about this pledge</button></p>`}</details></div>
    <p class="faint tiny center">Private page for ${esc(guest.name)} · expires ${new Date(data.expires_at).toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' })} · Pledgebook</p>
  </div>`;
  bind();
}

function bind() {
  document.querySelectorAll('[data-amount]').forEach((b) => b.addEventListener('click', () => {
    payAmount = Number(b.dataset.amount);
    const input = document.querySelector('#pay-form input[name=amount]'); if (input) input.value = payAmount;
    document.querySelectorAll('[data-amount]').forEach((x) => x.classList.toggle('on', x === b));
  }));
  document.querySelector('#pay-form input[name=amount]')?.addEventListener('input', (e) => {
    payAmount = Number(e.target.value || 0);
    document.querySelectorAll('[data-amount]').forEach((x) => x.classList.toggle('on', Number(x.dataset.amount) === payAmount));
  });
  document.getElementById('pay-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.target));
    const button = event.target.querySelector('button'); button.disabled = true; button.innerHTML = `${icon('lock')} Opening Paystack…`;
    try { const result = await api('/checkout', { amount: Number(form.amount), email: form.email || '' }); location.href = result.checkout_url; }
    catch (error) { toast(error.message, 'error'); button.disabled = false; button.innerHTML = `${icon('lock')} Pay securely with Paystack`; }
  });
  document.getElementById('promise-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    try { await api('/promise', Object.fromEntries(new FormData(event.target))); data = await api(''); render(); toast('Thank you. The organiser can see the date you chose.'); }
    catch (error) { toast(error.message, 'error'); }
  });
  document.getElementById('dispute-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      await api('/dispute', Object.fromEntries(new FormData(event.target)));
      page.innerHTML = `${hero('<div class="gp-org">Thank you for telling us</div><h1>The organiser will review this pledge</h1>')}<div class="gp-shell"><div class="card center stack"><div class="success-check">${icon('check')}</div><p class="muted">They will contact you. This page is now closed.</p></div></div>`;
    } catch (error) { toast(error.message, 'error'); }
  });
  document.getElementById('stop')?.addEventListener('click', async () => {
    try { await api('/stop', {}); data = await api(''); render(); toast('You will not receive more reminders about this pledge.'); }
    catch (error) { toast(error.message, 'error'); }
  });
  document.getElementById('voice-start')?.addEventListener('click', startVoice);
  document.getElementById('voice-end')?.addEventListener('click', () => endVoice(true));
  const moment = document.getElementById('moment');
  if (moment) loadMoment(moment);
}

// --------------------------------------------------------- the pledge moment

async function loadMoment(node) {
  try {
    const blob = await (await fetch(`/api/pay/${token}/audio`)).blob();
    const buffer = await new OfflineAudioContext(1, 2, 16000).decodeAudioData(await blob.arrayBuffer());
    const samples = buffer.getChannelData(0); const size = Math.floor(samples.length / 48) || 1;
    const peaks = Array.from({ length: 48 }, (_, i) => { let m = 0; for (let j = i * size; j < (i + 1) * size && j < samples.length; j += 4) m = Math.max(m, Math.abs(samples[j])); return m; });
    const top = Math.max(...peaks) || 1;
    const bars = node.querySelectorAll('.wave-bars i');
    peaks.forEach((p, i) => { bars[i].style.height = `${Math.max(10, (p / top) * 100)}%`; });
    node.querySelector('.time').textContent = fmt(buffer.duration);
    const audio = new Audio(URL.createObjectURL(blob));
    const button = node.querySelector('.play');
    const setIcon = (playing) => { button.innerHTML = icon(playing ? 'pause' : 'play'); button.classList.toggle('playing', playing); };
    audio.addEventListener('timeupdate', () => { const r = audio.currentTime / buffer.duration; bars.forEach((b, i) => b.classList.toggle('on', i / bars.length <= r)); node.querySelector('.time').textContent = fmt(audio.currentTime); });
    audio.addEventListener('ended', () => { setIcon(false); bars.forEach((b) => b.classList.remove('on')); node.querySelector('.time').textContent = fmt(buffer.duration); });
    audio.addEventListener('pause', () => setIcon(false));
    button.addEventListener('click', () => { if (audio.paused) { audio.play(); setIcon(true); } else audio.pause(); });
    node.querySelector('.wave-bars').addEventListener('click', (e) => { const rect = e.currentTarget.getBoundingClientRect(); audio.currentTime = ((e.clientX - rect.left) / rect.width) * buffer.duration; audio.play(); setIcon(true); });
  } catch { node.classList.add('error'); node.querySelector('.time').textContent = '—'; }
}

// ------------------------------------------------------------ voice assistant

function tools() {
  return [
    { type: 'function', name: 'confirm_identity', description: 'Record whether the person speaking is the named guest. Pass true only after a clear yes to the question of who they are. Call this before discussing the pledge.', parameters: { type: 'object', properties: { is_correct_person: { type: 'boolean' } }, required: ['is_correct_person'], additionalProperties: false } },
    { type: 'function', name: 'open_checkout', description: 'Show a Paystack payment button on the guest\'s screen for the full outstanding amount.', parameters: { type: 'object', properties: {}, additionalProperties: false } },
    { type: 'function', name: 'record_promise', description: 'Record the date the guest plans to pay, as YYYY-MM-DD.', parameters: { type: 'object', properties: { promised_date: { type: 'string' } }, required: ['promised_date'], additionalProperties: false } },
    { type: 'function', name: 'record_dispute', description: 'Record what the guest says is wrong with the pledge, in their words.', parameters: { type: 'object', properties: { what_they_said: { type: 'string' } }, required: ['what_they_said'], additionalProperties: false } },
    { type: 'function', name: 'record_opt_out', description: 'Record that the guest does not want reminders about this pledge.', parameters: { type: 'object', properties: {}, additionalProperties: false } },
    { type: 'function', name: 'end_call', description: 'Record the outcome and end the conversation.', parameters: { type: 'object', properties: { outcome: { type: 'string', enum: ['checkout_opened', 'promised', 'disputed', 'declined', 'opted_out', 'wrong_person', 'incomplete'] } }, required: ['outcome'], additionalProperties: false } },
  ];
}

function say(who, text) {
  const node = document.getElementById('transcript');
  if (!node || !text) return;
  node.hidden = false;
  const p = document.createElement('p'); p.className = who; p.textContent = text;
  node.append(p); node.scrollTop = node.scrollHeight;
}

async function startVoice() {
  const start = document.getElementById('voice-start');
  start.disabled = true; start.innerHTML = `${icon('mic')} Connecting…`;
  try {
    const session = await api('/assistant', {});
    voice.session = session;
    const today = new Date().toISOString().slice(0, 10);
    const prompt = `You are the automated Pledgebook assistant for ${session.event.organisation}, speaking with someone who opened the private pledge page for ${session.guest_name} from ${session.event.name} on ${session.event.event_date}. Today is ${today}. Say plainly that you are an automated assistant. Ask whether you are speaking with ${session.guest_name}. Call confirm_identity with true only if they clearly say yes; if they say no, are unsure, or the answer is unclear or unrelated, ask once more, and if it is still not a clear yes call confirm_identity with false. Do not discuss the pledge before identity is confirmed. If it is not confirmed, apologise, call end_call with wrong_person and stop. If confirmed, thank them for their pledge; the amount still to pay is ${session.amount_label}. Offer three choices: pay now (call open_checkout, then tell them to press the payment button on their screen), choose a date to pay (call record_promise with a YYYY-MM-DD date), or tell you if something is wrong (call record_dispute with their words). If they want no more reminders, call record_opt_out. Never change or negotiate the amount, never pressure them, and never invent a payment link. Keep it short and warm, then call end_call.`;
    voice.socket = new WebSocket(`wss://agents.assemblyai.com/v1/ws?token=${encodeURIComponent(session.token)}`);
    voice.socket.onopen = async () => {
      voice.socket.send(JSON.stringify({ type: 'session.update', session: { system_prompt: prompt, greeting: `Hello, I am the automated Pledgebook assistant for ${session.event.organisation}. Am I speaking with ${session.guest_name}?`, input: { format: { encoding: 'audio/pcm' } , keyterms: [session.guest_name] }, output: { voice: 'anna', format: { encoding: 'audio/pcm' } }, tools: tools() } }));
      await startMicrophone();
      document.getElementById('orb').hidden = false;
      document.getElementById('voice-end').hidden = false;
      start.hidden = true;
    };
    voice.socket.onmessage = async (raw) => {
      const event = JSON.parse(raw.data);
      if (event.type === 'reply.audio') play(event.data);
      else if (event.type === 'transcript.agent') say('agent', event.text);
      else if (event.type === 'transcript.user') say('you', event.text);
      else if (event.type === 'tool.call') voice.pending.push(event);
      else if (event.type === 'reply.done') await flushTools();
      else if (event.type === 'session.ended') endVoice(false);
      else if (event.type === 'error') toast('The assistant reported a problem. You can use the buttons on this page instead.', 'error');
    };
    voice.socket.onerror = () => { toast('The assistant could not connect. You can use the buttons on this page instead.', 'error'); endVoice(false); };
    voice.socket.onclose = () => endVoice(false);
  } catch (error) {
    start.disabled = false; start.innerHTML = `${icon('mic')} Start talking`;
    toast(error.name === 'NotAllowedError' ? 'Microphone permission was denied. You can use the buttons on this page instead.' : error.message, 'error');
  }
}

async function flushTools() {
  while (voice.pending.length && voice.socket?.readyState === WebSocket.OPEN) {
    const call = voice.pending.shift();
    let result;
    try { result = await api(`/assistant/${voice.session.call_id}/tool`, { session_id: voice.session.session_id, tool: call.name, arguments: call.arguments || {} }); }
    catch (error) { result = { ok: false, error: error.message }; }
    if (call.name === 'open_checkout' && result.checkout_url) {
      const box = document.getElementById('voice-pay');
      box.hidden = false;
      box.innerHTML = `<a class="btn btn-primary btn-lg btn-block" href="${esc(result.checkout_url)}">${icon('lock')} Pay ${esc(voice.session.amount_label)} with Paystack</a>`;
      delete result.checkout_url;
    }
    voice.socket.send(JSON.stringify({ type: 'tool.result', call_id: call.call_id, result: JSON.stringify(result), is_error: result.ok === false }));
  }
}

async function startMicrophone() {
  voice.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
  voice.audio = new AudioContext(); await voice.audio.resume(); await voice.audio.audioWorklet.addModule('/static/voice-worklet.js');
  voice.source = voice.audio.createMediaStreamSource(voice.stream); voice.worklet = new AudioWorkletNode(voice.audio, 'pledgebook-voice-pcm');
  voice.sink = voice.audio.createGain(); voice.sink.gain.value = 0;
  voice.source.connect(voice.worklet); voice.worklet.connect(voice.sink); voice.sink.connect(voice.audio.destination);
  voice.worklet.port.onmessage = (event) => {
    if (voice.socket?.readyState !== WebSocket.OPEN) return;
    const bytes = new Uint8Array(event.data); let binary = '';
    for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    voice.socket.send(JSON.stringify({ type: 'input.audio', audio: btoa(binary) }));
  };
}

function play(encoded) {
  if (!encoded) return;
  if (!voice.playback) voice.playback = new AudioContext();
  const bytes = Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0));
  const samples = new Int16Array(bytes.buffer, bytes.byteOffset, Math.floor(bytes.byteLength / 2));
  const buffer = voice.playback.createBuffer(1, samples.length, 24000);
  const channel = buffer.getChannelData(0);
  for (let i = 0; i < samples.length; i += 1) channel[i] = samples[i] / 32768;
  const source = voice.playback.createBufferSource(); source.buffer = buffer; source.connect(voice.playback.destination);
  const at = Math.max(voice.playback.currentTime, voice.nextTime); source.start(at); voice.nextTime = at + buffer.duration;
  const orb = document.getElementById('orb');
  if (orb) { orb.classList.add('talking'); clearTimeout(play.timer); play.timer = setTimeout(() => orb.classList.remove('talking'), (voice.nextTime - voice.playback.currentTime) * 1000 + 200); }
}

function endVoice(sendEnd) {
  if (sendEnd && voice.socket?.readyState === WebSocket.OPEN) voice.socket.send(JSON.stringify({ type: 'session.end' }));
  voice.worklet?.disconnect(); voice.sink?.disconnect(); voice.source?.disconnect();
  voice.stream?.getTracks().forEach((t) => t.stop()); voice.audio?.close();
  const socket = voice.socket; voice.socket = null; if (socket && socket.readyState < WebSocket.CLOSING) socket.close();
  Object.assign(voice, { audio: null, worklet: null, sink: null, source: null, stream: null, pending: [] });
  const start = document.getElementById('voice-start'); const end = document.getElementById('voice-end'); const orb = document.getElementById('orb');
  if (start) { start.hidden = false; start.disabled = false; start.innerHTML = `${icon('mic')} Talk again`; }
  if (end) end.hidden = true;
  if (orb) orb.classList.remove('talking');
}

try { const saved = localStorage.getItem('pb-theme'); if (saved) document.documentElement.dataset.theme = saved; } catch { /* storage unavailable */ }
load();
