/* LankaEconomy.lk — Interactive Economic Dashboard Frontend
 * Supports both Python Flask API (/api/*) and static GitHub Pages (/data/*.json).
 */
(function () {
  "use strict";

  const PALETTE = [
    "#0b63b8", "#2e9a14", "#d97706", "#dc2626", "#7c3aed",
    "#0891b2", "#be185d", "#4f46e5", "#059669", "#b45309",
  ];
  const FREQ_NAMES = { A: "Annual", Q: "Quarterly", M: "Monthly", D: "Daily" };
  const DEFAULT_IMF_ENTITIES = ["LKA", "WEOWORLD", "IND", "ADVEC", "OEMDC"];

  const LK_CATEGORIES = [
    "All",
    "Sri Lanka Economy",
    "Business",
    "Banking & Finance",
    "Markets",
    "Trade & Industry",
    "Money & Prices",
  ];
  const WD_CATEGORIES = [
    "All",
    "Global Economy",
    "Business",
    "Banking & Finance",
    "Markets",
    "Trade & Industry",
    "Money & Prices",
  ];

  const state = {
    group: "lk",          // 'lk' (Sri Lanka) or 'wd' (World)
    category: "All",      // active sector filter
    summary: null,
    cbsl: null,
    imf: null,

    // Active workbench selection
    datasetId: null,
    freq: null,
    selectedSeries: [],
    chartType: "line",
    transform: "raw",
    preset: "MAX",

    periods: [],
    startIdx: 0,
    endIdx: 0,
    showTable: false,
  };

  const $ = (id) => document.getElementById(id);
  const esc = (s) =>
    String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  function fmtNum(v, dec = 2) {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
    const n = Number(v);
    if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(2) + "M";
    if (Math.abs(n) >= 1e4 && dec === 0) return n.toLocaleString("en-US", { maximumFractionDigits: 0 });
    return n.toLocaleString("en-US", {
      minimumFractionDigits: dec,
      maximumFractionDigits: dec,
    });
  }

  function svgSparkline(points, col, W = 180, H = 32) {
    const valid = (points || []).filter((x) => x && x[1] !== null && !Number.isNaN(Number(x[1])));
    if (valid.length < 2) return "";
    const vals = valid.map((x) => Number(x[1]));
    let lo = Math.min.apply(null, vals);
    let hi = Math.max.apply(null, vals);
    const pd = (hi - lo) * 0.18 || 1;
    lo -= pd;
    hi += pd;
    const X = (i) => (W * i) / Math.max(valid.length - 1, 1);
    const Y = (y) => H * (1 - (y - lo) / (hi - lo));
    const pts = valid.map((x, i) => [X(i), Y(Number(x[1]))]);
    const ln = pts.map((c, i) => (i ? "L" : "M") + c[0].toFixed(1) + " " + c[1].toFixed(1)).join("");
    return (
      `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">` +
      `<path d="${ln}L${pts[pts.length - 1][0].toFixed(1)} ${H}L${pts[0][0].toFixed(1)} ${H}Z" fill="${col}" opacity=".14"/>` +
      `<path d="${ln}" fill="none" stroke="${col}" stroke-width="2" stroke-linejoin="round"/>` +
      `</svg>`
    );
  }

  async function fetchJsonWithFallback(apiPath, staticPath) {
    try {
      const r = await fetch(apiPath);
      if (r.ok) return await r.json();
    } catch (_) {}
    const r2 = await fetch(staticPath);
    return await r2.json();
  }

  // =========================================================================
  // Initialization
  // =========================================================================
  async function init() {
    $("today").textContent = new Date().toLocaleDateString("en-GB", {
      weekday: "long",
      day: "numeric",
      month: "long",
      year: "numeric",
    });
    $("cp-year").textContent = new Date().getFullYear();

    const q = new URLSearchParams(location.search);
    // Direct News button to https://lankaneconomy.blogspot.com/ by default (or custom ?news=...)
    const newsUrl = q.get("news") || "https://lankaneconomy.blogspot.com/";
    if ($("btn-news")) $("btn-news").href = newsUrl;
    if ($("footer-news-link")) $("footer-news-link").href = newsUrl;

    if (q.get("g") === "wd" || q.get("g") === "lk") {
      state.group = q.get("g");
    } else {
      try {
        state.group = localStorage.getItem("grp") === "wd" ? "wd" : "lk";
      } catch (_) {}
    }
    document.body.setAttribute("data-g", state.group);

    const [summary, cbsl, imf] = await Promise.all([
      fetchJsonWithFallback("/api/summary", "data/summary.json"),
      fetchJsonWithFallback("/api/cbsl", "data/cbsl_data.json"),
      fetchJsonWithFallback("/api/imf", "data/imf_data.json"),
    ]);
    state.summary = summary;
    state.cbsl = cbsl;
    state.imf = imf;

    const totalSeries = (cbsl?.stats?.series || 0) + (imf?.stats?.series || 0);
    $("dataset-badge").textContent = `${(cbsl.stats.tables + imf.stats.indicators)} Datasets · ${totalSeries.toLocaleString()} Series`;

    setupSearch();
    refreshView(true);
  }

  // =========================================================================
  // Mode & Category Filter Switching
  // =========================================================================
  function setGroup(g) {
    if (g !== "lk" && g !== "wd") return;
    state.group = g;
    state.category = "All";
    document.body.setAttribute("data-g", g);
    try {
      localStorage.setItem("grp", g);
    } catch (_) {}
    refreshView(true);
  }

  function setCategory(cat) {
    state.category = cat;
    refreshView(true);
  }

  function renderCategoryBar() {
    const cats = state.group === "lk" ? LK_CATEGORIES : WD_CATEGORIES;
    const allItems = state.group === "lk" ? state.cbsl?.tables || [] : state.imf?.indicators || [];
    $("cat-bar").innerHTML = cats
      .map((c) => {
        const cnt = c === "All" ? allItems.length : allItems.filter((x) => x.category === c).length;
        const on = state.category === c;
        return (
          `<button type="button" class="cat-pill ${on ? "on" : ""}" onclick="App.setCategory('${esc(c)}')">` +
          `${esc(c)} <span class="cnt">${cnt}</span>` +
          `</button>`
        );
      })
      .join("");
  }

  // =========================================================================
  // Main View Refresh (Category Pills + Ticker + KPI Strip + Workbench + Gallery)
  // =========================================================================
  function refreshView(resetDataset = false) {
    renderCategoryBar();
    renderTicker();
    renderKpiStrip();
    populateDatasetSelector(resetDataset);
    renderGallery();
  }

  function renderTicker() {
    const hl = state.summary?.highlights || {};
    const items = state.group === "lk" ? hl.ticker_lk || [] : hl.ticker_wd || [];
    $("ticker-badge").textContent = state.group === "lk" ? "Sri Lanka Indicators" : "Global Indicators";
    $("tick").innerHTML = items
      .map(
        (it, idx) =>
          `<span class="tick-item" onclick="App.onKpiClick(${idx})">` +
          `<strong>${esc(it.label)}:</strong> ${esc(it.value)} ` +
          `<span class="${it.up ? "up" : "dn"}">${esc(it.change)}</span>` +
          `</span>`
      )
      .join("");
  }

  function renderKpiStrip() {
    const hl = state.summary?.highlights || {};
    const kpis = (state.group === "lk" ? hl.lk_kpis : hl.wd_kpis) || [];
    $("kpi-strip").innerHTML = kpis
      .slice(0, 10)
      .map((k, idx) => {
        const up = k.change >= 0;
        const sign = up ? "▲ +" : "▼ ";
        const unitLabel = k.is_pct && k.unit === "%" ? "%" : ` <small>${esc(k.unit)}</small>`;
        return (
          `<article class="kpi-card" onclick="App.onKpiClick(${idx})" title="Click to inspect in main chart">` +
          `<div class="kpi-top">` +
          `<span class="kpi-title">${esc(k.title)}</span>` +
          `<span class="kpi-period">${esc(k.period)}</span>` +
          `</div>` +
          `<div class="kpi-val">${fmtNum(k.value, k.decimals)}${unitLabel}</div>` +
          `<div class="kpi-delta ${up ? "up" : "dn"}">${sign}${fmtNum(k.change, k.decimals)} vs ${esc(k.prev_period)}</div>` +
          `<div class="kpi-spark">${svgSparkline(k.sparkline, k.color || "#0b63b8")}</div>` +
          `</article>`
        );
      })
      .join("");
  }

  function onKpiClick(idx) {
    if (state.group === "lk") {
      const map = [
        "ccpi_and_ccpi_core",
        "ncpi_and_ncpi_core",
        "cbsl_quarterly_gdp_growth",
        "table4_04",
        "if_buying_selling_exchange_rates",
        "table2_15_2",
        "table2_14_2",
        "table2_14_1",
        "table2_02",
        "table2_04",
      ];
      const tid = map[idx];
      if (tid) onSelectDataset(tid);
    } else {
      const map = [
        "NGDP_RPCH",
        "PCPIPCH",
        "NGDP_RPCH",
        "NGDP_RPCH",
        "NGDP_RPCH",
        "GGXWDG_NGDP",
        "NGDP_RPCH",
        "PCPIPCH",
        "GGXWDG_NGDP",
        "BCA_NGDPD",
      ];
      const indId = map[idx];
      if (indId) onSelectDataset(indId);
    }
    $("workbench").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // =========================================================================
  // Dataset & Series Selection
  // =========================================================================
  function getFilteredDatasets() {
    if (state.group === "lk") {
      const all = state.cbsl?.tables || [];
      if (state.category === "All") return all;
      return all.filter((t) => t.category === state.category);
    } else {
      const all = state.imf?.indicators || [];
      if (state.category === "All") return all;
      return all.filter((i) => i.category === state.category);
    }
  }

  function populateDatasetSelector(resetSelection) {
    const list = getFilteredDatasets();
    const sel = $("sel-dataset");
    if (!list.length) {
      sel.innerHTML = `<option value="">No datasets in this sector</option>`;
      return;
    }

    if (state.group === "lk") {
      $("lbl-dataset").textContent = "1. Select Sri Lanka Economic Dataset";
      $("lbl-dataset-count").textContent = `${list.length} datasets`;
      $("lbl-series").textContent = "2. Select Time-Series to Plot (Multi-Select)";
      sel.innerHTML = list
        .map(
          (t) =>
            `<option value="${esc(t.id)}">[${esc(t.category)}] ${esc(t.title)} (${t.start}–${t.end}, ${t.series_count} series)</option>`
        )
        .join("");
    } else {
      $("lbl-dataset").textContent = "1. Select Global Economic Indicator";
      $("lbl-dataset-count").textContent = `${list.length} indicators`;
      $("lbl-series").textContent = "2. Compare Countries & Regions (Multi-Select)";
      sel.innerHTML = list
        .map(
          (ind) =>
            `<option value="${esc(ind.id)}">[${esc(ind.category)}] ${esc(ind.title)} — ${esc(ind.unit)} (${ind.start}–${ind.end})</option>`
        )
        .join("");
    }

    if (resetSelection || !list.some((x) => x.id === state.datasetId)) {
      state.datasetId = list[0].id;
    }
    sel.value = state.datasetId;
    loadActiveDataset(true);
  }

  function onSelectDataset(id, preferredSeriesIds = null) {
    state.datasetId = id;
    const sel = $("sel-dataset");
    if (![...sel.options].some((o) => o.value === id)) {
      state.category = "All";
      renderCategoryBar();
      populateDatasetSelector(false);
      sel.value = id;
    } else {
      sel.value = id;
    }
    loadActiveDataset(true, preferredSeriesIds);
  }

  function loadActiveDataset(resetSeries = true, preferredSeriesIds = null) {
    if (state.group === "lk") {
      const tbl = (state.cbsl?.tables || []).find((t) => t.id === state.datasetId);
      if (!tbl) return;

      $("wb-cat-badge").textContent = tbl.category;
      $("wb-title").textContent = tbl.title;
      $("wb-unit").textContent = `Unit: ${tbl.unit || "See series label"}`;
      $("wb-span").textContent = `Span: ${tbl.start} to ${tbl.end}`;

      const freqs = tbl.frequencies || ["A"];
      if (!state.freq || !freqs.includes(state.freq) || resetSeries) {
        state.freq = ["M", "Q", "A", "D"].find((f) => freqs.includes(f)) || freqs[0];
      }
      renderFreqButtons(freqs);
      $("wb-freq").textContent = `Frequency: ${FREQ_NAMES[state.freq] || state.freq}`;

      const availSeries = tbl.series.filter((s) => s.freq === state.freq);
      if (preferredSeriesIds && preferredSeriesIds.length) {
        state.selectedSeries = preferredSeriesIds;
      } else if (resetSeries || !state.selectedSeries.some((id) => availSeries.some((s) => s.id === id))) {
        state.selectedSeries = pickDefaultCbslSeries(tbl, availSeries);
      }
      renderSeriesChips(
        availSeries.map((s) => ({
          id: s.id,
          label: `${s.name} (${fmtNum(s.last, 1)})`,
          title: `${s.name} · ${s.start} to ${s.end}`,
        }))
      );
    } else {
      const ind = (state.imf?.indicators || []).find((i) => i.id === state.datasetId);
      if (!ind) return;

      $("wb-cat-badge").textContent = ind.category;
      $("wb-title").textContent = ind.title;
      $("wb-unit").textContent = `Unit: ${ind.unit}`;
      $("wb-freq").textContent = "Frequency: Annual (with Projections)";
      $("wb-span").textContent = `Span: ${ind.start} to ${ind.end}`;
      $("freq-btns").style.display = "none";

      const availEntities = (state.imf?.entities || []).filter((e) => ind.values[e.code]);
      if (preferredSeriesIds && preferredSeriesIds.length) {
        state.selectedSeries = preferredSeriesIds;
      } else if (resetSeries || !state.selectedSeries.some((c) => ind.values[c])) {
        const defaults = DEFAULT_IMF_ENTITIES.filter((c) => ind.values[c]);
        state.selectedSeries = defaults.length ? defaults : availEntities.slice(0, 4).map((e) => e.code);
      }
      renderSeriesChips(
        availEntities.map((e) => {
          const pts = ind.values[e.code] || [];
          const last = pts.length ? pts[pts.length - 1][1] : null;
          return {
            id: e.code,
            label: `${e.name} (${fmtNum(last, 1)})`,
            title: `${e.name} [${e.code}]`,
          };
        })
      );
    }

    recomputePeriodUnion();
    applyPreset(state.preset, false);
    renderMainChart();
  }

  function pickDefaultCbslSeries(tbl, availSeries) {
    if (!availSeries.length) return [];
    const id = tbl.id;
    if (id.includes("ccpi") || id.includes("ncpi")) {
      const yoy = availSeries.filter((s) => s.name.toLowerCase().includes("year-on-year"));
      if (yoy.length) return yoy.map((s) => s.id);
    }
    if (id.includes("if_monthly_average") || id.includes("if_end_of_the_month")) {
      const fx = availSeries.filter((s) => /\b(USD|EUR|GBP|INR)\b/.test(s.name));
      if (fx.length) return fx.slice(0, 3).map((s) => s.id);
    }
    if (id.includes("if_buying_selling")) {
      const usd = availSeries.filter((s) => s.name.includes("USD"));
      if (usd.length) return usd.map((s) => s.id);
    }
    if (id.includes("table4_04")) {
      const rates = availSeries.filter((s) => /(OPR|SDFR|SLFR|3-Month|AWPR)/i.test(s.name));
      if (rates.length) return rates.slice(0, 4).map((s) => s.id);
    }
    return availSeries.slice(0, Math.min(3, availSeries.length)).map((s) => s.id);
  }

  function renderFreqButtons(freqs) {
    const box = $("freq-btns");
    if (freqs.length <= 1) {
      box.style.display = "none";
      return;
    }
    box.style.display = "flex";
    box.innerHTML =
      `<span class="toolbar-lbl">Freq:</span>` +
      freqs
        .map(
          (f) =>
            `<button type="button" class="tbtn ${state.freq === f ? "active" : ""}" onclick="App.setFreq('${f}')">${esc(FREQ_NAMES[f] || f)}</button>`
        )
        .join("");
  }

  function setFreq(f) {
    state.freq = f;
    loadActiveDataset(true);
  }

  function renderSeriesChips(items) {
    const box = $("series-picker");
    box.innerHTML = items
      .map((it) => {
        const on = state.selectedSeries.includes(it.id);
        return `<button type="button" class="sp-chip ${on ? "active" : ""}" title="${esc(it.title)}" onclick="App.toggleSeries('${esc(it.id)}')">${esc(it.label)}</button>`;
      })
      .join("");
  }

  function toggleSeries(id) {
    const idx = state.selectedSeries.indexOf(id);
    if (idx > -1) {
      if (state.selectedSeries.length === 1) return;
      state.selectedSeries.splice(idx, 1);
    } else {
      state.selectedSeries.push(id);
    }
    loadActiveDataset(false, state.selectedSeries);
  }

  function clearSeriesSelection() {
    state.selectedSeries = state.selectedSeries.slice(0, 1);
    loadActiveDataset(false, state.selectedSeries);
  }

  // =========================================================================
  // Adjustable Time Period Engine (Presets + Dropdowns + Dual Sliders)
  // =========================================================================
  function getActiveSeriesObjects() {
    if (state.group === "lk") {
      const tbl = (state.cbsl?.tables || []).find((t) => t.id === state.datasetId);
      if (!tbl) return [];
      const map = new Map(tbl.series.map((s) => [s.id, s]));
      return state.selectedSeries
        .map((id) => map.get(id))
        .filter(Boolean)
        .map((s) => ({ id: s.id, name: s.name, freq: s.freq, data: s.data }));
    } else {
      const ind = (state.imf?.indicators || []).find((i) => i.id === state.datasetId);
      if (!ind) return [];
      const entMap = new Map((state.imf?.entities || []).map((e) => [e.code, e.name]));
      return state.selectedSeries
        .filter((c) => ind.values[c])
        .map((c) => ({
          id: c,
          name: `${entMap.get(c) || c}`,
          freq: "A",
          data: ind.values[c],
        }));
    }
  }

  function recomputePeriodUnion() {
    const seriesList = getActiveSeriesObjects();
    const pset = new Set();
    seriesList.forEach((s) => {
      (s.data || []).forEach(([p]) => pset.add(p));
    });
    state.periods = Array.from(pset).sort();
    const maxIdx = Math.max(0, state.periods.length - 1);

    const selStart = $("sel-start");
    const selEnd = $("sel-end");
    const opts = state.periods.map((p, i) => `<option value="${i}">${esc(p)}</option>`).join("");
    selStart.innerHTML = opts;
    selEnd.innerHTML = opts;

    $("rng-start").max = maxIdx;
    $("rng-end").max = maxIdx;
    state.startIdx = 0;
    state.endIdx = maxIdx;
    syncRangeControls();
  }

  function setPreset(p) {
    state.preset = p;
    document.querySelectorAll("#preset-btns .tbtn").forEach((b) => {
      b.classList.toggle("active", b.getAttribute("data-p") === p);
    });
    applyPreset(p, true);
    renderGallery();
  }

  function applyPreset(p, redraw = true) {
    const n = state.periods.length;
    if (!n) return;
    state.endIdx = n - 1;
    if (p === "MAX" || p === "CUSTOM") {
      if (p === "MAX") state.startIdx = 0;
    } else {
      const years = parseInt(p.replace("Y", ""), 10) || 5;
      const lastP = state.periods[n - 1];
      const endYear = parseInt(String(lastP).slice(0, 4), 10);
      const targetYear = String(endYear - years);
      const suffix = String(lastP).slice(4);
      const cutoff = targetYear + suffix;
      const idx = state.periods.findIndex((per) => per >= cutoff);
      state.startIdx = idx >= 0 ? idx : 0;
    }
    syncRangeControls();
    if (redraw) renderMainChart();
  }

  function syncRangeControls() {
    $("sel-start").value = String(state.startIdx);
    $("sel-end").value = String(state.endIdx);
    $("rng-start").value = String(state.startIdx);
    $("rng-end").value = String(state.endIdx);
    const count = Math.max(0, state.endIdx - state.startIdx + 1);
    const p0 = state.periods[state.startIdx] || "—";
    const p1 = state.periods[state.endIdx] || "—";
    $("lbl-obs-count").textContent = `${p0} → ${p1} (${count} periods)`;
  }

  function onSelectRangeDropdowns() {
    let s = parseInt($("sel-start").value, 10) || 0;
    let e = parseInt($("sel-end").value, 10) || 0;
    if (s > e) [s, e] = [e, s];
    state.startIdx = s;
    state.endIdx = e;
    state.preset = "CUSTOM";
    document.querySelectorAll("#preset-btns .tbtn").forEach((b) => b.classList.remove("active"));
    syncRangeControls();
    renderMainChart();
  }

  function onSliderInput(which) {
    let s = parseInt($("rng-start").value, 10) || 0;
    let e = parseInt($("rng-end").value, 10) || 0;
    if (which === "start" && s > e) s = e;
    if (which === "end" && e < s) e = s;
    state.startIdx = s;
    state.endIdx = e;
    state.preset = "CUSTOM";
    document.querySelectorAll("#preset-btns .tbtn").forEach((b) => b.classList.remove("active"));
    syncRangeControls();
    renderMainChart();
  }

  function setChartType(ct) {
    state.chartType = ct;
    document.querySelectorAll("[data-ct]").forEach((b) => {
      b.classList.toggle("active", b.getAttribute("data-ct") === ct);
    });
    renderMainChart();
  }

  function setTransform(tr) {
    state.transform = tr;
    document.querySelectorAll("[data-tr]").forEach((b) => {
      b.classList.toggle("active", b.getAttribute("data-tr") === tr);
    });
    renderMainChart();
  }

  // =========================================================================
  // Data Transformations & Main Interactive Plotly Graph
  // =========================================================================
  function transformSeries(pts, freq, startP, endP) {
    let mapped = pts.map(([p, v]) => [p, Number(v)]);
    if (state.transform === "yoy") {
      const lag = freq === "M" ? 12 : freq === "Q" ? 4 : freq === "D" ? 252 : 1;
      const out = [];
      for (let i = lag; i < mapped.length; i++) {
        const prev = mapped[i - lag][1];
        const cur = mapped[i][1];
        if (prev && Math.abs(prev) > 1e-9) {
          out.push([mapped[i][0], Number((((cur - prev) / Math.abs(prev)) * 100).toFixed(2))]);
        }
      }
      mapped = out;
    }
    const sliced = mapped.filter(([p]) => p >= startP && p <= endP);
    if (state.transform === "idx" && sliced.length) {
      const base = sliced.find(([, v]) => v && Math.abs(v) > 1e-9)?.[1] || 1;
      return sliced.map(([p, v]) => [p, Number(((v / base) * 100).toFixed(2))]);
    }
    return sliced;
  }

  function renderMainChart() {
    const seriesList = getActiveSeriesObjects();
    const startP = state.periods[state.startIdx] || "";
    const endP = state.periods[state.endIdx] || "";

    const traces = [];
    const statsHtml = [];
    const legendHtml = [];

    seriesList.forEach((s, idx) => {
      const color = PALETTE[idx % PALETTE.length];
      const pts = transformSeries(s.data || [], s.freq, startP, endP);
      const xs = pts.map(([p]) => p);
      const ys = pts.map(([, v]) => v);

      legendHtml.push(
        `<span class="legend-item" title="${esc(s.name)}">` +
          `<i class="legend-dot" style="background:${color}"></i>` +
          `<span class="legend-text">${esc(s.name)}</span>` +
          `</span>`
      );

      const trace = {
        name: s.name,
        x: xs,
        y: ys,
        line: { color, width: 2.5, shape: "spline", smoothing: 0.35 },
        marker: { color, size: 5 },
        hovertemplate: `<b>${esc(s.name)}</b><br>Period: %{x}<br>Value: <b>%{y:,.2f}</b><extra></extra>`,
      };

      if (state.chartType === "bar") {
        trace.type = "bar";
        trace.marker = { color };
      } else if (state.chartType === "area") {
        trace.type = "scatter";
        trace.mode = "lines";
        trace.fill = idx === 0 ? "tozeroy" : "tonexty";
        trace.fillcolor = color + "22";
      } else if (state.chartType === "scatter") {
        trace.type = "scatter";
        trace.mode = "lines+markers";
      } else {
        trace.type = "scatter";
        trace.mode = pts.length <= 45 ? "lines+markers" : "lines";
      }
      traces.push(trace);

      if (ys.length) {
        const minV = Math.min(...ys);
        const maxV = Math.max(...ys);
        const avgV = ys.reduce((a, b) => a + b, 0) / ys.length;
        const firstV = ys[0];
        const lastV = ys[ys.length - 1];
        const chg = lastV - firstV;
        statsHtml.push(
          `<div class="stat-box" style="border-left:4px solid ${color}">` +
            `<h5 title="${esc(s.name)}">${esc(s.name)}</h5>` +
            `<div class="stat-row"><span>Latest (${esc(xs[xs.length - 1])})</span><b>${fmtNum(lastV, 2)}</b></div>` +
            `<div class="stat-row"><span>Period Change</span><b style="color:${chg >= 0 ? "#2e9a14" : "#dc2626"}">${chg >= 0 ? "+" : ""}${fmtNum(chg, 2)}</b></div>` +
            `<div class="stat-row"><span>Min / Max</span><b>${fmtNum(minV, 1)} / ${fmtNum(maxV, 1)}</b></div>` +
            `<div class="stat-row"><span>Mean (${ys.length} obs)</span><b>${fmtNum(avgV, 2)}</b></div>` +
            `</div>`
        );
      }
    });

    if ($("main-legend")) $("main-legend").innerHTML = legendHtml.join("");
    $("stats-strip").innerHTML = statsHtml.join("");

    const yLabel =
      state.transform === "yoy"
        ? "YoY % Change"
        : state.transform === "idx"
        ? `Index (${startP} = 100)`
        : $("wb-unit").textContent.replace("Unit: ", "");

    const isMobile = window.innerWidth <= 600;
    const layout = {
      margin: isMobile
        ? { l: 46, r: 12, t: 12, b: 52 }
        : { l: 64, r: 24, t: 16, b: 64 },
      height: isMobile ? 340 : 450,
      paper_bgcolor: "#ffffff",
      plot_bgcolor: "#ffffff",
      font: { family: "Inter, sans-serif", size: isMobile ? 10.5 : 12, color: "#16202e" },
      hovermode: "x unified",
      barmode: "group",
      showlegend: false,
      xaxis: {
        type: "category",
        gridcolor: "#edf1f6",
        tickangle: isMobile ? -35 : -30,
        nticks: isMobile ? 7 : 14,
        automargin: true,
        showspikes: true,
        spikemode: "across",
        spikethickness: 1,
      },
      yaxis: {
        title: isMobile
          ? undefined
          : { text: yLabel, font: { size: 11.5, color: "#5b6675" }, standoff: 10 },
        gridcolor: "#e6ebf2",
        automargin: true,
        zeroline: true,
        zerolinecolor: "#94a3b8",
        zerolinewidth: 1,
      },
    };

    if (window.Plotly) {
      window.Plotly.react("main-chart", traces, layout, {
        responsive: true,
        displaylogo: false,
        displayModeBar: !isMobile,
        modeBarButtonsToRemove: ["lasso2d", "select2d"],
      });
    }

    if (state.showTable) renderDataTable(seriesList, startP, endP);
  }

  // =========================================================================
  // Data Table & CSV Export
  // =========================================================================
  function toggleTable() {
    state.showTable = !state.showTable;
    $("data-drawer").style.display = state.showTable ? "block" : "none";
    $("btn-toggle-tbl").classList.toggle("active", state.showTable);
    if (state.showTable) {
      const startP = state.periods[state.startIdx] || "";
      const endP = state.periods[state.endIdx] || "";
      renderDataTable(getActiveSeriesObjects(), startP, endP);
    }
  }

  function renderDataTable(seriesList, startP, endP) {
    const transformed = seriesList.map((s) => ({
      name: s.name,
      map: new Map(transformSeries(s.data || [], s.freq, startP, endP)),
    }));
    const rowsPeriods = state.periods.slice(state.startIdx, state.endIdx + 1).slice().reverse();

    let html = `<table class="data-tbl"><thead><tr><th>Period</th>`;
    transformed.forEach((s) => {
      html += `<th>${esc(s.name)}</th>`;
    });
    html += `</tr></thead><tbody>`;
    rowsPeriods.forEach((p) => {
      html += `<tr><td>${esc(p)}</td>`;
      transformed.forEach((s) => {
        const v = s.map.get(p);
        html += `<td>${v !== undefined ? fmtNum(v, 2) : "—"}</td>`;
      });
      html += `</tr>`;
    });
    html += `</tbody></table>`;
    $("table-scroll").innerHTML = html;
  }

  function downloadCSV() {
    const seriesList = getActiveSeriesObjects();
    const startP = state.periods[state.startIdx] || "";
    const endP = state.periods[state.endIdx] || "";
    const transformed = seriesList.map((s) => ({
      name: s.name,
      map: new Map(transformSeries(s.data || [], s.freq, startP, endP)),
    }));
    const rowsPeriods = state.periods.slice(state.startIdx, state.endIdx + 1);
    const header = ["Period", ...transformed.map((s) => `"${s.name.replace(/"/g, '""')}"`)].join(",");
    const lines = [header];
    rowsPeriods.forEach((p) => {
      const cells = [p, ...transformed.map((s) => (s.map.get(p) ?? ""))];
      lines.push(cells.join(","));
    });
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${state.datasetId}_${startP}_${endP}.csv`;
    a.click();
  }

  // =========================================================================
  // Multi-Chart Gallery (Synchronized with Sector & Time Period Preset)
  // =========================================================================
  function renderGallery() {
    const list = getFilteredDatasets().slice(0, 8);
    const catTitle =
      state.category === "All"
        ? state.group === "lk"
          ? "Sri Lanka Economy — Interactive Charts"
          : "Global Economy — Interactive Charts"
        : `${state.category} — Interactive Charts`;
    $("gallery-title").textContent = catTitle;

    const grid = $("gallery-grid");
    grid.innerHTML = list
      .map((item, idx) => {
        if (state.group === "lk") {
          const f = ["M", "Q", "A", "D"].find((x) => item.frequencies.includes(x)) || item.frequencies[0];
          const sList = item.series.filter((s) => s.freq === f);
          const s0 = sList[0];
          const lastVal = s0 ? fmtNum(s0.last, 1) : "—";
          const lastPer = s0 ? s0.end : item.end;
          return (
            `<article class="gcard">` +
            `<div class="gcard-head">` +
            `<div><h3 title="${esc(item.title)}">${esc(item.title)}</h3><div class="gcard-sub">${esc(item.category)} · ${esc(item.unit || FREQ_NAMES[f])}</div></div>` +
            `<div class="gcard-val"><div class="big">${lastVal}</div><div class="per">${esc(lastPer)}</div></div>` +
            `</div>` +
            `<div class="chart-legend gcard-legend" id="glegend-${idx}"></div>` +
            `<div class="gcard-chart" id="gchart-${idx}"></div>` +
            `<div class="gcard-foot">` +
            `<span>${item.start} – ${item.end} (${item.series_count} series)</span>` +
            `<button type="button" class="gcard-btn" onclick="App.openInWorkbench('${esc(item.id)}')">Explore &amp; Compare →</button>` +
            `</div>` +
            `</article>`
          );
        } else {
          const pts = item.values["LKA"] || item.values["WEOWORLD"] || Object.values(item.values)[0] || [];
          const last = pts.length ? pts[pts.length - 1] : ["—", null];
          return (
            `<article class="gcard">` +
            `<div class="gcard-head">` +
            `<div><h3 title="${esc(item.title)}">${esc(item.title)}</h3><div class="gcard-sub">${esc(item.category)} · ${esc(item.unit)}</div></div>` +
            `<div class="gcard-val"><div class="big">${fmtNum(last[1], 1)}</div><div class="per">${esc(last[0])}</div></div>` +
            `</div>` +
            `<div class="chart-legend gcard-legend" id="glegend-${idx}"></div>` +
            `<div class="gcard-chart" id="gchart-${idx}"></div>` +
            `<div class="gcard-foot">` +
            `<span>${item.start} – ${item.end} (${item.entity_count} economies)</span>` +
            `<button type="button" class="gcard-btn" onclick="App.openInWorkbench('${esc(item.id)}')">Compare Countries →</button>` +
            `</div>` +
            `</article>`
          );
        }
      })
      .join("");

    list.forEach((item, idx) => {
      const containerId = `gchart-${idx}`;
      const legendEl = $(`glegend-${idx}`);
      const el = $(containerId);
      if (!el || !window.Plotly) return;
      const traces = [];
      const legendItems = [];

      if (state.group === "lk") {
        const f = ["M", "Q", "A", "D"].find((x) => item.frequencies.includes(x)) || item.frequencies[0];
        const avail = item.series.filter((s) => s.freq === f);
        const picked = pickDefaultCbslSeries(item, avail)
          .slice(0, 2)
          .map((id) => avail.find((s) => s.id === id))
          .filter(Boolean);
        picked.forEach((s, si) => {
          const color = PALETTE[(idx + si) % PALETTE.length];
          const pts = sliceByActivePreset(s.data);
          legendItems.push(
            `<span class="legend-item" title="${esc(s.name)}">` +
              `<i class="legend-dot" style="background:${color}"></i>` +
              `<span class="legend-text">${esc(s.name)}</span>` +
              `</span>`
          );
          traces.push({
            name: s.name,
            x: pts.map((p) => p[0]),
            y: pts.map((p) => p[1]),
            type: idx % 3 === 2 && picked.length === 1 ? "bar" : "scatter",
            mode: "lines",
            line: { color, width: 2.2 },
            marker: { color },
            hovertemplate: `<b>${esc(s.name)}</b><br>%{x}: <b>%{y:,.2f}</b><extra></extra>`,
          });
        });
      } else {
        ["LKA", "WEOWORLD", "IND"].forEach((code, si) => {
          const ptsRaw = item.values[code];
          if (!ptsRaw) return;
          const color = PALETTE[si % PALETTE.length];
          const label = code === "WEOWORLD" ? "World" : code === "LKA" ? "Sri Lanka" : "India";
          const pts = sliceByActivePreset(ptsRaw);
          legendItems.push(
            `<span class="legend-item" title="${esc(label)}">` +
              `<i class="legend-dot" style="background:${color}"></i>` +
              `<span class="legend-text">${esc(label)}</span>` +
              `</span>`
          );
          traces.push({
            name: label,
            x: pts.map((p) => p[0]),
            y: pts.map((p) => p[1]),
            type: "scatter",
            mode: "lines",
            line: { color, width: 2.2 },
            hovertemplate: `<b>${esc(label)}</b><br>%{x}: <b>%{y:,.2f}</b><extra></extra>`,
          });
        });
      }

      if (legendEl) legendEl.innerHTML = legendItems.join("");

      const isMobile = window.innerWidth <= 600;
      window.Plotly.newPlot(
        containerId,
        traces,
        {
          margin: isMobile
            ? { l: 38, r: 8, t: 8, b: 32 }
            : { l: 46, r: 14, t: 10, b: 36 },
          height: isMobile ? 195 : 220,
          paper_bgcolor: "rgba(0,0,0,0)",
          plot_bgcolor: "rgba(0,0,0,0)",
          hovermode: "x unified",
          showlegend: false,
          xaxis: {
            type: "category",
            nticks: isMobile ? 5 : 6,
            tickangle: 0,
            automargin: true,
            tickfont: { size: isMobile ? 9.5 : 10, color: "#5b6675" },
            gridcolor: "#f1f5f9",
          },
          yaxis: {
            automargin: true,
            tickfont: { size: isMobile ? 9.5 : 10, color: "#5b6675" },
            gridcolor: "#e2e8f0",
          },
        },
        { responsive: true, displayModeBar: false }
      );
    });
  }

  function sliceByActivePreset(pts) {
    if (!pts || !pts.length || state.preset === "MAX" || state.preset === "CUSTOM") {
      return pts.slice(-120);
    }
    const years = parseInt(state.preset.replace("Y", ""), 10) || 10;
    const lastP = pts[pts.length - 1][0];
    const cutoff = String(parseInt(String(lastP).slice(0, 4), 10) - years) + String(lastP).slice(4);
    const filtered = pts.filter(([p]) => p >= cutoff);
    return filtered.length >= 2 ? filtered : pts.slice(-24);
  }

  function openInWorkbench(id) {
    onSelectDataset(id);
    $("workbench").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // =========================================================================
  // Instant Cross-Source Search
  // =========================================================================
  function setupSearch() {
    const input = $("search-input");
    const pop = $("search-pop");

    input.addEventListener("input", () => {
      const q = input.value.trim().toLowerCase();
      if (q.length < 2) {
        pop.classList.remove("open");
        return;
      }
      const results = [];
      (state.cbsl?.tables || []).forEach((t) => {
        const tm = t.title.toLowerCase().includes(q) || t.category.toLowerCase().includes(q);
        t.series.forEach((s) => {
          if (tm || s.name.toLowerCase().includes(q)) {
            results.push({
              group: "lk",
              badge: "Sri Lanka",
              datasetId: t.id,
              seriesId: s.id,
              freq: s.freq,
              title: s.name,
              sub: `${t.title} (${s.start}–${s.end})`,
            });
          }
        });
      });
      (state.imf?.indicators || []).forEach((ind) => {
        if (
          ind.title.toLowerCase().includes(q) ||
          ind.id.toLowerCase().includes(q) ||
          ind.category.toLowerCase().includes(q)
        ) {
          results.push({
            group: "wd",
            badge: "World",
            datasetId: ind.id,
            seriesId: null,
            freq: "A",
            title: ind.title,
            sub: `${ind.category} · ${ind.unit} (${ind.start}–${ind.end})`,
          });
        }
      });

      if (!results.length) {
        pop.innerHTML = `<div class="sp-item"><small>No matching indicators found.</small></div>`;
      } else {
        pop.innerHTML = results
          .slice(0, 25)
          .map(
            (r, i) =>
              `<div class="sp-item" data-idx="${i}">` +
              `<div><h6>${esc(r.title)}</h6><small>${esc(r.sub)}</small></div>` +
              `<span class="tag-badge">${esc(r.badge)}</span>` +
              `</div>`
          )
          .join("");
        pop.querySelectorAll(".sp-item[data-idx]").forEach((el) => {
          el.addEventListener("click", () => {
            const r = results[parseInt(el.getAttribute("data-idx"), 10)];
            pop.classList.remove("open");
            input.value = "";
            if (state.group !== r.group) {
              state.group = r.group;
              document.body.setAttribute("data-g", r.group);
            }
            state.category = "All";
            if (r.freq) state.freq = r.freq;
            renderCategoryBar();
            populateDatasetSelector(false);
            onSelectDataset(r.datasetId, r.seriesId ? [r.seriesId] : null);
          });
        });
      }
      pop.classList.add("open");
    });

    document.addEventListener("click", (e) => {
      if (!$("search-form").contains(e.target)) {
        pop.classList.remove("open");
      }
    });
  }

  // =========================================================================
  // Live Python Backend Sync (/api/refresh)
  // =========================================================================
  async function refreshBackend() {
    const btn = $("btn-refresh");
    const orig = btn.textContent;
    btn.textContent = "⟳ Syncing...";
    btn.disabled = true;
    try {
      const r = await fetch("/api/refresh", { method: "POST" });
      if (r.ok) {
        const [summary, cbsl, imf] = await Promise.all([
          fetchJsonWithFallback("/api/summary", "data/summary.json"),
          fetchJsonWithFallback("/api/cbsl", "data/cbsl_data.json"),
          fetchJsonWithFallback("/api/imf", "data/imf_data.json"),
        ]);
        state.summary = summary;
        state.cbsl = cbsl;
        state.imf = imf;
        refreshView(false);
        btn.textContent = "✓ Updated";
      } else {
        btn.textContent = "✓ Up to date";
      }
    } catch (_) {
      btn.textContent = "✓ Up to date";
    }
    setTimeout(() => {
      btn.textContent = orig;
      btn.disabled = false;
    }, 2500);
  }

  window.App = {
    setGroup,
    setCategory,
    onKpiClick,
    onSelectDataset,
    setFreq,
    toggleSeries,
    clearSeriesSelection,
    setPreset,
    onSelectRangeDropdowns,
    onSliderInput,
    setChartType,
    setTransform,
    toggleTable,
    downloadCSV,
    openInWorkbench,
    refreshBackend,
  };

  let _lastMobileState = window.innerWidth <= 600;
  window.addEventListener("resize", () => {
    const nowMobile = window.innerWidth <= 600;
    if (nowMobile !== _lastMobileState) {
      _lastMobileState = nowMobile;
      renderMainChart();
      renderGallery();
    }
  });

  window.addEventListener("DOMContentLoaded", init);
})();
