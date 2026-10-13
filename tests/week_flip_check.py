"""Current week turns over on Tuesday at 14:00 UTC, the time of the weekly refresh (Steven, Oct 13).

Sleeper's own NFL state still says Week 5 until Wednesday; the site should show Week 6 as current from Tuesday
14:00 UTC. Reuses the mocked Sleeper league from tests/league_hub_check.py. Synthetic leagues only.
- Tue 13:50 UTC: Matchups and Rosters default to Week 5 (the week just played).
- Tue 14:10 UTC: they default to Week 6, "· current" is on Week 6.
- A page opened before 14:00 and left open moves to Week 6 on its next redraw.

Run from the repo root:  python3 tests/week_flip_check.py   (CHROMIUM=/path/to/chromium if needed)
"""
import json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "league_hub_check.py"), encoding="utf-8").read()
exec(compile(src[:src.index("failures = []")].replace("__file__", repr(os.path.join(HERE, "league_hub_check.py"))), "league_hub_mock", "exec"))

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

port = serve()
STATS = json.load(open(os.path.join(ROOT, "data", "stats", "2026.json")))
for rows in STATS["schedule"].values():   # Weeks 1-5 final, Week 6+ not played
    for r in rows:
        if r[0] <= 5 and r[4] is None: r[4], r[5] = 20, 17
        if r[0] >= 6: r[4] = r[5] = None
STATS_BODY = json.dumps(STATS)
last5 = max(r[3] for rows in STATS["schedule"].values() for r in rows if r[0] == 5)
print("Week 5's last game:", last5)

def sleeper5(route):   # Sleeper's state still on Week 5
    if route.request.url.split("?")[0].endswith("/state/nfl"):
        return route.fulfill(status=200, content_type="application/json",
                             body=json.dumps({"season": "2026", "league_season": "2026", "week": 5, "display_week": 5, "season_type": "regular"}))
    return sleeper(route)

with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw); errs = []
    def page(clock):
        pg = br.new_page(viewport={"width": 1440, "height": 1000})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.clock.install(time=clock)
        pg.route("https://api.sleeper.app/**", sleeper5)
        pg.route("**/data/stats/2026.json", lambda r: r.fulfill(status=200, content_type="application/json", body=STATS_BODY))
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.github\.com|api\.sleeper\.com)/.*"), lambda r: r.abort())
        pg.goto(f"http://127.0.0.1:{port}/#rankings"); pg.wait_for_timeout(3500)
        pg.evaluate("() => { const b = document.createElement('button'); b.dataset.act = 'account'; document.getElementById('league-menu').append(b); b.click(); b.remove(); }")
        pg.wait_for_timeout(400)
        pg.fill("#sd-username", "tester"); pg.press("#sd-username", "Enter"); pg.wait_for_timeout(800)
        pg.locator("#sd-leagues [data-league='L1']").click(); pg.wait_for_timeout(1500)
        return pg
    def weeks(pg):
        pg.click("#tab-league"); pg.wait_for_timeout(500)
        pg.locator("[data-lsub='matchups']").first.click(); pg.wait_for_timeout(1500)
        mx = pg.evaluate("() => { const s = document.getElementById('mx-week'); return s ? [Number(s.value), [...s.options].filter(o => o.text.includes('current')).map(o => Number(o.value))] : null; }")
        pg.locator("[data-lsub='rosters']").first.click(); pg.wait_for_timeout(1500)
        ro = pg.evaluate("() => { const s = document.getElementById('ro-week'); return s ? Number(s.value) : null; }")
        return mx, ro

    pg = page("2026-10-13T13:50:00Z")
    mx, ro = weeks(pg)
    ok(mx and mx[0] == 5 and mx[1] == [5], f"Tue 13:50 UTC: Matchups on Week 5, current = Week 5 ({mx})")
    ok(ro == 5, f"Tue 13:50 UTC: Rosters on Week 5 ({ro})")
    # left open past 14:00
    pg.clock.run_for(20 * 60 * 1000); pg.wait_for_timeout(300)
    mx, ro = weeks(pg)
    ok(mx and mx[0] == 6 and mx[1] == [6], f"Same page after 14:00 UTC moves to Week 6 ({mx})")
    ok(ro == 6, f"Same page after 14:00 UTC: Rosters on Week 6 ({ro})")
    pg.close()

    pg = page("2026-10-13T14:10:00Z")
    mx, ro = weeks(pg)
    ok(mx and mx[0] == 6 and mx[1] == [6], f"Tue 14:10 UTC: Matchups on Week 6 although Sleeper still says 5 ({mx})")
    ok(ro == 6, f"Tue 14:10 UTC: Rosters on Week 6 ({ro})")
    ok(pg.evaluate("() => SPM.myLineup ? true : true"), "page alive")
    pg.close()

    pg = page("2026-10-12T22:00:00Z")   # Monday night, before Week 5's last game ends
    mx, ro = weeks(pg)
    ok(mx and mx[0] == 5, f"Monday night: still Week 5 ({mx})")
    pg.close()
    ok(not errs, f"No page errors ({errs[:3]})")
    br.close()
print("\n" + ("ALL PASS" if not failures else f"{len(failures)} FAILED"))
sys.exit(1 if failures else 0)
