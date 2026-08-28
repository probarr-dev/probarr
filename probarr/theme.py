"""Shared visual language for the contact sheet and the web UI.

Deliberately styled after the *arr applications (Sonarr/Radarr/Prowlarr): dark
slate ground, a single accent, dense information rows. Anyone arriving from
that stack should not have to learn a new visual grammar to read this.
"""
from . import __version__

CSS = """
:root{
  --bg:#1f2224; --bg2:#262b2e; --panel:#2a2f33; --panel2:#31373b;
  --line:#3a4247; --text:#e8eaec; --dim:#9aa4ab; --faint:#6b757c;
  --accent:#35c5f0; --accent2:#1e9fc7;
  --ok:#27c24c; --warn:#f0ad4e; --bad:#f05050; --dup:#a774d9;
  --radius:4px;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
a{color:var(--accent);text-decoration:none}
header.topbar{position:sticky;top:0;z-index:50;background:var(--bg2);
  border-bottom:1px solid var(--line);padding:9px 16px 10px;
  display:flex;flex-direction:column;gap:9px}
.tbrow{display:flex;gap:10px;align-items:center;flex-wrap:wrap;width:100%}
.tbmain{gap:14px}
/* The nav sits under the actions rather than beside them, at every width,
   so the header keeps one shape instead of rearranging itself. */
.tbnav{border-top:1px solid var(--line);padding-top:9px;margin-bottom:-1px}
.tbnav .nav{flex-wrap:wrap}
.brand{font-weight:700;font-size:16px;letter-spacing:.3px;color:var(--text);
  text-decoration:none;display:inline-block}
.brand span{color:var(--accent)}
a.brand:hover{opacity:.8}
.brand-version{font-weight:400;font-size:11px;color:var(--faint);
  letter-spacing:normal;margin-left:6px}
.nav{display:flex;gap:6px;align-items:center}
.nav a{text-decoration:none}
.nav button.on{background:var(--panel2);border-color:var(--faint);color:var(--text)}
.nav .sep{width:1px;height:20px;background:var(--line);margin:0 4px}
.navmenu-wrap{position:relative}
.navmenu{display:none;position:absolute;top:calc(100% + 6px);left:0;z-index:60;
  background:var(--panel2);border:1px solid var(--line);border-radius:var(--radius);
  box-shadow:0 6px 18px rgba(0,0,0,.35);padding:5px;min-width:150px;
  flex-direction:column;gap:2px}
.navmenu.on{display:flex}
.navmenu a{text-decoration:none}
.navmenu button{width:100%;text-align:left;background:transparent;border:1px solid transparent}
.navmenu button:hover{background:var(--panel)}
.navmenu button.on{background:var(--panel2);border-color:var(--faint);color:var(--text)}
.runmeta{color:var(--dim);font-size:12px}
.spacer{flex:1}
.diagbadge{position:relative;display:none;align-items:center;gap:5px;
  background:var(--panel2);border:1px solid var(--line);border-radius:999px;
  padding:4px 11px;font-size:12px;color:var(--dim)}
.diagbadge.show{display:flex}
.diagbadge b{color:var(--text)}
.diagpop{display:none;position:absolute;top:calc(100% + 6px);right:0;z-index:60;
  background:var(--panel2);border:1px solid var(--line);border-radius:var(--radius);
  box-shadow:0 6px 18px rgba(0,0,0,.35);padding:8px 10px;width:max-content;
  max-width:340px;max-height:260px;overflow-y:auto;font-size:12.5px;color:var(--text)}
.diagbadge:hover .diagpop{display:block}
.diagpop-group{padding:5px 0 3px;border-bottom:1px solid rgba(255,255,255,.05)}
.diagpop-group:last-child{border-bottom:0}
.diagpop-chan{font-weight:600;color:var(--text)}
.diagpop-stream{padding:2px 0 2px 12px;color:var(--dim)}
input[type=search],select{background:var(--panel);color:var(--text);
  border:1px solid var(--line);border-radius:var(--radius);padding:6px 9px;font-size:13px}
input[type=search]{min-width:200px}
button{background:var(--panel2);color:var(--text);border:1px solid var(--line);
  border-radius:var(--radius);padding:6px 12px;font-size:13px;cursor:pointer}
button:hover{background:var(--line)}
button.primary{background:var(--accent2);border-color:var(--accent2);color:#04222c;font-weight:600}
button.primary:hover{background:var(--accent)}
.toggles{display:flex;gap:12px;align-items:center;font-size:12px;color:var(--dim);flex-wrap:wrap}
.toggles label{display:flex;gap:5px;align-items:center;cursor:pointer;user-select:none}
.filters{background:var(--bg2);border-bottom:1px solid var(--line);
  padding:9px 16px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
.stats{display:flex;gap:16px;padding:10px 16px;background:var(--bg2);
  border-bottom:1px solid var(--line);font-size:12px;color:var(--dim);flex-wrap:wrap}
.stats b{color:var(--text);font-size:15px;margin-right:4px}
main{padding:14px 16px 80px}
.channel{background:var(--panel);border:1px solid var(--line);
  border-radius:var(--radius);margin-bottom:12px;overflow:hidden}
.channel.excluded{opacity:.45}
.chead{display:flex;gap:12px;align-items:center;padding:9px 12px;
  background:var(--panel2);border-bottom:1px solid var(--line);cursor:pointer}
.chead h2{margin:0;font-size:15px;font-weight:600}
.chead .why{color:var(--dim);font-size:12px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(232px,1fr));
  gap:10px;padding:12px}
.card{background:var(--bg2);border:1px solid var(--line);border-radius:var(--radius);
  overflow:hidden;position:relative;transition:border-color .12s}
.card:hover{border-color:var(--faint)}
.card.chosen{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset}
.card.fallback{border-color:var(--warn);box-shadow:0 0 0 1px var(--warn) inset}
.thumbwrap{position:relative;aspect-ratio:16/9;background:#000;
  display:flex;align-items:center;justify-content:center}
.thumbwrap img{width:100%;height:100%;object-fit:contain;display:block;cursor:zoom-in}
.noframe{color:var(--faint);font-size:12px;text-align:center;padding:8px}
.pill{position:absolute;top:6px;left:6px;font-size:10px;font-weight:700;
  letter-spacing:.4px;padding:2px 6px;border-radius:3px;text-transform:uppercase}
.pill.ok{background:var(--ok);color:#062a0f}
.pill.dirty{background:var(--warn);color:#3a2600}
.pill.placeholder{background:var(--dup);color:#1c0730}
.pill.no_frame,.pill.no_video,.pill.dead{background:var(--bad);color:#3a0000}
.rank{position:absolute;top:6px;right:6px;font-size:10px;font-weight:700;
  background:rgba(0,0,0,.72);color:var(--dim);padding:2px 6px;border-radius:3px}
.rank.r1{color:var(--accent)}
.dupflag{position:absolute;bottom:6px;left:6px;font-size:10px;font-weight:700;
  background:var(--dup);color:#1c0730;padding:2px 6px;border-radius:3px}
.cbody{padding:8px 9px}
.sname{font-size:12px;color:var(--text);white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;margin-bottom:5px}
.specs{display:flex;flex-wrap:wrap;gap:4px;font-size:10.5px;margin-bottom:6px}
.spec{background:var(--panel2);border:1px solid var(--line);color:var(--dim);
  padding:1px 5px;border-radius:3px;white-space:nowrap}
.spec.hi{color:var(--text);border-color:var(--faint)}
.spec.err{color:var(--bad);border-color:var(--bad)}
.spec.warn2{color:var(--warn);border-color:var(--warn)}
.actions{display:flex;gap:5px}
.actions button{flex:1;padding:4px 0;font-size:11px}
.empty{color:var(--dim);text-align:center;padding:40px}
footer.bar{position:fixed;bottom:0;left:0;right:0;background:var(--bg2);
  border-top:1px solid var(--line);padding:9px 16px;display:flex;gap:12px;
  align-items:center;z-index:60;font-size:13px}
.lightbox{position:fixed;inset:0;background:rgba(0,0,0,.9);display:none;
  align-items:center;justify-content:center;z-index:100;cursor:zoom-out}
.lightbox.on{display:flex}
.lightbox img{max-width:94vw;max-height:88vh}
.lightbox .cap{position:absolute;bottom:16px;left:0;right:0;text-align:center;
  color:var(--dim);font-size:12px}
"""


# Pages are generated by four different modules; without one definition of the
# header they drift apart, which is how the brand ended up as dead text on
# every page and the curation view ended up with no way back at all.
#
# Split into DAILY (what you touch every time you sit down: check on runs,
# curate) and SETUP (what you configure once and rarely open again:
# providers, channels, wantlists, lineups, settings). A flat bar of six
# equally-weighted tabs gave a returning user the exact same wall of
# options as a first-time one, forever -- there was no visual difference
# between "the thing you do daily" and "the thing you did once during
# setup and will maybe touch again in a month". Setup items now live under
# one "Setup" menu instead of five permanent tabs.
_NAV_DAILY = [("runs", "/runs", "Runs")]
_NAV_SETUP = [("providers", "/providers", "Providers"),
              # The channel browser was the answer to "I have a 55,000-line
              # playlist and no idea what is in it", and it was reachable
              # only from inside the Wantlists page -- so the one screen that
              # solves a newcomer's actual first problem was the one screen
              # they never found.
              ("browse", "/browse", "Channels"),
              ("wantlists", "/wantlists", "Wantlists"),
              ("lineups", "/lineups", "Lineups"),
              # What a push refuses to touch (a number collision with a
              # Dispatcharr channel probarr has never claimed) has to have
              # a place to send you -- otherwise "blocked" in a push
              # preview is a dead end with no next step.
              ("unclaimed", "/unclaimed", "Unclaimed"),
              ("settings", "/settings", "Settings")]
_NAV_ITEMS = _NAV_DAILY + _NAV_SETUP   # kept for anything still iterating the flat list


def topbar(label="", active="", right="", home=True):
    """The shared header.

    `home` exists for the contact sheet, which is also written to disk as a
    standalone file. That copy is opened directly from the filesystem, where
    links to server paths would simply be broken, so it gets a header with no
    navigation rather than one that lies.

    A "+ New Run" button is always present (except on the standalone sheet):
    it is the single action that starts everything else, and previously had
    no obvious home in the UI at all -- there was no way to begin a run
    without already knowing the CLI.
    """
    ver = f'<span class="brand-version">v{__version__}</span>'
    brand = ((f'<a class="brand" href="/">prob<span>arr</span></a>{ver}') if home
             else f'<div class="brand">prob<span>arr</span></div>{ver}')
    nav = ""
    newrun = nav = ""
    if home:
        newrun = ('<a href="/new"><button class="primary'
                 + (' on' if active == 'new' else '') + '">+ New Run</button></a>')
        daily = "".join(
            f'<a href="{href}"><button class="{"on" if key == active else ""}">'
            f'{text}</button></a>' for key, href, text in _NAV_DAILY)
        # A dropdown, not five more permanent tabs -- these are the pages
        # you configure once during setup and rarely open again, so they
        # do not deserve the same permanent screen real estate as Runs.
        # Marked "on" as a GROUP when the active page is any one of them,
        # the same visual cue a flat tab would have given, so landing on
        # e.g. Settings doesn't look like you've navigated away from
        # everything the nav bar knows about.
        setup_on = active in {k for k, _, _ in _NAV_SETUP}
        setup_items = "".join(
            f'<a href="{href}"><button class="{"on" if key == active else ""}">'
            f'{text}</button></a>' for key, href, text in _NAV_SETUP)
        setup = (
            f'<div class="navmenu-wrap">'
            f'<button class="navmenu-btn{" on" if setup_on else ""}" '
            f'id="navsetupbtn">Setup ▾</button>'
            f'<div class="navmenu" id="navsetupmenu">{setup_items}</div>'
            f'</div>')
        nav = (f'<div class="nav">{daily}<span class="sep"></span>{setup}</div>'
               '<script>'
               '(function(){'
               'var b=document.getElementById("navsetupbtn"),'
               'm=document.getElementById("navsetupmenu");'
               'if(!b||!m)return;'
               'b.addEventListener("click",function(e){'
               'e.stopPropagation();m.classList.toggle("on");});'
               'document.addEventListener("click",function(e){'
               'if(m.classList.contains("on")&&!m.contains(e.target)'
               '&&e.target!==b)m.classList.remove("on");});'
               'document.addEventListener("keydown",function(e){'
               'if(e.key==="Escape")m.classList.remove("on");});'
               '})();'
               '</script>')
    # A count and a list, not just a count -- Diagnose is often fired at
    # several candidates of the SAME channel at once, so "2 probing" with
    # no detail reads as one thing happening twice, not two different
    # streams. Genuinely absent (not shown-but-empty) when nothing is
    # in flight, same as the rest of this header only shows what applies
    # right now. Polls /api/diagnosing (see web.py's _diagnosing_snapshot),
    # which covers every single-candidate probe this queue ever runs --
    # Diagnose, a plain card ↻ re-probe, Preview, a freshly-added
    # Find-streams pick, an imported channel's first probe -- not just
    # Diagnose, since all of those are just as invisible once their own
    # dialog closes. A NEW RUN's bulk verify pass never appears here; that
    # already has its own progress bar. Each row is labelled "diagnosing"
    # or "probing" depending which kind it actually is. Grouped by channel
    # in the popover, not one flat line per stream -- a channel with
    # several candidates queued at once (Diagnose's normal case) used to
    # repeat its own name several times in a row, reading as duplicates
    # rather than distinct streams of the same channel.
    diagbadge = ""
    if home:
        diagbadge = (
            '<div class="diagbadge" id="diagbadge" title="">'
            '<b id="diagcount"></b><span>&nbsp;probing</span>'
            '<div class="diagpop" id="diagpop"></div>'
            '</div>'
            '<script>'
            '(function(){'
            'var badge=document.getElementById("diagbadge"),'
            'count=document.getElementById("diagcount"),'
            'pop=document.getElementById("diagpop");'
            'if(!badge)return;'
            'function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;")'
            '.replace(/</g,"&lt;").replace(/>/g,"&gt;");}'
            'function poll(){'
            'fetch("/api/diagnosing",{cache:"no-store"}).then(function(r){return r.json();})'
            '.then(function(d){'
            'var rows=d.items||[];'
            'if(rows.length){'
            'badge.classList.add("show");'
            'count.textContent=rows.length;'
            'var groups=[],byKey={};'
            'rows.forEach(function(r){'
            'var k=r.run_id+"|"+r.channel_key;'
            'if(!byKey[k]){byKey[k]={channel_key:r.channel_key,run_id:r.run_id,streams:[]};'
            'groups.push(byKey[k]);}'
            'byKey[k].streams.push(r);});'
            'pop.innerHTML=groups.map(function(g){'
            'var lines=g.streams.map(function(r){'
            'var st=(r.state==="running"?"running":'
            '"queued"+(r.position?" #"+r.position:""))+'
            '(r.diagnose?" \\u00b7 diagnosing":" \\u00b7 probing");'
            'return "<div class=\\"diagpop-stream\\">"+esc(r.stream_name)+'
            '"<span style=\\"color:var(--faint)\\"> \\u2014 "+esc(st)+"</span></div>";'
            '}).join("");'
            'return "<div class=\\"diagpop-group\\"><div class=\\"diagpop-chan\\">"+'
            'esc(g.channel_key)+"<span style=\\"color:var(--faint);font-weight:400\\"> \\u2014 "'
            '+esc(g.run_id)+"</span></div>"+lines+"</div>";'
            '}).join("");'
            '}else{badge.classList.remove("show"); pop.innerHTML="";}'
            '}).catch(function(){});'
            '}'
            'poll(); setInterval(poll, 4000);'
            '})();'
            '</script>')
    # Two rows on purpose, not because the first one ran out of width.
    # What you DO on this page (export it, push it, start another run) and
    # where you can GO are different kinds of thing, and mixing them into one
    # long strip made both harder to scan -- the page's own actions ended up
    # sandwiched between the brand and a row of destinations. Splitting them
    # also stops the header reflowing into a different arrangement at every
    # window width, which is what made it look accidental.
    return (f'<header class="topbar">'
            f'<div class="tbrow tbmain">{brand}'
            f'<div class="runmeta">{label}</div>'
            f'<div class="spacer"></div>{diagbadge}{right}{newrun}</div>'
            + (f'<div class="tbrow tbnav">{nav}</div>' if nav else '')
            + '</header>')
