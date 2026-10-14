"""Trade Finder: "Any players" on My Team and a third package player (Steven, Oct 14). Synthetic leagues only.

Reuses the mocked Sleeper league from tests/league_hub_check.py.
- My Team's player dropdown starts with "Any players"; picking it hides the package pickers, locks From team to you
  and turns off 3-team ideas.
- With Position wanted = RB, every idea gets an RB as the main piece from another team, gives only your players
  (1-3 of them), stays within the value difference, and mixes shapes (incl. packages from your side).
- Against one team: every idea is with that team.
- A third player picker appears once a second is chosen; a 3-player package gives exactly those three, and only
  All packages is enabled.

Run from the repo root:  python3 tests/finder_any_check.py   (CHROMIUM=/path/to/chromium if needed)
"""
import json, os, re, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "league_hub_check.py"), encoding="utf-8").read()
exec(compile(src[:src.index("failures = []")].replace("__file__", repr(os.path.join(HERE, "league_hub_check.py"))), "league_hub_mock", "exec"))

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

port = serve()
with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw); errs = []
    pg = br.new_page(viewport={"width": 1440, "height": 1000})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("https://api.sleeper.app/**", sleeper)
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.github\.com|api\.sleeper\.com)/.*"), lambda r: r.abort())
    pg.goto(f"http://127.0.0.1:{port}/#rankings"); pg.wait_for_timeout(3500)
    pg.evaluate("() => { const b = document.createElement('button'); b.dataset.act = 'account'; document.getElementById('league-menu').append(b); b.click(); b.remove(); }")
    pg.wait_for_timeout(400)
    pg.fill("#sd-username", "tester"); pg.press("#sd-username", "Enter"); pg.wait_for_timeout(800)
    pg.locator("#sd-leagues [data-league='L1']").click(); pg.wait_for_timeout(1500)
    pg.click("#tab-finder"); pg.wait_for_timeout(1200)

    def setsel(id_, v):
        pg.evaluate(f"() => {{ const s = document.getElementById('{id_}'); s.value = {json.dumps(v)}; s.dispatchEvent(new Event('change', {{bubbles:true}})); }}")
        pg.wait_for_timeout(300)
    def ideas():   # from the page state: [team rosterId, give [(sid, pos, mine)], get [(sid, pos, owner rosterId)], more]
        return pg.evaluate("""() => { const T = window.SPM && SPM._tf ? SPM._tf() : null; return T; }""")

    opts = pg.evaluate("() => [...document.getElementById('tf-player').options].map(o => [o.value, o.text])")
    ok(opts[0][0] == "*any" and opts[0][1].lower().startswith("any players"), f"My Team dropdown starts with Any players ({opts[0]})")
    my_sids = set(v for v, _ in opts[1:])
    setsel("tf-player", "*any")
    ok(pg.locator("#tf-player2").count() == 0, "Any players hides the package pickers")
    ok(pg.evaluate("() => document.getElementById('tf-from').disabled") and pg.evaluate("() => document.getElementById('tf-three').disabled"), "From team is locked to you and 3-team ideas are off")
    t0 = time.time(); setsel("tf-pos", "RB"); dt = time.time() - t0
    print(f"  search took {dt:.1f}s")
    ok(dt < 8, f"Any players search finishes quickly ({dt:.1f}s)")
    ok("any of your players" in pg.inner_text("#tf-lead").lower(), f"Lead names Any of your players: {pg.inner_text('#tf-lead')[:120]!r}")
    data = pg.evaluate("""() => SPM.finderIdeas()""")
    ok(len(data) >= 5, f"Any players finds plenty of RB ideas ({len(data)})")
    good_main = all(d["get"][0]["pos"] == "RB" and d["get"][0]["owner"] != d["s"] for d in data)
    ok(good_main, "Every idea's main incoming piece is an RB from another team")
    ok(all(all(g["sid"] in my_sids for g in d["give"]) and 1 <= len(d["give"]) <= 3 for d in data), "Every idea gives only your players, 1-3 of them")
    ok(all(d["more"] <= 10.05 for d in data), "Every idea is within the 10% value difference")
    shapes = {f"{len(d['give'])}-for-{len(d['get'])}" for d in data}
    ok(len(shapes) >= 2 and any(len(d["give"]) >= 2 for d in data), f"Mixes shapes, incl. packages from your side ({sorted(shapes)})")
    ok(len({tuple(sorted(g["sid"] for g in d["give"])) for d in data}) >= 3, "Uses different combinations of your players")
    cards = pg.locator(".tf-card:not(.tf3)").count()
    ok(cards == min(10, len(data)), f"First 10 ideas show as cards ({cards})")
    ag = pg.evaluate("() => [...document.getElementById('tf-against').options].map(o => o.value).filter(v => v !== 'ANY')")[0]
    setsel("tf-against", ag)
    data2 = pg.evaluate("() => SPM.finderIdeas()")
    ok(data2 and all(str(d["team"]) == str(ag) for d in data2), f"Against one team: every idea is with that team ({len(data2)})")
    setsel("tf-against", "ANY")
    pg.click("#tf-size [data-size='21']"); pg.wait_for_timeout(300)
    d21 = pg.evaluate("() => SPM.finderIdeas()")
    ok(d21 and all(len(d["give"]) == 2 and len(d["get"]) == 1 for d in d21), f"Trade type 2-for-1 with Any players: only 2-for-1 ideas ({len(d21)})")
    pg.click("#tf-size [data-size='all']"); pg.wait_for_timeout(300)
    setsel("tf-pos", "ANY")

    # third package player
    first = [v for v, _ in opts[1:]]
    setsel("tf-player", first[3])
    ok(pg.locator("#tf-player2").count() == 1 and pg.locator("#tf-player3").count() == 0, "A second picker, no third until a second is chosen")
    setsel("tf-player2", first[4])
    ok(pg.locator("#tf-player3").count() == 1, "Choosing a second player shows the third picker")
    third = pg.evaluate("() => [...document.getElementById('tf-player3').options].map(o => o.value).filter(Boolean)")
    ok(first[4] not in third and first[3] not in third, "The third picker leaves out the two already chosen")
    setsel("tf-player3", first[5])
    pkg = {first[3], first[4], first[5]}
    data3 = pg.evaluate("() => SPM.finderIdeas()")
    ok(data3 and all({g["sid"] for g in d["give"]} == pkg for d in data3), f"Every idea gives exactly the three players ({len(data3)} ideas)")
    en = pg.evaluate("() => [...document.querySelectorAll('#tf-size button')].filter(b => !b.disabled).map(b => b.dataset.size)")
    ok(en == ["all"], f"Only All packages is enabled for a 3-player package ({en})")
    ok(len(pg.locator("#tf-lead .tf-amp").all()) == 2, "The lead shows the three players")
    setsel("tf-player2", "")
    ok(pg.locator("#tf-player3").count() == 0, "Clearing the second player removes the third")
    ok(not errs, f"No page errors ({errs[:3]})")
    br.close()
print("\n" + ("ALL PASS" if not failures else f"{len(failures)} FAILED"))
sys.exit(1 if failures else 0)
