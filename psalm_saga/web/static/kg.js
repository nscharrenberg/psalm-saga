/* Story knowledge-graph explorer (Cytoscape.js).
   mountKG(container, {runId, which, against}) renders the graph served by
   /api/runs/<id>/graph?which=<which> with filters, search, chapter range, layouts,
   a details panel and exports. which = "compare" renders the source graph aligned with the
   synthetic one (against = "design" | "text"), with a diff filter and a diff summary. */
(function () {
  const NODE_TYPES = [
    ["character", "Characters"], ["place", "Places"], ["object", "Objects"], ["organisation", "Organisations"],
    ["other", "Other entities"], ["scene", "Scenes"], ["event", "Events"], ["chapter", "Chapters"],
  ];
  const EDGE_TYPES = [
    ["relation:social", "Social relations"], ["relation:world", "World relations"], ["co_occurs", "Co-occurrence"],
    ["appears_in", "Appears in scene"], ["set_in", "Scene set in"], ["happens_at", "Event at place"],
    ["involves", "Event involves"], ["causes", "Causes"], ["in_chapter", "In chapter"], ["next", "Sequence"],
  ];
  const DEFAULT_NODES = new Set(["character", "place", "object", "organisation", "other"]);
  const DEFAULT_EDGES = new Set(["relation:social", "relation:world", "co_occurs", "set_in", "happens_at", "involves", "causes"]);
  const EDGES_FOR = { scene: ["appears_in", "set_in"], event: ["involves", "causes", "happens_at"], chapter: ["in_chapter", "next"] };
  const SHAPES = { character: "ellipse", place: "round-pentagon", object: "round-diamond", organisation: "round-hexagon",
    other: "ellipse", scene: "round-rectangle", event: "round-triangle", chapter: "round-rectangle" };
  const LANES = ["chapter", "scene", "event", "character", "place", "object", "organisation", "other"];
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const ekey = (e) => e.type + (e.group ? ":" + e.group : "");

  function palette() {
    const p = {};
    for (const [t] of NODE_TYPES) p[t] = css("--k-" + t) || "#888";
    return p;
  }

  const STATUS = [["kept", "Kept"], ["changed", "Changed"], ["source_only", "Only in source"], ["synthetic_only", "Only in synthetic"]];

  function style(colors) {
    const ink = css("--ink"), muted = css("--muted"), line = css("--line"), bg = css("--panel"), accent = css("--accent"), warm = css("--warm");
    const bad = css("--bad") || "#c0392b", ok = css("--ok") || "#2e7d32";
    return [
      { selector: "node", style: {
        "background-color": (n) => colors[n.data("type")], shape: (n) => SHAPES[n.data("type")] || "ellipse",
        width: "data(size)", height: "data(size)", label: "data(label)", color: ink, "font-size": 10,
        "font-family": "Inter, system-ui, sans-serif", "text-valign": "bottom", "text-margin-y": 3,
        "text-wrap": "ellipsis", "text-max-width": 120, "min-zoomed-font-size": 7,
        "border-width": 1, "border-color": bg, "text-background-color": bg, "text-background-opacity": 0.75,
        "text-background-padding": 1, "text-background-shape": "round-rectangle" } },
      { selector: "node[type='scene'], node[type='event']", style: { "text-opacity": 0, "font-size": 9 } },
      { selector: "node.hl, node:selected, node.match", style: { "text-opacity": 1 } },
      { selector: "node:selected", style: { "border-width": 3, "border-color": ink } },
      { selector: "node.match", style: { "border-width": 3, "border-color": warm } },
      { selector: "edge", style: {
        width: 1.2, "line-color": line, "curve-style": "bezier", opacity: 0.9,
        "font-size": 8, color: muted, "text-rotation": "autorotate", "min-zoomed-font-size": 9,
        "text-background-color": bg, "text-background-opacity": 1, "text-background-padding": 1 } },
      { selector: "edge[type='relation']", style: { label: "data(label)", "line-color": muted, width: 1.5,
        "target-arrow-shape": "triangle", "target-arrow-color": muted, "arrow-scale": 0.7 } },
      { selector: "edge[type='co_occurs']", style: { "line-color": accent, opacity: 0.35, width: "mapData(weight, 1, 12, 1, 7)" } },
      { selector: "edge[type='causes']", style: { "line-color": warm, "target-arrow-shape": "triangle", "target-arrow-color": warm, width: 1.6 } },
      { selector: "edge[?inferred]", style: { "line-style": "dashed" } },
      { selector: "edge[type='set_in'], edge[type='happens_at']", style: { "line-color": colors.place, opacity: 0.7 } },
      { selector: "edge[type='involves'], edge[type='appears_in']", style: { "line-color": colors.character, opacity: 0.45 } },
      { selector: "edge[type='next']", style: { "target-arrow-shape": "triangle", "target-arrow-color": line, "arrow-scale": 0.6 } },
      { selector: "edge.hl, edge:selected", style: { opacity: 1, width: 2.5, "text-opacity": 1, "min-zoomed-font-size": 0 } },
      { selector: "node[status='kept']", style: { opacity: 0.55 } },
      { selector: "node[status='changed']", style: { "border-width": 3, "border-color": warm } },
      { selector: "node[status='source_only']", style: { "background-opacity": 0.25, "border-width": 2.5, "border-style": "dashed", "border-color": bad } },
      { selector: "node[status='synthetic_only']", style: { "border-width": 3, "border-color": ok, "border-style": "double" } },
      { selector: "edge[status='kept']", style: { opacity: 0.3 } },
      { selector: "edge[status='changed']", style: { "line-color": warm, "target-arrow-color": warm, opacity: 1, width: 2 } },
      { selector: "edge[status='source_only']", style: { "line-color": bad, "target-arrow-color": bad, "line-style": "dashed", opacity: 0.9, width: 1.8 } },
      { selector: "edge[status='synthetic_only']", style: { "line-color": ok, "target-arrow-color": ok, opacity: 0.9, width: 1.8 } },
      { selector: ".faded", style: { opacity: 0.1, "text-opacity": 0 } },
      { selector: ".hidden", style: { display: "none" } },
    ];
  }

  function snippet(d, len = 70) {
    const x = d.details || {}, t = x.summary || x.description || "";
    if (d.type !== "scene" && d.type !== "event") return d.label;
    const num = d.id.slice(1);
    return `${num} · ${t.length > len ? t.slice(0, len - 1) + "…" : t}`;
  }

  function icon(type, color) {
    const p = { ellipse: "<circle cx='6' cy='6' r='5'/>", "round-pentagon": "<polygon points='6,1 11,5 9,11 3,11 1,5'/>",
      "round-diamond": "<polygon points='6,0.5 11.5,6 6,11.5 0.5,6'/>", "round-hexagon": "<polygon points='3,1 9,1 11.5,6 9,11 3,11 0.5,6'/>",
      "round-rectangle": "<rect x='0.5' y='2.5' width='11' height='7' rx='2'/>", "round-triangle": "<polygon points='6,1 11.5,11 0.5,11'/>" }[SHAPES[type]];
    return `<svg width="12" height="12" viewBox="0 0 12 12" style="fill:${color};vertical-align:-1px">${p}</svg>`;
  }

  function sizeOf(n, maxW) {
    if (n.type === "chapter") return 26;
    if (n.type === "scene") return 15;
    if (n.type === "event") return 14;
    return 14 + 30 * Math.sqrt((n.weight || 1) / maxW);
  }

  window.mountKG = async function (root, opts) {
    const { runId, which } = opts;
    const q = `which=${which}${which === "compare" ? "&against=" + (opts.against || "design") : ""}`;
    const cmp = which === "compare";
    root.innerHTML = `<div class="kg-empty muted">Loading the knowledge graph…</div>`;
    let g;
    try {
      const r = await fetch(`/api/runs/${runId}/graph?${q}`);
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      g = await r.json();
    } catch (e) {
      root.innerHTML = `<div class="kg-empty muted">No knowledge graph yet: ${esc(e.message)}</div>`;
      return;
    }
    if (!window.cytoscape) { root.innerHTML = `<div class="kg-empty muted">Graph library failed to load.</div>`; return; }

    const chapters = g.chapters.length ? g.chapters : [1];
    const cmin = Math.min(...chapters), cmax = Math.max(...chapters);
    const maxCo = Math.max(1, ...g.edges.filter((e) => e.type === "co_occurs").map((e) => e.weight));
    const st = { nodes: new Set(DEFAULT_NODES), edges: new Set(DEFAULT_EDGES), from: cmin, to: cmax, minCo: 1,
      focus: null, isolated: false, layout: "force", status: new Set(STATUS.map(([s]) => s)) };
    const scount = {};
    if (cmp) { for (const n of g.nodes) scount[n.status] = (scount[n.status] || 0) + 1; for (const e of g.edges) scount[e.status] = (scount[e.status] || 0) + 1; }
    const countOf = (t) => g.counts[t] || 0, ecountOf = (t) => g.edge_counts[t] || 0;

    root.innerHTML = `
      <div class="kg-bar">
        <div class="kg-row"><span class="kg-lbl">Show</span>${NODE_TYPES.filter(([t]) => countOf(t)).map(([t, l]) =>
          `<button class="kg-chip" data-n="${t}"><i style="background:var(--k-${t})"></i>${l} <span>${countOf(t)}</span></button>`).join("")}</div>
        <div class="kg-row"><span class="kg-lbl">Links</span>${EDGE_TYPES.filter(([t]) => ecountOf(t)).map(([t, l]) =>
          `<button class="kg-chip" data-e="${t}">${l} <span>${ecountOf(t)}</span></button>`).join("")}</div>
        ${cmp ? `<div class="kg-row"><span class="kg-lbl">Diff</span>
          <button class="small kg-diff-all">Everything</button><button class="small kg-diff-chg">Changes only</button>
          ${STATUS.map(([s, l]) => `<button class="kg-chip kg-st-${s}" data-s="${s}"><i></i>${l} <span>${scount[s] || 0}</span></button>`).join("")}</div>` : ""}
        <div class="kg-row">
          <span class="kg-lbl">Chapters</span>
          <input type="range" class="kg-from" min="${cmin}" max="${cmax}" value="${cmin}">
          <input type="range" class="kg-to" min="${cmin}" max="${cmax}" value="${cmax}">
          <span class="kg-range mono"></span>
          ${maxCo > 1 ? `<span class="kg-lbl">Min. shared scenes</span><input type="range" class="kg-co" min="1" max="${maxCo}" value="1"><span class="kg-co-v mono">1</span>` : ""}
          <label class="kg-check"><input type="checkbox" class="kg-iso"> hide unconnected</label>
        </div>
        <div class="kg-row">
          <input class="kg-search" placeholder="Search names, aliases, descriptions…">
          <select class="kg-layout"><option value="force">Force layout</option><option value="timeline">Timeline (by chapter)</option>
            <option value="concentric">Concentric (by importance)</option><option value="grid">Grid</option></select>
          <button class="small kg-fit">Fit</button><button class="small kg-all" style="display:none">Show all</button>
          <span class="grow"></span>
          <button class="small kg-png">PNG</button>
          <a class="small-link" href="/api/runs/${runId}/graph?${q}&format=graphml"><button class="small">GraphML</button></a>
          <button class="small kg-json">JSON</button>
        </div>
      </div>
      <div class="kg-main"><div class="kg-canvas"></div><aside class="kg-side"></aside></div>
      <div class="kg-note muted">${NODE_TYPES.filter(([t]) => countOf(t)).map(([t, l]) => `${icon(t, css("--k-" + t))} ${l.toLowerCase()}`).join(" · ")} · node size = mentions · dashed cause links are inferred from the cause text${cmp ? " · diff: faded = kept, orange = changed, red dashed = only in the source, green = only in the synthetic graph" : ""}</div>
      <div class="kg-tip"></div>`;

    const $ = (s) => root.querySelector(s);
    const colors = palette();
    const maxW = Math.max(1, ...g.nodes.filter((n) => !["scene", "event", "chapter"].includes(n.type)).map((n) => n.weight));
    const byId = Object.fromEntries(g.nodes.map((n) => [n.id, n]));
    const cy = cytoscape({
      container: $(".kg-canvas"),
      elements: [
        ...g.nodes.map((n) => ({ group: "nodes", data: { ...n, size: sizeOf(n, maxW) } })),
        ...g.edges.map((e) => ({ group: "edges", data: { ...e, key: ekey(e) } })),
      ],
      style: style(colors), wheelSensitivity: 0.25, minZoom: 0.05, maxZoom: 4,
    });
    const placed = new Set();

    const overlap = (chs) => !chs || !chs.length || chs.some((c) => c >= st.from && c <= st.to);
    function apply(relayout) {
      const focusSet = st.focus ? new Set(cy.getElementById(st.focus).closedNeighborhood().nodes().map((n) => n.id())) : null;
      cy.batch(() => {
        cy.nodes().forEach((n) => {
          const d = n.data();
          const vis = st.nodes.has(d.type) && overlap(d.chapters) && (!focusSet || focusSet.has(d.id));
          n.toggleClass("hidden", !vis);
        });
        const statusOk = (e) => !cmp || st.status.has(e.data("status"));
        // Styles are not recomputed inside a batch, so test the class rather than ":visible".
        const shown = (e) => !e.hasClass("hidden") && !e.source().hasClass("hidden") && !e.target().hasClass("hidden");
        cy.edges().forEach((e) => {
          const d = e.data();
          const vis = st.edges.has(d.key) && statusOk(e) && !e.source().hasClass("hidden") && !e.target().hasClass("hidden") &&
            overlap(d.chapters) && (d.type !== "co_occurs" || d.weight >= st.minCo);
          e.toggleClass("hidden", !vis);
        });
        if (cmp && !st.status.has("kept")) {  // kept nodes stay only as anchors of a visible change
          cy.nodes().forEach((n) => { if (n.data("status") === "kept" && !n.connectedEdges().some(shown)) n.addClass("hidden"); });
        }
        if (cmp) cy.nodes().forEach((n) => { if (n.data("status") !== "kept" && !st.status.has(n.data("status"))) n.addClass("hidden"); });
        if (st.isolated) cy.nodes().forEach((n) => { if (!n.hasClass("hidden") && n.id() !== st.focus && !n.connectedEdges().some(shown)) n.addClass("hidden"); });
      });
      $(".kg-range").textContent = st.from === st.to ? `chapter ${st.from}` : `${st.from}–${st.to}`;
      root.querySelectorAll("[data-n]").forEach((b) => b.classList.toggle("on", st.nodes.has(b.dataset.n)));
      root.querySelectorAll("[data-e]").forEach((b) => b.classList.toggle("on", st.edges.has(b.dataset.e)));
      root.querySelectorAll("[data-s]").forEach((b) => b.classList.toggle("on", st.status.has(b.dataset.s)));
      $(".kg-all").style.display = st.focus ? "" : "none";
      const unplaced = cy.nodes(":visible").some((n) => !placed.has(n.id()));
      if (relayout || unplaced) layout();
    }

    function layout() {
      const els = cy.elements(":visible");
      els.nodes().forEach((n) => placed.add(n.id()));
      if (st.layout === "timeline") {
        const vis = els.nodes(), story = new Set(["chapter", "scene", "event"]);
        const perCh = {};  // widest lane per chapter decides the column width
        vis.forEach((n) => { const d = n.data(); if (story.has(d.type)) { const c = d.chapters[0], k = c + ":" + d.type; perCh[k] = (perCh[k] || 0) + 1; } });
        const colW = {}; let x0 = 0; const colX = {};
        for (const c of chapters) {
          colW[c] = Math.max(1, ...["scene", "event"].map((t) => perCh[c + ":" + t] || 0)) * 58 + 50;
          colX[c] = x0; x0 += colW[c];
        }
        const width = Math.max(x0, 600), seen = {};
        vis.forEach((n) => {
          const d = n.data(), lane = LANES.indexOf(d.type);
          if (story.has(d.type)) {
            const c = d.chapters[0], k = c + ":" + d.type; seen[k] = (seen[k] || 0) + 1;
            const x = d.type === "chapter" ? colX[c] + colW[c] / 2 - 25 : colX[c] + (seen[k] - 1) * 58;
            n.position({ x, y: lane * 130 });
          }
        });
        for (const t of LANES.filter((t) => !story.has(t))) {
          const lane = LANES.indexOf(t);
          const ents = vis.filter((n) => n.data("type") === t).sort((a, b) => {
            const m = (n) => { const c = n.data("chapters"); return c && c.length ? c.reduce((x, y) => x + y, 0) / c.length : cmin; };
            return m(a) - m(b) || b.data("weight") - a.data("weight");
          });
          const step = width / Math.max(ents.length, 1);
          ents.forEach((n, i) => n.position({ x: step * (i + 0.5), y: lane * 130 + (i % 2) * 34 }));
        }
        cy.fit(els, 30);
        return;
      }
      const conf = st.layout === "concentric"
        ? { name: "concentric", concentric: (n) => (n.data("weight") || 1) + n.degree() * 2, levelWidth: () => 6, minNodeSpacing: 18, animate: false }
        : st.layout === "grid" ? { name: "grid", avoidOverlap: true, animate: false }
        : { name: "cose", animate: false, randomize: true, nodeRepulsion: () => 12000, idealEdgeLength: () => 90,
            edgeElasticity: () => 80, nodeOverlap: 12, componentSpacing: 80, numIter: 1500 };
      els.layout({ ...conf, fit: true, padding: 30 }).run();
    }

    // ---- details panel
    const side = $(".kg-side");
    const typeLabel = Object.fromEntries([...NODE_TYPES.map(([t, l]) => [t, l.replace(/s$/, "")]), ...EDGE_TYPES]);
    function row(k, v) { return v ? `<div class="kg-kv"><span>${k}</span><div>${esc(v)}</div></div>` : ""; }
    function showNode(n) {
      const d = n.data(), x = d.details || {};
      const groups = {};
      n.connectedEdges().forEach((e) => {
        const out = e.source().id() === d.id, other = out ? e.target() : e.source(), t = e.data("type");
        const DIR = { causes: ["Leads to", "Caused by"], next: ["Next", "Previous"] };
        const k = t === "relation" ? (out ? e.data("label") : `← ${e.data("label")}`)
          : DIR[t] ? DIR[t][out ? 0 : 1] : typeLabel[e.data("key")] || t;
        (groups[k] = groups[k] || []).push({ id: other.id(), label: snippet(other.data(), 60), type: other.data("type"), hidden: other.hasClass("hidden") || e.hasClass("hidden") });
      });
      side.innerHTML = `
        <div class="kg-type"><i style="background:var(--k-${d.type})"></i>${esc(typeLabel[d.type] || d.type)}${d.type === "scene" || d.type === "event" ? " " + esc(d.id.slice(1)) : ""}</div>
        <h3>${esc(d.type === "scene" || d.type === "event" ? (x.summary || x.description || d.label) : d.label)}</h3>
        ${cmp ? `<div class="kg-diffnote kg-st-${d.status}"><i></i><b>${esc((STATUS.find(([s]) => s === d.status) || [, d.status])[1])}</b>${d.diff ? " · " + esc(d.diff) : ""}</div>` : ""}
        ${x.counterpart ? `<div class="muted kg-cp">${which === "synthetic" ? "Was" : "Becomes"} <b>${esc(x.counterpart)}</b> ${which === "synthetic" ? "in the source" : "in the synthetic story"}</div>` : ""}
        ${x.matched_by ? `<div class="muted kg-cp">Matched by ${esc(x.matched_by)}</div>` : ""}
        ${x.checked ? `<div class="muted kg-cp">Not found by the analysis, but a check of the synthetic chapter says <b>${esc(x.checked.realised)}</b>: “${esc(x.checked.evidence || "")}”</div>` : ""}
        ${row("Aliases", (x.aliases || []).join(", "))}${row("Role", x.role)}${d.type === "event" ? "" : row("Description", x.description)}
        ${d.type === "scene" ? "" : row("Summary", x.summary)}${row("Setting", x.setting)}${row("Location", x.location)}${row("Purpose", x.purpose)}
        ${row("Point of view", x.pov)}${row("Caused by", x.caused_by)}${row("Mentions", x.mentions)}
        ${x.synthetic ? row("In the synthetic graph", x.synthetic.summary || x.synthetic.description || "") : ""}
        ${d.chapters && d.chapters.length ? `<div class="kg-kv"><span>Chapters</span><div>${d.chapters.map((c) => `<button class="kg-chapter" data-c="${c}">${c}</button>`).join("")}</div></div>` : ""}
        <div class="kg-actions"><button class="small kg-focus">Focus on neighbours</button></div>
        ${Object.entries(groups).sort((a, b) => b[1].length - a[1].length).map(([k, items]) => `
          <div class="kg-group"><div class="kg-gh">${esc(k)} <span>${items.length}</span></div>
          ${items.slice(0, 40).map((i) => `<a class="kg-link ${i.hidden ? "muted" : ""}" data-go="${esc(i.id)}"><i style="background:var(--k-${i.type})"></i>${esc(i.label)}</a>`).join("")}</div>`).join("")}`;
      side.querySelector(".kg-focus").onclick = () => { st.focus = d.id; apply(true); };
      side.querySelectorAll(".kg-chapter").forEach((b) => b.onclick = () => { st.from = st.to = +b.dataset.c; $(".kg-from").value = st.from; $(".kg-to").value = st.to; apply(false); });
      side.querySelectorAll("[data-go]").forEach((a) => a.onclick = () => go(a.dataset.go));
    }
    function showEdge(e) {
      const d = e.data();
      side.innerHTML = `<div class="kg-type">${esc(typeLabel[d.key] || d.type)}${d.inferred ? " · inferred" : ""}</div>
        ${cmp ? `<div class="kg-diffnote kg-st-${d.status}"><i></i><b>${esc((STATUS.find(([s]) => s === d.status) || [, d.status])[1])}</b>${d.diff ? " · " + esc(d.diff) : ""}</div>` : ""}
        <h3>${esc(snippet(e.source().data(), 50))} ${d.directed === false ? "↔" : "→"} ${esc(snippet(e.target().data(), 50))}</h3>
        ${row("Relation", d.label)}${row("Description", d.description)}${row("Weight", d.weight > 1 ? d.weight : "")}
        ${row("Chapters", (d.chapters || []).join(", "))}
        <div class="kg-group"><a class="kg-link" data-go="${esc(d.source)}">${esc(snippet(e.source().data()))}</a><a class="kg-link" data-go="${esc(d.target)}">${esc(snippet(e.target().data()))}</a></div>`;
      side.querySelectorAll("[data-go]").forEach((a) => a.onclick = () => go(a.dataset.go));
    }
    function go(id) {
      const n = cy.getElementById(id);
      if (!n.length) return;
      const t = n.data("type");
      if (!st.nodes.has(t)) { st.nodes.add(t); (EDGES_FOR[t] || []).forEach((k) => st.edges.add(k)); }
      if (!overlap(n.data("chapters"))) { st.from = cmin; st.to = cmax; $(".kg-from").value = cmin; $(".kg-to").value = cmax; }
      if (st.focus && !cy.getElementById(st.focus).closedNeighborhood().contains(n)) st.focus = null;
      apply(false);
      cy.elements().unselect(); n.select();
      cy.animate({ center: { eles: n }, zoom: Math.max(cy.zoom(), 1.1) }, { duration: 300 });
      showNode(n);
    }

    function intro() {
      if (!cmp) { side.innerHTML = `<p class="muted">Click a node or link for details. Hover to highlight its neighbours; double-click to focus on it.</p>`; return; }
      const sm = g.summary || {}, pct = (x) => x == null ? "–" : Math.round(100 * x) + "%";
      const lab = Object.fromEntries([...NODE_TYPES, ...EDGE_TYPES]);
      const ceil = g.ceiling || null;
      const tbl = (o, part) => Object.entries(o).filter(([, c]) => c.kept + c.changed + c.source_only + c.synthetic_only)
        .map(([k, c]) => { const cr = ceil && ((ceil[part] || {})[k] || {}).recall;
          return `<tr><td>${esc(lab[k] || k)}</td><td>${c.kept}</td><td>${c.changed}</td><td>${c.source_only}</td><td>${c.synthetic_only}</td><td>${pct(c.recall)}</td>${ceil ? `<td title="the same recall when the source is analysed twice: the best this comparison can show">${pct(cr)}</td>` : ""}</tr>`; }).join("");
      const hdr = `<tr><th></th><th title="found, same">kept</th><th title="found, but different people, place or wording">chg</th><th title="not found in the other graph">src</th><th title="only in the other graph">syn</th><th title="share of source items found">recall</th>${ceil ? `<th title="recall of the source against its own second analysis: the noise floor">ceiling</th>` : ""}</tr>`;
      const list = (status) => g.nodes.filter((n) => n.status === status && !STORY.has(n.type)).sort((a, b) => b.weight - a.weight).slice(0, 12)
        .map((n) => `<a class="kg-link" data-go="${esc(n.id)}"><i style="background:var(--k-${n.type})"></i>${esc(n.label)}</a>`).join("") || `<div class="muted">none</div>`;
      const as = g.alignment_stats || null;
      side.innerHTML = `<h3>${opts.against === "design_text" ? "Design vs synthetic text" : "Source vs " + (opts.against === "text" ? "synthetic text" : opts.against === "calibration" ? "its own second analysis" : "synthetic design")}</h3>
        <p class="muted" style="font-size:12px">${opts.against === "calibration" ? "The same source analysed twice: every difference is analysis noise." : (opts.against === "text" || opts.against === "design_text") ? "The synthetic text, analysed once, aligned with the design (which keeps the source's identities)." : "The design the synthetic story was written from (story bible after transformation)."} Recall = share of ${opts.against === "design_text" ? "design" : "source"} items found in the synthetic text.</p>
        ${as ? `<p class="muted" style="font-size:12px">Matched by names: ${as.rules ?? 0} · by the model: ${(as.model_entities || 0) + (as.model_story || 0)} · found by checking the text: ${as.found_by_check || 0} of ${as.checked || 0} still unmatched.</p>` : ""}
        ${ceil ? `<p class="muted" style="font-size:12px"><b>Ceiling</b> = the same recall when the source is compared with a second analysis of itself. Two analyses never agree fully, so a recall near the ceiling means the synthetic text keeps that layer as well as can be measured.</p>` : ""}
        <table class="kg-sum">${hdr}${tbl(sm.nodes || {}, "nodes")}</table>
        <table class="kg-sum" style="margin-top:8px">${hdr}${tbl(sm.edges || {}, "edges")}</table>
        <div class="kg-group"><div class="kg-gh">Only in the source</div>${list("source_only")}</div>
        <div class="kg-group"><div class="kg-gh">Only in the synthetic graph</div>${list("synthetic_only")}</div>`;
      side.querySelectorAll("[data-go]").forEach((a) => a.onclick = () => go(a.dataset.go));
    }
    const STORY = new Set(["chapter", "scene", "event"]);

    // ---- events
    cy.on("tap", (ev) => { if (ev.target === cy) intro(); });
    cy.on("tap", "node", (ev) => showNode(ev.target));
    cy.on("tap", "edge", (ev) => showEdge(ev.target));
    cy.on("dbltap", "node", (ev) => { st.focus = ev.target.id(); apply(true); showNode(ev.target); });
    const tip = $(".kg-tip");
    cy.on("mouseover", "node", (ev) => {
      const n = ev.target, d = n.data(), nb = n.closedNeighborhood();
      cy.elements(":visible").not(nb).addClass("faded"); nb.addClass("hl");
      const x = d.details || {};
      tip.innerHTML = `<b>${esc(d.type === "scene" || d.type === "event" ? `${typeLabel[d.type]} ${d.id.slice(1)}` : d.label)}</b><br>${esc((x.summary || x.description || "").slice(0, 160))}`;
      const p = ev.renderedPosition, box = $(".kg-canvas").getBoundingClientRect(), rb = root.getBoundingClientRect();
      tip.style.left = Math.min(box.left - rb.left + p.x + 14, box.right - rb.left - 270) + "px";
      tip.style.top = (box.top - rb.top + p.y + 14) + "px";
      tip.style.display = "block";
    });
    cy.on("mouseout", "node", () => { cy.elements().removeClass("faded hl"); tip.style.display = "none"; });
    root.querySelectorAll("[data-n]").forEach((b) => b.onclick = () => {
      const t = b.dataset.n;
      if (st.nodes.has(t)) st.nodes.delete(t);
      else { st.nodes.add(t); if (!(EDGES_FOR[t] || []).some((k) => st.edges.has(k))) (EDGES_FOR[t] || []).forEach((k) => st.edges.add(k)); }
      apply(true);
    });
    root.querySelectorAll("[data-e]").forEach((b) => b.onclick = () => {
      const t = b.dataset.e; st.edges.has(t) ? st.edges.delete(t) : st.edges.add(t); apply(st.layout === "force");
    });
    const syncRange = (moved) => {
      let f = +$(".kg-from").value, t = +$(".kg-to").value;
      if (f > t) { if (moved === "from") t = f; else f = t; $(".kg-from").value = f; $(".kg-to").value = t; }
      st.from = f; st.to = t; apply(false);
    };
    $(".kg-from").oninput = () => syncRange("from");
    $(".kg-to").oninput = () => syncRange("to");
    if ($(".kg-co")) $(".kg-co").oninput = (e) => { st.minCo = +e.target.value; $(".kg-co-v").textContent = st.minCo; apply(false); };
    $(".kg-iso").onchange = (e) => { st.isolated = e.target.checked; apply(false); };
    $(".kg-layout").onchange = (e) => { st.layout = e.target.value; layout(); };
    $(".kg-fit").onclick = () => cy.fit(cy.elements(":visible"), 30);
    $(".kg-all").onclick = () => { st.focus = null; apply(true); };
    if (cmp) {
      root.querySelectorAll("[data-s]").forEach((b) => b.onclick = () => { const v = b.dataset.s; st.status.has(v) ? st.status.delete(v) : st.status.add(v); apply(false); });
      $(".kg-diff-all").onclick = () => { st.status = new Set(STATUS.map(([s]) => s)); apply(false); };
      $(".kg-diff-chg").onclick = () => { st.status = new Set(["changed", "source_only", "synthetic_only"]); apply(false); };
    }
    const search = $(".kg-search");
    search.oninput = () => {
      const q = search.value.trim().toLowerCase();
      cy.nodes().removeClass("match");
      if (q.length < 2) return;
      cy.nodes().filter((n) => {
        const d = n.data(), x = d.details || {};
        return [d.label, ...(x.aliases || []), x.description, x.summary, x.counterpart].some((s) => s && String(s).toLowerCase().includes(q));
      }).addClass("match");
    };
    search.onkeydown = (e) => { if (e.key === "Enter") { const m = cy.nodes(".match"); if (m.length) go(m[0].id()); } };
    const download = (name, href) => { const a = document.createElement("a"); a.href = href; a.download = name; a.click(); };
    $(".kg-png").onclick = () => download(`${runId}-${which}${cmp ? "-" + (opts.against || "design") : ""}-graph.png`, cy.png({ full: true, scale: 2, bg: css("--panel") }));
    $(".kg-json").onclick = () => download(`${runId}-${which}-graph.json`, URL.createObjectURL(new Blob([JSON.stringify(g, null, 1)], { type: "application/json" })));

    intro();
    apply(true);
    return cy;
  };
})();
