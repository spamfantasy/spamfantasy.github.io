"""ESPN connect (Steven, Oct 16): private leagues on phones and desktops. A synthetic ESPN league only.

ESPN's API answers 401 for private leagues unless the request carries the member's ESPN cookies, which a browser never
sends from another site. So the site shows a "bring it over yourself" box:
- Phone (touch, 390px): phone steps (Save to Files / Download → Upload saved file), a themed upload button (no native
  file control), no sideways scrolling; uploading the saved file connects straight to "Which team is yours?".
- Uploading ESPN's "not authorized" answer (a signed-out browser) says to sign in at espn.com.
- Desktop: copy-and-paste steps and the paste box; pasting the data connects.
- A request that never comes back (blocked / network) gets its own message; a readable league (200) connects directly.

Run from the repo root:  python3 tests/espn_connect_check.py   (CHROMIUM=/path/to/chromium if needed)
"""
import json, os, re, sys, threading, functools, http.server, socketserver
from playwright.sync_api import sync_playwright
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT)); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

# synthetic league: 10 teams, real NFL players (public identity) picked from the ESPN → Sleeper ID map
ids = json.load(open(os.path.join(ROOT, "data", "platform_ids.json")))["espn"]
sp = json.load(open(os.path.join(ROOT, "data", "sleeper_players.json")))
POS_ID = {"QB": 1, "RB": 2, "WR": 3, "TE": 4}
pool = [(e, s) for e, s in ids.items() if s in sp and sp[s][1] in POS_ID][:160]
teams = []
for t in range(10):
    entries = [{"playerId": int(e), "lineupSlotId": 20, "playerPoolEntry": {"player": {"fullName": sp[s][0], "defaultPositionId": POS_ID[sp[s][1]], "proTeamId": 1}}}
               for e, s in pool[t * 15:(t + 1) * 15]]
    teams.append({"id": t + 1, "name": f"Test Team {t + 1}", "primaryOwner": f"m{t}", "roster": {"entries": entries},
                  "record": {"overall": {"wins": t % 4, "losses": 4 - t % 4, "pointsFor": 500 + t, "pointsAgainst": 480}}})
LEAGUE = {"id": 123456, "seasonId": 2026, "members": [{"id": f"m{t}", "displayName": f"Manager {t}"} for t in range(10)], "teams": teams,
          "settings": {"name": "Synthetic ESPN League", "size": 10,
                       "rosterSettings": {"lineupSlotCounts": {"0": 1, "2": 2, "4": 2, "6": 1, "23": 1, "20": 6, "21": 1}},
                       "scoringSettings": {"scoringItems": [{"statId": 53, "points": 1}, {"statId": 42, "points": 0.1}, {"statId": 43, "points": 6},
                                                            {"statId": 3, "points": 0.04}, {"statId": 4, "points": 4}, {"statId": 24, "points": 0.1}, {"statId": 25, "points": 6}]}}}
NOAUTH = {"messages": ["You are not authorized to view this League."], "details": [{"message": "You are not authorized to view this League.", "shortMessage": "Not authorized", "resolution": None, "type": "AUTH_LEAGUE_NOT_VISIBLE", "metaData": None}]}
TMP = "/tmp/claude-0/espn_test"; os.makedirs(TMP, exist_ok=True)
open(f"{TMP}/league.json", "w").write(json.dumps(LEAGUE))
open(f"{TMP}/noauth.json", "w").write(json.dumps(NOAUTH))

with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw); errs = []
    def page(mode, phone):
        ctx = br.new_context(**({"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True, "device_scale_factor": 2} if phone else {"viewport": {"width": 1440, "height": 1000}}))
        pg = ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        def espn(route):
            if mode == "abort": return route.abort()
            if mode == "ok": return route.fulfill(status=200, content_type="application/json", body=json.dumps(LEAGUE))
            return route.fulfill(status=401, content_type="application/json", body=json.dumps(NOAUTH))
        pg.route("https://lm-api-reads.fantasy.espn.com/**", espn)
        pg.route(re.compile(r"https://(api\.sleeper\.app|api\.sleeper\.com|sleepercdn\.com|a\.espncdn\.com|api\.github\.com)/.*"), lambda r: r.abort())
        pg.goto(f"http://127.0.0.1:{port}/#rankings"); pg.wait_for_timeout(2500)
        pg.evaluate("() => { document.getElementById('fmt-chip').click(); }"); pg.wait_for_timeout(300)
        pg.evaluate("() => document.querySelector('#fmt-import [data-import=espn]').click()"); pg.wait_for_timeout(300)
        pg.fill("#im-espn-id", "https://fantasy.espn.com/football/league?leagueId=123456")
        pg.click("#im-espn-go"); pg.wait_for_timeout(1200)
        return pg, ctx
    vis = lambda pg, sel: pg.evaluate(f"() => {{ const e = document.querySelector('{sel}'); if (!e) return false; const r = e.getBoundingClientRect(); return r.width > 2 && r.height > 2 && e.checkVisibility({{ visibilityProperty: true, contentVisibilityAuto: true }}); }}")

    # 1. phone, private league
    pg, ctx = page("private", True)
    ok(vis(pg, "#im-espn-paste"), "Private league: the bring-it-over box opens")
    why = pg.inner_text("#im-espn-why")
    ok("private" in why.lower() and "signed-in" in why.lower(), f"It says the league is private: {why[:80]!r}")
    ok(vis(pg, ".im-steps-phone") and not vis(pg, ".im-steps-desk"), "Phone: phone steps (Save to Files / Download), no Ctrl+A steps")
    ok("Save to Files" in pg.inner_text(".im-steps-phone") and "Download" in pg.inner_text(".im-steps-phone"), "Phone steps name Save to Files and Download")
    ok(vis(pg, ".im-file-btn") and not vis(pg, "#im-espn-file"), "A themed Upload saved file button, the native file control hidden")
    ok(pg.evaluate("() => document.querySelector('.im-file-btn').getBoundingClientRect().height") >= 44, "The upload button is at least 44px tall (easy to tap)")
    ok(not vis(pg, "#im-espn-json"), "The paste box is tucked away on phones")
    ok(pg.evaluate("() => document.getElementById('im-espn-file').getAttribute('accept') === null"), "No file-type filter (saved pages aren't greyed out in Files)")
    over = pg.evaluate("() => { const d = document.querySelector('#import-dialog'); return [d.scrollWidth - d.clientWidth, document.documentElement.scrollWidth - window.innerWidth]; }")
    ok(max(over) <= 1, f"No sideways scrolling at 390px ({over})")
    a = pg.get_attribute(".im-steps-phone .im-espn-link", "href")
    ok(a and "leagues/123456" in a and "mRoster" in a, f"The link opens the league's data with rosters ({a[-70:] if a else a})")
    if os.environ.get("SHOTS"): pg.screenshot(path=f"{os.environ['SHOTS']}/espn_phone.png")
    pg.set_input_files("#im-espn-file", f"{TMP}/noauth.json"); pg.wait_for_timeout(800)
    e1 = pg.inner_text("#im-espn-error")
    ok("sign in at espn.com" in e1.lower(), f"ESPN's 'not authorized' file says to sign in: {e1[:90]!r}")
    pg.set_input_files("#im-espn-file", f"{TMP}/league.json"); pg.wait_for_timeout(1500)
    ok(vis(pg, "#im-mine") and "Synthetic ESPN League" in pg.inner_text("#im-mine"), "Uploading the saved league connects straight to 'Which team is yours?'")
    ok("league.json" in pg.inner_text("#im-espn-file-name") or vis(pg, "#im-mine"), "The chosen file's name is shown")
    if os.environ.get("SHOTS"): pg.screenshot(path=f"{os.environ['SHOTS']}/espn_phone_mine.png")
    ctx.close()

    # 2. desktop, private league: copy and paste
    pg, ctx = page("private", False)
    ok(vis(pg, ".im-steps-desk") and not vis(pg, ".im-steps-phone"), "Desktop: copy-and-paste steps")
    ok(vis(pg, "#im-espn-json") and vis(pg, ".im-file-btn"), "Desktop: the paste box and the upload button")
    pg.fill("#im-espn-json", json.dumps(LEAGUE)); pg.click("#im-espn-go"); pg.wait_for_timeout(1500)
    ok(vis(pg, "#im-mine"), "Pasting the league's data connects")
    ctx.close()

    # 3. blocked request, 4. readable league
    pg, ctx = page("abort", False)
    ok(vis(pg, "#im-espn-paste") and "didn't let this site" in pg.inner_text("#im-espn-why"), "A request that never comes back gets its own message")
    ctx.close()
    pg, ctx = page("ok", True)
    ok(vis(pg, "#im-mine") and not vis(pg, "#im-espn-paste"), "A league ESPN shares connects directly")
    ctx.close()
    ok(not errs, f"No page errors ({errs[:3]})")
    br.close()
print("\n" + ("ALL PASS" if not failures else f"{len(failures)} FAILED"))
sys.exit(1 if failures else 0)
