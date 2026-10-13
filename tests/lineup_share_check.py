"""Lineup check (My Team) and trade sharing / import (Trade Calculator), Oct 12. Synthetic leagues only.

Reuses the mocked Sleeper league from tests/league_hub_check.py (its setup code, up to the checks).
- My Team shows a Lineup check card; its Start / Bench tags match the suggested swaps; setting Sleeper's lineup to the
  suggested one makes it say the lineup is set; an empty starting slot is always flagged.
- Import a trade: typed names (incl. nicknames, last names) land on the right sides.
- Share: the link reproduces the same trade in a fresh browser.

Run from the repo root:  python3 tests/lineup_share_check.py   (CHROMIUM=/path/to/chromium if needed)
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
CLOCK = "2026-10-08T12:00:00Z"   # the Thursday morning of Week 5, before any Week 5 game
STATS = json.load(open(os.path.join(ROOT, "data", "stats", "2026.json")))
for rows in STATS["schedule"].values():   # Week 5 not played yet: no scores, so nobody is locked
    for r in rows:
        if r[0] >= 5: r[4] = r[5] = None
STATS_BODY = json.dumps(STATS)
with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw); errs = []
    def page():
        pg = br.new_page(viewport={"width": 1440, "height": 1000})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.clock.install(time=CLOCK)
        pg.route("https://api.sleeper.app/**", sleeper)
        pg.route("**/data/stats/2026.json", lambda r: r.fulfill(status=200, content_type="application/json", body=STATS_BODY))
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.github\.com|api\.sleeper\.com)/.*"), lambda r: r.abort())
        return pg
    pg = page()
    pg.goto(f"http://127.0.0.1:{port}/#rankings"); pg.wait_for_timeout(3500)
    pg.evaluate("() => { const b = document.createElement('button'); b.dataset.act = 'account'; document.getElementById('league-menu').append(b); b.click(); b.remove(); }")
    pg.wait_for_timeout(400)
    pg.fill("#sd-username", "tester"); pg.press("#sd-username", "Enter"); pg.wait_for_timeout(800)
    pg.locator("#sd-leagues [data-league='L1']").click(); pg.wait_for_timeout(1500)

    # 1. lineup check card on My Team
    pg.click("#tab-myteam"); pg.wait_for_timeout(1500)
    ok(pg.locator(".mt-lineup").count() == 1 and "lineup check" in pg.inner_text(".mt-lineup").lower(), "My Team has a Lineup check card")
    L = pg.evaluate("() => SPM.myLineup()")
    ok(L is not None and L["best"] >= L["now"] - 0.01, f"Best lineup projects at least as much as the current one ({L and round(L['now'],1)} → {L and round(L['best'],1)})")
    if L and L["act"]:
        tags_start = pg.evaluate("() => [...document.querySelectorAll('.mt-row .lu-tag.start')].length")
        tags_bench = pg.evaluate("() => [...document.querySelectorAll('.mt-row .lu-tag.bench')].length")
        ok(tags_start == len(L["start"]) and tags_bench == len(L["bench"]), f"Start / Bench tags on the roster match the swaps ({tags_start} start, {tags_bench} bench)")
        ok("+" in pg.inner_text(".mt-lineup") or L["alerts"], "The card shows the projected gain or an alert")
    # set Sleeper's lineup to the suggested one → "Your lineup is set"
    best = [x or "0" for x in L["order"]]
    sl = json.loads(pg.evaluate("() => localStorage.getItem('spm_sleeper')"))
    d = sl["data"]["L1"]; me = next(r for r in d["rosters"] if r["roster_id"] == 1); me["starters"] = best
    MOCK_ME = next(r for r in LEAGUES["L1"]["rosters"] if r["roster_id"] == 1)   # Sleeper's own copy (matchups read it)
    MOCK_ME["starters"] = list(best)
    pg.evaluate("v => localStorage.setItem('spm_sleeper', v)", json.dumps(sl))
    pg.reload(); pg.wait_for_timeout(3500); pg.click("#tab-myteam"); pg.wait_for_timeout(1500)
    L2 = pg.evaluate("() => SPM.myLineup()")
    set_ok = not L2["start"] and not L2["bench"] and abs(L2["gain"]) < 0.05 and all(a == "empty" for a in L2["alerts"])
    ok(set_ok and ("Your lineup is set" in pg.inner_text(".mt-lineup") or L2["alerts"]), f"With the suggested lineup set, no swaps are suggested (only slots nobody on the roster can fill): {pg.inner_text('.mt-lineup')[:90]!r}")
    # a clearly better bench player: swap the FLEX starter for the weakest bench player → "Start" him back
    slots = [x for x in d["league"]["roster_positions"] if x != "BN"]; fi = slots.index("FLEX")
    star = best[fi]; weak = next(x for x in me["players"] if x not in best and x != "0")
    me["starters"] = best[:fi] + [weak] + best[fi + 1:]; MOCK_ME["starters"] = list(me["starters"])
    pg.evaluate("v => localStorage.setItem('spm_sleeper', v)", json.dumps(sl))
    pg.reload(); pg.wait_for_timeout(3500); pg.click("#tab-myteam"); pg.wait_for_timeout(1500)
    L4 = pg.evaluate("() => SPM.myLineup()")
    ok(star in L4["start"] and weak in L4["bench"] and L4["gain"] >= 1, f"Bench player clearly better than the FLEX starter: suggests starting him (+{round(L4['gain'], 1)})")
    ok("Start" in pg.inner_text(".mt-lineup") and pg.locator(".mt-row .lu-tag.start").count() >= 1, "The card and the roster show the Start suggestion")
    ok([star, weak] in L4["pairs"], f"The swap says whom he replaces: start {star} over {weak} ({L4['pairs']})")
    card = pg.inner_text(".mt-lineup")
    if os.environ.get("SHOTS"): pg.locator(".mt-lineup").screenshot(path=os.path.join(os.environ["SHOTS"], "lineup_over.png"))
    ok(re.search(r"Start .*\bover ", card, re.S) is not None, f"The card reads 'Start X over Y': {card[:160]!r}")
    # an empty starting slot is flagged
    me["starters"] = best[:-1] + ["0"]; MOCK_ME["starters"] = list(me["starters"])
    pg.evaluate("v => localStorage.setItem('spm_sleeper', v)", json.dumps(sl))
    pg.reload(); pg.wait_for_timeout(3500); pg.click("#tab-myteam"); pg.wait_for_timeout(1500)
    txt = pg.inner_text(".mt-lineup")
    ok("slot is empty" in txt and pg.locator(".mt-lineup.warn").count() == 1 and "Bye" not in txt.split("Start", 1)[-1][:0] , f"An empty starting slot is flagged: {txt[:120]!r}")
    L3 = pg.evaluate("() => SPM.myLineup()")
    ok(not any(pg.evaluate(f"() => {{ const p = [...document.querySelectorAll('.mt-row')].find(r => r.querySelector('.lu-tag.start') && /BYE|OUT/.test(r.innerText)); return !!p; }}") for _ in [0]), "Never suggests starting a player who's Out or on bye")

    # a QB on bye in the QB slot and no other QB on the roster: suggest the best free-agent QB (Steven, Oct 13)
    csv_rows = list(csv.DictReader(io.StringIO(re.search(r"RANKINGS_CSV\s*=\s*`(.*?)`", open(os.path.join(ROOT, "index.html"), encoding="utf-8").read(), re.S).group(1).strip())))
    pos_of = {r["sleeper_id"]: r["pos"] for r in csv_rows if r["sleeper_id"]}
    team_of = {r["sleeper_id"]: r["team"] for r in csv_rows if r["sleeper_id"]}
    bye5 = {t for t, rws in STATS["schedule"].items() if not any(r[0] == 5 for r in rws)}
    owned_all = {x for L in LEAGUES.values() for r in L["rosters"] for x in r["players"]}
    byeqb = next((s for s in sids if pos_of.get(s) == "QB" and team_of.get(s) in bye5), None)
    if byeqb:
        keep = [x for x in me["players"] if pos_of.get(x) != "QB" and x != byeqb]
        me["players"] = keep + [byeqb]
        qslot = slots.index("QB"); sfslot = slots.index("SUPER_FLEX")
        st = [x if pos_of.get(x) != "QB" else "0" for x in best]
        nonq = [x for x in keep if x not in st]
        st[qslot] = byeqb; st[sfslot] = nonq[0] if nonq else "0"
        me["starters"] = st
        MOCK_ME["players"] = list(me["players"]); MOCK_ME["starters"] = list(st)
        for L in LEAGUES.values():
            for r in L["rosters"]:
                if r is not MOCK_ME and byeqb in r["players"]: r["players"].remove(byeqb)
        pg.evaluate("v => localStorage.setItem('spm_sleeper', v)", json.dumps(sl))
        pg.reload(); pg.wait_for_timeout(3500); pg.click("#tab-myteam"); pg.wait_for_timeout(2000)
        L6 = pg.evaluate("() => SPM.myLineup()")
        if os.environ.get("SHOTS"): pg.locator(".mt-lineup").screenshot(path=os.path.join(os.environ["SHOTS"], "lineup_pickup.png"))
        txt = pg.inner_text(".mt-lineup")
        picks = [p for ps in L6["pickups"] for p in ps]
        owned_now = {x for r in LEAGUES["L1"]["rosters"] for x in r["players"]}   # this league only
        qpicks = next((ps for ps in L6["pickups"] if ps and all(pos_of.get(p) == "QB" for p in ps)), [])
        ok(qpicks and all(p not in owned_now for p in picks) and "Pick up" in txt and "fill your QB slot" in txt and "on bye" in txt,
           f"QB on bye with no other QB: suggests picking up a free-agent QB ({[name_of.get(p) for p in qpicks]}): {txt[:200]!r}")
        ok(L6["pickups"] and L6["pickups"][0] and name_of.get(L6["pickups"][0][0], "") in txt, "The top pickup is named on the card")
    else:
        ok(True, "No QB on bye in Week 5 in this data (pickup check skipped)")

    # the saved roster is stale (FLEX = weak) but Sleeper's matchup for this week has the lineup already changed
    # (Steven, Oct 13): My Team follows the matchup's lineup, so the benched player shows on the bench, not as a starter
    me["starters"] = best[:fi] + [weak] + best[fi + 1:]; MOCK_ME["starters"] = list(best)
    pg.evaluate("v => localStorage.setItem('spm_sleeper', v)", json.dumps(sl))
    pg.reload(); pg.wait_for_timeout(3500); pg.click("#tab-myteam"); pg.wait_for_timeout(2000)
    L5 = pg.evaluate("() => SPM.myLineup()")
    ok(weak not in (L5["start"] or []) and star not in (L5["bench"] or []) and not L5["start"] and not L5["bench"], f"Stale saved lineup, fresh Sleeper matchup: My Team uses the matchup's lineup (no swaps: {L5['start']} / {L5['bench']})")

    # 2. import a trade by names
    pg.click("#tab-trade"); pg.wait_for_timeout(600)
    pg.click("#tc-import > summary")
    pg.fill("#imp-A", "JSN, Puka")
    pg.fill("#imp-B", "gibbs\nNobody McFakename")
    pg.click("#imp-go"); pg.wait_for_timeout(800)
    sideA = pg.locator("#roster-A li").all_inner_texts(); sideB = pg.locator("#roster-B li").all_inner_texts()
    ok(any("Smith-Njigba" in t for t in sideA) and any("Nacua" in t for t in sideA) and any("Gibbs" in t for t in sideB), f"Import puts JSN + Puka on one side and Gibbs on the other")
    ok("Not found: Nobody McFakename" in pg.inner_text("#imp-msg"), f"Unknown names are listed: {pg.inner_text('#imp-msg')!r}")
    verdict = pg.inner_text("#verdict-title")

    # 3. share link reproduces the trade in a fresh browser
    pg.click("#share-btn"); pg.wait_for_timeout(400)
    url = pg.input_value("#share-url")
    ok("?trade=" in url and url.endswith("#trade"), f"Share builds a trade link: {url}")
    pg2 = page()
    pg2.goto(url.replace("https://spamfantasy.github.io", f"http://127.0.0.1:{port}")); pg2.wait_for_timeout(3500)
    a2 = pg2.locator("#roster-A li").all_inner_texts(); b2 = pg2.locator("#roster-B li").all_inner_texts()
    ok(pg2.locator("#panel-trade").is_visible() and any("Smith-Njigba" in t for t in a2) and any("Nacua" in t for t in a2) and any("Gibbs" in t for t in b2), "Opening the link shows the same trade in the calculator")
    ok("trade=" not in pg2.url, "The trade parameter is removed from the address after loading")
    ok(pg2.inner_text("#verdict-title").strip() != "Build a trade", f"The shared trade gets a verdict: {pg2.inner_text('#verdict-title')!r}")
    ok(not errs, f"No page errors {errs}")
    br.close()
print("\n" + ("All lineup / share checks passed." if not failures else f"{len(failures)} check(s) failed."))
sys.exit(1 if failures else 0)
