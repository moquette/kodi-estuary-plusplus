#!/usr/bin/env bash
# Rebuild the synthetic bench library from scratch, end to end.
#
# Idempotent. Safe to re-run any time the library looks wrong. Takes about a
# minute, most of which is waiting for Kodi's scanner.
#
# Order matters and each step exists for a reason, recorded in the clean-bench
# skill (.claude/skills/clean-bench/SKILL.md at the meta root):
#   1. stop Kodi          Kodi caches sources and add-on settings in memory and
#                         will overwrite anything written underneath it
#   2. generate media     posters, fanart, NFOs, stub .mkv files
#   3. register sources   sources.xml gets the two entries; the video DB gets the
#                         matching path rows with content type + metadata.local,
#                         which is the only place Kodi stores "this source is
#                         movies" and there is no JSON-RPC method for it
#   4. start Kodi
#   5. wipe + scan        movies are REMOVED before the scan. Kodi will not
#                         re-read an NFO for a movie it already has, not even via
#                         VideoLibrary.RefreshMovie, so an edit to the NFO
#                         template is invisible without this
#   6. apply watched      playcounts and resume points, from seed-plan.json
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KODI_APP="${KODI_APP:-/Applications/Kodi.app}"
KODI_HOME="${KODI_HOME:-$HOME/Library/Application Support/Kodi}"
MEDIA="$REPO/bench/media"
RPC="http://localhost:8080/jsonrpc"
CURL=(curl -s -m 30 -u kodi:kodi -H 'Content-Type: application/json')

j() { "${CURL[@]}" -d "$1" "$RPC"; }

stop_kodi() {
  osascript -e 'quit app "Kodi"' >/dev/null 2>&1 || true
  for _ in $(seq 1 30); do
    pgrep -f 'MacOS/Kodi' >/dev/null || return 0
    sleep 1
  done
  echo "Kodi will not quit. Refusing to write under userdata." >&2
  exit 1
}

start_kodi() {
  open -a "$KODI_APP"
  for _ in $(seq 1 60); do
    j '{"jsonrpc":"2.0","method":"JSONRPC.Ping","id":1}' 2>/dev/null | grep -q pong && return 0
    sleep 1
  done
  echo "Kodi never answered JSON-RPC on 8080." >&2
  exit 1
}

echo "== 1. stopping Kodi"
stop_kodi

echo "== 2. generating media tree"
python3 "$REPO/bench/seed-library.py"

echo "== 3. registering sources and content paths"
DB="$(/bin/ls "$KODI_HOME/userdata/Database/"MyVideos*.db 2>/dev/null |
  grep -v 'MyVideos146' | sort -V | tail -1)"
[ -n "$DB" ] || {
  echo "no MyVideos db found" >&2
  exit 1
}
MEDIA="$MEDIA" SRC="$KODI_HOME/userdata/sources.xml" DB="$DB" python3 - <<'PY'
import datetime, os, sqlite3
MEDIA, SRC, DB = os.environ["MEDIA"], os.environ["SRC"], os.environ["DB"]
entries = [("POV Bench Movies", MEDIA + "/movies/"),
           ("POV Bench TV Shows", MEDIA + "/tvshows/")]
s = open(SRC, encoding="utf-8").read()
block = "".join(
    f"\n        <source>\n            <name>{n}</name>\n"
    f'            <path pathversion="1">{p}</path>\n'
    f"            <allowsharing>true</allowsharing>\n        </source>\n"
    for n, p in entries if p not in s)
if block:
    s = s.replace('    <video>\n        <default pathversion="1" />\n',
                  '    <video>\n        <default pathversion="1" />\n' + block, 1)
    open(SRC, "w", encoding="utf-8").write(s)
con = sqlite3.connect(DB); cur = con.cursor()
now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
settings = '<settings><setting id="127" value="true" /></settings>'
for _, p in entries:
    content = "movies" if p.endswith("/movies/") else "tvshows"
    rec = 2147483647 if content == "movies" else 0
    fold = 1 if content == "movies" else 0
    row = cur.execute("select idPath from path where strPath=?", (p,)).fetchone()
    if row:
        cur.execute("update path set strContent=?,strScraper=?,scanRecursive=?,"
                    "useFolderNames=?,strSettings=?,noUpdate=0,exclude=0 where idPath=?",
                    (content, "metadata.local", rec, fold, settings, row[0]))
    else:
        cur.execute("insert into path (strPath,strContent,strScraper,strHash,"
                    "scanRecursive,useFolderNames,strSettings,noUpdate,exclude,"
                    "allAudio,dateAdded,idParentPath) values (?,?,?,'',?,?,?,0,0,0,?,NULL)",
                    (p, content, "metadata.local", rec, fold, settings, now))
con.commit(); con.close()
print(f"   db: {os.path.basename(DB)}")
PY

echo "== 4. starting Kodi"
start_kodi

echo "== 5. wiping and rescanning"
python3 - <<'PY'
import base64, json, time, urllib.request
URL = "http://localhost:8080/jsonrpc"
AUTH = "Basic " + base64.b64encode(b"kodi:kodi").decode()
def J(m, p=None):
    b = json.dumps({"jsonrpc": "2.0", "method": m, "params": p or {}, "id": 1}).encode()
    return json.load(urllib.request.urlopen(urllib.request.Request(
        URL, b, {"Content-Type": "application/json", "Authorization": AUTH}), timeout=60))
for m in J("VideoLibrary.GetMovies", {"properties": ["title"]})["result"].get("movies", []):
    J("VideoLibrary.RemoveMovie", {"movieid": m["movieid"]})
for s in J("VideoLibrary.GetTVShows", {"properties": ["title"]})["result"].get("tvshows", []):
    J("VideoLibrary.RemoveTVShow", {"tvshowid": s["tvshowid"]})
J("VideoLibrary.Scan", {"showdialogs": False})
for _ in range(60):
    time.sleep(2)
    mv = J("VideoLibrary.GetMovies")["result"]["limits"]["total"]
    ep = J("VideoLibrary.GetEpisodes")["result"]["limits"]["total"]
    if mv >= 24 and ep >= 60:
        break
print(f"   scanned: {mv} movies, {ep} episodes")
PY

echo "== 6. applying watched flags and resume points"
python3 "$REPO/bench/apply-watched.py"

echo "== done"
