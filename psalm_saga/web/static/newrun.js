// New run and Edit settings. The page follows the decisions a person makes, in order: the text; what
// carries over from it (one click for the common answers, every dimension adjustable); which models
// write and judge (chosen from the model library, described once); how (the full pipeline, or a
// method to compare with); and options. A bar at the bottom always shows what will run.
// Uses the helpers of index.html and models.js.

let PRESET = "full";
const JUDGES = {psalm: ["PSALM dimensions", "six dimensions × six aspects; function and expression rated separately, with evidence and reasoning (6 calls)"],
                content: ["Same story", "does the synthetic text tell the same story? (1 call)"],
                style: ["Same style", "does it read like the same writing? (1 call)"]};
function judgePicker(prefix, selected){ const sel = selected || Object.keys(JUDGES);
  return `<div class="stagepick">${Object.entries(JUDGES).map(([k,[l,h]])=>`<label title="${esc(h)}"><input type="checkbox" class="jpick-${prefix}" value="${k}" ${sel.includes(k)?"checked":""}> ${esc(l)}</label>`).join("")}</div>`; }
// kept for older code paths (a textarea of further judges)
function parsePanel(txt){ return (txt||"").split("\n").map(l=>l.trim()).filter(Boolean).map(l=>{ const i=l.indexOf("@");
  return i>0 ? {name:l.slice(0,i).trim(), api_base:l.slice(i+1).trim()} : l; }); }
function panelText(p){ return (p||[]).map(x=>typeof x==="string"?x:(x.use||`${x.name}${x.api_base?" @ "+x.api_base:""}`)).join("\n"); }

const DIMS6 = ["writing_style","narrative_voice","character","plot_structure","scene_sequence","world_building"];
const POLWORD = {preserve:"Keep", abstract:"Re-invent", regenerate:"Replace"};
const ROLE_STEPS = [["extract","Analyse the source (and the synthetic text)"],["spec","Describe the six dimensions"],["transform","Decide what carries over"],
                    ["plan","Plan the story"],["conform","Match the source's style"],["review","Check and repair"]];

// ------------------------------------------------------------------ what carries over
function levelOf(pol){ const L = (H().levels||[]).find(l=>DIMS6.every(d=>(l.policy[d]||"preserve")===(pol[d]||"preserve"))); return L ? L.key : "custom"; }
function polBar(pol){ return `<span class="polbar">${DIMS6.map(d=>`<i class="pb-${pol[d]||"preserve"}" title="${esc(d.replace(/_/g," "))}: ${POLWORD[pol[d]||"preserve"]}"></i>`).join("")}</span>`; }
function levelTiles(id, pol){
  const cur = levelOf(pol);
  return `<div class="tiles" role="radiogroup">${(H().levels||[]).map(l=>`<button type="button" role="radio" aria-checked="${l.key===cur}" class="tile ${l.key===cur?"on":""}" onclick="setLevel('${id}','${l.key}')">
      <b>${esc(l.title)}</b>${polBar(l.policy)}<span>${esc(l.summary)}</span><small>${esc(l.psalm)}</small></button>`).join("")}
    <div class="tile custom ${cur==="custom"?"on":""}" aria-checked="${cur==="custom"}"><b>Your own choice</b>${polBar(pol)}<span>Set each dimension below.</span></div></div>`;
}
function polRowsHTML(id, pol){
  const EX = H().dimension_examples||{};
  return META.taxonomy.dimensions.map(d=>`<div class="polrow"><div class="pd"><b>${esc(d.label)}</b>${info("dimension",d.key)}<div class="muted small">${esc(d.description)}</div></div>
    <div class="seg" data-pol-id="${id}" data-dim="${d.key}">${["preserve","abstract","regenerate"].map(o=>`<button type="button" class="${(pol[d.key]||"preserve")===o?"on":""} s-${o}" data-v="${o}" title="${esc((EX[d.key]||{})[o]||"")}" onclick="setDim('${id}','${d.key}','${o}')">${POLWORD[o]}</button>`).join("")}</div></div>`).join("");
}
function policyCard(id, pol){
  const P = H().policies||{};
  return `<div id="pol-${id}" data-pol='${esc(JSON.stringify(pol))}'>
    <div id="pol-${id}-tiles">${levelTiles(id, pol)}</div>
    <details class="poldetail" ${levelOf(pol)==="custom"?"open":""}><summary>Adjust each dimension <span class="muted small">— Keep: same particulars in new words · Re-invent: same function, new particulars · Replace: something new</span></summary>
      <div class="row small" style="margin:8px 0"><span class="muted">All six:</span>${["preserve","abstract","regenerate"].map(o=>`<button type="button" class="small" onclick="setAll('${id}','${o}')">${POLWORD[o]} all</button>`).join("")}</div>
      <div id="pol-${id}-rows">${polRowsHTML(id, pol)}</div></details></div>`;
}
function getPol(id){ const el = $(`#pol-${id}`); return el ? JSON.parse(el.dataset.pol) : {}; }
function _setPol(id, pol){ const el = $(`#pol-${id}`); el.dataset.pol = JSON.stringify(pol);
  $(`#pol-${id}-tiles`).innerHTML = levelTiles(id, pol); $(`#pol-${id}-rows`).innerHTML = polRowsHTML(id, pol); updateSummary(); }
function setLevel(id, key){ const L = (H().levels||[]).find(l=>l.key===key); if(L) _setPol(id, {...L.policy}); }
function setDim(id, dim, v){ const p = getPol(id); p[dim] = v; _setPol(id, p); }
function setAll(id, v){ const p = {}; DIMS6.forEach(d=>p[d]=v); _setPol(id, p); }

// ------------------------------------------------------------------ method (preset)
function presetFlags(cfg){
  const st = cfg.stages||{}, on = s => st[s] && st[s].enabled!==false;
  const impl = (st.draft||{}).impl||"chapter";
  const sees = impl==="paraphrase" || (impl==="oneshot" && ((st.draft.params||{}).inputs||[]).includes("source"));
  return [["story graph", on("transform") && impl!=="oneshot" && impl!=="paraphrase" && cfg.use_graph!==false],
          ["plan", on("plan") && impl==="chapter"], ["style matching", on("conform")], ["check and repair", on("review")],
          ["copy guard", on("guard")], ["writer sees the source", sees, true]];
}
function flagChips(cfg){ return `<span class="flags">${presetFlags(cfg).map(([l,v,inv])=>`<i class="${v?(inv?"neg":"yes"):"no"}">${v?"✓":"–"} ${esc(l)}</i>`).join("")}</span>`; }
function presetTile(p){ const h = (H().presets||{})[p.name]||{};
  return `<button type="button" role="radio" aria-checked="${p.name===PRESET}" class="tile ptile ${p.name===PRESET?"on":""}" data-preset="${p.name}" onclick="presetChanged('${p.name}')">
    <b>${esc(h.title||p.name)}${h.recommended?' <span class="core">recommended</span>':""}</b>${flagChips(p.config)}<span>${esc(h.summary||p.description)}</span>${h.when?`<small>${esc(h.when)}</small>`:""}</button>`; }
function methodCard(){
  const hp = H().presets||{}, by = {};
  META.presets.forEach(p=>{ const k=(hp[p.name]||{}).kind||"more"; (by[k]=by[k]||[]).push(p); });
  const cur = (hp[PRESET]||{}).kind||"more";
  return `<div class="tiles">${(by.main||[]).map(presetTile).join("")}</div>
    <details open><summary><b>${esc((H().kinds||{}).paper||"Compared in the paper")}</b> <span class="muted small">— the setups the experiments compare with the full pipeline</span></summary><div class="tiles">${(by.paper||[]).map(presetTile).join("")}</div></details>
    <details ${cur==="more"?"open":""}><summary><b>${esc((H().kinds||{}).more||"More")}</b></summary><div class="tiles">${(by.more||[]).map(presetTile).join("")}</div></details>
    <details><summary class="small">Turn single steps on or off</summary><div id="stages" class="stagepick" style="margin-top:6px"></div></details>`;
}
function presetChanged(name){
  PRESET = name || PRESET;
  document.querySelectorAll(".ptile").forEach(c=>{ const on = c.dataset.preset===PRESET; c.classList.toggle("on", on); c.setAttribute("aria-checked", on); });
  const p = META.presets.find(x=>x.name===PRESET);
  $("#stages").innerHTML = STAGE_ORDER.filter(s=>s in p.config.stages).map(s=>{const c=p.config.stages[s];
    return `<label title="${esc(((H().stages||{})[s]||{}).what||s)}"><input type="checkbox" data-stage="${s}" ${c.enabled?"checked":""}> ${esc(stageTitle(s))}${c.impl&&c.impl!==s?` <span class="muted">(${esc(c.impl)})</span>`:""}</label>`}).join("");
  const fixed = (p.config.stages.draft||{}).impl==="paraphrase";
  const note = $("#polnote"); if(note) note.innerHTML = fixed ? `<div class="pf warning"><b>${esc(presetTitle(PRESET))}</b> always keeps every dimension: it paraphrases the source passage by passage. The choice below does not apply.</div>` : "";
  // the person's choice of what carries over stays when they pick another method
  const ab = $("#allNewBody"); if(ab){ window.__extraRoles = {}; ab.innerHTML = allSettingsBox("nr", p.config); }
  updateSummary();
}

// ------------------------------------------------------------------ models
function writerDefault(cfg){ return refFromModel((cfg.models||{}).default||{}); }
function refFromModel(m){ if(!m) return ""; if(m.use) return m.use; const e = MODELS.find(x=>x.name===m.name); return e ? e.alias : (m.name||""); }
function providerOf(ref){ const e = modelEntry(ref); const n = e ? e.name : (ref||""); return n.split("/")[0]; }
function familyWarning(){
  const w = pickerValue("nr-writer"), j = pickerValue("nr-judge"), box = $("#judgewarn"); if(!box) return;
  box.innerHTML = (w && j && providerOf(w)===providerOf(j) && providerOf(w)!=="fake") ? `<span class="warn">The judge comes from the writer's own family; it may be lenient towards its text. Choose a judge of another family.</span>` : "";
}
function modelsCard(cfg){
  const roles = ROLE_STEPS.map(([r,l])=>{ const m = (cfg.models||{})[r]; const cur = m && (m.use || m.name!==((cfg.models||{}).default||{}).name) ? refFromModel(m) : "";
    return `<div><label>${esc(l)}</label>${modelPicker(`nr-role-${r}`, cur, {same:true, onchange:"updateSummary()"})}</div>`; }).join("");
  const writer = writerDefault(cfg);
  const judge = MODELS.find(m=>m.provider!==providerOf(writer) && m.kind==="api" && m.key_ready) || MODELS.find(m=>m.provider!==providerOf(writer));
  return `<div class="grid2"><div><label>Writer <span class="muted" style="font-weight:400">— writes the synthetic text, and does the other steps unless you choose otherwise</span></label>
      ${modelPicker("nr-writer", writer, {onchange:"familyWarning();updateSummary()"})}</div>
    <div><label>&nbsp;</label><div class="row small"><button type="button" class="small" onclick="showModels()">Manage models</button><button type="button" class="small" onclick="showKeys()">API keys</button></div>
      <p class="muted small">Each model is described once (id, address, reasoning, limits, price) under <i>Manage models</i>; here you only choose.</p></div></div>
    <details><summary class="small">Use other models for some steps <span class="muted">(e.g. a cheaper model for the analysis)</span></summary><div class="grid3" style="margin-top:6px">${roles}</div></details>
    <div class="jbox"><label style="color:var(--ink);font-size:13px;margin:10px 0 4px"><input type="checkbox" id="jOn" style="width:auto" onchange="$('#jbody').style.display=this.checked?'':'none';updateSummary()"> Judge the result with language models <span class="muted">(optional; adds the PSALM ratings and two holistic judgements to the evaluation)</span></label>
    <div id="jbody" style="display:none">
      <div class="grid2"><div><label>Primary judge <span class="muted" style="font-weight:400">— its ratings count in the grades; choose another family than the writer</span></label>${modelPicker("nr-judge", judge?judge.alias:"", {onchange:"familyWarning();updateSummary()"})}<div id="judgewarn" class="small"></div></div>
        <div><label>Judges to run</label>${judgePicker("j")}</div></div>
      <label>Further judges <span class="muted" style="font-weight:400">— optional: they repeat the same judgements, so you see whether judges agree</span></label>${modelChips("nr-panel", [])}
    </div></div>`;
}

// ------------------------------------------------------------------ the page
async function showNew(){
  CUR=null; closeES(); loadRuns(); await loadModels();
  const p = META.presets.find(x=>x.name===PRESET) || META.presets[0];
  $("#main").innerHTML = `
  <h2 style="font:600 24px var(--serif);margin:0 0 4px">New synthetic text</h2>
  <p class="lead">Four choices: the text, what carries over from it, which models write and judge, and how. Everything else has a sensible default and can be changed under <i>Options</i> and <i>All settings</i>. To compare methods across many texts, set up an <a href="#" onclick="showBuilder();return false">experiment</a> instead.</p>
  <div class="card"><h3>1 · Text</h3>
    <div class="drop" id="drop" onclick="$('#file').click()" ondragover="event.preventDefault();this.classList.add('over')" ondragleave="this.classList.remove('over')" ondrop="dropFile(event)">
      <b>Drop a text file here</b> or click to choose one <span class="muted">(.txt, .md; .json for a specification)</span><div id="fname" class="small"></div></div>
    <input type="file" id="file" accept=".txt,.md,.json" style="display:none" onchange="$('#fname').textContent=this.files[0]?this.files[0].name:'';updateSummary()">
    <label>…or paste it</label><textarea id="text" rows="5" placeholder="A book, a chapter, a story — or a premise for a new story." oninput="updateSummary()"></textarea>
    <div class="row small"><label style="margin:0">This is</label><select id="kind" style="max-width:300px" onchange="updateSummary()"><option value="auto">decided automatically</option><option value="source">a source text to make a counterpart of</option><option value="premise">a premise for a new story</option><option value="spec">a specification (JSON)</option></select>${info("mode")}
      <span class="muted">Any language: the synthetic text is written in the language of the input.</span></div>
  </div>
  <div class="card"><h3>2 · What carries over from the source ${info("policy")}</h3>
    <div id="polnote"></div>
    ${policyCard("nr", {...p.config.transform.policy})}
    <div class="row small" style="margin-top:8px"><label style="margin:0" title="Replace every character and place name with a new one (recommended: original names are protected expression)."><input type="checkbox" id="rename" checked style="width:auto"> replace all invented names</label>
      <label style="margin:0" title="New names fit the source's culture and period (Dutch names for a Dutch novel), instead of being free."><input type="checkbox" id="culture" checked style="width:auto"> new names fit the source's culture and period</label></div>
  </div>
  <div class="card"><h3>3 · Models</h3>${modelsCard(p.config)}</div>
  <div class="card"><h3>4 · How</h3>${methodCard()}</div>
  <details class="card"><summary><b>Options</b> <span class="muted small">— language and length, budget and time limit, priorities, pausing</span></summary>
    <div class="grid3"><div><label title="Output language; auto = the input's language">Language</label><input id="lang" placeholder="as the input"></div>
      <div><label title="Target length in words; empty = the source's length">Length in words</label><input id="words" type="number" placeholder="as the source"></div>
      <div><label title="Number of chapters; empty = the source's">Chapters</label><input id="chapters" placeholder="as the source"></div></div>
    <label>Language variety <span class="muted" style="font-weight:400">(dialect or historical spelling)</span></label><input id="variety" placeholder="empty = keep the source's variety · 'modern' = modernise · or describe one">
    <div class="grid2"><div><label>Budget in US dollars <span class="muted" style="font-weight:400">(stops when spent)</span></label><input id="budget" type="number" step="0.5" placeholder="no limit"></div>
      <div><label>Time limit in minutes <span class="muted" style="font-weight:400">(stops, keeps everything, can be continued)</span></label><input id="minutes" type="number" step="5" placeholder="no limit"></div></div>
    <label>Priorities <span class="muted" style="font-weight:400">— measures that matter most for your study (the generation works harder on them)</span></label>${priorityPicker("nr", [])}
    <label>Pause after <span class="muted" style="font-weight:400">(to inspect or edit before going on)</span></label><select id="until"><option value="">run to the end</option><option value="spec">the specification</option><option value="transform">the design (names and transformed story)</option><option value="plan">the plan</option></select>
    <label style="color:var(--ink);font-size:13px" title="Every model answer is kept on disk. By default a run only replays its own answers (resuming is free), so running the same text again gives a new sample."><input type="checkbox" id="sharedCache" style="width:auto"> reuse answers from earlier identical runs (free, but not a new sample)</label>
  </details>
  <details class="card" id="allNew"><summary><b>All settings</b> <span class="muted small">— every setting of the run: models per step, every step's parameters, judges, limits</span></summary>
    <div id="allNewBody"></div>
    <label>Extra settings <span class="muted" style="font-weight:400">(one key=value per line)</span></label><textarea id="extra" rows="2" class="mono" placeholder="stages.review.params.rounds=2"></textarea>
  </details>
  <div id="pfnew"></div>
  <div class="actionbar"><div id="summary" class="small"></div><div class="row"><button onclick="checkNew()" title="Check the models, API keys and settings without starting">Check settings</button><button class="primary" onclick="createRun()" title="The settings are checked first; a run with a problem waits for you to fix it">Start</button></div></div>`;
  presetChanged(PRESET); prioWire("nr"); familyWarning();
  $("#main").addEventListener("change", updateSummary);
}
function dropFile(ev){ ev.preventDefault(); $("#drop").classList.remove("over"); const f = ev.dataTransfer.files[0]; if(!f) return;
  const dt = new DataTransfer(); dt.items.add(f); $("#file").files = dt.files; $("#fname").textContent = f.name; updateSummary(); }
function updateSummary(){
  const box = $("#summary"); if(!box) return;
  const f = $("#file") && $("#file").files[0], t = ($("#text")||{}).value||"";
  const text = f ? f.name : t.trim() ? `${t.trim().split(/\s+/).length.toLocaleString()} words pasted` : `<span class="warn">no text yet</span>`;
  const p = META.presets.find(x=>x.name===PRESET);
  const fixed = (p.config.stages.draft||{}).impl==="paraphrase";
  const lvl = fixed ? "keep everything" : (((H().levels||[]).find(l=>l.key===levelOf(getPol("nr")))||{}).title||"your own choice");
  const w = modelLabel(pickerValue("nr-writer")) || "the preset's model";
  const judges = $("#jOn") && $("#jOn").checked ? [pickerValue("nr-judge"), ...chipsValue("nr-panel")].filter(Boolean).map(modelLabel) : [];
  box.innerHTML = `<b>${esc(presetTitle(PRESET))}</b> · ${esc(lvl)} · written by <b>${esc(w)}</b>${judges.length?` · judged by ${esc(judges.join(", "))}`:" · no judges"} · ${text}`;
}

function newOverrides(){
  const p = META.presets.find(x=>x.name===PRESET);
  const ov = {};
  document.querySelectorAll("[data-stage]").forEach(c=>{ if(c.checked!==p.config.stages[c.dataset.stage].enabled) ov[`stages.${c.dataset.stage}.enabled`]=c.checked; });
  if((p.config.stages.draft||{}).impl!=="paraphrase"){
    const pol = getPol("nr"); for(const [k,v] of Object.entries(pol)) if(v!==p.config.transform.policy[k]) ov[`transform.policy.${k}`]=v; }
  if(!$("#rename").checked) ov["transform.rename_entities"]=false;
  if(!$("#culture").checked) ov["transform.keep_cultural_setting"]=false;
  const w = pickerValue("nr-writer"); if(w && w!==writerDefault(p.config)) roleOverrides("default", w, ov);
  ROLE_STEPS.forEach(([r])=>{ const v = pickerValue(`nr-role-${r}`); if(v) roleOverrides(r, v, ov); });
  if($("#jOn").checked){ ov["judges.enabled"]=true; const j = pickerValue("nr-judge"); if(j) ov["judges.model"]=j;
    ov["judges.instruments"]=[...document.querySelectorAll(".jpick-j:checked")].map(x=>x.value);
    const pn = chipsValue("nr-panel"); if(pn.length) ov["judges.panel"]=pn; }
  if($("#lang").value) ov["language.output"]=$("#lang").value.trim();
  if($("#variety").value) ov["language.variety"]=$("#variety").value.trim();
  if($("#words").value) ov["length.target_words"]=+$("#words").value;
  if($("#chapters").value) ov["length.chapters"]= isNaN(+$("#chapters").value)? $("#chapters").value : +$("#chapters").value;
  if($("#budget").value) ov["limits.max_cost_usd"]=+$("#budget").value;
  if($("#minutes").value) ov["limits.max_minutes"]=+$("#minutes").value;
  const pr = readPriorities("nr"); if(pr.length) ov["priorities"]=pr;
  if($("#sharedCache").checked) ov["cache_scope"]="shared";
  Object.assign(ov, readAllSettings("nr"));   // the full editor wins where both set a value
  $("#extra").value.split("\n").map(l=>l.trim()).filter(Boolean).forEach(l=>{const i=l.indexOf("="); if(i<1) return; let v=l.slice(i+1).trim(); try{v=JSON.parse(v)}catch{} ov[l.slice(0,i).trim()]=v;});
  return ov;
}
async function checkNew(){
  const box=$("#pfnew"); box.innerHTML = `<div class="card"><span class="muted">Checking the settings, with one tiny test call per model…</span></div>`;
  try{ const r = await api("/api/check", {method:"POST", headers:{"content-type":"application/json"}, body:JSON.stringify({preset:PRESET, overrides:newOverrides()})}); box.innerHTML = `<div class="card">${pfHTML(r)}</div>`; box.scrollIntoView({behavior:"smooth"}); }
  catch(e){ box.innerHTML = `<div class="card"><div class="pf error">${esc(e.message)}</div></div>`; }
}
async function createRun(){
  const p = META.presets.find(x=>x.name===PRESET);
  if(!$("#text").value.trim() && !$("#file").files[0]){ toast("Add a text first: drop a file or paste it."); return; }
  const fd = new FormData();
  fd.append("text", $("#text").value); fd.append("kind", $("#kind").value); fd.append("preset", p.name);
  fd.append("overrides", JSON.stringify(newOverrides())); fd.append("until", $("#until").value);
  if($("#file").files[0]) fd.append("file", $("#file").files[0]);
  try{ const r = await api("/api/runs", {method:"POST", body:fd}); toast("Run created — starting. Follow it in the activity tab."); TAB="activity"; await openRun(r.id); }catch(e){ toast(e.message); }
}
function setPolicies(kind){ const map = {all:"keep_all", surface:"new_people", structure:"structure_only"}; setLevel("nr", map[kind]||kind); }

// ------------------------------------------------------------------ edit settings of a run
async function editSettings(){
  await loadModels();
  const cfg = (ST.meta||{}).config||{};
  const roles = ROLE_STEPS.map(([r,l])=>{ const m = (cfg.models||{})[r]; const cur = m && (m.use || m.name!==((cfg.models||{}).default||{}).name) ? refFromModel(m) : "";
    return `<div><label>${esc(l)}</label>${modelPicker(`es-role-${r}`, cur, {same:true})}</div>`; }).join("");
  window.__esOrig = {writer: writerDefault(cfg), judge: cfg.judges.model || "", panel: (cfg.judges.panel||[]).map(x=>typeof x==="object"?(x.use||x.name):x),
                     roles: Object.fromEntries(ROLE_STEPS.map(([r])=>{ const m=(cfg.models||{})[r]; return [r, m && (m.use || m.name!==((cfg.models||{}).default||{}).name) ? refFromModel(m) : ""]; }))};
  modal("Edit settings", `<p class="small">Changes apply to what the run still has to do (and to anything you redo). Finished steps are kept — to apply a change to them, use <i>Redo from…</i> afterwards.</p>
    <h4>Models</h4>
    <div class="grid2"><div><label>Writer</label>${modelPicker("es-writer", window.__esOrig.writer)}</div>
      <div><label>&nbsp;</label><div class="row small"><button class="small" onclick="showModels()">Manage models</button><button class="small" onclick="showKeys()">API keys</button></div></div></div>
    <details><summary class="small">Other models for some steps</summary><div class="grid3">${roles}</div></details>
    <h4>Judges</h4>
    <label style="color:var(--ink);font-size:13px"><input type="checkbox" id="es-jon" style="width:auto" ${cfg.judges.enabled?"checked":""}> judge the result with language models</label>
    <div class="grid2"><div><label>Primary judge</label>${modelPicker("es-judge", window.__esOrig.judge, {same:true, sameLabel:"the judge role / the writer's model (not advised)"})}</div><div><label>Judges to run</label>${judgePicker("es", cfg.judges.instruments)}</div></div>
    <label>Further judges</label>${modelChips("es-panel", window.__esOrig.panel)}
    <h4>Limits</h4>
    <div class="grid2"><div><label>Budget (US dollars; empty = no limit)</label><input id="es-budget" type="number" step="0.5" value="${cfgGet(cfg,"limits.max_cost_usd")??""}"></div>
      <div><label>Time limit (minutes; empty = none)</label><input id="es-minutes" type="number" step="5" value="${cfgGet(cfg,"limits.max_minutes")??""}"></div></div>
    <details style="margin-top:10px"><summary><b>What carries over</b> <span class="muted small">— takes effect when the design is made again (Redo from “Decide what carries over”)</span></summary>${policyCard("es", {...cfg.transform.policy})}</details>
    <details style="margin-top:10px"><summary><b>Priorities</b> <span class="muted small">— ${(cfg.priorities||[]).length?esc((cfg.priorities||[]).join(", ")):"none: every measure counts equally"}</span></summary>${priorityPicker("es", cfg.priorities||[])}</details>
    <details style="margin-top:12px"><summary><b>All settings</b> <span class="muted small">— every step's parameters, model settings per step, judges, limits</span></summary>${allSettingsBox("es", cfg)}
      <label>Extra settings <span class="muted" style="font-weight:400">(one key=value per line)</span></label><textarea id="es-extra" rows="2" class="mono"></textarea></details>
    <div class="row" style="margin-top:12px"><button class="primary" onclick="saveSettings(true)">Save, check and continue</button><button onclick="saveSettings(false)">Save and check</button><span class="muted small" id="es-msg"></span></div>
    <div id="pfm"></div>`);
  prioWire("es");
}
async function saveSettings(go){
  const cfg = (ST.meta||{}).config||{}, ov = {}, O = window.__esOrig||{};
  const w = pickerValue("es-writer"); if(w && w!==O.writer) roleOverrides("default", w, ov);
  ROLE_STEPS.forEach(([r])=>{ const v = pickerValue(`es-role-${r}`); if(v!==(O.roles||{})[r]){ if(v) roleOverrides(r, v, ov); else { ov[`models.${r}`] = null; } } });
  if($("#es-jon").checked!==!!cfg.judges.enabled) ov["judges.enabled"]=$("#es-jon").checked;
  const j = pickerValue("es-judge"); if(j!==O.judge) ov["judges.model"] = j || null;
  const ins = [...document.querySelectorAll(".jpick-es:checked")].map(x=>x.value); if(JSON.stringify(ins)!==JSON.stringify(cfg.judges.instruments)) ov["judges.instruments"]=ins;
  const pn = chipsValue("es-panel"); if(JSON.stringify(pn)!==JSON.stringify(O.panel)) ov["judges.panel"]=pn;
  const b = $("#es-budget").value; const bv = b===""?null:+b; if(bv!==(cfgGet(cfg,"limits.max_cost_usd")??null)) ov["limits.max_cost_usd"]=bv;
  const m=$("#es-minutes").value; const mv = m===""?null:+m; if(mv!==(cfgGet(cfg,"limits.max_minutes")??null)) ov["limits.max_minutes"]=mv;
  const pr = readPriorities("es"); if(JSON.stringify(pr)!==JSON.stringify(cfg.priorities||[])) ov["priorities"]=pr;
  const pol = getPol("es"); for(const [k,v] of Object.entries(pol)) if(v!==(cfg.transform.policy||{})[k]) ov[`transform.policy.${k}`]=v;
  Object.assign(ov, readAllSettings("es"));
  $("#es-extra").value.split("\n").map(l=>l.trim()).filter(Boolean).forEach(l=>{const i=l.indexOf("="); if(i<1) return; let v=l.slice(i+1).trim(); try{v=JSON.parse(v)}catch{} ov[l.slice(0,i).trim()]=v;});
  const msg=$("#es-msg");
  try{
    if(Object.keys(ov).length){ await api(`/api/runs/${CUR}/config`, {method:"PUT", headers:{"content-type":"application/json"}, body:JSON.stringify({overrides:ov})}); if(msg) msg.textContent=`saved ${Object.keys(ov).length} change${Object.keys(ov).length>1?"s":""} — checking…`; }
    else if(msg) msg.textContent="no changes — checking…";
    const st = await api(`/api/runs/${CUR}`); window.ST = st;
    const r = await api(`/api/runs/${CUR}/check`, {method:"POST"}); const box=$("#pfm"); if(box) box.innerHTML = pfHTML(r);
    if(r.ok && go){ closeModal(); await runAgain(); return; }
    if(msg) msg.textContent = r.ok ? "saved; the settings are ready" : "saved; the check still finds problems";
    renderRun(true);
  }catch(e){ if(msg) msg.textContent = e.message; toast(e.message); }
}

// ------------------------------------------------------------------ judges on a finished run
async function runJudges(){
  const model = pickerValue("jModelEv")||"", instruments=[...document.querySelectorAll(".jpick-ev:checked")].map(x=>x.value);
  const panel = chipsValue("jPanelEv");
  if(!instruments.length){ toast("Choose at least one judge."); return; }
  try{ await api(`/api/runs/${CUR}/judge`, {method:"POST", headers:{"content-type":"application/json"}, body:JSON.stringify({model, instruments, panel})}); toast("Judges running — only the evaluation is redone."); TAB="activity"; await openRun(CUR); }
  catch(e){ toast(e.message); }
}
