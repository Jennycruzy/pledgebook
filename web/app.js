const state = { event: null, media: null, audio: null, worklet: null, socket: null, source: null, stream: null, selectedPledge: null, voiceSocket: null, voiceAudio: null, voiceWorklet: null, voiceSource: null, voiceStream: null, voicePlayback: null, voiceNextTime: 0, voicePendingTools: [], voiceCallId: null };
const $ = (id) => document.getElementById(id);
document.querySelector('input[name="event_date"]').value = new Date().toISOString().slice(0, 10);
const money = (value, currency = 'NGN') => currency === 'NGN' || !currency ? `₦${Number(value || 0).toLocaleString('en-NG')}` : `${currency} ${Number(value || 0).toLocaleString()}`;
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[char]));
function showError(message) { $('error').textContent = message; $('error').hidden = false; }
function clearError() { $('error').hidden = true; }
async function api(url, options = {}) { const headers = {'Content-Type':'application/json', ...(options.headers || {})}; if (options.body instanceof FormData) delete headers['Content-Type']; const response = await fetch(url, {...options, headers}); const body = await response.json().catch(() => ({})); if (!response.ok) throw new Error(body.detail || body.error || `Request failed (${response.status})`); return body; }

function render() {
  if (!state.event) return;
  const {event, pledges, guests, totals} = state.event;
  $('event-title').textContent = event.name;
  $('event-label').textContent = `${event.organisation} · ${event.event_date}`;
  $('total').textContent = money(totals.pledged);
  $('target-label').textContent = event.target_minor ? `Target ${money(event.target_minor)}` : 'No target set';
  $('progress-bar').style.width = `${event.target_minor ? Math.min(100, totals.pledged / event.target_minor * 100) : 0}%`;
  $('guest-count').textContent = `${guests.length} guests loaded`;
  const keyTerms = state.event.key_terms || {included_count:0, overflow_count:0, characters:0, term_limit:100, character_limit:8000};
  $('keyterms-preview').innerHTML = `<strong>${keyTerms.included_count} names are being listened for</strong><br><span class="muted">${keyTerms.characters}/${keyTerms.character_limit} name characters used.</span>${keyTerms.overflow_count ? `<br><span class="muted">${keyTerms.overflow_count} names are beyond the verified limit and are shown here so they are never hidden.</span>` : ''}`;
  $('pledge-feed').innerHTML = pledges.length ? pledges.slice(0, 12).map(pledgeRow).join('') : '<div class="empty-list">No pledges yet. Press the microphone and read the script.</div>';
  $('register-list').innerHTML = pledges.length ? pledges.map(pledgeRow).join('') : '<div class="empty-list">The register will fill as pledges are heard.</div>';
  const flags = pledges.filter((p) => p.state === 'flagged');
  $('review-list').innerHTML = flags.length ? flags.map(reviewRow).join('') : '<div class="empty-list">Nothing needs checking right now.</div>';
  $('guest-list-items').innerHTML = guests.map((g) => `<div class="guest-row"><span><strong>${esc([g.title,g.name].filter(Boolean).join(' '))}</strong>${g.group_name ? `<small class="muted"> · ${esc(g.group_name)}</small>` : ''}</span><span class="muted">${g.consent_to_contact ? 'Follow-up agreed' : 'No follow-up yet'}</span></div>`).join('');
  const followUps = pledges.filter((p) => ['confirmed','corrected','redeemed'].includes(p.state));
  $('follow-up-list').innerHTML = followUps.length ? followUps.map((p) => {
    const guest = guests.find((g) => g.id === p.guest_id);
    const guestName = p.matched_name || p.heard_name || 'Name unclear';
    const allowed = guest && guest.consent_to_contact;
    return `<div class="pledge-row"><div><strong>${esc(guestName)}</strong><div class="pledge-sub">${esc(labelFor(p.state))} · ${guest && guest.consent_to_contact ? 'Follow-up agreed' : 'No follow-up consent recorded'}</div></div><div>${p.item ? esc(p.item) : money(p.amount, p.currency)} ${allowed ? `<button class="quiet" data-call-pledge="${p.id}">Call about this</button>` : ''}</div></div>`;
  }).join('') : '<div class="empty-list">A confirmed pledge will appear here.</div>';
  const newest = pledges[0];
  if (newest) { $('newest').classList.remove('empty'); $('newest').innerHTML = `${esc(newest.matched_name || newest.heard_name || 'Name unclear')} <span class="pledge-amount">${newest.item ? esc(newest.item) : money(newest.amount, newest.currency)}</span>`; $('new-state').textContent = labelFor(newest.state); $('new-state').className = `state ${newest.state}`; }
  $('export').href = `/api/events/${event.id}/export.csv`;
}
function labelFor(state) { return ({provisional:'Provisional',confirmed:'Confirmed',corrected:'Rechecked — changed',flagged:'Needs checking',rejected:'Rejected',redeemed:'Redeemed'}[state] || state); }
function pledgeRow(p) { return `<div class="pledge-row"><div class="pledge-main"><div class="pledge-name">${esc(p.matched_name || p.heard_name || 'Name unclear')}</div><div class="pledge-sub">Heard: ${esc(p.live_text || '—')}${p.recheck_text ? ` · Rechecked: ${esc(p.recheck_text)}` : ''}${p.reason ? ` · ${esc(p.reason)}` : ''}</div>${p.id ? `<audio controls preload="none" src="/api/audio/${state.event.event.id}/${p.id}"></audio>` : ''}</div><div><div class="pledge-amount">${p.item ? esc(p.item) : money(p.amount,p.currency)}</div><span class="state ${p.state}">${labelFor(p.state)}</span></div></div>`; }
function reviewRow(p) { const guests = state.event.guests.slice(0, 8); return `<div class="review-row"><div><strong>${esc(p.heard_name || 'Name unclear')} · ${p.item ? esc(p.item) : money(p.amount,p.currency)}</strong><div class="pledge-sub">${esc(p.reason || 'Please listen to the audio moment and choose what you heard.')}</div>${p.id ? `<audio controls preload="none" src="/api/audio/${state.event.event.id}/${p.id}"></audio>` : ''}</div><div class="review-actions">${guests.map(g => `<button data-review="${p.id}" data-guest="${g.id}">This is ${esc([g.title,g.name].filter(Boolean).join(' '))}</button>`).join('')}<button data-amount="${p.id}">Fix amount</button><button data-reject="${p.id}">Not a pledge</button></div></div>`; }
async function refresh() { state.event = await api(`/api/events/${state.event.event.id}`); render(); }

async function createEvent(event) { event.preventDefault(); clearError(); try { const form = new FormData(event.target); state.event = await api('/api/events', {method:'POST', body: JSON.stringify({name:form.get('name'), organisation:form.get('organisation'), event_date:form.get('event_date'), target:Number(form.get('target') || 0), minimum:Number(form.get('minimum') || 0), maximum:Number(form.get('maximum') || 0), demo:true})}); $('setup').hidden = true; $('dashboard').hidden = false; render(); connectSSE(); } catch (error) { showError(error.message); } }
async function startEvent() { try { state.event = await api(`/api/events/${state.event.event.id}/start`, {method:'POST'}); render(); } catch (error) { showError(error.message); } }
function connectSSE() { const source = new EventSource(`/api/events/${state.event.event.id}/stream`); source.onmessage = async (message) => { try { const payload = JSON.parse(message.data); if (payload.type === 'realtime' && payload.event?.transcript) { $('live-text').textContent = payload.event.transcript; $('live-status').textContent = payload.event.end_of_turn ? 'Turn heard' : 'Listening'; } if (payload.type === 'error') showError(payload.message); } catch (error) { showError('A live update could not be read; the register will refresh.'); } await refresh(); }; source.onerror = () => { $('connection').textContent = 'Updates reconnecting…'; }; }
function setView(view) { document.querySelectorAll('.view').forEach((node) => node.hidden = node.id !== view); document.querySelectorAll('.tab').forEach((node) => node.classList.toggle('active', node.dataset.view === view)); }

async function startMic() {
  if (state.socket) return stopMic();
  clearError();
  try {
    state.stream = await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:false, noiseSuppression:false, channelCount:1}});
    state.audio = new AudioContext(); await state.audio.audioWorklet.addModule('/static/pcm-worklet.js');
    state.source = state.audio.createMediaStreamSource(state.stream); state.worklet = new AudioWorkletNode(state.audio, 'pledgebook-pcm');
    state.socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/events/${state.event.event.id}/capture`);
    state.socket.binaryType = 'arraybuffer';
    state.socket.onopen = () => { $('mic').classList.add('active'); $('mic-label').textContent = 'Listening — press to stop'; $('connection').textContent = 'Listening'; state.source.connect(state.worklet); state.worklet.port.onmessage = (message) => { if (state.socket?.readyState === WebSocket.OPEN) state.socket.send(message.data); }; };
    state.socket.onmessage = async (message) => { const payload = JSON.parse(message.data); if (payload.type === 'realtime') { const event = payload.event; if (event.transcript) { $('live-text').textContent = event.transcript; $('live-status').textContent = event.end_of_turn ? 'Turn heard' : 'Listening'; } } else if (payload.type === 'pledge') { state.event = payload.state; render(); } else if (payload.type === 'error') showError(payload.message); };
    state.socket.onclose = () => { cleanupMic(); $('connection').textContent = 'Ready'; };
  } catch (error) { cleanupMic(); showError(error.message); }
}
function stopMic() { if (state.socket?.readyState === WebSocket.OPEN) state.socket.send(JSON.stringify({type:'stop'})); cleanupMic(); }
function cleanupMic() { if (state.worklet) state.worklet.disconnect(); if (state.source) state.source.disconnect(); state.stream?.getTracks().forEach(track => track.stop()); state.audio?.close(); state.socket?.close(); state.socket = null; state.worklet = null; state.source = null; state.stream = null; $('mic').classList.remove('active'); $('mic-label').textContent = 'Press to listen'; }

function randomCallId() { if (crypto.randomUUID) return crypto.randomUUID(); return `${Date.now()}-${Math.random().toString(16).slice(2)}`; }
function base64FromBuffer(buffer) { const bytes = new Uint8Array(buffer); let binary = ''; for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000)); return btoa(binary); }
function setVoiceStatus(message) { $('voice-status').textContent = message; }
function playVoiceAudio(encoded) {
  if (!encoded) return;
  if (!state.voicePlayback) state.voicePlayback = new AudioContext();
  const bytes = Uint8Array.from(atob(encoded), (char) => char.charCodeAt(0));
  const samples = new Int16Array(bytes.buffer, bytes.byteOffset, Math.floor(bytes.byteLength / 2));
  const buffer = state.voicePlayback.createBuffer(1, samples.length, 24000);
  const channel = buffer.getChannelData(0);
  for (let i = 0; i < samples.length; i += 1) channel[i] = samples[i] / 32768;
  const source = state.voicePlayback.createBufferSource(); source.buffer = buffer; source.connect(state.voicePlayback.destination);
  const when = Math.max(state.voicePlayback.currentTime, state.voiceNextTime); source.start(when); state.voiceNextTime = when + buffer.duration;
}
function stopVoiceInput() { if (state.voiceWorklet) state.voiceWorklet.disconnect(); if (state.voiceSource) state.voiceSource.disconnect(); state.voiceStream?.getTracks().forEach((track) => track.stop()); state.voiceAudio?.close(); state.voiceWorklet = null; state.voiceSource = null; state.voiceStream = null; state.voiceAudio = null; }
function endVoiceSession(sendEnd = true) { if (sendEnd && state.voiceSocket?.readyState === WebSocket.OPEN) state.voiceSocket.send(JSON.stringify({type:'session.end'})); stopVoiceInput(); if (state.voiceSocket) state.voiceSocket.close(); state.voiceSocket = null; state.voicePendingTools = []; $('start-call').disabled = !state.selectedPledge; $('end-call').disabled = true; }
function voiceTools() { return [
  {type:'function', name:'confirm_identity', description:'Confirm whether the person answering is the named guest. Do this before mentioning the amount.', parameters:{type:'object', properties:{is_correct_person:{type:'boolean'}}, required:['is_correct_person'], additionalProperties:false}},
  {type:'function', name:'send_payment_link', description:'Create a Paystack test payment link after identity is confirmed. If unavailable, explain that clearly.', parameters:{type:'object', properties:{channel:{type:'string', enum:['screen','email']}}, required:['channel'], additionalProperties:false}},
  {type:'function', name:'record_promise', description:'Record the date the confirmed guest plans to pay.', parameters:{type:'object', properties:{promised_date:{type:'string', format:'date'}}, required:['promised_date'], additionalProperties:false}},
  {type:'function', name:'record_dispute', description:'Record what the guest said when they dispute the pledge.', parameters:{type:'object', properties:{what_they_said:{type:'string'}}, required:['what_they_said'], additionalProperties:false}},
  {type:'function', name:'record_opt_out', description:'Record that the guest does not want follow-up.', parameters:{type:'object', properties:{}, additionalProperties:false}},
  {type:'function', name:'end_call', description:'Record the final outcome and end the call.', parameters:{type:'object', properties:{outcome:{type:'string', enum:['paid_link_sent','promised','disputed','declined','opted_out','wrong_person','incomplete']}}, required:['outcome'], additionalProperties:false}},
]; }
async function flushVoiceTools() {
  if (!state.voiceSocket || state.voiceSocket.readyState !== WebSocket.OPEN) return;
  while (state.voicePendingTools.length) {
    const call = state.voicePendingTools.shift();
    let result;
    try { result = await api(`/api/events/${state.event.event.id}/pledges/${state.selectedPledge.id}/call/tool`, {method:'POST', body:JSON.stringify({browser_call_id:state.voiceCallId, tool:call.name, arguments:call.arguments || {}})}); }
    catch (error) { result = {ok:false, error:error.message}; }
    state.voiceSocket.send(JSON.stringify({type:'tool.result', call_id:call.call_id, result:JSON.stringify(result), is_error:result.ok === false}));
  }
}
async function startVoiceInput() {
  state.voiceStream = await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true, noiseSuppression:true, channelCount:1}});
  state.voiceAudio = new AudioContext(); await state.voiceAudio.audioWorklet.addModule('/static/voice-worklet.js');
  state.voiceSource = state.voiceAudio.createMediaStreamSource(state.voiceStream); state.voiceWorklet = new AudioWorkletNode(state.voiceAudio, 'pledgebook-voice-pcm');
  state.voiceSource.connect(state.voiceWorklet); state.voiceWorklet.port.onmessage = (message) => { if (state.voiceSocket?.readyState === WebSocket.OPEN) state.voiceSocket.send(JSON.stringify({type:'input.audio', audio:base64FromBuffer(message.data)})); };
}
async function startVoiceCall(pledgeId) {
  const pledge = state.event.pledges.find((item) => item.id === Number(pledgeId)); if (!pledge) return;
  endVoiceSession(false); clearError(); state.selectedPledge = pledge; state.voiceCallId = randomCallId(); $('voice-title').textContent = `Calling ${pledge.matched_name || pledge.heard_name}`; $('voice-transcript').textContent = 'Connecting to the disclosed assistant…'; $('start-call').disabled = true; $('end-call').disabled = false;
  try {
    const context = await api(`/api/events/${state.event.event.id}/pledges/${pledge.id}/call/start`, {method:'POST', body:JSON.stringify({browser_call_id:state.voiceCallId})});
    const tokenResult = await api('/api/voice-token');
    const guestName = [context.guest.title, context.guest.name].filter(Boolean).join(' ');
    const amount = pledge.item ? pledge.item : money(pledge.amount, pledge.currency);
    const prompt = `You are the clearly disclosed automated Pledgebook assistant calling on behalf of ${context.event.organisation} about ${context.event.name} on ${context.event.event_date}. You are speaking to the guest named ${guestName}. First say you are automated and ask whether you are speaking with that person. Call confirm_identity with their answer before discussing any pledge or amount. If they say no, apologise, call end_call with wrong_person, and never reveal the amount. If identity is confirmed, thank them for their pledge of ${amount}, offer a payment link, a date they plan to pay, or an opt-out. Never change the amount. If Paystack is unavailable, say so plainly and do not invent a link. Keep the call brief and polite.`;
    state.voiceSocket = new WebSocket(`wss://agents.assemblyai.com/v1/ws?token=${encodeURIComponent(tokenResult.token)}`);
    state.voiceSocket.onopen = async () => { state.voiceSocket.send(JSON.stringify({type:'session.update', session:{system_prompt:prompt, greeting:`Hello, I am the automated Pledgebook assistant. Am I speaking with ${guestName}?`, input:{format:{encoding:'audio/pcm'}, keyterms:[guestName]}, output:{voice:'anna', format:{encoding:'audio/pcm'}}, tools:voiceTools()}})); await startVoiceInput(); setVoiceStatus('The assistant is listening.'); };
    state.voiceSocket.onmessage = async (message) => { const event = JSON.parse(message.data); if (event.type === 'session.ready') setVoiceStatus('The assistant is ready.'); else if (event.type === 'reply.audio') playVoiceAudio(event.data); else if (event.type === 'transcript.agent.delta') $('voice-transcript').textContent += `${event.delta || ''}`; else if (event.type === 'transcript.user') $('voice-transcript').textContent += `\nYou: ${event.text || ''}`; else if (event.type === 'tool.call') state.voicePendingTools.push(event); else if (event.type === 'reply.done') await flushVoiceTools(); else if (event.type === 'session.ended') { setVoiceStatus('Call ended.'); endVoiceSession(false); } else if (event.type === 'error') showError('The assistant connection reported an error.'); };
    state.voiceSocket.onerror = () => { showError('The assistant connection failed.'); endVoiceSession(false); };
    state.voiceSocket.onclose = () => { stopVoiceInput(); $('end-call').disabled = true; if (state.selectedPledge) $('start-call').disabled = false; };
  } catch (error) { endVoiceSession(false); showError(error.message); }
}

async function uploadAudio() {
  const file = $('audio-upload').files[0];
  if (!file) return;
  clearError();
  $('upload-audio').disabled = true;
  $('upload-status').textContent = 'Sending the real recording…';
  try {
    const form = new FormData();
    form.append('file', file, file.name);
    const result = await api(`/api/events/${state.event.event.id}/upload`, {method:'POST', body:form});
    $('upload-status').textContent = result.message;
    await refresh();
  } catch (error) {
    $('upload-status').textContent = 'Upload stopped.';
    showError(error.message);
  } finally {
    $('upload-audio').disabled = false;
    $('audio-upload').value = '';
  }
}

async function addGuest(event) { event.preventDefault(); try { const form = new FormData(event.target); state.event = await api(`/api/events/${state.event.event.id}/guests`, {method:'POST', body: JSON.stringify({title:form.get('title'), name:form.get('name'), phone:form.get('phone'), email:form.get('email'), consent_to_contact:form.get('consent') === 'on'})}).then(refresh).then(() => state.event); event.target.reset(); } catch (error) { showError(error.message); } }
async function importGuests() { const file = $('guest-csv').files[0]; if (!file) return; $('import-status').textContent = 'Importing…'; try { const form = new FormData(); form.append('file', file, file.name); await api(`/api/events/${state.event.event.id}/guests/import`, {method:'POST', body:form}); $('import-status').textContent = 'Guest list imported.'; await refresh(); } catch (error) { $('import-status').textContent = 'Import stopped.'; showError(error.message); } finally { $('guest-csv').value = ''; } }
document.addEventListener('click', async (event) => { const callButton = event.target.closest('[data-call-pledge]'); if (callButton) { state.selectedPledge = state.event.pledges.find((pledge) => pledge.id === Number(callButton.dataset.callPledge)); $('start-call').disabled = !state.selectedPledge; setView('follow-up'); $('voice-title').textContent = state.selectedPledge ? `Ready to call ${state.selectedPledge.matched_name || state.selectedPledge.heard_name}` : 'No call started'; return; } const guestButton = event.target.closest('[data-review]'); if (guestButton) { try { state.event = await api(`/api/events/${state.event.event.id}/pledges/${guestButton.dataset.review}/resolve`, {method:'POST', body:JSON.stringify({action:'guest', guest_id:Number(guestButton.dataset.guest)})}); render(); } catch (error) { showError(error.message); } } const amountButton = event.target.closest('[data-amount]'); if (amountButton) { const amount = Number(prompt('What amount did the recording clearly say?')); if (!Number.isInteger(amount) || amount < 0) return; try { state.event = await api(`/api/events/${state.event.event.id}/pledges/${amountButton.dataset.amount}/resolve`, {method:'POST', body:JSON.stringify({action:'amount', amount})}); render(); } catch (error) { showError(error.message); } } const reject = event.target.closest('[data-reject]'); if (reject) { const reason = prompt('Why is this not a pledge?'); if (!reason) return; try { state.event = await api(`/api/events/${state.event.event.id}/pledges/${reject.dataset.reject}/resolve`, {method:'POST',body:JSON.stringify({action:'reject',reason})}); render(); } catch (error) { showError(error.message); } } });
document.querySelector('#event-form').addEventListener('submit', createEvent); document.querySelector('#start-event').addEventListener('click', startEvent); document.querySelector('#mic').addEventListener('click', startMic); document.querySelector('#upload-audio').addEventListener('click', () => document.querySelector('#audio-upload').click()); document.querySelector('#audio-upload').addEventListener('change', uploadAudio); document.querySelector('#guest-form').addEventListener('submit', addGuest); document.querySelector('#import-guests').addEventListener('click', importGuests); document.querySelector('#start-call').addEventListener('click', () => { if (state.selectedPledge) startVoiceCall(state.selectedPledge.id); }); document.querySelector('#end-call').addEventListener('click', () => endVoiceSession(true)); document.querySelector('#reset').addEventListener('click', () => { cleanupMic(); endVoiceSession(false); location.reload(); }); document.querySelectorAll('.tab').forEach((button) => button.addEventListener('click', () => setView(button.dataset.view)));
