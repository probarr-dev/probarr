"""The setup wizard: blank instance to a curated first run, one screen at a
time.

Every piece this walks through already has its own full page (Providers,
Wantlists, EPG sources, New Run, Curate) -- this is not a replacement for
any of them, it is the on-ramp a brand-new install has never had. Someone
who has never used probarr before lands on an empty nav bar with six
destinations and no obvious order to visit them in; this imposes the order
that actually works (a source before a wantlist means something before a
run means something), does the real work through the exact same API
endpoints those pages use, and ends by explaining what Curate is showing
before dropping the operator into it.

Manually launched only (see Settings/nav), never forced on anyone -- an
operator who already knows the shape of the tool does not want to be
walked through it.
"""
from .theme import CSS, topbar
from .pages import WANTLIST_EXTRA

EXTRA_CSS = WANTLIST_EXTRA + """
.wizwrap{max-width:720px;margin:0 auto}
.wizsteps{display:flex;gap:4px;margin-bottom:18px;flex-wrap:wrap}
.wizstep-dot{flex:1;min-width:70px;text-align:center;padding:7px 4px;font-size:11px;
  border-radius:var(--radius);background:var(--panel);border:1px solid var(--line);
  color:var(--faint)}
.wizstep-dot.done{background:var(--accent2);border-color:var(--accent2);color:#04222c;font-weight:600}
.wizstep-dot.current{border-color:var(--accent2);color:var(--text);font-weight:600}
.wiz-step{display:none}
.wiz-step.on{display:block}
.wizrow{display:flex;gap:10px;margin-top:14px}
.wizrow .spacer{flex:1}
.wizskip{font-size:12px;color:var(--faint);background:none;border:0;cursor:pointer;
  text-decoration:underline}
.wizskip:hover{color:var(--text)}
.wizok{color:var(--accent2);font-size:12.5px;margin-top:8px}
.wizprogress{background:var(--bg2);border:1px solid var(--line);border-radius:var(--radius);
  padding:10px 12px;font-size:12.5px;margin-top:12px}
.wizexplain{background:var(--bg2);border:1px solid var(--line);border-radius:var(--radius);
  padding:12px 14px;margin-bottom:14px}
.wizexplain dt{font-weight:600;margin-top:10px}
.wizexplain dt:first-child{margin-top:0}
.wizexplain dd{color:var(--dim);margin:2px 0 0;font-size:13px}
.pwrap{position:relative;display:flex;gap:8px;align-items:center}
.pwrap input{flex:1}
.testresult{display:none;font-size:12.5px;margin-top:8px;padding:8px 10px;
  border-radius:var(--radius)}
.testresult.show{display:block}
.testresult.good{background:rgba(39,194,76,.1);border:1px solid var(--ok);color:var(--ok)}
.testresult.bad{background:rgba(240,80,80,.1);border:1px solid var(--bad);color:var(--bad)}
.hint2{color:var(--faint);font-size:11.5px;margin-top:6px}
.pbar{height:8px;border-radius:4px;background:var(--bg2);overflow:hidden;border:1px solid var(--line)}
.pbar > div{height:100%;background:var(--accent2);width:0%;transition:width .3s}
.pstats{display:flex;gap:16px;font-size:12.5px;color:var(--dim);margin:8px 0}
.plog{background:#000;border:1px solid var(--line);border-radius:var(--radius);
  padding:8px 10px;font:11.5px/1.5 ui-monospace,Menlo,Consolas,monospace;color:#8fdc9a;
  max-height:140px;overflow-y:auto;white-space:pre-wrap}
"""

WIZARD_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>probarr &middot; setup wizard</title><style>__CSS____EXTRA__</style></head><body>

__TOPBAR__

<div class="page wizwrap">

  <div class="wizsteps" id="wizsteps"></div>

  <div class="wiz-step" id="wiz-provider">
    <div class="card">
      <h2>1. Add your provider</h2>
      <div class="lead">The playlist or Xtream login your subscription gave you.
        This is the source every run probes.</div>
      <div class="row" style="margin-bottom:10px">
        <input type="text" id="wp-name" placeholder="Name, e.g. My IPTV">
      </div>
      <div class="row" style="margin-bottom:8px">
        <input type="text" id="wp-url" style="flex:1"
          placeholder="Playlist URL, or just the provider's host/domain">
      </div>
      <div class="pwrap">
        <input type="text" id="wp-user" placeholder="Username (only if not already in the URL)">
        <input type="password" id="wp-pass" style="flex:1"
          placeholder="Password (only if not already in the URL)">
      </div>
      <div class="hint2">Paste the full playlist URL your provider gave you (username/password
        stay blank) &mdash; or, if you were given an Xtream login instead, just the
        host/domain plus your username and password.</div>
      <div class="testresult" id="wp-result"></div>
      <div class="wizrow">
        <button id="wp-test">Test connection</button>
        <span class="spacer"></span>
        <button class="primary" id="wp-save">Save and continue</button>
      </div>
    </div>
  </div>

  <div class="wiz-step" id="wiz-dispatcharr">
    <div class="card">
      <h2>2. Connect Dispatcharr</h2>
      <div class="lead">Optional &mdash; skip this entirely if you're only using probarr
        to export an M3U file. Lets probarr push curated channels back into
        Dispatcharr.</div>
      <div class="row" style="margin-bottom:10px">
        <input type="text" id="wd-name" placeholder="Name, e.g. My Dispatcharr">
      </div>
      <div class="row" style="margin-bottom:8px">
        <input type="text" id="wd-host" placeholder="IP or hostname" style="flex:1">
        <input type="number" id="wd-port" placeholder="Port" style="width:110px" value="9191">
      </div>
      <div class="pwrap">
        <input type="text" id="wd-user" placeholder="Username">
        <input type="password" id="wd-pass" style="flex:1" placeholder="Password">
      </div>
      <div class="hint2">Its own admin login, not the Xtream/M3U playback credentials.</div>
      <label class="hint2" style="display:flex;align-items:center;gap:6px;margin-top:10px">
        <input type="checkbox" id="wd-assource" style="width:auto" checked>
        Also use Dispatcharr as a provider (offer it as something a run can probe from)
      </label>
      <div class="testresult" id="wd-result"></div>
      <div class="wizrow">
        <button id="wd-test">Test connection</button>
        <span class="spacer"></span>
        <button class="wizskip" id="wd-skip">Skip this step</button>
        <button class="primary" id="wd-save">Save and continue</button>
      </div>
    </div>
  </div>

  <div class="wiz-step" id="wiz-wantlist">
    <div class="card">
      <h2>3. Which channels?</h2>
      <div class="lead">Optional. Leave this out and a run probes <b>every</b> channel
        the provider carries &mdash; fine for a small provider, slow for a
        large aggregated one. A wantlist narrows a run to just the channels
        you actually want, one name per line.</div>
      <div id="ww-fromdisp" style="display:none;margin-bottom:12px">
        <button id="ww-pulldisp">I've already got Dispatcharr set up with the channels I watch &mdash; pull them in</button>
        <div class="hint2">Reads every channel already in Dispatcharr's active lineup right now
          and fills the list below with their names, exactly as Dispatcharr has them &mdash;
          nothing is changed in Dispatcharr itself. Still worth a look before saving: a name
          here is what the provider must be probed under, and Dispatcharr's own channel names
          don't always match the provider's.</div>
      </div>
      <div class="row" style="margin-bottom:8px">
        <input type="text" id="ww-name" placeholder="Name, e.g. my-channels">
      </div>
      <textarea id="ww-body" placeholder="BBC One&#10;BBC Two&#10;ITV1&#10;Channel 4&#10;&hellip;"
        style="min-height:160px"></textarea>
      <div class="hint2">A richer starter list (by country/provider) is also available from
        the <a href="/wantlists" target="_blank">Wantlists page</a> if you'd rather browse one
        than type your own &mdash; come back here once it's saved.</div>
      <div class="testresult" id="ww-result"></div>
      <div class="wizrow">
        <span class="spacer"></span>
        <button class="wizskip" id="ww-skip">Skip &mdash; probe everything</button>
        <button class="primary" id="ww-save">Save and continue</button>
      </div>
    </div>
  </div>

  <div class="wiz-step" id="wiz-epg">
    <div class="card">
      <h2>4. A guide (EPG) source</h2>
      <div class="lead">Optional. An XMLTV URL lets probarr record what the guide said
        should be playing at the exact moment each frame was captured &mdash;
        the fastest way to catch a stream that is alive but showing the
        wrong channel entirely.</div>
      <div class="row" style="margin-bottom:10px">
        <input type="text" id="we-name" placeholder="Name, e.g. uk-guide">
        <input type="text" id="we-url" placeholder="XMLTV URL (.xml or .xml.gz)" style="flex:1;min-width:220px">
      </div>
      <div class="testresult" id="we-result"></div>
      <div class="wizrow">
        <span class="spacer"></span>
        <button class="wizskip" id="we-skip">Skip this step</button>
        <button class="primary" id="we-save">Save and continue</button>
      </div>
    </div>
  </div>

  <div class="wiz-step" id="wiz-run">
    <div class="card">
      <h2>5. Start your first run</h2>
      <div class="lead">This probes every candidate stream your provider offers for
        each wanted channel, capturing a picture and measuring quality for
        each one &mdash; usually a few seconds to a few minutes per channel.</div>
      <div id="wr-summary" class="wizprogress"></div>
      <div class="testresult" id="wr-result" style="margin-top:10px"></div>
      <div id="wr-progresswrap" style="display:none;margin-top:12px">
        <div class="pbar"><div id="wr-pbarfill"></div></div>
        <div class="pstats"><span id="wr-pstate"></span></div>
        <div class="plog" id="wr-plog"></div>
      </div>
      <div class="wizrow">
        <span class="spacer"></span>
        <button class="primary" id="wr-start">Start verifying</button>
      </div>
    </div>
  </div>

  <div class="wiz-step" id="wiz-curate">
    <div class="card">
      <h2>6. Reading Curate</h2>
      <div class="lead">Your run is done. Here's what you're about to see, channel by channel.</div>
      <dl class="wizexplain">
        <dt>Candidate cards, ranked</dt>
        <dd>Every stream your provider offered for a channel, best-ranked first
          &mdash; a screenshot, resolution/bitrate, and any problems found
          (corruption, wrong aspect ratio, low motion).</dd>
        <dt>+ Add to channel / Remove from channel</dt>
        <dd>What gets pushed to Dispatcharr (or exported), in the order shown.
          A clean top candidate is picked automatically; add or remove others
          as you see fit.</dd>
        <dt>Guide at probe time</dt>
        <dd>What the EPG said should be airing the instant this exact frame was
          captured, right next to the picture &mdash; the fastest way to catch
          a channel that's alive but simply wrong.</dd>
        <dt>Delete stream</dt>
        <dd>Removes one candidate for good, with an optional reason. The Find
          streams search can always bring it back later if you change your mind.</dd>
        <dt>Diagnose this channel</dt>
        <dd>Re-scans every candidate with a longer sample and a watchable clip
          &mdash; for a channel that misbehaves in a real player and a still
          frame doesn't explain why.</dd>
        <dt>Export to Dispatcharr</dt>
        <dd>Pushes your curated picks, with a preview of exactly what will
          change before anything actually happens.</dd>
      </dl>
      <div class="wizrow">
        <span class="spacer"></span>
        <button class="primary" id="wc-go">Open Curate</button>
      </div>
    </div>
  </div>

</div>

<script>
const $ = id => document.getElementById(id);
const STEPS = ["provider", "dispatcharr", "wantlist", "epg", "run", "curate"];
const STEP_LABELS = {provider: "Provider", dispatcharr: "Dispatcharr",
  wantlist: "Channels", epg: "Guide", run: "First run", curate: "Curate"};
let STEP_I = 0;
let RUN_ID = null;

function renderSteps(){
  $("wizsteps").innerHTML = STEPS.map((s,i) =>
    '<div class="wizstep-dot '+(i<STEP_I?"done":i===STEP_I?"current":"")+'">'+
    (i+1)+". "+STEP_LABELS[s]+"</div>").join("");
}
function goto(i){
  STEP_I = i;
  document.querySelectorAll(".wiz-step").forEach(el => el.classList.remove("on"));
  $("wiz-"+STEPS[i]).classList.add("on");
  renderSteps();
  window.scrollTo({top:0, behavior:"smooth"});
  // Only worth offering once Dispatcharr is actually connected -- step 2 is
  // still on the SAME page (every step's DOM stays mounted, just hidden),
  // so its own name field is readable directly rather than re-fetching
  // /api/providers to find out what step 2 just saved.
  if(STEPS[i] === "wantlist")
    $("ww-fromdisp").style.display = $("wd-name").value.trim() ? "block" : "none";
}
renderSteps();
goto(0);

// -- Step 1: provider (M3U/Xtream) --------------------------------------
function computeProviderSpec(){
  const url = $("wp-url").value.trim();
  const user = $("wp-user").value.trim(), pass = $("wp-pass").value.trim();
  if(!url) return "";
  if(user || pass){
    const hostport = url.replace(/^https?:\/\//i, "").replace(/\/.*$/, "");
    return "xtream://"+encodeURIComponent(user)+":"+encodeURIComponent(pass)+"@"+hostport;
  }
  return url;
}
$("wp-test").addEventListener("click", async ()=>{
  const spec = computeProviderSpec();
  const box = $("wp-result");
  if(!spec){ box.className="testresult show bad"; box.textContent="Enter a provider address first."; return; }
  box.className="testresult show"; box.textContent="Testing…";
  try{
    const r = await fetch("/api/providers/test", {method:"POST",
      headers:{"Content-Type":"application/json"}, body:JSON.stringify({spec})});
    const d = await r.json();
    box.className = "testresult show " + (d.ok ? "good" : "bad");
    box.textContent = d.ok ? "Connected — "+d.channels+" streams found." : "Could not connect: "+d.error;
  }catch(e){ box.className="testresult show bad"; box.textContent="Request failed."; }
});
$("wp-save").addEventListener("click", async ()=>{
  const name = $("wp-name").value.trim(), spec = computeProviderSpec();
  const box = $("wp-result");
  if(!name || !spec){
    box.className = "testresult show bad";
    box.textContent = !name ? "Name is required." : "Fill in the provider's address first.";
    return;
  }
  box.className = "testresult show"; box.textContent = "Saving…";
  const r = await fetch("/api/providers/"+encodeURIComponent(name), {method:"POST",
    headers:{"Content-Type":"application/json"}, body: JSON.stringify({spec})});
  const d = await r.json();
  if(!d.ok){ box.className="testresult show bad"; box.textContent="error: "+(d.error||"failed"); return; }
  box.className="testresult show good"; box.textContent="Saved.";
  setTimeout(()=>goto(1), 400);
});

// -- Step 2: Dispatcharr (optional) --------------------------------------
function computeDispSpec(){
  const host = $("wd-host").value.trim(), port = $("wd-port").value.trim();
  const user = $("wd-user").value.trim(), pass = $("wd-pass").value.trim();
  if(!host) return "";
  return "dispatcharr://"+encodeURIComponent(user)+":"+encodeURIComponent(pass)+
    "@"+host+(port?":"+port:"");
}
$("wd-test").addEventListener("click", async ()=>{
  const spec = computeDispSpec();
  const box = $("wd-result");
  if(!spec){ box.className="testresult show bad"; box.textContent="Enter Dispatcharr's host first."; return; }
  box.className="testresult show"; box.textContent="Testing…";
  try{
    const r = await fetch("/api/providers/test", {method:"POST",
      headers:{"Content-Type":"application/json"}, body:JSON.stringify({spec})});
    const d = await r.json();
    box.className = "testresult show " + (d.ok ? "good" : "bad");
    box.textContent = d.ok ? "Connected — "+d.channels+" streams found." : "Could not connect: "+d.error;
  }catch(e){ box.className="testresult show bad"; box.textContent="Request failed."; }
});
$("wd-skip").addEventListener("click", ()=>goto(2));
$("wd-save").addEventListener("click", async ()=>{
  const name = $("wd-name").value.trim(), spec = computeDispSpec();
  const box = $("wd-result");
  if(!name || !spec){
    box.className = "testresult show bad";
    box.textContent = !name ? "Name is required." : "Fill in Dispatcharr's address first.";
    return;
  }
  box.className = "testresult show"; box.textContent = "Saving…";
  const r = await fetch("/api/providers/"+encodeURIComponent(name), {method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({spec, as_source: $("wd-assource").checked})});
  const d = await r.json();
  if(!d.ok){ box.className="testresult show bad"; box.textContent="error: "+(d.error||"failed"); return; }
  box.className="testresult show good"; box.textContent="Saved.";
  setTimeout(()=>goto(2), 400);
});

// -- Step 3: wantlist (optional) -----------------------------------------
$("ww-pulldisp").addEventListener("click", async ()=>{
  const dispName = $("wd-name").value.trim();
  const btn = $("ww-pulldisp"), box = $("ww-result");
  if(!dispName) return;
  btn.disabled = true; btn.textContent = "Reading Dispatcharr…";
  box.className = "testresult show"; box.textContent = "";
  try{
    const r = await fetch("/api/browse", {method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({provider: dispName, active_only: true})});
    const d = await r.json();
    if(d.error){ box.className="testresult show bad"; box.textContent=d.error; }
    else if(!d.channels || !d.channels.length){
      box.className = "testresult show bad";
      box.textContent = "Dispatcharr has no channels in its active lineup yet — "+
        "nothing to pull in. Skip this step, or type your own list below.";
    } else {
      $("ww-body").value = d.channels.map(c=>c.name).join("\n");
      if(!$("ww-name").value.trim()) $("ww-name").value = "dispatcharr-channels";
      box.className = "testresult show good";
      box.textContent = "Pulled "+d.channels.length+" channel(s) from Dispatcharr — "+
        "check the list below, then Save and continue.";
    }
  }catch(e){ box.className="testresult show bad"; box.textContent="Request failed."; }
  btn.disabled = false; btn.textContent =
    "I've already got Dispatcharr set up with the channels I watch — pull them in";
});
$("ww-skip").addEventListener("click", ()=>goto(3));
$("ww-save").addEventListener("click", async ()=>{
  const name = $("ww-name").value.trim(), body = $("ww-body").value;
  const box = $("ww-result");
  if(!name || !body.trim()){
    box.className = "testresult show bad";
    box.textContent = !name ? "Name is required." : "Add at least one channel name, or Skip.";
    return;
  }
  box.className = "testresult show"; box.textContent = "Saving…";
  const r = await fetch("/api/wantlists/"+encodeURIComponent(name), {method:"POST",
    headers:{"Content-Type":"application/json"}, body: JSON.stringify({text: body})});
  const d = await r.json();
  if(!d.ok){ box.className="testresult show bad"; box.textContent="error: "+(d.error||"failed"); return; }
  box.className="testresult show good"; box.textContent="Saved.";
  setTimeout(()=>goto(3), 400);
});

// -- Step 4: EPG source (optional) ---------------------------------------
$("we-skip").addEventListener("click", ()=>goto(4));
$("we-save").addEventListener("click", async ()=>{
  const name = $("we-name").value.trim(), url = $("we-url").value.trim();
  const box = $("we-result");
  if(!name || !url){
    box.className = "testresult show bad";
    box.textContent = "Name and URL are both required, or Skip.";
    return;
  }
  box.className = "testresult show"; box.textContent = "Saving…";
  const r = await fetch("/api/epg-sources/"+encodeURIComponent(name), {method:"POST",
    headers:{"Content-Type":"application/json"}, body: JSON.stringify({url})});
  const d = await r.json();
  if(!d.ok){ box.className="testresult show bad"; box.textContent="error: "+(d.error||"failed"); return; }
  box.className="testresult show good"; box.textContent="Saved.";
  setTimeout(()=>goto(4), 400);
});

// -- Step 5: first run ----------------------------------------------------
async function loadRunSummary(){
  const [p, w, e] = await Promise.all([
    (await fetch("/api/providers")).json(),
    (await fetch("/api/wantlists")).json(),
    (await fetch("/api/epg-sources")).json()]);
  const prov = (p.providers || []).find(x => x.as_source !== false);
  const want = (w.wantlists || [])[$("ww-name").value.trim() ? 0 : -1];
  const wantSaved = (w.wantlists || []).find(x => x.name === $("ww-name").value.trim());
  const epgSaved = (e.epg_sources || []).find(x => x.name === $("we-name").value.trim());
  $("wr-summary").innerHTML =
    "<b>Provider:</b> " + (prov ? esc(prov.name) : "<span style=\"color:var(--bad)\">none saved — go back</span>") + "<br>" +
    "<b>Channels:</b> " + (wantSaved ? esc(wantSaved.name)+" ("+wantSaved.channels+" channels)" : "all channels (no wantlist)") + "<br>" +
    "<b>Guide:</b> " + (epgSaved ? esc(epgSaved.name) : "none");
  $("wr-start").disabled = !prov;
  return {provider: prov, wantlist: wantSaved, epg: epgSaved};
}
function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");}
$("wr-start").addEventListener("click", async ()=>{
  const ctx = await loadRunSummary();
  if(!ctx.provider) return;
  $("wr-start").disabled = true;
  $("wr-result").className = "testresult show"; $("wr-result").textContent = "Starting…";
  const r = await fetch("/api/runs/start", {method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({provider: ctx.provider.name,
                         wantlist: ctx.wantlist ? ctx.wantlist.name : "",
                         epg: ctx.epg ? ctx.epg.name : ""})});
  const d = await r.json();
  if(!d.ok){ $("wr-result").className="testresult show bad"; $("wr-result").textContent="error: "+(d.error||"failed");
    $("wr-start").disabled=false; return; }
  RUN_ID = d.run_id;
  $("wr-result").className = "testresult";
  $("wr-progresswrap").style.display = "";
  pollRun();
});
function pollRun(){
  const poller = setInterval(async ()=>{
    let d;
    try{ d = await (await fetch("/api/run/"+encodeURIComponent(RUN_ID)+"/progress",
                                {cache:"no-store"})).json(); }
    catch(e){ return; }
    if(d.error){ $("wr-pstate").textContent = "error: "+d.error; clearInterval(poller); return; }
    const p = d.progress;
    if(p){
      const pct = p.total ? Math.round(100*p.done/p.total) : 0;
      $("wr-pbarfill").style.width = pct+"%";
      $("wr-pstate").textContent = p.done+"/"+p.total+" probed";
    }
    $("wr-plog").textContent = (d.log||[]).slice(-6).join("\n");
    if(d.state === "done" || d.state === "error" || d.state === "stopped"){
      clearInterval(poller);
      if(d.state === "done") setTimeout(()=>goto(5), 600);
    }
  }, 1200);
}
$("wc-go").addEventListener("click", ()=>{
  if(RUN_ID) location.href = "/run/"+encodeURIComponent(RUN_ID)+"/curate";
});

loadRunSummary();
</script></body></html>
"""


def wizard_page():
    return (WIZARD_PAGE
            .replace("__TOPBAR__", topbar("setup wizard", active="wizard"))
            .replace("__CSS__", CSS).replace("__EXTRA__", EXTRA_CSS))
