// The model library in the interface: every model is described once (Models & keys), then chosen by
// name wherever a task needs one (writer, analysis, judges, experiment writers). Uses the helpers of
// index.html ($, esc, api, toast, modal, closeModal, showKeys).

let MODELS = [];          // the library, from /api/models
async function loadModels(){ try{ MODELS = (await api("/api/models")).models; }catch(e){ MODELS = []; } return MODELS; }
function modelEntry(alias){ return MODELS.find(m=>m.alias===alias); }
function modelLabel(ref){
  if(!ref) return "";
  if(typeof ref==="object") ref = ref.use || ref.name;
  const m = modelEntry(ref); return m ? m.label : ref;
}
function _modelOpt(m, sel){ return `<option value="${esc(m.alias)}" ${m.alias===sel?"selected":""}>${esc(m.label)}${m.key_ready?"":" — needs a key"}</option>`; }

// A model chooser: a select over the library, grouped, with "the writer's model" (when allowed) and
// "another model id…" for a model not in the library. `cur` is a library name, a LiteLLM id or "".
function modelPicker(id, cur, {same=false, sameLabel="same as the writer", onchange="", cls=""}={}){
  const inLib = cur && modelEntry(cur);
  const custom = cur && !inLib;
  const api_ = MODELS.filter(m=>m.kind!=="local"), local = MODELS.filter(m=>m.kind==="local");
  return `<div class="mpick ${cls}" data-picker="${esc(id)}">
    <select id="${esc(id)}" onchange="pickerChanged('${esc(id)}');${onchange}">
      ${same?`<option value="" ${!cur?"selected":""}>${esc(sameLabel)}</option>`:""}
      ${api_.length?`<optgroup label="Through an API">${api_.map(m=>_modelOpt(m, cur)).join("")}</optgroup>`:""}
      ${local.length?`<optgroup label="On this computer or your own server">${local.map(m=>_modelOpt(m, cur)).join("")}</optgroup>`:""}
      <option value="__custom" ${custom?"selected":""}>another model id…</option>
    </select>
    <input id="${esc(id)}-custom" class="mono" placeholder="provider/model, e.g. openai/gpt-…" value="${custom?esc(cur):""}" style="${custom?"":"display:none"}" onchange="${onchange}">
    <div class="mnote" id="${esc(id)}-note">${pickerNote(inLib?cur:"")}</div></div>`;
}
function pickerNote(alias){
  const m = modelEntry(alias); if(!m) return "";
  const bits = [m.name, m.api_base?`at ${m.api_base}`:"", m.reasoning_effort?`reasoning ${m.reasoning_effort}`:"",
                m.context_window?`${Math.round(m.context_window/1000)}k context`:""].filter(Boolean);
  return `<span class="muted">${esc(bits.join(" · "))}</span>${m.key_ready?"":` <a href="#" class="warn" onclick="showKeys();return false">set the ${esc(m.provider)} key</a>`}
    <a href="#" onclick="editModel('${esc(m.alias)}');return false">edit</a>`;
}
function pickerChanged(id){
  const s = $("#"+CSS.escape(id)); const c = $("#"+CSS.escape(id+"-custom")); const n = $("#"+CSS.escape(id+"-note"));
  if(c) c.style.display = s.value==="__custom" ? "" : "none";
  if(n) n.innerHTML = pickerNote(s.value);
}
// The picker's value: a library name, a model id, or "" (the default / same as the writer).
function pickerValue(id){
  const s = $("#"+CSS.escape(id)); if(!s) return undefined;
  if(s.value==="__custom") return ($("#"+CSS.escape(id+"-custom")).value||"").trim();
  return s.value;
}
// Overrides for a role from a picker value: a library entry by name, else a raw model id.
function roleOverrides(role, v, ov){
  if(v===undefined) return ov;
  if(!v){ return ov; }
  if(modelEntry(v)){ ov[`models.${role}.use`] = v; }
  else { ov[`models.${role}.name`] = v; ov[`models.${role}.use`] = null; }
  return ov;
}
function roleRef(cfg, role){ const m = (cfg.models||{})[role]; if(!m) return ""; return m.use || m.name || ""; }

// Several models at once (further judges, experiment writers): toggle chips.
function modelChips(id, selected, {exclude=[]}={}){
  const sel = new Set((selected||[]).map(x=>typeof x==="object"?(x.use||x.name):x));
  const extra = [...sel].filter(x=>!modelEntry(x));
  return `<div class="mchips" id="${esc(id)}">${MODELS.filter(m=>!exclude.includes(m.alias)).map(m=>`<label class="mchip ${sel.has(m.alias)?"on":""}" title="${esc(m.name)}${m.key_ready?"":" — needs a key"}"><input type="checkbox" value="${esc(m.alias)}" ${sel.has(m.alias)?"checked":""} onchange="this.parentElement.classList.toggle('on',this.checked)"> ${esc(m.label)}${m.key_ready?"":' <span class="warn">·key</span>'}</label>`).join("")}
    ${extra.map(x=>`<label class="mchip on"><input type="checkbox" value="${esc(x)}" checked onchange="this.parentElement.classList.toggle('on',this.checked)"> ${esc(x)}</label>`).join("")}</div>`;
}
function chipsValue(id){ return [...document.querySelectorAll(`#${CSS.escape(id)} input:checked`)].map(x=>x.value); }

// ------------------------------------------------------------------ the library manager
async function showModels(){
  await loadModels();
  const rows = MODELS.map(m=>`<tr><td><b>${esc(m.label)}</b><div class="muted small mono">${esc(m.alias)}</div></td>
      <td class="small mono">${esc(m.name)}${m.api_base?`<div class="muted">${esc(m.api_base)}</div>`:""}</td>
      <td class="small">${[m.reasoning_effort?`reasoning ${m.reasoning_effort}`:"", m.context_window?`${Math.round(m.context_window/1000)}k context`:"", m.max_output_tokens?`${m.max_output_tokens} out`:"", m.max_concurrency?`${m.max_concurrency} at once`:""].filter(Boolean).map(esc).join("<br>")}</td>
      <td class="small">${m.key_ready?'<span class="good">ready</span>':`<a href="#" class="warn" onclick="showKeys();return false">set ${esc(m.provider)} key</a>`}<div class="muted">${esc(m.source)}</div></td>
      <td style="white-space:nowrap"><button class="small" onclick="testModel('${esc(m.alias)}', this)">Test</button> <button class="small" onclick="editModel('${esc(m.alias)}')">Edit</button>
        ${m.source!=="built-in"?`<button class="small" onclick="deleteModel('${esc(m.alias)}')">${m.source==="yours"?"Delete":"Reset"}</button>`:""}</td></tr>`).join("");
  modal("Models", `<p>Describe each model <b>once</b> here: its id, where it runs, how much it reasons, its limits and price. Then choose it by name for any task — the writer, the analysis, the judges, the writers of an experiment. What belongs to a task (the analysis' low temperature, the judges' temperature 0) is set by the task, not here. The list is kept on this computer in <code>${esc((await api("/api/models")).file)}</code>; a run keeps a copy of the settings it was made with.</p>
    <div class="row" style="margin:8px 0"><button class="primary small" onclick="editModel()">Add a model</button><button class="small" onclick="showKeys()">API keys and addresses</button></div>
    <table class="small"><tr><th>model</th><th>id and address</th><th>settings</th><th>status</th><th></th></tr>${rows}</table>
    <div id="mtest"></div>`);
}
const MFIELDS = [
  ["label","Name shown","text","e.g. Mistral Large 4"],
  ["name","LiteLLM model id","text","provider/model, e.g. mistral/mistral-large-4-0, ollama_chat/gemma4:e4b, hosted_vllm/<model>"],
  ["kind","Where it runs","choice",["api","local"]],
  ["api_base","Address of a self-hosted server","text","e.g. http://localhost:11434 (Ollama) or http://host:8000/v1 (vLLM); empty for an API"],
  ["reasoning_effort","Reasoning effort (reasoning models)","choice",["","low","medium","high"]],
  ["reasoning_max_tokens","Most reasoning per call (tokens; OpenRouter, Anthropic)","int","empty = provider default; e.g. 4000"],
  ["context_window","Context window (tokens)","int","200000"],
  ["max_output_tokens","Longest answer (tokens; 0 = no limit of our own, within the run's budget)","int","8000"],
  ["max_concurrency","Calls at the same time","int","4"],
  ["timeout_s","Seconds before a call is abandoned","int","600"],
  ["rpm","Requests per minute (empty = no limit)","int",""],
  ["input_cost_per_mtok","Price per million input tokens (USD; empty = LiteLLM's table, 0 for local)","float",""],
  ["output_cost_per_mtok","Price per million output tokens (USD)","float",""],
  ["notes","Notes","text",""],
];
function editModel(alias){
  const m = alias ? (modelEntry(alias)||{}) : {kind:"api"};
  modal(alias?`Edit model: ${esc(m.label||alias)}`:"Add a model", `
    <label>Short name <span class="muted" style="font-weight:400">(how settings and experiment plans refer to it)</span></label>
    <input id="me-alias" class="mono" value="${esc(alias||"")}" ${alias?"readonly":""} placeholder="e.g. mistral-large-4">
    <div class="grid2">${MFIELDS.map(([k,l,t,ph])=>`<div><label>${esc(l)}</label>${t==="choice"?`<select id="me-${k}">${ph.map(o=>`<option value="${o}" ${(m[k]||"")===o?"selected":""}>${o||"default"}</option>`).join("")}</select>`:`<input id="me-${k}" ${t==="int"||t==="float"?`type="number" step="${t==="int"?1:"any"}"`:""} value="${m[k]??""}" placeholder="${esc(ph)}">`}</div>`).join("")}</div>
    <div class="row" style="margin-top:12px"><button class="primary" onclick="saveModel()">Save</button><button onclick="saveModel(true)">Save and test</button><button onclick="showModels()">Back</button><span id="me-msg" class="muted small"></span></div>
    <div id="mtest"></div>`);
}
async function saveModel(test){
  const alias = $("#me-alias").value.trim(); const entry = {};
  MFIELDS.forEach(([k,l,t])=>{ const v = $(`#me-${k}`).value.trim(); if(v==="") return; entry[k] = (t==="int"||t==="float") ? +v : v; });
  try{ await api(`/api/models/${encodeURIComponent(alias)}`, {method:"PUT", headers:{"content-type":"application/json"}, body: JSON.stringify({entry})});
    await loadModels(); toast("saved"); if(test) await testModel(alias); else showModels(); refreshPickers(); }
  catch(e){ $("#me-msg").textContent = e.message; }
}
async function deleteModel(alias){ try{ await api(`/api/models/${encodeURIComponent(alias)}`, {method:"DELETE"}); await loadModels(); showModels(); refreshPickers(); }catch(e){ toast(e.message); } }
async function testModel(alias, btn){
  const box = $("#mtest"); if(box) box.innerHTML = `<p class="muted small">Asking ${esc(modelLabel(alias))} to reply "OK"…</p>`;
  if(btn) btn.disabled = true;
  try{ const r = await api(`/api/models/${encodeURIComponent(alias)}/test`, {method:"POST"});
    const res = (r.results||[])[0]||{};
    if(box) box.innerHTML = r.ok ? `<div class="pf ok"><b>${esc(modelLabel(alias))}</b> answered in ${res.seconds}s.</div>` : (r.problems||[]).map(p=>`<div class="pf error"><b>${esc(modelLabel(alias))}</b> ${esc(p.message)}<div class="muted small">${esc(p.hint||"")}</div></div>`).join(""); }
  catch(e){ if(box) box.innerHTML = `<div class="pf error">${esc(e.message)}</div>`; }
  if(btn) btn.disabled = false;
}
// Re-render pickers on the page after the library changed (keeps their values).
function refreshPickers(){
  document.querySelectorAll(".mpick").forEach(p=>{ const id = p.dataset.picker; const v = pickerValue(id);
    const sel = $("#"+CSS.escape(id)); const same = !!sel.querySelector('option[value=""]');
    const label = same ? sel.querySelector('option[value=""]').textContent : undefined;
    const onch = (sel.getAttribute("onchange")||"").replace(`pickerChanged('${id}');`, "");
    p.outerHTML = modelPicker(id, v, {same, sameLabel: label, onchange: onch}); });
}
