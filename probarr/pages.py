"""Standalone web pages that are not tied to a single run."""
from .theme import CSS, topbar

WANTLIST_EXTRA = """
.page{max-width:1000px;margin:18px auto;padding:0 16px 60px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
  padding:14px 16px;margin-bottom:14px}
.card h2{margin:0 0 4px;font-size:16px}
.card .lead{color:var(--dim);font-size:12.5px;margin-bottom:12px}
.stepnum{display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;
  border-radius:50%;background:var(--accent2);color:#04222c;font-weight:700;font-size:12px;
  margin-top:16px;vertical-align:middle}
.stephead{display:inline-block;margin:16px 0 4px 8px;font-size:14px;vertical-align:middle}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
textarea{width:100%;min-height:260px;background:var(--bg);color:var(--text);
  border:1px solid var(--line);border-radius:var(--radius);padding:10px 12px;
  font:12.5px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;resize:vertical}
input[type=text]{background:var(--bg);color:var(--text);border:1px solid var(--line);
  border-radius:var(--radius);padding:6px 9px;font-size:13px;min-width:220px}
.split{display:grid;grid-template-columns:1fr 340px;gap:14px;align-items:start}
@media(max-width:820px){.split{grid-template-columns:1fr}}
.preview{background:var(--bg2);border:1px solid var(--line);border-radius:var(--radius);
  padding:10px 12px;max-height:420px;overflow:auto}
.preview h3{margin:0 0 8px;font-size:12px;text-transform:uppercase;letter-spacing:.5px;
  color:var(--faint)}
.prow{display:flex;gap:8px;font-size:12.5px;padding:3px 0;border-bottom:1px solid rgba(255,255,255,.04)}
.prow .n{color:var(--faint);min-width:34px;font-variant-numeric:tabular-nums}
.prow .t{color:var(--faint);font-size:11px}
.warn{background:rgba(240,173,78,.1);border:1px solid var(--warn);color:var(--warn);
  border-radius:var(--radius);padding:8px 10px;font-size:12px;margin-bottom:8px}
.warn b{color:var(--warn)}
.ok{color:var(--ok)}
.saved{display:flex;gap:10px;align-items:center;padding:9px 0;
  border-bottom:1px solid rgba(255,255,255,.05);font-size:13px}
.saved:last-child{border-bottom:0}
.saved .nm{flex:1;font-weight:600}
.saved .meta{color:var(--faint);font-size:11.5px}
.cmd{background:var(--bg);border:1px solid var(--line);border-radius:var(--radius);
  padding:9px 11px;font:12px/1.6 ui-monospace,Menlo,Consolas,monospace;color:var(--dim);
  overflow-x:auto;white-space:pre;margin-top:8px}
.cmd b{color:var(--accent)}
.muted{color:var(--faint);font-size:12px}
.modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:150;
  align-items:center;justify-content:center}
.modal.on{display:flex}
.modalbox{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
  width:460px;max-width:92vw;max-height:88vh;overflow-y:auto;padding:18px 20px;position:relative}
.modalbox h3{margin:0 0 4px;font-size:16px}
.modalx{position:absolute;top:12px;right:14px;background:none;border:0;
  color:var(--faint);font-size:15px;cursor:pointer;padding:2px 4px}
.modalx:hover{color:var(--text)}
.modalbox .sub{color:var(--dim);font-size:12px;margin-bottom:14px}
.mfield select{width:100%;background:var(--bg);color:var(--text);border:1px solid var(--line);
  border-radius:var(--radius);padding:7px 9px;font-size:13px}
.mrow{display:flex;gap:8px;justify-content:flex-end;margin-top:16px}
.mresult{margin-top:14px;padding:10px 12px;border-radius:var(--radius);font-size:12.5px;
  display:none}
.mresult.show{display:block}
.mresult.good{background:rgba(39,194,76,.1);border:1px solid var(--ok)}
.mresult.bad{background:rgba(240,80,80,.1);border:1px solid var(--bad)}
.cat-results{max-height:300px;overflow:auto;display:flex;flex-direction:column;gap:4px}
.cat-hit{display:flex;gap:9px;align-items:center;padding:6px 8px;background:var(--bg2);
  border:1px solid var(--line);border-radius:var(--radius);cursor:pointer}
.cat-hit .k{font-weight:600;flex:1}
"""

WANTLIST_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>probarr &middot; wantlists</title><style>__CSS____EXTRA__</style></head><body>

__TOPBAR__

<div class="page">

  <div class="card">
    <h2>What a wantlist is for</h2>
    <div class="lead">
      A wantlist is the set of channels you actually want. probarr only probes
      candidate streams for these &mdash; on a provider listing tens of thousands of
      streams that is the difference between a run that finishes and one that
      does not. It also decides the channel numbers and names in your exported
      playlist.
    </div>

    <div class="stepnum">1</div>
    <h3 class="stephead">Get channel names into the editor</h3>
    <div class="lead" style="margin-top:0">Pick whichever of these matches what you have.
      They all add to the editor below rather than replacing it, so more than one can be
      combined &mdash; e.g. browse your provider first, then top up from an EPG.</div>
    <div class="row" style="margin-top:8px">
      <a href="/browse"><button class="primary">Browse a provider's channels</button></a>
      <span class="muted">no typing, no probing &mdash; tick names from what your provider actually lists</span>
    </div>
    <div class="row" style="margin-top:8px">
      <button id="epgimportopen">Import channels from an EPG source&hellip;</button>
      <span class="muted">tick names from a guide someone else already keeps current</span>
    </div>
    <div class="row" style="margin-top:8px">
      <select id="starterselect" style="width:auto"><option value="">Load a starter lineup&hellip;</option></select>
      <span class="muted">Real channel numbering, ready to import &mdash; free-to-air only for now.</span>
    </div>
    <div class="row" style="margin-top:8px">
      <button id="loadtpl">Load the blank template</button>
      <label class="muted" style="display:flex;gap:6px;align-items:center">
        <input type="file" id="file" accept=".txt,.m3u,text/plain" style="display:none">
        <button id="pick">Import a file&hellip;</button>
      </label>
      <span class="muted" id="fileinfo"></span>
      <a href="/wantlists/template.txt" download="probarr-wantlist.txt" style="font-size:12px">
        or just download it to edit by hand&hellip;</a>
    </div>

    <div class="stepnum">2</div>
    <h3 class="stephead">Then enrich it <span class="muted" style="font-weight:400">(optional)</span></h3>
    <div class="lead" style="margin-top:0">An EPG has no channel numbers or categories &mdash;
      this cross-references whatever's now in the editor against a real broadcaster lineup
      (e.g. Sky UK) to fill in what's missing, without touching anything already set.</div>
    <div class="row" style="margin-top:8px">
      <button id="enrichopen">Fill in numbers &amp; groups from a reference lineup&hellip;</button>
    </div>
  </div>

  <div class="modal" id="enrichmodal">
    <div class="modalbox" style="width:min(560px,94vw)">
      <button class="modalx" id="enrich-x" title="Close">&#10005;</button>
      <h3>Fill in numbers &amp; groups from a reference lineup</h3>
      <div class="sub">Known lineups are pulled from the
        <a href="https://github.com/PiratesIRC/Dispatcharr-Lineuparr-Plugin/tree/main/Lineuparr"
           target="_blank" rel="noopener">Lineuparr project</a> &mdash; fetched fresh each time,
        nothing stored here.</div>
      <div class="row" style="margin:10px 0">
        <select id="enrich-select" style="flex:1"></select>
        <button id="enrich-refresh" title="Re-fetch the list from GitHub">Refresh list</button>
      </div>
      <div class="mfield" id="enrich-url-row" style="margin:10px 0; display:none">
        <input type="text" id="enrich-url" style="width:100%"
          placeholder="https://raw.githubusercontent.com/.../lineup.json">
      </div>
      <div class="mresult" id="enrich-result"></div>
      <div class="mrow" style="flex-wrap:wrap;gap:8px 16px;align-items:center;justify-content:space-between">
        <div style="flex:1;min-width:220px">
          <b>Apply to editor</b> &mdash; matches by name against the channels
          already in the editor below; only fills a number or group that's
          currently blank, everything else is left alone.
        </div>
        <button id="enrich-go">Apply to editor</button>
      </div>
      <div class="mrow" style="flex-wrap:wrap;gap:8px 16px;align-items:center;justify-content:space-between;margin-top:10px">
        <div style="flex:1;min-width:220px">
          <b>Load channels from this lineup</b> &mdash; skips any EPG entirely
          and builds the list straight from the lineup's own names, numbers
          and groups. Best when your EPG's names don't textually resemble
          the lineup's (e.g. Sky's abbreviated on-screen guide text) &mdash;
          probarr's own stream matching handles the real-world naming
          variance from here. <b>Replaces</b> whatever's in the editor.
        </div>
        <button class="primary" id="enrich-load">Load channels</button>
      </div>
      <div class="mrow" style="margin-top:14px">
        <button id="enrich-close">Close</button>
      </div>
    </div>
  </div>

  <div class="modal" id="epgimportmodal">
    <div class="modalbox" style="width:min(640px,94vw)">
      <button class="modalx" id="epgimp-x" title="Close">&#10005;</button>
      <h3>Import channels from an EPG source</h3>
      <div class="sub">Every DISTINCT channel one of your saved EPG sources
        declares &mdash; an SD/HD pair like "BBC One" / "BBC One HD" is
        folded into one row (the plain name), the same way probarr already
        treats them as one channel everywhere else; a real regional variant
        like "BBC One London" keeps its own row. Tick what you want &mdash;
        ticked channels are appended to the editor as
        <code>name | tvg-id</code> lines, keeping whatever's already there.
        XMLTV carries no group/category data, so there's no per-group tick
        here &mdash; just search and select/deselect all.</div>
      <div class="mfield" style="margin-bottom:8px">
        <select id="epgimp-src" style="width:100%"></select>
      </div>
      <div class="row" style="margin-bottom:8px">
        <input type="text" id="epgimp-newname" placeholder="new source name" style="width:140px">
        <input type="text" id="epgimp-newurl" placeholder="XMLTV URL (.xml or .xml.gz)" style="flex:1">
        <button id="epgimp-newsave">Add source</button>
      </div>
      <div class="row" style="margin-bottom:8px">
        <input type="text" id="epgimp-q" placeholder="Filter&hellip;" style="flex:1">
        <button class="togg" id="epgimp-all">select all</button>
        <button class="togg" id="epgimp-none">select none</button>
        <span class="muted" id="epgimp-count"></span>
      </div>
      <div id="epgimp-list" class="cat-results" style="max-height:360px"></div>
      <div class="mresult" id="epgimp-result"></div>
      <div class="mrow">
        <button id="epgimp-close">Close</button>
        <button class="primary" id="epgimp-add" disabled>Add ticked to editor</button>
      </div>
    </div>
  </div>

  <div class="card">
    <h2>Create or edit</h2>
    <div class="lead">Paste a list, import a file, or start from the template.
      The preview updates as you type so you can see exactly what probarr
      understood before saving.</div>
    <div class="row" style="margin-bottom:10px">
      <input type="text" id="name" placeholder="wantlist name, e.g. uk-lineup">
      <button class="primary" id="save">Save</button>
      <span id="savemsg" class="muted"></span>
    </div>
    <div class="split">
      <textarea id="text" spellcheck="false"
        placeholder="101: BBC One&#10;102: BBC Two&#10;BBC Four"></textarea>
      <div class="preview" id="preview"></div>
    </div>
  </div>

  <div class="card">
    <h2>Saved wantlists</h2>
    <div id="saved"></div>
  </div>

</div>

<script>
const $ = id => document.getElementById(id);
let debounce = null;

async function preview(){
  const text = $("text").value;
  if(!text.trim()){ $("preview").innerHTML =
    '<h3>Preview</h3><div class="muted">Nothing to parse yet.</div>'; return; }
  try{
    const r = await fetch("/api/wantlists/preview", {method:"POST",
      headers:{"Content-Type":"application/json"}, body:JSON.stringify({text})});
    const d = await r.json();
    const warns = (d.warnings||[]).map(w =>
      '<div class="warn">Line <b>'+w.line+'</b>: '+esc(w.problem)+
      '<br><span class="muted">'+esc(w.text)+'</span></div>').join("");
    const rows = (d.channels||[]).map(c =>
      '<div class="prow"><span class="n">'+(c.number!=null?c.number:"&mdash;")+'</span>'+
      '<span style="flex:1">'+esc(c.name)+
        (c.group?' <em class="muted">'+esc(c.group)+'</em>':'')+'</span>'+
      '<span class="t">'+esc(c.key)+'</span></div>').join("");
    $("preview").innerHTML = '<h3>Preview &mdash; <span class="ok">'+
      (d.channels||[]).length+' channels</span></h3>' + warns + rows;
  }catch(e){
    $("preview").innerHTML='<h3>Preview</h3><div class="warn">Preview failed.</div>';
  }
}
function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;")
  .replace(/>/g,"&gt;").replace(/"/g,"&quot;");}

$("text").addEventListener("input", ()=>{ clearTimeout(debounce);
  debounce=setTimeout(preview,250); });

$("pick").addEventListener("click", e=>{ e.preventDefault(); $("file").click(); });
$("file").addEventListener("change", async ()=>{
  const f = $("file").files[0]; if(!f) return;
  // Read client-side and post as plain text. Avoids multipart entirely, which
  // keeps the server on the standard library with no upload parsing.
  const text = await f.text();
  $("text").value = text;
  $("fileinfo").textContent = f.name + " (" + Math.round(f.size/1024) + " KB)";
  if(!$("name").value) $("name").value = f.name.replace(/\.[^.]+$/, "");
  preview();
});
$("loadtpl").addEventListener("click", async ()=>{
  const r = await fetch("/wantlists/template.txt");
  $("text").value = await r.text();
  if(!$("name").value) $("name").value = "my-lineup";
  preview();
});
(async ()=>{
  const d = await (await fetch("/api/wantlists/starters")).json();
  $("starterselect").innerHTML = '<option value="">Load a starter lineup&hellip;</option>' +
    d.starters.map(s => '<option value="'+esc(s.name)+'">'+esc(s.label)+'</option>').join("");
})();
$("starterselect").addEventListener("change", async ()=>{
  const name = $("starterselect").value;
  if(!name) return;
  const r = await fetch("/wantlists/starter/"+encodeURIComponent(name)+".txt");
  $("text").value = await r.text();
  if(!$("name").value) $("name").value = name;
  $("starterselect").value = "";
  preview();
});

// --- Import channels from an EPG source ---------------------------------
// The bulk counterpart to Check EPG's search: instead of checking one
// channel against a guide, build a whole wantlist FROM one -- reusing a
// guide someone else already keeps current instead of hand-typing a list.
let EPGIMP_CHANNELS = [];
async function openEpgImport(){
  const d = await (await fetch("/api/epg-sources")).json();
  const sel = $("epgimp-src");
  sel.innerHTML = (d.epg_sources||[]).map(s =>
    '<option value="'+esc(s.name)+'">'+esc(s.name)+'</option>').join("") ||
    '<option value="">No EPG sources saved yet</option>';
  $("epgimportmodal").classList.add("on");
  if(d.epg_sources && d.epg_sources.length) loadEpgImportList();
}
async function loadEpgImportList(){
  const src = $("epgimp-src").value;
  const box = $("epgimp-list");
  box.innerHTML = '<div class="muted" style="padding:6px">loading&hellip;</div>';
  $("epgimp-add").disabled = true;
  if(!src) { box.innerHTML = ""; return; }
  try{
    const r = await fetch("/api/epg-list?source="+encodeURIComponent(src));
    const d = await r.json();
    if(d.error){ box.innerHTML = '<div class="muted" style="padding:6px">'+esc(d.error)+'</div>'; return; }
    EPGIMP_CHANNELS = d.channels || [];
  }catch(e){
    box.innerHTML = '<div class="muted" style="padding:6px">request failed</div>';
    return;
  }
  renderEpgImportList();
}
function renderEpgImportList(){
  const q = $("epgimp-q").value.trim().toLowerCase();
  const box = $("epgimp-list");
  const rows = EPGIMP_CHANNELS.filter(c => !q || c.guide_name.toLowerCase().includes(q) ||
    (c.alts||[]).some(a => a.guide_name.toLowerCase().includes(q)));
  box.innerHTML = rows.map(c => {
    // Regional variants (alts) share one row and one checkbox -- the
    // dropdown picks WHICH region's id/name the tick actually uses,
    // rather than making you tick through 15 near-identical rows to
    // find your own. The checkbox itself carries whichever is picked.
    const opts = c.alts ? [c, ...c.alts] : null;
    const picker = opts ? '<select class="epgimp-region" style="width:auto;margin-left:8px" '+
      'onclick="event.stopPropagation()">' + opts.map((o,i) =>
        '<option value="'+i+'" data-name="'+esc(o.guide_name)+'" data-id="'+esc(o.guide_id)+'">'+
        esc(o.guide_name)+'</option>').join("") + '</select>' : '';
    return '<div class="cat-hit" style="cursor:default">'+
      '<label style="display:flex;flex:1;gap:9px;align-items:center;cursor:pointer">'+
      '<input type="checkbox" class="epgimp-pick" '+
      'data-name="'+esc(c.guide_name)+'" data-id="'+esc(c.guide_id)+'">'+
      '<span class="k">'+esc(c.guide_name)+'</span></label>'+picker+'</div>';
  }).join("") || '<div class="muted" style="padding:6px">no channels match</div>';
  updateEpgImportCount();
}
function updateEpgImportCount(){
  const n = document.querySelectorAll(".epgimp-pick:checked").length;
  $("epgimp-count").textContent = n ? n+" ticked" : "";
  $("epgimp-add").disabled = !n;
}
$("epgimp-newsave").addEventListener("click", async () => {
  const name = $("epgimp-newname").value.trim(), url = $("epgimp-newurl").value.trim();
  if(!name || !url) return;
  $("epgimp-newsave").disabled = true; $("epgimp-newsave").textContent = "saving…";
  try{
    const r = await fetch("/api/epg-sources/"+encodeURIComponent(name), {method:"POST",
      headers:{"Content-Type":"application/json"}, body: JSON.stringify({url})});
    const d = await r.json();
    if(!r.ok || d.error){
      alert("Could not save: "+(d.error||"failed"));
    } else {
      $("epgimp-newname").value = ""; $("epgimp-newurl").value = "";
      await openEpgImport();          // refresh the source list
      $("epgimp-src").value = name;   // land on the one just added
      loadEpgImportList();
    }
  }catch(e){ alert("Request failed."); }
  $("epgimp-newsave").disabled = false; $("epgimp-newsave").textContent = "Add source";
});
$("epgimportopen").addEventListener("click", openEpgImport);
$("epgimp-x").addEventListener("click", () => $("epgimportmodal").classList.remove("on"));
$("epgimp-close").addEventListener("click", () => $("epgimportmodal").classList.remove("on"));
$("epgimp-src").addEventListener("change", loadEpgImportList);
$("epgimp-q").addEventListener("input", renderEpgImportList);
$("epgimp-list").addEventListener("change", e => {
  if(e.target.classList.contains("epgimp-pick")) updateEpgImportCount();
  if(e.target.classList.contains("epgimp-region")){
    const opt = e.target.selectedOptions[0];
    const cb = e.target.closest(".cat-hit").querySelector(".epgimp-pick");
    cb.dataset.name = opt.dataset.name;
    cb.dataset.id = opt.dataset.id;
    cb.nextElementSibling.textContent = opt.dataset.name;
  }
});
$("epgimp-all").addEventListener("click", () => {
  document.querySelectorAll(".epgimp-pick").forEach(x => x.checked = true);
  updateEpgImportCount();
});
$("epgimp-none").addEventListener("click", () => {
  document.querySelectorAll(".epgimp-pick").forEach(x => x.checked = false);
  updateEpgImportCount();
});
$("epgimp-add").addEventListener("click", () => {
  const picked = [...document.querySelectorAll(".epgimp-pick:checked")]
    .map(x => x.dataset.name+" | "+x.dataset.id);
  if(!picked.length) return;
  const cur = $("text").value;
  $("text").value = (cur && !cur.endsWith("\n") ? cur+"\n" : cur) + picked.join("\n") + "\n";
  preview();
  $("epgimportmodal").classList.remove("on");
});

// --- Fill in numbers/groups from a reference lineup ----------------------
async function loadEnrichSelect(force){
  const sel = $("enrich-select");
  sel.innerHTML = '<option value="">Loading&hellip;</option>';
  try{
    const r = await fetch("/api/wantlists/reference-lineups" + (force ? "?refresh=1" : ""));
    const d = await r.json();
    if(!r.ok || d.error){
      sel.innerHTML = '<option value="">Choose a lineup&hellip;</option>'+
        '<option value="__custom__">Custom URL&hellip;</option>';
      $("enrich-result").innerHTML = '<div class="warn">Could not list known lineups: '+
        esc(d.error||"failed")+' &mdash; use Custom URL instead.</div>';
      sel.value = "__custom__";
      $("enrich-url-row").style.display = "";
      return;
    }
    const byRegion = {};
    for(const item of d.lineups||[])
      (byRegion[item.region] = byRegion[item.region] || []).push(item);
    let html = '<option value="">Choose a lineup&hellip;</option>';
    for(const region of Object.keys(byRegion).sort()){
      html += '<optgroup label="'+esc(region)+'">';
      for(const item of byRegion[region])
        html += '<option value="'+esc(item.url)+'">'+esc(item.label)+'</option>';
      html += '</optgroup>';
    }
    html += '<option value="__custom__">Custom URL&hellip;</option>';
    sel.innerHTML = html;
  }catch(e){
    sel.innerHTML = '<option value="">Choose a lineup&hellip;</option>'+
      '<option value="__custom__">Custom URL&hellip;</option>';
  }
}
$("enrich-select").addEventListener("change", () => {
  const custom = $("enrich-select").value === "__custom__";
  $("enrich-url-row").style.display = custom ? "" : "none";
});
$("enrich-refresh").addEventListener("click", () => loadEnrichSelect(true));
$("enrichopen").addEventListener("click", () => {
  loadEnrichSelect(false);
  $("enrich-result").innerHTML = "";
  $("enrichmodal").classList.add("on");
});
$("enrich-x").addEventListener("click", () => $("enrichmodal").classList.remove("on"));
$("enrich-close").addEventListener("click", () => $("enrichmodal").classList.remove("on"));
// Shared by both actions below: resolve the dropdown selection to a real
// URL (falling back to the custom-URL field), or show the same "choose
// one" warning either way -- used to be copy-pasted into each handler.
function resolveEnrichUrl(){
  const sel = $("enrich-select").value;
  const url = sel === "__custom__" ? $("enrich-url").value.trim() : sel;
  if(!url) $("enrich-result").innerHTML =
    '<div class="warn">Choose a lineup, or pick "Custom URL…" and paste one.</div>';
  return url;
}
$("enrich-go").addEventListener("click", async () => {
  const url = resolveEnrichUrl();
  if(!url) return;
  $("enrich-go").disabled = true; $("enrich-go").textContent = "fetching…";
  try{
    const r = await fetch("/api/wantlists/enrich", {method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({url, text: $("text").value})});
    const d = await r.json();
    if(!r.ok || d.error){
      $("enrich-result").innerHTML = '<div class="warn">'+esc(d.error||"failed")+'</div>';
    } else {
      $("text").value = d.text;
      preview();
      let html = '<div class="ok">Matched '+d.matched+' of '+d.total+
        ' channels &mdash; editor updated.</div>';
      if((d.warnings||[]).length)
        html += '<div class="warn">'+d.warnings.length+' line(s) had a problem before '+
          'matching even ran:<br>'+d.warnings.map(esc).join('<br>')+'</div>';
      if((d.unmatched||[]).length)
        html += '<div class="muted" style="margin-top:6px">No match in this lineup for: '+
          d.unmatched.map(esc).join(', ')+
          (d.unmatched.length>=80 ? ' &hellip;' : '')+'</div>';
      $("enrich-result").innerHTML = html;
    }
  }catch(e){ $("enrich-result").innerHTML = '<div class="warn">Request failed.</div>'; }
  $("enrich-go").disabled = false; $("enrich-go").textContent = "Apply to editor";
});
$("enrich-load").addEventListener("click", async () => {
  const url = resolveEnrichUrl();
  if(!url) return;
  if($("text").value.trim() && !confirm("This replaces everything currently in the editor with this lineup's own channel list. Continue?")) return;
  $("enrich-load").disabled = true; $("enrich-load").textContent = "fetching…";
  try{
    const r = await fetch("/api/wantlists/from-reference", {method:"POST",
      headers:{"Content-Type":"application/json"}, body: JSON.stringify({url})});
    const d = await r.json();
    if(!r.ok || d.error){
      $("enrich-result").innerHTML = '<div class="warn">'+esc(d.error||"failed")+'</div>';
    } else {
      $("text").value = d.text;
      preview();
      $("enrich-result").innerHTML = '<div class="ok">Loaded '+d.count+
        ' channels straight from the lineup &mdash; editor replaced.</div>';
    }
  }catch(e){ $("enrich-result").innerHTML = '<div class="warn">Request failed.</div>'; }
  $("enrich-load").disabled = false; $("enrich-load").textContent = "Load channels";
});

$("save").addEventListener("click", async ()=>{
  const name=$("name").value.trim();
  if(!name){ $("savemsg").textContent="Give it a name first."; return; }
  $("savemsg").textContent="saving\u2026";
  const r = await fetch("/api/wantlists/"+encodeURIComponent(name),
    {method:"POST", headers:{"Content-Type":"application/json"},
     body:JSON.stringify({text:$("text").value})});
  const d = await r.json();
  $("savemsg").textContent = d.ok ? ("saved as "+d.name) : ("error: "+(d.error||"failed"));
  loadSaved();
});

async function loadSaved(){
  const r = await fetch("/api/wantlists"); const d = await r.json();
  if(!d.wantlists.length){ $("saved").innerHTML =
    '<div class="muted">None saved yet.</div>'; return; }
  $("saved").innerHTML = d.wantlists.map(w =>
    '<div class="saved"><span class="nm">'+esc(w.name)+'</span>'+
    '<span class="meta">'+w.channels+' channels</span>'+
    '<button data-edit="'+esc(w.name)+'">Edit</button>'+
    '<button data-del="'+esc(w.name)+'">Delete</button></div>').join("") +
    '<div class="muted" style="margin-top:12px">Use one in a run:</div>'+
    '<div class="cmd">docker exec probarr python3 -m probarr verify \\\n'+
    '  --source &lt;your m3u or xtream url&gt; \\\n'+
    '  --wantlist <b>'+esc(d.wantlists[0].name)+'</b> \\\n'+
    '  --epg &lt;xmltv url, optional&gt;</div>';
}
document.addEventListener("click", async e=>{
  const ed=e.target.closest("[data-edit]"), dl=e.target.closest("[data-del]");
  if(ed){
    const r=await fetch("/api/wantlists/"+encodeURIComponent(ed.dataset.edit));
    const d=await r.json();
    $("text").value=d.text||""; $("name").value=ed.dataset.edit; preview();
    window.scrollTo({top:0,behavior:"smooth"});
  }
  if(dl){
    if(!confirm("Delete wantlist \""+dl.dataset.del+"\"?")) return;
    await fetch("/api/wantlists/"+encodeURIComponent(dl.dataset.del)+"/delete",
      {method:"POST"});
    loadSaved();
  }
});

loadSaved(); preview();
</script></body></html>
"""


def wantlist_page():
    return (WANTLIST_PAGE
            .replace("__TOPBAR__", topbar("wantlists", active="wantlists"))
            .replace("__CSS__", CSS).replace("__EXTRA__", WANTLIST_EXTRA))


SETTINGS_EXTRA = WANTLIST_EXTRA + """
.dectbl{border-collapse:collapse;font-size:12.5px;margin-top:8px;min-width:380px}
.dectbl th,.dectbl td{text-align:left;padding:5px 12px 5px 0;
  border-bottom:1px solid var(--line)}
.dectbl th{color:var(--faint);font-weight:600;font-size:11px;
  text-transform:uppercase;letter-spacing:.4px}
.dectbl td:nth-child(2),.dectbl td:nth-child(3){font-variant-numeric:tabular-nums}
.field{display:flex;gap:12px;align-items:flex-start;padding:11px 0;
  border-bottom:1px solid rgba(255,255,255,.05)}
.field:last-child{border-bottom:0}
.field .lab{width:190px;flex:none;font-size:13px;font-weight:600;padding-top:5px}
.field .ctl{flex:1}
.field .help{color:var(--dim);font-size:12px;margin-top:4px;max-width:620px}
.field input[type=number]{width:110px}
.field input[type=text]{width:100%;max-width:560px}
.rate{background:var(--bg2);border:1px solid var(--line);border-radius:var(--radius);
  padding:10px 12px;margin-top:10px;font-size:12.5px;color:var(--dim)}
.rate b{color:var(--accent)}
.danger{color:var(--warn)}
"""

SETTINGS_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>probarr &middot; settings</title><style>__CSS____EXTRA__</style></head><body>

__TOPBAR__

<div class="page">
  <div class="card">
    <h2>Probing</h2>
    <div class="lead">These apply to new runs and to re-probing a single stream
      from the curation view.</div>

    <div class="field">
      <div class="lab">Streams at once</div>
      <div class="ctl">
        <input type="number" id="concurrency" min="1" max="16">
        <div class="help">
          Set this to how many simultaneous connections <b>your provider
          allows</b>, leaving one spare for whoever is actually watching
          television. A three-stream account probes roughly three times faster
          than a one-stream account.
          <br><br>
          <span class="danger">Setting it higher than your allowance does not
          fail cleanly.</span> An over-limit provider returns small, plausible
          error responses that are indistinguishable from a dead stream, so the
          run completes and quietly marks working channels as broken. When in
          doubt, leave it at 1.
        </div>
        <div class="rate" id="rate"></div>
      </div>
    </div>

    <div class="field">
      <div class="lab">Gap between probes</div>
      <div class="ctl"><input type="number" id="gap_seconds" min="0" max="10" step="0.1">
        <div class="help">Seconds to pause between serial probes. Ignored when
          probing more than one stream at once.</div></div>
    </div>

    <div class="field">
      <div class="lab">Sample length</div>
      <div class="ctl"><input type="number" id="sample_seconds" min="3" max="60">
        <div class="help">Seconds of video decoded per stream. Longer finds
          intermittent corruption more reliably and makes every run
          proportionally slower.</div></div>
    </div>

    <div class="field">
      <div class="lab">Freshness window</div>
      <div class="ctl"><input type="number" id="freshness_hours" min="0" max="1440">
        <div class="help">Re-verifying a <b>lineup</b> skips re-probing a
          candidate whose stream hasn't changed on the provider's end since
          its last verdict, as long as that verdict is within this many
          hours &mdash; carrying the prior result forward instead of
          spending a connection on a stream nothing has touched. 0 disables
          this and always re-probes everything, which was every run's
          behaviour before this setting existed. Only applies to runs
          started from a saved lineup; an ad-hoc run has no prior verdict
          to compare against.</div></div>
    </div>

    <div class="field">
      <div class="lab">Match sensitivity</div>
      <div class="ctl">
        <select id="match_sensitivity">
          <option value="strict">Strict &mdash; refuse rather than guess (default)</option>
          <option value="normal">Normal &mdash; also try word-order/typo-tolerant matching</option>
          <option value="relaxed">Relaxed &mdash; same, with a looser threshold</option>
        </select>
        <div class="help">A wanted channel that doesn't match anything exactly,
          by alias, or by prefix/suffix is reported <b>missing</b> by default
          &mdash; the safest answer when the alternative is silently guessing
          wrong. Normal/Relaxed add one more, looser attempt after all of
          those have failed: comparing the channel name's WORDS regardless of
          their order (catches "Sports 1 Meridian" for "Meridian Sports 1"),
          refusing if the best candidate isn't clearly ahead of the next
          one. Every match found this way is still reported as a guess, same
          as the existing prefix/suffix matches.</div>
      </div>
    </div>

    <div class="field">
      <div class="lab">Frame height</div>
      <div class="ctl"><input type="number" id="frame_height" min="180" max="2160">
        <div class="help">Height of the full-size captured frame, never
          upscaled beyond the source. The 1:1 native crop is captured
          separately and is unaffected by this.</div></div>
    </div>

    <div class="field">
      <div class="lab">Thumbnail height</div>
      <div class="ctl"><input type="number" id="thumb_height" min="90" max="720">
        <div class="help">Height of the small image shown in grids.</div></div>
    </div>
  </div>

  <div class="card">
    <h2>Defaults for new runs</h2>
    <div class="lead">Optional. Saves retyping them on the command line.</div>
    <div class="field"><div class="lab">Source</div>
      <div class="ctl"><input type="text" id="source"
        placeholder="playlist URL, or xtream://user:pass@host:port">
        <div class="help">Stored on the server in <code>/config/settings.json</code>.
          A source URL usually contains your subscription credentials.</div></div></div>
    <div class="field"><div class="lab">EPG</div>
      <div class="ctl"><input type="text" id="epg"
        placeholder="XMLTV URL (.xml or .xml.gz)"></div></div>
    <div class="field"><div class="lab">Wantlist</div>
      <div class="ctl"><input type="text" id="wantlist"
        placeholder="name of a saved wantlist"></div></div>
  </div>

  <div class="card">
    <h2>Dispatcharr failover evidence</h2>
    <div class="lead">Dispatcharr's own event log records when a channel
      genuinely failed over in real use -- not a probe's guess, the actual
      thing a viewer's player did. Shown per channel during import.</div>
    <div class="field"><div class="lab">Reporting</div>
      <div class="ctl">
        <select id="failover_display">
          <option value="off">Off &mdash; never asked, never shown</option>
          <option value="info">Informational &mdash; shown on the channel card, never affects ranking</option>
        </select>
        <div class="help">More levels (weighting it into ranking) land here
          later without disturbing what is already saved -- flip freely.</div>
      </div>
    </div>
  </div>

  <div class="card">
    <h2>Backup &amp; restore</h2>
    <div class="lead">Everything needed to rebuild this install elsewhere:
      providers, lineups, wantlists, EPG sources, settings, and every run's
      curated state. Deliberately not the captured thumbnails/frames/clips
      &mdash; a run's own "Clear images" already treats those as disposable,
      and for a lineup with a long history they can dwarf everything else.
      Provider credentials ARE included, so keep the download somewhere
      only you can reach.</div>
    <div class="row">
      <a href="/api/backup/export"><button class="primary">Download backup</button></a>
      <label class="muted" style="display:flex;gap:6px;align-items:center">
        <input type="file" id="restorefile" accept=".gz,.tar.gz,application/gzip" style="display:none">
        <button id="restorepick">Restore from a backup&hellip;</button>
      </label>
      <span class="muted" id="restoremsg"></span>
    </div>
  </div>

  <div class="row">
    <button class="primary" id="save">Save settings</button>
    <span class="muted" id="msg"></span>
  </div>

  <h2 style="margin-top:26px">Name aliases</h2>
  <p class="muted" style="margin:0 0 10px">When a provider spells a channel
    differently enough that the matcher cannot connect it &mdash; UKTV's
    <b>U&amp;Drama</b> against a provider's plain <b>Drama</b> &mdash; an alias
    says the two are the same channel. It applies everywhere at once: runs,
    the catalogue search and Find streams, so they can never disagree about
    what a channel is called. Names are normalised, so case, spacing and
    punctuation do not matter.</p>
  <div class="row" style="margin-bottom:10px">
    <input type="text" id="al-name" placeholder="the name that fails, e.g. U&amp;Drama">
    <span class="muted">&rarr;</span>
    <input type="text" id="al-canon" placeholder="what the provider calls it, e.g. Drama">
    <button id="al-add">Add alias</button>
    <span class="muted" id="al-msg"></span>
  </div>
  <div id="al-list"></div>

  <h2 style="margin-top:26px">Ranking vs. you</h2>
  <div id="dec"></div>
</div>

<script>
const $ = id => document.getElementById(id);
const KEYS = ["concurrency","gap_seconds","sample_seconds","frame_height",
              "thumb_height","source","epg","wantlist","failover_display",
              "freshness_hours","match_sensitivity"];
// source/epg come back from GET masked (they may hold live provider
// credentials) -- track the as-loaded value so an unedited field is left
// out of the POST body instead of overwriting the real saved secret with
// the "***" placeholder the operator never actually typed.
const SECRET_KEYS = ["source","epg"];
const loadedSecret = {};

function estimate(){
  const c = Math.max(1, parseInt($("concurrency").value||"1",10));
  const s = Math.max(3, parseInt($("sample_seconds").value||"10",10));
  const per = s + 6;                     // decode window plus connect/probe overhead
  const mins = n => Math.round(n*per/c/60);
  $("rate").innerHTML = "At these settings, roughly <b>"+mins(100)+
    " minutes</b> per 100 candidate streams (<b>"+mins(500)+
    "</b> for 500). Probing every candidate for 150 channels usually means "+
    "300-600 streams.";
}

async function load(){
  const d = await (await fetch("/api/settings")).json();
  KEYS.forEach(k => { if($(k)) $(k).value = d[k]; });
  SECRET_KEYS.forEach(k => { loadedSecret[k] = d[k]; });
  estimate();
}
KEYS.forEach(k => { const el=$(k); if(el) el.addEventListener("input", estimate); });

$("save").addEventListener("click", async ()=>{
  const body={};
  KEYS.forEach(k => {
    if(!$(k)) return;
    // Unedited secret field still shows the masked placeholder from GET --
    // omit it so the write path keeps whatever's actually stored, instead
    // of clobbering the real credential with the "***" text on screen.
    if(SECRET_KEYS.includes(k) && $(k).value === loadedSecret[k]) return;
    body[k] = $(k).value;
  });
  $("msg").textContent="saving\u2026";
  const r = await fetch("/api/settings", {method:"POST",
    headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
  const d = await r.json();
  KEYS.forEach(k => { if($(k)) $(k).value = d[k]; });
  SECRET_KEYS.forEach(k => { loadedSecret[k] = d[k]; });
  estimate();
  $("msg").textContent="saved";
  setTimeout(()=>$("msg").textContent="", 1800);
});

$("restorepick").addEventListener("click", e=>{ e.preventDefault(); $("restorefile").click(); });
$("restorefile").addEventListener("change", async ()=>{
  const f = $("restorefile").files[0]; if(!f) return;
  if(!confirm("Restore from “"+f.name+"”?\n\nThis OVERWRITES providers, "+
              "lineups, wantlists, EPG sources, settings and every run's curated "+
              "state with what's in the backup. There is no merge and no undo "+
              "— if you want to keep what's here now, back it up first."))
  { $("restorefile").value = ""; return; }
  $("restoremsg").textContent = "restoring…";
  try{
    const data = await f.arrayBuffer();
    const r = await fetch("/api/backup/import", {method:"POST",
      headers:{"Content-Type":"application/gzip"}, body:data});
    const d = await r.json();
    if(!r.ok || d.error){
      $("restoremsg").textContent = "error: "+(d.error||"restore failed");
    } else {
      $("restoremsg").textContent = "restored — reloading…";
      setTimeout(()=>location.reload(), 1200);
    }
  }catch(e){
    $("restoremsg").textContent = "request failed";
  }
  $("restorefile").value = "";
});

load();

// --- Ranking vs. you -----------------------------------------------------
// The override log (decisions.jsonl) was write-only until this existed:
// recording that the curator disagreed with the ranking is only useful once
// something reads it back and says WHERE. Reported, never auto-applied --
// retuning score_key() is a judgement call, and this is the evidence for it.
async function loadDecisions(){
  const box = document.getElementById("dec");
  let d;
  try{ d = await (await fetch("/api/decisions")).json(); }
  catch(e){ box.innerHTML = "<p class=\'muted\'>Could not load.</p>"; return; }
  if(!d.total){
    box.innerHTML = "<p class=\'muted\'>No overrides recorded yet. Whenever you "+
      "pick a stream the ranking did not rank first, it is logged here so the "+
      "scoring can be checked against real judgement over time.</p>";
    return;
  }
  const rows = d.dimensions.filter(x => x.curator_took_worse || x.curator_took_better)
    .map(x =>
      "<tr><td>"+x.dimension+"</td><td>"+x.curator_took_worse+
      "</td><td>"+x.curator_took_better+"</td></tr>").join("");
  box.innerHTML =
    "<p class=\'muted\'>"+d.total+" override(s) recorded. A dimension you "+
    "repeatedly accept a <b>worse</b> value on is one the ranking weights too "+
    "highly; one you repeatedly move <b>toward</b> is one it weights too "+
    "little.</p>"+
    "<table class=\'dectbl\'><thead><tr><th>Dimension</th>"+
    "<th>You took worse</th><th>You took better</th></tr></thead><tbody>"+
    rows+"</tbody></table>"+
    (d.recent.length ? "<p class=\'muted\' style=\'margin-top:10px\'>Most recent: "+
      d.recent.slice(0,5).map(r=>r.channel).join(", ")+"</p>" : "");
}
loadDecisions();

function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;")
  .replace(/>/g,"&gt;").replace(/"/g,"&quot;");}

async function loadAliases(){
  const box = document.getElementById("al-list");
  let d;
  try{ d = await (await fetch("/api/aliases", {cache:"no-store"})).json(); }
  catch(e){ box.innerHTML = "<p class=\'muted\'>Could not load.</p>"; return; }
  const rows = d.aliases || [];
  box.innerHTML = rows.length
    ? rows.map(a => '<div class="saved"><span class="nm">'+esc(a.name)+
        ' <span class="muted">&rarr;</span> '+esc(a.canonical)+
        '</span><button data-adel="'+esc(a.name)+'">Delete</button></div>').join("")
    : '<p class="muted">No aliases yet.</p>';
}
document.getElementById("al-add").addEventListener("click", async ()=>{
  const name = document.getElementById("al-name").value.trim();
  const canonical = document.getElementById("al-canon").value.trim();
  const msg = document.getElementById("al-msg");
  if(!name || !canonical){ msg.textContent = "Both names are required."; return; }
  const r = await fetch("/api/aliases", {method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({name, canonical})});
  const d = await r.json();
  msg.textContent = d.error ? ("error: "+d.error)
    : ("saved: "+d.name+" \u2192 "+d.canonical);
  if(!d.error){
    document.getElementById("al-name").value = "";
    document.getElementById("al-canon").value = "";
    loadAliases();
  }
});
document.getElementById("al-list").addEventListener("click", async e=>{
  const b = e.target.closest("button[data-adel]"); if(!b) return;
  if(!confirm("Delete alias \""+b.dataset.adel+"\"?\n\nChannels matched only "+
              "because of it stop matching on the next run.")) return;
  await fetch("/api/aliases", {method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({delete:true, name:b.dataset.adel})});
  loadAliases();
});
loadAliases();
</script></body></html>
"""


def settings_page():
    return (SETTINGS_PAGE
            .replace("__TOPBAR__", topbar("settings", active="settings"))
            .replace("__CSS__", CSS).replace("__EXTRA__", SETTINGS_EXTRA))


PROVIDERS_EXTRA = WANTLIST_EXTRA + """
.schemebadge{font-size:10px;text-transform:uppercase;letter-spacing:.4px;
  padding:2px 7px;border-radius:3px;background:var(--panel2);color:var(--dim);
  border:1px solid var(--line)}
.pwrap{position:relative;display:flex;gap:8px;align-items:center}
.pwrap input{flex:1}
.testresult{font-size:12.5px;margin-top:8px;padding:8px 10px;border-radius:var(--radius);
  display:none}
.testresult.show{display:block}
.testresult.good{background:rgba(39,194,76,.1);border:1px solid var(--ok);color:var(--ok)}
.testresult.bad{background:rgba(240,80,80,.1);border:1px solid var(--bad);color:var(--bad)}
.hint2{color:var(--faint);font-size:11.5px;margin-top:6px}
.ptype{padding:7px 16px}
.ptype.on{background:var(--accent2);border-color:var(--accent2);color:#04222c;font-weight:600}
"""

PROVIDERS_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>probarr &middot; providers</title><style>__CSS____EXTRA__</style></head><body>

__TOPBAR__

<div class="page">

  <div class="card">
    <h2>Add a provider</h2>
    <div class="row" style="margin-bottom:10px">
      <input type="text" id="name" placeholder="Name, e.g. My IPTV">
    </div>

    <div class="row" style="margin-bottom:10px">
      <button type="button" id="ptype-iptv" class="ptype on">IPTV</button>
      <button type="button" id="ptype-dispatcharr" class="ptype">Dispatcharr</button>
    </div>

    <div id="ptype-iptv-fields">
      <div class="row" style="margin-bottom:8px">
        <input type="text" id="iptv-url" style="flex:1"
          placeholder="Playlist URL, or just the provider's host/domain">
      </div>
      <div class="pwrap">
        <input type="text" id="iptv-user" placeholder="Username (only if not already in the URL)">
        <input type="password" id="iptv-pass" style="flex:1"
          placeholder="Password (only if not already in the URL)">
        <button id="iptv-toggle" type="button">Show</button>
      </div>
      <div class="hint2">Paste the full playlist URL your provider gave you (username/password
        stay blank) &mdash; or, if you were given an Xtream login instead of a link, just the
        host/domain plus your username and password.</div>
    </div>

    <div id="ptype-dispatcharr-fields" style="display:none">
      <div class="row" style="margin-bottom:8px">
        <input type="text" id="disp-host" placeholder="IP or hostname" style="flex:1">
        <input type="number" id="disp-port" placeholder="Port" style="width:110px" value="9191">
      </div>
      <div class="pwrap">
        <input type="text" id="disp-user" placeholder="Username">
        <input type="password" id="disp-pass" style="flex:1" placeholder="Password">
        <button id="disp-toggle" type="button">Show</button>
      </div>
      <div class="hint2">Its own admin login, not the Xtream/M3U playback credentials &mdash;
        this is what pushes curated channels back into Dispatcharr.</div>
    </div>

    <div class="hint2" style="margin-top:10px">
      <a href="#" id="advtoggle">Paste a raw connection string instead&hellip;</a>
    </div>
    <div class="pwrap" id="advwrap" style="display:none;margin-top:8px">
      <input type="password" id="spec" style="flex:1"
        placeholder="M3U URL, xtream://user:pass@host:port, or dispatcharr://user:pass@host:port">
      <button id="toggle" type="button">Show</button>
    </div>

    <div class="row" style="margin-top:12px">
      <input type="number" id="concurrency" min="1" style="width:90px"
        placeholder="default" title="Max simultaneous probe connections for THIS provider. Blank uses the global default in Settings. Each provider gets its own pool, so a saturated one never stalls jobs against a different, more permissive provider.">
      <span class="muted" style="align-self:center">max connections (blank = default)</span>
    </div>
    <div class="row" style="margin-top:12px">
      <button id="test">Test connection</button>
      <button class="primary" id="save">Save provider</button>
      <span class="muted" id="savemsg"></span>
    </div>
    <div class="testresult" id="testresult"></div>
  </div>

  <div class="card">
    <h2>Saved providers</h2>
    <div id="list"></div>
  </div>

  <div class="card" id="epg-sources">
    <h2>EPG (guide) sources</h2>
    <div class="lead">The third thing a run can use, alongside a provider and
      a wantlist: an XMLTV URL that records what the guide said should be
      playing at the moment each frame was captured. Save one here once, then
      pick it from a dropdown on New Run instead of retyping the URL.</div>
    <div class="row" style="margin-bottom:10px">
      <input type="text" id="epgname" placeholder="name, e.g. uk-guide">
      <input type="text" id="epgurl" placeholder="XMLTV URL (.xml or .xml.gz)" style="flex:1;min-width:260px">
      <button class="primary" id="epgsave">Save</button>
      <span id="epgsavemsg" class="muted"></span>
    </div>
    <div id="epglist"></div>
  </div>

</div>

<script>
const $ = id => document.getElementById(id);
let PTYPE = "iptv";

function pwToggle(fieldId, btnId){
  $(btnId).addEventListener("click", ()=>{
    const on = $(fieldId).type === "password";
    $(fieldId).type = on ? "text" : "password";
    $(btnId).textContent = on ? "Hide" : "Show";
  });
}
pwToggle("spec", "toggle");
pwToggle("iptv-pass", "iptv-toggle");
pwToggle("disp-pass", "disp-toggle");

$("ptype-iptv").addEventListener("click", ()=>{
  PTYPE = "iptv";
  $("ptype-iptv").classList.add("on"); $("ptype-dispatcharr").classList.remove("on");
  $("ptype-iptv-fields").style.display = ""; $("ptype-dispatcharr-fields").style.display = "none";
});
$("ptype-dispatcharr").addEventListener("click", ()=>{
  PTYPE = "dispatcharr";
  $("ptype-dispatcharr").classList.add("on"); $("ptype-iptv").classList.remove("on");
  $("ptype-dispatcharr-fields").style.display = ""; $("ptype-iptv-fields").style.display = "none";
});
$("advtoggle").addEventListener("click", (e)=>{
  e.preventDefault();
  $("advwrap").style.display = $("advwrap").style.display === "none" ? "" : "none";
});

// Builds the same raw spec string the backend has always accepted
// (xtream://user:pass@host:port, dispatcharr://user:pass@host:port, or a
// bare M3U URL) from whichever structured fields are actually filled in,
// so the backend never needed to change to get a friendlier form. The
// advanced box, if open and non-empty, always wins -- it's an explicit
// escape hatch for anything the structured fields can't express.
function computeSpec(){
  const adv = $("spec").value.trim();
  if($("advwrap").style.display !== "none" && adv) return adv;
  if(PTYPE === "dispatcharr"){
    const host = $("disp-host").value.trim(), port = $("disp-port").value.trim();
    const user = $("disp-user").value.trim(), pass = $("disp-pass").value.trim();
    if(!host) return "";
    return "dispatcharr://"+encodeURIComponent(user)+":"+encodeURIComponent(pass)+
      "@"+host+(port?":"+port:"");
  }
  const url = $("iptv-url").value.trim();
  const user = $("iptv-user").value.trim(), pass = $("iptv-pass").value.trim();
  if(!url) return "";
  if(user || pass){
    // A host/domain, not a full link -- strip any scheme the user pasted
    // out of habit and build an Xtream login from it.
    const hostport = url.replace(/^https?:\/\//i, "").replace(/\/.*$/, "");
    return "xtream://"+encodeURIComponent(user)+":"+encodeURIComponent(pass)+"@"+hostport;
  }
  return url;   // a complete playlist URL, used exactly as given
}
function syncSpec(){ $("spec").value = computeSpec(); return $("spec").value; }

$("spec").addEventListener("input", ()=>{
  $("spec").style.borderColor = "";
  $("testresult").className = "testresult";
});

$("test").addEventListener("click", async ()=>{
  const spec = syncSpec();
  const box = $("testresult");
  if(!spec){ box.className="testresult show bad"; box.textContent="Enter a provider address first."; return; }
  box.className="testresult show"; box.textContent="Testing\u2026";
  try{
    const r = await fetch("/api/providers/test", {method:"POST",
      headers:{"Content-Type":"application/json"}, body:JSON.stringify({spec})});
    const d = await r.json();
    if(d.ok){
      box.className="testresult show good";
      box.textContent="Connected \u2014 "+d.channels+" streams found.";
    } else {
      box.className="testresult show bad";
      box.textContent="Could not connect: "+d.error;
    }
  }catch(e){ box.className="testresult show bad"; box.textContent="Request failed."; }
});

$("save").addEventListener("click", async ()=>{
  const name=$("name").value.trim(), spec=syncSpec();
  const concurrency = $("concurrency").value.trim();
  if(!name || !spec){
    // The address field is left EMPTY after clicking Edit (the real value
    // is never sent to the browser), but its placeholder -- "re-enter the
    // address for X" -- reads enough like real filled-in content that it's
    // easy to click Save without noticing nothing was typed. A quiet grey
    // message next to the button was easy to miss entirely, which read as
    // "editing a provider doesn't work" rather than "the field is empty".
    // Highlighting the field itself, not just the message, makes it obvious.
    // Which field that actually IS depends on what's visible: the raw
    // advanced box during an edit (still the only way to change an
    // existing provider's credentials), or the structured field a fresh
    // add is missing.
    const advOpen = $("advwrap").style.display !== "none";
    const target = advOpen ? $("spec")
      : PTYPE === "dispatcharr" ? $("disp-host") : $("iptv-url");
    target.style.borderColor = "var(--bad)";
    target.focus();
    $("testresult").className = "testresult show bad";
    $("testresult").textContent = !name ? "Name is required."
      : advOpen
        ? "Paste the address again \u2014 it's cleared after Edit since it's "
          + "never sent to the browser, and wasn't re-entered."
        : "Fill in the provider's address first.";
    return;
  }
  $("spec").style.borderColor = "";
  $("savemsg").textContent="saving\u2026";
  const r = await fetch("/api/providers/"+encodeURIComponent(name), {method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({spec, concurrency: concurrency ? parseInt(concurrency,10) : null})});
  const d = await r.json();
  $("savemsg").textContent = d.ok ? "saved" : ("error: "+(d.error||"failed"));
  if(d.ok){
    $("name").value=""; $("spec").value=""; $("concurrency").value="";
    $("iptv-url").value=""; $("iptv-user").value=""; $("iptv-pass").value="";
    $("disp-host").value=""; $("disp-user").value=""; $("disp-pass").value="";
    $("testresult").className="testresult";
  }
  loadList();
});

function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;")
  .replace(/>/g,"&gt;").replace(/"/g,"&quot;");}

async function loadList(){
  const d = await (await fetch("/api/providers")).json();
  if(!d.providers.length){
    $("list").innerHTML='<div class="muted">No providers saved yet \u2014 add one above.</div>';
    return;
  }
  $("list").innerHTML = d.providers.map(p =>
    '<div class="saved"><span class="schemebadge">'+esc(p.scheme)+'</span>'+
    '<span class="nm">'+esc(p.name)+'</span>'+
    '<span class="meta">'+esc(p.redacted)+
      (p.concurrency ? ' · max '+p.concurrency+' connection'+(p.concurrency===1?'':'s') : '')+'</span>'+
    '<button data-edit="'+esc(p.name)+'">Edit</button>'+
    '<button data-del="'+esc(p.name)+'">Delete</button></div>').join("");
}
document.addEventListener("click", async e=>{
  const ed=e.target.closest("[data-edit]"), dl=e.target.closest("[data-del]");
  if(ed){
    const d = await (await fetch("/api/providers")).json();
    const p = d.providers.find(x=>x.name===ed.dataset.edit);
    // The address is deliberately not sent to the browser, so editing means
    // re-entering it. Saving under the same name replaces the old one.
    if(p){ $("name").value=p.name; $("spec").value="";
           $("spec").placeholder = "re-enter the address for " + p.name;
           $("spec").style.borderColor = "var(--bad)";
           $("concurrency").value = p.concurrency || "";
           // Editing still needs the raw box: the structured fields can't
           // be pre-filled from a saved credential that's deliberately
           // never sent to the browser, and re-deriving which of three
           // formats it was from a redacted string isn't worth it when
           // the box that already handles "enter a full spec string" does
           // the job.
           $("advwrap").style.display = "";
           $("testresult").className = "testresult show bad";
           $("testresult").textContent = "Address cleared for editing — it's never sent "
             + "to the browser, so paste it again below before saving.";
           window.scrollTo({top:0,behavior:"smooth"});
           $("spec").focus(); }
  }
  if(dl){
    if(!confirm("Delete provider \""+dl.dataset.del+"\"?")) return;
    await fetch("/api/providers/"+encodeURIComponent(dl.dataset.del)+"/delete", {method:"POST"});
    loadList();
  }
});

$("epgsave").addEventListener("click", async ()=>{
  const name=$("epgname").value.trim(), url=$("epgurl").value.trim();
  if(!name || !url){ $("epgsavemsg").textContent="Name and URL are both required."; return; }
  $("epgsavemsg").textContent="saving\u2026";
  const r = await fetch("/api/epg-sources/"+encodeURIComponent(name), {method:"POST",
    headers:{"Content-Type":"application/json"}, body:JSON.stringify({url})});
  const d = await r.json();
  $("epgsavemsg").textContent = d.ok ? "saved" : ("error: "+(d.error||"failed"));
  if(d.ok){ $("epgname").value=""; $("epgurl").value=""; }
  loadEpgList();
});
async function loadEpgList(){
  const d = await (await fetch("/api/epg-sources")).json();
  EPGORDER = d.epg_sources.map(s=>s.name);
  if(!d.epg_sources.length){
    $("epglist").innerHTML='<div class="muted">None saved yet.</div>';
    return;
  }
  // Order here IS priority: "first match wins" resolves sources in this
  // exact order everywhere -- Check EPG, a re-probe's captured guide entry,
  // and the export. A source with no explicit per-channel override is
  // silently using whichever one is listed first, so the list needs to say
  // that plainly, not just be a bag of saved URLs.
  $("epglist").innerHTML = '<div class="muted" style="margin-bottom:6px">'+
    'Order is priority: the first source below that has a channel wins, '+
    'unless a channel has its own explicit choice (set from Check EPG).</div>'+
    d.epg_sources.map((s,i) =>
    '<div class="saved"><span class="nm">'+(i+1)+'. '+esc(s.name)+'</span>'+
    '<span class="meta">'+esc(s.url)+'</span>'+
    '<button data-eup="'+esc(s.name)+'" '+(i===0?'disabled':'')+' title="Higher priority">&uarr;</button>'+
    '<button data-edown="'+esc(s.name)+'" '+(i===d.epg_sources.length-1?'disabled':'')+' title="Lower priority">&darr;</button>'+
    '<button data-eedit="'+esc(s.name)+'">Edit</button>'+
    '<button data-edel="'+esc(s.name)+'">Delete</button></div>').join("");
}
let EPGORDER = [];
async function moveEpgSource(name, dir){
  const i = EPGORDER.indexOf(name); if(i<0) return;
  const j = i+dir; if(j<0 || j>=EPGORDER.length) return;
  [EPGORDER[i], EPGORDER[j]] = [EPGORDER[j], EPGORDER[i]];
  await fetch("/api/epg-sources/reorder", {method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({names: EPGORDER})});
  loadEpgList();
}
document.addEventListener("click", async e=>{
  const eu=e.target.closest("[data-eup]"), edn=e.target.closest("[data-edown]");
  if(eu){ moveEpgSource(eu.dataset.eup, -1); return; }
  if(edn){ moveEpgSource(edn.dataset.edown, 1); return; }
  const ee=e.target.closest("[data-eedit]"), ed2=e.target.closest("[data-edel]");
  if(ee){
    const d = await (await fetch("/api/epg-sources")).json();
    const s = d.epg_sources.find(x=>x.name===ee.dataset.eedit);
    if(s){ $("epgname").value=s.name; $("epgurl").value=s.url||""; window.scrollTo({top:0,behavior:"smooth"}); }
  }
  if(ed2){
    if(!confirm("Delete EPG source \""+ed2.dataset.edel+"\"?")) return;
    await fetch("/api/epg-sources/"+encodeURIComponent(ed2.dataset.edel)+"/delete", {method:"POST"});
    loadEpgList();
  }
});
loadEpgList();

loadList();
</script></body></html>
"""


def providers_page():
    return (PROVIDERS_PAGE
            .replace("__TOPBAR__", topbar("providers", active="providers"))
            .replace("__CSS__", CSS).replace("__EXTRA__", PROVIDERS_EXTRA))


NEWRUN_EXTRA = WANTLIST_EXTRA + """
.field{display:flex;gap:12px;align-items:flex-start;padding:11px 0;
  border-bottom:1px solid rgba(255,255,255,.05)}
.field:last-child{border-bottom:0}
.field .lab{width:110px;flex:none;font-size:13px;font-weight:600;padding-top:6px}
.field .ctl{flex:1}
select{background:var(--bg);color:var(--text);border:1px solid var(--line);
  border-radius:var(--radius);padding:6px 9px;font-size:13px;width:100%;max-width:460px}
.field input[type=text],.field input[type=number]{width:100%;max-width:460px}
.field input[type=number]{max-width:110px}
.miniline{color:var(--faint);font-size:11.5px;margin-top:4px}
.emptynote{background:var(--bg2);border:1px solid var(--line);border-left:3px solid var(--warn);
  border-radius:var(--radius);padding:10px 12px;margin-bottom:10px;font-size:13px}
.emptynote a{color:var(--accent)}
.startbar{display:flex;gap:10px;align-items:center;margin-top:6px}
#progresswrap{display:none;margin-top:16px}
#progresswrap.show{display:block}
.pbar{height:8px;border-radius:4px;background:var(--bg2);overflow:hidden;border:1px solid var(--line)}
.pbar > div{height:100%;background:var(--accent2);width:0%;transition:width .3s}
.pstats{display:flex;gap:16px;font-size:12.5px;color:var(--dim);margin:8px 0}
.pstats b{color:var(--text)}
.plog{background:#000;border:1px solid var(--line);border-radius:var(--radius);
  padding:8px 10px;font:11.5px/1.5 ui-monospace,Menlo,Consolas,monospace;color:#8fdc9a;
  max-height:220px;overflow-y:auto;white-space:pre-wrap}
.pdone{display:none;margin-top:12px}
.pdone.show{display:flex;gap:10px;align-items:center}
"""

NEWRUN_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>probarr &middot; new run</title><style>__CSS____EXTRA__</style></head><body>

__TOPBAR__

<div class="page">
  <div class="card">
    <h2>New run</h2>

    <div id="noproviders" class="emptynote" style="display:none">
      No provider saved yet. <a href="/providers">Add one</a> first.
    </div>

    <div class="field">
      <div class="lab">Lineup</div>
      <div class="ctl">
        <select id="lineup"><option value="">One-off run (no lineup)</option></select>
        <div class="miniline"><a href="/lineups">Manage lineups</a> &middot;
          starting from a lineup fills in the rest, and the run inherits every
          per-channel decision that lineup has accumulated</div>
      </div>
    </div>

    <div class="field">
      <div class="lab">Provider</div>
      <div class="ctl">
        <select id="provider"></select>
        <div class="miniline"><a href="/providers">Manage providers</a></div>
      </div>
    </div>

    <div class="field">
      <div class="lab">Channels</div>
      <div class="ctl">
        <select id="wantlist"><option value="">All channels in the source</option></select>
        <div class="miniline"><a href="/wantlists">Manage wantlists</a> &middot;
          leave as "All channels" only for a small source</div>
      </div>
    </div>

    <div class="field">
      <div class="lab">Guide (EPG)</div>
      <div class="ctl">
        <select id="epgselect"><option value="">No guide</option>
          <option value="__custom__">Custom URL&hellip;</option></select>
        <input type="text" id="epg" placeholder="XMLTV URL"
          style="display:none;margin-top:6px">
        <div class="miniline"><a href="/providers#epg-sources" target="_blank">Manage EPG sources</a></div>
      </div>
    </div>

    <div class="field">
      <div class="lab">Regions</div>
      <div class="ctl">
        <input type="text" id="regions" placeholder="e.g. UK (optional, comma-separated)">
        <div class="miniline">On a multi-country provider, a generically-named
          channel (TLC, CNN, MTV&hellip;) matches every country's copy without
          this &mdash; measured live: 158 UK channels with no region filter
          pulled in 1,565 candidates, mostly other countries' channels.</div>
        <label class="miniline"><input type="checkbox" id="strict_region">
          Strict &mdash; also drop channels with no recognisable country
          marker at all. Without this, Regions only rejects candidates it can
          positively identify as a DIFFERENT country; unmarked candidates
          (common on aggregated providers) still get through.</label>
      </div>
    </div>

    <div class="field">
      <div class="lab">Streams at once</div>
      <div class="ctl">
        <input type="number" id="concurrency" min="1" max="16">
        <div class="miniline">Set in <a href="/settings">Settings</a> to match your
          provider's connection limit.</div>
      </div>
    </div>

    <div class="field">
      <div class="lab">Run name</div>
      <div class="ctl"><input type="text" id="run_id" placeholder="optional, e.g. my-lineup"></div>
    </div>

    <div class="warn" id="scopewarn" style="display:none"></div>

    <div class="startbar">
      <button class="primary" id="start">Start verifying</button>
      <span class="muted" id="startmsg"></span>
    </div>

    <div id="progresswrap">
      <div class="pbar"><div id="pbarfill"></div></div>
      <div class="pstats">
        <span><b id="pdone">0</b>/<span id="ptotal">0</span> probed</span>
        <span id="peta"></span>
        <span id="pstate"></span>
        <button id="stopverify"
          style="margin-left:auto;border-color:var(--bad);color:var(--bad)">Stop verifying</button>
      </div>
      <div class="plog" id="plog"></div>
      <div class="pdone" id="pdonebar">
        <button class="primary" id="opencurate">Open in Curate</button>

      </div>
    </div>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);
let currentRunId = null, poller = null;

async function loadProviders(){
  const d = await (await fetch("/api/providers")).json();
  if(!d.providers.length){
    $("noproviders").style.display="block";
    $("start").disabled = true;
    return;
  }
  $("provider").innerHTML = d.providers.map(p =>
    '<option value="'+esc(p.name)+'">'+esc(p.name)+' ('+esc(p.scheme)+')</option>').join("");
}
async function loadWantlists(){
  const d = await (await fetch("/api/wantlists")).json();
  $("wantlist").innerHTML = '<option value="">All channels in the source</option>' +
    d.wantlists.map(w => '<option value="'+esc(w.name)+'">'+esc(w.name)+
      ' ('+w.channels+' channels)</option>').join("");
}
async function loadEpgSources(){
  const d = await (await fetch("/api/epg-sources")).json();
  const sel = $("epgselect");
  const customOpt = '<option value="__custom__">Custom URL&hellip;</option>';
  sel.innerHTML = '<option value="">No guide</option>' +
    d.epg_sources.map(s => '<option value="'+esc(s.url)+'">'+esc(s.name)+'</option>').join("") +
    customOpt;
}
$("epgselect").addEventListener("change", ()=>{
  const custom = $("epgselect").value === "__custom__";
  $("epg").style.display = custom ? "block" : "none";
  if(!custom) $("epg").value = "";
});
async function loadDefaults(){
  const d = await (await fetch("/api/settings")).json();
  $("concurrency").value = d.concurrency;
  if(d.epg){
    // A saved default that doesn't match any named source still has to be
    // usable -- fall back to the custom-URL slot rather than silently
    // dropping it.
    const opt = [...$("epgselect").options].find(o => o.value === d.epg);
    if(opt){ $("epgselect").value = d.epg; }
    else { $("epgselect").value = "__custom__"; $("epg").style.display = "block"; $("epg").value = d.epg; }
  }
}
function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;")
  .replace(/>/g,"&gt;").replace(/"/g,"&quot;");}

// The two defaults that most often bite: "All channels" against a
// provider that's actually a large multi-country catalog probes tens of
// thousands of candidates, and no Regions filter lets a plainly-named
// channel match every country's copy of it (the exact incident that
// motivated runner.py's own after-the-fact log warning -- this is the
// same check surfaced BEFORE a run starts instead of after candidates
// have already ballooned).
function checkScope(){
  const box = $("scopewarn");
  const noWantlist = !$("wantlist").value;
  const noRegions = !$("regions").value.trim();
  if(noWantlist && noRegions){
    box.style.display = "";
    box.innerHTML = "<b>Heads up:</b> \"All channels in the source\" with no " +
      "Regions filter probes every candidate for every channel your provider " +
      "lists -- on anything but a small, single-country source this can mean " +
      "hours instead of minutes, and can match the wrong country's copy of a " +
      "plainly-named channel. Pick a wantlist above, or set Regions, before starting.";
  } else if(noWantlist){
    box.style.display = "";
    box.innerHTML = "<b>Heads up:</b> \"All channels in the source\" probes every " +
      "candidate your provider lists, not just the ones you actually want -- fine " +
      "for a small source, likely to take a very long time on a large one.";
  } else {
    box.style.display = "none";
  }
}
$("wantlist").addEventListener("change", checkScope);
$("regions").addEventListener("input", checkScope);

$("start").addEventListener("click", async ()=>{
  if($("scopewarn").style.display !== "none" && $("scopewarn").innerHTML &&
     !confirm("This run may probe far more than you intend -- see the warning " +
              "above. Start anyway?")) return;
  const provName = $("provider").value;
  if(!provName){ $("startmsg").textContent="Choose a provider first."; return; }

  $("start").disabled = true;
  $("startmsg").textContent = "starting\u2026";
  const body = {
    // The name only. The server resolves it to the real address, which
    // never leaves it -- see /api/providers.
    provider: provName,
    wantlist: $("wantlist").value,
    epg: $("epgselect").value === "__custom__" ? $("epg").value : $("epgselect").value,
    regions: $("regions").value,
    strict_region: $("strict_region").checked,
    concurrency: $("concurrency").value,
    run_id: $("run_id").value.trim(),
    // Recorded on the run, which is what lets Curate inherit this lineup's
    // decisions and lets a later push remember the group it pushed into.
    lineup: $("lineup").value,
  };
  const r = await fetch("/api/runs/start", {method:"POST",
    headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
  const d = await r.json();
  if(!d.ok){ $("startmsg").textContent = "error: "+(d.error||"failed"); $("start").disabled=false; return; }
  $("startmsg").textContent = "";
  currentRunId = d.run_id;
  $("progresswrap").classList.add("show");
  $("stopverify").style.display = "";
  $("stopverify").disabled = false;
  $("stopverify").textContent = "Stop verifying";
  poll();
});

$("stopverify").addEventListener("click", async () => {
  if(!currentRunId) return;
  if(!confirm("Stop this run? Whatever's already been probed is kept -- "+
              "you can open it in Curate with just those results, or "+
              "re-run later to pick up the rest.")) return;
  $("stopverify").disabled = true; $("stopverify").textContent = "stopping…";
  await fetch("/api/run/"+encodeURIComponent(currentRunId)+"/stop", {method:"POST"});
});

function poll(){
  if(poller) clearInterval(poller);
  poller = setInterval(async ()=>{
    let d;
    try{ d = await (await fetch("/api/run/"+encodeURIComponent(currentRunId)+"/progress",
                                {cache:"no-store"})).json(); }
    catch(e){ return; }
    if(d.error){ $("pstate").textContent = "error: "+d.error; clearInterval(poller); return; }
    const p = d.progress;
    if(p){
      $("pdone").textContent = p.done; $("ptotal").textContent = p.total;
      const pct = p.total ? Math.round(100*p.done/p.total) : 0;
      $("pbarfill").style.width = pct+"%";
      $("peta").textContent = p.eta ? ("~"+Math.ceil(p.eta/60)+" min left") : "";
    }
    $("plog").textContent = (d.log||[]).join("\n");
    $("plog").scrollTop = $("plog").scrollHeight;
    $("pstate").textContent = d.state;
    if(d.state === "done" || d.state === "error" || d.state === "stopped"){
      clearInterval(poller);
      $("start").disabled = false;
      $("stopverify").style.display = "none";
      if(d.state === "done"){
        $("pdonebar").classList.add("show");
        $("opencurate").onclick = ()=> location.href="/run/"+encodeURIComponent(currentRunId)+"/curate";
      }
    }
  }, 1200);
}

// A lineup fills the form in rather than bypassing it: every field stays
// visible and editable, so a one-off variation ("same lineup, but only the
// sports wantlist") does not require editing the lineup itself.
let LINEUPS = [];
async function loadLineups(){
  const d = await (await fetch("/api/lineups")).json();
  $("lineup").innerHTML = '<option value="">One-off run (no lineup)</option>' +
    (d.lineups||[]).map(l => '<option value="'+esc(l.name)+'">'+esc(l.name)+
      '</option>').join("");
  LINEUPS = d.lineups || [];
  const want = new URLSearchParams(location.search).get("lineup");
  if(want && LINEUPS.some(l => l.name === want)){
    $("lineup").value = want;
    applyLineup();
  }
}
function applyLineup(){
  const lu = LINEUPS.find(l => l.name === $("lineup").value);
  if(!lu) return;
  if(lu.provider || lu.source) $("provider").value = lu.provider || lu.source;
  $("regions").value = lu.regions || "";
  // A lineup can legitimately hold either the address or the saved NAME of
  // a wantlist or guide -- both are resolvable server-side -- so match on
  // the option's label as well as its value, or a perfectly valid lineup
  // lands in the custom-URL slot with a name in it.
  const pick = (sel, v) => {
    const o = [...$(sel).options].find(x => x.value === v || x.textContent.trim() === v);
    if(o){ $(sel).value = o.value; return true; }
    return false;
  };
  if(!pick("wantlist", (lu.wantlist||"").replace(/\.txt$/, "")))
    pick("wantlist", lu.wantlist || "");
  if(pick("epgselect", lu.epg || "")){ $("epg").style.display = "none"; }
  else { $("epgselect").value = "__custom__"; $("epg").style.display = "block";
         $("epg").value = lu.epg; }
  if(!$("run_id").value.trim()) $("run_id").placeholder = lu.name + "-" +
    new Date().toISOString().slice(0,10);
  checkScope();
}
$("lineup").addEventListener("change", applyLineup);

// Ordered deliberately: a lineup can only fill the form in once the selects
// it writes into actually have their options, because setting .value on a
// select with no matching option silently does nothing.
Promise.all([loadProviders(), loadWantlists(),
             loadEpgSources().then(loadDefaults)]).then(() => { loadLineups(); checkScope(); });
</script></body></html>
"""


def new_run_page():
    return (NEWRUN_PAGE
            .replace("__TOPBAR__", topbar("new run", active="new"))
            .replace("__CSS__", CSS).replace("__EXTRA__", NEWRUN_EXTRA))


BROWSE_EXTRA = WANTLIST_EXTRA + NEWRUN_EXTRA + """
.brwrap{display:grid;grid-template-columns:1fr 320px;gap:14px;align-items:start}
@media(max-width:900px){.brwrap{grid-template-columns:1fr}}
.brtools{display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap}
.brtools input[type=search]{flex:1;min-width:180px}
.brcount{color:var(--dim);font-size:12.5px;white-space:nowrap}
.brlist{max-height:640px;overflow-y:auto;border:1px solid var(--line);border-radius:var(--radius)}
.brrow{display:flex;gap:10px;align-items:flex-start;padding:8px 10px;
  border-bottom:1px solid rgba(255,255,255,.05);font-size:13px}
.brrow:last-child{border-bottom:0}
.brrow:hover{background:var(--panel)}
.brrow input[type=checkbox]{margin-top:3px}
.brrow .nm{flex:1}
.brrow .nm b{font-weight:600}
.brrow .cnt{color:var(--faint);font-size:11.5px;margin-left:6px}
.brrow .ex{color:var(--faint);font-size:11px;margin-top:2px;cursor:pointer}
.brrow .exlist{display:none;color:var(--dim);font-size:11px;margin-top:4px;
  padding-left:2px}
.brrow.expanded .exlist{display:block}
.brside{position:sticky;top:14px}
.empty2{color:var(--dim);text-align:center;padding:30px;font-size:13px}
"""

BROWSE_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>probarr &middot; browse channels</title><style>__CSS____EXTRA__</style></head><body>

__TOPBAR__

<div class="page" style="max-width:1200px">
  <div class="card">
    <h2>Browse a provider's channels</h2>
    <div class="lead">No probing, no waiting -- just the channel names your
      provider lists, grouped so 40 spellings of the same channel become one
      row. Tick what you want, save it as a wantlist.</div>

    <div id="noproviders" class="emptynote" style="display:none">
      No provider saved yet. <a href="/providers">Add one</a> first.
    </div>

    <div id="loadbar" class="row">
      <select id="provider"></select>
      <input type="text" id="regions" placeholder="Regions, e.g. UK (optional)" style="max-width:220px">
      <button class="primary" id="load">Load channels</button>
      <span class="muted" id="loadmsg"></span>
    </div>
  </div>

  <div class="card" id="results" style="display:none">
    <div class="brwrap">
      <div>
        <div class="brtools">
          <input type="search" id="q" placeholder="Filter channels&hellip;">
          <button id="selall">Select visible</button>
          <button id="selnone">Select none</button>
          <span class="brcount" id="brcount"></span>
        </div>
        <div class="brlist" id="brlist"></div>
      </div>
      <div class="brside">
        <div class="mfield">
          <label>Save as wantlist</label>
          <input type="text" id="wname" list="wnames" placeholder="wantlist name">
          <datalist id="wnames"></datalist>
          <div class="miniline" id="wexisting"></div>
        </div>
        <div class="row">
          <button class="primary" id="save">Save wantlist</button>
          <span class="muted" id="savemsg"></span>
        </div>
        <div class="hint2" style="margin-top:10px">
          Saving a name that already exists appends your new picks to it
          rather than replacing it.
        </div>
      </div>
    </div>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);
let CHANNELS = [];
const CHECKED = new Set();

function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;")
  .replace(/>/g,"&gt;").replace(/"/g,"&quot;");}

async function loadProviders(){
  const d = await (await fetch("/api/providers")).json();
  if(!d.providers.length){ $("noproviders").style.display="block"; $("loadbar").style.display="none"; return; }
  $("provider").innerHTML = d.providers.map(p =>
    '<option value="'+esc(p.name)+'">'+esc(p.name)+' ('+esc(p.scheme)+')</option>').join("");
}
async function loadWantlistNames(){
  const d = await (await fetch("/api/wantlists")).json();
  $("wnames").innerHTML = d.wantlists.map(w => '<option value="'+esc(w.name)+'">').join("");
  return d.wantlists;
}

$("load").addEventListener("click", async ()=>{
  const provider = $("provider").value;
  if(!provider){ $("loadmsg").textContent="Choose a provider first."; return; }
  $("load").disabled = true; $("loadmsg").textContent = "loading\u2026";
  try{
    const r = await fetch("/api/browse", {method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({provider, regions: $("regions").value})});
    const d = await r.json();
    if(d.error){ $("loadmsg").textContent = "error: "+d.error; return; }
    CHANNELS = d.channels; CHECKED.clear();
    $("loadmsg").textContent = CHANNELS.length+" channels found in "+d.total_streams+" streams";
    $("results").style.display = "block";
    renderList();
  }catch(e){ $("loadmsg").textContent = "request failed"; }
  finally{ $("load").disabled = false; }
});

function visible(){
  const q = $("q").value.trim().toLowerCase();
  if(!q) return CHANNELS;
  return CHANNELS.filter(c => c.name.toLowerCase().includes(q) ||
    c.examples.some(e => e.toLowerCase().includes(q)));
}

function renderList(){
  const list = visible();
  $("brlist").innerHTML = list.length ? list.map(c => {
    const checked = CHECKED.has(c.key);
    const examples = c.examples.filter(e => e !== c.name);
    return '<div class="brrow" data-key="'+esc(c.key)+'">'+
      '<input type="checkbox" data-tick="'+esc(c.key)+'"'+(checked?' checked':'')+'>'+
      '<div class="nm"><b>'+esc(c.name)+'</b><span class="cnt">'+c.count+' stream'+
        (c.count===1?'':'s')+'</span>'+
      (examples.length ? '<div class="ex" data-toggle="'+esc(c.key)+'">'+
        examples.length+' other name'+(examples.length===1?'':'s')+' grouped here \u2013 show</div>'+
        '<div class="exlist">'+examples.map(esc).join('<br>')+'</div>' : '')+
      '</div></div>';
  }).join("") : '<div class="empty2">No channels match.</div>';
  $("brcount").textContent = CHECKED.size+" selected";
}

document.addEventListener("click", e=>{
  const tick = e.target.closest("[data-tick]");
  if(tick){
    if(tick.checked) CHECKED.add(tick.dataset.tick); else CHECKED.delete(tick.dataset.tick);
    $("brcount").textContent = CHECKED.size+" selected";
    return;
  }
  const tog = e.target.closest("[data-toggle]");
  if(tog){ tog.closest(".brrow").classList.toggle("expanded"); return; }
});
$("q").addEventListener("input", renderList);
$("selall").addEventListener("click", ()=>{ visible().forEach(c=>CHECKED.add(c.key)); renderList(); });
$("selnone").addEventListener("click", ()=>{ visible().forEach(c=>CHECKED.delete(c.key)); renderList(); });

$("wname").addEventListener("input", async ()=>{
  const names = await loadWantlistNames();
  const existing = names.find(w => w.name === $("wname").value.trim());
  $("wexisting").textContent = existing
    ? ("Existing list has "+existing.channels+" channels \u2014 your picks will be added to it.")
    : "";
});

$("save").addEventListener("click", async ()=>{
  const name = $("wname").value.trim();
  if(!name){ $("savemsg").textContent = "Name the wantlist first."; return; }
  if(!CHECKED.size){ $("savemsg").textContent = "Tick at least one channel."; return; }
  $("savemsg").textContent = "saving\u2026";
  const picked = CHANNELS.filter(c => CHECKED.has(c.key));
  let text = picked.map(c => c.name).join("\n") + "\n";
  try{
    const existingResp = await fetch("/api/wantlists/"+encodeURIComponent(name));
    if(existingResp.ok){
      const ex = await existingResp.json();
      // Duplicates are resolved by the wantlist parser itself (first
      // occurrence wins, by normalised key) -- appending naively here is
      // safe and keeps this page from needing its own normalisation logic.
      text = (ex.text || "").replace(/\n?$/, "\n") +
        "\n# added from the channel browser (" + new Date().toISOString().slice(0,10) + ")\n" + text;
    }
  }catch(e){ /* no existing list -- fine, save as new */ }
  const r = await fetch("/api/wantlists/"+encodeURIComponent(name), {method:"POST",
    headers:{"Content-Type":"application/json"}, body: JSON.stringify({text})});
  const d = await r.json();
  $("savemsg").textContent = d.ok
    ? ("saved to '"+d.name+"' -- ")
    : ("error: "+(d.error||"failed"));
  if(d.ok){
    $("savemsg").innerHTML = "saved to '"+esc(d.name)+"' \u2014 <a href=\"/wantlists\">open it</a>";
  }
  loadWantlistNames();
});

loadProviders(); loadWantlistNames();
</script></body></html>
"""


def browse_page():
    return (BROWSE_PAGE
            .replace("__TOPBAR__", topbar("browse channels", active="browse"))
            .replace("__CSS__", CSS).replace("__EXTRA__", BROWSE_EXTRA))


LINEUPS_EXTRA = NEWRUN_EXTRA + r"""
.lu{border:1px solid var(--line);border-radius:var(--radius);background:var(--bg2);
  padding:11px 13px;margin-bottom:10px}
.lu .hd{display:flex;gap:10px;align-items:baseline}
.lu .hd b{font-size:14px}
.lu .hd .m{color:var(--faint);font-size:11.5px;flex:1}
.lu .cfg{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 6px}
.lu .cfg span{background:var(--bg);border:1px solid var(--line);border-radius:20px;
  padding:2px 9px;font-size:11.5px;color:var(--dim)}
.lu .cfg span b{color:var(--text);font-weight:600}
.prefs{margin-top:8px;border-top:1px solid rgba(255,255,255,.05);padding-top:8px}
.prefs table{width:100%;border-collapse:collapse;font-size:12px}
.prefs td{padding:3px 6px 3px 0;border-bottom:1px solid rgba(255,255,255,.04)}
.prefs td.k{color:var(--dim);font-family:ui-monospace,Menlo,Consolas,monospace}
.prefs td.x{width:1%;text-align:right}
.prefs button{font-size:11px;padding:1px 7px}
.togg{cursor:pointer;color:var(--accent);font-size:11.5px;background:none;border:0;padding:0}
.schedrow{display:flex;gap:7px;align-items:center;font-size:12px;color:var(--dim);
  margin:2px 0 6px}
.schedrow select{width:auto;min-width:0;padding:3px 6px;font-size:12px}
"""

LINEUPS_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>probarr &middot; lineups</title><style>__CSS____EXTRA__</style></head><body>

__TOPBAR__

<div class="page">
  <div class="card">
    <h2>Lineups</h2>
    <div class="lead">A lineup is the durable thing a run is a snapshot of &mdash;
      "my channels", not "the run from Tuesday". It holds the configuration
      a run starts from, and the per-channel decisions (name, group, guide
      source) that every later run inherits instead of asking again.</div>
    <div id="list"><div class="muted">loading&hellip;</div></div>
  </div>

  <div class="card">
    <h2 id="edithead">New lineup</h2>
    <div class="lead" id="editlead">Give it a name and the configuration its runs
      should start from. Everything except the name is optional and can be
      changed later.</div>

    <div class="field">
      <div class="lab">Name</div>
      <div class="ctl"><input type="text" id="name" placeholder="e.g. uk-channels"></div>
    </div>
    <div class="field">
      <div class="lab">Provider</div>
      <div class="ctl"><select id="provider"><option value="">Choose when starting a run</option></select></div>
    </div>
    <div class="field">
      <div class="lab">Channels</div>
      <div class="ctl"><select id="wantlist"><option value="">All channels in the source</option></select></div>
    </div>
    <div class="field">
      <div class="lab">Guide (EPG)</div>
      <div class="ctl"><select id="epgselect"><option value="">No guide</option></select>
        <a href="/providers#epg-sources" target="_blank" style="font-size:12px;margin-left:8px">
          add or remove a guide source&hellip;</a></div>
    </div>
    <div class="field">
      <div class="lab">Regions</div>
      <div class="ctl"><input type="text" id="regions" placeholder="e.g. UK (optional)"></div>
    </div>
    <div class="field">
      <div class="lab">Re-verify</div>
      <div class="ctl">
        <select id="schedule" style="max-width:210px;display:inline-block">
          <option value="0">Never &mdash; only when I start a run</option>
          <option value="1">Every day</option>
          <option value="7">Every week</option>
          <option value="14">Every fortnight</option>
          <option value="30">Every month</option>
        </select>
        <select id="sched-day" style="max-width:130px;display:none">
          <option value="0">on Monday</option><option value="1">on Tuesday</option>
          <option value="2">on Wednesday</option><option value="3">on Thursday</option>
          <option value="4">on Friday</option><option value="5">on Saturday</option>
          <option value="6">on Sunday</option>
        </select>
        <select id="sched-hour" style="max-width:110px;display:none"></select>
        <div class="miniline">Streams rot quietly: the pick that was clean a
          month ago is often dead now. A scheduled run never starts while
          another run or probe is in flight, because it holds the provider's
          connection for as long as it takes.</div>
      </div>
    </div>
    <div class="startbar">
      <button class="primary" id="save">Save lineup</button>
      <button id="cancel" style="display:none">Cancel</button>
      <span class="muted" id="savemsg"></span>
    </div>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);
function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;")
  .replace(/>/g,"&gt;").replace(/"/g,"&quot;");}
let LINEUPS = [], PROVIDERS = [];

// days|weekday. A weekly cadence names its night, because "every 7 days"
// starting from whenever you happened to save is not a schedule anyone means.
const SCHED_OPTS = [["0|0","never"],["1|0","every day"],
  ["7|0","every Monday"],["7|1","every Tuesday"],["7|2","every Wednesday"],
  ["7|3","every Thursday"],["7|4","every Friday"],["7|5","every Saturday"],
  ["7|6","every Sunday"],["14|0","every fortnight"],["30|0","every month"]];
function schedValue(lu){
  const d = lu.schedule_days || 0;
  return d + "|" + (d === 7 ? (lu.schedule_weekday || 0) : 0);
}

async function loadOptions(){
  const [p, w, e] = await Promise.all([
    (await fetch("/api/providers")).json(),
    (await fetch("/api/wantlists")).json(),
    (await fetch("/api/epg-sources")).json()]);
  PROVIDERS = p.providers;
  $("provider").innerHTML = '<option value="">Choose when starting a run</option>' +
    p.providers.map(x => '<option value="'+esc(x.name)+'">'+esc(x.name)+'</option>').join("");
  $("wantlist").innerHTML = '<option value="">All channels in the source</option>' +
    w.wantlists.map(x => '<option value="'+esc(x.name)+'">'+esc(x.name)+
      ' ('+x.channels+' channels)</option>').join("");
  $("epgselect").innerHTML = '<option value="">No guide</option>' +
    e.epg_sources.map(x => '<option value="'+esc(x.url)+'">'+esc(x.name)+'</option>').join("");
}

// The whole point of a lineup is the decisions it accumulates, so they are
// shown in the list rather than hidden behind an edit screen -- otherwise
// "what has this lineup actually learned" is unanswerable from the UI.
function prefRows(lu){
  const keys = Object.keys(lu.preferences || {});
  if(!keys.length) return '<div class="muted">No per-channel decisions yet. '+
    'Renaming a channel, setting its group or picking its guide source in '+
    'Curate records one here.</div>';
  return '<table>' + keys.sort().map(k => {
    const p = lu.preferences[k] || {};
    const bits = Object.keys(p).sort().map(f =>
      esc(f)+': <b>'+esc(String(p[f]))+'</b>').join(" &middot; ");
    return '<tr><td class="k">'+esc(k)+'</td><td>'+bits+
      '</td><td class="x"><button data-clear="'+esc(lu.name)+'" data-key="'+
      esc(k)+'">forget</button></td></tr>';
  }).join("") + '</table>';
}

function render(){
  if(!LINEUPS.length){
    $("list").innerHTML = '<div class="muted">No lineups yet. Create one below, '+
      'then start a run from it.</div>';
    return;
  }
  $("list").innerHTML = LINEUPS.map(lu => {
    const nprefs = Object.keys(lu.preferences || {}).length;
    const cfg = [];
    if(lu.provider || lu.source)
      cfg.push('<span>provider <b>'+esc(lu.provider || lu.source)+'</b></span>');
    if(lu.wantlist) cfg.push('<span>channels <b>'+esc(lu.wantlist)+'</b></span>');
    if(lu.epg) cfg.push('<span>guide <b>'+esc(lu.epg)+'</b></span>');
    if(lu.regions) cfg.push('<span>regions <b>'+esc(lu.regions)+'</b></span>');
    else if(!lu.wantlist)
      // The same combination that caused a real 1,203-candidate run this
      // session -- "all channels" with no Regions filter -- but here it's
      // silent: no tag at all where a set one would show, indistinguishable
      // from "deliberately not needed" at a glance. Every OTHER run started
      // from this lineup inherits this until someone notices, so it's
      // worth flagging every time the lineup list is viewed, not just once.
      cfg.push('<span style="border-color:var(--warn);color:var(--warn)">'+
        'no regions set — all channels, all countries</span>');
    if(lu.schedule_days){
      const DAY=["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"];
      const hh=String(lu.schedule_hour==null?2:lu.schedule_hour).padStart(2,"0");
      cfg.push('<span>re-verify <b>'+
        (lu.schedule_days===1 ? 'daily'
         : lu.schedule_days===7 ? DAY[lu.schedule_weekday||0]+"s"
         : 'every '+lu.schedule_days+' days')+' at '+hh+':00</b></span>');
    }
    if(!cfg.length) cfg.push('<span>no saved configuration yet</span>');
    const runs = lu.runs || [];
    return '<div class="lu"><div class="hd"><b>'+esc(lu.name)+'</b>'+
      '<div class="m">'+runs.length+' run'+(runs.length===1?'':'s')+
      (lu.last_run ? ' &middot; last '+esc(lu.last_run) : '')+' &middot; '+
      nprefs+' remembered decision'+(nprefs===1?'':'s')+'</div>'+
      '<a href="/new?lineup='+encodeURIComponent(lu.name)+
        '"><button class="primary">New run</button></a>'+
      '<button data-edit="'+esc(lu.name)+'">Edit</button>'+
      '<button data-del="'+esc(lu.name)+'">Delete</button></div>'+
      '<div class="cfg">'+cfg.join("")+'</div>'+
      // On the lineup itself, not buried in the edit form. Re-verifying is
      // the thing a lineup DOES; making it reachable only through a screen
      // headed "New lineup" meant the setting could not be found at all.
      '<div class="schedrow">Re-verify '+
        '<select data-sch="'+esc(lu.name)+'">'+SCHED_OPTS.map(o =>
          '<option value="'+o[0]+'"'+(o[0]===schedValue(lu)?' selected':'')+
          '>'+o[1]+'</option>').join("")+'</select> '+
        '<select data-schh="'+esc(lu.name)+'"'+
          (lu.schedule_days?'':' style="display:none"')+'>'+
          Array.from({length:24},(_,h)=>'<option value="'+h+'"'+
            ((lu.schedule_hour==null?2:lu.schedule_hour)===h?' selected':'')+
            '>at '+String(h).padStart(2,"0")+':00</option>').join("")+
        '</select>'+
        '<button class="togg" data-once="'+esc(lu.name)+'" '+
          'title="Re-verify this lineup once, tonight at 2am, refreshing the '+
          'run you already have rather than making a new one \u2014 your '+
          'picks, groups and renames all stay.">'+
          (lu.run_once_at ? "one-off scheduled \u2014 cancel"
                          : "or run once tonight at 2am")+'</button>'+
        '<span class="muted" data-schmsg="'+esc(lu.name)+'"></span></div>'+
      (runs.length ? '<div class="muted">'+runs.slice(0,4).map(r =>
        '<a href="/run/'+encodeURIComponent(r)+'/curate">'+esc(r)+'</a>').join(" &middot; ")+
        '</div>' : '')+
      '<div class="prefs"><button class="togg" data-prefs="'+esc(lu.name)+
        '">'+nprefs+' remembered decision'+(nprefs===1?'':'s')+' &mdash; show</button>'+
      '<div id="pf-'+esc(lu.name)+'" style="display:none;margin-top:6px">'+
        prefRows(lu)+'</div></div></div>';
  }).join("");
}

async function load(){
  const d = await (await fetch("/api/lineups", {cache:"no-store"})).json();
  LINEUPS = d.lineups || [];
  render();
}

$("list").addEventListener("click", async e => {
  const t = e.target.closest("button"); if(!t) return;
  if(t.dataset.prefs){
    const box = $("pf-"+t.dataset.prefs);
    const on = box.style.display === "none";
    box.style.display = on ? "block" : "none";
    t.innerHTML = t.innerHTML.replace(on ? "show" : "hide", on ? "hide" : "show");
    return;
  }
  if(t.dataset.edit){
    const lu = LINEUPS.find(x => x.name === t.dataset.edit); if(!lu) return;
    $("name").value = lu.name;
    $("provider").value = lu.provider || "";
    $("wantlist").value = lu.wantlist || "";
    $("epgselect").value = lu.epg || "";
    $("regions").value = lu.regions || "";
    $("schedule").value = String(lu.schedule_days || 0);
    $("sched-day").value = String(lu.schedule_weekday || 0);
    $("sched-hour").value = String(lu.schedule_hour == null ? 2 : lu.schedule_hour);
    schedVis();
    $("edithead").textContent = "Edit " + lu.name;
    $("editlead").textContent = "The name identifies the lineup, so changing it "+
      "creates a separate one rather than renaming this.";
    $("cancel").style.display = "";
    window.scrollTo(0, document.body.scrollHeight);
    return;
  }
  if(t.dataset.del){
    if(!confirm("Delete lineup \"" + t.dataset.del + "\"?\n\n" +
                "Its remembered per-channel decisions go with it. Runs made "+
                "from it are not touched.")) return;
    await fetch("/api/lineups/"+encodeURIComponent(t.dataset.del),
      {method:"POST", headers:{"Content-Type":"application/json"},
       body:JSON.stringify({delete:true})});
    load();
    return;
  }
  if(t.dataset.clear){
    await fetch("/api/lineups/"+encodeURIComponent(t.dataset.clear),
      {method:"POST", headers:{"Content-Type":"application/json"},
       body:JSON.stringify({clear_preference:t.dataset.key})});
    const open = $("pf-"+t.dataset.clear).style.display !== "none";
    await load();
    if(open) $("pf-"+t.dataset.clear).style.display = "block";
  }
});

$("list").addEventListener("click", async e=>{
  const b = e.target.closest("button[data-once]"); if(!b) return;
  const name = b.dataset.once;
  const lu = LINEUPS.find(x => x.name === name); if(!lu) return;
  let at = 0;
  if(!lu.run_once_at){
    // The next 02:00 from now, so asking at half past midnight means
    // tonight and asking at lunchtime means the coming night.
    const d = new Date(); d.setHours(2, 0, 0, 0);
    if(d.getTime() <= Date.now()) d.setDate(d.getDate() + 1);
    at = Math.round(d.getTime() / 1000);
    if(!confirm("Re-verify \u201c"+name+"\u201d once, at "+
                d.toLocaleString()+"?\n\nIt refreshes the run you already "+
                "have, so every pick, group and rename stays. It pauses by "+
                "itself if anyone is watching."))
      return;
  }
  await fetch("/api/lineups/"+encodeURIComponent(name), {method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({run_once_at: at})});
  load();
});

$("list").addEventListener("change", async e=>{
  const t = e.target;
  const name = t.dataset.sch || t.dataset.schh;
  if(!name) return;
  const lu = LINEUPS.find(x => x.name === name); if(!lu) return;
  const cad = document.querySelector('[data-sch="'+CSS.escape(name)+'"]').value.split("|");
  const hourEl = document.querySelector('[data-schh="'+CSS.escape(name)+'"]');
  const msg = document.querySelector('[data-schmsg="'+CSS.escape(name)+'"]');
  const days = parseInt(cad[0], 10) || 0;
  hourEl.style.display = days ? "" : "none";
  msg.textContent = "saving\u2026";
  const r = await fetch("/api/lineups/"+encodeURIComponent(name), {method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({schedule_days: days,
                          schedule_weekday: parseInt(cad[1], 10) || 0,
                          schedule_hour: parseInt(hourEl.value, 10) || 0})});
  const d = await r.json();
  msg.textContent = d.error ? ("error: "+d.error)
    : (days ? "saved" : "off");
  Object.assign(lu, {schedule_days: days,
                     schedule_weekday: parseInt(cad[1], 10) || 0,
                     schedule_hour: parseInt(hourEl.value, 10) || 0});
  setTimeout(()=>{ if(msg.textContent==="saved"||msg.textContent==="off")
                     msg.textContent=""; }, 2500);
});

$("cancel").addEventListener("click", ()=>{
  ["name","regions"].forEach(k => $(k).value = "");
  ["provider","wantlist","epgselect"].forEach(k => $(k).value = "");
  $("schedule").value = "0"; schedVis();
  $("edithead").textContent = "New lineup";
  $("cancel").style.display = "none";
  $("savemsg").textContent = "";
});

$("save").addEventListener("click", async ()=>{
  const name = $("name").value.trim();
  if(!name){ $("savemsg").textContent = "A name is required."; return; }
  $("save").disabled = true; $("savemsg").textContent = "saving…";
  const r = await fetch("/api/lineups", {method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({name: name, provider: $("provider").value,
      // The NAME only: a lineup stores which provider to use, and the
      // address behind it stays server-side.
      source: "",
      wantlist: $("wantlist").value, epg: $("epgselect").value,
      regions: $("regions").value.trim(),
      schedule_days: parseInt($("schedule").value, 10) || 0,
      schedule_weekday: parseInt($("sched-day").value, 10) || 0,
      schedule_hour: parseInt($("sched-hour").value, 10) || 0})});
  const d = await r.json();
  $("save").disabled = false;
  $("savemsg").textContent = d.error ? ("error: "+d.error) : "saved";
  if(!d.error){ $("cancel").click(); load(); }
});

function schedVis(){
  const n = parseInt($("schedule").value, 10) || 0;
  $("sched-day").style.display = n === 7 ? "inline-block" : "none";
  $("sched-hour").style.display = n ? "inline-block" : "none";
}
$("sched-hour").innerHTML = Array.from({length:24}, (_,h) =>
  '<option value="'+h+'"'+(h===2?' selected':'')+'>at '+
  String(h).padStart(2,"0")+':00</option>').join("");
$("schedule").addEventListener("change", schedVis);
schedVis();

loadOptions().then(load);
</script></body></html>
"""


def lineups_page():
    return (LINEUPS_PAGE
            .replace("__TOPBAR__", topbar("lineups", active="lineups"))
            .replace("__CSS__", CSS).replace("__EXTRA__", LINEUPS_EXTRA))
