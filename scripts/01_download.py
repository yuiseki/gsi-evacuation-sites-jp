#!/usr/bin/env python3
"""Fetch GSI's designated emergency evacuation sites and designated shelters data.

The Geospatial Information Authority of Japan (GSI, 国土地理院) publishes the
指定緊急避難場所・指定避難所データ that municipalities register with it, from
https://www.gsi.go.jp/bousaichiri/hinanbasho.html. Its download buttons lead,
through a terms page (https://hinanmap.gsi.go.jp/index.html), to the listing
page https://hinanmap.gsi.go.jp/hinanjocp/hinanbasho/koukaidate.html. That page
is static HTML; its script reads three CSV lists and builds a ZIP in the browser
from two files per entry and a notice:

    ../defaultFtpData/csv/<key>.csv           UTF-8 with BOM
    ../defaultFtpData/geoJSON/<key>.geojson   Point features, coordinates rounded to 6 decimals
    ../assets/notice/ご利用上の注意.txt          Shift_JIS (cp932)

<key> is <code>_2 for 指定緊急避難場所 (designated emergency evacuation sites,
"site" here) and <code>_1 for 指定避難所 (designated shelters, "shelter" here).
The code is mergeFromCity for the national file (every municipality that
publishes), <pref>000 for a prefecture, the 5-digit municipality code for a
municipality. This script reads the page for those locations and the three
lists (never guessing a URL), and decides what exists the way the page's
script does:

    countrySetData.csv          national row: flag 1 = sites only, 2 = shelters only, 9 = none
    prefectureListData.csv      code, name, last update, flag (as above)
    publicHistoryListData.csv   code, name, first published, last update, flag, comment;
                                flag 11 = sites only, 12 = shelters only, 2, 3 or 9 or
                                no dates = nothing published

GSI overwrites the files in place (they are regenerated every morning, about
00:30 UTC), and states no release number. A fetch goes to
data/raw/<date>/, where <date> is the latest 最終更新日 of the municipality
list, which the page shows as the 最終更新日 of the national data. The three
lists and the notice are kept beside the data, as fetched.

Levels: national (the default, and the full collection: the national files are
the union of every published municipality), prefecture (47 x 2 x 2 files) and
municipality (about 1,700 x 2 x 2 files). They go to data/raw/<date>/,
data/raw/<date>/prefecture/ and data/raw/<date>/municipality/.

data/raw/<date>/MANIFEST.json records for each file its URL, bytes, sha256,
Last-Modified, fetch time (UTC), encoding and what the lists state about it. It
is written after every file, so an interrupted run resumes where it stopped; a
file whose manifest entry has the same URL and whose sha256 still matches is not
fetched again. The lists are fetched on every run (they say what exists).

www.gsi.go.jp and hinanmap.gsi.go.jp need TLS legacy renegotiation, which
OpenSSL 3 refuses by default; the SSL context turns it on for these requests.

    uv run python scripts/01_download.py                         # national files, the full collection
    uv run python scripts/01_download.py --dry-run               # the estimate only
    uv run python scripts/01_download.py --level municipality --only 08220 --format csv
    uv run python scripts/01_download.py --level prefecture --kind shelter --limit 4
"""

import argparse
import hashlib
import json
import re
import shutil
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
SOURCE_PAGE = "https://www.gsi.go.jp/bousaichiri/hinanbasho.html"
PAGE_URL = "https://hinanmap.gsi.go.jp/hinanjocp/hinanbasho/koukaidate.html"
TERMS_URL = "https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html"
NOTICE_URL = "https://www.gsi.go.jp/bousaichiri/hinanbasho-menseki.html"
UA = "gsi-evacuation-sites-jp/1 (+https://github.com/yuiseki/gsi-evacuation-sites-jp)"
DELAY = 1.0
RETRIES = 5
HEAD_MAX = 60  # above this many files, the estimate does not HEAD each one
LEVELS = ("national", "prefecture", "municipality")
KINDS = {"site": "_2", "shelter": "_1"}  # the page's key suffixes
KIND_JA = {"site": "指定緊急避難場所", "shelter": "指定避難所"}
FORMATS = ("csv", "geojson")
LISTS = ("publicHistoryListData.csv", "countrySetData.csv", "prefectureListData.csv")
ENCODINGS = {".csv": "utf-8-sig", ".geojson": "utf-8", ".txt": "cp932"}

_last_request = 0.0


def parse_page(html: str, base: str) -> dict:
    """The file locations the page's script uses: the csv and geoJSON directories, the notice, the lists."""
    fetches = re.findall(r'fetch\("([^"]+)"\s*(?:\+\s*municode\s*\+\s*"(\.[a-zA-Z]+)")?\)', html)
    loc: dict = {}
    for path, ext in fetches:
        url = urllib.parse.urljoin(base, urllib.parse.quote(path, safe="/.:"))
        if ext == ".csv":
            loc["csv"] = url
        elif ext == ".geojson":
            loc["geojson"] = url
        elif path.endswith(".txt"):
            loc["notice"] = url
    lists = re.findall(r"url:\s*'([^']+\.csv)'", html)
    loc["lists"] = {Path(p).name: urllib.parse.urljoin(base, p) for p in lists}
    nat = re.findall(r"dlFile\(&quot;([A-Za-z]+)_[12]&quot;\)", html)
    loc["national"] = nat[0] if nat and len(set(nat)) == 1 else None
    missing = [k for k in ("csv", "geojson", "notice", "national") if not loc.get(k)]
    missing += [n for n in LISTS if n not in loc["lists"]]
    if missing:
        raise SystemExit(f"the listing page no longer shows: {', '.join(missing)}")
    return loc


def split_list(text: str) -> dict[str, list[str]]:
    """Like the page's convertCSVtoArray: split on newlines and commas, keyed by the first cell, last wins."""
    out = {}
    for line in text.split("\n"):
        cells = line.rstrip("\r").split(",")
        if cells[0]:
            out[cells[0]] = cells
    return out


def _kinds(flag: str, site_only: str, shelter_only: str, none: tuple[str, ...]) -> list[str]:
    if flag in none:
        return []
    if flag == site_only:
        return ["site"]
    if flag == shelter_only:
        return ["shelter"]
    return ["site", "shelter"]


def municipalities(rows: dict) -> list[dict]:
    out = []
    for code, c in rows.items():
        c = c + [""] * (6 - len(c))
        kinds = [] if not (c[2] and c[3]) else _kinds(c[4], "11", "12", ("2", "3", "9"))
        out.append({"code": code, "name": c[1], "published": c[2], "updated": c[3],
                    "flag": c[4], "comment": c[5], "kinds": kinds})  # fmt: skip
    return out


def prefectures(rows: dict) -> list[dict]:
    out = []
    for code, c in rows.items():
        c = c + [""] * (4 - len(c))
        out.append({"code": code, "name": c[1], "updated": c[2], "flag": c[3],
                    "kinds": _kinds(c[3], "1", "2", ("9",))})  # fmt: skip
    return out


def national(rows: dict) -> list[str]:
    flag = next(iter(rows.values()), ["", ""])
    return _kinds(flag[1] if len(flag) > 1 else "", "1", "2", ("9",))


def version(munis: list[dict]) -> str:
    """The latest 最終更新日 in the municipality list: the date the page shows for the national data."""
    dates = [
        m["updated"] for m in munis if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", m["updated"])
    ]
    if not dates:
        raise SystemExit("the municipality list has no update dates")
    return max(dates)


def file_name(code: str, kind: str, fmt: str) -> str:
    return f"{code}{KINDS[kind]}.{fmt}"


def targets(loc, lists, levels, only=None, kinds=None, formats=None, limit=None) -> list[dict]:
    """The data files to fetch, in page order: per entry, sites then shelters, CSV then GeoJSON."""
    entries = []
    if "national" in levels:
        entries.append(
            (
                "national",
                "",
                {"code": loc["national"], "kinds": national(lists["countrySetData.csv"])},
            )
        )
    if "prefecture" in levels:
        entries += [
            ("prefecture", "prefecture/", p) for p in prefectures(lists["prefectureListData.csv"])
        ]
    if "municipality" in levels:
        entries += [("municipality", "municipality/", p)
                    for p in municipalities(lists["publicHistoryListData.csv"])]  # fmt: skip
    out = []
    for level, sub, e in entries:
        if only and e["code"] not in only:
            continue
        listing = {k: v for k, v in e.items() if k not in ("code", "kinds")}
        for kind in e["kinds"]:
            if kinds and kind not in kinds:
                continue
            for fmt in FORMATS:
                if formats and fmt not in formats:
                    continue
                name = file_name(e["code"], kind, fmt)
                out.append({"path": sub + name, "url": loc[fmt] + name, "level": level,
                            "code": e["code"], "kind": kind, "format": fmt, "listing": listing})  # fmt: skip
    return out[:limit] if limit else out


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def plan(ts: list[dict], manifest: dict, d: Path) -> list[dict]:
    """The targets still to fetch: not in the manifest, another URL, or another sha256 on disk."""
    todo = []
    for t in ts:
        e = manifest.get("files", {}).get(t["path"])
        p = d / t["path"]
        if e and e["url"] == t["url"] and p.exists() and sha256(p) == e["sha256"]:
            continue
        todo.append(t)
    return todo


def should_retry(status: int) -> bool:
    return status in (429, 503)


def _context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
    return ctx


_CTX = _context()


def _open(url: str, method: str = "GET"):
    """One request, at least DELAY after the previous one; 429 and 503 back off and retry."""
    global _last_request
    for attempt in range(RETRIES):
        wait = DELAY - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, headers={"User-Agent": UA}, method=method)
        try:
            r = urllib.request.urlopen(req, timeout=300, context=_CTX)
            _last_request = time.monotonic()
            return r
        except urllib.error.HTTPError as ex:
            _last_request = time.monotonic()
            if not should_retry(ex.code) or attempt == RETRIES - 1:
                raise
            after = ex.headers.get("Retry-After", "")
            pause = int(after) if after.isdigit() else 30 * 2**attempt
            print(f"{ex.code} on {url}; waiting {pause} s", file=sys.stderr, flush=True)
            time.sleep(pause)
    raise AssertionError("unreachable")


def get_bytes(url: str) -> tuple[bytes, str]:
    with _open(url) as r:
        return r.read(), r.headers.get("Last-Modified", "")


def head_length(url: str) -> int | None:
    with _open(url, "HEAD") as r:
        v = r.headers.get("Content-Length")
    return int(v) if v else None


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(url: str, dest: Path) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with _open(url) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
        length = r.headers.get("Content-Length")
        lm = r.headers.get("Last-Modified", "")
    got = tmp.stat().st_size
    if length is not None and got != int(length):
        tmp.unlink()
        raise SystemExit(f"{url}: got {got} bytes, the server stated {length}")
    tmp.replace(dest)
    return {"url": url, "bytes": got, "sha256": sha256(dest), "last_modified": lm,
            "fetched_at": _now(), "encoding": ENCODINGS[dest.suffix]}  # fmt: skip


def store(data: bytes, url: str, lm: str, dest: Path, entry: dict | None) -> dict:
    """Keep an already fetched small file (a list or the notice); unchanged bytes keep their entry."""
    sha = hashlib.sha256(data).hexdigest()
    if entry and entry["sha256"] == sha and dest.exists() and sha256(dest) == sha:
        return entry
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return {"url": url, "bytes": len(data), "sha256": sha, "last_modified": lm,
            "fetched_at": _now(), "encoding": ENCODINGS[dest.suffix]}  # fmt: skip


def load_manifest(d: Path) -> dict:
    p = d / "MANIFEST.json"
    return json.loads(p.read_text()) if p.exists() else {"files": {}}


def write_manifest(d: Path, manifest: dict) -> None:
    d.mkdir(parents=True, exist_ok=True)
    # a sorted copy: the caller keeps adding to manifest["files"], the same dict
    out = {**manifest, "files": dict(sorted(manifest["files"].items()))}
    tmp = d / "MANIFEST.json.part"
    tmp.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    tmp.replace(d / "MANIFEST.json")


def describe(t: dict) -> dict:
    """What the page and its lists state about a data file."""
    return {"level": t["level"], "code": t["code"], "kind": t["kind"],
            "kind_ja": KIND_JA[t["kind"]], "format": t["format"], "listing": t["listing"]}  # fmt: skip


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--level", nargs="+", choices=LEVELS, default=["national"])
    ap.add_argument("--only", nargs="+", help="codes: mergeFromCity, 08000, 08220, ...")
    ap.add_argument(
        "--kind",
        nargs="+",
        choices=list(KINDS),
        help="site (指定緊急避難場所) or shelter (指定避難所)",
    )
    ap.add_argument("--format", nargs="+", choices=FORMATS)
    ap.add_argument("--limit", type=int, help="at most N files, in page order")
    ap.add_argument("--dry-run", action="store_true", help="print the estimate and stop")
    a = ap.parse_args()

    html, _ = get_bytes(PAGE_URL)
    loc = parse_page(html.decode("utf-8"), PAGE_URL)
    fetched = {name: get_bytes(url) for name, url in loc["lists"].items()}
    lists = {name: split_list(b.decode("utf-8-sig")) for name, (b, _) in fetched.items()}
    munis = municipalities(lists["publicHistoryListData.csv"])
    ver = version(munis)
    d = RAW / ver
    manifest = load_manifest(d)
    ts = targets(
        loc, lists, a.level, set(a.only or ()), set(a.kind or ()), set(a.format or ()), a.limit
    )
    todo = plan(ts, manifest, d)

    published = sum(1 for m in munis if m["kinds"])
    print(f"{ver}: {len(munis)} municipalities listed, {published} publish data; "
          f"{len(ts)} files selected, {len(todo)} to fetch", flush=True)  # fmt: skip
    if len(todo) <= HEAD_MAX:
        stated = [head_length(t["url"]) for t in todo]
        size = f"{sum(n or 0 for n in stated):,} bytes stated ({len(todo)} HEAD made)"
    else:
        size = "bytes not asked for (the national files are about 170 MB per level in all)"
    print(f"  {len(todo)} GET requests to come, {size}, about {len(todo) * DELAY:.0f} s plus transfer",
          flush=True)  # fmt: skip
    if a.dry_run:
        return 0

    manifest.update({
        "version": ver,
        "version_is": "the latest 最終更新日 in publicHistoryListData.csv (the page's 最終更新日 of the national data)",
        "source_page": SOURCE_PAGE, "listing_page": PAGE_URL,
        "terms_of_use": TERMS_URL, "notice": NOTICE_URL,
        "municipalities_listed": len(munis), "municipalities_published": published,
        "published_row_counts": None,
    })  # fmt: skip
    files = manifest["files"]
    for name, (b, lm) in fetched.items():
        files[name] = store(b, loc["lists"][name], lm, d / name, files.get(name))
    nb, nlm = get_bytes(loc["notice"])
    nname = urllib.parse.unquote(Path(urllib.parse.urlparse(loc["notice"]).path).name)
    files[nname] = store(nb, loc["notice"], nlm, d / nname, files.get(nname))
    write_manifest(d, manifest)

    for t in todo:
        entry = fetch(t["url"], d / t["path"])
        entry.update(describe(t))
        files[t["path"]] = entry
        write_manifest(d, manifest)
        print(f"{ver}/{t['path']}: {entry['bytes']:,} bytes, {entry['last_modified']}", flush=True)
    for t in ts:  # the lists' statements may change while a file does not
        if t["path"] in files:
            files[t["path"]].update(describe(t))
    write_manifest(d, manifest)
    print(f"{len(ts)} selected, {len(todo)} fetched into {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
