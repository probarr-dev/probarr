"""Self-contained HTML contact sheet.

The reason this exists: some stream faults are only detectable by a human
looking at a picture. A feed can respond correctly, decode without a single
error, carry accurate metadata, and be showing entirely the wrong programme --
the guide says one film, a different film is playing. No amount of probing
finds that. A grid of thumbnails finds it in about two seconds.

So the sheet is not a report. It is an input device: every candidate stream
for every channel, stamped with what verification measured, with the tool's
own pick pre-selected and one click to overrule it.

Output is one file with the images embedded, so it survives being copied to
another machine, and it carries only redacted URLs so it can be shared without
handing over a subscription.
"""
import base64
import html
import json
import os
import time

from . import rank as rank_mod
from .theme import CSS, topbar


def _thumb_data_uri(path):
    try:
        with open(path, "rb") as f:
            return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()
    except OSError:
        return None


def build_payload(by_channel, store, embed=True, channel_titles=None):
    channels = []
    for key, records in sorted(by_channel.items()):
        ranked = rank_mod.rank(records)
        cands = []
        for i, r in enumerate(ranked):
            thumb = None
            if r.get("thumb"):
                abs_thumb = os.path.join(store.dir, r["thumb"])
                thumb = _thumb_data_uri(abs_thumb) if embed else r["thumb"]
            cands.append({
                "id": r.get("rec_key") or r["stream_id"],
                "stream_id": r["stream_id"],
                "name": r.get("stream_name", ""),
                "url": r.get("url_redacted", ""),
                "status": r.get("status", "dead"),
                "reason": r.get("reason", ""),
                "w": r.get("width", 0), "h": r.get("height", 0),
                "fps": r.get("fps", 0),
                "kbps": r.get("measured_kbps", 0),
                "declared_kbps": r.get("declared_kbps", 0),
                "vcodec": r.get("video_codec", ""),
                "acodec": r.get("audio_codec", ""),
                "ach": r.get("audio_channels", 0),
                "errors": r.get("decode_errors", 0),
                "corrupt": r.get("corruption_errors", 0),
                "dup": r.get("placeholder_group"),
                "lowmo": bool(r.get("low_motion")),
                "motion": r.get("motion"),
                "flat": bool(r.get("low_contrast")),
                "abr": bool(r.get("multi_bitrate_manifest")),
                "dashabr": bool(r.get("dash_multi_bitrate")),
                "slowfetch": bool(r.get("slow_fetch")),
                "rank": i + 1,
                "thumb": thumb,
            })
        title = (channel_titles or {}).get(key) or _prettify(key, records)
        channels.append({
            "key": key,
            "title": title,
            "why": rank_mod.explain_choice(ranked),
            "candidates": cands,
        })
    return {
        "run_id": store.run_id,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "meta": store.read_meta(),
        "channels": channels,
    }


def _prettify(key, records):
    """A readable channel title. The normalised key is a matching artefact, not a name."""
    for r in records:
        n = r.get("stream_name") or ""
        if n:
            return n
    return key


HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ChannelIQ contact sheet &middot; __RUN__</title>
<style>__CSS__</style></head><body>

__TOPBAR__
<div class="filters">
  <input type="search" id="q" placeholder="Filter channels or streams&hellip;">
  <div class="toggles">
    <label><input type="checkbox" id="f-hidedead"> hide dead</label>
    <label><input type="checkbox" id="f-dupes"> only placeholders</label>
    <label><input type="checkbox" id="f-problem"> only channels needing review</label>
    <label><input type="checkbox" id="f-included"> only included</label>
  </div>
  <div class="spacer"></div>
  <button id="reset">Reset to auto-pick</button>
</div>

<div class="stats" id="stats"></div>
<main id="grid"></main>

<footer class="bar">
  <div id="selsum"></div>
  <div class="spacer"></div>
  <button id="copy">Copy picks as JSON</button>
  <button class="primary" id="download">Download picks</button>
</footer>

<div class="lightbox" id="lb"><img alt=""><div class="cap"></div></div>

<script>
const DATA = __DATA__;
const LSKEY = "channeliq:sel:" + DATA.run_id;

// Selection state: {channelKey: {include, primary, fallback}}
let SEL = {};

function autoPick(ch){
  const usable = ch.candidates.filter(c => c.status === "ok" || c.status === "dirty");
  return {
    include: usable.length > 0 && usable[0].status === "ok",
    primary: usable[0] ? usable[0].id : null,
    fallback: usable[1] ? usable[1].id : null,
  };
}
function resetSel(){
  SEL = {};
  DATA.channels.forEach(ch => SEL[ch.key] = autoPick(ch));
  save(); render();
}
function load(){
  try{
    const s = JSON.parse(localStorage.getItem(LSKEY) || "null");
    if (s && typeof s === "object"){ SEL = s; }
  }catch(e){}
  DATA.channels.forEach(ch => { if(!SEL[ch.key]) SEL[ch.key] = autoPick(ch); });
}
function save(){ try{ localStorage.setItem(LSKEY, JSON.stringify(SEL)); }catch(e){} }

// A channel "needs review" when the tool is not confident: nothing clean, or
// the winning frame duplicates another channel's picture, or the top two
// candidates are close enough that the choice is arguably arbitrary.
function needsReview(ch){
  const usable = ch.candidates.filter(c => c.status === "ok");
  if (usable.length === 0) return true;
  if (ch.candidates.some(c => c.dup || c.lowmo)) return true;
  if (usable[0] && usable[0].flat) return true;
  return false;
}

function specs(c){
  const out = [];
  if (c.w) out.push({t: c.w + "\\u00d7" + c.h + (c.fps ? "@" + c.fps : ""), hi: true});
  if (c.kbps) out.push({t: c.kbps + " kbps", hi: true});
  if (c.vcodec) out.push({t: c.vcodec});
  if (c.acodec) out.push({t: c.acodec + (c.ach ? " " + c.ach + "ch" : "")});
  if (c.corrupt) out.push({t: c.corrupt + " corrupt", err: true});
  else if (c.errors) out.push({t: c.errors + " err"});
  if (c.dup) out.push({t: "provider placeholder", err: true});
  else if (c.lowmo) out.push({t: "low motion \u2014 check picture", err: true});
  if (c.flat) out.push({t: "low contrast", err: true});
  if (c.dashabr) out.push({t: "DASH multi-bitrate", err: true});
  else if (c.abr) out.push({t: "multi-bitrate manifest", warn: true});
  if (c.slowfetch) out.push({t: "slow fetch", warn: true});
  return out;
}

function cardHTML(ch, c){
  const sel = SEL[ch.key] || {};
  const cls = ["card"];
  if (sel.primary === c.id) cls.push("chosen");
  if (sel.fallback === c.id) cls.push("fallback");
  const thumb = c.thumb
    ? '<img loading="lazy" src="' + c.thumb + '" alt="" data-full="' + c.thumb +
      '" data-cap="' + esc(c.name) + '">'
    : '<div class="noframe">no frame<br>' + esc(c.reason || c.status) + '</div>';
  return '<div class="' + cls.join(" ") + '" data-id="' + c.id + '" data-ch="' + esc(ch.key) + '">' +
    '<div class="thumbwrap">' + thumb +
      '<div class="pill ' + c.status + '">' + c.status + '</div>' +
      '<div class="rank' + (c.rank === 1 ? ' r1' : '') + '">#' + c.rank + '</div>' +
      (c.dup ? '<div class="dupflag">placeholder ' + c.dup + '</div>' : '') +
    '</div><div class="cbody">' +
      '<div class="sname" title="' + esc(c.name) + '">' + esc(c.name) + '</div>' +
      '<div class="specs">' + specs(c).map(s =>
          '<span class="spec' + (s.hi ? ' hi' : '') + (s.err ? ' err' : '') +
          (s.warn ? ' warn2' : '') + '">' +
          esc(s.t) + '</span>').join("") + '</div>' +
      '<div class="actions">' +
        '<button data-act="primary">Primary</button>' +
        '<button data-act="fallback">Fallback</button>' +
      '</div>' +
    '</div></div>';
}

function esc(s){ return String(s == null ? "" : s)
  .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }

function visibleChannels(){
  const q = document.getElementById("q").value.trim().toLowerCase();
  const onlyDupes = document.getElementById("f-dupes").checked;
  const onlyProblem = document.getElementById("f-problem").checked;
  const onlyIncluded = document.getElementById("f-included").checked;
  return DATA.channels.filter(ch => {
    if (onlyDupes && !ch.candidates.some(c => c.dup || c.lowmo)) return false;
    if (onlyProblem && !needsReview(ch)) return false;
    if (onlyIncluded && !(SEL[ch.key] || {}).include) return false;
    if (!q) return true;
    if (ch.title.toLowerCase().includes(q) || ch.key.toLowerCase().includes(q)) return true;
    return ch.candidates.some(c => c.name.toLowerCase().includes(q));
  });
}

function render(){
  const hideDead = document.getElementById("f-hidedead").checked;
  const chans = visibleChannels();
  const grid = document.getElementById("grid");
  grid.innerHTML = chans.length ? chans.map(ch => {
    const sel = SEL[ch.key] || {};
    let cands = ch.candidates;
    if (hideDead) cands = cands.filter(c => !["dead","no_video","no_frame"].includes(c.status));
    return '<section class="channel' + (sel.include ? '' : ' excluded') + '" data-ch="' + esc(ch.key) + '">' +
      '<div class="chead">' +
        '<input type="checkbox" data-act="include"' + (sel.include ? ' checked' : '') + '>' +
        '<h2>' + esc(ch.title) + '</h2>' +
        '<span class="why">' + esc(ch.why) + '</span>' +
        '<span class="spacer"></span>' +
        '<span class="why">' + ch.candidates.length + ' candidates' +
          (needsReview(ch) ? ' &middot; needs review' : '') + '</span>' +
      '</div>' +
      '<div class="cards">' + cands.map(c => cardHTML(ch, c)).join("") + '</div>' +
    '</section>';
  }).join("") : '<div class="empty">Nothing matches the current filters.</div>';
  renderStats(chans);
}

function renderStats(shown){
  const all = DATA.channels;
  const clean = all.filter(ch => ch.candidates.some(c => c.status === "ok")).length;
  const review = all.filter(needsReview).length;
  const cands = all.reduce((n, ch) => n + ch.candidates.length, 0);
  const dupes = new Set();
  all.forEach(ch => ch.candidates.forEach(c => { if (c.dup) dupes.add(c.dup); }));
  document.getElementById("stats").innerHTML =
    '<div><b>' + all.length + '</b>channels</div>' +
    '<div><b>' + cands + '</b>candidates probed</div>' +
    '<div><b>' + clean + '</b>with a clean stream</div>' +
    '<div><b>' + review + '</b>needing review</div>' +
    '<div><b>' + dupes.size + '</b>placeholder groups</div>' +
    '<div><b>' + shown.length + '</b>shown</div>';
  const inc = Object.values(SEL).filter(s => s.include).length;
  const fb = Object.values(SEL).filter(s => s.include && s.fallback).length;
  document.getElementById("selsum").textContent =
    inc + " channels selected, " + fb + " with a fallback stream";
}

function selectionJSON(){
  const out = {run_id: DATA.run_id, generated: new Date().toISOString(), channels: []};
  DATA.channels.forEach(ch => {
    const s = SEL[ch.key] || {};
    if (!s.include) return;
    const find = id => ch.candidates.find(c => c.id === id) || null;
    const p = find(s.primary), f = find(s.fallback);
    out.channels.push({
      key: ch.key, title: ch.title,
      primary: p ? {id: p.id, name: p.name} : null,
      fallback: f ? {id: f.id, name: f.name} : null,
    });
  });
  return JSON.stringify(out, null, 2);
}

document.addEventListener("click", e => {
  const img = e.target.closest(".thumbwrap img");
  if (img){
    const lb = document.getElementById("lb");
    lb.querySelector("img").src = img.dataset.full;
    lb.querySelector(".cap").textContent = img.dataset.cap;
    lb.classList.add("on");
    return;
  }
  if (e.target.closest("#lb")){ document.getElementById("lb").classList.remove("on"); return; }

  const btn = e.target.closest("button[data-act]");
  if (btn){
    const card = btn.closest(".card");
    const ch = card.dataset.ch, id = card.dataset.id;
    SEL[ch] = SEL[ch] || {};
    if (btn.dataset.act === "primary"){
      SEL[ch].primary = SEL[ch].primary === id ? null : id;
      if (SEL[ch].fallback === id) SEL[ch].fallback = null;
      SEL[ch].include = true;
    } else {
      SEL[ch].fallback = SEL[ch].fallback === id ? null : id;
      if (SEL[ch].primary === id) SEL[ch].primary = null;
    }
    save(); render(); return;
  }
  const inc = e.target.closest('input[data-act="include"]');
  if (inc){
    const ch = inc.closest(".channel").dataset.ch;
    SEL[ch] = SEL[ch] || {};
    SEL[ch].include = inc.checked;
    save(); render();
  }
});

["q","f-hidedead","f-dupes","f-problem","f-included"].forEach(id => {
  document.getElementById(id).addEventListener("input", render);
});
document.getElementById("reset").addEventListener("click", resetSel);
document.getElementById("copy").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(selectionJSON());
        document.getElementById("copy").textContent = "Copied"; 
        setTimeout(() => document.getElementById("copy").textContent = "Copy picks as JSON", 1500);
  } catch(e){ alert(selectionJSON()); }
});
document.getElementById("download").addEventListener("click", () => {
  const blob = new Blob([selectionJSON()], {type: "application/json"});
  const a = document.createElement("a");
  // NOT "selection.json": the contact sheet is written into the run's own
  // directory, right next to the real selection.json the app reads back --
  // and this file is a flat report ({run_id, generated, channels:[...]}),
  // a completely different shape. Downloading it and saving it in the
  // obvious place would silently overwrite the run's actual curation with
  // something read_selection() would parse as garbage channel keys.
  a.href = URL.createObjectURL(blob); a.download = "contact-sheet-picks.json";
  document.body.appendChild(a); a.click(); a.remove();
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape") document.getElementById("lb").classList.remove("on");
});

load(); render();
</script></body></html>
"""


def render(by_channel, store, out_path, embed=True, channel_titles=None,
           served=False):
    """Write the contact sheet.

    served=True adds navigation and a link back to the run's curation view.
    The default writes the portable copy: one file that can be moved to another
    machine, where links to a server that is not running would be broken.
    """
    payload = build_payload(by_channel, store, embed=embed, channel_titles=channel_titles)
    right = (f'<a href="/run/{store.run_id}/curate"><button class="primary">'
             f'Curate</button></a>' if served else "")
    doc = (HTML
           .replace("__TOPBAR__", topbar(f"contact sheet &middot; run {store.run_id}",
                                         right=right, home=served))
           .replace("__CSS__", CSS)
           .replace("__DATA__", json.dumps(payload, ensure_ascii=False))
           .replace("__RUN__", html.escape(store.run_id))
           .replace("__GEN__", html.escape(payload["generated"])))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(doc)
    return out_path, payload
