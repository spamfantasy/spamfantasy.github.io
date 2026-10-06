"""Boards check (Oct 8): Alan's and Steven's rankings are separate boards; the SPAM board is their average.

- Three tabs (SPAM default), SPAM is read-only, personal boards say whose board you're editing.
- Editing Alan's board changes only Alan's columns; Steven's board doesn't move.
- SPAM order = (Alan rank + Steven rank) / 2, ties to the better of the two ranks; SPAM tiers are the averaged tiers;
  a value typed on one board averages with the other board's value.
- The disagreement line ("Alan WR5 · Steven WR19") on the SPAM board.
- Saved edits survive a reload; old-style (SPAM-board) browser edits carry onto both boards.
- Publishing (GitHub mocked) writes only the personal columns plus SPAM columns rebuilt from the merged boards.

Run from the repo root:  python3 tests/boards_check.py   (CHROMIUM=/path/to/chromium if needed)
"""
import base64, csv, functools, http.server, io, json, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT); h.log_message = lambda *a: None
srv = socketserver.TCPServer(("127.0.0.1", 0), h); threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/#rankings"
SRC = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

def expected_order(B):
    """SPAM order from the two boards: average rank, then the better rank, then the current SPAM rank"""
    a, s, sp = B["alan"], B["steven"], B["spam"]
    out = lambda sid: str(a[sid][2]) == "99" and str(s[sid][2]) == "99"
    ids = [k for k in a if k in s and a[k][0] is not None]
    return sorted(ids, key=lambda k: (out(k), (a[k][0] + s[k][0]) / 2, min(a[k][0], s[k][0]), sp[k][0]))

ROWS = """() => [...document.querySelectorAll('#rank-body tr.player')].map(tr => ({ id: tr.dataset.id, name: tr.querySelector('.pl-name').textContent.trim(),
  split: (tr.querySelector('.bd-split') || {}).textContent || '' }))"""
with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw); errs = []
    pg = br.new_page(viewport={"width": 1440, "height": 1000})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.app)/.*"), lambda r: r.abort())
    # GitHub mock: the repo's index.html as the "latest" file, capture what gets published
    puts = []
    def github(route):
        u, m = route.request.url, route.request.method
        if m == "PUT":
            puts.append((u, json.loads(route.request.post_data))); return route.fulfill(status=200, content_type="application/json", body='{"content":{}}')
        if u.endswith("/user"): return route.fulfill(status=200, content_type="application/json", body='{"login":"tester"}')
        if "/contents/index.html" in u: return route.fulfill(status=200, content_type="application/json", body=json.dumps({"sha": "x", "content": base64.b64encode(SRC.encode()).decode()}))
        if "/contents/" in u: return route.fulfill(status=404, content_type="application/json", body='{"message":"Not Found"}')
        return route.fulfill(status=200, content_type="application/json", body='{"permissions":{"push":true}}')
    pg.route("https://api.github.com/**", github)
    pg.add_init_script("if (!sessionStorage.getItem('init')) { sessionStorage.setItem('init', '1'); localStorage.clear(); }")
    pg.goto(URL); pg.wait_for_timeout(4500)

    # 1. tabs, SPAM default and read-only
    tabs = [t.strip() for t in pg.locator("#rk-boards .rkb-tab").all_inner_texts()]
    ok([t.split("\n")[0] for t in tabs] == ["SPAM", "Alan", "Steven"] and pg.get_attribute("[data-board=spam]", "aria-selected") == "true", f"Tabs SPAM | Alan | Steven, SPAM selected: {tabs}")
    ok(pg.locator("#rank-body .handle").count() == 0 and pg.locator("#rank-body .num-btn").count() == 0 and pg.locator("#rkb-banner").is_hidden(), "SPAM board is read-only (no drag handles, no editable values, no banner)")
    B0 = pg.evaluate("() => SPM.boards()")
    ok(B0["alan"] == B0["steven"] == B0["spam"], f"All three boards start identical ({len(B0['spam'])} players)")

    # 2. the formula on the example from the request (synthetic CSV)
    head = "player,pos,team,rank,pos_rank,tier,value,proj_ppg,games,proj_score,sleeper_id,source,tier_name," + ",".join(f"{w}_{c}" for w in ("alan", "steven") for c in ("rank", "pos_rank", "tier", "value", "source", "tier_name"))
    def row(n, pos, sid, a, s): return f"{n},{pos},XX,,,,,,0,,{sid},manual,,{a},,1,,manual,,{s},,1,,manual,"
    mini = "\n".join([head, row("Jahmyr Gibbs", "RB", "1", 1, 4), row("Bijan Robinson", "RB", "2", 2, 1), row("Puka Nacua", "WR", "3", 3, 2), row("Some Guy", "WR", "4", 4, 3)])
    res = list(csv.DictReader(io.StringIO(pg.evaluate("csv => SPM.consensusOf(csv)", mini))))
    order = [r["player"] for r in sorted(res, key=lambda r: int(r["rank"]))]
    ok(order[:3] == ["Bijan Robinson", "Jahmyr Gibbs", "Puka Nacua"], f"Example: Bijan 1.5, Gibbs 2.5, Puka 2.5 (tie → Gibbs's better #1) → {order}")

    # 3. Alan's board: banner, editing; a move changes only Alan
    pg.click("#rk-boards [data-board=alan]"); pg.wait_for_timeout(400)
    ban = pg.inner_text("#rkb-banner")
    ok("Alan's rankings" in ban and "only Alan's board" in ban and pg.locator("#rank-body .handle").count() > 50, f"Alan's tab says whose board it is and is editable: {ban!r}")
    ok("Alan's board" in pg.inner_text("#eb-hint"), "Editor bar names Alan's board")
    pg.click("#pos-chips button:has-text('WR')"); pg.wait_for_timeout(300)
    wr = pg.evaluate(ROWS); mover = wr[4]
    for _ in range(14):
        pg.locator(f'#rank-body tr.player[data-id="{mover["id"]}"] .arrow[data-dir="1"]').click(force=True); pg.wait_for_timeout(120)
    B1 = pg.evaluate("() => SPM.boards()")
    moved = [k for k in B1["alan"] if B1["alan"][k][:2] != B0["alan"][k][:2]]
    ok(len(moved) > 1 and B1["steven"] == B0["steven"], f"Moving {mover['name']} WR5 → WR19 on Alan's board moves {len(moved)} Alan ranks; Steven's board unchanged")
    exp = expected_order(B1); got = sorted(B1["spam"], key=lambda k: B1["spam"][k][0])
    ok(exp == got, "SPAM order = average of Alan's and Steven's overall ranks (ties: better rank, then previous SPAM rank)")
    msid = next(k for k in B1["alan"] if B1["alan"][k][1] == 19 and B0["alan"][k][1] == 5)
    ta, ts, tsp = int(B1["alan"][msid][2]), int(B1["steven"][msid][2]), int(B1["spam"][msid][2])
    ok(tsp >= round((ta + ts) / 2 - 0.01) and tsp >= ts, f"SPAM tier for {mover['name']}: Alan T{ta}, Steven T{ts} → SPAM T{tsp} (average, kept in order)")
    # SPAM tiers never go back up the ladder down a position's SPAM order (tag tiers aside)
    mono = True
    for pos in ("QB", "RB", "WR", "TE"):
        seq = [int(v[2]) for k, v in sorted(B1["spam"].items(), key=lambda kv: kv[1][0]) if v[4] == pos and v[2] not in ("", "None") and int(v[2]) < 90]
        mono = mono and all(seq[i] >= seq[i - 1] for i in range(1, len(seq)))
    ok(mono, "SPAM tiers stay in ladder order down every position")
    # 4. disagreement line on the SPAM WR tab
    pg.click("#rk-boards [data-board=spam]"); pg.wait_for_timeout(300)
    pg.click("#pos-chips button:has-text('WR')"); pg.wait_for_timeout(300)
    rows = pg.evaluate(ROWS); me = next(r for r in rows if r["name"] == mover["name"])
    ok(me["split"] == "Alan WR19 · Steven WR5", f"SPAM shows the disagreement: {me['split']!r}")
    ok(sum(1 for r in rows if r["split"]) <= 3, f"Only players the boards really disagree on get the line ({sum(1 for r in rows if r['split'])})")
    # 5. a value typed on Steven's board averages with Alan's value
    pg.click("#rk-boards [data-board=steven]"); pg.wait_for_timeout(300)
    pg.click("#pos-chips button:has-text('All')"); pg.wait_for_timeout(300)
    rows = pg.evaluate(ROWS); tgt = rows[60]
    tsid = next(k for k, v in B1["steven"].items() if v[0] == 61)
    pg.locator(f'#rank-body tr.player[data-id="{tgt["id"]}"] .num-btn').click(); pg.wait_for_timeout(200)
    typed = B1["steven"][tsid][3] + 150
    pg.fill(".val-input", str(typed)); pg.press(".val-input", "Enter"); pg.wait_for_timeout(600)
    B2 = pg.evaluate("() => SPM.boards()")
    av = round((B2["alan"][tsid][3] + typed) / 2)
    ok(B2["steven"][tsid][3] == typed and abs(B2["spam"][tsid][3] - av) <= 1 and B2["alan"] == B1["alan"], f"Steven types {typed} for {tgt['name']}: SPAM value {B2['spam'][tsid][3]} = average with Alan's {B2['alan'][tsid][3]}; Alan's board unchanged")
    # 6. save in this browser (no token) and reload
    pg.click("#eb-save"); pg.wait_for_timeout(800)
    pg.reload(); pg.wait_for_timeout(4500)
    B3 = pg.evaluate("() => SPM.boards()")
    ok(B3["alan"][msid][1] == 19 and B3["steven"][tsid][3] == typed and B3["spam"] == B2["spam"], "Saved edits come back after a reload, SPAM rebuilt the same")
    ok(pg.get_attribute("[data-board=spam]", "aria-selected") == "true", "SPAM is the tab after a reload")
    # 7. publish (GitHub mocked)
    pg.evaluate("() => localStorage.setItem('spm_editor_token', 'test-token')")
    pg.reload(); pg.wait_for_timeout(4500)
    pg.click("#rk-boards [data-board=alan]"); pg.wait_for_timeout(300)
    pg.click("#eb-publish"); pg.wait_for_timeout(2500)
    idx = [b for u, b in puts if u.endswith("/contents/index.html")]
    ok(len(idx) == 1 and "Alan's board" in idx[0]["message"] and "Steven's board" in idx[0]["message"], f"Published index.html: {idx[0]['message'] if idx else 'nothing'}")
    if idx:
        txt = base64.b64decode(idx[0]["content"]).decode()
        pub = re.search(r"const RANKINGS_CSV = `\n(.*?)\n`;", txt, re.S).group(1)
        rows_p = list(csv.DictReader(io.StringIO(pub))); orig = {r["player"]: r for r in csv.DictReader(io.StringIO(re.search(r"const RANKINGS_CSV = `\n(.*?)\n`;", SRC, re.S).group(1)))}
        ranks = sorted(int(r["rank"]) for r in rows_p if r["pos"] != "PICK")
        ok(ranks == list(range(1, len(ranks) + 1)), "Published SPAM ranks run 1..N with no gaps or duplicates")
        ok(pg.evaluate("csv => SPM.consensusOf(csv)", pub) == pub, "Published SPAM columns are exactly the consensus of the published boards")
        st_changed = [r["player"] for r in rows_p if any(r["steven_" + c] != orig[r["player"]]["steven_" + c] for c in ("rank", "pos_rank", "tier", "source"))]
        ok(st_changed == [] and any(r["steven_value"] == str(typed) for r in rows_p), "Steven's columns: only his typed value changed")
        ok(any(r["alan_pos_rank"] == "19" and orig[r["player"]]["alan_pos_rank"] == "5" for r in rows_p), "Alan's columns carry his move")
    # 8. old-style browser edits (SPAM board, before Oct 8) carry onto both boards
    pg.evaluate("""() => { localStorage.removeItem('spm_editor_token'); localStorage.setItem('spm_local_edits', JSON.stringify({ 'jahmyr gibbs|rb': { value: '9000' } })); }""")
    pg.route("https://api.github.com/**", lambda r: r.abort())
    pg.reload(); pg.wait_for_timeout(4500)
    B4 = pg.evaluate("() => SPM.boards()")
    g = next(k for k, v in B4["spam"].items() if k == next(s for s in B0["spam"] if B0["spam"][s][0] == 1))
    ok(B4["alan"][g][3] == 9000 and B4["steven"][g][3] == 9000 and B4["spam"][g][3] == 9000, "An old SPAM-board browser edit applies to both boards")
    ok(not errs, f"No page errors {errs}")
    br.close()
print("\n" + ("All boards checks passed." if not failures else f"{len(failures)} check(s) failed."))
sys.exit(1 if failures else 0)
