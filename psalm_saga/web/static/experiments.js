// Experiment builder: set up, save, check and start an experiment plan without writing YAML.
// Uses the helpers of index.html ($, esc, api, toast, META, H, presetTitle, allSettingsBox,
// readAllSettings, parsePanel, panelText). The plan it writes is experiments/<name>.yaml, the same
// file the command line runs (`saga experiment experiments/<name>.yaml`).

const DIMS = ["writing_style", "narrative_voice", "character", "plot_structure", "scene_sequence", "world_building"];
const POLS = ["preserve", "abstract", "regenerate"];
const PAPER = {
  policies: {
    preserve: {all: "preserve"},
    reinvent: {all: "abstract", writing_style: "preserve", narrative_voice: "preserve"},
    replace: {all: "regenerate", writing_style: "preserve", narrative_voice: "preserve"},
  },
  conditions: [
    {name: "full", preset: "full", repeats: 3, policies: null, panel: true},
    {name: "no_graph", preset: "no_graph", repeats: 1, policies: null},
    {name: "no_feedback", preset: "no_feedback", repeats: 1, policies: null},
    {name: "paraphrase", preset: "paraphrase", repeats: 1, policies: ["preserve"]},
    {name: "single_call", preset: "flat", repeats: 1, policies: null},
  ],
  models: [
    {key: "mistral_large", name: "mistral/mistral-large-4-0", api_base: "", effort: "", max_out: "", ctx: "", conc: ""},
    {key: "gemma_small", name: "ollama_chat/gemma4:e4b", api_base: "http://localhost:11434", effort: "", max_out: 8192, ctx: 131072, conc: 1},
  ],
  judges: {model: "anthropic/claude-sonnet-5-5", panel: ["openai/<model>", {name: "hosted_vllm/Qwen/Qwen3.5-397B-A17B", api_base: "http://<host>:8000/v1"}],
           instruments: ["psalm", "content", "style"], exp: ["psalm_check", "psalm_anchor", "alignment_anchor", "quality_pairwise"],
           quality_baseline: "single_call"},
};
const EXP_INSTR = {psalm_check: "agreement of the further judges (PSALM)", psalm_anchor: "PSALM on unrelated texts (lower anchor)",
  alignment_anchor: "alignment against another book's text (lower anchor)", quality_pairwise: "blind pairwise quality against a baseline",
  emotional_arc: "emotional arc", surface_reuse: "close paraphrase and distinctive particulars", reconstruction: "reconstruction attack",
  spec_recovery: "specification recovered from the text"};
let EXPB = null;

function _clone(x){ return JSON.parse(JSON.stringify(x)); }
function newBuilderState(){
  return {name: "my_experiment", inputs: ["inputs/my_experiment/*.txt"], metadata: "", policies: _clone(PAPER.policies),
          conditions: _clone(PAPER.conditions), models: _clone(PAPER.models), judges: _clone(PAPER.judges),
          repeats: 1, concurrency: 2, budget: 10, minutes: 240, hypotheses: "default", overrides: {}, quick: false};
}
function demoState(){
  const s = newBuilderState();
  Object.assign(s, {name: "demo", policies: {preserve: {all: "preserve"}, reinvent: _clone(PAPER.policies.reinvent)},
    conditions: [{name: "full", preset: "full", repeats: 1, policies: null, panel: false},
                 {name: "single_call", preset: "flat", repeats: 1, policies: null}],
    models: [_clone(PAPER.models[0])], budget: 2, minutes: 60, inputs: ["inputs/demo/*.txt"]});
  s.judges.panel = []; s.judges.exp = []; return s;
}

async function loadExperimentPlans(){
  try{
    const ps = await api("/api/experiment-plans");
    const box = $("#expPlans"); if(!box) return;
    box.innerHTML = `<div class="muted" style="font-size:11px;text-transform:uppercase;letter-spacing:.05em;margin:10px 0 4px">Experiment plans</div>`
      + ps.map(p=>`<a class="small-link" href="#" onclick="showBuilder('${esc(p.name)}');return false" style="display:block;font-size:13px;padding:3px 0">${esc(p.name)} <span class="muted">· ${p.error?"has a problem":`${p.done||0}/${p.jobs} runs${p.running?" · running":""}`}</span></a>`).join("")
      + `<a class="small-link" href="#" onclick="showBuilder();return false" style="display:block;font-size:13px;padding:3px 0">+ New experiment</a>`;
  }catch(e){}
}

function stateFromPlan(name, plan){
  const s = newBuilderState(); s.name = name;
  s.inputs = (plan.inputs||[]).map(i=>i.glob||i.path).filter(Boolean);
  s.metadata = plan.metadata||""; s.policies = plan.policies||{};
  s.repeats = plan.repeats||1; s.concurrency = plan.concurrency||2;
  const ov = {...(plan.overrides||{})};
  s.budget = ov["limits.max_cost_usd"] ?? ""; s.minutes = ov["limits.max_minutes"] ?? "";
  s.judges.model = ov["judges.model"] || (plan.judge||{}).model || "";
  s.judges.instruments = ov["judges.instruments"] || s.judges.instruments;
  s.judges.exp = (plan.judge||{}).instruments || [];
  s.judges.quality_baseline = (plan.judge||{}).quality_baseline || "";
  let panel = [];
  s.conditions = Object.entries(plan.conditions||{}).map(([n,c])=>{ const o = {...(c.overrides||{})}; const pn = o["judges.panel"]; delete o["judges.panel"];
    if(pn) panel = pn; return {name: n, preset: c.preset||"full", repeats: c.repeats||1, policies: c.policies||null, panel: !!pn, overrides: o}; });
  s.judges.panel = panel.length ? panel : ((plan.judge||{}).check_models||[]);
  s.models = Object.entries(plan.models||{}).map(([k,m])=>({key: k, name: m["models.default.name"]||"", api_base: m["models.default.extra.api_base"]||"",
    effort: m["models.default.extra.reasoning_effort"]||"", max_out: m["models.default.max_output_tokens"]||"", ctx: m["models.default.context_window"]||"",
    conc: m["models.default.max_concurrency"]||""}));
  ["limits.max_cost_usd","limits.max_minutes","judges.enabled","judges.model","judges.instruments"].forEach(k=>delete ov[k]);
  s.overrides = ov; s.hypotheses = Array.isArray(plan.hypotheses) ? plan.hypotheses : (plan.hypotheses||"default");
  s.analyses = plan.analyses; s.tstr_label = plan.tstr_label; s.period_split = plan.period_split; s.output = plan.output;
  s.alpha = plan.alpha; s.bootstrap = plan.bootstrap; s.margins = plan.margins;
  return s;
}

function planFromState(s){
  const conds = {};
  s.conditions.forEach(c=>{ const o = {...(c.overrides||{})};
    if(c.panel && s.judges.panel.length) o["judges.panel"] = s.judges.panel;
    conds[c.name] = {preset: c.preset, ...(c.repeats>1?{repeats: +c.repeats}:{}), ...(c.policies&&c.policies.length?{policies: c.policies}:{}), ...(Object.keys(o).length?{overrides: o}:{})}; });
  const models = {};
  s.models.forEach(m=>{ const o = {"models.default.name": m.name};
    if(m.api_base) o["models.default.extra.api_base"] = m.api_base;
    if(m.effort) o["models.default.extra.reasoning_effort"] = m.effort;
    if(m.max_out) o["models.default.max_output_tokens"] = +m.max_out;
    if(m.ctx) o["models.default.context_window"] = +m.ctx;
    if(m.conc) o["models.default.max_concurrency"] = +m.conc;
    models[m.key] = o; });
  const ov = {...s.overrides};
  if(s.budget!=="" && s.budget!=null) ov["limits.max_cost_usd"] = +s.budget;
  if(s.minutes!=="" && s.minutes!=null) ov["limits.max_minutes"] = +s.minutes;
  if(s.judges.model){ ov["judges.enabled"] = true; ov["judges.model"] = s.judges.model; ov["judges.instruments"] = s.judges.instruments; }
  const plan = {output: s.output || `experiments_out/${s.name}`, inputs: s.inputs.filter(Boolean).map(g=>({glob: g, kind: "source"})),
    ...(Object.keys(s.policies).length?{policies: s.policies}:{}), conditions: conds, models, repeats: +s.repeats||1,
    concurrency: +s.concurrency||2, overrides: ov};
  if(s.judges.model && (s.judges.exp||[]).length){
    plan.judge = {model: s.judges.model, instruments: s.judges.exp,
                  ...(s.judges.panel.length?{check_models: s.judges.panel.map(p=>typeof p==="string"?p:p.name)}:{}),
                  ...(s.judges.quality_baseline?{quality_baseline: s.judges.quality_baseline}:{})};
  }
  if(s.metadata) plan.metadata = s.metadata;
  ["analyses","tstr_label","period_split","alpha","bootstrap","margins"].forEach(k=>{ if(s[k]!==undefined && s[k]!==null) plan[k] = s[k]; });
  plan.hypotheses = s.hypotheses;
  return plan;
}

async function showBuilder(name){
  CUR=null; if(typeof closeES==="function") closeES();
  if(name){ try{ const r = await api(`/api/experiment-plans/${encodeURIComponent(name)}`); EXPB = stateFromPlan(name, r.plan||{}); EXPB.__info = r; }
            catch(e){ toast(e.message); EXPB = newBuilderState(); } }
  else EXPB = newBuilderState();
  renderBuilder();
}

function _presetOptions(sel){ return META.presets.map(p=>`<option value="${esc(p.name)}" ${p.name===sel?"selected":""}>${esc(presetTitle(p.name))} (${esc(p.name)})</option>`).join(""); }

function renderBuilder(){
  const s = EXPB, P = Object.keys(s.policies);
  const polRows = Object.entries(s.policies).map(([n,spec])=>{ const full = Object.fromEntries(DIMS.map(d=>[d, spec[d]||spec.all||"preserve"]));
    return `<tr><td><input value="${esc(n)}" onchange="renamePolicy('${esc(n)}', this.value)" style="width:110px"></td>${DIMS.map(d=>`<td><select onchange="EXPB.policies['${esc(n)}']['${d}']=this.value">${POLS.map(v=>`<option ${full[d]===v?"selected":""}>${v}</option>`).join("")}</select></td>`).join("")}<td><button class="small" onclick="delete EXPB.policies['${esc(n)}'];renderBuilder()">remove</button></td></tr>`; }).join("");
  const condRows = s.conditions.map((c,i)=>`<tr><td><input value="${esc(c.name)}" onchange="EXPB.conditions[${i}].name=this.value"></td>
      <td><select onchange="EXPB.conditions[${i}].preset=this.value">${_presetOptions(c.preset)}</select></td>
      <td><input type="number" min="1" value="${c.repeats||1}" style="width:60px" onchange="EXPB.conditions[${i}].repeats=+this.value"></td>
      <td>${P.length?P.map(p=>`<label class="small" style="display:inline-flex;gap:3px;margin:0 6px 0 0"><input type="checkbox" style="width:auto" ${!c.policies||c.policies.includes(p)?"checked":""} onchange="togglePol(${i},'${esc(p)}',this.checked)">${esc(p)}</label>`).join(""):'<span class="muted small">—</span>'}</td>
      <td><input type="checkbox" style="width:auto" ${c.panel?"checked":""} onchange="EXPB.conditions[${i}].panel=this.checked" title="the further judges also rate this condition's runs"></td>
      <td><button class="small" onclick="EXPB.conditions.splice(${i},1);renderBuilder()">remove</button></td></tr>`).join("");
  const modelRows = s.models.map((m,i)=>`<tr><td><input value="${esc(m.key)}" style="width:110px" onchange="EXPB.models[${i}].key=this.value"></td>
      <td><input value="${esc(m.name)}" onchange="EXPB.models[${i}].name=this.value" placeholder="provider/model"></td>
      <td><input value="${esc(m.api_base||"")}" onchange="EXPB.models[${i}].api_base=this.value" placeholder="(API)"></td>
      <td><select onchange="EXPB.models[${i}].effort=this.value">${["","low","medium","high"].map(v=>`<option value="${v}" ${m.effort===v?"selected":""}>${v||"default"}</option>`).join("")}</select></td>
      <td><input type="number" value="${m.max_out||""}" style="width:80px" onchange="EXPB.models[${i}].max_out=this.value" placeholder="default"></td>
      <td><input type="number" value="${m.ctx||""}" style="width:90px" onchange="EXPB.models[${i}].ctx=this.value" placeholder="default"></td>
      <td><input type="number" value="${m.conc||""}" style="width:55px" onchange="EXPB.models[${i}].conc=this.value" placeholder="4"></td>
      <td><button class="small" onclick="EXPB.models.splice(${i},1);renderBuilder()">remove</button></td></tr>`).join("");
  const condNames = s.conditions.map(c=>c.name);
  const info = s.__info && !s.__info.error ? s.__info : null;
  const hypo = s.hypotheses==="default" ? "default" : "custom";
  $("main").innerHTML = `<h2 style="font:600 22px var(--serif);margin:0 0 4px">Experiment</h2>
  <p class="muted">Set up a whole experiment here: the texts, the policy settings, the setups to compare, the writer models, the judges and the pre-registered tests. It is saved as <code>experiments/${esc(s.name)}.yaml</code>, the same file the command line runs. Every condition runs on every text with every writer; a run that stops can be continued, nothing is paid twice.</p>
  <div class="row" style="margin-bottom:8px"><button class="small" onclick="EXPB=Object.assign(newBuilderState(),{name:EXPB.name});renderBuilder()">Start from the paper's design</button>
    <button class="small" onclick="EXPB=demoState();renderBuilder()">Start from a small demo</button></div>
  <div class="card"><h3>1 · Name and texts</h3>
    <div class="grid2"><div><label>Name</label><input id="xb-name" value="${esc(s.name)}" onchange="EXPB.name=this.value.trim()"></div>
      <div><label>Metadata CSV <span class="muted" style="font-weight:400">(optional: item, year, author_gender, … for the corpus analyses)</span></label><input value="${esc(s.metadata||"")}" onchange="EXPB.metadata=this.value.trim()" placeholder="../corpus/metadata.csv"></div></div>
    <label>Texts <span class="muted" style="font-weight:400">(one file pattern per line, relative to the experiments folder)</span></label>
    <textarea rows="2" class="mono" onchange="EXPB.inputs=this.value.split('\\n').map(x=>x.trim()).filter(Boolean)">${esc(s.inputs.join("\n"))}</textarea>
    <div class="row small" style="margin-top:6px"><input type="file" id="xb-files" multiple accept=".txt,.md" style="max-width:320px"><button class="small" onclick="uploadExpTexts()">Upload texts</button><span class="muted">saved to experiments/inputs/${esc(s.name)}/ and added above</span></div></div>
  <div class="card"><h3>2 · Policy settings <span class="muted" style="font:12px var(--sans)">— each condition runs under each setting it is ticked for</span></h3>
    <p class="muted small">preserve keeps a dimension (function and expression high), abstract re-invents it (function high, expression low), regenerate replaces it (both low). Leave the table empty to use each preset's own policy.</p>
    <table class="small"><tr><th>name</th>${DIMS.map(d=>`<th>${esc(d.replace(/_/g," "))}</th>`).join("")}<th></th></tr>${polRows}</table>
    <button class="small" style="margin-top:6px" onclick="addPolicy()">Add a setting</button></div>
  <div class="card"><h3>3 · Setups</h3>
    <table class="small"><tr><th>name</th><th>preset</th><th>samples per text</th><th>policy settings</th><th title="the further judges also rate it">all judges</th><th></th></tr>${condRows}</table>
    <button class="small" style="margin-top:6px" onclick="EXPB.conditions.push({name:'cond'+(EXPB.conditions.length+1),preset:'full',repeats:1,policies:null});renderBuilder()">Add a setup</button>
    <p class="muted small">Presets: ${META.presets.map(p=>`<b>${esc(p.name)}</b> ${esc(((H().presets||{})[p.name]||{}).title||"")}`).join(" · ")}</p></div>
  <div class="card"><h3>4 · Writer models</h3>
    <table class="small"><tr><th>key</th><th>model id</th><th>endpoint</th><th>reasoning</th><th>max output</th><th>context</th><th>parallel</th><th></th></tr>${modelRows}</table>
    <button class="small" style="margin-top:6px" onclick="EXPB.models.push({key:'model'+(EXPB.models.length+1),name:''});renderBuilder()">Add a writer</button>
    <p class="muted small">A self-hosted model: e.g. <code>ollama_chat/gemma4:e4b</code> with endpoint <code>http://localhost:11434</code>, or <code>hosted_vllm/&lt;model&gt;</code> with a vLLM endpoint. Set API keys with <a href="#" onclick="showKeys();return false">API keys</a>.</p></div>
  <div class="card"><h3>5 · Judges</h3>
    <div class="grid2"><div><label>Primary judge <span class="muted" style="font-weight:400">(decides the grades; another family than every writer)</span></label><input value="${esc(s.judges.model||"")}" onchange="EXPB.judges.model=this.value.trim()" placeholder="anthropic/claude-…"></div>
      <div><label>Judges in every run</label><div class="stagepick">${["psalm","content","style"].map(k=>`<label><input type="checkbox" ${s.judges.instruments.includes(k)?"checked":""} onchange="toggleIn(EXPB.judges.instruments,'${k}',this.checked)"> ${k}</label>`).join("")}</div></div></div>
    <label>Further judges <span class="muted" style="font-weight:400">(one per line: model id, or <code>id @ endpoint</code>; they rate the setups ticked "all judges", for the agreement check)</span></label>
    <textarea rows="2" class="mono" onchange="EXPB.judges.panel=parsePanel(this.value)">${esc(panelText(s.judges.panel))}</textarea>
    <label>Experiment-level checks</label><div class="stagepick">${Object.entries(EXP_INSTR).map(([k,l])=>`<label title="${esc(l)}"><input type="checkbox" ${(s.judges.exp||[]).includes(k)?"checked":""} onchange="toggleIn(EXPB.judges.exp,'${k}',this.checked)"> ${esc(k)}</label>`).join("")}</div>
    <label>Quality baseline <span class="muted" style="font-weight:400">(blind pairwise comparison against this setup, same policy setting)</span></label>
    <select onchange="EXPB.judges.quality_baseline=this.value"><option value="">none</option>${condNames.map(n=>`<option ${s.judges.quality_baseline===n?"selected":""}>${esc(n)}</option>`).join("")}</select></div>
  <div class="card"><h3>6 · Limits and settings for every run</h3>
    <div class="grid3"><div><label>Budget per run (US dollars)</label><input type="number" step="0.5" value="${s.budget??""}" onchange="EXPB.budget=this.value"></div>
      <div><label>Time limit per run (minutes)</label><input type="number" step="5" value="${s.minutes??""}" onchange="EXPB.minutes=this.value"></div>
      <div><label>Runs at the same time</label><input type="number" min="1" value="${s.concurrency}" onchange="EXPB.concurrency=+this.value"></div></div>
    <details style="margin-top:8px"><summary><b>All settings</b> <span class="muted small">— applied to every run on top of its preset (${Object.keys(s.overrides).length} set)</span></summary>
      ${allSettingsBox("xb", META.presets.find(p=>p.name==="full").config)}
      ${Object.keys(s.overrides).length?`<p class="muted small">Set in this plan: <code>${esc(Object.entries(s.overrides).map(([k,v])=>`${k}=${JSON.stringify(v)}`).join(", "))}</code></p>`:""}</details></div>
  <div class="card"><h3>7 · Pre-registered tests</h3>
    <label style="color:var(--ink);font-size:13px"><input type="radio" name="xb-h" style="width:auto" ${hypo==="default"?"checked":""} onchange="EXPB.hypotheses='default';renderBuilder()"> the paper's tests, generated from the setups and policy settings (H1 review loop, H2 knowledge graph, H3 policy control, H4 paraphrase, H5 single call)</label>
    <label style="color:var(--ink);font-size:13px"><input type="radio" name="xb-h" style="width:auto" ${hypo==="custom"?"checked":""} onchange="fixTests()"> a fixed list I can edit (for the pre-registration)</label>
    ${hypo==="custom"?`<textarea id="xb-tests" rows="10" class="mono" onchange="setTests(this.value)">${esc(testsText(s.hypotheses))}</textarea><p class="muted small">One test per line as JSON: {"id", "family", "measure", "a", "b", "test": superiority | non_inferiority | equivalence | above | below | share_below, "margin", "better"}.</p>`:""}</div>
  <div class="card"><div class="row"><button onclick="saveBuilder()">Save and check</button><button class="primary" onclick="saveBuilder(true)">Save and start</button>
    ${info&&info.running?`<button onclick="stopExp()">Stop</button>`:""}${info&&info.has_report?`<button onclick="showExperiment('${esc(s.name)}')">Open the report</button>`:""}
    <button class="small" onclick="editPlanYaml()">Edit as YAML</button><span class="muted small" id="xb-msg"></span></div><div id="xb-info">${info?infoHTML(info):""}</div></div>`;
  if(info && info.running) setTimeout(pollExp, 5000);
}
function infoHTML(i){
  const pct = i.jobs ? Math.round(100*(i.done||0)/i.jobs) : 0;
  return `<p class="small" style="margin-top:10px"><b>${i.jobs} runs</b> = ${i.items.length} text${i.items.length===1?"":"s"} × ${i.conditions.length} conditions (${i.conditions.map(esc).join(", ")}) × ${i.models.length} writer${i.models.length===1?"":"s"}, with the samples per text; ${i.tests} pre-registered test${i.tests===1?"":"s"}. ${i.done||0} done (${pct}%)${i.running?" — running":""}.</p>
    <div style="height:6px;background:var(--line);border-radius:4px"><div style="height:6px;width:${pct}%;background:var(--accent,#2a6);border-radius:4px"></div></div>
    ${(i.log||[]).length?`<pre class="mono small" style="max-height:180px;overflow:auto;margin-top:8px">${esc(i.log.join("\n"))}</pre>`:""}`;
}
function toggleIn(arr, v, on){ const i = arr.indexOf(v); if(on && i<0) arr.push(v); if(!on && i>=0) arr.splice(i,1); }
function togglePol(i, p, on){ const c = EXPB.conditions[i]; const all = Object.keys(EXPB.policies); let cur = c.policies ? [...c.policies] : [...all];
  toggleIn(cur, p, on); c.policies = cur.length===all.length ? null : cur; }
function addPolicy(){ let n = "setting"+(Object.keys(EXPB.policies).length+1); EXPB.policies[n] = {all:"preserve"}; renderBuilder(); }
function renamePolicy(old, nw){ nw = nw.trim(); if(!nw || nw===old) return; EXPB.policies[nw] = EXPB.policies[old]; delete EXPB.policies[old];
  EXPB.conditions.forEach(c=>{ if(c.policies) c.policies = c.policies.map(p=>p===old?nw:p); }); renderBuilder(); }
function testsText(h){ return (Array.isArray(h)?h:[]).map(t=>JSON.stringify(t)).join("\n"); }
function setTests(txt){ try{ EXPB.hypotheses = txt.split("\n").map(l=>l.trim()).filter(Boolean).map(l=>JSON.parse(l)); $("#xb-msg").textContent=""; }
  catch(e){ $("#xb-msg").textContent = "a test line is not valid JSON: "+e.message; } }
async function fixTests(){
  const conds = Object.fromEntries(EXPB.conditions.map(c=>[c.name, c.preset]));
  try{ const r = await api("/api/experiment-plans/default-tests", {method:"POST", headers:{"content-type":"application/json"}, body: JSON.stringify({conditions: conds, policies: EXPB.policies, margins: EXPB.margins||{}})});
    EXPB.hypotheses = r.hypotheses; renderBuilder(); }catch(e){ toast(e.message); }
}
async function uploadExpTexts(){
  const f = $("#xb-files").files; if(!f.length){ toast("Choose one or more text files first."); return; }
  const fd = new FormData(); [...f].forEach(x=>fd.append("files", x));
  try{ const r = await api(`/api/experiment-plans/${encodeURIComponent(EXPB.name)}/inputs`, {method:"POST", body: fd});
    if(!EXPB.inputs.includes(r.glob)) EXPB.inputs = [...EXPB.inputs.filter(g=>g!==`inputs/${EXPB.name}/*.txt`), r.glob];
    toast(`${r.saved.length} text${r.saved.length===1?"":"s"} saved`); renderBuilder(); }catch(e){ toast(e.message); }
}
async function saveBuilder(start){
  const msg = $("#xb-msg"); Object.assign(EXPB.overrides, readAllSettings("xb"));
  try{
    const r = await api("/api/experiment-plans", {method:"POST", headers:{"content-type":"application/json"}, body: JSON.stringify({name: EXPB.name, plan: planFromState(EXPB)})});
    EXPB.__info = r; if(msg) msg.textContent = "saved";
    if(start){ await api(`/api/experiment-plans/${encodeURIComponent(EXPB.name)}/start`, {method:"POST"}); toast("Experiment started"); EXPB.__info.running = true; }
    renderBuilder(); loadExperimentPlans();
  }catch(e){ if(msg) msg.textContent = e.message; toast(e.message); }
}
async function pollExp(){
  if(!EXPB || !$("#xb-info")) return;
  try{ const r = await api(`/api/experiment-plans/${encodeURIComponent(EXPB.name)}`); EXPB.__info = r; $("#xb-info").innerHTML = infoHTML(r);
    if(r.running) setTimeout(pollExp, 5000); else { loadExperimentPlans(); if(typeof loadExperiments==="function") loadExperiments(); renderBuilder(); } }catch(e){}
}
async function stopExp(){ try{ await api(`/api/experiment-plans/${encodeURIComponent(EXPB.name)}/stop`, {method:"POST"}); toast("stopping"); setTimeout(pollExp, 1000); }catch(e){ toast(e.message); } }
async function editPlanYaml(){
  let text = "";
  try{ text = (await api(`/api/experiment-plans/${encodeURIComponent(EXPB.name)}`)).yaml; }catch(e){ text = "# save the plan first, or paste a plan here\n"; }
  modal(`experiments/${esc(EXPB.name)}.yaml`, `<textarea id="xb-yaml" rows="28" class="mono" style="width:100%">${esc(text)}</textarea>
    <div class="row" style="margin-top:8px"><button class="primary" onclick="saveYaml()">Save</button><span class="muted small" id="xb-ymsg"></span></div>`);
}
async function saveYaml(){
  try{ const r = await api("/api/experiment-plans", {method:"POST", headers:{"content-type":"application/json"}, body: JSON.stringify({name: EXPB.name, yaml: $("#xb-yaml").value})});
    closeModal(); await showBuilder(EXPB.name); toast(`saved: ${r.jobs} runs`); }catch(e){ $("#xb-ymsg").textContent = e.message; }
}
