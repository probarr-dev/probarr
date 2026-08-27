"""The curation view: wantlist on the left, candidate frames on the right.

The contact sheet is one long page, which is right for scanning a whole run at
a glance and wrong for working through two hundred channels one at a time.
This view is built for the second job: pick a channel, look at its candidates,
choose, move on -- driven from the keyboard so a long list does not become an
afternoon of clicking.

The EPG line above the frames is what makes the hardest check possible. probarr
records what the guide said should be playing at the exact moment each frame
was captured, so the question "is this actually the channel it claims to be?"
becomes a glance rather than an investigation.
"""
import json
import os

from . import rank as rank_mod
from .theme import CSS, topbar

EXTRA_CSS = """
html,body{height:100%}
body{display:flex;flex-direction:column;overflow:hidden}
.wrap{flex:1;display:flex;min-height:0}
aside{width:320px;flex:none;border-right:1px solid var(--line);background:var(--bg2);
  display:flex;flex-direction:column;min-height:0}
aside .tools{padding:9px 10px;border-bottom:1px solid var(--line);display:flex;
  flex-direction:column;gap:7px}
aside .tools input[type=search]{width:100%}
.searchrow{display:flex;gap:6px;align-items:center}
.searchrow input[type=search]{flex:1;min-width:0}
.addmenu-wrap{position:relative;flex:none}
.iconbtn{width:29px;height:29px;padding:0;font-size:16px;line-height:1;
  display:flex;align-items:center;justify-content:center}
.addmenu{display:none;position:absolute;top:calc(100% + 4px);right:0;z-index:20;
  background:var(--panel2);border:1px solid var(--line);border-radius:var(--radius);
  box-shadow:0 6px 18px rgba(0,0,0,.35);padding:5px;min-width:200px;
  flex-direction:column;gap:3px}
.addmenu.on{display:flex}
.addmenu button{width:100%;text-align:left;font-size:12px;padding:7px 9px;
  background:transparent;border:1px solid transparent}
.addmenu button:hover{background:var(--panel);border-color:var(--line)}
.toolrow{display:flex;gap:7px}
.toolrow button{flex:1}
.chips{display:flex;gap:4px;flex-wrap:wrap}
.chip{font-size:11px;padding:3px 8px;border:1px solid var(--line);border-radius:11px;
  cursor:pointer;color:var(--dim);background:var(--panel);user-select:none}
.chip.on{background:var(--accent2);border-color:var(--accent2);color:#04222c;font-weight:600}
.chanlist{overflow-y:auto;flex:1;min-height:0}
.chan{display:flex;gap:8px;align-items:center;padding:7px 10px;cursor:pointer;
  border-bottom:1px solid rgba(255,255,255,.03);font-size:13px}
.chan:hover{background:var(--panel)}
.chan.sel{background:var(--panel2);box-shadow:inset 3px 0 0 var(--accent)}
.chan .num{color:var(--faint);font-size:11px;min-width:30px;font-variant-numeric:tabular-nums}
.chan .num.nonum{color:#fff;background:var(--bad);font-weight:700;letter-spacing:.3px;
  padding:1px 5px;border-radius:3px;min-width:auto}
.dhead .num.nonum{display:inline-block;color:#fff;background:var(--bad);font-weight:700;
  font-size:13px;letter-spacing:.3px;padding:2px 7px;border-radius:3px;vertical-align:middle}
.chlogo{height:18px;width:18px;object-fit:contain;flex:none;background:var(--bg);
  border-radius:3px}
.chlogo-empty{visibility:hidden}
.chan .nm{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.chan.missing .nm{color:var(--faint);font-style:italic}
.chan.marked{background:rgba(53,197,240,.10);box-shadow:inset 3px 0 0 var(--dup)}
.dot{width:8px;height:8px;border-radius:50%;flex:none}
.dot.ok{background:var(--ok)}.dot.review{background:var(--warn)}
.dot.bad{background:var(--bad)}.dot.off{background:var(--faint)}
.chan .cnt{color:var(--faint);font-size:11px;font-variant-numeric:tabular-nums}
main.detail{flex:1;overflow-y:auto;min-height:0;padding:14px 16px 20px}
.dhead{margin-bottom:12px}
.dhead h1{margin:0 0 4px;font-size:20px;display:flex;align-items:center;gap:10px}
.dhlogo{height:34px;width:34px;object-fit:contain;flex:none;background:var(--bg2);
  border-radius:5px}
#titletext{cursor:pointer;border-bottom:1px dashed transparent}
#titletext:hover{border-bottom-color:var(--faint)}
#titleedit{background:none;border:0;color:var(--faint);cursor:pointer;font-size:14px;
  padding:0 0 0 6px;vertical-align:1px}
#titleedit:hover{color:var(--accent)}
.dhead .sub{color:var(--dim);font-size:12px;margin-bottom:8px}
#groupedit{background:none;border:0;color:var(--faint);cursor:pointer;font-size:12px;
  padding:0 0 0 4px;vertical-align:-1px}
#groupedit:hover{color:var(--accent)}
#diagnosebtn,#epgcheckbtn,#removechanbtn,#dupchanbtn,
#watermarkbtn,#clearwatermarkbtn,#changesbtn,
#findstreamsbtn{
  font-size:12px;padding:5px 10px;margin-right:8px}
#removechanbtn{border-color:var(--bad);color:var(--bad)}
#removechanbtn:hover{background:var(--bad);color:#3a0000}
/* What the guide said was airing at THIS candidate's own probe moment --
   the channel-level summary this used to sit under is gone (the modal's
   own per-source EPG check plus this per-candidate line cover the same
   ground without a third, redundant place to look). */
.cand-epg{margin-top:5px;padding:4px 8px;background:var(--bg2);
  border-left:2px solid var(--accent);border-radius:3px;font-size:11.5px;
  color:var(--dim);display:flex;gap:6px;align-items:baseline;flex-wrap:wrap}
.cand-epg .lbl{color:var(--faint);text-transform:uppercase;font-size:9.5px;
  letter-spacing:.4px;flex:none}
.cand-epg .ttl{color:var(--text);font-weight:600}
/* A list, not a grid. The order of the list IS the channel's stream order,
   which is how Dispatcharr stores a channel anyway -- so what you drag is
   literally what gets pushed, and there is no longer a hard limit of two.
   The picture stays: it is the whole reason to look at this screen. */
.cands{display:flex;flex-direction:column;gap:6px}
.cand{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
  overflow:hidden;display:flex;align-items:stretch;gap:0}
.cand.chosen{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset}
.cand.unused{opacity:.58}
.cand.unused:hover{opacity:.85}
.cand.dragging{opacity:.4}
.cand.dropinto{border-color:var(--accent2);box-shadow:0 -2px 0 var(--accent2) inset}
/* Diagnose/Find-streams progress: which candidate is being scanned right
   now, and a brief flash on whichever one just landed a fresh result --
   so a multi-candidate scan reads as a live, moving process rather than a
   silent wait that only resolves at the very end. */
.cand.probing{border-color:var(--accent2);
  box-shadow:0 0 0 2px var(--accent2) inset,0 0 10px 0 var(--accent2);
  animation:cand-probing-pulse 1.3s ease-in-out infinite}
@keyframes cand-probing-pulse{
  0%,100%{box-shadow:0 0 0 2px var(--accent2) inset,0 0 4px 0 var(--accent2)}
  50%{box-shadow:0 0 0 2px var(--accent2) inset,0 0 14px 2px var(--accent2)}}
.cand.just-scanned{animation:cand-just-scanned 1.5s ease-out}
@keyframes cand-just-scanned{0%{background:var(--accent2)}100%{background:var(--panel)}}
.cand .grip{width:26px;flex:none;display:flex;align-items:center;justify-content:center;
  color:var(--faint);cursor:grab;font-size:13px;user-select:none;background:var(--bg2)}
.cand.unused .grip{cursor:default;color:transparent}
.cand .pos{width:30px;flex:none;display:flex;align-items:center;justify-content:center;
  font-size:14px;font-weight:700;color:var(--accent);background:var(--bg2)}
.cand.unused .pos{color:var(--faint);font-weight:400;font-size:12px}
.cand .shot{position:relative;width:150px;flex:none;aspect-ratio:16/9;background:#000;
  cursor:zoom-in}
.cand .shot img{width:100%;height:100%;object-fit:contain;display:block}
/* The marked watermark area, cropped from this candidate's own frame --
   deliberately the same height as .shot (align-items:stretch on .cand
   already gives it that, for free) so it reads as a direct side-by-side,
   not a different-sized afterthought. Width is whatever the crop's own
   aspect ratio needs, not fixed -- a logo box is rarely 16:9.
   overflow:hidden is load-bearing, not decorative: with no fixed height
   of its own (only align-items:stretch on .cand giving it one) and an
   <img> sized purely by height:100%/width:auto, the image's rendered box
   can disagree with its flex parent's actual computed size -- confirmed
   live, it visually bled out of its own slot and sat on top of
   neighbouring candidate text instead of being confined to its column.
   cursor:zoom-in matches .shot's own affordance now that this is
   click-to-enlarge too. */
.cand .wmshot{flex:none;background:#000;display:flex;align-items:center;
  justify-content:center;border-left:1px solid var(--line);overflow:hidden;
  max-width:140px;cursor:zoom-in}
.cand .wmshot img{height:100%;width:auto;max-width:100%;max-height:100%;
  object-fit:contain;display:block}
.cand .wmshot.wmshot-empty{width:40px}
.cand .wmshot.wmshot-empty img{display:none}
.cand .cbody{flex:1;min-width:0;padding:7px 10px;display:flex;flex-direction:column;
  justify-content:center;gap:4px}
.cand .actions{display:flex;gap:5px;flex-wrap:wrap;align-items:center}
.cand .actions button{font-size:11.5px;padding:3px 8px}
@media(max-width:860px){.cand .shot{width:104px}}
/* Curate was built around a fixed 320px sidebar sitting beside the detail
   pane -- fine on a desktop window, but on a phone-width viewport 320px
   alone eats nearly the whole screen, crushing the detail pane (where the
   actual pictures live, the entire point of this page) into an unusable
   sliver. Stacking below this width is a pragmatic fix, not a full mobile
   redesign: the channel list gets a bounded, independently-scrollable
   height above the detail pane rather than the two fighting over width
   that doesn't exist. */
@media(max-width:760px){
  .wrap{flex-direction:column}
  aside{width:100%;max-height:38vh}
  main.detail{width:100%}
}
.kbd{position:absolute;bottom:6px;right:6px;background:rgba(0,0,0,.75);color:var(--dim);
  font-size:10px;padding:2px 6px;border-radius:3px;font-family:ui-monospace,monospace}
.empty{color:var(--dim);text-align:center;padding:60px 20px}
.hint{color:var(--faint);font-size:11.5px;margin-top:14px}
.hint code{background:var(--panel2);padding:1px 5px;border-radius:3px}
.lb2{position:fixed;inset:0;background:rgba(0,0,0,.94);display:none;flex-direction:column;
  align-items:center;justify-content:center;z-index:200;gap:10px}
.lb2.on{display:flex}
.lb2 img{max-width:96vw;max-height:80vh;object-fit:contain;background:#000}
/* A watermark crop's max-width/max-height alone do nothing useful here --
   those only ever SHRINK an oversized image, and a marked area is usually
   a few dozen pixels natively, well under either limit already. Forcing
   an explicit width is what actually makes "enlarged" mean anything for
   an image this small; the browser's own upscaling handles the rest.
   Softness at this size is expected and inherent to the source
   resolution, not a bug -- the point is making it BIG enough to look at,
   not making it look native-resolution-sharp. */
.lb2 img.wm-big{width:50vw;max-width:50vw;height:auto;max-height:80vh;
  object-fit:contain;image-rendering:pixelated}
.lb2 .bar2{display:flex;gap:8px;align-items:center;color:var(--dim);font-size:12px}
.saveind{font-size:11px;color:var(--faint)}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.7);display:none;
  align-items:center;justify-content:center;z-index:150}
.modal.on{display:flex}
.modalbox{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
  width:460px;max-width:92vw;max-height:88vh;overflow-y:auto;padding:18px 20px}
.modalbox h3{margin:0 0 4px;font-size:16px}
.modalbox{position:relative}
.modalx{position:absolute;top:12px;right:14px;background:none;border:0;
  color:var(--faint);font-size:15px;cursor:pointer;padding:2px 4px}
.modalx:hover{color:var(--text)}
.modalbox .sub{color:var(--dim);font-size:12px;margin-bottom:14px}
.mfield{margin-bottom:14px}
.mfield label{display:block;font-size:12.5px;font-weight:600;margin-bottom:5px}
.mfield select,.mfield input[type=text]{width:100%;background:var(--bg);color:var(--text);
  border:1px solid var(--line);border-radius:var(--radius);padding:7px 9px;font-size:13px}
.fbchoice{display:flex;flex-direction:column;gap:8px}
.fbopt{display:flex;gap:8px;align-items:flex-start;background:var(--bg2);
  border:1px solid var(--line);border-radius:var(--radius);padding:9px 10px;cursor:pointer}
.fbopt input{margin-top:3px}
.fbopt.checked{border-color:var(--accent)}
.fbopt .t{font-size:13px;font-weight:600}
.fbopt .d{font-size:11.5px;color:var(--dim);margin-top:2px}
.mrow{display:flex;gap:8px;justify-content:flex-end;margin-top:16px}
.mresult{margin-top:14px;padding:10px 12px;border-radius:var(--radius);font-size:12.5px;
  display:none;white-space:pre-wrap}
.mresult.show{display:block}
.mresult.good{background:rgba(39,194,76,.1);border:1px solid var(--ok)}
.mresult.bad{background:rgba(240,80,80,.1);border:1px solid var(--bad)}
.noprov{color:var(--dim);font-size:13px}
.noprov a{color:var(--accent)}
.em-sources{display:flex;flex-direction:column;gap:8px}
.em-src{display:flex;gap:10px;align-items:center;background:var(--bg2);
  border:1px solid var(--line);border-radius:var(--radius);padding:9px 10px}
.em-src.current{border-color:var(--accent)}
.em-src .name{font-size:12.5px;font-weight:600;min-width:110px}
.em-guidechan{font-size:10.5px;font-weight:400;color:var(--faint);margin-top:1px}
.em-src .prog{flex:1;font-size:12px;color:var(--dim)}
.em-src .prog .t{color:var(--text);font-weight:600}
.em-src .nomatch{color:var(--faint);font-style:italic}
.em-src button{font-size:11px;padding:4px 9px}
.em-captured{font-size:12px;color:var(--dim)}
.em-captured .t{color:var(--text);font-weight:600}
.em-current-tag{font-size:10.5px;color:var(--accent);margin-left:6px;font-weight:600}
.em-logo-current{display:flex;align-items:center;gap:10px;background:var(--bg2);
  border:1px solid var(--line);border-radius:var(--radius);padding:8px 10px;
  font-size:12px;color:var(--dim);margin-bottom:8px}
.em-logo-current img{height:32px;width:32px;object-fit:contain;background:var(--bg);
  border-radius:4px}
.em-logo-current .none{font-style:italic;color:var(--faint)}
.em-logo-choices{display:flex;flex-wrap:wrap;gap:8px}
.em-logo-opt{display:flex;flex-direction:column;align-items:center;gap:4px;
  width:74px;background:var(--bg2);border:1px solid var(--line);
  border-radius:var(--radius);padding:6px;cursor:pointer;text-align:center}
.em-logo-opt:hover{border-color:var(--accent)}
.em-logo-opt.picked{border-color:var(--accent);background:rgba(80,140,255,.08)}
.em-logo-opt img{height:34px;width:100%;object-fit:contain;background:var(--bg);
  border-radius:3px}
.em-logo-opt .lbl{font-size:9.5px;color:var(--dim);line-height:1.25;
  overflow:hidden;text-overflow:ellipsis;display:-webkit-box;
  -webkit-line-clamp:2;-webkit-box-orient:vertical;word-break:break-word}
.dm-summary{display:flex;gap:8px;align-items:center;font-size:12.5px;color:var(--dim);
  background:var(--bg2);border:1px solid var(--line);border-radius:var(--radius);
  padding:7px 10px;margin-bottom:10px}
.dm-summary b{color:var(--text)}
.dm-summary .togg{margin-left:auto}
.dm-plan{margin-top:12px;max-height:230px;overflow:auto;display:none}
.dm-plan.show{display:block}
.dm-plan .pcounts{font-size:12px;color:var(--dim);margin-bottom:8px}
.dm-plan .pcounts b{color:var(--text)}
.dm-row.delete .pname,.dm-row.delete .pchg{color:var(--bad)}
.dm-row.dropped .pname,.dm-row.dropped .pchg{color:var(--warn)}
.dm-row{display:flex;gap:8px;align-items:baseline;padding:4px 6px;border-radius:3px;
  font-size:12px;border-left:2px solid transparent}
.dm-row.create{border-left-color:var(--ok);background:rgba(39,194,76,.06)}
.dm-row.update{border-left-color:var(--warn);background:rgba(240,173,78,.06)}
.dm-row.unchanged{opacity:.45}
.dm-row .pname{min-width:150px;font-weight:600}
.dm-row .pchg{color:var(--dim)}
.dm-row .pchg code{color:var(--text);background:var(--bg);padding:0 3px;border-radius:2px}
/* Blocked/relink rows are the ones a push refuses to touch until resolved
   -- they need real space to show what's actually at stake (existing vs
   incoming), not a line squeezed into a 460px popup alongside 140 dimmed
   "no change" rows. See #dispatchmodal .modalbox below. */
.dm-row.blocked{border-left-color:var(--bad);background:rgba(240,80,80,.08);
  flex-direction:column;align-items:stretch;padding:9px 10px;gap:4px}
.dm-row.relink{border-left-color:var(--dup);background:rgba(167,116,217,.08);
  flex-direction:column;align-items:stretch;padding:9px 10px;gap:4px}
.dm-row.blocked .pname,.dm-row.relink .pname{min-width:0}
.dm-row.blocked .pchg{color:var(--bad)}
.dm-row.relink .pchg{color:var(--dup)}
.dm-conflict-detail{font-size:11.5px;color:var(--dim)}
.dm-conflict-actions{display:flex;gap:8px;margin-top:2px}
.dm-conflict-actions button{font-size:11.5px;padding:4px 9px}
.dm-unchanged-count{font-size:12px;color:var(--faint);padding:4px 6px}
.dm-plan .warn{background:rgba(240,173,78,.1);border:1px solid var(--warn);color:var(--warn);
  border-radius:var(--radius);padding:7px 9px;font-size:12px;margin-bottom:8px}
#dispatchmodal .modalbox{width:min(1400px,95vw);max-width:95vw;height:88vh;
  display:flex;flex-direction:column}
#dispatchmodal .dm-plan{flex:1;max-height:none}
.cat-results{max-height:300px;overflow:auto;display:flex;flex-direction:column;gap:4px}
.cat-hit{display:flex;gap:9px;align-items:center;padding:6px 8px;background:var(--bg2);
  border:1px solid var(--line);border-radius:var(--radius);font-size:12.5px;cursor:pointer}
.cat-hit.on{border-color:var(--accent)}
.cat-hit.have{opacity:.5;cursor:default}
.cat-hit .k{font-weight:600;flex:1}
.cat-hit .n{color:var(--dim);font-size:11.5px}
.st-row{display:flex;gap:9px;align-items:center;padding:6px 8px;background:var(--bg2);
  border:1px solid var(--line);border-radius:var(--radius);cursor:pointer}
.st-row.on{border-color:var(--accent)}
.st-row.done{opacity:.62;cursor:default}
.st-row .nm{flex:1;font-size:12.5px}
.st-row .nm em{color:var(--faint);font-style:normal;font-size:11px}
.st-row .vd{color:var(--dim);font-size:11.5px;white-space:nowrap}
.strex{color:var(--bad);font-size:10.5px;margin-left:8px;font-weight:600}
.imp-bar{display:flex;gap:10px;align-items:center;font-size:12px;color:var(--dim);
  margin:2px 0 7px;flex-wrap:wrap}
.imp-bar .imp-note{color:var(--faint);font-size:11.5px;flex-basis:100%}
.st-head{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--faint);
  margin:8px 0 3px}
.dtag.fail{background:rgba(248,81,73,.12);border-color:var(--bad);color:var(--bad)}
.dtag{margin-left:8px;background:var(--bg2);border:1px solid var(--line);
  border-radius:20px;padding:1px 8px;font-size:11px;color:var(--dim)}
.claimtag{font-size:11px;font-weight:400;border-radius:20px;padding:2px 9px;
  vertical-align:middle;white-space:nowrap}
.claimtag-on{background:rgba(39,194,76,.1);border:1px solid var(--ok);color:var(--ok)}
.claimtag-off{background:rgba(240,80,80,.1);border:1px solid var(--bad);color:var(--bad)}
.chpip{margin-left:5px;font-size:9.5px;font-weight:700;color:#3a2200;
  background:var(--warn);border-radius:3px;padding:0 4px;vertical-align:1px}
.whybox{background:var(--bg2);border:1px solid var(--line);border-left:3px solid var(--accent2);
  border-radius:var(--radius);padding:9px 11px;margin-bottom:10px;font-size:12.5px}
.whybox b{display:block;margin-bottom:3px;font-size:12px}
.whybox ul{margin:0 0 7px;padding-left:17px}
.whybox li{margin:1px 0;color:var(--dim)}
.whybox button{font-size:12px;padding:4px 9px}
.grpacc-bar{display:flex;justify-content:space-between;align-items:center;
  margin-bottom:8px;font-size:12px}
.grpsec{border:1px solid var(--line);border-radius:var(--radius);margin-bottom:8px;
  overflow:hidden}
.grpsec.dropover{border-color:var(--accent2);box-shadow:0 0 0 1px var(--accent2) inset}
.grphead{display:flex;align-items:center;gap:10px;padding:9px 12px;background:var(--bg2);
  cursor:pointer;user-select:none}
.grphead .nm{font-weight:600;font-size:13px;flex:1}
.grphead .n{color:var(--faint);font-size:11.5px}
.grphead .plus{font-size:15px;color:var(--faint);width:16px;text-align:center}
.grpdel{font-size:11px;padding:2px 7px;border-color:var(--bad);color:var(--bad)}
.grpdel:hover{background:var(--bad);color:#3a0000}
.grpsec.open .plus{color:var(--accent)}
.grpmove{font-size:11px;padding:2px 8px;display:none}
.grpsec.hasmove .grpmove{display:inline-block}
.grpbody{display:none;padding:6px 8px}
.grpsec.open .grpbody{display:block}
.grprow{display:flex;align-items:center;gap:9px;padding:5px 8px;border-radius:5px;
  cursor:grab;font-size:12.5px}
.grprow input[type=checkbox]{flex:none;margin:0}
.grprow:hover{background:var(--bg2)}
.grprow.picked{background:rgba(88,166,255,.13);outline:1px solid var(--accent2)}
.grprow.dragging{opacity:.35}
.grprow.dropinto{box-shadow:0 -2px 0 var(--accent2) inset}
.grprow .dot{width:7px;height:7px;border-radius:50%;flex:none}
.grprow .num{color:var(--faint);width:34px;text-align:right;font-variant-numeric:tabular-nums;
  flex:none}
.grpempty{color:var(--faint);font-size:12px;padding:10px 8px}
.canddiv{font-size:11.5px;color:var(--faint);padding:8px 4px 5px;border-top:1px dashed var(--line);
  margin-top:4px}
.canddiv b{color:var(--dim)}
.offbox{background:rgba(155,161,170,.1);border:1px solid var(--faint);
  border-radius:var(--radius);padding:9px 11px;margin-bottom:10px;font-size:12.5px;
  color:var(--dim)}
.offbox button{margin-left:10px;font-size:12px;padding:3px 9px}
.chbox{background:rgba(240,173,78,.08);border:1px solid var(--warn);
  border-radius:var(--radius);padding:8px 11px;margin-bottom:10px;font-size:12.5px}
.chbox ul{margin:0;padding-left:17px}
.chbox li{margin:1px 0;color:var(--dim)}
.dpip{margin-left:5px;font-size:9.5px;font-weight:700;color:var(--bg);
  background:var(--dim);border-radius:3px;padding:0 3px;vertical-align:1px}
.grp-list{display:flex;flex-wrap:wrap;gap:6px;max-height:150px;overflow:auto}
.grp-opt{font-size:12px;padding:4px 10px;border:1px solid var(--line);
  border-radius:12px;cursor:pointer;background:var(--bg2)}
.grp-opt.on{border-color:var(--accent);background:var(--panel2);color:var(--text)}
.chan .pend{width:7px;height:7px;border-radius:50%;background:var(--warn);flex:none}
.chan .pend.create{background:var(--ok)}
"""

HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>probarr curate &middot; __RUN__</title><style>__CSS__
__EXTRA__</style></head><body>

__TOPBAR__

<div class="wrap">
  <aside>
    <div class="tools">
      <div class="searchrow">
        <input type="search" id="q" placeholder="Find a channel&hellip;">
        <div class="addmenu-wrap">
          <button id="addmenubtn" class="iconbtn" title="Add channels">+</button>
          <div class="addmenu" id="addmenu">
            <button id="addchannels">+ Add from provider</button>
            <button id="importdispatch"
              title="Read the channels that already exist in Dispatcharr into this run, and probe the provider's alternatives for each.">&darr; Import from Dispatcharr</button>
          </div>
        </div>
      </div>
      <div class="toolrow">
        <button id="opengroups" style="font-size:12px;padding:5px 8px"
          title="See every group and what is in it, drag channels between groups, or drop one channel on another to swap their numbers.">Groups</button>
        <button id="diagfiltered" style="font-size:12px;padding:5px 8px"
          title="Re-scan every candidate for the channels currently shown by this filter/search &mdash; pick which ones before it starts, same as the nightly re-verify but on demand and on a subset.">
          Diagnose these (<span id="diagfilteredcount">0</span>)</button>
      </div>
      <div class="chips" id="chips"></div>
    </div>
    <div class="chanlist" id="chanlist"></div>
  </aside>
  <main class="detail" id="detail"></main>
</div>

<div class="lb2" id="lb2">
  <img alt="">
  <div class="bar2">
    <button id="lbmode">Show 1:1 crop</button>
    <button id="lbclose">Close</button>
    <span id="lbcap"></span>
    <span>&middot; <code>c</code> toggles, Esc closes</span>
  </div>
</div>

<div class="lb2" id="clipviewer">
  <video id="clipvideo" controls autoplay style="max-width:92vw;max-height:80vh;background:#000"></video>
  <div class="bar2">
    <span id="clipcap"></span>
    <span>&middot; Esc closes</span>
  </div>
</div>

<div class="modal" id="dispatchmodal">
  <div class="modalbox">
    <h3 id="dm-title">Export to Dispatcharr</h3>
    <div class="sub" id="dm-sub">Pushes your curated picks into an existing Dispatcharr
      instance -- creates or updates channels, sets streams, links logos,
      re-matches EPG.</div>

    <div id="dm-noprov" class="noprov" style="display:none">
      No Dispatcharr provider saved yet. <a href="/providers">Add one</a> first.
    </div>

    <div id="dm-body" style="display:none">
      <div class="mfield">
        <label>Push into</label>
        <select id="dm-provider"></select>
      </div>

      <div class="dm-summary" id="dm-summary">
        <span id="dm-sumtext"></span>
        <button class="togg" id="dm-more">change</button>
      </div>

      <div id="dm-options" style="display:none">
      <div class="mfield">
        <label>Fallback handling</label>
        <div class="fbchoice">
          <label class="fbopt" data-v="native">
            <input type="radio" name="fbmode" value="native">
            <span><span class="t">Native (one channel, two streams)</span>
              <span class="d">Dispatcharr's own failover switches to the
                fallback automatically. No lineup clutter, but the fallback
                is not individually selectable.</span></span>
          </label>
          <label class="fbopt" data-v="separate">
            <input type="radio" name="fbmode" value="separate">
            <span><span class="t">Separate channel</span>
              <span class="d">A second channel, named "FALLBACK: &hellip;",
                streaming only the fallback. Doubles the lineup but makes it
                visible and selectable by hand.</span></span>
          </label>
        </div>
      </div>

      <div class="mfield">
        <label>Group name</label>
        <input type="text" id="dm-group" placeholder="probarr (__RUN__)">
      </div>

      <div class="mfield">
        <label style="display:flex;gap:7px;align-items:flex-start;font-weight:400">
          <input type="checkbox" id="dm-prune" checked style="margin-top:2px">
          <span><b style="font-size:12.5px">Tidy up emptied groups</b>
            <span class="d" style="display:block;font-size:11.5px;color:var(--dim)">
              Delete any group this push moves the last channel out of. Only
              groups this push empties &mdash; never other empty groups.</span></span>
        </label>
      </div>
      </div>
    </div>

    <div class="mresult" id="dm-result"></div>

    <div id="dm-plan" class="dm-plan"></div>

    <div class="mrow">
      <button id="dm-cancel">Cancel</button>
      <button id="dm-preview" disabled>Preview changes</button>
      <button class="primary" id="dm-push" disabled>Push</button>
    </div>
  </div>
</div>

<div class="modal" id="grpmodal">
  <div class="modalbox">
    <h3 id="grp-title">Set group</h3>
    <div class="sub">Pick an existing group or type a new one. Carried through
      to Dispatcharr on the next push, where it wins over the export form's
      blanket group.</div>
    <div class="mfield">
      <label>Existing groups</label>
      <div id="grp-list" class="grp-list"></div>
    </div>
    <div class="mfield">
      <label>Or a new one</label>
      <input type="text" id="grp-new" placeholder="e.g. Sports">
    </div>
    <div class="mrow">
      <button id="grp-cancel">Cancel</button>
      <button id="grp-clear">Clear group</button>
      <button class="primary" id="grp-save">Set</button>
    </div>
  </div>
</div>

<div class="modal" id="catmodal">
  <div class="modalbox">
    <h3>Add channels from the provider</h3>
    <div class="sub">Searches the provider's ENTIRE catalogue, not just this
      run's wantlist -- for channels you did not think to ask for. Selected
      channels are added to this run and probed in the background, respecting
      your connection limit.</div>
    <div class="mfield">
      <input type="text" id="cat-q" placeholder="Search the catalogue&hellip;">
    </div>
    <div id="cat-results" class="cat-results"></div>
    <div class="mresult" id="cat-result"></div>
    <div class="mrow">
      <button id="cat-close">Close</button>
      <button class="primary" id="cat-add" disabled>Add selected</button>
    </div>
  </div>
</div>

<div class="modal" id="groupsmodal">
  <div class="modalbox" style="width:min(900px,94vw)">
    <button class="modalx" id="groups-x" title="Close">\u2715</button>
    <h3>Groups</h3>
    <div class="sub">Drag a channel onto another group to move it there. Drop
      it on another channel WITHIN the same group to swap their numbers
      &mdash; nothing else is renumbered, so a genre-banded scheme like
      100s/300s/400s stays exactly where you put it. Click rows to select
      several, then use a group's "Move N here" to bulk-move without
      dragging one at a time.</div>
    <div class="grpacc-bar">
      <span style="display:flex;gap:6px">
        <input type="text" id="grpacc-new" placeholder="New group name" style="width:180px">
        <button id="grpacc-add" style="font-size:12px;padding:4px 10px">Add group</button>
      </span>
      <span class="muted" id="grpacc-sel"></span>
      <button class="togg" id="grpacc-expand">expand all</button>
    </div>
    <div id="grpacc"></div>
    <div class="mrow"><button id="groups-close">Close</button></div>
  </div>
</div>

<div class="modal" id="diagmodal">
  <div class="modalbox" style="width:min(640px,94vw)">
    <button class="modalx" id="diag-x" title="Close">✕</button>
    <h3>Diagnose filtered channels</h3>
    <div class="sub">Re-scans every candidate for each ticked channel with a longer
      sample and a kept clip &mdash; the same as the per-channel Diagnose button,
      queued for all of these at once. Untick anything you don't want touched.
      One probe runs at a time on a connection-limited provider, so this can take
      a while for a large selection.</div>
    <div class="mfield" style="margin-bottom:8px">
      <label style="font-weight:400;display:flex;align-items:center;gap:6px">
        <input type="checkbox" id="diag-include-dead" style="width:auto">
        also re-probe candidates that came back dead (slower &mdash; only worth it
        if a slow-starting stream is the actual suspicion)</label>
    </div>
    <div id="diag-list" class="cat-results"></div>
    <div class="mresult" id="diag-result"></div>
    <div class="mrow" style="justify-content:space-between;align-items:center">
      <span class="muted" id="diag-summary"></span>
      <span style="display:flex;gap:8px">
        <button id="diag-cancel">Cancel</button>
        <button class="primary" id="diag-go">Start</button>
      </span>
    </div>
  </div>
</div>

<div class="modal" id="strmodal">
  <div class="modalbox">
    <h3>Streams for <span id="st-title"></span></h3>
    <div class="sub">A run only probes the first few candidates of a pool,
      ordered by their declared quality &mdash; necessary over one connection,
      but it means a better stream can sit here unprobed. Search reaches
      further still: it ignores the matcher entirely, so a variant labelled
      differently enough never to be connected to this channel can be
      attached to it anyway. Ticked streams are probed for THIS channel only.</div>
    <div class="mfield">
      <input type="text" id="st-q" placeholder="Search the whole catalogue by name&hellip;">
    </div>
    <div id="st-results" class="cat-results"></div>
    <div class="mresult" id="st-result"></div>
    <div class="mrow">
      <button id="st-close">Close</button>
      <button class="primary" id="st-go" disabled>Probe selected</button>
    </div>
  </div>
</div>

<div class="modal" id="impmodal">
  <div class="modalbox">
    <h3>Import from Dispatcharr</h3>
    <div class="sub">Reads the channels that already exist in Dispatcharr and
      brings them into this run, keeping their number, name and group. Each one
      is then probed against the provider's candidates for it, so a channel you
      added there by hand can be compared with the alternatives rather than
      just sitting there unexamined. Anything this run has already verified
      is left alone &mdash; only genuinely new channels and streams cost a
      provider connection.</div>
    <div class="mfield">
      <select id="imp-prov"></select>
    </div>
    <div class="mfield" style="font-size:12px">
      <label><input type="checkbox" id="imp-probe" checked>
        Probe the provider's alternatives for each channel</label>
      <div class="sub" style="margin:2px 0 0">Untick to just record what
        Dispatcharr has &mdash; number, group and current stream &mdash;
        without spending a single connection.</div>
    </div>
    <div class="imp-bar" id="imp-bar" style="display:none">
      <span id="imp-count"></span>
      <button class="togg" id="imp-all">select all</button>
      <button class="togg" id="imp-none">select none</button>
      <span class="imp-note">Adds and updates only &mdash; nothing already in
        this run is removed, whether you tick it or not.</span>
    </div>
    <div id="imp-results" class="cat-results"></div>
    <div class="mresult" id="imp-result"></div>
    <div class="mrow">
      <button id="imp-close">Close</button>
      <button id="imp-plan">Look</button>
      <button class="primary" id="imp-go" disabled>Import selected</button>
    </div>
  </div>
</div>

<div class="modal" id="epgmodal">
  <div class="modalbox" style="width:min(560px,94vw)">
    <button class="modalx" id="em-x" title="Close">✕</button>
    <h3>EPG check &mdash; <span id="em-title"></span></h3>
    <div class="sub">What each saved EPG source says is on RIGHT NOW,
      compared against what the guide said at capture time.</div>

    <div class="mfield" id="em-captured"></div>

    <div class="mfield">
      <label>Live, per source</label>
      <div id="em-sources" class="em-sources"></div>
    </div>

    <div class="mfield">
      <label>Search a source for the right channel</label>
      <div class="sub" style="margin:-4px 0 8px">For when the row above says
        &ldquo;not found&rdquo;, or the wrong entry, because this channel is
        filed under a name the matcher wouldn't try. Type part of the real
        name and pick from what actually exists.</div>
      <div style="display:flex;gap:8px">
        <select id="em-search-src" style="width:150px;flex:none"></select>
        <input type="text" id="em-search-q" placeholder="e.g. dmax, three, sports&hellip;"
          style="width:auto;flex:1">
      </div>
      <div id="em-search-results" class="cat-results" style="margin-top:8px"></div>
    </div>

    <div class="mfield">
      <label>Logo</label>
      <div class="sub" style="margin:-4px 0 8px">Pick which picture represents this
        channel: the provider's own, whichever matched EPG source's icon, or search
        the wider <a href="https://github.com/tv-logo/tv-logos" target="_blank"
        rel="noopener">tv-logo/tv-logos</a> catalogue. Every option here links straight
        to its own source's hosting &mdash; probarr never downloads or stores the
        image itself.</div>
      <div id="em-logo-current" class="em-logo-current"></div>
      <div id="em-logo-choices" class="em-logo-choices"></div>
      <div style="display:flex;gap:8px;margin-top:10px">
        <select id="em-logo-country" style="width:170px;flex:none"></select>
        <input type="text" id="em-logo-q" placeholder="search by channel name&hellip;"
          style="width:auto;flex:1">
      </div>
      <div id="em-logo-results" class="em-logo-choices" style="margin-top:8px"></div>
    </div>

    <div class="mresult" id="em-result"></div>

    <div class="mrow">
      <button id="em-close">Close</button>
    </div>
  </div>
</div>

<div class="modal" id="watermarkmodal">
  <div class="modalbox" style="width:min(720px,96vw)">
    <button class="modalx" id="wm-x" title="Close">✕</button>
    <h3>Mark watermark area &mdash; <span id="wm-title"></span></h3>
    <div class="sub">Drag a box around the logo/watermark on this known-good
      picture. Every candidate will then show that same area (scaled to its
      own resolution) cropped out of its own frame, right next to its
      screenshot &mdash; so a wrong stream (right name, wrong feed) is
      obvious to look at, not just inferred from a mismatched EPG.</div>
    <div class="sub" id="wm-nopic" style="display:none">No captured frame to
      draw on yet for this channel &mdash; probe or diagnose a candidate
      first, then come back here.</div>
    <div class="mfield" id="wm-picker-field" style="display:none">
      <label>Picture to draw on</label>
      <div class="sub" style="margin:-2px 0 6px">Defaults to the best-ranked
        candidate with a captured frame &mdash; switch if THIS one happens to
        be a moment the watermark faded off, or you'd rather use a different
        candidate's picture as the known-good reference.</div>
      <select id="wm-picker"></select>
    </div>
    <div id="wm-imgwrap" style="position:relative;display:inline-block;
      max-width:100%;line-height:0;cursor:crosshair">
      <img id="wm-img" style="max-width:100%;display:block" draggable="false">
      <div id="wm-box" style="position:absolute;border:2px solid var(--accent2);
        background:rgba(88,166,255,.18);display:none;pointer-events:none"></div>
    </div>
    <div class="mresult" id="wm-result"></div>
    <div class="mrow">
      <button id="wm-save" disabled>Save area</button>
      <button id="wm-close">Cancel</button>
    </div>
  </div>
</div>

<script>
const DATA = __DATA__;
// Matches the server's own auto-fallback depth (AUTO_FALLBACK_DEPTH in
// web.py) -- the client's bootstrap guess and the export's own fallback
// should never disagree about how many streams an uncurated channel gets.
// Real bug this ordering fixes: a completely untouched run (DATA.selection
// genuinely empty -- nothing has ever been curated) calls autoAll() right
// here at script load, which needs AUTO_FALLBACK_DEPTH immediately. It
// used to be declared further down the file as a `const`, which is in its
// temporal dead zone until that later line actually runs -- so opening
// Curate on a brand new run threw "Cannot access before initialization"
// and the whole page silently failed to render, with no channel list, no
// filter chips, nothing. Only ever triggered by a run whose selection was
// still completely empty, which nothing earlier in this session had
// happened to hit.
const AUTO_FALLBACK_DEPTH = 4;
function autoPick(ch){
  const usable = (ch.candidates||[]).filter(c => c.status==="ok" || c.status==="dirty");
  return {include: usable.length>0 && usable[0].status==="ok",
          streams: usable.slice(0, AUTO_FALLBACK_DEPTH).map(c=>c.id),
          primary: usable[0]?usable[0].id:null,
          fallback: usable[1]?usable[1].id:null, confirmed:false};
}
function autoAll(){
  const s={}; DATA.channels.forEach(ch => s[ch.key]=autoPick(ch)); return s;
}
let SEL = DATA.selection && Object.keys(DATA.selection).length
  ? DATA.selection : autoAll();
// Opens on triage when there IS anything to triage, else on All -- so the
// first thing shown is the work, and an already-clean run doesn't greet you
// with a confusing empty list.
let filter = "triage", current = null, lbFull = true, lbCand = null;
// Channels marked for a bulk action (currently: grouping). Cmd/Ctrl-click a
// row to toggle. Kept separate from `current` so marking a set does not
// disturb which channel you are actually looking at.
const MARKED = new Set();
// key -> "create"|"update", from the export planner. Lets the channel list
// say WHICH channels are actually out of sync with Dispatcharr, rather than
// leaving "have I pushed this yet?" as something you keep in your head.
let PENDING = {};
async function checkPending(){
  const btn = document.getElementById("pushall");
  let prov = (DATA.meta && DATA.meta.provider_name) || "";
  if(!prov){
    try{
      const d = await (await fetch("/api/providers")).json();
      const dd = d.providers.filter(p=>p.scheme==="dispatcharr");
      if(dd.length === 1) prov = dd[0].name;
    }catch(e){ return; }
  }
  if(!prov) return;
  try{
    const r = await fetch("/api/run/"+encodeURIComponent(DATA.run_id)+
      "/export/dispatcharr/plan",
      {method:"POST", headers:{"Content-Type":"application/json"},
       body: JSON.stringify({provider: prov, fallback_mode:"native"})});
    const d = await r.json();
    if(d.error) return;
    // plan() reports per expanded ROW (a "separate" fallback becomes its own
    // row); matching back by name is enough to flag the channel it came from.
    const byName = {};
    d.actions.forEach(a => { if(a.kind!=="unchanged") byName[a.name]=a.kind; });
    PENDING = {};
    DATA.channels.forEach(ch => { if(byName[ch.title]) PENDING[ch.key]=byName[ch.title]; });
    const n = Object.keys(PENDING).length;
    btn.textContent = n ? "Push changes ("+n+")" : "Push changes";
    btn.classList.toggle("primary", n>0);
    renderList();
  }catch(e){}
}

function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;")
  .replace(/>/g,"&gt;").replace(/"/g,"&quot;");}

// --- persistence -------------------------------------------------------
let saveTimer=null;
// Returns a promise resolving once the debounced write has actually
// reached the server -- every existing caller ignores it (fire-and-forget,
// unchanged behaviour), but a caller that immediately depends on the save
// having landed (e.g. re-rendering something that fetches FROM the just-
// saved state) can await it instead of racing ahead of it. Real bug this
// fixes: saving a watermark_box and re-rendering candidate cards straight
// after used to request each crop before the debounced save had actually
// written the box server-side, so the crop endpoint correctly 404'd
// (nothing to crop yet), got marked empty, and stayed that way until an
// unrelated full page reload happened to re-render after the save had
// caught up.
function save(){
  document.getElementById("saveind").textContent="saving\u2026";
  clearTimeout(saveTimer);
  return new Promise(resolve => {
    saveTimer=setTimeout(async ()=>{
      try{
        await fetch("/api/run/"+encodeURIComponent(DATA.run_id)+"/selection",
          {method:"POST",headers:{"Content-Type":"application/json"},
           body:JSON.stringify(SEL)});
        document.getElementById("saveind").textContent="saved";
      }catch(e){ document.getElementById("saveind").textContent="save failed"; }
      resolve();
    },400);
  });
}

// --- channel state -----------------------------------------------------
// Evidence a settle decision is made on: candidate statuses plus the EPG
// mismatch signature. Anything not in here can change silently underneath a
// settled channel without ever re-asking -- so anything the UI nags about
// has to be in here.
function evidenceSig(ch){
  const cs = (ch.candidates||[]).map(c=>c.id+":"+c.status).join("|");
  const mm = ch.epg_mismatch
    ? (ch.epg_mismatch.dispatcharr.guide_id+">"+ch.epg_mismatch.probarr.guide_id)
    : "";
  return cs+"||"+mm;
}
function state(ch){
  if (ch.missing) return "bad";
  const s = SEL[ch.key]||{};
  // include is absent for the common case (nothing has ever touched this
  // channel's selection, or a lineup only ever stored OTHER preferences
  // like group), and absent must mean "included by default" -- matching
  // web.py's own s.get("include", True). A plain `!s.include` treated
  // absent the same as explicitly-excluded, which meant EVERY channel
  // inheriting a lineup preference that only ever set e.g. group (never
  // include, since nothing needs to) rendered as excluded, with no
  // exclusion ever having actually happened.
  if (s.include === false) return "off";
  const clean = (ch.candidates||[]).filter(c=>c.status==="ok");
  // A settled channel is settled only while the evidence it was settled on
  // still holds -- "stop asking" means stop asking, not "stop asking until
  // the next unrelated reason to ask turns up". Otherwise "stop asking"
  // becomes permanent blindness the other way: the one channel you
  // dismissed is the one that quietly dies with no way to ever confirm it.
  if (s.confirmed && s.settled_on){
    const now = evidenceSig(ch);
    if (now !== s.settled_on && needsReview(ch)) return clean.length ? "review" : "bad";
    return "ok";
  }
  if (!clean.length) return "bad";
  if (needsReview(ch)) return "review";
  return "ok";
}
// The reasons, in the order they matter. "Needs you" was a colour and a
// count with no statement of what was actually wanted -- so every flagged
// channel had to be opened and worked out from scratch, and there was no
// way to say "I have looked at this, it is fine" and have it stay said.
function reviewReasons(ch){
  const out = [];
  if (ch.missing) {
    out.push("no stream matched this name \u2014 try Find streams, or add an alias");
    return out;
  }
  const cs = ch.candidates||[];
  if (!cs.length) out.push("nothing has been probed for this channel yet");
  else if (!cs.some(c=>c.status==="ok")){
    const best = cs[0];
    out.push("no clean stream: best is "+esc(best.name)+" ("+
             esc(best.status)+(best.reason?", "+esc(best.reason):"")+")");
  }
  if (cs.some(c=>c.dup))
    out.push("a candidate is the provider's holding card, not the channel");
  if (cs.some(c=>c.lowmo))
    out.push("a candidate barely moves \u2014 check the picture is really live");
  if (cs.some(c=>c.offcad))
    out.push("a candidate is another country's feed (wrong frame rate)");
  if (ch.epg_mismatch)
    out.push("Dispatcharr is showing \u201c"+ch.epg_mismatch.dispatcharr.title+
      "\u201d for this channel, but the guide says it should be \u201c"+
      ch.epg_mismatch.probarr.guide_name+"\u201d ("+ch.epg_mismatch.probarr.source+
      ") \u2014 push again to correct it, or Check EPG to pick a different source first.");
  if ((ch.changes||[]).length) out.push(...ch.changes);
  return out;
}
function needsReview(ch){
  if (ch.missing) return true;
  const cs = ch.candidates||[];
  if (!cs.some(c=>c.status==="ok")) return true;
  if (cs.some(c=>c.dup||c.lowmo)) return true;
  if (ch.epg_mismatch) return true;
  if (ch.epg_missing) return false;
  return false;
}
// "Triage" is the union of every state that genuinely needs a person:
// something to review, or something with no usable candidate at all.
// It leads the list because reviewing all N channels is almost never the
// job -- the job is the handful the algorithm could not settle. Opening on
// "All" made the exhaustive path the default one, which is why confirmed
// counts tended to stay at zero: the useful subset was never surfaced.
function needsHuman(ch){ const st=state(ch); return st==="review"||st==="bad"; }
// Cut from seven chips to five. "Needs review" and "Unresolved" were never
// anything but a manual split of "Needs you" -- it already unions them, so
// the split chips tracked the same channels the union did (identically 7
// and 0 against Needs you's 7, on a real lineup) and nobody filtered to the
// half instead of the whole. The distinction is not gone: state() still
// tells review from bad, and it still shows on each channel's dot colour
// and in "why this needs you" -- it just does not need its own tab to do
// that.
const FILTERS = [["changed","Changed"],["triage","Needs you"],["all","All"],
                 ["off","Excluded"]];

function visible(){
  const q=document.getElementById("q").value.trim().toLowerCase();
  return DATA.channels.filter(ch=>{
    if (q && !(ch.title.toLowerCase().includes(q) ||
               String(ch.number||"").includes(q))) return false;
    const st=state(ch);
    if (filter==="changed") return (ch.changes||[]).length > 0;
    if (filter==="triage") return needsHuman(ch);
    if (filter==="off") return st==="off";
    return true;
  });
}

function renderChips(){
  const counts={all:DATA.channels.length,review:0,bad:0,off:0,triage:0};
  DATA.channels.forEach(ch=>{
    const st=state(ch); if(counts[st]!==undefined) counts[st]++;
    if(needsHuman(ch)) counts.triage++;
  });
  counts.changed = DATA.channels.filter(ch => (ch.changes||[]).length).length;
  document.getElementById("chips").innerHTML = FILTERS.map(([k,label])=>
    '<span class="chip'+(filter===k?' on':'')+'" data-f="'+k+'">'+label+
    ' '+(counts[k]||0)+'</span>').join("");
}

// Same precedence _resolve_curated() uses server-side for export, minus
// the live EPG-source fallback -- that needs a network round trip per
// channel and this renders the entire (possibly hundreds-long) list on
// every filter/search keystroke, so it's deliberately just the two cheap,
// already-in-memory sources. A channel with neither shows no thumbnail
// rather than a broken-image icon.
const STATE_LABEL = {ok: "clean", review: "needs a look",
  bad: "no usable stream", off: "excluded"};
function listLogo(ch){
  const sel = SEL[ch.key] || {};
  return sel.logo_override || (ch.candidates||[]).map(c=>c.logo).find(Boolean) || "";
}
function renderList(){
  const list=visible();
  document.getElementById("chanlist").innerHTML = list.length ? list.map(ch=>{
    const logoUrl = listLogo(ch);
    const st = state(ch);
    return '<div class="chan'+(current===ch.key?' sel':'')+(ch.missing?' missing':'')+
    (MARKED.has(ch.key)?' marked':'')+'" data-k="'+esc(ch.key)+'">'+
      '<span class="dot '+st+'" title="'+esc(STATE_LABEL[st]||st)+'"></span>'+
      (ch.number!=null?'<span class="num">'+ch.number+'</span>'
        :'<span class="num nonum" title="No channel number set — this channel '+
          'will be dropped from every export until it has one">NO #</span>')+
      (logoUrl ? '<img class="chlogo" src="'+esc(logoUrl)+'" alt="" loading="lazy">'
               : '<span class="chlogo chlogo-empty"></span>')+
      '<span class="nm">'+esc(ch.title)+
        (ch.dispatcharr?'<span class="dpip" title="imported from Dispatcharr">D</span>':'')+
        ((ch.changes||[]).length ? '<span class="chpip" title="'+
          esc(ch.changes.join(" \u00b7 "))+'">changed</span>' : '')+
        '</span>'+
      '<span class="cnt">'+(ch.missing?"\u2014":(ch.candidates||[]).length)+'</span>'+
    '</div>';
  }).join("")
    : (filter==="triage"
        ? '<div class="empty">Nothing needs you.<div class="hint">Every channel '+
          'has a clean pick the ranking is confident about. Switch to '+
          '<b>All</b> to browse them, or export as-is.</div></div>'
        : '<div class="empty">No channels match.</div>');
  renderChips();
  document.getElementById("diagfilteredcount").textContent = list.length;
}

// The channel's own most common declared aspect ratio, not a hardcoded
// 16:9 -- a handful of real UK channels are still 4:3 or otherwise
// non-widescreen, and hardcoding 16:9 would flag every single one of
// THEIR candidates as wrong instead of the genuinely mismatched one. Mode,
// not mean: outliers (the actual thing being detected) must not be
// allowed to drag the "normal" value toward themselves.
function dominantAspect(ch){
  const counts = new Map();
  for(const c of (ch.candidates||[])){
    if(!c.w || !c.h) continue;
    const r = Math.round((c.w/c.h)*100)/100;
    counts.set(r, (counts.get(r)||0)+1);
  }
  let best=null, bestN=0;
  for(const [r,n] of counts) if(n>bestN){ best=r; bestN=n; }
  return best;
}
function specHTML(c, expectedAspect){
  const out=[];
  if(c.dropped) out.push(['<span class="spec err" title="Dispatcharr\'s own '+
    'event log: this exact stream has genuinely failed over '+c.dropped+
    ' time(s) in real use, not a probe guess. Turn off in Settings if you '+
    'would rather not see it.">',
    '\u26a0 dropped '+c.dropped+'\u00d7', '</span>']);
  if(c.w) out.push(['<span class="spec hi">',c.w+"\u00d7"+c.h+(c.fps?"@"+c.fps:""),'</span>']);
  // A different WIDTH at the same declared height is the visible signature
  // of a stretched/squashed picture -- the whole reason a watermark crop
  // (same fractional box, different absolute pixels per candidate) makes a
  // wrong aspect ratio obvious to spot by eye without watching the stream.
  // 3% tolerance: real widescreen sources round to slightly different
  // w/h ratios from rounding alone (1920x1080 vs 1280x720 are both
  // "16:9" but not bit-identical as a fraction); anything past that is a
  // genuinely different shape, not rounding noise.
  if(c.w && c.h && expectedAspect){
    const ratio = c.w/c.h;
    if(Math.abs(ratio-expectedAspect)/expectedAspect > 0.03){
      out.push(['<span class="spec err" title="This channel\u2019s other '+
        'candidates are mostly '+expectedAspect.toFixed(2)+':1 \u2014 this '+
        'one declares '+ratio.toFixed(2)+':1. Likely stretched or letterboxed '+
        'wrong, not just a different resolution.">',
        'aspect ratio off','</span>']);
    }
  }
  if(c.kbps) out.push(['<span class="spec hi">',c.kbps+" kbps",'</span>']);
  if(c.vcodec) out.push(['<span class="spec">',c.vcodec,'</span>']);
  if(c.acodec) out.push(['<span class="spec">',c.acodec+(c.ach?" "+c.ach+"ch":""),'</span>']);
  if(c.corrupt) out.push(['<span class="spec err">',c.corrupt+" corrupt",'</span>']);
  if(c.dup) out.push(['<span class="spec err">','provider placeholder','</span>']);
  else if(c.lowmo) out.push(['<span class="spec err">','low motion \u2014 check picture','</span>']);
  if(c.offcad) out.push(['<span class="spec err" title="This lineup is almost '+
    'entirely '+esc((c.housecad||"").toUpperCase())+' \u2014 UK and European '+
    'broadcast is 25 or 50fps. A candidate at '+esc((c.cad||"").toUpperCase())+
    ' rates (29.97/59.94) is another country\'s feed under the right name, '+
    'however it is labelled.">'+
    (c.cad==="ntsc" ? "60Hz \u2014 likely a US feed" : "wrong cadence")+
    '</span>']);
  if(c.abr) out.push(['<span class="spec warn2" title="Source is a multi-rendition manifest \u2014 the relay has to do real ABR switching, which has caused real buffering.">','multi-bitrate manifest','</span>']);
  if(c.slowfetch) out.push(['<span class="spec warn2" title="Sample took close to real-time or longer to download \u2014 delivery may struggle to keep up with playback.">','slow fetch','</span>']);
  return out.map(x=>x[0]+esc(x[1])+x[2]).join("");
}

function renderDetail(){
  const ch=DATA.channels.find(c=>c.key===current);
  const d=document.getElementById("detail");
  if(!ch){ d.innerHTML='<div class="empty">Select a channel on the left.<div class="hint">'+
    '<code>\u2191</code><code>\u2193</code> move &middot; <code>1</code>-<code>9</code> pick '+
    '&middot; <code>f</code> fallback &middot; <code>Enter</code> confirm and advance'+
    '</div></div>'; return; }
  const s=SEL[ch.key]||{};
  const cands=(ch.candidates||[]);
  // needsHuman()/state() already know whether a PREVIOUSLY settled channel
  // has been re-flagged (its evidence moved since "This is fine" was
  // clicked) -- checking !s.confirmed here as well was stale and actively
  // wrong once re-flagging existed: a re-flagged channel has confirmed===
  // true AND needsHuman()===true at once, and this hid the only button
  // that could dismiss it again. Trapped in Needs You with no way out.
  const why = needsHuman(ch) ? reviewReasons(ch) : [];
  const whybox = why.length
    ? '<div class="whybox"><b>Why this needs you</b><ul>'+
      why.map(x=>'<li>'+x+'</li>').join("")+'</ul>'+
      '<button id="settlebtn" title="Mark this channel (or a multi-selection) '+
      'settled. It stops being flagged, and the decision is remembered on '+
      'the lineup so later runs inherit it \u2014 until something about the '+
      'channel actually changes, when it is flagged again.">'+
      (MARKED.size>1 ? 'This is fine \u2014 stop asking ('+MARKED.size+')'
                     : 'This is fine \u2014 stop asking')+'</button>'+
      '</div>'
    : '';
  // Collapsed by default, and the trigger lives in the button row now, not
  // as its own always-visible banner -- a channel with nine real changes
  // used to fill the whole screen with a list nobody asked to read in
  // full, every single time the card was opened, pushing the actual
  // picture below the fold.
  const changed = (ch.changes||[]).length
    ? '<div class="chbox" id="chlist" style="display:none"><ul>'+
      ch.changes.map(x=>'<li>'+esc(x)+'</li>').join("")+'</ul></div>'
    : '';
  const changesBtn = (ch.changes||[]).length
    ? '<button id="changesbtn" data-chtoggle="chlist" title="What changed for '+
      'this channel since the last scan.">Changes ('+ch.changes.length+')</button>'
    : '';
  // Exclude/Re-include applies to a channel with no matched candidates
  // just as well as one with them -- a real gap this used to have: a
  // channel a provider simply doesn't carry is exactly the case for
  // "stop asking about this every run" without deleting it outright
  // (Remove), which a provider swap later might make moot. Built once,
  // shared between both branches below so they can't drift.
  const includeBtn =
    '<button id="includebtn2" title="'+(s.include !== false
      ? 'Leave this channel (or a multi-selection) out of every export, '+
        'without deleting its probe results — the same as pressing x. '+
        'It stays in this run and can be re-included at any time.'
      : 'Bring this channel (or a multi-selection) back into every export. '+
        'Same as pressing x.')+'">'+
    (MARKED.size>1
      ? (s.include !== false ? 'Exclude ('+MARKED.size+')' : 'Re-include ('+MARKED.size+')')
      : (s.include !== false ? 'Exclude this channel' : 'Re-include this channel'))+
    '</button>';
  const dLogoUrl = listLogo(ch);
  d.innerHTML =
    '<div class="dhead"><h1>'+
      '<span id="numtext" tabindex="0" title="'+
        (ch.number!=null?'Click to change this channel’s number'
          :'No channel number set — this channel is dropped from every '+
           'export until it has one. Click to set it.')+'">'+
        (ch.number!=null?esc(String(ch.number)):
          '<span class="num nonum">NO #</span>')+'</span>'+
      (ch.number!=null?' &middot; ':' ')+
      '<button id="numedit" title="Set this channel’s number">✎</button> '+
      (dLogoUrl ? '<img class="dhlogo" src="'+esc(dLogoUrl)+'" alt="">' : '')+
      '<span id="titletext" tabindex="0" title="Click to rename">'+esc(ch.title)+'</span>'+
      '<button id="titleedit" title="Rename this channel">\u270e</button> '+
      // Whether push() would refuse this channel as an unclaimed number
      // collision -- see claims.py. Shown right next to the name because
      // that is exactly the thing worth seeing while debugging a "blocked"
      // row in the push preview: is THIS channel tagged, and as what.
      (ch.claim
        ? '<span class="claimtag claimtag-on" title="Tagged as Dispatcharr '+
          'channel #'+esc(ch.claim.dispatcharr_id)+' \u2014 push() will treat '+
          'a number match against this id as an ordinary update, not a '+
          'blocked/relink conflict.">linked \u00b7 Dispatcharr #'+
          esc(ch.claim.dispatcharr_id)+'</span>'
        : '<span class="claimtag claimtag-off" title="Not yet tagged to any '+
          'Dispatcharr channel. If this channel\u2019s number collides with an '+
          'unrecognised Dispatcharr channel on push, it will show as '+
          '\u201cblocked\u201d or \u201crelink\u201d in the push preview until '+
          'resolved there, or via Unclaimed.">not linked to Dispatcharr</span>')+
      '</h1>'+
      '<div class="sub">'+esc(ch.why||"")+
        (!ch.missing ? ' &middot; group: <b>'+esc(s.group||"none")+'</b>'+
          '<button id="groupedit" title="Change this channel’s group (or a '+
          'multi-selection’s) — carried through to Dispatcharr on the next '+
          'push. The Groups view covers moving several channels around at '+
          'once.">✎</button>' : '')+
        (ch.dispatcharr ? '<span class="dtag" title="This channel already '+
          'exists in Dispatcharr. The candidates below are what the provider '+
          'carries for it \u2014 the point of importing is to see whether any '+
          'of them beat what is live there now.">in Dispatcharr'+
          (ch.dispatcharr.number!=null?' #'+esc(ch.dispatcharr.number):'')+
          (ch.dispatcharr.group?' &middot; '+esc(ch.dispatcharr.group):'')+
          (ch.dispatcharr.stream?' &middot; '+esc(ch.dispatcharr.stream):'')+
          '</span>' : '')+
        (ch.dispatcharr && ch.dispatcharr.failovers_7d ? '<span class="dtag fail" '+
          'title="Dispatcharr\'s own event log: this channel\'s stream has '+
          'genuinely failed over '+ch.dispatcharr.failovers_7d+' time(s) in the '+
          'last 7 days \u2014 real playback evidence, not a probe guess. Turn '+
          'off in Settings if you would rather not see it.">'+
          '\u26a0 failed over '+ch.dispatcharr.failovers_7d+'&times; this week</span>' : '')+
        '</div>'+
      // The buttons an UNMATCHED channel still needs. It used to get none at
      // all, which meant Find streams -- the one action that can actually
      // resolve "no candidate streams matched", by searching the catalogue
      // past the matcher -- was hidden on precisely the channels that need
      // it. Rename and Remove apply just as well to a channel with no
      // candidates; Diagnose, EPG check and Duplicate do not, since there
      // is nothing yet to diagnose, compare or copy.
      '<button id="findstreamsbtn" title="Every stream the provider offers for '+
        'this channel, probed or not \u2014 plus a search of the whole catalogue '+
        'for variants the matcher did not connect to it. Tick what is worth '+
        'probing; only this channel is touched.">Find streams</button>'+
      (ch.missing ?
        includeBtn+
        '<button id="removechanbtn" class="danger" title="Remove this channel from '+
        'the run \u2014 optionally from Dispatcharr too.">Remove</button>'+
        changesBtn+
        '<span class="muted" id="diagnosemsg"></span>' :
        '<button id="diagnosebtn" title="Re-scan every candidate for this channel with a '+
        'longer sample and a kept video clip \u2014 for when a channel misbehaves in a real '+
        'player and a still frame doesn\'t explain why.">Diagnose this channel</button>'+
        '<button id="epgcheckbtn" title="Compare every saved EPG source\'s live '+
        '\u2018now playing\u2019 for this channel, side by side with what the guide said '+
        'at capture time.">Check EPG</button>'+
        '<button id="watermarkbtn" title="Draw a box around this channel\u2019s logo/'+
        'watermark on a known-good picture. Every candidate then shows that same '+
        'area cropped out of its own frame, right next to its screenshot \u2014 so a '+
        'wrong stream (right name, wrong feed) is obvious at a glance, not just '+
        'inferred from a mismatched EPG.">'+
        (s.watermark_box ? 'Redraw watermark area' : 'Mark watermark area')+'</button>'+
        (s.watermark_box ? '<button id="clearwatermarkbtn" title="Stop comparing '+
        'this channel\u2019s candidates against a watermark area.">Clear</button>' : '')+
        '<button id="dupchanbtn" title="Make a second copy of this channel so '+
        'it can sit in another group as well \u2014 same streams, no re-probing.">'+
        'Duplicate</button>'+
        includeBtn+
        '<button id="removechanbtn" class="danger" title="Remove this channel from '+
        'the run \u2014 optionally from Dispatcharr too.">Remove</button>'+
        changesBtn+
        '<span class="muted" id="diagnosemsg"></span>')+
    '</div>'+
    (s.include === false ? '<div class="offbox">This channel is <b>excluded</b> \u2014 '+
      'left out of every export until you re-include it.'+
      '<button id="includebtn">Re-include this channel</button></div>' : '') +
    whybox + changed +
    (ch.missing
      ? '<div class="empty">No candidate streams matched this name.'+
        '<div class="hint">The usual cause is a naming difference, not a missing '+
        'channel \u2014 the provider almost certainly carries it under a spelling '+
        'the matcher did not connect. <b>Find streams</b> searches the whole '+
        'catalogue by name and can attach anything it turns up to this channel, '+
        'no alias or re-run needed.<br>To fix it for every future run instead, '+
        '<code>probarr explain "'+esc(ch.title)+'" --source &lt;src&gt;</code> '+
        'shows what normalisation did to the name, and an alias makes the match '+
        'permanent.</div></div>'
      : '<div class="cands" id="cands">' + ((() => {
          // A divider marks the seam between the ordered, pushed list and
          // everything else in the pool -- without it "only two rows look
          // special" reads as a cap of two, when any candidate below can be
          // added with + Add to channel, in any number.
          const ids = chosenIds(ch);
          const expectedAspect = dominantAspect(ch);
          let div = "";
          return orderedCands(ch).map((c,i)=>{
          const used = ids.indexOf(c.id);
          const pre = (i === ids.length && ids.length > 0 && !div)
            ? (div = "1") && '<div class="canddiv">'+(orderedCands(ch).length-ids.length)+
              ' more candidate'+(orderedCands(ch).length-ids.length===1?'':'s')+' below '+
              '\u2014 <b>+ Add to channel</b> includes any of them, in any number</div>'
            : "";
          return pre + '<div class="cand'+(used>=0?' chosen':' unused')+
        '" data-id="'+esc(c.id)+'"'+(used>=0?' draggable="true"':'')+'>'+
          '<div class="grip" title="Drag to reorder">\u2261</div>'+
          '<div class="pos">'+(used>=0 ? (used+1) : "\u2013")+'</div>'+
          '<div class="shot" data-zoom="'+esc(c.id)+'">'+
            (c.thumb?'<img loading="lazy" src="'+esc(c.thumb)+'" alt="">'
                    :'<div class="empty" style="padding:14px 6px;font-size:11px">no frame<br>'+
                      esc(c.reason||c.status)+'</div>')+
            '<div class="pill '+c.status+'">'+c.status+'</div>'+
            (i<9?'<div class="kbd">'+(i+1)+'</div>':'')+
          '</div>'+
          (s.watermark_box ? '<div class="wmshot" data-zoom-wm="'+esc(c.id)+'" '+
            'title="The marked watermark area, cropped out of THIS candidate’s '+
            'own frame — compare it by eye against the screenshot to its left. '+
            'Click to enlarge.">'+
            '<img loading="lazy" src="/run/'+encodeURIComponent(DATA.run_id)+
            '/watermark?key='+encodeURIComponent(c.id)+'" alt="" '+
            'onerror="this.closest(\'.wmshot\').classList.add(\'wmshot-empty\')">'+
            '</div>' : '')+
          '<div class="cbody"><div class="sname" title="'+esc(c.name)+'">'+esc(c.name)+
            ' <span class="n" style="color:var(--faint)">#'+c.rank+' ranked</span></div>'+
            '<div class="specs">'+specHTML(c, expectedAspect)+'</div>'+
            (c.expected ? '<div class="cand-epg" title="What the guide said '+
              'was airing at the moment THIS candidate was probed — '+
              'compare it against the screenshot to its left.">'+
              '<span class="lbl">Guide at probe time'+
              (c.expected.window?' ('+esc(c.expected.window)+')':'')+
              ':</span><span class="ttl">'+esc(c.expected.title)+'</span></div>' : '')+
            '<div class="actions">'+
              '<button data-act="use">'+(used>=0?"Remove from channel":"+ Add to channel")+'</button>'+
              (c.clip ? '<button data-act="clip" title="Watch the last captured clip">\u25b6</button>' : '')+
              '<button data-act="drop" class="danger" title="Delete this stream '+
                'from the channel entirely: its probe results and frames go '+
                'too. Not the same as removing it from the pushed list.">'+
                'Delete stream</button>'+
              '<button data-act="reprobe" title="Re-probe this stream now, '+
                'including a fresh clip \u2014 updates its status, picture and '+
                'the clip together.">\u21bb</button>'+
            '</div></div></div>';}).join("");
        })()) + '</div>')+
    '<div class="hint">'+(s.confirmed?'Confirmed. ':'')+
      'Drag the numbered streams to set the order Dispatcharr tries them in. '+
      '<code>\u2191</code><code>\u2193</code> move &middot; <code>1</code>-<code>9</code> make first '+
      '&middot; <code>f</code> add the next candidate &middot; <code>x</code> exclude '+
      '&middot; <code>Enter</code> confirm and advance</div>';
  wireDrag();
}

// Reordering by dragging, on the chosen rows only. Plain HTML5 drag events
// rather than a library: probarr ships no dependencies, and the whole
// interaction is "pick a row up, decide which row it lands above".
let dragId = null;
function wireDrag(){
  const box = document.getElementById("cands"); if(!box) return;
  box.querySelectorAll(".cand.chosen").forEach(row => {
    row.addEventListener("dragstart", e => {
      dragId = row.dataset.id;
      row.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      // Firefox refuses to start a drag without payload.
      try{ e.dataTransfer.setData("text/plain", dragId); }catch(_){}
    });
    row.addEventListener("dragend", () => {
      dragId = null;
      box.querySelectorAll(".cand").forEach(r =>
        r.classList.remove("dragging","dropinto"));
    });
    row.addEventListener("dragover", e => {
      if(!dragId || row.dataset.id === dragId) return;
      e.preventDefault();
      row.classList.add("dropinto");
    });
    row.addEventListener("dragleave", () => row.classList.remove("dropinto"));
    row.addEventListener("drop", e => {
      e.preventDefault();
      row.classList.remove("dropinto");
      const ch = DATA.channels.find(c=>c.key===current);
      if(!ch || !dragId || row.dataset.id === dragId) return;
      const ids = chosenIds(ch).filter(x => x !== dragId);
      const at = ids.indexOf(row.dataset.id);
      ids.splice(at < 0 ? ids.length : at, 0, dragId);
      setStreams(ids);
    });
  });
}

function select(key){ current=key; renderList(); renderDetail();
  const el=document.querySelector('.chan.sel'); if(el) el.scrollIntoView({block:"nearest"});
  saveViewState(); }
// Where you are is remembered in the URL, not just in memory -- a reload
// used to always land back on "Needs you" and the first channel in it, no
// matter what you had actually been looking at. history.replaceState so
// this never adds a back-button entry per click.
function saveViewState(){
  const h = "#f="+encodeURIComponent(filter)+(current?"&ch="+encodeURIComponent(current):"");
  if(location.hash !== h) history.replaceState(null, "", h);
}
function loadViewState(){
  const p = new URLSearchParams(location.hash.replace(/^#/, ""));
  return {f: p.get("f"), ch: p.get("ch")};
}

function advance(dir){
  const list=visible(); if(!list.length) return;
  let i=list.findIndex(c=>c.key===current);
  i = i<0 ? 0 : Math.min(list.length-1, Math.max(0, i+dir));
  select(list[i].key);
}

// --- lightbox ----------------------------------------------------------
let lbIsWatermark = false;
function zoom(id){
  const ch=DATA.channels.find(c=>c.key===current); if(!ch) return;
  const c=(ch.candidates||[]).find(x=>x.id===id); if(!c||!c.frame) return;
  lbCand=c; lbFull=true; lbIsWatermark=false;
  document.getElementById("lbmode").style.display = "";
  document.getElementById("lb2").querySelector("img").classList.remove("wm-big");
  paintLB();
  document.getElementById("lb2").classList.add("on");
}
// A watermark crop is one image, not a full-frame/1:1-crop PAIR to toggle
// between -- reuses the same lightbox chrome (close button, Esc, dark
// backdrop) rather than building a second one, but skips paintLB()
// entirely (that function assumes lbCand, which this has no use for) and
// hides the now-meaningless mode-toggle button instead of leaving it to
// silently do nothing when clicked.
function zoomWatermark(id){
  const ch=DATA.channels.find(c=>c.key===current); if(!ch) return;
  const c=(ch.candidates||[]).find(x=>x.id===id); if(!c) return;
  lbIsWatermark = true;
  const lb=document.getElementById("lb2");
  const img = lb.querySelector("img");
  img.src = "/run/"+encodeURIComponent(DATA.run_id)+
    "/watermark?key="+encodeURIComponent(id);
  // Explicitly forced large -- max-width/max-height alone only ever
  // SHRINK an oversized image, and a marked area is typically a few dozen
  // native pixels, nowhere near either limit. Without an explicit width
  // this "enlarged" view would show the exact same tiny image as the
  // card did, just alone on a dark background -- which is not what
  // "enlarged" was asked for.
  img.classList.add("wm-big");
  document.getElementById("lbmode").style.display = "none";
  document.getElementById("lbcap").textContent =
    c.name + " \u2014 marked watermark area, enlarged (native pixels upscaled "+
    "by the browser; a small marked area on a low-resolution frame will look soft)";
  lb.classList.add("on");
}
function paintLB(){
  if(!lbCand || lbIsWatermark) return;
  const lb=document.getElementById("lb2");
  const src = lbFull ? lbCand.frame : (lbCand.crop||lbCand.frame);
  lb.querySelector("img").src = src;
  document.getElementById("lbmode").textContent =
    lbFull ? "Show 1:1 crop" : "Show full frame";
  document.getElementById("lbcap").textContent =
    lbCand.name + " \u2014 " + (lbFull
      ? (lbCand.w + "\u00d7" + lbCand.h + " scaled to fit")
      : "native pixels, no scaling \u2014 compression artefacts visible here");
}

// --- events ------------------------------------------------------------
document.addEventListener("click", e=>{
  // While the lightbox is open it owns every click. Handling it first (and
  // always returning) stops a click from both dismissing the overlay AND
  // activating whatever sat underneath it -- which otherwise silently
  // reselected a different channel.
  const lb=document.getElementById("lb2");
  if(lb.classList.contains("on")){
    if(e.target.id==="lbmode" && !lbIsWatermark){ lbFull=!lbFull; paintLB(); return; }
    if(e.target.id==="lbclose"){ lb.classList.remove("on"); return; }
    if(e.target.closest(".bar2")) return;
    lb.classList.remove("on");
    return;
  }
  const cv=document.getElementById("clipviewer");
  if(cv.classList.contains("on")){
    if(e.target.closest(".bar2") || e.target.tagName==="VIDEO") return;
    closeClip();
    return;
  }
  if(e.target.id==="pushall"){ openDispatchModal(null); return; }
  if(e.target.id==="diagnosebtn"){ diagnoseChannel(); return; }
  if(e.target.id==="findstreamsbtn"){ openStreams(); return; }
  if(e.target.id==="settlebtn"){ settleChannel(); return; }
  if(e.target.id==="epgcheckbtn"){ openEpgModal(); return; }
  if(e.target.id==="groupedit"){ setGroup(); return; }
  if(e.target.id==="watermarkbtn"){ openWatermarkModal(); return; }
  if(e.target.id==="clearwatermarkbtn"){
    const s=SEL[current]=SEL[current]||{};
    delete s.watermark_box;
    save(); renderList(); renderDetail();
    return;
  }
  if(e.target.id==="removechanbtn"){ removeChannel(); return; }
  if(e.target.id==="dupchanbtn"){ duplicateChannel(); return; }
  if(e.target.id==="includebtn" || e.target.id==="includebtn2"){ toggleInclude(); return; }
  const chip=e.target.closest(".chip");
  if(chip){ filter=chip.dataset.f; renderList(); saveViewState(); return; }
  const row=e.target.closest(".chan");
  if(row){
    if(e.metaKey || e.ctrlKey){
      const k=row.dataset.k;
      MARKED.has(k) ? MARKED.delete(k) : MARKED.add(k);
      renderList(); renderDetail(); return;
    }
    select(row.dataset.k); return;
  }
  const wmshot=e.target.closest("[data-zoom-wm]");
  if(wmshot){ zoomWatermark(wmshot.dataset.zoomWm); return; }
  const shot=e.target.closest("[data-zoom]");
  if(shot){ zoom(shot.dataset.zoom); return; }
  const btn=e.target.closest("button[data-act]");
  if(btn){
    const id=btn.closest(".cand").dataset.id;
    if(btn.dataset.act==="clip"){ watchClip(id); return; }
    if(btn.dataset.act==="reprobe"){ reprobe(id, btn); return; }
    if(btn.dataset.act==="drop"){ dropStream(id, btn); return; }
    if(btn.dataset.act==="use"){ toggleUse(id); return; }
  }
});
async function dropStream(id, btn){
  const ch = DATA.channels.find(c=>c.key===current); if(!ch) return;
  const c = (ch.candidates||[]).find(x=>x.id===id); if(!c) return;
  // One dialog, not confirm() then a separate prompt() -- and the reason IS
  // the point: the stream itself survives (Find streams can and will offer
  // it again), so without a note here a future look has no way to tell "not
  // yet tried" from "tried, and here is why it was wrong".
  const reason = prompt(
    "Remove \u201c"+c.name+"\u201d from "+ch.title+"?\n\n"+
    "Its probe results and captured frames are deleted. The stream itself "+
    "is untouched and can still turn up again in Find streams \u2014 so say "+
    "why, and that shows up next to it if it does. Cancel to keep it.\n\n"+
    "Reason (optional):", "");
  if(reason === null) return;
  btn.disabled = true;
  try{
    const r = await fetch("/api/run/"+encodeURIComponent(DATA.run_id)+
      "/candidate-remove", {method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({rec_key: id, reason})});
    const d = await r.json();
    if(d.error){ alert("Could not remove: "+d.error); btn.disabled=false; return; }
    await refreshChannel(current);
  }catch(e){ alert("Request failed."); btn.disabled = false; }
}

async function reprobe(id, btn, extra){
  btn.disabled=true;
  try{
    const r=await fetch("/api/run/"+encodeURIComponent(DATA.run_id)+"/reprobe",
      {method:"POST",headers:{"Content-Type":"application/json"},
       body:JSON.stringify({rec_key:id, ...(extra||{})})});
    const d=await r.json();
    if(d.state==="cooldown"){
      // Refusing outright was the honest answer to "probe this again NOW" --
      // a fresh capture seconds later shows almost the same instant, and
      // the provider gets hit for nothing. But it made the button look
      // broken: it changed to a number that never moved, and the click was
      // thrown away, so you had to remember to come back and press it
      // again. Counting down visibly and then submitting it yourself keeps
      // the cooldown intact while treating the click as what it plainly
      // was -- a request to re-probe as soon as that is worth doing.
      return countdown(id, btn, Math.ceil(d.retry_after || 1), extra);
    }
    if(d.error){ btn.textContent="!"; btn.disabled=false; return; }
    watch(id, btn);
  }catch(e){ btn.textContent="!"; btn.disabled=false; }
}

// Poll until this stream leaves the queue, so a burst of clicks shows honest
// queue positions instead of every button claiming to be working at once.
// A visible, ticking wait rather than a frozen number, and the queue is
// joined automatically at zero.
function countdown(id, btn, secs, extra){
  btn.disabled = true;
  const tick = () => {
    if(secs <= 0){
      btn.textContent = "\u2026";
      return reprobe(id, btn, extra);  // the cooldown has passed; take the turn
    }
    btn.textContent = secs + "s";
    secs -= 1;
    setTimeout(tick, 1000);
  };
  tick();
}

function watch(id, btn){
  const key = DATA.run_id + "|" + id;
  let tries = 0;
  const tick = async () => {
    tries++;
    let snap;
    try{ snap = await (await fetch("/api/queue", {cache:"no-store"})).json(); }
    catch(e){ btn.textContent="!"; btn.disabled=false; return; }
    const st = snap.keys && snap.keys[key];
    // Same highlight Diagnose uses for a multi-candidate scan, applied
    // here too -- a single re-probe deserves the same "this is the one
    // being watched right now" cue, not just a button whose text changes.
    const row = document.querySelector('.cand[data-id="'+CSS.escape(id)+'"]');
    if(st){
      btn.textContent = snap.blocked ? "\u23f8"
        : st.state === "running" ? "\u2026"
        : ("#" + (st.position || "?"));
      btn.title = snap.blocked || "";
      if(row) row.classList.toggle("probing", st.state === "running");
      if(tries < 600) return setTimeout(tick, 1000);
      btn.textContent="!"; btn.disabled=false; if(row) row.classList.remove("probing");
      return;
    }
    if(row) row.classList.remove("probing");
    await refreshChannel(current);
    const fresh = document.querySelector('.cand[data-id="'+CSS.escape(id)+'"]');
    if(fresh){
      fresh.classList.add("just-scanned");
      setTimeout(()=>fresh.classList.remove("just-scanned"), 1500);
    }
  };
  btn.textContent="\u2026";
  setTimeout(tick, 600);
}

function watchClip(id){
  const ch=DATA.channels.find(c=>c.key===current); if(!ch) return;
  const c=(ch.candidates||[]).find(x=>x.id===id); if(!c||!c.clip) return;
  const v=document.getElementById("clipvideo");
  v.src=c.clip;
  document.getElementById("clipcap").textContent=c.name+" \u2014 diagnose clip";
  document.getElementById("clipviewer").classList.add("on");
  v.play().catch(()=>{});
}
function closeClip(){
  const v=document.getElementById("clipvideo");
  v.pause(); v.removeAttribute("src"); v.load();
  document.getElementById("clipviewer").classList.remove("on");
}

// Adding channels the wantlist never mentioned. The run's own list is a
// starting point, not a ceiling -- the provider carries far more than any
// hand-written wantlist names, and finding those needs a search over the
// whole catalogue rather than over what was already matched.
const CATPICK = new Set();
let catTimer = null;
function openCatalog(){
  CATPICK.clear();
  document.getElementById("cat-q").value = "";
  document.getElementById("cat-results").innerHTML =
    '<div class="n">Type at least 2 characters.</div>';
  document.getElementById("cat-result").className = "mresult";
  document.getElementById("cat-add").disabled = true;
  document.getElementById("catmodal").classList.add("on");
  document.getElementById("cat-q").focus();
}
async function catSearch(){
  const q = document.getElementById("cat-q").value.trim();
  const box = document.getElementById("cat-results");
  if(q.length < 2){ box.innerHTML='<div class="n">Type at least 2 characters.</div>'; return; }
  box.innerHTML = '<div class="n">searching\u2026</div>';
  let d;
  try{
    d = await (await fetch("/run/"+encodeURIComponent(DATA.run_id)+
      "/catalog?q="+encodeURIComponent(q), {cache:"no-store"})).json();
  }catch(e){ box.innerHTML='<div class="n">Search failed.</div>'; return; }
  if(d.error){ box.innerHTML='<div class="n">'+esc(d.error)+'</div>'; return; }
  if(!d.hits.length){ box.innerHTML='<div class="n">Nothing matched.</div>'; return; }
  box.innerHTML = d.hits.map(h =>
    '<div class="cat-hit'+(h.in_run?" have":"")+(CATPICK.has(h.key)?" on":"")+
    '" data-k="'+esc(h.key)+'"'+(h.in_run?' data-have="1"':'')+'>'+
      '<span class="k">'+esc(h.example||h.key)+'</span>'+
      '<span class="n">'+h.candidates+' candidate'+(h.candidates===1?"":"s")+
      (h.in_run?" &middot; already in run":"")+'</span></div>').join("")+
    (d.total > d.hits.length
      ? '<div class="n">'+(d.total-d.hits.length)+' more \u2014 refine the search.</div>' : "");
}
// -- per-channel stream finder ----------------------------------------
//
// The narrowest unit of work in the tool: look at everything the provider
// has for ONE channel, tick what deserves a probe, probe only that. It
// exists because the two ways a better stream stays hidden are both
// invisible from the channel card -- the run probes only the first few of a
// pool, and the matcher may never have connected a differently-labelled
// variant to this channel at all. Neither is fixed by re-running anything.
let STRPICK = new Set(), STRDATA = {pool: [], hits: []};

function strRow(c){
  const bits = [];
  if(c.w) bits.push(c.w+"×"+c.h+(c.fps?"@"+c.fps:""));
  if(c.kbps) bits.push(c.kbps+" kbps");
  if(c.vcodec) bits.push(c.vcodec);
  return '<div class="st-row'+(c.probed?" done":"")+(STRPICK.has(c.stream_id)?" on":"")+
    '" data-s="'+esc(c.stream_id)+'"'+(c.probed?' data-done="1"':'')+'>'+
    '<span class="nm">'+esc(c.name)+
      (c.region?' <em>'+esc(c.region)+'</em>':
        (c.group?' <em>'+esc(c.group)+'</em>':''))+
      (c.excluded ? '<span class="strex" title="Deleted from this channel'+
        (c.excluded.at?' on '+esc(new Date(c.excluded.at*1000).toLocaleDateString()):'')+
        (c.excluded.reason?': “'+esc(c.excluded.reason)+'”':', no reason given')+
        ' — the stream itself was untouched, this is just a note it was '+
        'tried and rejected once already.">⚠ deleted before'+
        (c.excluded.reason?': '+esc(c.excluded.reason):'')+'</span>' : '')+
      '</span>'+
    '<span class="vd">'+(c.probed
      ? esc(c.status||"probed")+(bits.length?" &middot; "+bits.join(" &middot; "):"")
      : "not probed yet")+'</span></div>';
}
function renderStreams(){
  const box = document.getElementById("st-results");
  const parts = [];
  const vd = STRDATA.via_dispatcharr;
  if(vd){
    // The one unambiguous "probe via Dispatcharr": Dispatcharr proxies by
    // CHANNEL, so this can only ever mean the stream it currently has
    // assigned, not an arbitrary candidate.
    parts.push('<div class="st-head">Live on Dispatcharr</div>'+
      '<div class="st-row" id="st-viadispatch">'+
      '<span class="nm">'+esc(vd.stream||"current stream")+
        ' <em>via Dispatcharr\'s own proxy</em></span>'+
      '<span class="vd">'+
        (vd.viewers!=null?vd.viewers+' viewer'+(vd.viewers===1?'':'s')+' now':'')+
        (vd.last_seen?' &middot; last seen '+esc(new Date(vd.last_seen).toLocaleString()):'')+
      '</span>'+
      '<button id="st-viadispatch-btn" style="margin-left:8px;font-size:11px;padding:2px 8px" '+
      'title="Probe exactly what Dispatcharr is serving right now, through its '+
      'own proxy \u2014 tests the real delivery pipe, not just the provider.">'+
      'Probe this path</button></div>');
  }
  parts.push('<div class="st-head">Matched to this channel ('+
    STRDATA.pool.length+')</div>');
  parts.push(STRDATA.pool.length ? STRDATA.pool.map(strRow).join("")
    : '<div class="n">The matcher found nothing for this channel. Search below.</div>');
  if(STRDATA.hits.length){
    parts.push('<div class="st-head">Elsewhere in the catalogue ('+
      STRDATA.hits.length+(STRDATA.hits_total > STRDATA.hits.length
        ? ' of '+STRDATA.hits_total : '')+
      ') &mdash; not matched to this channel</div>');
    parts.push(STRDATA.hits.map(strRow).join(""));
  }
  box.innerHTML = parts.join("");
  const vbtn = document.getElementById("st-viadispatch-btn");
  if(vbtn) vbtn.addEventListener("click", async ()=>{
    const ch = DATA.channels.find(c=>c.key===current); if(!ch) return;
    vbtn.disabled = true; vbtn.textContent = "\u2026";
    try{
      const r = await fetch("/api/run/"+encodeURIComponent(DATA.run_id)+
        "/probe-via-dispatcharr", {method:"POST",
        headers:{"Content-Type":"application/json"},
        body: JSON.stringify({channel_key: ch.key})});
      const d = await r.json();
      if(d.error){ vbtn.textContent = "!"; alert(d.error); return; }
      vbtn.textContent = "Queued";
      STRWATCH = [{rec_key: d.rec_key, name: "Via Dispatcharr", done: false}];
      trackProbes();
    }catch(e){ vbtn.textContent = "!"; }
  });
  const btn = document.getElementById("st-go");
  btn.disabled = STRPICK.size === 0;
  btn.textContent = STRPICK.size ? "Probe "+STRPICK.size+" stream"+
    (STRPICK.size===1?"":"s") : "Probe selected";
}
async function loadStreams(retried){
  const ch = DATA.channels.find(c=>c.key===current); if(!ch) return;
  const q = document.getElementById("st-q").value.trim();
  const box = document.getElementById("st-results");
  box.innerHTML = '<div class="n">looking…</div>';
  let d;
  try{
    d = await (await fetch("/run/"+encodeURIComponent(DATA.run_id)+
      "/candidates?key="+encodeURIComponent(ch.key)+"&q="+encodeURIComponent(q))).json();
  }catch(e){ box.innerHTML='<div class="n">'+esc(String(e))+'</div>'; return; }
  if(d.error){ box.innerHTML='<div class="n">'+esc(d.error)+'</div>'; return; }
  // A channel the matcher missed is usually one the provider spells
  // differently, and the difference is usually a prefix -- "U&YESTERDAY"
  // against five streams all called some form of "Yesterday". Seeding the
  // search with the full title then finds nothing at all, which reads as
  // "the provider doesn't carry it" when the opposite is true. So when the
  // exact name turns up nothing, retry once on its longest word and SAY so,
  // rather than either failing quietly or silently searching for something
  // other than what was typed.
  const loose = looseNeedle(q);
  if(!d.pool.length && !d.hits.length && !retried && loose && loose.toLowerCase() !== q.toLowerCase()){
    const note = document.getElementById("st-result");
    note.className = "mresult show";
    note.textContent = "Nothing matched \u201c"+q+"\u201d \u2014 showing streams "+
      "matching \u201c"+loose+"\u201d instead.";
    document.getElementById("st-q").value = loose;
    return loadStreams(true);
  }
  STRDATA = d;
  renderStreams();
}
function looseNeedle(t){
  const words = String(t||"").split(/[^A-Za-z0-9]+/).filter(w => w.length >= 3);
  if(!words.length) return "";
  return words.sort((a,b) => b.length - a.length)[0];
}
function openStreams(){
  const ch = DATA.channels.find(c=>c.key===current); if(!ch) return;
  STRPICK.clear();
  document.getElementById("st-title").textContent = ch.title;
  // Seeded with the channel's own name, because the search is most often
  // wanted for exactly this channel under a label the matcher did not
  // recognise -- and it is one keystroke to widen or clear.
  document.getElementById("st-q").value = ch.title;
  document.getElementById("st-result").className = "mresult";
  document.getElementById("strmodal").classList.add("on");
  loadStreams();
}
document.getElementById("st-close").addEventListener("click", ()=>
  document.getElementById("strmodal").classList.remove("on"));
let strTimer = null;
document.getElementById("st-q").addEventListener("input", ()=>{
  clearTimeout(strTimer); strTimer = setTimeout(loadStreams, 350);
});
document.getElementById("st-results").addEventListener("click", e=>{
  const row = e.target.closest(".st-row"); if(!row || row.dataset.done) return;
  const id = row.dataset.s;
  if(STRPICK.has(id)) STRPICK.delete(id); else STRPICK.add(id);
  row.classList.toggle("on");
  const btn = document.getElementById("st-go");
  btn.disabled = STRPICK.size === 0;
  btn.textContent = STRPICK.size ? "Probe "+STRPICK.size+" stream"+
    (STRPICK.size===1?"":"s") : "Probe selected";
});
document.getElementById("st-go").addEventListener("click", async ()=>{
  const ch = DATA.channels.find(c=>c.key===current); if(!ch) return;
  const btn = document.getElementById("st-go");
  const res = document.getElementById("st-result");
  btn.disabled = true; btn.textContent = "Queuing…";
  try{
    const r = await fetch("/api/run/"+encodeURIComponent(DATA.run_id)+
      "/candidate-add", {method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({channel_key: ch.key, stream_ids: [...STRPICK]})});
    const d = await r.json();
    if(d.error){ res.className="mresult show bad"; res.textContent=d.error; }
    else{
      res.className="mresult show good";
      STRPICK.clear();
      // The queue is serial by design and a probe takes ten seconds or so,
      // so this is a real wait -- minutes for a handful of streams. Showing
      // nothing for that long reads as a failure, which is exactly how it
      // read the first time it was used. The queue already knows each
      // stream's state and position; from here on it is simply displayed.
      STRWATCH = (d.streams || []).map(x => ({
        rec_key: x.rec_key, name: x.name,
        stream_id: String(x.rec_key).split("|").slice(1).join("|"),
        stream_key: x.stream_key, done: false}));
      trackProbes();
      offerAlias(d.streams || []);
    }
  }catch(e){ res.className="mresult show bad"; res.textContent=String(e); }
  btn.disabled = false; btn.textContent = "Probe selected";
});
let STRWATCH = [], strPoll = null;

// Each ticked stream's own row reports its state, and the summary line
// counts down -- so a two-minute serial wait looks like progress instead of
// nothing happening. The card is refreshed as results land rather than only
// at the end, because the first finished probe is often the answer.
async function trackProbes(){
  if(strPoll) clearTimeout(strPoll);
  let snap;
  try{ snap = await (await fetch("/api/queue", {cache:"no-store"})).json(); }
  catch(e){ return; }
  const keys = snap.keys || {};
  let landed = false;
  STRWATCH.forEach(w => {
    const st = keys[DATA.run_id+"|"+w.rec_key];
    const row = document.querySelector('.st-row[data-s="'+CSS.escape(w.stream_id)+'"]');
    if(st){
      w.state = st.state;
      if(row) row.querySelector(".vd").textContent =
        st.state === "running" ? "probing\u2026"
                               : "queued \u00b7 #"+(st.position||"?");
    }else if(!w.done){
      w.done = true; landed = true;
      if(row) row.querySelector(".vd").textContent = "probed";
    }
  });
  const done = STRWATCH.filter(w=>w.done).length;
  const res = document.getElementById("st-result");
  if(snap.blocked && done < STRWATCH.length){
    res.className = "mresult show";
    res.textContent = snap.blocked + ". "+done+" of "+STRWATCH.length+
      " probed so far; the rest resume by themselves.";
    return (strPoll = setTimeout(trackProbes, 3000));
  }
  if(done < STRWATCH.length){
    // This used to always say "one connection at a time" and estimate at
    // 10s each regardless -- wrong for any provider saved with its own
    // higher concurrency (Settings > provider), which the actual queue
    // DOES already respect via its per-provider lane limit. The text just
    // never reflected that. Real running count, observed from the queue
    // itself, is used both to describe what's actually happening and to
    // scale the estimate -- a provider probing 4 at once finishes in a
    // quarter the time a serial one would, and the message should say so.
    const runningNow = STRWATCH.filter(w=>w.state==="running").length;
    const remaining = STRWATCH.length-done;
    const etaSeconds = 10 * Math.ceil(remaining / Math.max(1, runningNow));
    res.className = "mresult show";
    res.textContent = done+" of "+STRWATCH.length+" probed"+
      (runningNow ? " \u00b7 "+runningNow+" running now" : "")+
      " \u2014 about "+etaSeconds+"s more.";
  }else{
    res.className = "mresult show good";
    res.textContent = "All "+STRWATCH.length+" probed. Results are on the card.";
  }
  if(landed) await refreshChannel(current);
  if(done < STRWATCH.length){
    strPoll = setTimeout(trackProbes, 2000);
  }else if(document.getElementById("strmodal").classList.contains("on")){
    loadStreams();       // redraw with the real specs now they exist
  }
}

// Attaching a stream whose own name normalises differently IS the statement
// an alias records. Offering it here is the only moment both halves are
// known without anyone having to work out what to type -- and it is what
// stops the same channel needing this by hand on every future run.
async function offerAlias(streams){
  const ch = DATA.channels.find(c=>c.key===current); if(!ch) return;
  const odd = streams.filter(x => x.stream_key && x.stream_key !== ch.key);
  if(!odd.length) return;
  const target = odd[0].stream_key;
  if(!odd.every(x => x.stream_key === target)) return;  // ambiguous, stay quiet
  if(!confirm("Remember that \u201c"+ch.title+"\u201d is the same channel as "+
              "\u201c"+target+"\u201d?\n\nThe provider files it under a name the "+
              "matcher cannot connect, so it had to be found by hand. Saving "+
              "this as an alias makes future runs match it automatically.\n\n"+
              "OK = remember it. Cancel = just this once."))
    return;
  try{
    const r = await fetch("/api/aliases", {method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({name: ch.key, canonical: target})});
    const d = await r.json();
    if(d.error) alert("Could not save the alias: "+d.error);
  }catch(e){ /* the probes still ran; the alias is a bonus */ }
}
document.getElementById("st-q").addEventListener("keydown", e=>{
  if(e.key === "Enter"){ clearTimeout(strTimer); loadStreams(); }
});

// -- import from Dispatcharr ------------------------------------------
//
// probarr could only ever push. A channel added by hand in Dispatcharr was
// invisible here, so the two drifted and neither side was the whole truth.
// Reading them back makes the relationship two-way: the point is not to
// mirror Dispatcharr, it is to put its current pick next to the provider's
// alternatives and let the same probing decide whether it can be beaten.
let IMPFOUND = [], IMPPICK = new Set();

async function openImport(){
  IMPFOUND = []; IMPPICK.clear();
  document.getElementById("imp-results").innerHTML =
    '<div class="n">Choose a connection, then press Look.</div>';
  document.getElementById("imp-result").className = "mresult";
  document.getElementById("imp-go").disabled = true;
  document.getElementById("impmodal").classList.add("on");
  const sel = document.getElementById("imp-prov");
  if(!sel.options.length){
    let d;
    try{ d = await (await fetch("/api/providers")).json(); }
    catch(e){ return; }
    const hits = (d.providers||[]).filter(p => p.scheme === "dispatcharr");
    sel.innerHTML = hits.length
      ? hits.map(p => '<option value="'+esc(p.name)+'">'+esc(p.name)+
          ' — '+esc(p.redacted)+'</option>').join("")
      : '<option value="">No Dispatcharr connection saved</option>';
    document.getElementById("imp-plan").disabled = !hits.length;
  }
}
function impCount(){
  const bar = document.getElementById("imp-bar");
  bar.style.display = IMPFOUND.length ? "flex" : "none";
  document.getElementById("imp-count").innerHTML =
    "<b>"+IMPPICK.size+"</b> of "+IMPFOUND.length+" selected";
  document.getElementById("imp-go").disabled = IMPPICK.size === 0;
}
function renderImport(){
  const box = document.getElementById("imp-results");
  if(!IMPFOUND.length){
    box.innerHTML = '<div class="n">Dispatcharr has no channels.</div>';
    document.getElementById("imp-bar").style.display = "none";
    return;
  }
  box.innerHTML = IMPFOUND.map(c =>
    '<div class="cat-hit'+(IMPPICK.has(c.key)?" on":"")+'" data-k="'+esc(c.key)+'">'+
      '<span class="k">'+(c.number!=null?esc(c.number)+' &middot; ':'')+esc(c.name)+
      '</span><span class="n">'+
      (c.in_run?"already in this run &middot; ":"")+
      (c.group?esc(c.group)+" &middot; ":"")+
      (c.candidates?c.candidates+' provider candidate'+(c.candidates===1?'':'s')
                   :'no provider candidate')+
      ' &middot; '+(c.probes ? c.probes+' probe'+(c.probes===1?'':'s')
                             : 'no new probes')+
      (c.current?' &middot; now: '+esc(c.current):'')+
      '</span></div>').join("");
  impCount();
}
document.getElementById("imp-all").addEventListener("click", ()=>{
  IMPPICK = new Set(IMPFOUND.filter(c=>c.key).map(c=>c.key));
  renderImport();
});
document.getElementById("imp-none").addEventListener("click", ()=>{
  IMPPICK.clear(); renderImport();
});
document.getElementById("importdispatch").addEventListener("click", ()=>{
  document.getElementById("addmenu").classList.remove("on");
  openImport();
});
document.getElementById("imp-probe").addEventListener("change", ()=>{
  if(IMPFOUND.length) document.getElementById("imp-plan").click();
});
document.getElementById("imp-close").addEventListener("click", ()=>
  document.getElementById("impmodal").classList.remove("on"));
document.getElementById("imp-results").addEventListener("click", e=>{
  const hit = e.target.closest(".cat-hit"); if(!hit) return;
  const k = hit.dataset.k;
  if(IMPPICK.has(k)) IMPPICK.delete(k); else IMPPICK.add(k);
  hit.classList.toggle("on");
  impCount();
});
document.getElementById("imp-plan").addEventListener("click", async ()=>{
  const btn = document.getElementById("imp-plan");
  const res = document.getElementById("imp-result");
  btn.disabled = true; btn.textContent = "Looking…";
  try{
    const r = await fetch("/api/run/"+encodeURIComponent(DATA.run_id)+
      "/dispatcharr-import", {method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({provider: document.getElementById("imp-prov").value,
                            probe: document.getElementById("imp-probe").checked,
                            plan: true})});
    const d = await r.json();
    if(d.error){ res.className="mresult show bad"; res.textContent=d.error; }
    else{
      IMPFOUND = d.channels || [];
      // Anything not already curated here is pre-selected: that is the
      // reason to open this at all. Ones already in the run stay opt-in,
      // because importing them only re-records where they came from.
      IMPPICK = new Set(IMPFOUND.filter(c=>!c.in_run && c.key).map(c=>c.key));
      res.className = "mresult show";
      // The cost is stated before it is spent: on a one-connection
      // provider that number is the difference between a click and an
      // overnight job.
      res.textContent = IMPFOUND.length+" channel(s) in Dispatcharr, "+
        IMPFOUND.filter(c=>!c.in_run).length+" not yet in this run. "+
        "Importing all of them would cost "+(d.probes||0)+" probe(s); "+
        "everything already verified is left alone.";
      renderImport();
    }
  }catch(e){ res.className="mresult show bad"; res.textContent=String(e); }
  btn.disabled = false; btn.textContent = "Look";
});
document.getElementById("imp-go").addEventListener("click", async ()=>{
  const btn = document.getElementById("imp-go");
  const res = document.getElementById("imp-result");
  btn.disabled = true; btn.textContent = "Importing…";
  try{
    const r = await fetch("/api/run/"+encodeURIComponent(DATA.run_id)+
      "/dispatcharr-import", {method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({provider: document.getElementById("imp-prov").value,
                            probe: document.getElementById("imp-probe").checked,
                            keys: [...IMPPICK]})});
    const d = await r.json();
    if(d.error){ res.className="mresult show bad"; res.textContent=d.error; }
    else{
      res.className="mresult show good";
      res.textContent = d.imported.length+" channel(s) imported, "+d.queued+
        " probe(s) queued"+
        (d.skipped ? ", "+d.skipped+" already verified and left alone" : "")+
        " — they appear in the list as results land.";
    }
  }catch(e){ res.className="mresult show bad"; res.textContent=String(e); }
  btn.textContent = "Import selected"; btn.disabled = false;
});

// -- Groups view --------------------------------------------------------
//
// The channel list already lets you set ONE channel's group at a time.
// This is the other direction: see every group at once, what is in each,
// and move things between them without hunting through the full list.
let GRPOPEN = new Set(), GRPPICK = new Set(), grpDragKey = null;

function chanGroup(ch){ return (SEL[ch.key]||{}).group || ""; }

function groupsData(){
  const by = {};
  ((DATA.meta && DATA.meta.extra_groups) || []).forEach(g => { by[g] = by[g] || []; });
  DATA.channels.forEach(ch => {
    const g = chanGroup(ch) || "(no group)";
    (by[g] = by[g] || []).push(ch);
  });
  Object.values(by).forEach(list =>
    list.sort((a,b) => (a.number??1e9) - (b.number??1e9)));
  // Named groups first, alphabetically; "(no group)" always last -- it is
  // the leftover bucket, not a destination anyone is looking for.
  const names = Object.keys(by).filter(n => n !== "(no group)").sort();
  if(by["(no group)"]) names.push("(no group)");
  return names.map(n => [n, by[n]]);
}

function renderGroups(){
  const groups = groupsData();
  document.getElementById("grpacc-sel").textContent =
    GRPPICK.size ? GRPPICK.size+" channel(s) selected — click a group's "+
      "Move button, or click again to deselect" : "";
  document.getElementById("grpacc").innerHTML = groups.map(([name, chans]) => {
    const open = GRPOPEN.has(name);
    const movable = GRPPICK.size && chans.some(c => !GRPPICK.has(c.key));
    return '<div class="grpsec'+(open?' open':'')+(movable?' hasmove':'')+
      '" data-g="'+esc(name)+'">'+
      '<div class="grphead" data-toggle="'+esc(name)+'">'+
        '<span class="plus">'+(open?'−':'+')+'</span>'+
        '<span class="nm">'+esc(name)+'</span>'+
        '<span class="n">'+chans.length+' channel'+(chans.length===1?'':'s')+'</span>'+
        '<button class="grpmove" data-moveto="'+esc(name)+'">Move '+
          GRPPICK.size+' here</button>'+
        (name!=="(no group)"?'<button class="grpdel" data-delgroup="'+esc(name)+
          '" title="Remove this group. Any channel still in it goes to (no '+
          'group), nothing else changes.">\u2715</button>':'')+
      '</div>'+
      '<div class="grpbody" data-body="'+esc(name)+'">'+
        (chans.length ? chans.map(c =>
          '<div class="grprow'+(GRPPICK.has(c.key)?' picked':'')+
            '" draggable="true" data-k="'+esc(c.key)+'">'+
            '<input type="checkbox" data-pick="'+esc(c.key)+'"'+
              (GRPPICK.has(c.key)?' checked':'')+'>'+
            '<span class="dot '+state(c)+'"></span>'+
            '<span class="num">'+(c.number!=null?c.number:'')+'</span>'+
            '<span class="nm" style="flex:1">'+esc(c.title)+'</span>'+
          '</div>').join("")
         : '<div class="grpempty">Nothing here.</div>')+
      '</div></div>';
  }).join("");
  wireGroupsDrag();
}

function wireGroupsDrag(){
  const acc = document.getElementById("grpacc");
  acc.querySelectorAll(".grprow").forEach(row => {
    row.addEventListener("dragstart", e => {
      grpDragKey = row.dataset.k;
      row.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      try{ e.dataTransfer.setData("text/plain", grpDragKey); }catch(_){}
    });
    row.addEventListener("dragend", () => {
      grpDragKey = null;
      acc.querySelectorAll(".grprow,.grpsec").forEach(el =>
        el.classList.remove("dragging","dropinto","dropover"));
    });
    row.addEventListener("dragover", e => {
      if(!grpDragKey || row.dataset.k === grpDragKey) return;
      e.preventDefault();
      row.classList.add("dropinto");
    });
    row.addEventListener("dragleave", () => row.classList.remove("dropinto"));
    row.addEventListener("drop", async e => {
      e.preventDefault();
      row.classList.remove("dropinto");
      if(!grpDragKey || row.dataset.k === grpDragKey) return;
      const src = DATA.channels.find(c => c.key === grpDragKey);
      const tgt = DATA.channels.find(c => c.key === row.dataset.k);
      if(!src || !tgt) return;
      if(chanGroup(src) === chanGroup(tgt)){
        const list = (groupsData().find(([n]) => n === (chanGroup(src)||"(no group)"))||[,[]])[1];
        const keys = list.map(c => c.key).filter(k => k !== src.key);
        keys.splice(keys.indexOf(tgt.key), 0, src.key);
        await reorderGroup(keys);
      } else {
        moveToGroup([src.key], chanGroup(tgt));
      }
    });
  });
  acc.querySelectorAll(".grpsec").forEach(sec => {
    sec.addEventListener("dragover", e => {
      if(!grpDragKey) return;
      e.preventDefault();
      sec.classList.add("dropover");
    });
    sec.addEventListener("dragleave", e => {
      if(!sec.contains(e.relatedTarget)) sec.classList.remove("dropover");
    });
    sec.addEventListener("drop", e => {
      // Only the body/empty-space handles the drop; a row inside it already
      // handled its own drop and stopped this from being redundant work --
      // but dropping on the header or the empty body still needs to land.
      if(e.target.closest(".grprow")) return;
      e.preventDefault();
      sec.classList.remove("dropover");
      if(!grpDragKey) return;
      const g = sec.dataset.g === "(no group)" ? "" : sec.dataset.g;
      moveToGroup([grpDragKey], g);
    });
  });
}

async function reorderGroup(keys){
  try{
    const r = await fetch("/api/run/"+encodeURIComponent(DATA.run_id)+"/reorder-group",
      {method:"POST", headers:{"Content-Type":"application/json"},
       body: JSON.stringify({keys})});
    const d = await r.json();
    if(d.error){ alert("Could not reorder: "+d.error); return; }
    Object.entries(d.numbers).forEach(([k,n]) => {
      const ch = DATA.channels.find(c=>c.key===k); if(ch) ch.number = n;
    });
    renderList(); renderGroups();
  }catch(e){ alert("Request failed."); }
}
async function addGroup(name){
  name = (name||"").trim(); if(!name) return;
  const r = await fetch("/api/run/"+encodeURIComponent(DATA.run_id)+"/groups",
    {method:"POST", headers:{"Content-Type":"application/json"},
     body: JSON.stringify({action:"add", name})});
  const d = await r.json();
  if(d.error){ alert(d.error); return; }
  DATA.meta.extra_groups = d.extra_groups;
  GRPOPEN.add(name);
  renderGroups();
}
async function removeGroup(name){
  if(!confirm("Remove group \""+name+"\"?\n\nAny channel still in it moves "+
              "to (no group). Nothing else changes.")) return;
  const r = await fetch("/api/run/"+encodeURIComponent(DATA.run_id)+"/groups",
    {method:"POST", headers:{"Content-Type":"application/json"},
     body: JSON.stringify({action:"remove", name})});
  const d = await r.json();
  if(d.error){ alert(d.error); return; }
  DATA.meta.extra_groups = d.extra_groups;
  DATA.channels.forEach(ch => { if(chanGroup(ch)===name) delete SEL[ch.key].group; });
  renderList(); renderGroups();
}

function moveToGroup(keys, group){
  const sel = {};
  keys.forEach(k => { SEL[k] = {...(SEL[k]||{}), group: group || undefined}; });
  save();
  GRPPICK.clear();
  renderList(); renderDetail(); renderGroups();
}

document.getElementById("opengroups").addEventListener("click", () => {
  GRPPICK.clear();
  if(!GRPOPEN.size) groupsData().forEach(([n]) => GRPOPEN.add(n));
  renderGroups();
  document.getElementById("groupsmodal").classList.add("on");
});
document.getElementById("groups-close").addEventListener("click", () =>
  document.getElementById("groupsmodal").classList.remove("on"));
document.getElementById("groups-x").addEventListener("click", () =>
  document.getElementById("groupsmodal").classList.remove("on"));
document.getElementById("grpacc-add").addEventListener("click", () => {
  addGroup(document.getElementById("grpacc-new").value);
  document.getElementById("grpacc-new").value = "";
});
document.getElementById("grpacc-new").addEventListener("keydown", e => {
  if(e.key === "Enter"){ e.preventDefault(); document.getElementById("grpacc-add").click(); }
});
document.getElementById("grpacc-expand").addEventListener("click", () => {
  const allOpen = groupsData().every(([n]) => GRPOPEN.has(n));
  GRPOPEN = allOpen ? new Set() : new Set(groupsData().map(([n]) => n));
  document.getElementById("grpacc-expand").textContent = allOpen ? "expand all" : "collapse all";
  renderGroups();
});
document.getElementById("grpacc").addEventListener("click", e => {
  const move = e.target.closest("[data-moveto]");
  if(move){
    moveToGroup([...GRPPICK], move.dataset.moveto === "(no group)" ? "" : move.dataset.moveto);
    return;
  }
  const del = e.target.closest("[data-delgroup]");
  if(del){ removeGroup(del.dataset.delgroup); return; }
  const head = e.target.closest("[data-toggle]");
  if(head){
    const g = head.dataset.toggle;
    GRPOPEN.has(g) ? GRPOPEN.delete(g) : GRPOPEN.add(g);
    renderGroups();
    return;
  }
  if(e.target.matches("[data-pick]")){
    const k = e.target.dataset.pick;
    GRPPICK.has(k) ? GRPPICK.delete(k) : GRPPICK.add(k);
    renderGroups();
    return;
  }
  const row = e.target.closest(".grprow");
  if(row){
    GRPPICK.has(row.dataset.k) ? GRPPICK.delete(row.dataset.k) : GRPPICK.add(row.dataset.k);
    renderGroups();
  }
});

document.getElementById("addmenubtn").addEventListener("click", (e)=>{
  e.stopPropagation();
  document.getElementById("addmenu").classList.toggle("on");
});
document.addEventListener("click", (e)=>{
  const menu = document.getElementById("addmenu");
  if(menu.classList.contains("on") && !menu.contains(e.target)
     && e.target.id !== "addmenubtn") menu.classList.remove("on");
});
document.addEventListener("keydown", (e)=>{
  if(e.key === "Escape") document.getElementById("addmenu").classList.remove("on");
});
document.getElementById("addchannels").addEventListener("click", ()=>{
  document.getElementById("addmenu").classList.remove("on");
  openCatalog();
});
document.getElementById("cat-close").addEventListener("click", ()=>
  document.getElementById("catmodal").classList.remove("on"));
document.getElementById("cat-q").addEventListener("input", ()=>{
  clearTimeout(catTimer); catTimer = setTimeout(catSearch, 300);
});
document.getElementById("cat-results").addEventListener("click", (e)=>{
  const hit = e.target.closest(".cat-hit"); if(!hit || hit.dataset.have) return;
  const k = hit.dataset.k;
  CATPICK.has(k) ? CATPICK.delete(k) : CATPICK.add(k);
  hit.classList.toggle("on", CATPICK.has(k));
  document.getElementById("cat-add").disabled = CATPICK.size === 0;
});
document.getElementById("cat-add").addEventListener("click", async ()=>{
  const btn = document.getElementById("cat-add");
  const res = document.getElementById("cat-result");
  btn.disabled = true; btn.textContent = "Adding\u2026";
  try{
    const r = await fetch("/api/run/"+encodeURIComponent(DATA.run_id)+"/catalog-add",
      {method:"POST", headers:{"Content-Type":"application/json"},
       body: JSON.stringify({keys:[...CATPICK]})});
    const d = await r.json();
    if(d.error){ res.className="mresult show bad"; res.textContent="Error: "+d.error; }
    else{
      res.className="mresult show good";
      res.textContent = d.added.length+" channel(s) added, "+d.queued+
        " probe(s) queued. They appear in the list as results land \u2014 "+
        "reload once probing finishes.";
      CATPICK.clear(); catSearch();
    }
  }catch(e){ res.className="mresult show bad"; res.textContent="Request failed."; }
  btn.disabled=false; btn.textContent="Add selected";
});

// Grouping. Applies to the current multi-selection when there is one, else
// to the channel in view -- so "tidy these twelve into Sports" is one action
// rather than twelve. Stored as a per-channel decision (and promoted to the
// lineup, so it survives into later runs), and carried through to
// Dispatcharr by the exporter, where it beats the export form's blanket
// group because it is the more specific instruction.
// The counterpart to adding a channel from the catalogue. Two-step on
// purpose: removing from the run is cheap and reversible (re-add it from
// the catalogue), whereas deleting from Dispatcharr is neither, so it is a
// separate explicit confirmation rather than a checkbox that is easy to
// leave ticked by accident.
async function removeChannel(){
  const ch = DATA.channels.find(c=>c.key===current); if(!ch) return;
  if(!confirm("Remove \u201c"+ch.title+"\u201d from this run?\n\n"+
              "Its probe results and captured frames are deleted. You can "+
              "re-add it later from the provider catalogue."))
    return;
  // Staged, not done now. Everything else here is curate locally, review
  // the diff, then push -- so this reads as "mark it for deletion", and the
  // push preview is where it becomes real and reviewable.
  const alsoDispatcharr = confirm(
    "Also delete this channel from Dispatcharr?\n\n"+
    "OK = mark it for deletion. Nothing is deleted now \u2014 it happens on "+
    "your next full push, and appears in the push preview first.\n"+
    "Cancel = leave Dispatcharr alone, remove from this run only.");
  const btn = document.getElementById("removechanbtn");
  btn.disabled = true; btn.textContent = "Removing\u2026";
  try{
    const r = await fetch("/api/run/"+encodeURIComponent(DATA.run_id)+"/channel-remove",
      {method:"POST", headers:{"Content-Type":"application/json"},
       body: JSON.stringify({channel_key: current,
                             also_dispatcharr: alsoDispatcharr})});
    const d = await r.json();
    if(d.error){ alert("Could not remove: "+d.error); btn.disabled=false;
                 btn.textContent="Remove"; return; }
    if(alsoDispatcharr && !d.staged)
      alert("Removed from the run, but it could not be marked for deletion "+
            "in Dispatcharr: this channel has no number, which is how a "+
            "Dispatcharr channel is identified. Delete it there by hand.");
    // Drop it from the in-memory model too rather than reloading, so the
    // current filter, scroll position and marked set all survive.
    const i = DATA.channels.findIndex(c=>c.key===current);
    DATA.channels.splice(i,1);
    delete SEL[current]; MARKED.delete(current); delete PENDING[current];
    const nxt = visible()[Math.min(i, visible().length-1)] || DATA.channels[0];
    current = nxt ? nxt.key : null;
    renderList(); renderDetail(); checkPending();
  }catch(e){
    alert("Request failed."); btn.disabled=false; btn.textContent="Remove";
  }
}

// Renaming matters most next to Duplicate: two copies of one feed are
// otherwise indistinguishable in the list. Updates the in-memory model in
// place rather than reloading, so the current filter and scroll survive.
// Click the title, or the pencil beside it, to edit it in place -- a
// separate Rename button that opened a browser prompt() was a detour for
// something this ordinary; every other renamed thing on the web is edited
// where it sits.
function startRename(){
  const span = document.getElementById("titletext"); if(!span) return;
  const ch = DATA.channels.find(c=>c.key===current); if(!ch) return;
  const input = document.createElement("input");
  input.type = "text"; input.value = ch.title || ""; input.id = "titleinput";
  input.style.cssText = "font:inherit;font-weight:inherit;background:var(--bg);" +
    "color:var(--text);border:1px solid var(--accent);border-radius:4px;" +
    "padding:1px 6px;width:min(420px,60vw)";
  span.replaceWith(input);
  document.getElementById("titleedit").style.display = "none";
  input.focus(); input.select();
  const commit = async () => {
    const v = input.value.trim();
    input.replaceWith(span);
    document.getElementById("titleedit").style.display = "";
    if(!v || v === ch.title) return;
    span.textContent = v;   // optimistic; reverted below on failure
    try{
      const r = await fetch("/api/run/"+encodeURIComponent(DATA.run_id)+
        "/channel-rename",
        {method:"POST", headers:{"Content-Type":"application/json"},
         body: JSON.stringify({channel_key: current, name: v})});
      const d = await r.json();
      if(d.error){ alert("Could not rename: "+d.error); span.textContent = ch.title; return; }
      ch.title = v;
      renderList(); checkPending();
    }catch(e){ alert("Request failed."); span.textContent = ch.title; }
  };
  input.addEventListener("keydown", e => {
    if(e.key === "Enter"){ e.preventDefault(); input.blur(); }
    if(e.key === "Escape"){ e.preventDefault(); input.value = ch.title; input.blur(); }
  });
  input.addEventListener("blur", commit, {once: true});
}

// Same "click it, edit in place" pattern as the title, and for the same
// reason it needs one at all: a channel with no number is invisible in
// every export (see _resolve_curated in web.py), so fixing it has to be
// possible from the exact place that warns about it, not a detour to some
// other screen.
function startRenumber(){
  const span = document.getElementById("numtext"); if(!span) return;
  const ch = DATA.channels.find(c=>c.key===current); if(!ch) return;
  const input = document.createElement("input");
  input.type = "number"; input.min = "1"; input.step = "1";
  input.value = ch.number!=null ? ch.number : "";
  input.id = "numinput";
  input.style.cssText = "font:inherit;font-weight:inherit;background:var(--bg);" +
    "color:var(--text);border:1px solid var(--accent);border-radius:4px;" +
    "padding:1px 6px;width:6em";
  span.replaceWith(input);
  document.getElementById("numedit").style.display = "none";
  input.focus(); input.select();
  const restore = () => {
    input.replaceWith(span);
    document.getElementById("numedit").style.display = "";
  };
  const commit = async () => {
    const v = input.value.trim();
    const n = v === "" ? NaN : parseInt(v, 10);
    if(!v || !Number.isInteger(n) || n <= 0 || n === ch.number){ restore(); return; }
    try{
      const r = await fetch("/api/run/"+encodeURIComponent(DATA.run_id)+
        "/channel-renumber",
        {method:"POST", headers:{"Content-Type":"application/json"},
         body: JSON.stringify({channel_key: current, number: n})});
      const d = await r.json();
      restore();
      if(d.error){ alert("Could not set number: "+d.error); return; }
      ch.number = n;
      renderDetail(); renderList(); checkPending();
    }catch(e){ restore(); alert("Request failed."); }
  };
  input.addEventListener("keydown", e => {
    if(e.key === "Enter"){ e.preventDefault(); input.blur(); }
    if(e.key === "Escape"){ e.preventDefault(); input.value = ch.number!=null?ch.number:""; input.blur(); }
  });
  input.addEventListener("blur", commit, {once: true});
}

// Same feed in two groups. Dispatcharr identifies a channel by its NUMBER,
// so a copy at a different number is genuinely a second channel there --
// which is what stops one group's push from undoing the other's. Results
// are copied rather than re-probed, so this costs no provider connections.
function toggleInclude(){
  // Bulk-aware the same way Set group already is: a multi-selection
  // (Cmd/Ctrl-click several rows) applies to the whole marked set, not
  // just whichever channel happens to be open. The direction is decided
  // ONCE from the open channel's current state and applied identically to
  // every marked channel -- independent per-channel toggling of a mixed
  // batch (some already excluded, some not) would be unpredictable to
  // reason about from one click.
  const keys = MARKED.size > 1 ? [...MARKED] : [current];
  const currentlyIncluded = (SEL[current] || {}).include !== false;
  // Toggle the EFFECTIVE state, not the raw stored value -- s.include is
  // commonly absent (meaning "included"), and `!s.include` on undefined
  // flips to true, which looks like a no-op but actually writes an
  // explicit include:true over what was already implicitly true.
  const newValue = !currentlyIncluded;
  for(const k of keys){
    const s = SEL[k] = SEL[k] || {};
    s.include = newValue;
  }
  save(); renderList(); renderDetail();
}
async function duplicateChannel(){
  const ch = DATA.channels.find(c=>c.key===current); if(!ch) return;
  const group = prompt("Duplicate \u201c"+ch.title+"\u201d into which group?"+
                       String.fromCharCode(10)+
                       "(leave blank to decide later)", "");
  if(group === null) return;
  const btn = document.getElementById("dupchanbtn");
  btn.disabled = true; btn.textContent = "Copying\u2026";
  try{
    const r = await fetch("/api/run/"+encodeURIComponent(DATA.run_id)+
      "/channel-duplicate",
      {method:"POST", headers:{"Content-Type":"application/json"},
       body: JSON.stringify({channel_key: current, group: group.trim()})});
    const d = await r.json();
    if(d.error){ alert("Could not duplicate: "+d.error); }
    else { location.reload(); return; }
  }catch(e){ alert("Request failed."); }
  btn.disabled = false; btn.textContent = "Duplicate";
}

let grpKeys = [], grpChoice = "";
async function setGroup(){
  grpKeys = MARKED.size ? [...MARKED] : (current ? [current] : []);
  if(!grpKeys.length) return;
  grpChoice = (SEL[grpKeys[0]]||{}).group || "";
  document.getElementById("grp-title").textContent = grpKeys.length>1
    ? "Set group for "+grpKeys.length+" channels" : "Set group";
  document.getElementById("grp-new").value = "";
  const box = document.getElementById("grp-list");
  box.innerHTML = "loading\u2026";
  document.getElementById("grpmodal").classList.add("on");
  let groups = [];
  try{
    groups = (await (await fetch("/run/"+encodeURIComponent(DATA.run_id)+
      "/groups", {cache:"no-store"})).json()).groups || [];
  }catch(e){}
  box.innerHTML = groups.length
    ? groups.map(g=>'<span class="grp-opt'+(g===grpChoice?" on":"")+
        '" data-g="'+esc(g)+'">'+esc(g)+'</span>').join("")
    : '<span class="n">None yet \u2014 type a new one below.</span>';
}
document.getElementById("grp-list").addEventListener("click", e=>{
  const o = e.target.closest(".grp-opt"); if(!o) return;
  grpChoice = o.dataset.g;
  document.getElementById("grp-new").value = "";
  [...document.querySelectorAll(".grp-opt")].forEach(x=>
    x.classList.toggle("on", x===o));
});
document.getElementById("grp-new").addEventListener("input", e=>{
  if(e.target.value.trim()){
    grpChoice = e.target.value.trim();
    [...document.querySelectorAll(".grp-opt")].forEach(x=>x.classList.remove("on"));
  }
});
function applyGroup(v){
  grpKeys.forEach(k => { SEL[k] = {...(SEL[k]||{}), group: v || undefined}; });
  save(); document.getElementById("grpmodal").classList.remove("on");
  renderList(); renderDetail(); checkPending();
}
document.getElementById("grp-cancel").addEventListener("click", ()=>
  document.getElementById("grpmodal").classList.remove("on"));
document.getElementById("grp-clear").addEventListener("click", ()=> applyGroup(""));
document.getElementById("grp-save").addEventListener("click", ()=>{
  const typed = document.getElementById("grp-new").value.trim();
  applyGroup(typed || grpChoice);
});

// Live per-source EPG comparison: what does each SAVED EPG source say is on
// this channel RIGHT NOW, versus what the run's own guide said at capture
// time. Answers "is the guide I used still accurate, and is there a better
// one now" -- something the run-time `expected` field alone cannot, since
// it is frozen the instant probing finished and only ever reflects the one
// EPG source the run was configured with.
async function openEpgModal(){
  const ch = DATA.channels.find(c=>c.key===current); if(!ch) return;
  document.getElementById("em-title").textContent = ch.title;
  const captured = document.getElementById("em-captured");
  captured.innerHTML = ch.expected
    ? "Captured at "+esc(ch.expected.window||"")+": <span class=\"t\">"+
      esc(ch.expected.title)+"</span>"
    : "No EPG was captured for this channel at probe time.";
  const box = document.getElementById("em-sources");
  box.innerHTML = "loading\u2026";
  document.getElementById("em-result").className = "mresult";
  document.getElementById("epgmodal").classList.add("on");

  let data;
  try{
    data = await (await fetch("/run/"+encodeURIComponent(DATA.run_id)+
      "/epg-check?key="+encodeURIComponent(current), {cache:"no-store"})).json();
  }catch(e){
    box.innerHTML = "";
    const r = document.getElementById("em-result");
    r.className = "mresult show bad"; r.textContent = "Request failed."; return;
  }
  if(data.error){
    box.innerHTML = "";
    const r = document.getElementById("em-result");
    r.className = "mresult show bad"; r.textContent = "Error: "+data.error; return;
  }
  const sel = SEL[current] || {};
  if(!data.sources.length){
    box.innerHTML = '<div class="noprov">No EPG sources saved yet. '+
      '<a href="/providers">Add one</a> first.</div>';
    return;
  }
  // With no explicit choice, the channel is not using "none of these" --
  // it is using whichever matched source comes first, the same first-match
  // rule the export and the guide capture both apply. Leaving all three
  // looking equally unselected hid that a real, active choice already
  // exists; it just was not made by a person.
  const explicit = !!sel.epg_source;
  const firstMatched = data.sources.find(s => s.matched);
  box.innerHTML = data.sources.map(s => {
    const isCurrent = explicit ? sel.epg_source === s.source
                               : (firstMatched && s.source === firstMatched.source);
    let prog;
    if(!s.matched) prog = '<span class="nomatch">channel not found in this source</span>';
    else if(s.error) prog = '<span class="nomatch">error: '+esc(s.error)+'</span>';
    else if(!s.now) prog = '<span class="nomatch">matched, but nothing scheduled right now</span>';
    else prog = '<span class="t">'+esc(s.now.title)+'</span>'+
      (s.now.window?' ('+esc(s.now.window)+')':'');
    const manualPin = sel.epg_channel_source === s.source && sel.epg_channel_id;
    const badge = isCurrent
      ? (manualPin ? 'In use (manual)' : explicit ? 'In use' : 'In use by default')
      : 'Use this';
    return '<div class="em-src'+(isCurrent?' current':'')+'">'+
      '<div class="name">'+esc(s.source)+
        (isCurrent && !explicit ? '<span class="em-current-tag" title="No source has '+
          'been explicitly chosen for this channel, so this is the first saved source '+
          'that matches it \u2014 the same rule the export and the captured guide use. '+
          '\u2018Use this\u2019 on any row makes the choice explicit.">default</span>' : '')+
        (manualPin ? '<span class="em-current-tag" title="Pinned to this exact guide '+
          'entry via search, rather than resolved automatically \u2014 use a plain '+
          '\u2018Use this\u2019 above, or pick another search result, to change it.">'+
          'manual</span>' : '')+
        (s.guide_name ? '<div class="em-guidechan" title="The actual guide entry this '+
          'source matched this channel to \u2014 a fuzzy or ambiguous match can land on '+
          'the wrong one while still showing a plausible programme, so the entry itself '+
          'is worth checking, not just what it says is on.">as \u201c'+esc(s.guide_name)+
          '\u201d</div>' : '')+
      '</div>'+
      '<div class="prog">'+prog+'</div>'+
      '<button data-use="'+esc(s.source)+'" '+(!s.matched?'disabled':'')+'>'+
        badge+'</button>'+
      '</div>';
  }).join("");

  const srcSel = document.getElementById("em-search-src");
  srcSel.innerHTML = data.sources.map(s =>
    '<option value="'+esc(s.source)+'">'+esc(s.source)+'</option>').join("");
  document.getElementById("em-search-q").value = "";
  document.getElementById("em-search-results").innerHTML = "";

  epgSourcesCache = data.sources;
  renderLogoSection(ch, data.sources);
}

// --- Logo picker ---------------------------------------------------------
// Lives inside the EPG modal on purpose (the user's own framing for this:
// "the EPG menu allows us to choose a channel exactly like we do, then it
// offers us the default logo, the logo from the other EPG matches it's
// found, or to search all logos") -- a channel's logo and its guide match
// are already the same decision-making moment, not two separate ones.
//
// Every option rendered here is a link to someone else's hosting -- the
// provider's own tvg-logo, a saved EPG source's <icon>, or a
// raw.githubusercontent.com URL from tv-logo/tv-logos (CC BY-SA 4.0).
// probarr never fetches or stores the image bytes itself; see logos.py's
// module docstring for why that distinction is the whole point.
let LOGO_COUNTRIES = null;
async function ensureLogoCountries(){
  // Length-checked, not just truthiness: [] is truthy in JavaScript, so a
  // plain `if(LOGO_COUNTRIES)` treated an empty result as a successful
  // load and never asked again for the rest of the session -- locking the
  // picker into a blank country list after a single failed request.
  if(LOGO_COUNTRIES && LOGO_COUNTRIES.length) return LOGO_COUNTRIES;
  try{
    const d = await (await fetch("/run/"+encodeURIComponent(DATA.run_id)+
      "/logo-countries", {cache:"no-store"})).json();
    LOGO_COUNTRIES = d.countries || [];
  }catch(e){ LOGO_COUNTRIES = []; }
  return LOGO_COUNTRIES;
}
function logoOptHTML(url, label, picked){
  return '<div class="em-logo-opt'+(picked?' picked':'')+'" data-logo-url="'+esc(url)+'" '+
    'title="'+esc(label)+'"><img src="'+esc(url)+'" alt="" loading="lazy">'+
    '<div class="lbl">'+esc(label)+'</div></div>';
}
async function renderLogoSection(ch, epgSources){
  const sel = SEL[current] || {};
  const override = sel.logo_override || "";
  const m3uLogo = (ch.candidates||[]).map(c=>c.logo).find(Boolean) || "";
  const curEl = document.getElementById("em-logo-current");
  const activeUrl = override || m3uLogo ||
    (epgSources.find(s=>s.logo) || {}).logo || "";
  curEl.innerHTML = activeUrl
    ? '<img src="'+esc(activeUrl)+'" alt="">'+
      '<span>'+(override ? 'Using the picked logo below.'
        : m3uLogo ? 'Using the provider’s own logo (no pick made yet).'
        : 'Using a matched EPG source’s icon (no pick made yet).')+'</span>'
    : '<span class="none">No logo available for this channel yet.</span>';

  const seen = new Set();
  const opts = [];
  if(m3uLogo && !seen.has(m3uLogo)){
    seen.add(m3uLogo);
    opts.push(logoOptHTML(m3uLogo, "Provider default", m3uLogo===override ||
      (!override && m3uLogo===activeUrl)));
  }
  for(const s of epgSources){
    if(s.logo && !seen.has(s.logo)){
      seen.add(s.logo);
      opts.push(logoOptHTML(s.logo, s.source, s.logo===override ||
        (!override && s.logo===activeUrl)));
    }
  }
  if(override && !seen.has(override)){
    opts.push(logoOptHTML(override, "Picked", true));
  }
  document.getElementById("em-logo-choices").innerHTML = opts.join("") ||
    '<div class="sub">No default or EPG-source logo found for this channel.</div>';

  const countrySel = document.getElementById("em-logo-country");
  if(!countrySel.dataset.loaded){
    const countries = await ensureLogoCountries();
    countrySel.innerHTML = countries.length
      ? countries.map(c =>
          '<option value="'+esc(c)+'"'+(c==="united-kingdom"?" selected":"")+'>'+
          esc(c)+'</option>').join("")
      : '<option value="">could not load \u2014 reopen to retry</option>';
    // Only latched on success, so a failed load is retried next time the
    // modal opens instead of leaving a permanently empty dropdown.
    if(countries.length) countrySel.dataset.loaded = "1";
  }
  document.getElementById("em-logo-q").value = "";
  document.getElementById("em-logo-results").innerHTML = "";
}
function pickLogo(url){
  SEL[current] = {...(SEL[current]||{}), logo_override: url};
  save();
  const ch = DATA.channels.find(c=>c.key===current);
  renderLogoSection(ch, epgSourcesCache || []);
  renderDetail();
  renderList();   // the sidebar's own logo thumbnail needs the same pick
}
let epgSourcesCache = null;
document.getElementById("em-logo-choices").addEventListener("click", (e) => {
  const opt = e.target.closest(".em-logo-opt"); if(!opt) return;
  pickLogo(opt.dataset.logoUrl);
});
document.getElementById("em-logo-results").addEventListener("click", (e) => {
  const opt = e.target.closest(".em-logo-opt"); if(!opt) return;
  pickLogo(opt.dataset.logoUrl);
});
let logoSearchTimer = null;
function runLogoSearch(){
  clearTimeout(logoSearchTimer);
  logoSearchTimer = setTimeout(async () => {
    const country = document.getElementById("em-logo-country").value;
    const q = document.getElementById("em-logo-q").value.trim();
    const box = document.getElementById("em-logo-results");
    if(!country || q.length < 2){ box.innerHTML = ""; return; }
    box.innerHTML = '<div class="sub">searching…</div>';
    let data;
    try{
      data = await (await fetch("/run/"+encodeURIComponent(DATA.run_id)+
        "/logo-search?country="+encodeURIComponent(country)+
        "&q="+encodeURIComponent(q), {cache:"no-store"})).json();
    }catch(e){
      box.innerHTML = '<div class="sub">search failed</div>';
      return;
    }
    const results = data.results || [];
    if(!results.length){
      box.innerHTML = '<div class="sub">no logos in "'+esc(country)+
        '" match "'+esc(q)+'"</div>';
      return;
    }
    box.innerHTML = results.map(r => logoOptHTML(r.url, r.filename, false)).join("");
  }, 300);
}
document.getElementById("em-logo-q").addEventListener("input", runLogoSearch);
document.getElementById("em-logo-country").addEventListener("change", runLogoSearch);

// --- EPG manual search --------------------------------------------------
// The algorithm already tries tvg-id then name matching; this is the
// fallback for when that guessed wrong or found nothing, because the
// channel is filed under a name nobody would think to try automatically.
// A person filtering a short real list beats trusting a fuzzy match.
let epgSearchTimer = null;
function runEpgSearch(){
  clearTimeout(epgSearchTimer);
  epgSearchTimer = setTimeout(async () => {
    const src = document.getElementById("em-search-src").value;
    const q = document.getElementById("em-search-q").value.trim();
    const box = document.getElementById("em-search-results");
    if(!src || q.length < 2){ box.innerHTML = ""; return; }
    box.innerHTML = '<div class="muted" style="padding:4px">searching…</div>';
    let data;
    try{
      data = await (await fetch("/run/"+encodeURIComponent(DATA.run_id)+
        "/epg-search?source="+encodeURIComponent(src)+"&q="+encodeURIComponent(q),
        {cache:"no-store"})).json();
    }catch(e){
      box.innerHTML = '<div class="muted" style="padding:4px">search failed</div>';
      return;
    }
    if(data.error){
      box.innerHTML = '<div class="muted" style="padding:4px">'+esc(data.error)+'</div>';
      return;
    }
    if(!data.hits.length){
      box.innerHTML = '<div class="muted" style="padding:4px">no channels in "'+
        esc(src)+'" match "'+esc(q)+'"</div>';
      return;
    }
    box.innerHTML = data.hits.map(h => {
      const prog = h.now
        ? esc(h.now.title)+(h.now.window?' ('+esc(h.now.window)+')':'')
        : '<span class="nomatch">nothing scheduled right now</span>';
      return '<div class="cat-hit" data-gid="'+esc(h.guide_id)+'" data-src="'+esc(src)+'">'+
        '<span class="k">'+esc(h.guide_name)+'</span>'+
        '<span class="n">'+prog+'</span>'+
        '<button data-pickguide="'+esc(h.guide_id)+'" data-pickfrom="'+esc(src)+'">'+
          'Use this</button></div>';
    }).join("");
  }, 300);
}
document.getElementById("em-search-q").addEventListener("input", runEpgSearch);
document.getElementById("em-search-src").addEventListener("change", runEpgSearch);
document.getElementById("em-search-results").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-pickguide]"); if(!btn) return;
  SEL[current] = {...(SEL[current]||{}), epg_source: btn.dataset.pickfrom,
                  epg_channel_source: btn.dataset.pickfrom,
                  epg_channel_id: btn.dataset.pickguide};
  save();
  openEpgModal();   // re-render with the manual pick now "In use"
  renderDetail();
  renderList();     // the epg_mismatch flag this may clear affects the dot/filter
});
document.getElementById("em-close").addEventListener("click", () => {
  document.getElementById("epgmodal").classList.remove("on");
});
document.getElementById("em-x").addEventListener("click", () => {
  document.getElementById("epgmodal").classList.remove("on");
});

// --- Mark watermark area -------------------------------------------------
// v1 is deliberately NOT automatic matching: no scoring, no threshold, no
// false positives/negatives to tune. A human draws the box once against a
// known-good picture; from then on every candidate just shows that same
// area cropped out of its own frame, right next to its screenshot, and a
// wrong feed is something a person notices by looking, the same way they'd
// notice anything else on the card. The box is stored as FRACTIONS of the
// reference image's width/height (not pixels) -- candidates are rarely all
// the same resolution, and a fraction survives that; an absolute pixel box
// would need translating per-candidate anyway, so the fraction is what
// gets stored and what the server's crop (web.py's _watermark_crop) works
// in directly via ffmpeg's iw/ih expressions.
let WM_DRAG = null;   // {x0,y0} in DISPLAYED (CSS) pixels, while dragging
let WM_BOX = null;    // {x,y,w,h} fractions, once a drag has completed
function openWatermarkModal(){
  const ch = DATA.channels.find(c=>c.key===current); if(!ch) return;
  document.getElementById("wm-title").textContent = ch.title;
  const img = document.getElementById("wm-img");
  const nopic = document.getElementById("wm-nopic");
  const wrap = document.getElementById("wm-imgwrap");
  const boxEl = document.getElementById("wm-box");
  const saveBtn = document.getElementById("wm-save");
  const pickerField = document.getElementById("wm-picker-field");
  const picker = document.getElementById("wm-picker");
  document.getElementById("wm-result").className = "mresult";
  boxEl.style.display = "none";
  saveBtn.disabled = true;
  WM_DRAG = null; WM_BOX = null;
  // Every candidate WITH a captured frame is a valid reference picture, not
  // just the best-ranked one -- the real case this is for: the top
  // candidate happened to be probed at a moment the watermark had faded
  // off (some channels do that periodically), and the picture needed to
  // draw the box on is a genuinely different candidate's, not "whichever
  // one probarr already assumed."
  const withFrames = (ch.candidates||[]).filter(c => c.frame);
  if(!withFrames.length){
    img.removeAttribute("src"); wrap.style.display = "none";
    pickerField.style.display = "none";
    nopic.style.display = "block";
  }else{
    wrap.style.display = "inline-block"; nopic.style.display = "none";
    picker.innerHTML = withFrames.map((c,i) =>
      '<option value="'+esc(c.id)+'">'+esc(c.name)+
      ' (#'+c.rank+' ranked)'+(i===0?' — default':'')+'</option>').join("");
    pickerField.style.display = withFrames.length > 1 ? "block" : "none";
    picker.value = withFrames[0].id;
    img.src = withFrames[0].frame;
  }
  document.getElementById("watermarkmodal").classList.add("on");
}
document.getElementById("wm-picker").addEventListener("change", (e) => {
  const ch = DATA.channels.find(c=>c.key===current); if(!ch) return;
  const c = (ch.candidates||[]).find(x=>x.id===e.target.value); if(!c) return;
  document.getElementById("wm-img").src = c.frame;
  // A new reference picture invalidates any in-progress (unsaved) drag --
  // its fraction was computed against the PREVIOUS image's displayed size
  // and would not mean the same thing here.
  document.getElementById("wm-box").style.display = "none";
  document.getElementById("wm-save").disabled = true;
  WM_DRAG = null; WM_BOX = null;
});
function wmImgRect(){
  const img = document.getElementById("wm-img");
  const r = img.getBoundingClientRect();
  return {left:r.left, top:r.top, w:r.width, h:r.height};
}
function wmClamp(v, lo, hi){ return Math.max(lo, Math.min(hi, v)); }
document.getElementById("wm-imgwrap").addEventListener("mousedown", (e) => {
  const img = document.getElementById("wm-img");
  if(!img.src) return;
  const r = wmImgRect();
  WM_DRAG = {x0: wmClamp(e.clientX - r.left, 0, r.w),
            y0: wmClamp(e.clientY - r.top, 0, r.h)};
  e.preventDefault();
});
document.addEventListener("mousemove", (e) => {
  if(!WM_DRAG) return;
  const r = wmImgRect();
  const x1 = wmClamp(e.clientX - r.left, 0, r.w);
  const y1 = wmClamp(e.clientY - r.top, 0, r.h);
  const x = Math.min(WM_DRAG.x0, x1), y = Math.min(WM_DRAG.y0, y1);
  const w = Math.abs(x1 - WM_DRAG.x0), h = Math.abs(y1 - WM_DRAG.y0);
  const boxEl = document.getElementById("wm-box");
  boxEl.style.display = "block";
  boxEl.style.left = x+"px"; boxEl.style.top = y+"px";
  boxEl.style.width = w+"px"; boxEl.style.height = h+"px";
});
document.addEventListener("mouseup", () => {
  if(!WM_DRAG) return;
  const boxEl = document.getElementById("wm-box");
  const r = wmImgRect();
  const img = document.getElementById("wm-img");
  // Displayed (CSS) pixels -> fractions of the image's NATURAL size. The
  // image is very likely displayed smaller than its captured resolution
  // (max-width:100% in a modal), so this is not a no-op conversion.
  const left = parseFloat(boxEl.style.left)||0, top = parseFloat(boxEl.style.top)||0;
  const w = parseFloat(boxEl.style.width)||0, h = parseFloat(boxEl.style.height)||0;
  WM_DRAG = null;
  const MIN_PX = 8;   // smaller than this is almost certainly a stray click
  if(w < MIN_PX || h < MIN_PX || !img.naturalWidth) { boxEl.style.display = "none"; return; }
  WM_BOX = {
    x: left / r.w, y: top / r.h,
    w: w / r.w, h: h / r.h,
  };
  document.getElementById("wm-save").disabled = false;
});
document.getElementById("wm-save").addEventListener("click", async () => {
  if(!WM_BOX) return;
  const s = SEL[current] = SEL[current] || {};
  s.watermark_box = WM_BOX;
  document.getElementById("watermarkmodal").classList.remove("on");
  // Wait for the box to actually be written server-side before rendering
  // the candidate cards that will immediately request crops OF it -- see
  // save()'s own comment for the real race this closes.
  await save();
  renderList(); renderDetail();
});
function closeWatermarkModal(){
  document.getElementById("watermarkmodal").classList.remove("on");
}
document.getElementById("wm-close").addEventListener("click", closeWatermarkModal);
document.getElementById("wm-x").addEventListener("click", closeWatermarkModal);
document.getElementById("em-sources").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-use]"); if(!btn) return;
  const src = btn.dataset.use;
  // Picking a source here means "trust its own automatic match" -- distinct
  // from Use this in the search results below, which pins one exact guide
  // channel. Clears any earlier manual pin so this genuinely goes back to
  // resolve() rather than silently keeping the old pin in effect.
  const s = {...(SEL[current]||{}), epg_source: src};
  delete s.epg_channel_source; delete s.epg_channel_id;
  SEL[current] = s;
  save();
  openEpgModal();   // re-render with the new "In use" state
  renderDetail();   // reflect the new tag next to "Guide said"
});

// Re-scan every candidate for the current channel in diagnose mode: a
// longer sample, plus a kept video clip instead of a discarded one. Polls
// the same queue the single-candidate re-probe button uses, but waits on
// ALL of this channel's candidates rather than one, so switching to a
// different stream (if one turns out to be genuinely better) is something
// the operator can see rather than guess at.
async function diagnoseChannel(){
  const key = current;
  // Looked up FRESH every time, not captured once -- any other action that
  // re-renders the detail panel while this is running (confirming "This is
  // fine", switching a stream, anything that calls renderDetail()) replaces
  // these nodes wholesale. A captured reference silently keeps writing to
  // the orphaned old node from then on: the polling itself never stops, it
  // just becomes invisible, which is exactly what looked like a frozen
  // diagnose after settling the channel it was running on.
  // Also gated on `current === key`: #diagnosebtn/#diagnosemsg are reused
  // ids, one per channel shown at a time -- if the operator has switched to
  // a DIFFERENT channel while this one's diagnose is still running, those
  // ids now belong to that other channel's panel, and writing to them would
  // put this channel's progress text on the wrong channel instead of just
  // losing it.
  const btn = () => current === key ? document.getElementById("diagnosebtn") : null;
  const msg = () => current === key ? document.getElementById("diagnosemsg") : null;
  const setMsg = t => { const m = msg(); if(m) m.textContent = t; };
  const setBtnDisabled = v => { const b = btn(); if(b) b.disabled = v; };
  setBtnDisabled(true); setMsg("queuing\u2026");
  let queued, queuedEta = 0, skippedCount = 0;
  try{
    const r = await fetch("/api/run/"+encodeURIComponent(DATA.run_id)+"/diagnose",
      {method:"POST", headers:{"Content-Type":"application/json"},
       body: JSON.stringify({channel_key: key})});
    const d = await r.json();
    if(!d.ok){ setMsg("error: "+(d.error||"failed")); setBtnDisabled(false); return; }
    queued = d.queued;
    queuedEta = d.eta_seconds || 0;
    skippedCount = (d.skipped || []).length;
    if(!queued.length){
      setMsg("nothing to diagnose \u2014 every candidate is dead. "+
        "Re-probe one individually with \u21bb, or find better streams.");
      setBtnDisabled(false); return;
    }
  }catch(e){ setMsg("request failed"); setBtnDisabled(false); return; }

  // Each candidate reports on its OWN card, using the same indicator a
  // single re-probe uses. A lone counter in the header could not say which
  // stream was being scanned, which is the thing you are watching for when
  // one of nine is misbehaving.
  queued.forEach(q => {
    const b = document.querySelector('.cand[data-id="'+CSS.escape(q.rec_key)+
                                     '"] button[data-act="reprobe"]');
    if(b){ b.disabled = true; b.textContent = "\u2026"; }
  });

  const pending = new Set(queued.map(q => DATA.run_id+"|"+q.rec_key));
  const started = Date.now();
  let tries = 0;
  const eta = queuedEta;
  const tick = async () => {
    tries++;
    let snap;
    try{ snap = await (await fetch("/api/queue", {cache:"no-store"})).json(); }
    catch(e){ setMsg("lost track of progress"); setBtnDisabled(false); return; }
    const landedKeys = [];
    for(const k of [...pending]) if(!(snap.keys && snap.keys[k])){
      pending.delete(k); landedKeys.push(k.slice((DATA.run_id+"|").length));
    }
    // Pull each candidate's fresh picture and status in AS IT LANDS, not
    // only once every candidate is done. The old code only ever called
    // refreshChannel() after the whole batch finished, so a five-minute
    // scan of nine candidates showed nothing changing on screen until the
    // very end -- indistinguishable from having frozen. This must happen
    // BEFORE the button/highlight pass below, since it rebuilds the whole
    // detail panel (renderDetail()) and would otherwise wipe out whatever
    // that pass had just set.
    if(landedKeys.length && current === key) await refreshChannel(current);
    if(current !== key) return;   // operator switched channels mid-scan
    document.querySelectorAll(".cand.probing").forEach(r=>r.classList.remove("probing"));
    queued.forEach(q => {
      const st = snap.keys && snap.keys[DATA.run_id+"|"+q.rec_key];
      const row = document.querySelector('.cand[data-id="'+CSS.escape(q.rec_key)+'"]');
      const b = row && row.querySelector('button[data-act="reprobe"]');
      if(st){
        if(b) b.textContent = st.state === "running" ? "\u2026"
                                                      : "#"+(st.position||"?");
        // The highlight IS the answer to "which one am I watching" -- a
        // counter or a per-row "queued #3" label doesn't say which
        // candidate has the provider's one connection right now, and that
        // is exactly what you want to see moving during a multi-candidate
        // scan.
        if(row && st.state === "running") row.classList.add("probing");
      } else if(b) { b.textContent = "\u21bb"; b.disabled = false; }
    });
    landedKeys.forEach(recKey => {
      const row = document.querySelector('.cand[data-id="'+CSS.escape(recKey)+'"]');
      if(row){
        row.classList.add("just-scanned");
        setTimeout(()=>row.classList.remove("just-scanned"), 1500);
      }
    });
    if(snap.blocked && pending.size){
      setMsg(snap.blocked);
      return setTimeout(tick, 3000);
    }
    if(pending.size && tries < 900){
      const left = Math.max(0, Math.round(eta - (Date.now()-started)/1000));
      setMsg((queued.length-pending.size)+" of "+queued.length+
        " scanned \u00b7 about "+fmtLeft(left)+" left"+
        (skippedCount ? " ("+skippedCount+" dead skipped)" : ""));
      return setTimeout(tick, 1200);
    }
    setMsg("done \u2014 "+queued.length+" scanned");
    setBtnDisabled(false);
    setTimeout(()=>{ const m = msg(); if(m && m.textContent.startsWith("done")) m.textContent=""; }, 5000);
  };
  setTimeout(tick, 800);
}
function fmtLeft(sec){
  if(sec < 60) return sec+"s";
  const m = Math.floor(sec/60);
  return m+"m"+(sec%60 ? " "+(sec%60)+"s" : "");
}

// Re-fetch one channel and swap it into DATA, then re-render.
//
// Deliberately NOT location.reload(). A reload depended on sessionStorage to
// remember which channel was open -- and sessionStorage throws outright in
// Safari's private browsing, which aborted the handler before the reload ever
// fired, so the capture succeeded and the picture never changed. Updating in
// place also keeps scroll position and the current selection.
// Confirming already existed but died with the run. A judgement that a
// channel is fine is about the CHANNEL, so it belongs on the lineup beside
// the group and the name -- otherwise the next run asks the same question
// about the same channel with no memory of having been answered.
async function settleChannel(){
  // Bulk-aware like Set group and Exclude/Re-include: applies to every
  // marked channel, not just the open one. Unlike those two, each channel
  // needs its OWN evidence signature -- "settled" is only meaningful
  // relative to the specific evidence it was settled on, which differs
  // per channel, so this can't just copy one decision onto the rest.
  const keys = MARKED.size > 1 ? [...MARKED] : [current];
  for(const k of keys){
    const ch = DATA.channels.find(c=>c.key===k); if(!ch) continue;
    const s = SEL[k] = SEL[k] || {};
    s.confirmed = true;
    // Recorded WITH the evidence it was settled on, so a later change can
    // tell "still fine" from "fine when I looked, different now".
    s.settled_on = evidenceSig(ch);
  }
  save();
  renderList(); renderDetail();
}

async function refreshChannel(key){
  if(!key) return;
  try{
    const r = await fetch("/run/"+encodeURIComponent(DATA.run_id)+
                          "/channel?key="+encodeURIComponent(key),
                          {cache:"no-store"});
    if(!r.ok) return;
    const fresh = await r.json();
    const i = DATA.channels.findIndex(c=>c.key===key);
    if(i>=0) DATA.channels[i]=fresh; else DATA.channels.push(fresh);
    renderList(); renderDetail();
  }catch(e){ /* leave the old card rather than blanking it */ }
}

// -- the channel's streams, as an ordered list -------------------------
//
// What you see IS what gets pushed, in that order. Dispatcharr stores a
// channel as an ordered streams array and fails over down it, so the old
// primary/fallback pair was a limit probarr imposed on itself: a third
// good stream had nowhere to go, and deciding which of two was "the
// fallback" was a different question from "what order should these be
// tried in".
function chosenIds(ch){
  const s = SEL[ch.key] || {};
  if(Array.isArray(s.streams)) return s.streams.filter(
    id => (ch.candidates||[]).some(c => c.id === id));
  // Runs curated before the list existed carry a primary and a fallback;
  // read them as a two-item list rather than migrating anything on disk,
  // so nothing is rewritten until the operator actually changes something.
  const out = [];
  if(s.primary) out.push(s.primary);
  if(s.fallback && s.fallback !== s.primary) out.push(s.fallback);
  if(out.length) return out;
  const auto = (ch.candidates||[]).find(c => c.status==="ok" || c.status==="dirty");
  return auto ? [auto.id] : [];
}
// Chosen streams in their chosen order, then everything else by rank --
// so the list reads top to bottom as "what this channel is, then what
// else was available".
function orderedCands(ch){
  const ids = chosenIds(ch);
  const cs = ch.candidates || [];
  return ids.map(id => cs.find(c=>c.id===id)).filter(Boolean)
    .concat(cs.filter(c => ids.indexOf(c.id) < 0));
}
function setStreams(ids){
  const s = SEL[current] = SEL[current] || {};
  s.streams = ids;
  // Kept in step so the M3U export, the push and every older reader agree
  // with the list rather than with a stale pair beside it.
  s.primary = ids[0] || null;
  s.fallback = ids[1] || null;
  if(ids.length) s.include = true;
  save(); renderList(); renderDetail();
}
function toggleUse(id){
  const ch = DATA.channels.find(c=>c.key===current); if(!ch) return;
  const ids = chosenIds(ch).slice();
  const at = ids.indexOf(id);
  if(at >= 0) ids.splice(at, 1); else ids.push(id);
  setStreams(ids);
}
// Kept for the keyboard shortcut only: pressing 1-9 makes that candidate
// first, same result as dragging it there, just faster. There is no
// standalone "Make first" button any more -- position is set by drag order,
// this is just another way of setting it.
function setPick(what,id){
  const ch = DATA.channels.find(c=>c.key===current); if(!ch) return;
  if(what==="primary"){
    const ids = chosenIds(ch).filter(x=>x!==id);
    setStreams([id].concat(ids));
  } else {
    toggleUse(id);
  }
}
document.getElementById("detail").addEventListener("click", e => {
  if(e.target.id === "titletext" || e.target.id === "titleedit") startRename();
  if(e.target.closest("#numtext") || e.target.id === "numedit") startRenumber();
  const ct = e.target.closest("[data-chtoggle]");
  if(ct){
    const box = document.getElementById(ct.dataset.chtoggle);
    if(box) box.style.display = box.style.display === "none" ? "block" : "none";
  }
});
// Click the dark backdrop (not the box itself) to close whichever modal is
// open -- one handler for every modal in the app, not just Groups.
document.querySelectorAll(".modal").forEach(m =>
  m.addEventListener("click", e => { if(e.target === m) m.classList.remove("on"); }));
document.getElementById("q").addEventListener("input", ()=>renderList());
document.addEventListener("keydown", e=>{
  if(e.target.tagName==="INPUT") { if(e.key==="Escape") e.target.blur(); return; }
  const lb=document.getElementById("lb2");
  const cv=document.getElementById("clipviewer");
  if(e.key==="Escape"){ lb.classList.remove("on"); closeClip(); return; }
  if(lb.classList.contains("on")){
    if(e.key==="c"||e.key===" "){ e.preventDefault(); lbFull=!lbFull; paintLB(); }
    return;
  }
  if(cv.classList.contains("on")) return;
  // Real bug found on a full-codebase review: this handler only ever
  // checked the lightbox and clip viewer, not any of the other modals
  // (Check EPG, watermark, groups, import, catalog, find-streams). Pressing
  // j/k or an arrow while one of those was open still called advance(),
  // silently changing `current` to a different channel while the modal
  // stayed open showing the OLD channel's data -- so a click inside it
  // (e.g. "Use this" on an EPG source, or saving a watermark box) applied
  // to whatever channel the hotkey had quietly moved to, not the one still
  // visible on screen. One check for "any modal is open" instead of naming
  // each one, matching the equally generic backdrop-click-to-close handler
  // just above -- so a modal added later is covered automatically too.
  if(document.querySelector(".modal.on")) return;
  if(e.key==="ArrowDown"||e.key==="j"){ e.preventDefault(); advance(1); }
  else if(e.key==="ArrowUp"||e.key==="k"){ e.preventDefault(); advance(-1); }
  else if(e.key>="1"&&e.key<="9"){
    const ch=DATA.channels.find(c=>c.key===current); if(!ch) return;
    const c=(ch.candidates||[])[parseInt(e.key,10)-1]; if(c) setPick("primary",c.id);
  }
  else if(e.key==="f"){
    const ch=DATA.channels.find(c=>c.key===current); if(!ch) return;
    const ids=chosenIds(ch);
    const next=(ch.candidates||[]).find(c=>ids.indexOf(c.id)<0);
    if(next) toggleUse(next.id);
  }
  else if(e.key==="x"){
    const s=SEL[current]=SEL[current]||{}; s.include=(s.include===false);
    save(); renderList(); renderDetail();
  }
  else if(e.key==="Enter"){
    const s=SEL[current]=SEL[current]||{}; s.confirmed=true;
    save(); renderList(); advance(1);
  }
});

if(filter==="triage" && !DATA.channels.some(needsHuman)) filter="all";
{
  const saved = loadViewState();
  if(saved.f && FILTERS.some(([k])=>k===saved.f)) filter = saved.f;
}
renderList();
// A saved channel wins outright if it is still in view under this filter;
// otherwise fall back to the first channel in the CURRENT view -- landing
// on triage (or wherever was saved) should put you on something that
// actually needs you, not just alphabetically first.
{
  const saved = loadViewState();
  const list = visible();
  const wanted = saved.ch && list.find(c=>c.key===saved.ch);
  const _first = wanted || list[0] || DATA.channels[0];
  if(_first) select(_first.key);
}
checkPending();

// --- Diagnose filtered ---------------------------------------------------
// Same idea as the nightly re-verify, but on demand and on a chosen subset:
// take whatever the current filter/search is showing, let the operator drop
// anything they don't actually want touched, then queue the rest through
// the same diagnose path the per-channel button uses.
const DIAG_SECONDS_PER_CANDIDATE = 31; // 25s sample + 6s overhead, matches the server
let DIAGSEL = new Set();
function diagCandidateCount(ch, includeDead){
  const cs = ch.candidates||[];
  return includeDead ? cs.length : cs.filter(c=>c.status!=="dead").length;
}
function renderDiagList(){
  const includeDead = document.getElementById("diag-include-dead").checked;
  const list = [...DIAGSEL].map(k=>DATA.channels.find(c=>c.key===k)).filter(Boolean);
  document.getElementById("diag-list").innerHTML = list.map(ch=>{
    const n = diagCandidateCount(ch, includeDead);
    return '<label class="cat-hit" style="cursor:pointer">'+
      '<input type="checkbox" class="diag-pick" data-k="'+esc(ch.key)+'" checked>'+
      '<span style="flex:1">'+esc(ch.title)+'</span>'+
      '<span class="muted">'+n+' candidate'+(n===1?"":"s")+'</span></label>';
  }).join("") || '<div class="empty">Nothing to diagnose.</div>';
  updateDiagSummary();
}
function updateDiagSummary(){
  const includeDead = document.getElementById("diag-include-dead").checked;
  const picked = [...document.querySelectorAll(".diag-pick:checked")].map(x=>x.dataset.k);
  const total = picked.reduce((sum,k)=>{
    const ch = DATA.channels.find(c=>c.key===k);
    return sum + (ch ? diagCandidateCount(ch, includeDead) : 0);
  }, 0);
  // This used to always say "serial, one at a time" and divide by 1
  // regardless -- wrong for a provider saved with its own concurrency
  // above 1 (the actual probe queue already respects that, per-provider,
  // via its lane limit). DATA.meta.concurrency is what THIS run was
  // started with, the best estimate of the provider's real limit
  // available here without a fresh lookup -- not perfectly live if the
  // provider's setting changed since, but far closer than a hardcoded 1.
  const conc = Math.max(1, DATA.meta.concurrency || 1);
  const secs = (total * DIAG_SECONDS_PER_CANDIDATE) / conc;
  const eta = secs < 90 ? Math.round(secs)+"s"
            : secs < 3600 ? Math.round(secs/60)+" min"
            : (secs/3600).toFixed(1)+" hr";
  document.getElementById("diag-summary").textContent =
    picked.length ? picked.length+" channel"+(picked.length===1?"":"s")+
      ", "+total+" probe"+(total===1?"":"s")+" — about "+eta+
      (conc>1 ? " (up to "+conc+" at once)" : " (serial, one at a time)")
      : "nothing selected";
  document.getElementById("diag-go").disabled = !picked.length;
}
document.getElementById("diagfiltered").addEventListener("click", () => {
  DIAGSEL = new Set(visible().map(c=>c.key));
  document.getElementById("diag-include-dead").checked = false;
  document.getElementById("diag-result").className = "mresult";
  document.getElementById("diag-result").textContent = "";
  renderDiagList();
  document.getElementById("diagmodal").classList.add("on");
});
document.getElementById("diag-x").addEventListener("click", () =>
  document.getElementById("diagmodal").classList.remove("on"));
document.getElementById("diag-cancel").addEventListener("click", () =>
  document.getElementById("diagmodal").classList.remove("on"));
document.getElementById("diag-include-dead").addEventListener("change", renderDiagList);
document.getElementById("diag-list").addEventListener("change", e => {
  if(e.target.classList.contains("diag-pick")) updateDiagSummary();
});
document.getElementById("diag-go").addEventListener("click", async () => {
  const includeDead = document.getElementById("diag-include-dead").checked;
  const picked = [...document.querySelectorAll(".diag-pick:checked")].map(x=>x.dataset.k);
  if(!picked.length) return;
  const btn = document.getElementById("diag-go");
  const result = document.getElementById("diag-result");
  btn.disabled = true; btn.textContent = "Queuing…";
  try{
    const r = await fetch("/api/run/"+encodeURIComponent(DATA.run_id)+"/diagnose-batch",
      {method:"POST", headers:{"Content-Type":"application/json"},
       body: JSON.stringify({channel_keys: picked, include_dead: includeDead})});
    const d = await r.json();
    if(!r.ok || d.error){
      result.className = "mresult show bad";
      result.textContent = d.error || "failed to queue";
    } else {
      const mins = Math.round(d.eta_seconds/60);
      result.className = "mresult show good";
      result.textContent = "Queued "+d.queued+" probe"+(d.queued===1?"":"s")+
        " across "+d.channels+" channel"+(d.channels===1?"":"s")+
        (d.skipped ? " ("+d.skipped+" dead candidate"+(d.skipped===1?"":"s")+" skipped)" : "")+
        " — roughly "+(mins<1?"under a minute":mins+" min")+
        ". Watch progress on each channel as usual.";
    }
  } catch(err){
    result.className = "mresult show bad";
    result.textContent = "request failed: "+err;
  }
  btn.disabled = false; btn.textContent = "Start";
});

// --- Dispatcharr export ------------------------------------------------
let pushChannelKey = null;   // null = push everything; a key = one channel only
async function openDispatchModal(channelKey){
  pushChannelKey = channelKey || null;
  const modal = document.getElementById("dispatchmodal");
  const sel = document.getElementById("dm-provider");
  const noprov = document.getElementById("dm-noprov");
  const body = document.getElementById("dm-body");
  if(pushChannelKey){
    const ch = DATA.channels.find(c=>c.key===pushChannelKey);
    document.getElementById("dm-title").textContent =
      "Push \u201c"+(ch?ch.title:pushChannelKey)+"\u201d to Dispatcharr";
    document.getElementById("dm-sub").textContent =
      "Pushes just this one channel \u2014 its current stream picks and EPG "+
      "choice \u2014 into the same group as a full export, without touching "+
      "any other channel.";
  } else {
    document.getElementById("dm-title").textContent = "Export to Dispatcharr";
    document.getElementById("dm-sub").textContent =
      "Pushes your curated picks into an existing Dispatcharr instance \u2014 "+
      "creates or updates channels, sets streams, links logos, re-matches EPG.";
  }
  document.getElementById("dm-result").className = "mresult";
  document.getElementById("dm-plan").className = "dm-plan";
  pushStarted = false;
  const _push = document.getElementById("dm-push");
  _push.disabled = true; _push.textContent = "Push"; delete _push.dataset.done;
  document.getElementById("dm-preview").disabled = true;
  unresolvedConflicts = 0;
  // Restored, not cleared. Clearing meant the dialog opened with Push
  // disabled and demanded the same three answers every single time -- and
  // the answer never changes: it is a property of this probarr and its
  // Dispatcharr, not a decision to be re-made per push.
  const cfg = await (await fetch("/api/settings", {cache:"no-store"})).json();
  const wantFb = cfg.push_fallback || "native";
  document.querySelectorAll('input[name="fbmode"]').forEach(r => {
    r.checked = (r.value === wantFb);
    r.closest(".fbopt").classList.toggle("checked", r.checked);
  });
  document.getElementById("dm-prune").checked = cfg.push_prune !== false;
  document.getElementById("dm-options").style.display = "none";
  document.getElementById("dm-more").textContent = "change";

  const d = await (await fetch("/api/providers")).json();
  const dispatchers = d.providers.filter(p => p.scheme === "dispatcharr");
  const groupEl = document.getElementById("dm-group");
  // Pre-fill with whatever group a push into the SELECTED PROVIDER last
  // actually used -- attached to the provider, not this run, because a
  // later push from a DIFFERENT probarr run of what the operator considers
  // the same conceptual lineup ("re-verify my channels") still needs to
  // land in the same place. Leaving this blank (the common case, especially
  // for a single-channel push) otherwise silently defaults to a brand new
  // group. Confirmed live, twice: once within a run's own later push,
  // and again across two different runs pushing into the same provider.
  function fillGroupFor(providerName){
    // Deliberately NOT pre-filled with real text: leaving this blank is
    // the CORRECT choice for an update (an existing channel keeps its
    // current group untouched; only a brand-new channel uses this as a
    // fallback) -- pre-filling it with the remembered name would make
    // "leave it blank" look like an omission instead of the actual
    // intended default. Shown only as a placeholder, so it is visible
    // without looking mandatory to retype.
    const p = dispatchers.find(x => x.name === providerName);
    const last = p && p.last_group_name;
    groupEl.value = "";
    groupEl.placeholder = last
      ? last+" (used for new channels; existing ones keep their own group)"
      : "probarr ("+DATA.run_id+") -- new channels only";
  }
  if(!dispatchers.length){
    noprov.style.display = "block"; body.style.display = "none";
  } else {
    noprov.style.display = "none"; body.style.display = "block";
    sel.innerHTML = dispatchers.map(p =>
      '<option value="'+esc(p.name)+'">'+esc(p.name)+'</option>').join("");
    // Default to the SAME provider this run was sourced from, if it was one
    // -- the point of tying export targets to Providers at all is that the
    // common case (push results back into where they came from) needs no
    // extra configuration.
    // Last used wins over the run's own source: pushing back into where a
    // run came from is a good guess, but where you actually pushed LAST
    // time is knowledge, not a guess.
    if(DATA.meta && DATA.meta.provider_name &&
       dispatchers.some(p => p.name === DATA.meta.provider_name)){
      sel.value = DATA.meta.provider_name;
    }
    if(cfg.push_provider && dispatchers.some(p => p.name === cfg.push_provider)){
      sel.value = cfg.push_provider;
    }
    fillGroupFor(sel.value);
    sel.onchange = () => { fillGroupFor(sel.value); dmSummary(); };
    // Everything is answered, so the buttons are live on open.
    document.getElementById("dm-preview").disabled = false;
    _push.disabled = false;
    dmSummary();
  }
  modal.classList.add("on");
  await checkPushStatus();
}

// Server-persisted push status (see store.write_push_status /
// _export_dispatcharr_status in web.py) is the source of truth, not
// anything held in this tab's local variables -- polled from scratch on
// modal open so reopening the modal after a reload, or from a different
// tab entirely, shows a push that's still running or already finished
// instead of a blank "Push" button with no memory of it.
let pushPoll = null;
// Whether a push was started from THIS opening of the modal. Without it,
// reopening after any completed push re-renders that stale "done" status
// and leaves the button stuck on Close -- so a later change (a regroup,
// say) could never be pushed again without a page reload.
let pushStarted = false;
function stopPushPoll(){ if(pushPoll){ clearInterval(pushPoll); pushPoll = null; } }
function renderPushStatus(s){
  const btn = document.getElementById("dm-push");
  const result = document.getElementById("dm-result");
  if(!s || s.state === "none"){
    return;
  }
  if(s.state === "running"){
    btn.disabled = true; btn.textContent = "Pushing\u2026";
    const phase = s.phase === "resolving" ? "resolving streams" : "pushing to Dispatcharr";
    result.className = "mresult show";
    result.textContent = "In progress \u2014 "+phase+": "+s.done+"/"+s.total+
      (s.current ? " (\u201c"+s.current+"\u201d)" : "");
  } else if(s.state === "done"){
    if(!pushStarted){
      // A completed push from an earlier session: show its result, but
      // leave the button ready to push again rather than as a dead Close.
      btn.disabled = false; btn.textContent = "Push"; delete btn.dataset.done;
      stopPushPoll();
      return;
    }
    btn.disabled = false; btn.textContent = "Close"; btn.dataset.done = "1";
    const d = s.summary;
    result.className = "mresult show good";
    result.textContent = d.created+" created, "+d.updated+" updated"+
      (d.errors.length ? ", "+d.errors.length+" error(s):\n"+
        d.errors.map(e=>"  "+e.channel+": "+e.error).join("\n") : "")+
      (d.deleted && d.deleted.length
        ? "\ndeleted from Dispatcharr: "+d.deleted.map(x =>
            (x.number!=null?x.number+" ":"")+(x.name||"")+
            (x.error?" (FAILED: "+x.error+")":x.id==null?" (already gone)":"")
          ).join(", ") : "")+
      (d.pruned && d.pruned.length
        ? "\nremoved emptied group(s): "+d.pruned.join(", ") : "")+
      (d.same_instance ? "\n(reused existing streams -- same instance as the run's source)"
                        : "\n(created new custom streams in the target)");
    stopPushPoll();
    checkPending();
  } else if(s.state === "error"){
    btn.disabled = false; btn.textContent = "Push"; delete btn.dataset.done;
    result.className = "mresult show bad";
    result.textContent = "Error after "+s.done+"/"+s.total+" channels: "+s.error;
    stopPushPoll();
  }
}
async function checkPushStatus(){
  try{
    const s = await (await fetch(
      "/api/run/"+encodeURIComponent(DATA.run_id)+"/export/dispatcharr/status",
      {cache:"no-store"})).json();
    renderPushStatus(s);
    if(s.state === "running" && !pushPoll){
      pushPoll = setInterval(checkPushStatus, 1500);
    }
  }catch(e){ /* transient; next poll or modal reopen will retry */ }
}

document.querySelectorAll(".fbopt").forEach(opt => {
  opt.addEventListener("click", () => {
    document.querySelectorAll(".fbopt").forEach(el => el.classList.remove("checked"));
    opt.classList.add("checked");
    opt.querySelector('input[type=radio]').checked = true;
    document.getElementById("dm-push").disabled = false;
    document.getElementById("dm-preview").disabled = false;
    dmSummary();
  });
});
document.getElementById("dm-preview").addEventListener("click", async () => {
  const btn = document.getElementById("dm-preview");
  const box = document.getElementById("dm-plan");
  const provider = document.getElementById("dm-provider").value;
  const fbEl = document.querySelector('input[name="fbmode"]:checked');
  if(!provider || !fbEl) return;
  btn.disabled = true; btn.textContent = "Checking\u2026";
  box.className = "dm-plan show"; box.innerHTML = "working\u2026";
  try{
    const r = await fetch("/api/run/"+encodeURIComponent(DATA.run_id)+
      "/export/dispatcharr/plan",
      {method:"POST", headers:{"Content-Type":"application/json"},
       body: JSON.stringify({provider, fallback_mode: fbEl.value,
                             group_name: document.getElementById("dm-group").value,
                             channel_key: pushChannelKey || undefined})});
    const d = await r.json();
    if(d.error){ box.innerHTML = '<span class="pchg">Error: '+esc(d.error)+'</span>'; }
    else {
      const c = d.counts;
      const dels = d.removals || [];
      // Channels the provider has stopped carrying. Nothing is done to
      // them -- the push never deletes on its own -- but they used to be
      // skipped in total silence, so a channel could sit dead in
      // Dispatcharr indefinitely with the preview cheerfully reporting
      // "no change" for everything it DID carry.
      const gone = d.dropped || [];
      // Number collisions with a Dispatcharr channel probarr has never
      // claimed (see claims.py) -- push() refuses to touch these, so they
      // need to be resolved right here, not discovered as a surprise
      // after the push already ran.
      const actions = d.actions || [];
      const blocked = actions.filter(a => a.kind === "blocked");
      const relink = actions.filter(a => a.kind === "relink");
      const normal = actions.filter(a => a.kind !== "blocked" && a.kind !== "relink"
                                       && a.kind !== "unchanged");
      unresolvedConflicts = blocked.length + relink.length;
      updatePushGate();
      box.innerHTML = '<div class="pcounts"><b>'+c.create+'</b> to create, <b>'+
        c.update+'</b> to update, <b>'+c.unchanged+'</b> already correct'+
        (dels.length ? ', <b>'+dels.length+'</b> to DELETE' : '')+
        (gone.length ? ', <b>'+gone.length+'</b> no longer carried' : '')+
        (blocked.length ? ', <b>'+blocked.length+'</b> BLOCKED' : '')+
        (relink.length ? ', <b>'+relink.length+'</b> need relinking' : '')+'</div>'+
        (blocked.length + relink.length
          ? '<div class="warn">Push will skip '+(blocked.length+relink.length)+
            ' channel(s) below until you resolve them. Bulk-resolving a lot '+
            'at once (e.g. after a Dispatcharr restore)? '+
            '<a href="/unclaimed" target="_blank" rel="noopener">Open Unclaimed ↗</a></div>'
          : '')+
        blocked.map(a => conflictRow(a, false)).join("") +
        relink.map(a => conflictRow(a, true)).join("") +
        dels.map(x =>
          '<div class="dm-row delete"><span class="pname">'+
          (x.number!=null?x.number+' ':'')+esc(x.name||"")+
          '</span><span class="pchg">'+
          (x.present ? "will be DELETED from Dispatcharr"
                     : "already gone from Dispatcharr")+'</span></div>').join("")+
        gone.map(x =>
          '<div class="dm-row dropped"><span class="pname">'+
          (x.number!=null?x.number+' ':'')+esc(x.name||"")+
          '</span><span class="pchg">'+esc(x.reason||"no usable stream")+
          (x.present ? ' — still live in Dispatcharr, left untouched'
                     : ' — not in Dispatcharr')+'</span></div>').join("")+
        normal.map(a =>
          '<div class="dm-row '+a.kind+'"><span class="pname">'+
          (a.number!=null?a.number+' ':'')+esc(a.name)+'</span><span class="pchg">'+
          (a.kind==="create" ? "will be created" :
           a.changes.map(ch => (ch.field==="group"||ch.field==="logo")
              ? esc(ch.field)+' <code>'+esc(ch.from_name||ch.from)+'</code> \u2192 <code>'+
                esc(ch.to_name||ch.to)+'</code>'
              : esc(ch.field)+' <code>'+esc(JSON.stringify(ch.from))+'</code> \u2192 <code>'+
                esc(JSON.stringify(ch.to))+'</code>').join(", "))+
          '</span></div>').join("")+
        (c.unchanged
          ? '<div class="dm-unchanged-count">'+c.unchanged+' more already correct, not shown</div>'
          : '');
    }
  }catch(e){ box.innerHTML = '<span class="pchg">Request failed.</span>'; }
  btn.disabled = false; btn.textContent = "Preview changes";
});

let unresolvedConflicts = 0;
function updatePushGate(){
  const pbtn = document.getElementById("dm-push");
  if(unresolvedConflicts > 0){
    pbtn.disabled = true;
    pbtn.title = unresolvedConflicts+" channel(s) need resolving above before this can push.";
  } else {
    pbtn.disabled = false;
    pbtn.title = "";
  }
}

function conflictRow(a, isRelink){
  const cur = a.dispatcharr_current || {};
  const warning = isRelink
    ? 'This looks like the same channel, just not yet linked to probarr.'
    : 'This will OVERWRITE channel '+a.number+' in Dispatcharr. It currently '+
      'contains \u201c'+esc(cur.name||"")+'\u201d ('+esc(cur.group||"no group")+', '+
      (cur.streams||0)+' stream(s)). It will be replaced with \u201c'+esc(a.name)+
      '\u201d. This cannot be undone from here.';
  return '<div class="dm-row '+a.kind+'" data-dispatcharr-id="'+esc(cur.id)+
    '" data-channel-key="'+esc(a.key||"")+'" data-channel-name="'+esc(a.name)+'">'+
    '<span class="pname">'+(a.number!=null?a.number+' ':'')+esc(a.name)+
    ' <span class="pchg">'+(isRelink ? '\u2014 looks like a match' : '\u2014 BLOCKED')+
    '</span></span>'+
    '<span class="dm-conflict-detail">Dispatcharr currently has \u201c'+
    esc(cur.name||"")+'\u201d ('+esc(cur.group||"no group")+', '+(cur.streams||0)+
    ' stream(s)) at number '+a.number+'.</span>'+
    '<div class="dm-conflict-actions">'+
    '<button class="resolve-claim" data-warn="'+esc(warning)+'">'+
    (isRelink ? "Relink \u2014 this is the same channel" : "This is my channel \u2014 let me push it")+
    '</button>'+
    '<button class="resolve-skip">Skip for now</button>'+
    // Same underlying claims.json this button writes to, just the other
    // door in -- Unclaimed also shows bulk assign/delete, useful when a
    // whole batch of these came from the same cause (a Dispatcharr
    // restore, say) rather than resolving one at a time here.
    '<a href="/unclaimed" target="_blank" rel="noopener">Manage in Unclaimed \u2197</a>'+
    '</div></div>';
}

document.getElementById("dm-plan").addEventListener("click", async e => {
  const row = e.target.closest(".dm-row");
  if(!row) return;
  if(e.target.classList.contains("resolve-skip")){
    row.remove();
    unresolvedConflicts = Math.max(0, unresolvedConflicts - 1);
    updatePushGate();
    return;
  }
  if(!e.target.classList.contains("resolve-claim")) return;
  const warn = e.target.dataset.warn || "";
  if(!confirm(warn+"\n\nContinue?")) return;
  e.target.disabled = true; e.target.textContent = "Linking\u2026";
  try{
    const r = await fetch("/api/dispatcharr/claim", {method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({dispatcharr_id: row.dataset.dispatcharrId,
                            channel_key: row.dataset.channelKey,
                            name: row.dataset.channelName,
                            source: "run:"+DATA.run_id})});
    const d = await r.json();
    if(d.error){ alert("Could not link: "+d.error); e.target.disabled = false;
                e.target.textContent = "Relink"; return; }
    document.getElementById("dm-preview").click();
  }catch(e2){ alert("Request failed."); e.target.disabled = false; }
});
function dmSummary(){
  const fb = document.querySelector('input[name="fbmode"]:checked');
  const grp = document.getElementById("dm-group").value.trim();
  document.getElementById("dm-sumtext").innerHTML =
    "Into <b>"+esc(document.getElementById("dm-provider").value)+"</b>"+
    " &middot; "+(fb && fb.value === "separate"
      ? "fallback as its own channel" : "native fallback")+
    (grp ? " &middot; new channels into <b>"+esc(grp)+"</b>" : "")+
    (document.getElementById("dm-prune").checked
      ? " &middot; tidying emptied groups" : "");
}
document.getElementById("dm-more").addEventListener("click", () => {
  const box = document.getElementById("dm-options");
  const open = box.style.display === "none";
  box.style.display = open ? "block" : "none";
  document.getElementById("dm-more").textContent = open ? "done" : "change";
});
["dm-prune","dm-group"].forEach(id =>
  document.getElementById(id).addEventListener("change", dmSummary));
document.querySelectorAll('input[name="fbmode"]').forEach(r =>
  r.addEventListener("change", dmSummary));

document.getElementById("dm-cancel").addEventListener("click", () => {
  document.getElementById("dispatchmodal").classList.remove("on");
  // Stop polling while the modal is closed rather than leaking an interval
  // per open/close cycle -- reopening calls checkPushStatus() again, which
  // resumes polling on its own if the push turns out to still be running.
  stopPushPoll();
});
document.getElementById("dm-push").addEventListener("click", async () => {
  const btn = document.getElementById("dm-push");
  const result = document.getElementById("dm-result");
  if(btn.dataset.done){
    document.getElementById("dispatchmodal").classList.remove("on");
    stopPushPoll();
    return;
  }
  const provider = document.getElementById("dm-provider").value;
  const fbEl = document.querySelector('input[name="fbmode"]:checked');
  if(!provider || !fbEl) return;
  btn.disabled = true; btn.textContent = "Pushing\u2026";
  result.className = "mresult show"; result.textContent = "Starting\u2026";
  try{
    const r = await fetch("/api/run/"+encodeURIComponent(DATA.run_id)+"/export/dispatcharr",
      {method:"POST", headers:{"Content-Type":"application/json"},
       body: JSON.stringify({provider, fallback_mode: fbEl.value,
                             group_name: document.getElementById("dm-group").value,
                             prune_empty_groups:
                               document.getElementById("dm-prune").checked,
                             channel_key: pushChannelKey || undefined})});
    const d = await r.json();
    if(d.error){
      // 409 (already in progress) still carries the current status --
      // show it and start polling rather than treating it as a dead end.
      if(d.status){ pushStarted = true; renderPushStatus(d.status);
                    pushPoll = setInterval(checkPushStatus, 1500); }
      else { result.className = "mresult show bad"; result.textContent = "Error: "+d.error;
             btn.disabled = false; btn.textContent = "Push"; }
      return;
    }
    // Push is now running server-side, independent of this tab. Poll for
    // progress rather than waiting on this request, which already returned.
    pushStarted = true;
    checkPushStatus();
    pushPoll = setInterval(checkPushStatus, 1500);
  }catch(e){
    result.className = "mresult show bad"; result.textContent = "Request failed.";
    btn.disabled = false; btn.textContent = "Push";
  }
});
</script></body></html>
"""


def changes_since_last_probe(store):
    """{channel_key: [human-readable change, ...]} from the results history.

    A re-verify refreshes a run in place, which is what keeps every curated
    pick -- but it also means the page looks identical afterwards whether
    nothing moved or half the lineup died. The evidence is already on disk:
    the log is append-only, so every probe's PREVIOUS result is still there
    to compare against.

    Only differences worth a person's attention are reported. A bitrate
    wobbling by 3% on a live stream is not news; a stream that stopped
    decoding, started decoding, or changed what country it is coming from
    is exactly what someone logging in afterwards is looking for.
    """
    history = {}
    for r in store.load(dedupe=False):
        rk = r.get("rec_key") or f"{r.get('channel_key')}|{r.get('stream_id')}"
        history.setdefault(rk, []).append(r)

    out = {}
    for rk, versions in history.items():
        if len(versions) < 2:
            continue
        new, old = versions[-1], versions[-2]
        if new.get("probed_at", 0) <= old.get("probed_at", 0):
            continue
        key = new.get("channel_key")
        name = (new.get("stream_name") or "")[:28]
        was, now = old.get("status"), new.get("status")
        msgs = []
        if was != now:
            broke = now in ("dead", "no_frame", "placeholder")
            fixed = was in ("dead", "no_frame", "placeholder") and now == "ok"
            if broke:
                msgs.append(f"{name} stopped working ({was} -> {now})")
            elif fixed:
                msgs.append(f"{name} works again ({was} -> {now})")
            else:
                msgs.append(f"{name}: {was} -> {now}")
        # Resolution and cadence are identity, not quality: a stream that
        # changes either is not the same feed it was, whatever it is called.
        if (old.get("width"), old.get("height")) != (new.get("width"), new.get("height")) \
                and new.get("width") and old.get("width"):
            msgs.append(f"{name} changed size "
                        f"({old['width']}x{old['height']} -> {new['width']}x{new['height']})")
        if old.get("fps") and new.get("fps") and \
                round(float(old["fps"]), 2) != round(float(new["fps"]), 2):
            msgs.append(f"{name} changed frame rate "
                        f"({old['fps']:g} -> {new['fps']:g})")
        if msgs:
            out.setdefault(key, []).extend(msgs)
    return out


def build_payload(by_channel, store, guide_present=False, inherited=None,
                  dropped=None, epg_mismatches=None, claims=None):
    """Channel records for the curation view, URL-referenced (not embedded).

    `claims`: {channel_key: {dispatcharr_id, ...}} from claims.claimed_by_key()
    -- purely a debugging display (see the "linked #N"/"not linked" tag
    next to the title in curate.py's own detail header), so a caller not
    passing it (None, the default) just gets no tag rather than an error.
    """
    want = store.read_wantlist()
    wanted = want.get("wanted") or []
    by_key = {w["key"]: w for w in wanted}
    order = {w["key"]: i for i, w in enumerate(wanted)}

    channels = []
    for key, records in by_channel.items():
        ranked = rank_mod.rank(records)
        w = by_key.get(key, {})
        # A rename is a durable property of the CHANNEL, not of this run's
        # candidates, so a name carried on the lineup wins over whatever the
        # provider called it in the wantlist. Without this, renaming in one
        # run silently reverted to the provider's name in the next.
        pref_name = ((inherited or {}).get(key) or {}).get("name")
        # Same reasoning as the rename above, for the number: a fresh run
        # rebuilds its wantlist from the provider, which has no notion of a
        # Dispatcharr number at all, so a number set by hand in Curate would
        # otherwise vanish (and the channel would drop out of every export
        # again) the moment the lineup was next re-run.
        pref_number = ((inherited or {}).get(key) or {}).get("number")
        expected = next((r.get("expected") for r in ranked if r.get("expected")), None)
        channels.append({
            "key": key,
            "number": w.get("number") if w.get("number") is not None else pref_number,
            "claim": (claims or {}).get(key),
            "title": pref_name or w.get("name")
                     or (ranked[0].get("stream_name") if ranked else key),
            "why": rank_mod.explain_choice(ranked),
            "expected": expected,
            "epg_missing": expected is None and guide_present,
            "missing": False,
            # Where this channel already exists in Dispatcharr, so Curate can
            # say what is live there right now next to the alternatives.
            "dispatcharr": w.get("dispatcharr") if w.get("imported_from") else None,
            # Independent of the above: this needs no prior Import, only a
            # matching channel NUMBER in Dispatcharr -- see web.py's
            # _epg_mismatches() for why a stored uuid cannot be relied on.
            "epg_mismatch": (epg_mismatches or {}).get(key),
            "candidates": [{
                "id": r.get("rec_key") or r["stream_id"],
                "stream_id": r["stream_id"],
                "name": r.get("stream_name", ""),
                "url": r.get("url_redacted", ""),
                "logo": r.get("logo", ""),
                "status": r.get("status", "dead"),
                "reason": r.get("reason", ""),
                "w": r.get("width", 0), "h": r.get("height", 0),
                "fps": r.get("fps", 0), "kbps": r.get("measured_kbps", 0),
                "vcodec": r.get("video_codec", ""), "acodec": r.get("audio_codec", ""),
                "ach": r.get("audio_channels", 0),
                # Real evidence this exact stream has failed in production,
                # from Dispatcharr's own log -- see web.py's _dropped_urls().
                "dropped": (dropped or {}).get(key, {}).get(r.get("url_redacted")) or
                          (dropped or {}).get(key, {}).get(r.get("url")),
                "corrupt": r.get("corruption_errors", 0),
                "dup": r.get("placeholder_group"),
                "lowmo": bool(r.get("low_motion")),
                "offcad": bool(r.get("off_cadence")),
                "cad": r.get("cadence", ""),
                "housecad": r.get("house_cadence", ""),
                "abr": bool(r.get("multi_bitrate_manifest")),
                "dashabr": bool(r.get("dash_multi_bitrate")),
                "slowfetch": bool(r.get("slow_fetch")),
                "rank": i + 1,
                # What the guide said was airing AT THIS CANDIDATE'S OWN
                # probe moment -- distinct from the channel-level `expected`
                # above (which is only ever the first ranked candidate's),
                # because candidates are not all probed at the same instant.
                # A picture that doesn't match a MISMATCHED channel-level
                # guide is ambiguous (maybe this candidate was just probed
                # at a different time); a picture that doesn't match ITS
                # OWN capture-time guide entry is not.
                "expected": r.get("expected"),
                "thumb": _url(store, r.get("thumb"), r.get("probed_at")),
                "frame": _url(store, r.get("frame"), r.get("probed_at")),
                "crop": _url(store, r.get("crop"), r.get("probed_at")),
                "clip": _url(store, r.get("clip"), r.get("probed_at")),
            } for i, r in enumerate(ranked)],
        })

    # Wanted channels that matched nothing still belong in the list. Dropping
    # them would hide the most actionable failure in a run -- a channel absent
    # because its name needs an alias looks identical to one you never asked
    # for.
    for w in wanted:
        if w["key"] not in by_channel:
            channels.append({"key": w["key"],
                             "number": w.get("number") if w.get("number") is not None
                                       else ((inherited or {}).get(w["key"]) or {}).get("number"),
                             "claim": (claims or {}).get(w["key"]),
                             "title": (((inherited or {}).get(w["key"]) or {})
                                       .get("name") or w.get("name")), "why": "no candidate streams matched",
                             "expected": None, "epg_missing": False,
                             "dispatcharr": (w.get("dispatcharr")
                                             if w.get("imported_from") else None),
                             "missing": True, "candidates": []})

    moved = changes_since_last_probe(store)
    sel_now = {**(inherited or {}), **(store.read_selection() or {})}
    for c in channels:
        msgs = list(moved.get(c["key"], []))
        pick = (sel_now.get(c["key"]) or {}).get("primary")
        cands = c.get("candidates") or []
        if pick and cands and cands[0]["id"] != pick:
            chosen = next((x for x in cands if x["id"] == pick), None)
            if chosen is None:
                msgs.append("the stream you chose is gone from this run")
            elif chosen["status"] != "ok" and cands[0]["status"] == "ok":
                msgs.append(f"your pick is now {chosen['status']}; "
                            f"{cands[0]['name'][:28]} is clean")
            else:
                msgs.append(f"{cands[0]['name'][:28]} now ranks above your pick")
        c["changes"] = msgs

    if order:
        channels.sort(key=lambda c: (order.get(c["key"], 10 ** 6),
                                     c["number"] if c["number"] is not None else 10 ** 6))
    else:
        channels.sort(key=lambda c: c["title"].lower())

    # Lineup preferences are layered UNDER the run's own selection: a
    # durable per-channel decision ("this channel's guide comes from
    # open-epg") is inherited by every later run automatically, while
    # anything decided in THIS run still wins. Without this a judgement
    # made while curating one run was invisible to the next, and had to be
    # made again with nothing indicating it ever had been.
    selection = dict(inherited or {})
    for k, v in (store.read_selection() or {}).items():
        selection[k] = {**inherited.get(k, {}), **v} if inherited else v
    return {"run_id": store.run_id, "meta": store.read_meta(),
            "selection": selection, "channels": channels}


def _url(store, rel, version=None):
    """Image URL, versioned by when the frame was captured.

    Re-probing overwrites the image in place, so the path alone is unchanged
    and a browser happily keeps showing the old picture -- the response carries
    no validators, so heuristic caching applies and even a full reload serves
    the stale copy. In a tool whose entire premise is looking at the frame,
    silently showing yesterday's frame is the worst possible failure.

    Appending the capture time makes the URL change exactly when the image
    does, which also lets the file handler mark it immutable and cache it hard.
    """
    if not rel:
        return None
    # The record can outlive the file: Clear Images on the run's page deletes
    # every capture but deliberately leaves every result untouched, since
    # results are the record of truth and pictures are illustration. Without
    # this check the record still points at the deleted file, and instead of
    # the promised "no frame until next probed" the card shows a broken
    # image icon.
    if not os.path.exists(os.path.join(store.dir, rel)):
        return None
    v = int(version or 0)
    return f"/run/{store.run_id}/file/{rel}" + (f"?v={v}" if v else "")


def render(by_channel, store, guide_present=False, inherited=None, dropped=None,
          epg_mismatches=None, claims=None):
    payload = build_payload(by_channel, store, guide_present, inherited, dropped,
                            epg_mismatches, claims)
    right = ('<span class="saveind" id="saveind"></span>'
             '<button id="pushall" title="Push every channel whose Dispatcharr state differs from your curated picks.">Push changes</button>'
             f'<a href="/run/{store.run_id}/export.xmltv" title="A guide for '
             'exactly these channels, keyed to the same ids as the playlist '
             '&mdash; a player needs both.">'
             '<button>Export EPG</button></a>'
             f'<a href="/run/{store.run_id}/export.m3u">'
             '<button class="primary">Export M3U</button></a>')
    return (HTML
            .replace("__TOPBAR__", topbar(f"curate &middot; run {store.run_id}",
                                          active="runs", right=right))
            .replace("__CSS__", CSS)
            .replace("__EXTRA__", EXTRA_CSS)
            .replace("__DATA__", json.dumps(payload, ensure_ascii=False))
            .replace("__RUN__", store.run_id))
