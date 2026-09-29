// The guest's private pledge page: hear the moment, pay, promise, raise a problem,
// or talk to the disclosed voice assistant on this device.

const token = location.pathname.split('/').filter(Boolean).pop();
const page = document.getElementById('page');
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]));
const money = (value, currency = 'NGN') => currency === 'NGN' ? `₦${Number(value || 0).toLocaleString('en-NG')}` : `${currency} ${Number(value || 0).toLocaleString()}`;
let data = null;
const voice = { socket: null, audio: null, worklet: null, sink: null, source: null, stream: null, playback: null, nextTime: 0, pending: [], session: null };

async function api(path, body) {
  const response = await fetch(`/api/pay/${token}${path}`, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Pledgebook': '1' }, body: JSON.stringify(body),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw Object.assign(new Error(result.detail || `Something went wrong (${response.status})`), { status: response.status });
  return result;
}

function message(text, kind = 'notice') {
  const node = document.getElementById('page-message');
  if (node) { node.className = kind; node.textContent = text; node.hidden = false; node.scrollIntoView({ block: 'nearest' }); }
}

async function load() {
  try { data = await api(''); }
  catch (error) {
    page.innerHTML = `<div class="panel"><p class="eyebrow">Pledgebook</p><h1>This page is not available</h1><p>${esc(error.message)}</p></div>`;
    return;
  }
  render();
  const reference = new URLSearchParams(location.search).get('reference');
  if (reference) {
    history.replaceState(null, '', location.pathname);
    message('Checking your payment with Paystack…');
    try {
      const result = await api('/verify', { reference });
      data = await api('');
      render();
      message(result.status === 'success' ? 'Thank you — your payment has been received.' : `Paystack reports this payment as ${result.status}. If money left your account, please contact the organiser.`, result.status === 'success' ? 'notice success' : 'inline-error');
    } catch (error) { message(error.message, 'inline-error'); }
  }
}

function render() {
  const { event, guest, pledge, payments, assistant } = data;
  const paidUp = !pledge.item && pledge.outstanding === 0;
  const progress = pledge.amount ? Math.min(100, (pledge.received / pledge.amount) * 100) : 0;
  page.innerHTML = `<div class="panel guest-card">
    <p class="eyebrow">${esc(event.organisation)} · ${esc(event.name)} · ${esc(event.event_date)}</p>
    <h1>Thank you, ${esc(guest.name)}</h1>
    <div class="amount">${pledge.item ? esc(pledge.item) : money(pledge.amount, pledge.currency)}</div>
    ${pledge.item ? '<p class="muted">An in-kind gift. The organiser will arrange it with you.</p>' : `<div class="progress"><span style="width:${progress}%"></span></div><p class="muted">${money(pledge.received)} received · ${money(pledge.outstanding)} to go</p>`}
    <div id="page-message" hidden></div>
    <h2>The moment you pledged</h2>
    ${pledge.audio ? `<audio controls preload="none" src="/api/pay/${esc(token)}/audio"></audio>` : `<p class="muted">${esc(pledge.audio_reason)}</p>`}
    <p class="muted">Words heard: “${esc(pledge.words || '—')}”</p></div>
    ${paidUp ? '<div class="panel guest-card"><h2>Fully paid</h2><p>Your pledge has been paid in full. Thank you for your generosity.</p></div>' : ''}
    ${!paidUp && payments.available ? `<div class="panel guest-card"><h2>Pay now</h2>
      ${payments.mode === 'test' ? '<p class="notice">This organiser is still testing. Payments here use Paystack test cards and no real money moves.</p>' : ''}
      <form id="pay-form" class="form-grid single"><label>Amount to pay now (₦) <span class="optional">You can pay in parts</span><input name="amount" type="number" min="100" max="${pledge.outstanding}" value="${pledge.outstanding}" required></label>
      ${guest.email_known ? '' : '<label>Email for your receipt<input name="email" type="email" required autocomplete="email"></label>'}
      <button class="primary full" type="submit">Continue to Paystack</button></form>
      ${payments.mode === 'test' ? '<p class="muted small-print">Test card 4084 0840 8408 4081 · any future expiry · CVV 408</p>' : ''}</div>` : ''}
    ${!paidUp ? `<div class="panel guest-card"><h2>Pay later</h2>
      ${pledge.promised_date ? `<p class="muted">You planned to pay on ${esc(pledge.promised_date)}.</p>` : ''}
      <form id="promise-form" class="inline-form"><label>I plan to pay on<input name="promised_date" type="date" min="${new Date().toISOString().slice(0, 10)}" required></label><button class="quiet" type="submit">Save date</button></form></div>` : ''}
    ${assistant.available && !paidUp ? `<div class="panel guest-card"><h2>Talk it through</h2>
      <p class="muted">Speak with an <strong>automated voice assistant</strong> on this device. It uses a generated voice and your microphone. It can take you to payment, note a date, record a concern, or stop reminders. It will not change your pledge amount.</p>
      <div id="voice-transcript" class="live-text" hidden></div>
      <div class="head-actions"><button id="voice-start" class="quiet">Start talking</button><button id="voice-end" class="quiet" hidden>End conversation</button></div>
      <div id="voice-pay" hidden></div></div>` : ''}
    <div class="panel guest-card"><details><summary>Something not right?</summary>
      <form id="dispute-form" class="form-grid single"><label>Tell the organiser what is wrong<textarea name="what_they_said" rows="3" minlength="3" required placeholder="For example: I pledged ₦50,000, not ₦500,000"></textarea></label><button class="quiet" type="submit">Send to the organiser</button></form>
      ${pledge.stopped ? '<p class="muted">You will not receive more reminders about this pledge.</p>' : '<p><button id="stop" class="text-button" type="button">Stop reminders about this pledge</button></p>'}</details></div>
    <p class="muted small-print center">Private page for ${esc(guest.name)} · expires ${new Date(data.expires_at).toLocaleDateString()} · Pledgebook</p>`;
  bind();
}

function bind() {
  document.getElementById('pay-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.target));
    const button = event.target.querySelector('button'); button.disabled = true;
    try { const result = await api('/checkout', { amount: Number(form.amount), email: form.email || '' }); location.href = result.checkout_url; }
    catch (error) { message(error.message, 'inline-error'); button.disabled = false; }
  });
  document.getElementById('promise-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    try { await api('/promise', Object.fromEntries(new FormData(event.target))); data = await api(''); render(); message('Thank you. The organiser can see the date you chose.', 'notice success'); }
    catch (error) { message(error.message, 'inline-error'); }
  });
  document.getElementById('dispute-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      await api('/dispute', Object.fromEntries(new FormData(event.target)));
      page.innerHTML = '<div class="panel guest-card"><h1>Thank you for telling us</h1><p>The organiser will review this pledge and contact you. This page is now closed.</p></div>';
    } catch (error) { message(error.message, 'inline-error'); }
  });
  document.getElementById('stop')?.addEventListener('click', async () => {
    try { await api('/stop', {}); data = await api(''); render(); message('You will not receive more reminders about this pledge.', 'notice'); }
    catch (error) { message(error.message, 'inline-error'); }
  });
  document.getElementById('voice-start')?.addEventListener('click', startVoice);
  document.getElementById('voice-end')?.addEventListener('click', () => endVoice(true));
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

function transcript(text) {
  const node = document.getElementById('voice-transcript');
  if (node) { node.hidden = false; node.textContent += text; node.scrollTop = node.scrollHeight; }
}

async function startVoice() {
  const start = document.getElementById('voice-start');
  start.disabled = true;
  try {
    const session = await api('/assistant', {});
    voice.session = session;
    const today = new Date().toISOString().slice(0, 10);
    const prompt = `You are the automated Pledgebook assistant for ${session.event.organisation}, speaking with someone who opened the private pledge page for ${session.guest_name} from ${session.event.name} on ${session.event.event_date}. Today is ${today}. Say plainly that you are an automated assistant. Ask whether you are speaking with ${session.guest_name}. Call confirm_identity with true only if they clearly say yes; if they say no, are unsure, or the answer is unclear or unrelated, ask once more, and if it is still not a clear yes call confirm_identity with false. Do not discuss the pledge before identity is confirmed. If it is not confirmed, apologise, call end_call with wrong_person and stop. If confirmed, thank them for their pledge; the amount still to pay is ${session.amount_label}. Offer three choices: pay now (call open_checkout, then tell them to press the payment button on their screen), choose a date to pay (call record_promise with a YYYY-MM-DD date), or tell you if something is wrong (call record_dispute with their words). If they want no more reminders, call record_opt_out. Never change or negotiate the amount, never pressure them, and never invent a payment link. Keep it short and warm, then call end_call.`;
    voice.socket = new WebSocket(`wss://agents.assemblyai.com/v1/ws?token=${encodeURIComponent(session.token)}`);
    voice.socket.onopen = async () => {
      voice.socket.send(JSON.stringify({ type: 'session.update', session: { system_prompt: prompt, greeting: `Hello, I am the automated Pledgebook assistant for ${session.event.organisation}. Am I speaking with ${session.guest_name}?`, input: { format: { encoding: 'audio/pcm' }, keyterms: [session.guest_name] }, output: { voice: 'anna', format: { encoding: 'audio/pcm' } }, tools: tools() } }));
      await startMicrophone();
      document.getElementById('voice-end').hidden = false;
    };
    voice.socket.onmessage = async (raw) => {
      const event = JSON.parse(raw.data);
      if (event.type === 'reply.audio') play(event.data);
      else if (event.type === 'transcript.agent') transcript(`Assistant: ${event.text || ''}\n`);
      else if (event.type === 'transcript.user') transcript(`You: ${event.text || ''}\n`);
      else if (event.type === 'tool.call') voice.pending.push(event);
      else if (event.type === 'reply.done') await flushTools();
      else if (event.type === 'session.ended') endVoice(false);
      else if (event.type === 'error') message('The assistant reported a problem. You can use the buttons on this page instead.', 'inline-error');
    };
    voice.socket.onerror = () => { message('The assistant could not connect. You can use the buttons on this page instead.', 'inline-error'); endVoice(false); };
    voice.socket.onclose = () => endVoice(false);
  } catch (error) {
    start.disabled = false;
    message(error.name === 'NotAllowedError' ? 'Microphone permission was denied. You can use the buttons on this page instead.' : error.message, 'inline-error');
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
      box.innerHTML = `<a class="button-link primary" href="${esc(result.checkout_url)}">Pay ${esc(voice.session.amount_label)} with Paystack</a>`;
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
}

function endVoice(sendEnd) {
  if (sendEnd && voice.socket?.readyState === WebSocket.OPEN) voice.socket.send(JSON.stringify({ type: 'session.end' }));
  voice.worklet?.disconnect(); voice.sink?.disconnect(); voice.source?.disconnect();
  voice.stream?.getTracks().forEach((t) => t.stop()); voice.audio?.close();
  const socket = voice.socket; voice.socket = null; if (socket && socket.readyState < WebSocket.CLOSING) socket.close();
  Object.assign(voice, { audio: null, worklet: null, sink: null, source: null, stream: null, pending: [] });
  const start = document.getElementById('voice-start'); const end = document.getElementById('voice-end');
  if (start) start.disabled = false; if (end) end.hidden = true;
}

load();
