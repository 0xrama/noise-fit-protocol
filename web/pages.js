/* pages.js — multi-page router + detail-page renderers for NoiseFit.
   Loaded after app.js + charts.js; reuses their globals: $, fmt, num, clamp,
   avg, sparkline, barchart, ring, sleepTotals, validSleepStages, sleepQuality,
   sleepQualityLabel, fmtSleepMins, epochLabel, stageName, SLEEP_STAGE_COLORS,
   sleepHistoryRecords, dayLabel, renderSavedDay, dayRecords, api. */

/* ── routing ──────────────────────────────────────────────────────────────── */
let currentPage = "overview";

const PAGE_TITLES = {
  overview: "Today",
  sleep: "Sleep",
  heart: "Heart rate",
  steps: "Steps",
  activity: "Activity",
  weekly: "Weekly review",
  healthspan: "Healthspan",
};

function showPage(name) {
  if (!PAGE_TITLES[name]) name = "overview";
  currentPage = name;
  document.querySelectorAll(".page-view").forEach((v) => {
    v.classList.toggle("is-active", v.id === "page-" + name);
  });
  document.querySelectorAll(".page-tab").forEach((t) => {
    t.classList.toggle("is-active", t.dataset.page === name);
  });
  const g = $("greeting");
  if (g && name !== "overview") g.textContent = PAGE_TITLES[name];
  renderCurrentPage();
}

/* Re-render whichever detail page is showing (called on nav + on new data). */
function renderCurrentPage() {
  const records = (typeof dayRecords === "object" && dayRecords) || {};
  const selected = selectedDayKey();
  switch (currentPage) {
    case "sleep": renderSleepPage(records, selected); break;
    case "heart": renderHeartPage(records, selected); break;
    case "steps": renderStepsPage(records, selected); break;
    case "activity": renderActivityPage(records, selected); break;
    case "weekly": renderWeeklyPage(records, selected); break;
    case "healthspan": renderHealthspanPage(); break;
  }
}

function selectedDayKey() {
  const picker = $("day-picker");
  if (picker && picker.value) return picker.value;
  return (typeof dayKey === "function") ? dayKey() : null;
}

/* ── multi-day trend helper ─────────────────────────────────────────────────
   Pull one metric path (e.g. "heart.resting", "sleep.duration", "steps.total")
   across all saved days → [{t, v, day}] oldest-first, skipping null/zero. */
function dayTrend(records, path, opts = {}) {
  const parts = path.split(".");
  const rows = Object.entries(records || {})
    .map(([day, rec]) => {
      let v = rec;
      for (const p of parts) v = v == null ? null : v[p];
      return { day, v: num(v) };
    })
    .filter((r) => r.v != null && (opts.allowZero || r.v > 0))
    .sort((a, b) => a.day.localeCompare(b.day));
  return rows.map((r) => ({ t: shortDay(r.day), v: r.v, day: r.day }));
}

function shortDay(key) {
  return (typeof dayLabel === "function") ? dayLabel(key) : key;
}

function trendStats(points) {
  if (!points.length) return null;
  const vals = points.map((p) => p.v);
  const last = vals[vals.length - 1];
  const first = vals[0];
  return {
    avg: avg(vals),
    min: Math.min(...vals),
    max: Math.max(...vals),
    last, first,
    delta: last - first,
    n: vals.length,
  };
}

function heroStat(label, value, sub) {
  return `<div class="hstat"><span class="hstat-num">${value}</span><span class="hstat-label">${label}</span>${sub ? `<span class="hstat-sub">${sub}</span>` : ""}</div>`;
}

function emptyPanel(id, msg) {
  const el = $(id);
  if (el) el.innerHTML = `<div class="panel-empty">${msg}</div>`;
}

/* ── wire navigation once DOM is ready ──────────────────────────────────────── */
function wirePages() {
  document.querySelectorAll(".page-tab").forEach((tab) => {
    tab.onclick = () => showPage(tab.dataset.page);
  });
  document.querySelectorAll(".drill").forEach((card) => {
    card.addEventListener("click", (e) => {
      // don't hijack clicks on interactive children (e.g. day rows)
      if (e.target.closest("button, a, select, input")) return;
      if (card.dataset.page) showPage(card.dataset.page);
    });
  });
}
if (document.readyState !== "loading") wirePages();
else document.addEventListener("DOMContentLoaded", wirePages);

/* ── Sleep page ─────────────────────────────────────────────────────────────── */
function renderSleepPage(records, selectedDay) {
  const recs = (typeof sleepHistoryRecords === "function") ? sleepHistoryRecords(records) : [];
  const hasSelectedDay = !!(selectedDay && records[selectedDay]);
  const sel = hasSelectedDay ? records[selectedDay].sleep : (recs[0] && recs[0].sleep);
  if (!sel || !num(sel.duration)) {
    $("sl-dur").textContent = "—";
    $("sl-hero-stats").innerHTML = "";
    ["sl-timeline", "sl-legend", "sl-dur-trend", "sl-qual-trend", "sl-consistency", "sl-stage-mix"].forEach((id) => { const e = $(id); if (e) e.innerHTML = ""; });
    emptyPanel("sl-timeline", "No sleep recorded yet.");
    return;
  }
  $("sl-dur").textContent = fmtSleepMins(sel.duration);
  const q = sleepQuality(sel);
  $("sl-hero-stats").innerHTML =
    heroStat("quality", q == null ? "—" : q + "%", sleepQualityLabel(q)) +
    heroStat("window", [sel.start_label || epochLabel(sel.start), sel.end_label || epochLabel(sel.end)].filter(Boolean).join("–") || "—") +
    heroStat("nights tracked", recs.length);

  // stage timeline (reuse charts.js)
  const totals = sleepTotals(sel);
  const exact = validSleepStages(sel);
  const useExact = exact.length && (!num(sel.duration) || exact.reduce((a, x) => a + (num(x.duration) || 0), 0) >= num(sel.duration) * 0.8) && !sel.stages_partial;
  const segs = useExact ? exact : totals.slice().sort((a, b) => ["awake", "rem", "light", "deep"].indexOf(a.type) - ["awake", "rem", "light", "deep"].indexOf(b.type));
  $("sl-timeline").innerHTML = (typeof renderSleepTimeline === "function") ? renderSleepTimeline(sel, segs, useExact) : "";
  $("sl-legend").innerHTML = totals.map((x) =>
    `<span class="sleep-legend-item"><span class="sleep-dot" style="background:${SLEEP_STAGE_COLORS[x.type] || SLEEP_STAGE_COLORS.unknown}"></span>${stageName(x.type)} ${fmtSleepMins(x.duration)}</span>`).join("");

  // duration trend (hours)
  const durPts = dayTrend(records, "sleep.duration").map((p) => ({ t: p.t, v: +(p.v / 60).toFixed(2) }));
  drawTrend("sl-dur-trend", durPts, { color: "var(--sleep-light)", unit: "h", fill: "rgba(142,155,255,0.16)" });
  const ds = trendStats(durPts);
  $("sl-dur-foot").textContent = ds ? `avg ${ds.avg.toFixed(1)}h  ·  ${ds.n} nights  ·  range ${ds.min.toFixed(1)}–${ds.max.toFixed(1)}h` : "";

  // quality trend
  const qualPts = recs.slice().reverse().map((r) => ({ t: shortDay(r.day), v: sleepQuality(r.sleep) })).filter((p) => p.v != null);
  drawTrend("sl-qual-trend", qualPts, { color: "var(--accent)", unit: "%", fill: "rgba(95,227,232,0.16)" });
  const qs = trendStats(qualPts);
  $("sl-qual-foot").textContent = qs ? `avg ${Math.round(qs.avg)}%  ·  latest ${qs.last}%` : "";

  // bedtime consistency scatter
  renderConsistency("sl-consistency", recs);
  // stage mix stacked bars across nights
  renderStageMix("sl-stage-mix", recs);
}

/* Bedtime/wake scatter — onset & wake minute-of-day per night. */
function renderConsistency(id, recs) {
  const el = $(id);
  if (!el) return;
  const nights = recs.slice(0, 14).reverse().map((r) => {
    const s = r.sleep;
    const st = num(s.start), en = num(s.end);
    return { day: r.day, start: st, end: en };
  }).filter((n) => n.start && n.end);
  if (!nights.length) { el.innerHTML = `<div class="panel-empty">Need a few nights to chart bedtime consistency.</div>`; return; }
  const onsetMin = (sec) => { const d = new Date(sec > 1e10 ? sec : sec * 1000); let m = d.getHours() * 60 + d.getMinutes(); if (m < 12 * 60) m += 24 * 60; return m; };
  const W = 600, H = 150, padX = 8, padT = 14, padB = 22;
  const lo = 18 * 60, hi = 32 * 60; // 18:00 → 08:00 next day
  const x = (i) => padX + (i / Math.max(1, nights.length - 1)) * (W - 2 * padX);
  const y = (m) => padT + (clamp(m, lo, hi) - lo) / (hi - lo) * (H - padT - padB);
  const fmtClock = (m) => { const h = Math.floor((m % (24 * 60)) / 60); const mm = m % 60; return `${String(h).padStart(2, "0")}:${String(mm).padStart(2, "0")}`; };
  let bars = "", dots = "";
  nights.forEach((n, i) => {
    const yo = y(onsetMin(n.start)), yw = y(onsetMin(n.end));
    bars += `<line x1="${x(i).toFixed(1)}" y1="${yo.toFixed(1)}" x2="${x(i).toFixed(1)}" y2="${yw.toFixed(1)}" stroke="var(--sleep-light)" stroke-width="3" stroke-linecap="round" opacity="0.55"/>`;
    dots += `<circle cx="${x(i).toFixed(1)}" cy="${yo.toFixed(1)}" r="3.5" fill="var(--sleep-deep)"><title>${shortDay(n.day)} · bed ${fmtClock(onsetMin(n.start))}</title></circle>`;
    dots += `<circle cx="${x(i).toFixed(1)}" cy="${yw.toFixed(1)}" r="3.5" fill="var(--accent)"><title>${shortDay(n.day)} · wake ${fmtClock(onsetMin(n.end))}</title></circle>`;
  });
  const gridY = [21 * 60, 24 * 60, 27 * 60, 30 * 60].map((m) =>
    `<line x1="${padX}" y1="${y(m).toFixed(1)}" x2="${W - padX}" y2="${y(m).toFixed(1)}" stroke="var(--rule-soft)"/><text x="${padX}" y="${(y(m) - 3).toFixed(1)}" class="scatter-lab">${fmtClock(m)}</text>`).join("");
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${gridY}${bars}${dots}</svg>`;
  const onsets = nights.map((n) => onsetMin(n.start));
  const sd = onsets.length > 1 ? Math.sqrt(onsets.reduce((a, m) => a + (m - onsets.reduce((p, q) => p + q, 0) / onsets.length) ** 2, 0) / (onsets.length - 1)) : 0;
  $("sl-consistency-foot").textContent = `bedtime varies ±${Math.round(sd)} min  ·  ${nights.length} nights  ·  steadier is better`;
}

/* Stacked per-night stage mix (% of night). */
function renderStageMix(id, recs) {
  const el = $(id);
  if (!el) return;
  const nights = recs.slice(0, 12).reverse();
  if (!nights.length) { el.innerHTML = `<div class="panel-empty">No nights yet.</div>`; return; }
  el.innerHTML = nights.map((r) => {
    const totals = sleepTotals(r.sleep);
    const tot = totals.reduce((a, x) => a + (num(x.duration) || 0), 0) || 1;
    const segs = totals.map((x) => `<span class="seg-${x.type}" style="flex:${(num(x.duration) || 0) / tot}" title="${stageName(x.type)} ${fmtSleepMins(x.duration)}"></span>`).join("");
    return `<div class="mix-row"><span class="mix-day">${shortDay(r.day)}</span><span class="mix-bar">${segs}</span><span class="mix-dur">${fmtSleepMins(r.sleep.duration)}</span></div>`;
  }).join("");
}

/* ── Heart rate page (measured data only) ───────────────────────────────────── */
function renderHeartPage(records, selectedDay) {
  const sel = (records[selectedDay] && records[selectedDay].heart) || latestMetric(records, "heart");
  if (!sel) { $("hr-now").textContent = "—"; $("hr-hero-stats").innerHTML = ""; emptyPanel("hr-day", "No heart-rate data yet."); return; }
  $("hr-now").textContent = sel.latest != null ? sel.latest : "—";
  $("hr-hero-stats").innerHTML =
    heroStat("resting", sel.resting != null ? sel.resting : "—", "bpm") +
    heroStat("min", sel.min != null ? sel.min : "—", "bpm") +
    heroStat("max", sel.max != null ? sel.max : "—", "bpm");
  $("hr-day").innerHTML = (sel.series && sel.series.length)
    ? sparkline(sel.series, { color: "#ff6f91", fill: "rgba(255,111,145,0.18)", tooltip: true, unit: "bpm" })
    : `<div class="panel-empty">No samples for this day.</div>`;

  const restPts = dayTrend(records, "heart.resting");
  drawTrend("hr-resting-trend", restPts, { color: "#ff6f91", unit: "bpm", fill: "rgba(255,111,145,0.16)" });
  const rs = trendStats(restPts);
  $("hr-resting-foot").textContent = rs ? `avg ${Math.round(rs.avg)} bpm  ·  ${rs.n} days  ·  ${rs.delta <= 0 ? "▼" : "▲"} ${Math.abs(Math.round(rs.delta))} since first` : "Resting HR trend appears as days accumulate.";

  // min/max envelope across days
  renderEnvelope("hr-envelope", records);
}

function renderEnvelope(id, records) {
  const el = $(id);
  if (!el) return;
  const rows = Object.entries(records || {})
    .map(([day, rec]) => ({ day, h: rec && rec.heart }))
    .filter((r) => r.h && num(r.h.min) && num(r.h.max))
    .sort((a, b) => a.day.localeCompare(b.day));
  if (!rows.length) { el.innerHTML = `<div class="panel-empty">Daily range builds up over time.</div>`; return; }
  const W = 600, H = 150, padX = 8, padT = 12, padB = 20;
  const allMin = Math.min(...rows.map((r) => r.h.min));
  const allMax = Math.max(...rows.map((r) => r.h.max));
  const range = allMax - allMin || 1;
  const x = (i) => padX + (i / Math.max(1, rows.length - 1)) * (W - 2 * padX);
  const y = (v) => padT + (1 - (v - allMin) / range) * (H - padT - padB);
  let bands = "", rest = "";
  rows.forEach((r, i) => {
    bands += `<line x1="${x(i).toFixed(1)}" y1="${y(r.h.min).toFixed(1)}" x2="${x(i).toFixed(1)}" y2="${y(r.h.max).toFixed(1)}" stroke="rgba(255,111,145,0.4)" stroke-width="4" stroke-linecap="round"><title>${shortDay(r.day)} · ${r.h.min}–${r.h.max} bpm</title></line>`;
    if (num(r.h.resting)) rest += `<circle cx="${x(i).toFixed(1)}" cy="${y(r.h.resting).toFixed(1)}" r="2.6" fill="#ff6f91"/>`;
  });
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${bands}${rest}</svg>`;
  $("hr-env-foot").textContent = `${allMin}–${allMax} bpm overall  ·  bars = daily min→max, dots = resting`;
}

function latestMetric(records, key) {
  const days = Object.keys(records || {}).sort();
  for (let i = days.length - 1; i >= 0; i--) { const v = records[days[i]] && records[days[i]][key]; if (v && Object.keys(v).length) return v; }
  return null;
}

/* shared: draw a trend into a container using sparkline, or empty note. */
function drawTrend(id, points, opts = {}) {
  const el = $(id);
  if (!el) return;
  if (!points || points.length < 2) { el.innerHTML = `<div class="panel-empty">Charts as more days are saved (${points ? points.length : 0} so far).</div>`; return; }
  el.innerHTML = sparkline(points, Object.assign({ tooltip: true }, opts));
}

/* ── Steps page ─────────────────────────────────────────────────────────────── */
function renderStepsPage(records, selectedDay) {
  const sel = (records[selectedDay] && records[selectedDay].steps) || latestMetric(records, "steps");
  if (!sel) { $("st-total").textContent = "—"; $("st-hero-stats").innerHTML = ""; emptyPanel("st-hourly", "No step data yet."); return; }
  const total = sel.today_steps != null ? sel.today_steps : sel.total;
  $("st-total").textContent = fmt(total);
  const dist = sel.distance_m;
  $("st-hero-stats").innerHTML =
    heroStat("distance", dist == null ? "—" : dist >= 1000 ? (dist / 1000).toFixed(2) + " km" : dist + " m") +
    heroStat("calories", sel.calories == null ? "—" : fmt(sel.calories), "kcal") +
    heroStat("goal", Math.round((total / 8000) * 100) + "%", "of 8,000");
  $("st-hourly").innerHTML = (sel.series && sel.series.length)
    ? barchart(sel.series, "#57e8a6", { tooltip: true, unit: "steps" })
    : `<div class="panel-empty">No hourly buckets for this day.</div>`;

  const totalPts = dayTrend(records, "steps.today_steps").length ? dayTrend(records, "steps.today_steps") : dayTrend(records, "steps.total");
  if ($("st-trend")) {
    if (totalPts.length >= 2) $("st-trend").innerHTML = barchart(totalPts, "#57e8a6", { tooltip: true, unit: "steps" });
    else emptyPanel("st-trend", `Daily totals chart as days are saved (${totalPts.length} so far).`);
  }
  const ts = trendStats(totalPts);
  $("st-trend-foot").textContent = ts ? `avg ${fmt(Math.round(ts.avg))}/day  ·  best ${fmt(ts.max)}  ·  ${ts.n} days` : "";

  const distPts = dayTrend(records, "steps.distance_m").map((p) => ({ t: p.t, v: +(p.v / 1000).toFixed(2) }));
  drawTrend("st-dist-trend", distPts, { color: "var(--accent-2)", unit: "km", fill: "rgba(122,162,255,0.16)" });
  const ds = trendStats(distPts);
  $("st-dist-foot").textContent = ds ? `avg ${ds.avg.toFixed(2)} km/day  ·  total ${distPts.reduce((a, p) => a + p.v, 0).toFixed(1)} km` : "";
}

/* ── Activity page ──────────────────────────────────────────────────────────── */
function renderActivityPage(records, selectedDay) {
  const selected = records[selectedDay] || {};
  const sel = selected.steps || latestMetric(records, "steps");
  const standing = selected.standing || latestMetric(records, "standing");
  const activity = selected.activity || latestMetric(records, "activity");
  const dist = sel && sel.distance_m;
  $("ac-dist").textContent = dist == null ? "—" : dist >= 1000 ? (dist / 1000).toFixed(2) + " km" : dist + " m";
  $("ac-hero-stats").innerHTML =
    heroStat("calories", sel && sel.calories != null ? fmt(sel.calories) : "—", "kcal") +
    heroStat("active hours", standing && standing.active_hours != null ? `${standing.active_hours}/${standing.total_hours || 24}` : "—") +
    heroStat("activity duration", activity && activity.total != null ? fmt(activity.total) : "—", activity && activity.unit ? activity.unit : "units") +
    heroStat("steps", sel ? fmt(sel.today_steps != null ? sel.today_steps : sel.total) : "—");

  const calPts = dayTrend(records, "steps.calories");
  drawTrend("ac-cal-trend", calPts, { color: "var(--warn)", unit: "kcal", fill: "rgba(255,197,107,0.16)" });
  const cs = trendStats(calPts);
  $("ac-cal-foot").textContent = cs ? `avg ${fmt(Math.round(cs.avg))} kcal/day  ·  ${cs.n} days` : "";

  const distPts = dayTrend(records, "steps.distance_m").map((p) => ({ t: p.t, v: +(p.v / 1000).toFixed(2) }));
  drawTrend("ac-dist-trend", distPts, { color: "var(--accent-2)", unit: "km", fill: "rgba(122,162,255,0.16)" });
  const ads = trendStats(distPts);
  $("ac-dist-foot").textContent = ads ? `avg ${ads.avg.toFixed(2)} km/day` : "";

  const standingPts = dayTrend(records, "standing.active_hours");
  drawTrend("ac-standing-trend", standingPts, { color: "var(--accent)", unit: "h", fill: "rgba(95,227,232,0.14)" });
  const shs = trendStats(standingPts);
  $("ac-standing-foot").textContent = shs ? `avg ${shs.avg.toFixed(1)} active hours/day` : "";

  const durationPts = dayTrend(records, "activity.total");
  drawTrend("ac-duration-trend", durationPts, { color: "var(--ok)", unit: activity && activity.unit ? activity.unit : "units", fill: "rgba(87,232,166,0.14)" });
  const ads2 = trendStats(durationPts);
  $("ac-duration-foot").textContent = ads2 ? `avg ${Math.round(ads2.avg)} ${activity && activity.unit ? activity.unit : "units"}/day` : "";

  // weekly movement: sum steps into ISO-ish weeks (group by 7-day chunks).
  renderWeekly("ac-weekly", records);
}

function renderWeekly(id, records) {
  const el = $(id);
  if (!el) return;
  const pts = dayTrend(records, "steps.today_steps").length ? dayTrend(records, "steps.today_steps") : dayTrend(records, "steps.total");
  if (pts.length < 2) { emptyPanel(id, "Weekly movement builds up over time."); $("ac-weekly-foot").textContent = ""; return; }
  // bucket every 7 days
  const weeks = [];
  for (let i = 0; i < pts.length; i += 7) {
    const chunk = pts.slice(i, i + 7);
    weeks.push({ t: chunk[0].t, v: chunk.reduce((a, p) => a + p.v, 0) });
  }
  el.innerHTML = barchart(weeks, "#57e8a6", { tooltip: true, unit: "steps" });
  $("ac-weekly-foot").textContent = `${weeks.length} week${weeks.length === 1 ? "" : "s"}  ·  weekly step totals`;
}

/* ── Weekly review page ──────────────────────────────────────────────────────
   A 7-day recap ending on the selected (or most recent) day: step history,
   sleep history, then a derived daily activity score. Reuses dayRecords +
   the shared chart helpers; days with no data show as quiet empty slots so
   the week always reads as a full 7-bar span. */

/* The 7 day-keys ending at `endKey`, oldest-first, with weekday labels. */
function weekDayKeys(endKey) {
  const end = new Date((endKey || localDateKey(new Date())) + "T12:00:00");
  if (Number.isNaN(end.getTime())) return [];
  const out = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date(end);
    d.setDate(end.getDate() - i);
    out.push({ key: localDateKey(d), label: d.toLocaleDateString(undefined, { weekday: "short" }) });
  }
  return out;
}

/* Derived 0–100 daily activity score from steps / distance / calories.
   Steps lead (most reliable signal), with distance & calories as bonuses,
   blending only the components that are present. */
function activityScore(steps) {
  if (!steps) return null;
  const total = num(steps.today_steps != null ? steps.today_steps : steps.total);
  const cal = num(steps.calories);
  const distKm = num(steps.distance_m) != null ? num(steps.distance_m) / 1000 : null;
  const parts = [];
  if (total != null) parts.push({ v: clamp(total / 8000 * 100, 0, 100), w: 0.6 });
  if (cal != null) parts.push({ v: clamp(cal / 600 * 100, 0, 100), w: 0.2 });
  if (distKm != null) parts.push({ v: clamp(distKm / 6 * 100, 0, 100), w: 0.2 });
  if (!parts.length) return null;
  const wsum = parts.reduce((a, p) => a + p.w, 0);
  return Math.round(parts.reduce((a, p) => a + p.v * p.w, 0) / wsum);
}

function renderWeeklyPage(records, selectedDay) {
  const recs = records || {};
  // End the week on the selected day if it has data, else the latest saved day.
  const savedDays = Object.keys(recs).sort();
  const endKey = (selectedDay && recs[selectedDay]) ? selectedDay : (savedDays[savedDays.length - 1] || selectedDay);
  const days = weekDayKeys(endKey);
  if (!days.length) {
    $("wk-range").textContent = "This week";
    $("wk-hero-stats").innerHTML = "";
    ["wk-steps", "wk-sleep", "wk-activity"].forEach((id) => emptyPanel(id, "No data for this week yet."));
    return;
  }

  // Range label across the hero.
  $("wk-range").textContent = dayLabel(days[0].key) + " – " + dayLabel(days[6].key);
  $("wk-range-sub").textContent = "7-day recap";

  const stepVals = days.map((d) => num(recs[d.key] && recs[d.key].steps && (recs[d.key].steps.today_steps ?? recs[d.key].steps.total)));
  const sleepVals = days.map((d) => num(recs[d.key] && recs[d.key].sleep && recs[d.key].sleep.duration));
  const actVals = days.map((d) => activityScore(recs[d.key] && recs[d.key].steps));

  const trackedSteps = stepVals.filter((v) => v != null && v > 0);
  const trackedSleep = sleepVals.filter((v) => v != null && v > 0);
  const trackedAct = actVals.filter((v) => v != null);

  $("wk-hero-stats").innerHTML =
    heroStat("avg steps", trackedSteps.length ? fmt(Math.round(avg(trackedSteps))) : "—", `${trackedSteps.length}/7 days`) +
    heroStat("avg sleep", trackedSleep.length ? fmtSleepMins(Math.round(avg(trackedSleep))) : "—", `${trackedSleep.length}/7 nights`) +
    heroStat("avg activity", trackedAct.length ? Math.round(avg(trackedAct)) : "—", trackedAct.length ? "of 100" : "");

  // Steps — one bar per weekday (zero-filled so the full week always shows).
  const stepPts = days.map((d, i) => ({ t: d.label, v: stepVals[i] || 0 }));
  $("wk-steps").innerHTML = barchart(stepPts, "#57e8a6", { tooltip: true, unit: "steps" });
  $("wk-steps-foot").textContent = trackedSteps.length
    ? `total ${fmt(trackedSteps.reduce((a, v) => a + v, 0))} steps  ·  best ${fmt(Math.max(...trackedSteps))}`
    : "Step history fills in as days sync.";

  // Sleep — hours per night, with a stage-color key in the legend.
  const sleepPts = days.map((d, i) => ({ t: d.label, v: sleepVals[i] ? +(sleepVals[i] / 60).toFixed(1) : 0 }));
  $("wk-sleep").innerHTML = barchart(sleepPts, "var(--sleep-light)", { tooltip: true, unit: "h" });
  $("wk-sleep-foot").textContent = trackedSleep.length
    ? `avg ${fmtSleepMins(Math.round(avg(trackedSleep)))}  ·  ${trackedSleep.length} night${trackedSleep.length === 1 ? "" : "s"}`
    : "Sleep history fills in as nights sync.";

  // Activity score — bar per day (0–100).
  const actPts = days.map((d, i) => ({ t: d.label, v: actVals[i] || 0 }));
  $("wk-activity").innerHTML = barchart(actPts, "var(--warn)", { tooltip: true, unit: "/100" });
  $("wk-activity-foot").textContent = trackedAct.length
    ? `avg ${Math.round(avg(trackedAct))}/100  ·  peak ${Math.max(...trackedAct)}  ·  steps-led, with distance & calories`
    : "Activity score is derived from steps, distance and calories.";
}
let healthspanLoading = false;

async function renderHealthspanPage() {
  const body = $("hs-body");
  if (!body) return;
  if (!api() || !api().healthspan) {
    body.innerHTML = `<div class="hs-state"><p class="hs-msg">Connect your watch to unlock Healthspan.</p></div>`;
    return;
  }
  if (healthspanLoading) return;
  healthspanLoading = true;
  body.innerHTML = `<div class="hs-state"><span class="spin"></span> Computing…</div>`;
  try {
    const hs = await api().healthspan();
    if (!hs || hs.error) { body.innerHTML = `<div class="hs-state"><p class="hs-msg">${(hs && hs.error) || "Could not compute Healthspan."}</p></div>`; return; }
    if (!hs.has_profile) { renderProfileForm(body); return; }
    if (!hs.ready) { renderHealthspanCollecting(body, hs); return; }
    renderHealthspanResult(body, hs);
    updateHealthspanCard(hs);
  } catch (err) {
    body.innerHTML = `<div class="hs-state"><p class="hs-msg">Healthspan error: ${err}</p></div>`;
  } finally {
    healthspanLoading = false;
  }
}

function renderProfileForm(body) {
  body.innerHTML = `
    <div class="hs-form-wrap">
      <div class="hs-form-lede">
        <h3 class="hs-form-title">Your Healthspan</h3>
        <p>A WHOOP-style biological-age estimate. It compares your measured sleep, movement, resting heart rate and stress against expert reference values for good health, and translates the gap into years. Tell us your age to anchor the number.</p>
      </div>
      <form class="hs-form" id="hs-form">
        <label class="hs-field"><span>Birth year</span><input id="hs-birth" class="field" type="number" inputmode="numeric" placeholder="1990" min="1900" max="2013" /></label>
        <label class="hs-field"><span>Sex</span>
          <select id="hs-sex" class="field"><option value="">—</option><option value="m">Male</option><option value="f">Female</option></select>
        </label>
        <label class="hs-field"><span>Height (cm) <em>optional</em></span><input id="hs-height" class="field" type="number" inputmode="numeric" placeholder="178" /></label>
        <label class="hs-field"><span>Weight (kg) <em>optional</em></span><input id="hs-weight" class="field" type="number" inputmode="numeric" placeholder="74" /></label>
        <button type="submit" class="btn btn-primary hs-submit"><span class="btn-label">Save & compute</span><span class="btn-arrow">→</span></button>
        <p class="hs-form-err" id="hs-form-err"></p>
      </form>
      <p class="hs-disclaimer">Lifestyle estimate from wearable signals — not a clinical or diagnostic measure.</p>
    </div>`;
  $("hs-form").onsubmit = async (e) => {
    e.preventDefault();
    const err = $("hs-form-err"); err.textContent = "";
    const birth = $("hs-birth").value.trim();
    const sex = $("hs-sex").value;
    if (!birth) { err.textContent = "Enter your birth year."; return; }
    const btn = $("hs-form").querySelector("button"); btn.disabled = true;
    const res = await api().save_profile(birth, sex || null, $("hs-height").value || null, $("hs-weight").value || null);
    btn.disabled = false;
    if (res && res.error) { err.textContent = res.error; return; }
    renderHealthspanPage();
  };
}

function renderHealthspanCollecting(body, hs) {
  const pct = Math.min(100, Math.round((hs.days_have / hs.days_needed) * 100));
  body.innerHTML = `
    <div class="hs-state hs-collecting">
      <div class="hs-ring-big" id="hs-collect-ring"></div>
      <h3 class="hs-form-title">Collecting your baseline</h3>
      <p class="hs-msg">Healthspan needs about ${hs.days_needed} days of sleep & activity to read your physiology. Keep syncing each day.</p>
      <div class="hs-progress"><div class="hs-progress-fill" style="width:${pct}%"></div></div>
      <p class="hs-progress-label">${hs.days_have} / ${hs.days_needed} days · chronological age ${hs.chronological_age}</p>
      <button class="btn btn-ghost hs-edit" id="hs-edit-profile">Edit profile</button>
    </div>`;
  const r = $("hs-collect-ring"); if (r && typeof ring === "function") r.innerHTML = ring(hs.days_have, hs.days_needed, "var(--accent)");
  const edit = $("hs-edit-profile"); if (edit) edit.onclick = () => renderProfileForm($("hs-body"));
}

function renderHealthspanResult(body, hs) {
  const delta = hs.age_delta;
  const younger = delta < -0.2, older = delta > 0.2;
  const deltaClass = younger ? "is-younger" : older ? "is-older" : "is-even";
  const deltaTxt = delta === 0 ? "on par with your age" : `${delta > 0 ? "+" : ""}${delta} yr vs your age`;
  const pace = hs.pace_of_aging;
  const paceLabel = pace <= 0 ? "reverse aging" : pace < 0.85 ? "aging slower" : pace <= 1.15 ? "keeping pace" : "aging faster";
  const paceColor = pace <= 0.85 ? "var(--good)" : pace <= 1.15 ? "var(--accent)" : "var(--bad)";

  const comps = (hs.components || []).map((c) => {
    const d = c.year_delta;
    const cls = d < -0.05 ? "is-younger" : d > 0.05 ? "is-older" : "is-even";
    const sign = d > 0 ? "+" : "";
    const val = c.value == null ? "—" : `${c.value}${c.unit ? " " + c.unit : ""}`;
    const pctBar = clamp(Math.abs(d) / 6 * 100, 4, 100);
    const side = d > 0 ? "right" : "left";
    return `<div class="hs-comp ${cls}">
      <div class="hs-comp-top"><span class="hs-comp-name">${c.label}</span><span class="hs-comp-delta">${sign}${d} yr</span></div>
      <div class="hs-comp-bar"><span class="hs-comp-fill ${side}" style="width:${pctBar}%"></span></div>
      <div class="hs-comp-meta"><span>your ${val}</span><span>target ${c.reference}${c.unit ? " " + c.unit : ""}</span></div>
      ${c.note ? `<div class="hs-comp-note">${c.note}</div>` : ""}
    </div>`;
  }).join("");

  body.innerHTML = `
    <div class="hs-hero">
      <div class="hs-hero-main">
        <span class="hs-eyebrow">WHOOP-style biological age</span>
        <div class="hs-age-row">
          <span class="hs-age">${hs.whoop_age}</span>
          <div class="hs-age-side">
            <span class="hs-delta ${deltaClass}">${deltaTxt}</span>
            <span class="hs-chrono">chronological age ${hs.chronological_age}</span>
          </div>
        </div>
      </div>
      <div class="hs-pace">
        <div class="hs-pace-ring" id="hs-pace-ring"></div>
        <div class="hs-pace-center"><span class="hs-pace-num">${pace}×</span><span class="hs-pace-lab">pace</span></div>
        <span class="hs-pace-tag" style="color:${paceColor}">${paceLabel}</span>
      </div>
    </div>
    <div class="hs-comps-head">What's moving your number <span>· last 6 months · ranked by impact</span></div>
    <div class="hs-comps">${comps}</div>
    <p class="hs-disclaimer">Lifestyle estimate from measured sleep, steps, resting heart rate and stress. No VO₂max, strength or body-composition inputs (this watch can't measure them). Not a clinical measure — and like all such models, it omits uncertainty.</p>
    <button class="btn btn-ghost hs-edit" id="hs-edit-profile">Edit profile</button>`;

  const pr = $("hs-pace-ring");
  if (pr && typeof ring === "function") pr.innerHTML = ring(clamp(2 - pace, 0, 2), 2, paceColor);
  const edit = $("hs-edit-profile"); if (edit) edit.onclick = () => renderProfileForm($("hs-body"));
}

/* Keep the overview teaser card in sync. */
function updateHealthspanCard(hs) {
  const age = $("hs-card-age"), sub = $("hs-card-sub"), foot = $("hs-card-foot");
  if (!age) return;
  if (hs && hs.ready) {
    age.textContent = hs.whoop_age;
    if (sub) sub.textContent = `${hs.age_delta > 0 ? "+" : ""}${hs.age_delta} yr`;
    if (foot) foot.textContent = `vs chronological ${hs.chronological_age}  ·  pace ${hs.pace_of_aging}×`;
  } else if (hs && hs.has_profile) {
    age.textContent = hs.days_have + "/" + hs.days_needed;
    if (sub) sub.textContent = "days";
    if (foot) foot.textContent = "Collecting your baseline";
  } else {
    age.textContent = "—";
    if (foot) foot.textContent = "Tap to set up biological age";
  }
}

/* Refresh the teaser card whenever records update (called from app.js render). */
async function refreshHealthspanCard() {
  if (!api() || !api().healthspan) return;
  try { updateHealthspanCard(await api().healthspan()); } catch (e) { /* ignore */ }
}



