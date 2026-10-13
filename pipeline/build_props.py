"""This week's NFL player props for the player card (and the projection blend), from The Odds API.

Needs an API key in the ODDS_API_KEY environment variable (a GitHub repository secret, never in the page or the repo).
Without one it does nothing and keeps the last file. Steven, Oct 13: show prop lines in the player card's This week box.

Writes data/props/<season>.json (the contract in CLAUDE.md):
  {"updated": "2026-10-17T16:45Z", "week": 6, "books": ["draftkings", ...], "source": "The Odds API",
   "players": {"<sleeper_id>": {"rec": 5.5, "rec_yd": 62.5, "rush_yd": 48.5, "rush_rec_yd": 71.5,
                                "pass_yd": 241.5, "pass_td": 1.5, "atd": 0.38}}}
Each line is the median across bookmakers of the Over/Under point; atd is the median no-vig probability of an anytime
touchdown (just the implied probability when a book only offers "Yes"). Only QB/RB/WR/TE matched to a Sleeper ID.

Credits (free plan: 500 a month): each game costs one credit per market (7 markets, US books only). To stay inside the
free plan, a run only asks for games that haven't kicked off and kick off within LOOKAHEAD_DAYS, and the workflow runs
it twice a week (Wednesday for Thursday's game, Saturday for the rest). It stops early when the API says fewer than
MIN_LEFT credits remain. Lines from earlier runs in the same week are kept.

Run from the pipeline folder: ODDS_API_KEY=... python build_props.py [days ahead, default 3]
"""
import json, os, re, sys, time, statistics, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

SEASON = 2026
KEY = os.environ.get("ODDS_API_KEY", "").strip()
API = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl"
MARKETS = {   # The Odds API market key -> our field
    "player_receptions": "rec", "player_reception_yds": "rec_yd", "player_rush_yds": "rush_yd",
    "player_rush_reception_yds": "rush_rec_yd", "player_pass_yds": "pass_yd", "player_pass_tds": "pass_td",
    "player_anytime_td": "atd",
}
LOOKAHEAD_DAYS = float(sys.argv[1]) if len(sys.argv) > 1 else 3
MIN_LEFT = 20
OUT = os.path.join("..", "data", "props", f"{SEASON}.json")
TEAMS = {   # full name (as The Odds API writes it) -> our abbreviation
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR", "Chicago Bears": "CHI", "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL", "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX", "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC", "Los Angeles Rams": "LAR", "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN", "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT", "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB", "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}
left = None


def get(path, **params):
    global left
    q = urllib.parse.urlencode({"apiKey": KEY, **params})
    req = urllib.request.Request(f"{API}{path}?{q}", headers={"User-Agent": "SPAM fantasy props (github.com/spamfantasy)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        rem = r.headers.get("x-requests-remaining")
        if rem is not None:
            try: left = float(rem)
            except ValueError: pass
        return json.load(r)


def norm(name):
    n = re.sub(r"[^a-z ]", "", str(name).lower().replace("-", " ").replace(".", ""))
    n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", n)
    return " ".join(n.split())


def implied(price):   # American odds -> probability
    price = float(price)
    return 100 / (price + 100) if price > 0 else -price / (-price + 100)


def main():
    if not KEY:
        print("No ODDS_API_KEY set: player props not refreshed (kept the last file)")
        return
    players = json.load(open(os.path.join("..", "data", "sleeper_players.json")))
    by_name = {}
    for sid, row in players.items():
        if len(row) >= 3 and row[1] in ("QB", "RB", "WR", "TE"):
            by_name.setdefault(norm(row[0]), []).append((sid, row[2]))
    stats = json.load(open(os.path.join("..", "data", "stats", f"{SEASON}.json")))
    sched = stats.get("schedule", {})

    now = datetime.now(timezone.utc)
    events = [e for e in get("/events") if now < datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")) <= now + timedelta(days=LOOKAHEAD_DAYS)]
    if not events:
        print("No games in the next", LOOKAHEAD_DAYS, "days"); return

    def week_of(e):   # the NFL week from our schedule (game date in Eastern time)
        t = datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")) - timedelta(hours=4)
        team = TEAMS.get(e["home_team"])
        for r in sched.get(team, []):
            if r[3] == t.strftime("%Y-%m-%d") or abs((datetime.fromisoformat(r[3]) - t.replace(tzinfo=None)).days) <= 1:
                return r[0]
        return None

    raw, books, weeks = {}, set(), []
    for e in events:
        if left is not None and left < MIN_LEFT + len(MARKETS):
            print(f"Stopping: only {left:.0f} API credits left"); break
        w = week_of(e)
        if w is None: continue
        weeks.append(w)
        try:
            odds = get(f"/events/{e['id']}/odds", regions="us", markets=",".join(MARKETS), oddsFormat="american")
        except Exception as err:
            print("skipped", e.get("home_team"), err); continue
        teams = {TEAMS.get(e["home_team"]), TEAMS.get(e["away_team"])}
        for bk in odds.get("bookmakers", []):
            books.add(bk["key"])
            for mk in bk.get("markets", []):
                field = MARKETS.get(mk["key"])
                if not field: continue
                yes, no = {}, {}
                for o in mk.get("outcomes", []):
                    who = o.get("description") or ""
                    cand = [c for c in by_name.get(norm(who), []) if c[1] in teams] or by_name.get(norm(who), [])
                    if len(cand) != 1: continue
                    sid = cand[0][0]
                    if field == "atd":
                        (yes if o.get("name") == "Yes" else no)[sid] = implied(o["price"])
                    elif o.get("name") == "Over" and o.get("point") is not None:
                        raw.setdefault(sid, {}).setdefault(field, []).append(float(o["point"]))
                for sid, p in yes.items():   # remove the book's margin when it prices both sides
                    q = no.get(sid)
                    raw.setdefault(sid, {}).setdefault("atd", []).append(p / (p + q) if q else p)
        time.sleep(0.5)
    if not weeks:
        print("No games matched the schedule"); return
    week = min(weeks)
    out = {"updated": now.strftime("%Y-%m-%dT%H:%MZ"), "week": week, "source": "The Odds API", "books": sorted(books), "players": {}}
    try:   # keep lines from an earlier run this week (e.g. Wednesday's for Thursday's game)
        old = json.load(open(OUT))
        if old.get("week") == week:
            out["players"].update(old.get("players", {}))
            out["books"] = sorted(set(out["books"]) | set(old.get("books", [])))
    except (OSError, ValueError):
        pass
    for sid, f in raw.items():
        out["players"][sid] = {k: round(statistics.median(v), 3 if k == "atd" else 1) for k, v in f.items() if v}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(f"Wrote {OUT}: week {week}, {len(out['players'])} players, {len(out['books'])} books"
          + (f", {left:.0f} credits left" if left is not None else ""))


if __name__ == "__main__":
    main()
