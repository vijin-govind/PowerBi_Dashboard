/* PBIX Canvas: a Figma-like editor for Power BI report layouts. */
(() => {
  "use strict";

  // ------------------------------------------------------------------
  // Constants
  // ------------------------------------------------------------------
  const GRID = 8;
  const CHART_COLORS = ["#118DFF", "#12239E", "#E66C37", "#6B007B", "#E044A7", "#744EC2", "#D9B300", "#D64550"];
  const TYPE_LABELS = {
    card: "Card", multiRowCard: "Multi-row card", kpi: "KPI", gauge: "Gauge",
    clusteredColumnChart: "Column chart", columnChart: "Column chart", stackedColumnChart: "Stacked column",
    hundredPercentStackedColumnChart: "100% stacked column", clusteredBarChart: "Bar chart", barChart: "Bar chart",
    stackedBarChart: "Stacked bar", hundredPercentStackedBarChart: "100% stacked bar", lineChart: "Line chart",
    areaChart: "Area chart", stackedAreaChart: "Stacked area", lineClusteredColumnComboChart: "Line & column",
    lineStackedColumnComboChart: "Line & stacked column", pieChart: "Pie chart", donutChart: "Donut chart",
    scatterChart: "Scatter chart", funnel: "Funnel", treemap: "Treemap", waterfallChart: "Waterfall",
    tableEx: "Table", pivotTable: "Matrix", slicer: "Slicer", textbox: "Text box", image: "Image",
    shape: "Shape", basicShape: "Shape", actionButton: "Button", group: "Group", map: "Map", filledMap: "Filled map",
  };
  // Roles used when creating new visuals (Power BI role names).
  const ROLES = {
    card: ["Values"],
    clusteredColumnChart: ["Category", "Y"],
    clusteredBarChart: ["Category", "Y"],
    lineChart: ["Category", "Y"],
    pieChart: ["Category", "Y"],
    tableEx: ["Values"],
    slicer: ["Values"],
    textbox: [],
  };
  const DEFAULT_SIZE = {
    card: [240, 120], clusteredColumnChart: [480, 300], clusteredBarChart: [480, 300], lineChart: [480, 300],
    pieChart: [360, 300], tableEx: [480, 280], slicer: [200, 260], textbox: [320, 64],
  };
  const CAT_ROLES = new Set(["Category", "Rows", "Axis", "Legend", "Series"]);

  // ------------------------------------------------------------------
  // State
  // ------------------------------------------------------------------
  const state = {
    session: null, filename: "", format: "", model: { tables: [] },
    pages: [], pageIdx: 0, selectedId: null, zoom: 1, snap: true,
    history: [], future: [], previewCache: new Map(),
  };
  const charts = new Map();
  const $ = (id) => document.getElementById(id);
  const page = () => state.pages[state.pageIdx];
  const selected = () => (page() ? page().visuals.find((v) => v.id === state.selectedId) : null);
  const uid = () => Array.from(crypto.getRandomValues(new Uint8Array(10)), (b) => b.toString(16).padStart(2, "0")).join("");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const snapV = (n) => (state.snap ? Math.round(n / GRID) * GRID : Math.round(n));

  function toast(msg, isError = false, ms = 3200) {
    const t = $("toast");
    t.textContent = msg;
    t.className = "toast" + (isError ? " error" : "");
    t.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => (t.hidden = true), ms);
  }

  // ------------------------------------------------------------------
  // History (undo / redo)
  // ------------------------------------------------------------------
  const snapshot = () => JSON.stringify({ pages: state.pages, pageIdx: state.pageIdx });
  function pushHistory(snap) {
    state.history.push(snap);
    if (state.history.length > 200) state.history.shift();
    state.future = [];
  }
  function commit(mutate, opts = {}) {
    const before = snapshot();
    mutate();
    if (snapshot() !== before) pushHistory(before);
    renderAll(opts);
  }
  function restore(snap) {
    const s = JSON.parse(snap);
    state.pages = s.pages;
    state.pageIdx = Math.min(s.pageIdx, state.pages.length - 1);
    if (!selected()) state.selectedId = null;
    renderAll();
  }
  function undo() {
    if (!state.history.length) return;
    state.future.push(snapshot());
    restore(state.history.pop());
  }
  function redo() {
    if (!state.future.length) return;
    state.history.push(snapshot());
    restore(state.future.pop());
  }

  // ------------------------------------------------------------------
  // Upload / export
  // ------------------------------------------------------------------
  async function upload(file) {
    if (!file) return;
    if (!/\.pbix$/i.test(file.name)) return toast("Please choose a .pbix file.", true);
    document.body.classList.add("busy");
    toast(`Reading ${file.name}…`, false, 60000);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await fetch("api/upload", { method: "POST", body: fd });
      const body = await r.json();
      if (!r.ok) throw new Error(body.detail || "Upload failed");
      if (state.session) fetch(`api/session/${state.session}`, { method: "DELETE" });
      Object.assign(state, {
        session: body.session, filename: body.filename, format: body.format, model: body.model,
        pages: body.report.pages, pageIdx: 0, selectedId: null, history: [], future: [], previewCache: new Map(),
      });
      state.modelError = body.modelError;
      if (!state.pages.length) state.pages.push(newPage("Page 1"));
      $("dropZone").hidden = true;
      $("pageCanvas").hidden = false;
      renderAll();
      zoomFit();
      toast(`Opened ${body.filename}: ${state.pages.length} page(s), ${body.format === "pbir" ? "PBIR" : "legacy"} report format.`);
    } catch (e) {
      toast(e.message, true, 6000);
    } finally {
      document.body.classList.remove("busy");
    }
  }

  async function exportPbix() {
    const btn = $("exportBtn");
    btn.disabled = true;
    btn.textContent = "Exporting…";
    try {
      const pages = state.pages.map((p) => ({
        id: p.isNew ? null : p.id, name: p.name, width: p.width, height: p.height,
        visuals: p.visuals.map(({ id, type, x, y, z, width, height, title, text, fields, isNew, duplicateOf }) =>
          ({ id, type, x, y, z, width, height, title, text, fields, isNew, duplicateOf })),
      }));
      const r = await fetch(`api/session/${state.session}/export`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pages }),
      });
      if (!r.ok) throw new Error((await r.json()).detail || "Export failed");
      const blob = await r.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = state.filename.replace(/\.pbix$/i, "") + "-edited.pbix";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      toast("Exported. Open it in Power BI Desktop. You may need to re-enter data source credentials on first refresh.", false, 6000);
    } catch (e) {
      toast(e.message, true, 6000);
    } finally {
      btn.disabled = false;
      btn.textContent = "Export .pbix";
    }
  }

  // ------------------------------------------------------------------
  // Rendering
  // ------------------------------------------------------------------
  function renderAll(opts = {}) {
    renderFileInfo();
    renderPages();
    if (!opts.keepFields) renderFields();
    renderCanvas();
    renderProps();
    $("undoBtn").disabled = !state.history.length;
    $("redoBtn").disabled = !state.future.length;
    const on = !!state.session;
    $("exportBtn").disabled = !on;
    $("addPage").disabled = !on;
    document.querySelectorAll(".tool").forEach((b) => (b.disabled = !on));
  }

  function renderFileInfo() {
    const el = $("fileInfo");
    if (!state.session) return (el.innerHTML = "");
    const dirty = state.history.length ? " ●" : "";
    el.innerHTML = `<span class="name" title="${esc(state.filename)}">${esc(state.filename)}${dirty}</span>
      <span class="badge">${state.format === "pbir" ? "PBIR" : "Legacy layout"}</span>`;
  }

  function renderPages() {
    const ul = $("pageList");
    ul.innerHTML = "";
    state.pages.forEach((p, i) => {
      const li = document.createElement("li");
      li.className = i === state.pageIdx ? "active" : "";
      li.innerHTML = `<span class="pname">${esc(p.name)}</span><span class="pactions">
        <button data-act="up" title="Move up">↑</button><button data-act="down" title="Move down">↓</button>
        <button data-act="del" title="Delete page">✕</button></span>`;
      li.addEventListener("click", (e) => {
        const act = e.target.dataset.act;
        if (act === "up" && i > 0) return commit(() => { swap(state.pages, i, i - 1); state.pageIdx = i - 1; });
        if (act === "down" && i < state.pages.length - 1) return commit(() => { swap(state.pages, i, i + 1); state.pageIdx = i + 1; });
        if (act === "del") {
          if (state.pages.length === 1) return toast("A report needs at least one page.", true);
          if (!confirm(`Delete page "${p.name}" and its ${p.visuals.length} visual(s)?`)) return;
          return commit(() => { state.pages.splice(i, 1); state.pageIdx = Math.max(0, Math.min(state.pageIdx, state.pages.length - 1)); state.selectedId = null; });
        }
        if (i !== state.pageIdx) { state.pageIdx = i; state.selectedId = null; renderAll({ keepFields: true }); zoomFit(); }
      });
      li.addEventListener("dblclick", () => renamePage(li, p));
      ul.appendChild(li);
    });
  }
  const swap = (a, i, j) => ([a[i], a[j]] = [a[j], a[i]]);

  function renamePage(li, p) {
    const span = li.querySelector(".pname");
    const input = document.createElement("input");
    input.value = p.name;
    span.replaceWith(input);
    input.focus();
    input.select();
    const done = (save) => {
      const v = input.value.trim();
      if (save && v && v !== p.name) commit(() => (p.name = v));
      else renderPages();
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") done(true); if (e.key === "Escape") done(false); });
    input.addEventListener("blur", () => done(true));
  }

  function newPage(name) {
    return { id: "new-" + uid(), isNew: true, name, width: 1280, height: 720, visuals: [] };
  }

  function renderFields() {
    const list = $("fieldList");
    const note = $("modelNote");
    list.innerHTML = "";
    note.className = "note";
    note.textContent = "";
    if (!state.session) return;
    if (state.modelError) {
      note.className = "note warn";
      note.textContent = "Data model could not be read (DirectQuery/live connection?). Layout editing still works.";
    } else if (state.model.tables.length) {
      note.textContent = "Drag a field onto the canvas or onto a new visual.";
    }
    for (const t of state.model.tables) {
      const node = document.createElement("div");
      node.className = "table-node";
      node.innerHTML = `<div class="tname"><span>▾</span>${esc(t.name)}</div><div class="fields"></div>`;
      node.querySelector(".tname").addEventListener("click", () => node.classList.toggle("collapsed"));
      const fields = node.querySelector(".fields");
      const items = [
        ...t.measures.map((m) => ({ kind: "measure", table: t.name, name: m.name, title: m.expression })),
        ...t.columns.map((c) => ({ kind: "column", table: t.name, name: c.name, dataType: c.dataType, title: c.dataType })),
      ];
      for (const f of items) {
        const el = document.createElement("div");
        el.className = "field " + f.kind;
        el.draggable = true;
        el.title = f.title || "";
        el.innerHTML = `<span class="ficon">${f.kind === "measure" ? "ƒx" : isNumeric(f.dataType) ? "Σ" : "Aa"}</span>${esc(f.name)}`;
        el.addEventListener("dragstart", (e) => e.dataTransfer.setData("application/x-pbi-field", JSON.stringify(f)));
        fields.appendChild(el);
      }
      list.appendChild(node);
    }
  }
  const isNumeric = (dt) => /int|float|double|decimal/i.test(dt || "");

  function renderCanvas() {
    charts.forEach((c) => c.dispose());
    charts.clear();
    const canvas = $("pageCanvas");
    canvas.innerHTML = "";
    const p = page();
    if (!p) return;
    canvas.style.width = p.width + "px";
    canvas.style.height = p.height + "px";
    canvas.style.transform = `scale(${state.zoom})`;
    canvas.classList.toggle("grid", state.snap);
    let sizer = $("sizer");
    if (!sizer) {
      sizer = document.createElement("div");
      sizer.id = "sizer";
      sizer.style.cssText = "position:absolute;left:0;top:0;pointer-events:none;";
      $("stage").appendChild(sizer);
    }
    sizer.style.width = p.width * state.zoom + 80 + "px";
    sizer.style.height = p.height * state.zoom + 80 + "px";
    $("zoomLabel").textContent = Math.round(state.zoom * 100) + "%";

    [...p.visuals].sort((a, b) => (a.z || 0) - (b.z || 0)).forEach((v) => canvas.appendChild(visualEl(v)));
  }

  function visualEl(v) {
    const el = document.createElement("div");
    el.className = "visual" + (v.type === "group" ? " group" : "") + (v.id === state.selectedId ? " selected" : "");
    el.dataset.id = v.id;
    placeEl(el, v);
    const showTitle = v.title && v.type !== "textbox" && v.type !== "group";
    el.innerHTML = `${showTitle ? `<div class="vtitle">${esc(v.title)}</div>` : ""}<div class="vbody"></div>
      ${v.isNew || v.duplicateOf ? `<span class="new-tag">${v.isNew ? "new" : "copy"}</span>` : ""}
      <i class="handle nw"></i><i class="handle ne"></i><i class="handle sw"></i><i class="handle se"></i>`;
    el.addEventListener("pointerdown", () => select(v.id));
    requestAnimationFrame(() => renderBody(v, el.querySelector(".vbody")));
    return el;
  }
  function placeEl(el, v) {
    Object.assign(el.style, { left: v.x + "px", top: v.y + "px", width: v.width + "px", height: v.height + "px" });
  }

  // ---------- visual bodies ----------
  async function getPreview(v) {
    const fields = (v.fields || []).filter((f) => ["column", "measure", "aggregation"].includes(f.kind));
    if (!fields.length || !state.session || state.modelError) return null;
    const key = JSON.stringify(fields);
    if (!state.previewCache.has(key)) {
      state.previewCache.set(key, fetch(`api/session/${state.session}/preview`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fields }),
      }).then((r) => r.json()).then((b) => b.data).catch(() => null));
    }
    return state.previewCache.get(key);
  }

  function sampleData(v) {
    const cats = (v.fields || []).filter((f) => CAT_ROLES.has(f.role));
    const vals = (v.fields || []).filter((f) => !CAT_ROLES.has(f.role) && f.kind !== "column");
    const seed = [...v.id].reduce((a, c) => a + c.charCodeAt(0), 0);
    const rnd = (i) => 30 + ((seed * (i + 7) * 9301 + 49297) % 233280) / 233280 * 70;
    const categories = ["A", "B", "C", "D", "E"].map((c) => (cats[0] ? `${cats[0].name} ${c}` : `Item ${c}`));
    const series = (vals.length ? vals : [{ name: "Value" }]).map((f, si) => ({ name: f.name, values: categories.map((_, i) => Math.round(rnd(i + si * 5))) }));
    return { categories, series, value: Math.round(rnd(1) * 123), name: vals[0]?.name || "Value", sample: true };
  }

  const fmt = (n) => {
    if (typeof n !== "number") return n ?? "";
    const a = Math.abs(n);
    if (a >= 1e9) return (n / 1e9).toFixed(2).replace(/\.?0+$/, "") + "bn";
    if (a >= 1e6) return (n / 1e6).toFixed(2).replace(/\.?0+$/, "") + "M";
    if (a >= 1e3) return (n / 1e3).toFixed(2).replace(/\.?0+$/, "") + "K";
    return Number.isInteger(n) ? String(n) : n.toFixed(2);
  };

  function chartKind(t) {
    if (/^(clustered|stacked|hundredPercentStacked)?ColumnChart$|^columnChart$/i.test(t) || t === "waterfallChart") return "column";
    if (/BarChart$/i.test(t)) return "bar";
    if (/^(line|area|stackedArea)Chart$/i.test(t) || /Combo/i.test(t)) return t.includes("rea") ? "area" : "line";
    if (t === "pieChart" || t === "donutChart") return "pie";
    if (t === "scatterChart") return "scatter";
    if (t === "funnel") return "funnel";
    if (t === "treemap") return "treemap";
    return null;
  }

  async function renderBody(v, body) {
    if (!body.isConnected) return;
    const t = v.type;
    if (t === "group") return;
    if (t === "textbox") {
      body.innerHTML = `<div class="textbox-body">${esc(v.text || "Text")}</div>`;
      return;
    }
    const kind = chartKind(t);
    const isCard = ["card", "multiRowCard", "kpi", "gauge"].includes(t);
    const isTable = ["tableEx", "pivotTable", "slicer"].includes(t);
    if (!kind && !isCard && !isTable) {
      body.innerHTML = `<div class="placeholder"><b>${esc(TYPE_LABELS[t] || t)}</b><span>Rendered by Power BI Desktop</span></div>`;
      return;
    }
    let data = await getPreview(v);
    if (!body.isConnected) return;
    const sample = !data;
    if (!data) data = sampleData(v);
    const badge = sample ? `<span class="sample">sample data</span>` : "";

    if (isCard) {
      const value = data.value ?? data.series?.[0]?.values?.reduce((a, b) => a + (b || 0), 0);
      body.innerHTML = `<div class="card-value"><div class="num">${esc(fmt(value))}</div><div class="lbl">${esc(data.name || v.fields?.[0]?.name || "")}</div></div>${badge}`;
      return;
    }
    if (isTable) {
      let columns, rows;
      if (data.rows) ({ columns, rows } = data);
      else {
        columns = [(v.fields || []).find((f) => CAT_ROLES.has(f.role))?.name || "Category", ...data.series.map((s) => s.name)];
        rows = data.categories.map((c, i) => [c, ...data.series.map((s) => s.values[i])]);
      }
      if (t === "slicer") {
        body.innerHTML = `<div class="slicer-list">${rows.slice(0, 30).map((r) => `<div>${esc(r[0])}</div>`).join("")}</div>${badge}`;
      } else {
        body.innerHTML = `<table class="mini-table"><thead><tr>${columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead>
          <tbody>${rows.slice(0, 40).map((r) => `<tr>${r.map((c) => `<td>${esc(fmt(c))}</td>`).join("")}</tr>`).join("")}</tbody></table>${badge}`;
      }
      return;
    }
    body.innerHTML = badge;
    const holder = document.createElement("div");
    holder.style.cssText = "position:absolute;inset:0;";
    body.prepend(holder);
    const chart = echarts.init(holder, null, { renderer: "canvas" });
    charts.get(v.id)?.dispose();
    charts.set(v.id, chart);
    chart.setOption(chartOption(kind, data));
  }

  function chartOption(kind, d) {
    const base = {
      animation: false, color: CHART_COLORS, textStyle: { fontFamily: "Segoe UI, sans-serif" },
      legend: d.series.length > 1 ? { top: 0, type: "scroll", textStyle: { fontSize: 10 } } : undefined,
      grid: { left: 8, right: 12, top: d.series.length > 1 ? 26 : 12, bottom: 8, containLabel: true },
      tooltip: { trigger: kind === "pie" ? "item" : "axis" },
    };
    const cat = { type: "category", data: d.categories, axisLabel: { fontSize: 10, hideOverlap: true } };
    const val = { type: "value", axisLabel: { fontSize: 10, formatter: fmt }, splitLine: { lineStyle: { color: "#eee" } } };
    if (kind === "pie" || kind === "funnel") {
      const s = d.series[0] || { values: [] };
      return { ...base, legend: undefined, series: [{ type: kind, radius: kind === "pie" ? ["0%", "70%"] : undefined, label: { fontSize: 10 },
        data: d.categories.map((c, i) => ({ name: String(c), value: s.values[i] })) }] };
    }
    if (kind === "treemap") {
      const s = d.series[0] || { values: [] };
      return { ...base, series: [{ type: "treemap", roam: false, nodeClick: false, breadcrumb: { show: false }, data: d.categories.map((c, i) => ({ name: String(c), value: s.values[i] })) }] };
    }
    if (kind === "scatter") {
      return { ...base, xAxis: val, yAxis: val, series: [{ type: "scatter", data: (d.series[0]?.values || []).map((y, i) => [d.series[1]?.values[i] ?? i, y]) }] };
    }
    const horizontal = kind === "bar";
    const type = kind === "column" || kind === "bar" ? "bar" : "line";
    return {
      ...base,
      xAxis: horizontal ? val : cat,
      yAxis: horizontal ? { ...cat, inverse: true } : val,
      series: d.series.map((s) => ({ name: s.name, type, data: s.values, areaStyle: kind === "area" ? {} : undefined, barMaxWidth: 48, symbolSize: 5 })),
    };
  }

  // ------------------------------------------------------------------
  // Properties panel
  // ------------------------------------------------------------------
  function renderProps() {
    const body = $("propsBody");
    if (!state.session) return;
    const v = selected();
    const p = page();
    if (!v) {
      const preset = `${p.width}x${p.height}`;
      body.innerHTML = `
        <div class="prop-group"><h4>Page</h4>
          <div class="prop-row"><label>Name</label><input id="pName" value="${esc(p.name)}"></div>
          <div class="prop-row"><label>Size</label><select id="pSize">
            ${[["1280x720", "16:9 (1280×720)"], ["960x720", "4:3 (960×720)"], ["816x1056", "Letter (816×1056)"], ["1920x1080", "Full HD (1920×1080)"]]
              .map(([k, l]) => `<option value="${k}" ${k === preset ? "selected" : ""}>${l}</option>`).join("")}
            ${["1280x720", "960x720", "816x1056", "1920x1080"].includes(preset) ? "" : `<option selected value="${preset}">Custom (${p.width}×${p.height})</option>`}
          </select></div>
          <div class="xywh"><div><span>W</span><input id="pW" type="number" min="100" value="${p.width}"></div><div><span>H</span><input id="pH" type="number" min="100" value="${p.height}"></div></div>
        </div>
        <div class="prop-group"><h4>This page</h4><p class="hint">${p.visuals.length} visual(s). Click a visual to edit it, or insert one from the toolbar.</p></div>
        <div class="prop-group"><h4>Shortcuts</h4><p class="hint">
          <span class="kbd">Del</span> delete · <span class="kbd">Ctrl+D</span> duplicate<br>
          <span class="kbd">Arrows</span> nudge (Shift = 10×)<br>
          <span class="kbd">Ctrl+Z</span> undo · <span class="kbd">Ctrl+Shift+Z</span> redo<br>
          <span class="kbd">Ctrl +/−/0</span> zoom · <span class="kbd">Esc</span> deselect</p></div>`;
      $("pName").addEventListener("change", (e) => e.target.value.trim() && commit(() => (p.name = e.target.value.trim())));
      $("pSize").addEventListener("change", (e) => { const [w, h] = e.target.value.split("x").map(Number); commit(() => Object.assign(p, { width: w, height: h })); zoomFit(); });
      $("pW").addEventListener("change", (e) => commit(() => (p.width = Math.max(100, +e.target.value || p.width))));
      $("pH").addEventListener("change", (e) => commit(() => (p.height = Math.max(100, +e.target.value || p.height))));
      return;
    }
    const editableFields = !!v.isNew;
    const roles = editableFields ? ROLES[v.type] || [] : [...new Set((v.fields || []).map((f) => f.role))];
    const rolesHtml = roles.length
      ? roles.map((r) => {
          const fs = (v.fields || []).map((f, i) => ({ f, i })).filter(({ f }) => f.role === r);
          return `<div class="role"><div class="rname">${esc(r)}</div>
            ${fs.map(({ f, i }) => `<div class="rfield"><span>${f.kind === "measure" ? "ƒx " : ""}${esc(fieldLabel(f))}</span>${editableFields ? `<button data-rm="${i}" title="Remove">✕</button>` : ""}</div>`).join("")}
            ${!fs.length ? `<div class="rempty">${editableFields ? "Drag a field onto the visual" : "—"}</div>` : ""}</div>`;
        }).join("")
      : `<p class="hint">No data fields.</p>`;
    body.innerHTML = `
      <div class="prop-group"><h4>Visual</h4>
        <div class="prop-row"><label>Type</label>${v.isNew && ROLES[v.type]
          ? `<select id="vType">${Object.keys(ROLES).map((t) => `<option value="${t}" ${t === v.type ? "selected" : ""}>${TYPE_LABELS[t]}</option>`).join("")}</select>`
          : `<input disabled value="${esc(TYPE_LABELS[v.type] || v.type)}">`}</div>
        ${v.type !== "textbox" ? `<div class="prop-row"><label>Title</label><input id="vTitle" value="${esc(v.title || "")}" placeholder="(no title)"></div>` : ""}
        ${v.type === "textbox" ? `<div class="prop-row"><label>Text</label><textarea id="vText" rows="3" ${v.isNew ? "" : "disabled title='Editing existing text boxes is not supported yet'"}>${esc(v.text || "")}</textarea></div>` : ""}
      </div>
      <div class="prop-group"><h4>Position & size</h4>
        <div class="xywh">
          ${["x", "y", "width", "height"].map((k) => `<div><span>${k[0].toUpperCase()}</span><input data-pos="${k}" type="number" value="${Math.round(v[k])}"></div>`).join("")}
        </div>
      </div>
      <div class="prop-group"><h4>Data ${editableFields ? "" : "<span class='muted'>(read-only)</span>"}</h4>${rolesHtml}
        ${!editableFields && v.fields?.length ? `<p class="hint">Field bindings of existing visuals are preserved as-is on export.</p>` : ""}</div>
      <div class="prop-group"><h4>Arrange</h4>
        <div class="btn-row">
          <button class="btn" data-z="front">Bring to front</button><button class="btn" data-z="back">Send to back</button>
          <button class="btn" id="vDup">Duplicate</button><button class="btn danger" id="vDel">Delete</button>
        </div>
      </div>`;
    $("vTitle")?.addEventListener("change", (e) => commit(() => (v.title = e.target.value)));
    $("vText")?.addEventListener("change", (e) => commit(() => (v.text = e.target.value)));
    $("vType")?.addEventListener("change", (e) => commit(() => {
      v.type = e.target.value;
      const allowed = new Set(ROLES[v.type]);
      v.fields = (v.fields || []).filter((f) => allowed.has(f.role));
    }));
    body.querySelectorAll("[data-pos]").forEach((inp) => inp.addEventListener("change", () => {
      const k = inp.dataset.pos;
      const min = k === "width" || k === "height" ? 20 : -10000;
      commit(() => (v[k] = Math.max(min, Math.round(+inp.value || 0))));
    }));
    body.querySelectorAll("[data-rm]").forEach((b) => b.addEventListener("click", () => commit(() => v.fields.splice(+b.dataset.rm, 1))));
    body.querySelectorAll("[data-z]").forEach((b) => b.addEventListener("click", () => commit(() => {
      const zs = page().visuals.map((o) => o.z || 0);
      v.z = b.dataset.z === "front" ? Math.max(...zs) + 1000 : Math.min(...zs) - 1000;
    })));
    $("vDup").addEventListener("click", duplicateSelected);
    $("vDel").addEventListener("click", deleteSelected);
  }
  const fieldLabel = (f) => (f.kind === "aggregation" ? `${f.agg === "average" ? "Average" : f.agg[0].toUpperCase() + f.agg.slice(1)} of ${f.name}` : f.name);

  // ------------------------------------------------------------------
  // Actions
  // ------------------------------------------------------------------
  function select(id) {
    if (state.selectedId === id) return;
    state.selectedId = id;
    document.querySelectorAll(".visual").forEach((el) => el.classList.toggle("selected", el.dataset.id === id));
    renderProps();
  }

  function nextZ() {
    return Math.max(0, ...page().visuals.map((v) => v.z || 0)) + 1000;
  }

  function addVisual(type, at, fields = []) {
    const [w, h] = DEFAULT_SIZE[type] || [300, 200];
    const p = page();
    const x = at ? at.x - w / 2 : (p.width - w) / 2;
    const y = at ? at.y - h / 2 : (p.height - h) / 2;
    const v = {
      id: uid(), isNew: true, type, x: snapV(Math.max(0, Math.min(x, p.width - w))), y: snapV(Math.max(0, Math.min(y, p.height - h))),
      z: nextZ(), width: w, height: h, title: type === "textbox" ? null : "", text: type === "textbox" ? "Double-check me in Desktop" : null, fields,
    };
    commit(() => { p.visuals.push(v); state.selectedId = v.id; });
    return v;
  }

  function duplicateSelected() {
    const v = selected();
    if (!v) return;
    const copy = JSON.parse(JSON.stringify(v));
    copy.id = uid();
    copy.x += 16;
    copy.y += 16;
    copy.z = nextZ();
    if (!v.isNew) copy.duplicateOf = v.duplicateOf || v.id;
    commit(() => { page().visuals.push(copy); state.selectedId = copy.id; });
  }

  function deleteSelected() {
    const v = selected();
    if (!v) return;
    commit(() => {
      page().visuals = page().visuals.filter((o) => o !== v);
      state.selectedId = null;
    });
  }

  function bindField(v, f) {
    if (!v.isNew) return toast("Field bindings of existing visuals are read-only in this version. Insert a new visual instead.", true);
    const roles = ROLES[v.type] || [];
    if (!roles.length) return toast("This visual has no data fields.", true);
    const has = (r) => (v.fields || []).some((x) => x.role === r);
    let field;
    if (f.kind === "measure") {
      if (v.type === "slicer") return toast("Slicers need a column, not a measure.", true);
      field = { role: roles.includes("Y") ? "Y" : "Values", kind: "measure", table: f.table, name: f.name };
    } else if (roles.includes("Category") && !has("Category")) {
      field = { role: "Category", kind: "column", table: f.table, name: f.name };
    } else if (v.type === "tableEx" || v.type === "slicer") {
      field = { role: "Values", kind: "column", table: f.table, name: f.name };
    } else {
      field = { role: roles.includes("Y") ? "Y" : "Values", kind: "aggregation", agg: isNumeric(f.dataType) ? "sum" : "count", table: f.table, name: f.name };
    }
    commit(() => {
      v.fields = v.fields || [];
      if (v.type === "slicer" || v.type === "card" || (field.role === "Category")) v.fields = v.fields.filter((x) => x.role !== field.role);
      v.fields.push(field);
    });
  }

  function canvasPoint(e) {
    const r = $("pageCanvas").getBoundingClientRect();
    return { x: (e.clientX - r.left) / state.zoom, y: (e.clientY - r.top) / state.zoom };
  }

  function setZoom(z) {
    state.zoom = Math.min(4, Math.max(0.1, z));
    renderCanvas();
  }
  function zoomFit() {
    const p = page();
    if (!p) return;
    const st = $("stage");
    setZoom(Math.min((st.clientWidth - 80) / p.width, (st.clientHeight - 80) / p.height, 2));
  }

  // ------------------------------------------------------------------
  // Drag & resize (interact.js)
  // ------------------------------------------------------------------
  function setupInteract() {
    let before = null;
    const start = (e) => {
      const v = page().visuals.find((o) => o.id === e.target.dataset.id);
      if (!v) return;
      select(v.id);
      before = snapshot();
      e.target._raw = { x: v.x, y: v.y, w: v.width, h: v.height };
    };
    const end = (e) => {
      if (before && before !== snapshot()) pushHistory(before);
      before = null;
      $("undoBtn").disabled = !state.history.length;
      renderFileInfo();
      renderProps();
      charts.get(e.target.dataset.id)?.resize();
    };
    interact(".visual")
      .draggable({
        listeners: {
          start,
          move(e) {
            const v = page().visuals.find((o) => o.id === e.target.dataset.id);
            const raw = e.target._raw;
            if (!v || !raw) return;
            raw.x += e.dx / state.zoom;
            raw.y += e.dy / state.zoom;
            v.x = snapV(raw.x);
            v.y = snapV(raw.y);
            placeEl(e.target, v);
          },
          end,
        },
      })
      .resizable({
        edges: { left: true, right: true, top: true, bottom: true },
        margin: 6,
        listeners: {
          start,
          move(e) {
            const v = page().visuals.find((o) => o.id === e.target.dataset.id);
            const raw = e.target._raw;
            if (!v || !raw) return;
            raw.x += e.deltaRect.left / state.zoom;
            raw.y += e.deltaRect.top / state.zoom;
            raw.w += e.deltaRect.width / state.zoom;
            raw.h += e.deltaRect.height / state.zoom;
            const nx = snapV(raw.x), ny = snapV(raw.y);
            const right = e.edges.left ? v.x + v.width : snapV(raw.x + raw.w);
            const bottom = e.edges.top ? v.y + v.height : snapV(raw.y + raw.h);
            if (e.edges.left) v.x = Math.min(nx, right - 20);
            if (e.edges.top) v.y = Math.min(ny, bottom - 20);
            v.width = Math.max(20, right - v.x);
            v.height = Math.max(20, bottom - v.y);
            placeEl(e.target, v);
            charts.get(v.id)?.resize();
          },
          end,
        },
      });
  }

  // ------------------------------------------------------------------
  // Wiring
  // ------------------------------------------------------------------
  function wire() {
    $("fileInput").addEventListener("change", (e) => { upload(e.target.files[0]); e.target.value = ""; });
    $("exportBtn").addEventListener("click", exportPbix);
    $("undoBtn").addEventListener("click", undo);
    $("redoBtn").addEventListener("click", redo);
    $("zoomIn").addEventListener("click", () => setZoom(state.zoom * 1.2));
    $("zoomOut").addEventListener("click", () => setZoom(state.zoom / 1.2));
    $("zoomFit").addEventListener("click", zoomFit);
    $("snapToggle").addEventListener("change", (e) => { state.snap = e.target.checked; renderCanvas(); });
    $("addPage").addEventListener("click", () => {
      commit(() => { state.pages.push(newPage(`Page ${state.pages.length + 1}`)); state.pageIdx = state.pages.length - 1; state.selectedId = null; });
      zoomFit();
    });
    document.querySelectorAll(".tool").forEach((b) => b.addEventListener("click", () => addVisual(b.dataset.type)));
    window.addEventListener("resize", () => state.session && zoomFit());

    const stage = $("stage");
    stage.addEventListener("pointerdown", (e) => {
      if (state.session && !e.target.closest(".visual") && state.selectedId) { state.selectedId = null; renderCanvas(); renderProps(); }
    });
    stage.addEventListener("dragover", (e) => {
      e.preventDefault();
      if (!state.session) return $("dropZone").classList.add("over");
      document.querySelectorAll(".visual.drop-target").forEach((el) => el.classList.remove("drop-target"));
      e.target.closest?.(".visual")?.classList.add("drop-target");
    });
    stage.addEventListener("dragleave", () => $("dropZone").classList.remove("over"));
    stage.addEventListener("drop", (e) => {
      e.preventDefault();
      $("dropZone").classList.remove("over");
      document.querySelectorAll(".visual.drop-target").forEach((el) => el.classList.remove("drop-target"));
      const file = e.dataTransfer.files?.[0];
      if (file) return upload(file);
      const raw = e.dataTransfer.getData("application/x-pbi-field");
      if (!raw || !state.session) return;
      const f = JSON.parse(raw);
      const target = e.target.closest?.(".visual");
      if (target) {
        const v = page().visuals.find((o) => o.id === target.dataset.id);
        select(v.id);
        return bindField(v, f);
      }
      const at = canvasPoint(e);
      if (f.kind === "measure") addVisual("card", at, [{ role: "Values", kind: "measure", table: f.table, name: f.name }]);
      else if (isNumeric(f.dataType)) addVisual("card", at, [{ role: "Values", kind: "aggregation", agg: "sum", table: f.table, name: f.name }]);
      else addVisual("tableEx", at, [{ role: "Values", kind: "column", table: f.table, name: f.name }]);
    });

    document.addEventListener("keydown", (e) => {
      if (!state.session) return;
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName);
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "z" && !typing) { e.preventDefault(); return e.shiftKey ? redo() : undo(); }
      if (mod && e.key.toLowerCase() === "y" && !typing) { e.preventDefault(); return redo(); }
      if (mod && (e.key === "=" || e.key === "+")) { e.preventDefault(); return setZoom(state.zoom * 1.2); }
      if (mod && e.key === "-") { e.preventDefault(); return setZoom(state.zoom / 1.2); }
      if (mod && e.key === "0") { e.preventDefault(); return zoomFit(); }
      if (typing) return;
      const v = selected();
      if (mod && e.key.toLowerCase() === "d") { e.preventDefault(); return duplicateSelected(); }
      if (e.key === "Escape") { state.selectedId = null; renderCanvas(); return renderProps(); }
      if (!v) return;
      if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); return deleteSelected(); }
      const step = (state.snap ? GRID : 1) * (e.shiftKey ? 10 : 1);
      const d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
      if (d) { e.preventDefault(); commit(() => { v.x += d[0]; v.y += d[1]; }, { keepFields: true }); }
    });
    window.addEventListener("beforeunload", (e) => { if (state.history.length) e.preventDefault(); });
  }

  wire();
  setupInteract();
})();
