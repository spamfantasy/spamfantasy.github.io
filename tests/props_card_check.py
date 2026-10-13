"""Player card props, the player-card tab scroll bar, My Team's info icons / Actual Pos Rk, the card's 2026 Pos Rk and
K / DEF recent form from Sleeper's weekly points (Steven, Oct 13). Synthetic leagues and a synthetic props file only.

Reuses the mocked Sleeper league from tests/league_hub_check.py (its setup code, up to the checks).
Run from the repo root:  python3 tests/props_card_check.py   (CHROMIUM=/path/to/chromium if needed)
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
CLOCK = "2026-10-08T12:00:00Z"   # Thursday morning of Week 5, before any Week 5 game
WEEK = 5
STATS = json.load(open(os.path.join(ROOT, "data", "stats", "2026.json")))
for rws in STATS["schedule"].values():
    for r in rws:
        if r[0] >= WEEK: r[4] = r[5] = None
STATS_BODY = json.dumps(STATS)
plays = {t for t, rws in STATS["schedule"].items() if any(r[0] == WEEK for r in rws)}
pos_of = {r["sleeper_id"]: (r["pos"], r["team"]) for r in rows if r["sleeper_id"]}
def first(pos, skip=()):
    return next(s for s in sids if pos_of[s][0] == pos and pos_of[s][1] in plays and s not in skip)
WR, RB, QB, TE = first("WR"), first("RB"), first("QB"), first("TE")
WR2 = first("WR", {WR})   # no props for him
PROPS = {"updated": "2026-10-07T16:45Z", "week": WEEK, "source": "test", "books": ["book_a", "book_b", "book_c"], "players": {
    WR: {"rec": 5.5, "rec_yd": 62.5, "atd": 0.38}, TE: {"rec": 4.5, "rec_yd": 44.5, "atd": 0.31},
    RB: {"rush_yd": 58.5, "rush_rec_yd": 81.5, "rec": 3.5, "atd": 0.52}, QB: {"pass_yd": 241.5, "pass_td": 1.5}}}

# a kicker on team 1's bench, with Sleeper's own weekly points in every week's matchups
SP = json.load(open(os.path.join(ROOT, "data", "sleeper_players.json")))
played24 = {t for t, rws in STATS["schedule"].items() if {2, 3, 4} <= {r[0] for r in rws}}
KICK = next(s for s, r in SP.items() if len(r) > 2 and r[1] == "K" and r[2] in plays and r[2] in played24)
kteam = SP[KICK][2]
L1["rosters"][0]["players"].append(KICK)
kpts = lambda w: 6.0 + w   # Week 1 = 7.0 ... Week 4 = 10.0
def sleeper2(route):
    path = route.request.url.split("/v1", 1)[-1].split("?")[0]
    m = re.match(r"/league/L1/matchups/(\d+)$", path)
    if m:
        w = int(m.group(1)); body = json.loads(json.dumps(mx_week(L1, w)))
        for e in body:
            if e["roster_id"] == 1 and w < WEEK: e.setdefault("players_points", {})[KICK] = kpts(w)
        return route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
    return sleeper(route)

with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw); errs = []
    pg = br.new_page(viewport={"width": 1440, "height": 1000})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.clock.install(time=CLOCK)
    pg.route("https://api.sleeper.app/**", sleeper2)
    pg.route("**/data/stats/2026.json", lambda r: r.fulfill(status=200, content_type="application/json", body=STATS_BODY))
    pg.route("**/data/props/2026.json", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(PROPS)))
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.github\.com|api\.sleeper\.com)/.*"), lambda r: r.abort())
    pg.goto(f"http://127.0.0.1:{port}/#rankings"); pg.wait_for_timeout(3500)
    pg.evaluate("() => { const b = document.createElement('button'); b.dataset.act = 'account'; document.getElementById('league-menu').append(b); b.click(); b.remove(); }")
    pg.wait_for_timeout(400)
    pg.fill("#sd-username", "tester"); pg.press("#sd-username", "Enter"); pg.wait_for_timeout(800)
    pg.locator("#sd-leagues [data-league='L1']").click(); pg.wait_for_timeout(1500)

    def open_player(sid):
        pg.evaluate("sid => { const a = document.createElement('a'); a.dataset.player = sid; document.body.append(a); a.click(); a.remove(); }", sid)
        pg.wait_for_timeout(1500)
    def props_text():
        return pg.inner_text("#player-body .tw-props") if pg.locator("#player-body .tw-props").count() else ""

    # 1. props in the This week card
    open_player(WR); t = props_text()
    if SHOTS: pg.screenshot(path=f"{SHOTS}/card_props_drawer.png")
    ok("Rec" in t and "5.5" in t and "Rec yds" in t and "62.5" in t and "Anytime TD" in t and "+163" in t and "38%" in t, f"WR props: rec, rec yds, anytime TD (+163 / 38%): {t!r}")
    ok("3 sportsbooks" in t, "Props note names the number of books")
    open_player(RB); t = props_text()
    ok(all(x in t for x in ("Rush yds", "58.5", "Rush + rec yds", "81.5", "Rec", "3.5", "Anytime TD", "−108")), f"RB props: rush, rush + rec, rec, anytime TD: {t!r}")
    open_player(QB); t = props_text()
    ok("Pass yds" in t and "241.5" in t and "Pass TD" in t and "1.5" in t and "Anytime" not in t, f"QB props: pass yds and pass TD only: {t!r}")
    open_player(TE); t = props_text()
    ok("Rec yds" in t and "44.5" in t, f"TE props: {t!r}")
    open_player(WR2); t = props_text()
    ok("No props posted yet" in t, f"A player without lines: 'No props posted yet' ({t!r})")

    # 2. 2026 Pos Rk beside 2026 PPG in the card header
    stats = pg.inner_text("#player-body .pm-stats")
    ok(re.search(r"2026 Pos Rk\s*WR\d+", stats, re.I), f"Card header shows 2026 Pos Rk: {stats.replace(chr(10), ' | ')!r}")

    # 3. tab scroll bar: open the last tab, then drag the thumb back to the left and reach Overview
    pg.set_viewport_size({"width": 900, "height": 900}); pg.wait_for_timeout(500)
    open_player(WR)
    pg.locator("#player-body [data-pp-tab=practice]").first.click(); pg.wait_for_timeout(600)
    if SHOTS: pg.screenshot(path=f"{SHOTS}/card_tabs_scrolled.png")
    bar = "#player-body .pp-tabs"
    sl = pg.evaluate(f"() => document.querySelector('{bar}').scrollLeft")
    vis = pg.evaluate("() => !document.querySelector('#player-body .pp-track').classList.contains('off')")
    ok(vis, "The tab scroll bar shows when the tabs don't fit")
    ok(sl > 0, f"Opening the last tab scrolls the tab row ({sl}px)")
    tb = pg.locator("#player-body .pp-track").bounding_box(); th = pg.locator("#player-body .pp-thumb").bounding_box()
    pg.mouse.move(th["x"] + th["width"] / 2, th["y"] + 3); pg.mouse.down(); pg.mouse.move(tb["x"] - 40, tb["y"] + 3, steps=6); pg.mouse.up(); pg.wait_for_timeout(300)
    sl2 = pg.evaluate(f"() => document.querySelector('{bar}').scrollLeft")
    ov = pg.evaluate(f"() => {{ const b = document.querySelector('{bar}'), o = b.querySelector('[data-pp-tab=overview]'); const r = o.getBoundingClientRect(), R = b.getBoundingClientRect(); return r.left >= R.left - 1 && r.right <= R.right + 1; }}")
    ok(sl2 == 0 and ov, f"Dragging the thumb left brings Overview back into view (scrollLeft {sl2})")
    pg.locator(f"{bar} [data-pp-tab=overview]").click(); pg.wait_for_timeout(500)
    ok(pg.locator(f"{bar} [data-pp-tab=overview][aria-pressed=true]").count() == 1, "Overview opens from the tab row")
    # mouse wheel over the tabs scrolls them sideways
    pg.locator(bar).hover(); pg.mouse.wheel(0, 400); pg.wait_for_timeout(300)
    ok(pg.evaluate(f"() => document.querySelector('{bar}').scrollLeft") > 0, "The mouse wheel over the tabs scrolls them sideways")
    # clicking the track's right end jumps there
    pg.mouse.click(tb["x"] + tb["width"] - 2, tb["y"] + 3); pg.wait_for_timeout(300)
    mx = pg.evaluate(f"() => {{ const b = document.querySelector('{bar}'); return [b.scrollLeft, b.scrollWidth - b.clientWidth]; }}")
    ok(abs(mx[0] - mx[1]) <= 2, f"Clicking the right end of the track scrolls to the last tabs {mx}")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    pg.set_viewport_size({"width": 1440, "height": 1000}); pg.wait_for_timeout(300)

    # 4. My Team: info icons, Actual Pos Rk column
    pg.click("#tab-myteam"); pg.wait_for_timeout(2500)
    heads = pg.eval_on_selector_all("#panel-myteam .mt-table thead th", "e => e.map(x => x.textContent.trim())")
    ok(any(h.startswith("Actual Pos Rk") for h in heads), f"My Team has an Actual Pos Rk column: {heads}")
    ai = [h.split(" ")[0] for h in heads]
    ok(heads.index(next(h for h in heads if h.startswith("Actual"))) == heads.index(next(h for h in heads if h.startswith("Recent form"))) + 1
       and heads.index(next(h for h in heads if h.startswith("Value"))) == heads.index(next(h for h in heads if h.startswith("Actual"))) + 1, "Actual Pos Rk sits between Recent form and Value")
    infos = pg.eval_on_selector_all("#panel-myteam .mt-table thead th .info", "e => e.map(x => x.dataset.info)")
    ok(len(infos) >= 3 and any("SPAM Consensus" in x and "position rank" in x for x in infos) and any("overall rank" in x for x in infos), f"Pos / Rk info icons explain the SPAM Consensus ranks ({len(infos)} icons)")
    pos_info = pg.locator("#panel-myteam .mt-table thead th.pos-col .info")
    pos_info.click(); pg.wait_for_timeout(200)
    ok(pg.evaluate("() => document.activeElement && document.activeElement.classList.contains('info')"), "Clicking the Pos info icon focuses it (shows the explanation)")
    if SHOTS: pg.screenshot(path=f"{SHOTS}/myteam_actual.png", full_page=False)
    cells = pg.eval_on_selector_all("#panel-myteam .mt-row td.mt-act", "e => e.map(x => x.textContent.trim())")
    ranked = [c for c in cells if re.fullmatch(r"(QB|RB|WR|TE)\d+", c)]
    ok(len(ranked) >= 8, f"Actual Pos Rk cells show position ranks ({len(ranked)} of {len(cells)}: {cells[:6]})")
    # the same rank as the card header for one rostered player
    sid1 = L1["rosters"][0]["players"][0]
    row_rank = pg.evaluate("sid => { for (const tr of document.querySelectorAll('#panel-myteam .mt-row')) { if (tr.querySelector(`[data-player='${sid}']`)) return tr.querySelector('td.mt-act').textContent.trim(); } return null; }", sid1)
    open_player(sid1)
    card = pg.inner_text("#player-body .pm-stats")
    ok(row_rank and row_rank in card, f"The card's 2026 Pos Rk matches My Team ({row_rank})")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)

    # 5. kicker: recent form from Sleeper's weekly points, not OUT
    pg.wait_for_timeout(2000)
    krow = pg.evaluate("sid => { for (const tr of document.querySelectorAll('#panel-myteam .mt-row')) { if (tr.innerHTML.includes(sid)) return tr.querySelector('td.mt-l3').innerText; } return null; }", KICK)
    exp = [f"{kpts(w):.1f}" for w in (2, 3, 4)]
    ok(krow is not None and all(x in krow for x in exp) and "OUT" not in krow, f"Kicker recent form = Sleeper's weekly points {exp}: {krow!r}")
    ok(not errs, f"No page errors {errs[:3]}")
    br.close()

print("\n" + ("All props / card / My Team checks passed." if not failures else f"{len(failures)} check(s) failed."))
sys.exit(1 if failures else 0)
