/* charts.js — inline SVG renderers + per-card render functions.
   Loaded after app.js; shares its globals ($, fmt, emptyFoot, setBattery). */

/* Build a smooth-ish area+line sparkline from [{t,v}]. */
function sparkline(points, opts = {}) {
  const W = 600, H = 150, pad = 6;
  if (!points || points.length === 0) {
    return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"></svg>`;
  }
  const color = opts.color || "#b23a48";
  const fillTop = opts.fill || "rgba(178,58,72,0.14)";
  const vals = points.map((p) => p.v);
  const max = Math.max(...vals, opts.min != null ? opts.min : 1);
  const min = Math.min(...vals, opts.baseline != null ? opts.baseline : 0);
  const range = max - min || 1;
  const n = points.length;
  const x = (i) => pad + (i / Math.max(1, n - 1)) * (W - 2 * pad);
  const y = (v) => H - pad - ((v - min) / range) * (H - 2 * pad);

  let line = "";
  points.forEach((p, i) => { line += (i === 0 ? "M" : "L") + x(i).toFixed(1) + " " + y(p.v).toFixed(1) + " "; });
  const area = line + `L ${x(n - 1).toFixed(1)} ${H - pad} L ${x(0).toFixed(1)} ${H - pad} Z`;

  const gid = "g" + Math.random().toString(36).slice(2, 7);
  const hover = opts.tooltip ? points.map((p, i) => {
    const px = x(i), py = y(p.v);
    const hitW = (W - 2 * pad) / Math.max(1, n - 1);
    const labelX = Math.max(48, Math.min(W - 48, px));
    const labelY = Math.max(18, py - 24);
    const title = `${p.t} · ${p.v} ${opts.unit || ""}`.trim();
    return `<g class="hover-point">
      <rect class="hover-hit" x="${(px - hitW / 2).toFixed(1)}" y="0" width="${hitW.toFixed(1)}" height="${H}" fill="transparent"><title>${title}</title></rect>
      <line class="hover-line" x1="${px.toFixed(1)}" y1="${pad}" x2="${px.toFixed(1)}" y2="${H - pad}"/>
      <circle class="hover-dot" cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="4"/>
      <g class="hover-label" transform="translate(${labelX.toFixed(1)} ${labelY.toFixed(1)})">
        <rect x="-42" y="-13" width="84" height="22" rx="11"/>
        <text text-anchor="middle" y="2">${p.t} · ${p.v} ${opts.unit || ""}</text>
      </g>
    </g>`;
  }).join("") : "";

  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${fillTop}"/><stop offset="1" stop-color="${fillTop}" stop-opacity="0"/>
    </linearGradient></defs>
    <path d="${area}" fill="url(#${gid})"/>
    <path d="${line}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
    ${hover}
  </svg>`;
}

/* Vertical bars for step buckets. */
function barchart(points, color = "#4f7a5b", opts = {}) {
  const W = 600, H = 150, pad = 4;
  if (!points || !points.length) return `<svg viewBox="0 0 ${W} ${H}"></svg>`;
  const vals = points.map((p) => p.v);
  const max = Math.max(...vals, 1);
  const n = points.length;
  const bw = (W - 2 * pad) / n;
  let bars = "";
  points.forEach((p, i) => {
    const h = (p.v / max) * (H - 2 * pad);
    const bx = pad + i * bw;
    const barX = bx + bw * 0.18;
    const barY = H - pad - h;
    const barW = bw * 0.64;
    const barH = Math.max(0, h);
    if (opts.tooltip) {
      const px = bx + bw / 2;
      const labelX = Math.max(52, Math.min(W - 52, px));
      const labelY = Math.max(18, barY - 16);
      const title = `${p.t} · ${fmt(p.v)} ${opts.unit || ""}`.trim();
      bars += `<g class="hover-point">
        <rect class="hover-hit" x="${bx.toFixed(1)}" y="0" width="${bw.toFixed(1)}" height="${H}" fill="transparent"><title>${title}</title></rect>
        <rect x="${barX.toFixed(1)}" y="${barY.toFixed(1)}" width="${barW.toFixed(1)}" height="${barH.toFixed(1)}" fill="${color}" opacity="${p.v ? 0.85 : 0.14}"/>
        <line class="hover-line" x1="${px.toFixed(1)}" y1="${pad}" x2="${px.toFixed(1)}" y2="${H - pad}"/>
        <g class="hover-label" transform="translate(${labelX.toFixed(1)} ${labelY.toFixed(1)})">
          <rect x="-48" y="-13" width="96" height="22" rx="11"/>
          <text text-anchor="middle" y="2">${p.t} · ${fmt(p.v)} ${opts.unit || ""}</text>
        </g>
      </g>`;
    } else {
      bars += `<rect x="${barX.toFixed(1)}" y="${barY.toFixed(1)}" width="${barW.toFixed(1)}" height="${barH.toFixed(1)}" fill="${color}" opacity="${p.v ? 0.85 : 0.14}"/>`;
    }
  });
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${bars}</svg>`;
}

/* progress ring 0..100 (fills its square wrapper; value sits centered over it) */
function ring(value, max, color) {
  const pct = Math.max(0, Math.min(1, value / max));
  const r = 27, c = 2 * Math.PI * r, off = c * (1 - pct);
  const gid = "rg" + Math.random().toString(36).slice(2, 7);
  return `<svg viewBox="0 0 64 64" width="100%" height="100%">
    <defs><linearGradient id="${gid}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="${color}"/><stop offset="1" stop-color="${color}" stop-opacity="0.7"/>
    </linearGradient></defs>
    <circle cx="32" cy="32" r="${r}" fill="none" stroke="rgba(128,120,108,0.22)" stroke-width="4"/>
    <circle cx="32" cy="32" r="${r}" fill="none" stroke="url(#${gid})" stroke-width="4" stroke-linecap="round"
      stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${off.toFixed(1)}" transform="rotate(-90 32 32)"/>
  </svg>`;
}

/* ── per-card renderers ──────────────────────────────────────────────────── */
function renderSteps(s) {
  if (!s || !s.series || !s.series.length) {
    $("steps-total").textContent = "—"; $("chart-steps").innerHTML = ""; emptyFoot("steps-foot", "No step data yet."); return;
  }
  const total = s.today_steps != null ? s.today_steps : s.total;
  $("steps-total").textContent = fmt(total);
  $("chart-steps").innerHTML = barchart(s.series, "#4f7a5b", { tooltip: true, unit: "steps" });
  $("steps-sub").textContent = `${s.series.length} buckets`;
  $("steps-foot").textContent = "Updated just now";
}

function renderHeart(h) {
  if (!h || !h.series || !h.series.length) {
    $("hr-latest").textContent = "—"; $("chart-hr").innerHTML = ""; emptyFoot("hr-foot", "No heart-rate data yet."); return;
  }
  $("hr-latest").textContent = h.latest != null ? h.latest : "—";
  $("chart-hr").innerHTML = sparkline(h.series, { color: "#b23a48", fill: "rgba(178,58,72,0.14)", tooltip: true, unit: "bpm" });
  $("hr-sub").textContent = `${h.series.length} readings`;
  const bits = [];
  if (h.min != null && h.max != null) bits.push(`${h.min}–${h.max} bpm`);
  if (h.resting != null) bits.push(`resting ${h.resting}`);
  $("hr-foot").textContent = bits.join("  ·  ");
}

function renderSleep(s) {
  const bar = $("sleep-bar");
  if (!s || !s.duration) {
    $("sleep-dur").textContent = "—"; bar.innerHTML = ""; emptyFoot("sleep-foot", "No sleep recorded last night."); return;
  }
  const mins = s.duration;
  $("sleep-dur").textContent = `${Math.floor(mins / 60)}h ${mins % 60}m`;
  const stages = s.stages || [];
  if (stages.length) {
    const tot = stages.reduce((a, x) => a + (x.duration || 0), 0) || 1;
    bar.innerHTML = stages.map((x) =>
      `<div class="sleep-seg seg-${x.type}" style="flex:${(x.duration || 0) / tot}"></div>`).join("");
  } else { bar.innerHTML = ""; }
  const bits = [];
  if (s.score != null) bits.push(`score ${s.score}`);
  if (s.deep_min != null) bits.push(`deep ${s.deep_min}m`);
  if (s.light_min != null) bits.push(`light ${s.light_min}m`);
  $("sleep-foot").textContent = bits.join("  ·  ");
}

function renderSpo2(s) {
  if (!s || s.latest == null) { $("spo2-latest").textContent = "—"; emptyFoot("spo2-foot", "No SpO₂ readings today."); return; }
  $("spo2-latest").textContent = s.latest;
  $("spo2-foot").textContent = `range ${s.min}–${s.max}%  ·  avg ${s.avg}%`;
}

function renderStress(s) {
  const r = $("stress-ring");
  if (!s || s.latest == null) { $("stress-latest").textContent = "—"; r.innerHTML = ""; emptyFoot("stress-foot", "No stress readings today."); return; }
  const v = s.latest;
  const color = v < 40 ? "#4f7a5b" : v < 60 ? "#b8852a" : v < 80 ? "#c8502a" : "#b23a48";
  const label = v < 40 ? "relaxed" : v < 60 ? "normal" : v < 80 ? "tense" : "stressed";
  $("stress-latest").textContent = v;
  r.innerHTML = ring(v, 100, color);
  $("stress-foot").textContent = `${label}  ·  avg ${s.avg}`;
}

function renderActivity(s) {
  if (!s) return;
  const dist = s.distance_m;
  $("act-dist").textContent = dist == null ? "—" : dist >= 1000 ? (dist / 1000).toFixed(2) + " km" : dist + " m";
  $("act-cal").textContent = s.calories == null ? "—" : fmt(s.calories) + " kcal";
}

/* ── wire up controls once DOM + bridge are ready ────────────────────────── */
function wire() {
  $("btn-scan").onclick = scan;
  $("btn-connect-manual").onclick = () => connect($("manual-mac").value.trim());
  $("manual-mac").addEventListener("keydown", (e) => { if (e.key === "Enter") connect($("manual-mac").value.trim()); });
  $("btn-refresh").onclick = refresh;
  $("btn-sync-time").onclick = syncTime;
  $("btn-disconnect").onclick = disconnect;
  const picker = $("day-picker");
  if (picker) picker.onchange = () => renderSavedDay(picker.value);
}

if (document.readyState !== "loading") wire();
else document.addEventListener("DOMContentLoaded", wire);
