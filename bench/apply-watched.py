#!/usr/bin/env python3
"""Apply the watched flags and resume points from bench/seed-plan.json.

Split out from seed-library.py on purpose: the plan is written when the media
tree is generated, but it can only be APPLIED once Kodi has scanned the tree,
which is a different moment and a different process. Re-running this is safe and
idempotent.
"""

import base64
import json
import os
import sys
import urllib.request

URL = os.environ.get("KODI_JSONRPC", "http://localhost:8080/jsonrpc")
USER = os.environ.get("KODI_USER", "kodi")
PASS = os.environ.get("KODI_PASS", "kodi")
AUTH = "Basic " + base64.b64encode(f"{USER}:{PASS}".encode()).decode()
PLAN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed-plan.json")


def J(method, params=None):
    body = json.dumps(
        {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": 1}
    ).encode()
    req = urllib.request.Request(
        URL, body, {"Content-Type": "application/json", "Authorization": AUTH}
    )
    return json.load(urllib.request.urlopen(req, timeout=60))


def main():
    plan = json.load(open(PLAN))
    movies = {
        m["label"]: m["movieid"]
        for m in J("VideoLibrary.GetMovies", {"properties": ["title"]})["result"].get(
            "movies", []
        )
    }
    eps = J(
        "VideoLibrary.GetEpisodes",
        {"properties": ["season", "episode", "showtitle"]},
    )["result"].get("episodes", [])
    epidx = {(e["showtitle"], e["season"], e["episode"]): e["episodeid"] for e in eps}

    counts = dict(mw=0, mi=0, ew=0, ei=0)
    for m in plan["movies"]:
        mid = movies.get(m["title"])
        if not mid:
            continue
        if m["state"] == "watched":
            J(
                "VideoLibrary.SetMovieDetails",
                {"movieid": mid, "playcount": 1, "lastplayed": "2026-07-20 21:14:00"},
            )
            counts["mw"] += 1
        elif m["state"] == "inprogress":
            J(
                "VideoLibrary.SetMovieDetails",
                {
                    "movieid": mid,
                    "playcount": 0,
                    "lastplayed": "2026-07-26 20:02:00",
                    "resume": {"position": m["position"], "total": m["total"]},
                },
            )
            counts["mi"] += 1
    for e in plan["episodes"]:
        eid = epidx.get((e["show"], e["season"], e["episode"]))
        if not eid:
            continue
        if e["state"] == "watched":
            J(
                "VideoLibrary.SetEpisodeDetails",
                {"episodeid": eid, "playcount": 1, "lastplayed": "2026-07-22 20:30:00"},
            )
            counts["ew"] += 1
        elif e["state"] == "inprogress":
            J(
                "VideoLibrary.SetEpisodeDetails",
                {
                    "episodeid": eid,
                    "playcount": 0,
                    "lastplayed": "2026-07-26 21:40:00",
                    "resume": {"position": e["position"], "total": e["total"]},
                },
            )
            counts["ei"] += 1

    print(
        "movies watched={mw} inprogress={mi}; episodes watched={ew} inprogress={ei}".format(
            **counts
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
