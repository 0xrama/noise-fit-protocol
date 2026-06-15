/* NoiseFit dashboard — talks to the Python bridge (window.pywebview.api),
   renders the connect flow and the dashboard with inline SVG charts.
   No external libraries, so it runs fully offline inside the WKWebView. */

const $ = (id) => document.getElementById(id);
const api = () => (window.pywebview && window.pywebview.api) || null;

let connected = false;
let rememberedAddress = "";
let restoredMemory = false;
let dayRecords = {};
let integrationStatus = { google_fit: {}, poke: {} };

/* ── tiny helpers ─────────────────────────────────────────────────────────── */
function show(el, on = true) { el.hidden = !on; }
function fmt(n) { return (n == null) ? "—" : Number(n).toLocaleString(); }

let toastTimer = null;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  show(t, true);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => show(t, false), 2600);
}

function setStatus(msg, busy = false) {
  const el = $("connect-status");
  el.innerHTML = (busy ? '<span class="spin"></span>' : "") + (msg || "");
}

function showTokenPanel(on = true) {
  const panel = $("token-panel");
  if (panel) show(panel, on);
}

function pairingToken() {
  const el = $("pairing-token");
  return el ? el.value.trim() : "";
}

function leaveDashboard(message) {
  connected = false;
  show($("screen-dash"), false);
  show($("screen-connect"), true);
  showTokenPanel(true);
  if (rememberedAddress) $("manual-mac").value = rememberedAddress;
  setStatus(message || "Reconnect with a fresh pairing token.");
}

function handleApiError(res, surface = "status") {
  if (!res || !res.error) return false;
  if (res.code === "pairing_token_rejected") {
    leaveDashboard(res.error);
  } else if (surface === "toast") {
    toast(res.error);
  } else {
    setStatus(res.error);
  }
  return true;
}

/* Sidebar live status — shows what the BLE layer is doing during a sync so the
   dashboard never looks frozen. Translates raw protocol log lines to plain text. */
function setSideStatus(line) {
  const el = $("side-foot");
  if (!el) return;
  const pretty = humanizeLog(line);
  const busy = /sync|connect|request|scan|verify|pull|reading|fitness/i.test(line);
  el.innerHTML = (busy ? '<span class="spin"></span>' : "") + pretty;
}

function humanizeLog(line) {
  const map = [
    [/DAILY|steps/i, "Reading steps…"],
    [/HEART_RATE|\bhr\b/i, "Reading heart rate…"],
    [/SLEEP/i, "Reading sleep…"],
    [/SpO2/i, "Reading blood oxygen…"],
    [/STRESS/i, "Reading stress…"],
    [/battery/i, "Reading battery…"],
    [/VERIFY|bring-up|Authenticated/i, "Authenticating…"],
    [/Connecting|Connected/i, "Connecting…"],
    [/Scanning|scan/i, "Scanning…"],
  ];
  for (const [re, txt] of map) if (re.test(line)) return txt;
  return (line || "").replace(/^[→✓!\s]+/, "").slice(0, 48) || "Working…";
}

/* Per-card loading shimmer while a sync is in flight. */
function markLoading(on) {
  document.querySelectorAll(".card").forEach((c) => c.classList.toggle("loading", on));
}

/* ── events pushed from Python ────────────────────────────────────────────── */
let lastLog = "";
window.addEventListener("watch:log", (e) => {
  lastLog = e.detail.line || "";
  if (!connected) {
    setStatus(lastLog, true);
  } else {
    // On the dashboard, surface live BLE progress in the sidebar so a slow
    // sync reads as "working on X", never as a frozen screen.
    setSideStatus(lastLog);
  }
});
window.addEventListener("watch:status", (e) => {
  const s = e.detail.state;
  if (s === "syncing") { markLoading(true); setSideStatus("Syncing health data…"); }
  else if (s === "connected") { connected = true; markLoading(false); setSideStatus("Up to date"); }
  else if (s === "disconnected") { connected = false; setSideStatus("Disconnected — cached data stays here"); }
});
window.addEventListener("watch:data", (e) => render(e.detail));

/* ── connect flow ─────────────────────────────────────────────────────────── */
async function scan() {
  if (!api()) { setStatus("Bridge not ready yet — try again."); return; }
  $("btn-scan").disabled = true;
  setStatus("Scanning…", true);
  show($("device-list"), false);
  try {
    const res = await api().scan(10);
    if (res.error) { setStatus(res.error); return; }
    const devices = res.devices || [];
    const list = $("device-list");
    list.innerHTML = "";
    if (!devices.length) {
      setStatus("No watches found. Wake the watch, keep it close, disconnect the phone app, then scan again.");
    } else {
      setStatus("");
      devices.forEach((d) => {
        const li = document.createElement("li");
        li.innerHTML = `<span class="dname">${d.name}</span><span class="daddr">${d.address}</span>`;
        li.onclick = () => connect(d.address);
        list.appendChild(li);
      });
      show(list, true);
    }
  } catch (err) {
    setStatus("Scan failed: " + err);
  } finally {
    $("btn-scan").disabled = false;
  }
}

async function connect(address) {
  if (!api()) { setStatus("Bridge not ready yet."); return; }
  if (!address) { setStatus("Enter a UUID, MAC, or name first."); return; }
  rememberedAddress = address;
  setStatus("Connecting… this can take a few seconds.", true);
  try {
    const info = await api().connect(address, pairingToken() || null);
    if (handleApiError(info)) return;
    connected = true;
    enterDashboard(info || {});
    markLoading(true);
    refresh();
    AutoSync.applyTimer();   // keep syncing on the chosen interval while open
  } catch (err) {
    setStatus("Connection failed: " + err);
  }
}

function enterDashboard(info) {
  show($("screen-connect"), false);
  show($("screen-dash"), true);
  $("dev-name").textContent = info.model ? `NoiseFit ${info.model}` : "NoiseFit";
  const bits = [];
  if (info.firmware) bits.push("fw " + info.firmware);
  if (info.serial) bits.push(info.serial);
  $("dev-meta").textContent = bits.join("  ·  ");
  if (info.battery != null) setBattery(info.battery, info.charging);

  const now = new Date();
  const h = now.getHours();
  const greet = h < 5 ? "Good night" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
  const g = $("greeting"); if (g) g.textContent = greet;
  const d = $("today-date");
  if (d) d.textContent = now.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
}

/* ── dashboard actions ───────────────────────────────────────────────────── */
// The watch allows ONE BLE conversation at a time, so a manual Refresh and an
// auto-sync tick must never run together. This guard lets either caller bail
// out cleanly if a sync is already in flight.
let syncing = false;

async function refresh() {
  if (syncing) return;
  if (!api()) { toast("Bridge not ready yet — try again."); return; }
  syncing = true;
  const btn = $("btn-refresh");
  btn.disabled = true; btn.textContent = "Syncing…";
  try {
    if (!connected) {
      setSideStatus("Connecting…");
      const link = await api().ensure_connected();
      if (handleApiError(link, "toast")) return;
      connected = true;
    }
    const data = await api().refresh();
    if (handleApiError(data, "toast")) return;
    else render(data);
  } catch (err) {
    toast("Sync failed: " + err);
  } finally {
    btn.disabled = false; btn.textContent = "Refresh";
    syncing = false;
  }
}

async function syncTime() {
  if (!connected) {
    const link = await api().ensure_connected();
    if (handleApiError(link, "toast")) return;
    connected = true;
  }
  const r = await api().sync_time();
  toast(r && r.ok ? "Watch time synced" : "Time sync failed");
}

async function disconnect() {
  await api().disconnect();
  connected = false;
  AutoSync.stopTimer();   // don't keep waking a watch the user just released
  setSideStatus("Disconnected — cached data stays here");
  toast("Disconnected. Refresh reconnects when needed.");
}

/* ── auto-sync ────────────────────────────────────────────────────────────────
   Two independent, user-toggled behaviours, persisted in localStorage:

   • onOpen   — sync once shortly after the app launches and a remembered watch
                is restored, so the dashboard is fresh without a manual Refresh.
   • interval — when the app stays open, keep syncing every N minutes (5 or 10).

   Both funnel through refresh(), which already auto-connects and is guarded
   against overlapping syncs, so we never stack BLE conversations. A periodic
   tick that fails is silent (refresh() toasts once); the next tick just retries. */
const AutoSync = {
  KEY: "noisefit.autosync",
  defaults: { onOpen: true, interval: 0 },   // interval in minutes; 0 = off
  _timer: null,

  prefs() {
    try {
      return { ...this.defaults, ...JSON.parse(localStorage.getItem(this.KEY) || "{}") };
    } catch { return { ...this.defaults }; }
  },

  save(patch) {
    const next = { ...this.prefs(), ...patch };
    try { localStorage.setItem(this.KEY, JSON.stringify(next)); } catch {}
    this.applyTimer();
    return next;
  },

  // Called once a watch has been restored/connected, so the first sync has
  // something to connect to. Runs the on-open sync, then arms the interval.
  start() {
    if (this.prefs().onOpen) {
      // Defer slightly so the bridge + restore settle before we grab the link.
      setTimeout(() => { if (!syncing) refresh(); }, 800);
    }
    this.applyTimer();
  },

  applyTimer() {
    this.stopTimer();
    const mins = Number(this.prefs().interval) || 0;
    if (mins > 0) {
      this._timer = setInterval(() => {
        if (!syncing && api()) refresh();
      }, mins * 60 * 1000);
    }
  },

  stopTimer() {
    if (this._timer) { clearInterval(this._timer); this._timer = null; }
  },
};

/* Reflect saved prefs into the sidebar controls and persist changes. */
function wireAutoSync() {
  const sw = $("autosync-onopen");
  const sel = $("autosync-interval");
  if (!sw || !sel) return;
  const p = AutoSync.prefs();

  sw.setAttribute("aria-checked", p.onOpen ? "true" : "false");
  sw.classList.toggle("on", !!p.onOpen);
  sel.value = String(p.interval || 0);

  sw.onclick = () => {
    const on = sw.getAttribute("aria-checked") !== "true";
    sw.setAttribute("aria-checked", on ? "true" : "false");
    sw.classList.toggle("on", on);
    AutoSync.save({ onOpen: on });
    toast(on ? "Will sync each time the app opens" : "Sync-on-open off");
  };

  sel.onchange = () => {
    const mins = Number(sel.value) || 0;
    AutoSync.save({ interval: mins });
    toast(mins ? `Syncing every ${mins} minutes while open` : "Periodic sync off");
  };
}

/* ── external integrations ───────────────────────────────────────────────── */
async function loadIntegrationStatus() {
  if (!api() || !api().integration_status) return;
  const res = await api().integration_status();
  if (res && !res.error) integrationStatus = res;
}

async function syncGoogleFit() {
  if (!api()) return;
  const btn = $("btn-google-fit");
  btn.disabled = true;
  const old = btn.innerHTML;
  btn.innerHTML = '<span class="side-ico">G</span>Syncing Google Fit…';
  try {
    await loadIntegrationStatus();
    if (!integrationStatus.google_fit || !integrationStatus.google_fit.configured) {
      const clientId = prompt("Google OAuth Desktop client ID\n\nCreate one in Google Cloud Console and enable Fitness API first:");
      if (!clientId) return;
      const secret = prompt("Google OAuth client secret (leave blank if your client has none):") || "";
      const saved = await api().save_google_fit_config(clientId.trim(), secret.trim());
      if (handleApiError(saved, "toast")) return;
    }
    setSideStatus("Opening Google Fit sync…");
    const res = await api().sync_google_fit();
    if (handleApiError(res, "toast")) return;
    await loadIntegrationStatus();
    const c = (res && res.counts) || {};
    toast(`Google Fit synced: ${c.steps || 0} steps, ${c.heart || 0} HR, ${c.sleep || 0} sleep, ${c.spo2 || 0} SpO₂`);
    setSideStatus("Google Fit sync complete");
  } catch (err) {
    toast("Google Fit sync failed: " + err);
  } finally {
    btn.disabled = false;
    btn.innerHTML = old;
  }
}

async function sendToPoke() {
  if (!api()) return;
  const btn = $("btn-poke");
  btn.disabled = true;
  const old = btn.innerHTML;
  btn.innerHTML = '<span class="side-ico">✦</span>Sending to Poke…';
  try {
    await loadIntegrationStatus();
    if (!integrationStatus.poke || !integrationStatus.poke.configured) {
      const key = prompt("Poke V2 API key\n\nCreate one at poke.com Kitchen → API Keys:");
      if (!key) return;
      const saved = await api().save_poke_key(key.trim());
      if (handleApiError(saved, "toast")) return;
    }
    setSideStatus("Sending latest health data to Poke…");
    const res = await api().send_to_poke();
    if (handleApiError(res, "toast")) return;
    await loadIntegrationStatus();
    toast("Sent latest health data to Poke");
    setSideStatus("Poke send complete");
  } catch (err) {
    toast("Poke send failed: " + err);
  } finally {
    btn.disabled = false;
    btn.innerHTML = old;
  }
}

/* ── battery ─────────────────────────────────────────────────────────────── */
function setBattery(pct, charging) {
  if (pct == null) return;
  $("batt-pct").textContent = pct + "%";
  const fill = $("batt-fill");
  fill.style.width = Math.max(4, Math.min(100, pct)) + "%";
  fill.style.background = charging ? "#57e8a6" : pct <= 20 ? "#ff6f91" : pct <= 40 ? "#ffc56b" : "#57e8a6";
}

/* ── render dashboard payload ────────────────────────────────────────────── */
/* Payloads stream in cumulatively (battery first, then each metric as it
   resolves). Only render a metric once its key is present, so cards stay as
   quiet "—" placeholders until their data actually arrives — no flashing
   "No data yet" between emits. */
function render(data) {
  if (!data) return;
  rememberDayRecord(data);
  if (data.battery != null) setBattery(data.battery);
  if ("steps" in data) { renderSteps(data.steps || {}); renderActivity(data.steps || {}); doneCard("card-steps"); doneCard("card-activity"); }
  if ("heart" in data) { renderHeart(data.heart || {}); doneCard("card-hr"); }
  if ("sleep" in data) { renderSleep(data.sleep || {}); doneCard("card-sleep"); }
  if ("spo2" in data) { renderSpo2(data.spo2 || {}); doneCard("card-spo2"); }
  if ("stress" in data) { renderStress(data.stress || {}); doneCard("card-stress"); }
  if (typeof renderWellness === "function") renderWellness(dayRecords);
  if (typeof renderSleepHistory === "function") renderSleepHistory(dayRecords, dayKey(data.ts));
  if (typeof renderCurrentPage === "function" && typeof currentPage !== "undefined" && currentPage !== "overview") renderCurrentPage();
  if (typeof refreshHealthspanCard === "function") refreshHealthspanCard();
}

function doneCard(id) { const c = $(id); if (c) c.classList.remove("loading"); }

function emptyFoot(id, msg) { $(id).innerHTML = `<span class="empty">${msg}</span>`; }

function localDateKey(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function dayKey(ts) {
  if (!ts) return localDateKey(new Date());
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? String(ts).slice(0, 10) : localDateKey(d);
}

function dayLabel(key) {
  const d = new Date(key + "T12:00:00");
  if (Number.isNaN(d.getTime())) return key;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function rememberDayRecord(data) {
  if (!data || !data.ts || !("steps" in data || "heart" in data || "sleep" in data || "spo2" in data || "stress" in data)) return;
  dayRecords[dayKey(data.ts)] = { ...(dayRecords[dayKey(data.ts)] || {}), ...data };
  updateDayPicker(dayKey(data.ts));
  if (typeof renderWellness === "function") renderWellness(dayRecords);
  if (typeof renderSleepHistory === "function") renderSleepHistory(dayRecords, dayKey(data.ts));
}

function updateDayPicker(selected) {
  const picker = $("day-picker");
  if (!picker) return;
  const days = Object.keys(dayRecords).sort().reverse();
  picker.hidden = days.length === 0;
  picker.innerHTML = days.map((day) => `<option value="${day}">${dayLabel(day)}</option>`).join("");
  if (selected && dayRecords[selected]) picker.value = selected;
}

function renderSavedDay(day) {
  const data = dayRecords[day];
  if (!data) return;
  render(data);
  const d = new Date(day + "T12:00:00");
  const label = Number.isNaN(d.getTime()) ? day : d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
  $("today-date").textContent = label;
  $("greeting").textContent = day === dayKey() ? "Today" : "Saved day";
  setSideStatus("Showing saved data");
}

async function restoreMemory() {
  if (restoredMemory || !api() || !api().memory) return;
  try {
    const mem = await api().memory();
    restoredMemory = true;
    const device = (mem && mem.device) || {};
    dayRecords = mem.records || {};
    rememberedAddress = device.address || mem.last_address || "";
    if (rememberedAddress) $("manual-mac").value = rememberedAddress;
    if (mem.auth_error) {
      showTokenPanel(true);
      setStatus(mem.auth_error);
      return;
    }
    if (!device.info && !mem.last_data) return;

    connected = false;
    enterDashboard(device.info || {});
    if (mem.last_data && typeof renderSteps === "function") render(mem.last_data);
    const selectedDay = mem.last_data ? dayKey(mem.last_data.ts) : undefined;
    updateDayPicker(selectedDay);
    if (typeof renderWellness === "function") renderWellness(dayRecords);
    if (typeof renderSleepHistory === "function") renderSleepHistory(dayRecords, selectedDay);
    if (typeof refreshHealthspanCard === "function") refreshHealthspanCard();
    setSideStatus(mem.last_data ? "Showing saved data" : "Saved watch remembered");
    loadIntegrationStatus();
    AutoSync.start();   // sync-on-open + arm the periodic timer if enabled
  } catch (err) {
    setStatus("Could not load saved watch: " + err);
  }
}

function scheduleMemoryRestore(attempt = 0) {
  restoreMemory();
  if (!restoredMemory && attempt < 20) setTimeout(() => scheduleMemoryRestore(attempt + 1), 100);
}

document.addEventListener("DOMContentLoaded", scheduleMemoryRestore);
window.addEventListener("pywebviewready", scheduleMemoryRestore);
if (document.readyState !== "loading") scheduleMemoryRestore();
