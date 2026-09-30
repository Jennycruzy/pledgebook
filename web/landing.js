// Motion for the Pledgebook landing page. The page is complete without it.
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, reduced ? 0 : ms));
const naira = (n) => `₦${Math.round(n).toLocaleString('en-NG')}`;
const compact = (n) => (n >= 1e6 ? `₦${(n / 1e6).toFixed(n % 1e6 ? 1 : 0)}m` : `₦${Math.round(n / 1000)}k`);
document.documentElement.classList.add('js');

// Nav shadow once the page scrolls.
const nav = $('nav');
addEventListener('scroll', () => nav.classList.toggle('scrolled', scrollY > 8), { passive: true });

// Headline words rise in one after another.
document.querySelectorAll('.reveal-words').forEach((h) => {
  let i = 0;
  const wrap = (node) => {
    [...node.childNodes].forEach((child) => {
      if (child.nodeType === 3) {
        const frag = document.createDocumentFragment();
        child.textContent.split(/(\s+)/).forEach((part) => {
          if (!part.trim()) { frag.append(part); return; }
          const s = document.createElement('span'); s.className = 'w'; s.textContent = part; s.style.animationDelay = `${0.08 * i++}s`; frag.append(s);
        });
        child.replaceWith(frag);
      } else if (child.nodeType === 1) {
        if (child.classList.contains('shine')) { child.classList.add('w'); child.style.animationDelay = `${0.08 * i++}s`; } else wrap(child);
      }
    });
  };
  wrap(h);
});

// Count numbers up when they come into view.
function countUp(el, to, from = 0, ms = 1400, fmt = (n) => Math.round(n).toLocaleString('en-NG')) {
  if (reduced) { el.textContent = fmt(to); return; }
  const t0 = performance.now();
  const step = (t) => { const k = Math.min(1, (t - t0) / ms); const e = 1 - (1 - k) ** 3; el.textContent = fmt(from + (to - from) * e); if (k < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}

// Sections slide in as they appear; the page is readable if this never runs.
document.querySelectorAll('.stop, .stat, .rule, .cmp-row, .head, .split > div').forEach((el) => el.classList.add('appear'));
const seen = new IntersectionObserver((entries) => entries.forEach((e) => {
  if (!e.isIntersecting) return;
  e.target.classList.add('in', 'lit');
  e.target.querySelectorAll('[data-count]').forEach((n) => countUp(n, +n.dataset.count));
  if (e.target.dataset.count) countUp(e.target, +e.target.dataset.count);
  if (e.target.dataset.step === '4') { const p = $('pct'); if (p) countUp(p, 100, 0, 2400, (n) => `${Math.round(n)}%`); }
  seen.unobserve(e.target);
}), { threshold: 0.25 });
document.querySelectorAll('.appear, .proof-mini b').forEach((el) => seen.observe(el));

// Journey rail: a spark travels along as the section scrolls past.
const rail = $('journeyRail');
const railFill = $('railFill'); const spark = $('spark');
function railTick() {
  if (!rail) return;
  const r = rail.getBoundingClientRect(); const vh = innerHeight;
  const k = Math.max(0, Math.min(1, (vh * 0.75 - r.top) / (r.height + vh * 0.25)));
  railFill.style.width = `${k * 100}%`; spark.style.left = `${k * 100}%`;
}
addEventListener('scroll', railTick, { passive: true }); railTick();

// Buttons lean toward the pointer.
document.querySelectorAll('.magnetic').forEach((b) => {
  b.addEventListener('pointermove', (e) => { if (reduced) return; const r = b.getBoundingClientRect(); b.style.transform = `translate(${(e.clientX - r.left - r.width / 2) * 0.15}px, ${(e.clientY - r.top - r.height / 2) * 0.25}px)`; });
  b.addEventListener('pointerleave', () => { b.style.transform = ''; });
});

// Console tilt follows the pointer.
const stage = $('stage'); const consoleEl = stage?.querySelector('.console');
stage?.addEventListener('pointermove', (e) => {
  if (reduced || !consoleEl) return;
  const r = stage.getBoundingClientRect(); const x = (e.clientX - r.left) / r.width - 0.5; const y = (e.clientY - r.top) / r.height - 0.5;
  consoleEl.style.transform = `perspective(1200px) rotateY(${x * 10}deg) rotateX(${-y * 8}deg)`;
});
stage?.addEventListener('pointerleave', () => { if (consoleEl) consoleEl.style.transform = ''; });

// Ticker of illustrative pledges.
const TICKER = [['Chief Adaeze Nnamdi', 250000], ['Engr. Bayo Adekunle', 100000], ['Dr. Kunle Martins', 500000], ['The Youth Fellowship', 300000], ['Mrs. Hauwa Sani', 70000], ['A daughter of the soil', 200000], ['Deaconess Ngozi Eze', 100000], ['Pastor Kelechi Amadi', 500000]];
const ticker = $('ticker');
if (ticker) { const html = TICKER.map(([n, a]) => `<span><i></i>${n} <b>${naira(a)}</b></span>`).join(''); ticker.innerHTML = html + html; }

// Live console: words arrive, a line is heard, then confirmed or flagged.
const LINES = [
  { name: 'Chief Adaeze Nnamdi', amount: 250000, words: 'Chief Adaeze Nnamdi, two hundred and fifty thousand naira! Clap for her!', end: 'ok' },
  { name: 'Engr. Bayo Adekunle', amount: 100000, words: 'Engineer Bayo Adekunle, one hundred thousand naira.', end: 'ok' },
  { name: 'Mrs. Hauwa Sani', amount: null, words: 'Mrs. Hauwa Sani, fifty thousand. Sorry, seventy thousand.', end: 'flag' },
  { name: 'Dr. Kunle Martins', amount: 500000, words: 'Dr. Kunle Martins, half a million naira! God bless you, sir.', end: 'ok' },
  { name: 'A daughter of the soil', amount: 200000, words: 'A daughter of the soil, two hundred thousand naira.', end: 'ok' },
];
const initials = (n) => n.replace(/^(Chief|Engr\.|Mrs\.|Dr\.|A)\s+/, '').split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase();
let talking = 0;
async function runConsole() {
  let i = 0; let total = 1250000;
  for (;;) {
    const feed = $('feed'); const heard = $('heard'); if (!feed) return;
    const line = LINES[i++ % LINES.length];
    heard.textContent = ''; talking = 1;
    for (const w of line.words.split(' ')) { heard.textContent += `${w} `; await sleep(120); }
    talking = 0.25;
    const row = document.createElement('div'); row.className = 'row';
    row.innerHTML = `<span class="av">${initials(line.name)}</span><span>${line.name}</span><span class="amt num">${line.amount ? compact(line.amount) : '—'}</span><span class="st prov">Heard</span>`;
    feed.prepend(row); while (feed.children.length > 3) feed.lastElementChild.remove();
    await sleep(1300);
    const st = row.querySelector('.st');
    if (line.end === 'ok') {
      st.className = 'st ok'; st.textContent = 'Confirmed';
      const from = total; total += line.amount; countUp($('total'), total, from, 900, naira);
      $('bar').style.width = `${Math.min(96, 20 + (total / 4000000) * 76)}%`;
      burst(row);
    } else { st.className = 'st flag'; st.textContent = 'Needs checking'; }
    if (total > 3200000) total = 1250000;
    await sleep(1600);
  }
}
runConsole();

// Canvas waveform in the console, louder while words are arriving.
const wave = $('wave');
if (wave) {
  const ctx = wave.getContext('2d'); let level = 0.3; let t = 0;
  const draw = () => {
    const w = wave.width = wave.clientWidth * devicePixelRatio; const h = wave.height = 70 * devicePixelRatio;
    level += ((talking || 0.15) - level) * 0.06; t += 0.05;
    ctx.clearRect(0, 0, w, h);
    const bars = 44; const bw = w / bars;
    for (let b = 0; b < bars; b++) {
      const n = Math.sin(b * 0.55 + t * 3) * 0.5 + Math.sin(b * 1.7 - t * 2) * 0.3 + Math.sin(b * 0.2 + t) * 0.2;
      const bh = Math.max(3 * devicePixelRatio, Math.abs(n) * h * 0.9 * level + h * 0.06);
      const g = ctx.createLinearGradient(0, (h - bh) / 2, 0, (h + bh) / 2);
      g.addColorStop(0, b % 5 === 0 ? '#f2b544' : '#46d19c'); g.addColorStop(1, '#0b7a55');
      ctx.fillStyle = g; const x = b * bw + bw * 0.2; const r = Math.min(bw * 0.3, 4 * devicePixelRatio);
      ctx.beginPath(); ctx.roundRect(x, (h - bh) / 2, bw * 0.6, bh, r); ctx.fill();
    }
    if (!reduced) requestAnimationFrame(draw);
  };
  draw();
}

// Gold sparks when a pledge is confirmed.
function burst(anchor) {
  if (reduced) return;
  const r = anchor.getBoundingClientRect();
  for (let k = 0; k < 14; k++) {
    const s = document.createElement('i');
    const a = Math.random() * Math.PI * 2; const d = 30 + Math.random() * 50;
    s.style.cssText = `position:fixed;z-index:30;pointer-events:none;left:${r.right - 60}px;top:${r.top + r.height / 2}px;width:6px;height:6px;border-radius:50%;background:${k % 3 ? '#f2b544' : '#46d19c'};box-shadow:0 0 8px #f2b544;transition:transform .8s cubic-bezier(.2,.8,.2,1),opacity .8s`;
    document.body.append(s);
    requestAnimationFrame(() => { s.style.transform = `translate(${Math.cos(a) * d}px, ${Math.sin(a) * d}px) scale(.3)`; s.style.opacity = '0'; });
    setTimeout(() => s.remove(), 900);
  }
}

// The real conversation, replayed when the voice section is on screen.
const CHAT = [
  ['agent', 'Assistant', 'Hello, I am the automated Pledgebook assistant for Grace Chapel. Am I speaking with Chief Emeka Okonkwo?'],
  ['guest', 'Guest', 'Yes, this is Emeka Okonkwo.'],
  ['tool', '', 'confirm_identity → true'],
  ['agent', 'Assistant', 'Thank you for your pledge, Chief. The amount still to pay is ₦250,000. Would you like to pay now, choose a date to pay later, or is there something wrong?'],
  ['guest', 'Guest', 'I would like to pay now, please.'],
  ['tool', '', 'open_checkout → payment button on his screen'],
  ['paybtn', '', 'Pay ₦250,000 with Paystack'],
];
const chat = $('chat'); const orb = $('orb'); let chatRunning = false;
async function playChat() {
  if (chatRunning || !chat) return; chatRunning = true;
  for (;;) {
    chat.innerHTML = '';
    for (const [kind, who, text] of CHAT) {
      const m = document.createElement('div'); m.className = `msg ${kind}`;
      if (kind === 'agent') {
        orb.classList.add('talking'); m.innerHTML = `<small>${who}</small><span></span>`; chat.append(m);
        const span = m.querySelector('span');
        for (const w of text.split(' ')) { span.textContent += `${w} `; await sleep(55); }
        orb.classList.remove('talking');
      } else { m.innerHTML = who ? `<small>${who}</small>${text}` : text; chat.append(m); }
      while (chat.children.length > 5) chat.firstElementChild.remove();
      await sleep(kind === 'tool' ? 900 : 1500);
    }
    await sleep(3500);
    if (reduced) return;
  }
}
const voice = $('voice');
if (voice) new IntersectionObserver((e, o) => { if (e[0].isIntersecting) { playChat(); o.disconnect(); } }, { threshold: 0.3 }).observe(voice);

// Background: slow gold and green motes drifting upward.
const sky = $('sky');
if (sky && !reduced) {
  const c = sky.getContext('2d'); let W; let H; const motes = [];
  const size = () => { W = sky.width = innerWidth * devicePixelRatio; H = sky.height = innerHeight * devicePixelRatio; };
  size(); addEventListener('resize', size);
  for (let k = 0; k < 42; k++) motes.push({ x: Math.random(), y: Math.random(), r: 0.6 + Math.random() * 2.2, s: 0.00006 + Math.random() * 0.00018, p: Math.random() * 6, gold: Math.random() < 0.45 });
  const loop = (t) => {
    c.clearRect(0, 0, W, H);
    for (const m of motes) {
      m.y -= m.s * 16; if (m.y < -0.02) { m.y = 1.02; m.x = Math.random(); }
      const x = (m.x + Math.sin(t / 3000 + m.p) * 0.01) * W; const y = m.y * H; const a = 0.25 + 0.25 * Math.sin(t / 900 + m.p);
      c.beginPath(); c.arc(x, y, m.r * devicePixelRatio, 0, Math.PI * 2);
      c.fillStyle = m.gold ? `rgba(224,162,42,${a})` : `rgba(11,122,85,${a * 0.8})`; c.fill();
    }
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
}

// Final band: confetti of naira-gold flecks.
const conf = $('confetti');
if (conf && !reduced) {
  const c = conf.getContext('2d'); const bits = []; let W; let H;
  const size = () => { W = conf.width = conf.clientWidth * devicePixelRatio; H = conf.height = conf.clientHeight * devicePixelRatio; };
  size(); addEventListener('resize', size);
  for (let k = 0; k < 60; k++) bits.push({ x: Math.random(), y: Math.random(), v: 0.0006 + Math.random() * 0.0012, r: Math.random() * Math.PI, w: 3 + Math.random() * 5, gold: Math.random() < 0.6 });
  const loop = () => {
    c.clearRect(0, 0, W, H);
    for (const b of bits) {
      b.y += b.v; b.r += 0.03; if (b.y > 1.05) { b.y = -0.05; b.x = Math.random(); }
      c.save(); c.translate(b.x * W, b.y * H); c.rotate(b.r); c.fillStyle = b.gold ? 'rgba(242,181,68,.8)' : 'rgba(140,230,193,.55)';
      c.fillRect(-b.w * devicePixelRatio / 2, -1.5 * devicePixelRatio, b.w * devicePixelRatio, 3 * devicePixelRatio); c.restore();
    }
    requestAnimationFrame(loop);
  };
  loop();
}
