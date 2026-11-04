/*
 * LiveRecall browser client.
 *
 * Local state (one entry per segment):
 *   segments: Map<segment, {segment, revision, final, text, source_ts}>
 *   - a newer revision replaces the older one in place;
 *   - once a segment is final it never changes (later or repeated updates are ignored);
 *   - finals are kept for KEEP_SECONDS (>= 60 s) so recall works from local state.
 *
 * Resume cursor = the highest (segment, revision) FINAL we hold. Provisional
 * updates never move it, so a reconnect asks only for finals we really lack.
 *
 * Recall age: source_ts comes from the source machine's clock, which may differ
 * from the browser's. clockOffset is the smallest (browser now - source_ts) seen
 * on a live update, so it is the clock difference plus the lowest one-way delay.
 * All local age checks use source_ts + clockOffset. HISTORY items are old by
 * nature, so they never set the offset. Until a live update arrives the offset is
 * unknown: recall assumes clocks agree and age pruning waits.
 *
 * Optional URL parameters: ?server=ws://host:8765&session=L1
 */

const params = new URLSearchParams(location.search);
const WS_URL = params.get("server") || `ws://${location.hostname || "127.0.0.1"}:8765`;
const SESSION = params.get("session") || "L1";
const KEEP_SECONDS = 70;            // local final history: 60 s recall plus a 10 s margin, same as the server
const MAX_LOCAL_SEGMENTS = 2000;    // hard bound on local state
const LIVE_ROWS = 40;               // rows kept on screen
const RECONNECT_MIN_MS = 500;
const RECONNECT_MAX_MS = 5000;
const DEMO_DROP_MS = 8000;          // how long the demo "drop" button stays offline

const statusEl = document.getElementById("status");
const liveEl = document.getElementById("live");
const recallEl = document.getElementById("recall");
const statsEl = document.getElementById("stats");

const segments = new Map();
const rows = new Map();             // segment -> DOM row
let cursor = { segment: 0, revision: 0 };
let ws = null;
let retryMs = RECONNECT_MIN_MS;
let reconnectTimer = null;
let clockOffset = null;             // seconds; browser clock minus source clock
let recallSeconds = null;           // null = recall panel closed
const stats = { applied: 0, ignored: 0, recovered: 0, reconnects: 0 };

function clientId() {
  const key = "liverecall-client-id";
  let value = sessionStorage.getItem(key);
  if (!value) {
    value = String(Math.floor(100000 + Math.random() * 900000));
    sessionStorage.setItem(key, value);
  }
  return Number(value);
}

function setStatus(state, text) {
  statusEl.className = state;
  statusEl.textContent = text || state;
}

function observeClock(sourceTs) {
  if (!Number.isFinite(sourceTs)) return;
  const offset = Date.now() / 1000 - sourceTs;
  if (clockOffset === null || offset < clockOffset) clockOffset = offset;
}

// source_ts expressed on the browser's clock.
function localTs(entry) {
  return entry.source_ts + (clockOffset ?? 0);
}

function isNewerCursor(seg, rev) {
  return seg > cursor.segment || (seg === cursor.segment && rev > cursor.revision);
}

// Returns true if the update changed local state.
function apply(msg) {
  if (msg.session !== SESSION || !Number.isInteger(msg.segment) || !Number.isInteger(msg.revision)) {
    return false;
  }
  const old = segments.get(msg.segment);
  const tooOld = !old && msg.segment <= cursor.segment;      // already pruned locally
  if (tooOld || (old && (old.final || msg.revision <= old.revision))) {
    stats.ignored++;                                         // duplicate or stale
    return false;
  }
  const entry = {
    segment: msg.segment, revision: msg.revision, final: msg.final === true,
    text: String(msg.text ?? ""), source_ts: Number(msg.source_ts) || Date.now() / 1000,
  };
  segments.set(entry.segment, entry);
  if (entry.final && isNewerCursor(entry.segment, entry.revision)) {
    cursor = { segment: entry.segment, revision: entry.revision };
  }
  stats.applied++;
  render(entry);
  return true;
}

function render(entry) {
  let row = rows.get(entry.segment);
  if (!row) {
    row = document.createElement("div");
    row.innerHTML = '<span class="seg"></span><span class="text"></span><span class="tag"></span>';
    row.querySelector(".seg").textContent = `#${entry.segment}`;
    // Keep rows ordered by segment even if a recovered one arrives late.
    let after = null;
    for (const [seg, r] of rows) if (seg > entry.segment && (!after || seg < after.seg)) after = { seg, r };
    liveEl.insertBefore(row, after ? after.r : null);
    rows.set(entry.segment, row);
  }
  row.className = `caption ${entry.final ? "final" : "provisional"}`;
  row.querySelector(".text").textContent = entry.text;
  row.querySelector(".tag").textContent = entry.final ? "final" : `rev ${entry.revision}`;
  while (rows.size > LIVE_ROWS) {
    const first = Math.min(...rows.keys());
    rows.get(first).remove();
    rows.delete(first);
  }
  const nearBottom = liveEl.scrollHeight - liveEl.scrollTop - liveEl.clientHeight < 80;
  if (nearBottom) liveEl.scrollTop = liveEl.scrollHeight;
}

function prune() {
  const cutoff = Date.now() / 1000 - KEEP_SECONDS;
  for (const [seg, e] of segments) {
    if ((clockOffset !== null && e.final && localTs(e) < cutoff) || segments.size > MAX_LOCAL_SEGMENTS) segments.delete(seg);
  }
}

function showRecall() {
  for (const b of document.querySelectorAll(".controls button")) {
    b.classList.toggle("selected", Number(b.dataset.seconds) === (recallSeconds ?? 30) && b.id !== "miss");
  }
  if (recallSeconds === null) { recallEl.innerHTML = ""; return; }
  const cutoff = Date.now() / 1000 - recallSeconds;
  const finals = [...segments.values()]
    .filter((e) => e.final && localTs(e) >= cutoff)
    .sort((a, b) => a.segment - b.segment);
  recallEl.innerHTML = "";
  const h = document.createElement("h2");
  h.textContent = `Last ${recallSeconds} s (${finals.length} final caption${finals.length === 1 ? "" : "s"})`;
  recallEl.appendChild(h);
  if (!finals.length) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "Nothing finalized in this window yet.";
    recallEl.appendChild(p);
  }
  for (const e of finals) {
    const p = document.createElement("p");
    p.textContent = e.text;
    recallEl.appendChild(p);
  }
}

function updateStats() {
  statsEl.textContent = `Resume cursor: segment ${cursor.segment} rev ${cursor.revision} · ` +
    `applied ${stats.applied} · ignored duplicate/stale ${stats.ignored} · ` +
    `recovered from history ${stats.recovered} · reconnects ${stats.reconnects}`;
}

let countdownTimer = null;

function scheduleReconnect(delay) {
  clearTimeout(reconnectTimer);
  clearInterval(countdownTimer);
  const due = Date.now() + delay;
  const tick = () => {
    const left = Math.max(1, Math.ceil((due - Date.now()) / 1000));
    setStatus("reconnecting", `reconnecting in ${left}`);
  };
  tick();
  countdownTimer = setInterval(tick, 250);
  reconnectTimer = setTimeout(connect, delay);
}

function connect() {
  clearTimeout(reconnectTimer);
  clearInterval(countdownTimer);
  setStatus("connecting", "connecting");
  const socket = new WebSocket(WS_URL);
  ws = socket;

  socket.addEventListener("open", () => {
    if (ws !== socket) return;
    retryMs = RECONNECT_MIN_MS;
    setStatus("connected");
    socket.send(JSON.stringify({
      type: "CLIENT_HELLO",
      client_id: clientId(),
      session: SESSION,
      last_segment: cursor.segment,
      last_revision: cursor.revision,
      history_seconds: 60,     // ask for the full window so 60 s recall works after a late join
    }));
  });

  socket.addEventListener("message", (event) => {
    if (ws !== socket) return;
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }
    if (msg.type === "CAPTION_UPDATE") {
      if (msg.session === SESSION) observeClock(msg.source_ts);
      apply(msg);
    } else if (msg.type === "HISTORY" && Array.isArray(msg.items)) {
      // Oldest first; apply() drops anything we already hold.
      for (const item of msg.items) if (apply(item)) stats.recovered++;
    }
    updateStats();
  });

  socket.addEventListener("close", () => {
    if (ws !== socket) return;          // an intentional demo drop handles its own reconnect
    ws = null;
    stats.reconnects++;
    scheduleReconnect(retryMs);
    retryMs = Math.min(retryMs * 2, RECONNECT_MAX_MS);
  });

  socket.addEventListener("error", () => { /* close follows and drives reconnect */ });
}

// Demo helper: drop the connection for a few seconds, then reconnect automatically.
function demoDrop() {
  if (!ws) return;
  const socket = ws;
  ws = null;
  socket.close();
  stats.reconnects++;
  scheduleReconnect(DEMO_DROP_MS);
}

for (const button of document.querySelectorAll(".controls button")) {
  button.addEventListener("click", () => {
    const s = Number(button.dataset.seconds);
    recallSeconds = recallSeconds === s && button.id !== "miss" ? null : s;
    if (button.id === "miss") recallSeconds = 30;
    showRecall();
  });
}

const dropButton = document.createElement("button");
dropButton.textContent = `Simulate disconnect (${DEMO_DROP_MS / 1000} s)`;
dropButton.addEventListener("click", demoDrop);
document.querySelector(".controls").appendChild(dropButton);

setInterval(() => { prune(); if (recallSeconds !== null) showRecall(); }, 1000);
window.liverecall = { segments, stats, get cursor() { return cursor; }, demoDrop };
updateStats();
connect();
