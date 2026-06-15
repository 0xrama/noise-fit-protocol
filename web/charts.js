/* charts.js — inline SVG renderers + per-card render functions.
   Loaded after app.js; shares its globals ($, fmt, emptyFoot, setBattery). */

/* Build a smooth-ish area+line sparkline from [{t,v}]. */
function sparkline(points, opts = {}) {
  const W = 600, H = 150, pad = 6;
  if (!points || points.length === 0) {
    return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"></svg>`;
  }
  const color = opts.color || "#ff6f91";
  const fillTop = opts.fill || "rgba(255,111,145,0.18)";
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
function barchart(points, color = "#57e8a6", opts = {}) {
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
    <circle cx="32" cy="32" r="${r}" fill="none" stroke="rgba(120,140,200,0.18)" stroke-width="4"/>
    <circle cx="32" cy="32" r="${r}" fill="none" stroke="url(#${gid})" stroke-width="4" stroke-linecap="round"
      stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${off.toFixed(1)}" transform="rotate(-90 32 32)"/>
  </svg>`;
}

/* ── wellness scoring helpers ────────────────────────────────────────────── */
const WELLNESS_UNLOCK_DAYS = 20;

function clamp(value, min, max) { return Math.max(min, Math.min(max, value)); }
function num(value) { const n = Number(value); return Number.isFinite(n) ? n : null; }
function avg(values) {
  const clean = values.map(num).filter((v) => v != null);
  return clean.length ? clean.reduce((a, v) => a + v, 0) / clean.length : null;
}
function sleepStageTotal(s, key) {
  const direct = num(s && s[key]);
  if (direct != null) return direct;
  const stages = (s && s.stages) || [];
  return stages.filter((x) => String(x.type || "").toLowerCase() === key.replace("_min", ""))
    .reduce((a, x) => a + (num(x.duration) || 0), 0);
}
function sleepQuality(s) {
  if (!s || !num(s.duration)) return null;
  const watchScore = num(s.score);
  if (watchScore != null && watchScore > 0) return Math.round(clamp(watchScore, 0, 100));
  const duration = num(s.duration) || 0;
  const deep = sleepStageTotal(s, "deep_min") || 0;
  const awake = sleepStageTotal(s, "awake_min") || 0;
  const durationScore = clamp(100 - Math.abs(duration - 480) / 2.4, 0, 100);
  const deepPct = duration ? deep / duration : 0;
  const deepScore = clamp(100 - Math.abs(deepPct - 0.22) * 260, 0, 100);
  const awakePenalty = clamp((awake / Math.max(1, duration)) * 180, 0, 35);
  return Math.round(clamp(durationScore * 0.55 + deepScore * 0.35 + 10 - awakePenalty, 0, 100));
}
function sleepQualityLabel(score) {
  if (score == null) return "—";
  if (score >= 85) return "excellent";
  if (score >= 72) return "good";
  if (score >= 58) return "fair";
  return "low";
}
function validWellnessRecords(records) {
  return Object.entries(records || {})
    .map(([day, data]) => ({ day, data }))
    .filter((r) => r.data && r.data.sleep && num(r.data.sleep.duration) > 0)
    .sort((a, b) => a.day.localeCompare(b.day));
}
function scoreFromRange(value, ideal, tolerance) {
  if (value == null) return null;
  return clamp(100 - Math.abs(value - ideal) / tolerance * 100, 0, 100);
}
function recoveryColor(score) {
  return score >= 75 ? "#57e8a6" : score >= 55 ? "#ffc56b" : "#ff6f91";
}
function renderWellness(records) {
  const recs = validWellnessRecords(records);
  const ready = recs.length >= WELLNESS_UNLOCK_DAYS;
  const recoveryCard = $("card-recovery");
  const bioageCard = $("card-bioage");
  if (recoveryCard) recoveryCard.hidden = !ready;
  if (bioageCard) bioageCard.hidden = !ready;
  if (!ready) return;

  const windowRecords = recs.slice(-WELLNESS_UNLOCK_DAYS);
  const sleepDurations = windowRecords.map((r) => num(r.data.sleep.duration)).filter((v) => v != null);
  const sleepScores = windowRecords.map((r) => sleepQuality(r.data.sleep)).filter((v) => v != null);
  const resting = windowRecords.map((r) => num(r.data.heart && r.data.heart.resting)).filter((v) => v != null);
  const steps = windowRecords.map((r) => num(r.data.steps && (r.data.steps.today_steps ?? r.data.steps.total))).filter((v) => v != null);
  const stress = windowRecords.map((r) => num(r.data.stress && (r.data.stress.avg ?? r.data.stress.latest))).filter((v) => v != null);

  const sleepAvg = avg(sleepDurations) || 0;
  const qualityAvg = avg(sleepScores) || sleepQuality({ duration: sleepAvg });
  const restingAvg = avg(resting);
  const stepsAvg = avg(steps);
  const stressAvg = avg(stress);
  const durationComponent = scoreFromRange(sleepAvg, 480, 180) || 0;
  const qualityComponent = qualityAvg || 0;
  const heartComponent = restingAvg == null ? 70 : clamp(100 - Math.max(0, restingAvg - 58) * 2.4, 35, 100);
  const activityComponent = stepsAvg == null ? 70 : clamp((stepsAvg / 9000) * 100, 35, 100);
  const stressComponent = stressAvg == null ? 70 : clamp(110 - stressAvg * 1.35, 30, 100);
  const recovery = Math.round(durationComponent * 0.25 + qualityComponent * 0.35 + heartComponent * 0.18 + activityComponent * 0.12 + stressComponent * 0.10);
  const recoveryLabel = recovery >= 75 ? "primed" : recovery >= 55 ? "steady" : "needs rest";

  $("recovery-window").textContent = `${WELLNESS_UNLOCK_DAYS}d`;
  $("recovery-score").textContent = recovery;
  $("recovery-ring").innerHTML = ring(recovery, 100, recoveryColor(recovery));
  $("recovery-foot").textContent = `${recoveryLabel}  ·  sleep quality ${Math.round(qualityAvg)}  ·  avg ${Math.round(sleepAvg / 60)}h ${Math.round(sleepAvg % 60)}m`;

  let ageDelta = 0;
  ageDelta += clamp((450 - sleepAvg) / 60, -0.8, 2.2) * 0.9;
  ageDelta += clamp((75 - qualityAvg) / 10, -1.0, 2.0) * 0.55;
  if (stepsAvg != null) ageDelta += clamp((7000 - stepsAvg) / 3500, -1.0, 1.8) * 0.65;
  if (restingAvg != null) ageDelta += clamp((restingAvg - 62) / 12, -0.8, 1.8) * 0.8;
  if (stressAvg != null) ageDelta += clamp((stressAvg - 45) / 22, -0.7, 1.6) * 0.55;
  ageDelta = clamp(ageDelta, -4.5, 7.5);
  const sign = ageDelta > 0 ? "+" : "";
  const trend = ageDelta <= -1 ? "younger trend" : ageDelta <= 1 ? "on track" : "recovery debt";

  $("bioage-window").textContent = `${WELLNESS_UNLOCK_DAYS}d`;
  $("bioage-delta").textContent = `${sign}${ageDelta.toFixed(1)}`;
  $("bioage-foot").textContent = `${trend}  ·  lifestyle estimate from sleep, activity, HR and stress`;
}

/* ── per-card renderers ──────────────────────────────────────────────────── */
function renderSteps(s) {
  if (!s || !s.series || !s.series.length) {
    $("steps-total").textContent = "—"; $("chart-steps").innerHTML = ""; emptyFoot("steps-foot", "No step data yet."); return;
  }
  const total = s.today_steps != null ? s.today_steps : s.total;
  $("steps-total").textContent = fmt(total);
  $("chart-steps").innerHTML = barchart(s.series, "#57e8a6", { tooltip: true, unit: "steps" });
  $("steps-sub").textContent = `${s.series.length} buckets`;
  $("steps-foot").textContent = "Updated just now";
}

function renderHeart(h) {
  if (!h || !h.series || !h.series.length) {
    $("hr-latest").textContent = "—"; $("chart-hr").innerHTML = ""; emptyFoot("hr-foot", "No heart-rate data yet."); return;
  }
  $("hr-latest").textContent = h.latest != null ? h.latest : "—";
  $("chart-hr").innerHTML = sparkline(h.series, { color: "#ff6f91", fill: "rgba(255,111,145,0.18)", tooltip: true, unit: "bpm" });
  $("hr-sub").textContent = `${h.series.length} readings`;
  const bits = [];
  if (h.min != null && h.max != null) bits.push(`${h.min}–${h.max} bpm`);
  if (h.resting != null) bits.push(`resting ${h.resting}`);
  $("hr-foot").textContent = bits.join("  ·  ");
}

const SLEEP_STAGE_COLORS = { awake: "var(--rule)", rem: "var(--sleep-rem)", light: "var(--sleep-light)", deep: "var(--sleep-deep)", unknown: "var(--ink-3)" };
const SLEEP_STAGE_ORDER = ["awake", "rem", "light", "deep"];

function fmtSleepMins(minutes) {
  const m = Number(minutes);
  if (!Number.isFinite(m) || m <= 0) return "—";
  return `${Math.floor(m / 60)}h ${Math.round(m % 60)}m`;
}
function epochLabel(epoch) {
  const n = Number(epoch);
  if (!Number.isFinite(n) || n <= 0) return "";
  return new Date((n > 10000000000 ? n : n * 1000)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
function stageName(type) {
  const t = String(type || "unknown").toLowerCase();
  return t === "rem" ? "REM" : t.charAt(0).toUpperCase() + t.slice(1);
}
function sleepTotals(s) {
  const direct = {
    awake: num(s && s.awake_min),
    light: num(s && s.light_min),
    deep: num(s && s.deep_min),
    rem: num(s && s.rem_min),
  };
  // An estimated REM is derived, not measured. Discard it and let the capped
  // gap-fill below re-derive it, so nights saved by an older backend (which
  // dumped the whole over-counted window into REM) get corrected on display.
  if (s && s.rem_estimated) direct.rem = null;
  const stages = (s && s.stages) || [];
  for (const typ of Object.keys(direct)) {
    if (direct[typ] == null) {
      const val = stages.filter((x) => String(x.type || "").toLowerCase() === typ)
        .reduce((a, x) => a + (num(x.duration) || 0), 0);
      if (val > 0) direct[typ] = val;
    }
  }
  const duration = num(s && s.duration);
  const knownNoRem = (direct.awake || 0) + (direct.light || 0) + (direct.deep || 0);
  if ((direct.rem == null || direct.rem === 0) && duration && knownNoRem < duration) {
    // Fill the unexplained gap with REM, but only when it's physiologically
    // plausible. A huge gap means the watch over-counted the sleep window
    // (e.g. missed wake-detection), not that the night was mostly REM — in
    // that case leave REM unknown rather than fabricating hours of it.
    const gap = duration - knownNoRem;
    const rem = Math.min(gap, Math.round(duration * 0.35));
    if (rem > 0 && gap <= duration * 0.5) direct.rem = rem;
  }
  return Object.entries(direct)
    .filter(([, duration]) => duration != null && duration > 0)
    .map(([type, duration]) => ({ type, duration }));
}
function validSleepStages(s) {
  return ((s && s.stages) || [])
    .map((x) => ({ type: String(x.type || "unknown").toLowerCase(), start: num(x.start), duration: num(x.duration) }))
    .filter((x) => x.duration && x.duration > 0 && ["awake", "light", "deep", "rem"].includes(x.type))
    .sort((a, b) => (a.start || 0) - (b.start || 0));
}
function stagePercent(duration, total) {
  const d = num(duration), t = num(total);
  if (!d || !t) return "";
  return `${Math.round((d / t) * 100)}%`;
}
function renderSleepDetail(s, totals, exactStages, useExact) {
  const total = num(s.duration) || totals.reduce((a, x) => a + (num(x.duration) || 0), 0) || 1;
  const window = [s.start_label || epochLabel(s.start), s.end_label || epochLabel(s.end)].filter(Boolean).join("–") || "—";
  const quality = s.timeline_quality || (useExact ? "exact" : exactStages.length ? "partial" : "totals");
  const qualityText = quality === "exact" ? "Exact stage timeline" : quality === "partial" ? "Partial stage timeline" : "Stage totals only";
  const coverage = s.stage_coverage_pct != null ? `${s.stage_coverage_pct}%` : (useExact ? "100%" : "—");
  const summaryRows = [
    ["Window", window],
    ["Duration", s.duration_label || fmtSleepMins(total)],
    ["Stage coverage", quality === "exact" ? "complete" : coverage],
    ["Timeline", qualityText],
  ].map(([k, v]) => `<div class="sleep-detail-row"><span>${k}</span><strong>${v}</strong></div>`).join("");

  const rowSegments = useExact ? exactStages : totals;
  // Percentages are relative to the sum of the staged segments, not the raw
  // duration — otherwise stages that over-count (or a duration that disagrees
  // with the stage sum) produce figures that exceed 100% and don't add up.
  const pctBase = rowSegments.reduce((a, x) => a + (num(x.duration) || 0), 0) || total;
  const stageRows = rowSegments.map((st) => {
    const start = st.start_label || epochLabel(st.start);
    const end = st.end_label || (st.start ? epochLabel(st.start + (num(st.duration) || 0) * 60) : "");
    const timing = start && end ? `${start}–${end}` : stagePercent(st.duration, pctBase);
    return `<div class="sleep-stage-row">
      <span class="sleep-dot" style="background:${SLEEP_STAGE_COLORS[st.type] || SLEEP_STAGE_COLORS.unknown}"></span>
      <span class="sleep-stage-name">${stageName(st.type)}</span>
      <span class="sleep-stage-time">${timing}</span>
      <strong>${fmtSleepMins(st.duration)}</strong>
    </div>`;
  }).join("");

  const observed = (!useExact && exactStages.length)
    ? `<div class="sleep-note">Observed exact transition sample: ${exactStages.slice(0, 3).map((st) => {
        const start = st.start_label || epochLabel(st.start);
        const end = st.end_label || (st.start ? epochLabel(st.start + (num(st.duration) || 0) * 60) : "");
        return `${stageName(st.type)} ${start && end ? `${start}–${end}` : fmtSleepMins(st.duration)}`;
      }).join(", ")}${exactStages.length > 3 ? "…" : ""}</div>`
    : "";
  const notes = (s.validation_notes || [])
    .map((note) => `<div class="sleep-note">${note}</div>`)
    .join("");
  return `<div class="sleep-detail-grid">${summaryRows}</div>
    <div class="sleep-stage-list">${stageRows || ""}</div>
    ${observed}
    ${notes}`;
}
function renderSleepTimeline(s, segments, exact) {
  const W = 600, H = 54, padX = 4, axisY = 43;
  if (!segments || !segments.length) return "";
  const sleepStart = num(s.start);
  const sleepEnd = num(s.end);
  const duration = num(s.duration) || segments.reduce((a, x) => a + (num(x.duration) || 0), 0) || 1;
  let minT = sleepStart || (segments[0].start || 0);
  let maxT = sleepEnd || (minT ? minT + duration * 60 : 0);
  const useClock = exact && minT && maxT && maxT > minT && segments.some((x) => x.start);
  const xClock = (sec) => padX + ((sec - minT) / (maxT - minT)) * (W - 2 * padX);
  const yMap = { awake: 8, rem: 16, light: 24, deep: 32, unknown: 24 };
  let cursor = 0;
  const rects = segments.map((seg) => {
    const type = SLEEP_STAGE_COLORS[seg.type] ? seg.type : "unknown";
    const dur = Math.max(1, num(seg.duration) || 0);
    let x, w, startLabel, endLabel;
    if (useClock && seg.start) {
      const st = seg.start;
      const en = st + dur * 60;
      x = xClock(st);
      w = Math.max(1.5, xClock(en) - x);
      startLabel = epochLabel(st); endLabel = epochLabel(en);
    } else {
      x = padX + (cursor / duration) * (W - 2 * padX);
      w = Math.max(1.5, (dur / duration) * (W - 2 * padX));
      startLabel = ""; endLabel = "";
      cursor += dur;
    }
    const title = `${stageName(type)} · ${fmtSleepMins(dur)}${startLabel ? ` · ${startLabel}–${endLabel}` : ""}`;
    return `<rect class="sleep-stage-band" x="${x.toFixed(1)}" y="${yMap[type]}" width="${w.toFixed(1)}" height="10" fill="${SLEEP_STAGE_COLORS[type]}"><title>${title}</title></rect>`;
  }).join("");
  const startText = epochLabel(sleepStart || minT);
  const endText = epochLabel(sleepEnd || maxT);
  const midText = startText && endText ? "sleep window" : "stage mix";
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    ${rects}
    <line class="sleep-axis" x1="${padX}" y1="${axisY}" x2="${W - padX}" y2="${axisY}"/>
    <text class="sleep-axis-label" x="${padX}" y="53">${startText}</text>
    <text class="sleep-axis-label" x="${W / 2}" y="53" text-anchor="middle">${midText}</text>
    <text class="sleep-axis-label" x="${W - padX}" y="53" text-anchor="end">${endText}</text>
  </svg>`;
}

function renderSleep(s) {
  const bar = $("sleep-bar");
  const chart = $("sleep-chart");
  const legend = $("sleep-legend");
  const detail = $("sleep-detail");
  if (!s || !s.duration) {
    $("sleep-dur").textContent = "—"; $("sleep-quality").textContent = "—"; $("sleep-quality-label").textContent = "—";
    bar.innerHTML = ""; if (chart) chart.innerHTML = ""; if (legend) legend.innerHTML = ""; if (detail) detail.innerHTML = "";
    emptyFoot("sleep-foot", "No sleep recorded last night."); return;
  }
  const mins = Number(s.duration);
  const quality = sleepQuality(s);
  $("sleep-dur").textContent = fmtSleepMins(mins);
  $("sleep-quality").textContent = quality == null ? "—" : `${quality}%`;
  $("sleep-quality-label").textContent = sleepQualityLabel(quality);

  const totals = sleepTotals(s);
  const exactStages = validSleepStages(s);
  const exactTotal = exactStages.reduce((a, x) => a + (num(x.duration) || 0), 0);
  const useExact = exactStages.length && (!mins || exactTotal >= mins * 0.8) && !s.stages_partial;
  const displaySegments = useExact ? exactStages : totals.sort((a, b) => SLEEP_STAGE_ORDER.indexOf(a.type) - SLEEP_STAGE_ORDER.indexOf(b.type));

  if (totals.length) {
    const tot = totals.reduce((a, x) => a + (x.duration || 0), 0) || 1;
    bar.innerHTML = totals.map((x) =>
      `<div class="sleep-seg seg-${x.type}" title="${stageName(x.type)} ${fmtSleepMins(x.duration)}" style="flex:${(x.duration || 0) / tot}"></div>`).join("");
  } else { bar.innerHTML = ""; }
  if (chart) chart.innerHTML = renderSleepTimeline(s, displaySegments, useExact);
  if (legend) legend.innerHTML = totals.map((x) =>
    `<span class="sleep-legend-item"><span class="sleep-dot" style="background:${SLEEP_STAGE_COLORS[x.type] || SLEEP_STAGE_COLORS.unknown}"></span>${stageName(x.type)} ${fmtSleepMins(x.duration)}</span>`
  ).join("");
  if (detail) detail.innerHTML = renderSleepDetail(s, totals, exactStages, useExact);

  // Footer carries only what the legend and detail grid don't already show:
  // provenance and timeline caveats. Stage minutes live in the legend.
  const bits = [];
  if (s.score != null) bits.push(`watch score ${s.score}`);
  if (s.rem_estimated) bits.push("REM estimated");
  if (s.cached) bits.push("saved sleep shown");
  if (s.cache_note) bits.push(s.cache_note);
  if (!useExact && exactStages.length) bits.push("stage timings partial — refresh once for full graph");
  else if (!useExact) bits.push("totals shown; exact transitions unavailable");
  $("sleep-foot").textContent = bits.join("  ·  ");
}

function sleepHistoryRecords(records) {
  return Object.entries(records || {})
    .map(([day, data]) => ({ day, data, sleep: data && data.sleep }))
    .filter((r) => r.sleep && num(r.sleep.duration) > 0)
    .sort((a, b) => b.day.localeCompare(a.day));
}
function sleepMiniBars(s) {
  const totals = sleepTotals(s);
  const total = totals.reduce((a, x) => a + (num(x.duration) || 0), 0) || num(s.duration) || 1;
  return `<div class="sleep-history-bars">${totals.map((x) =>
    `<span class="sleep-history-bar seg-${x.type}" style="flex:${(num(x.duration) || 0) / total}" title="${stageName(x.type)} ${fmtSleepMins(x.duration)}"></span>`
  ).join("")}</div>`;
}
function renderSleepHistory(records, selectedDay) {
  const list = $("sleep-history");
  const summary = $("sleep-history-summary");
  const sub = $("sleep-history-sub");
  const foot = $("sleep-history-foot");
  if (!list || !summary || !sub || !foot) return;
  const recs = sleepHistoryRecords(records);
  sub.textContent = recs.length ? `${recs.length} night${recs.length === 1 ? "" : "s"}` : "";
  if (!recs.length) {
    summary.innerHTML = "";
    list.innerHTML = "";
    emptyFoot("sleep-history-foot", "Sleep nights will appear here after refreshes.");
    return;
  }

  const avgDuration = Math.round(recs.reduce((a, r) => a + (num(r.sleep.duration) || 0), 0) / recs.length);
  const avgScoreValues = recs.map((r) => sleepQuality(r.sleep)).filter((v) => v != null);
  const avgScore = avgScoreValues.length ? Math.round(avgScoreValues.reduce((a, v) => a + v, 0) / avgScoreValues.length) : null;
  const latest = recs[0].sleep;
  summary.innerHTML = `<div class="sleep-history-stat"><span>Avg duration</span><strong>${fmtSleepMins(avgDuration)}</strong></div>
    <div class="sleep-history-stat"><span>Avg quality</span><strong>${avgScore == null ? "—" : `${avgScore}%`}</strong></div>
    <div class="sleep-history-stat"><span>Latest</span><strong>${fmtSleepMins(latest.duration)}</strong></div>`;

  list.innerHTML = recs.slice(0, 14).map((r) => {
    const s = r.sleep;
    const quality = sleepQuality(s);
    const window = [s.start_label || epochLabel(s.start), s.end_label || epochLabel(s.end)].filter(Boolean).join("–") || "—";
    const selected = r.day === selectedDay ? " is-selected" : "";
    const notes = s.timeline_quality === "exact" ? "exact" : s.timeline_quality === "partial" ? `${s.stage_coverage_pct || 0}% timeline` : "totals";
    return `<button class="sleep-history-row${selected}" type="button" data-day="${r.day}">
      <span class="sleep-history-date">${dayLabel(r.day)}</span>
      <span class="sleep-history-main"><strong>${fmtSleepMins(s.duration)}</strong><em>${window}</em>${sleepMiniBars(s)}</span>
      <span class="sleep-history-score">${quality == null ? "—" : `${quality}%`}<em>${notes}</em></span>
    </button>`;
  }).join("");
  list.querySelectorAll(".sleep-history-row").forEach((row) => {
    row.onclick = () => renderSavedDay(row.dataset.day);
  });
  foot.textContent = recs.length > 14 ? `Showing latest 14 of ${recs.length} saved nights` : "Click a night to inspect that saved day";
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
  const token = $("pairing-token");
  if (token) token.addEventListener("keydown", (e) => { if (e.key === "Enter") connect($("manual-mac").value.trim()); });
  $("btn-refresh").onclick = refresh;
  $("btn-sync-time").onclick = syncTime;
  const gf = $("btn-google-fit"); if (gf) gf.onclick = syncGoogleFit;
  const poke = $("btn-poke"); if (poke) poke.onclick = sendToPoke;
  $("btn-disconnect").onclick = disconnect;
  if (typeof wireAutoSync === "function") wireAutoSync();
  const picker = $("day-picker");
  if (picker) picker.onchange = () => renderSavedDay(picker.value);
}

if (document.readyState !== "loading") wire();
else document.addEventListener("DOMContentLoaded", wire);
