#!/usr/bin/env python3
"""Turn the newest national CSVs into two GeoParquet files.

    data/parquet/sites.parquet      指定緊急避難場所 (designated emergency evacuation sites), from mergeFromCity_2.csv
    data/parquet/shelters.parquet   指定避難所 (designated shelters), from mergeFromCity_1.csv

Only the newest data/raw/<date>/ is exported: GSI overwrites its data in place
and corrects it, so the newest fetch is the one to publish. The CSVs are made
from, not the GeoJSON, because GSI's GeoJSON rounds the coordinates to six
decimals while the CSV keeps what the municipality registered.

The CSVs are UTF-8 with a BOM, comma separated, with double quotes around
cells that hold line breaks. DuckDB reads them with every column as text, no
type inference, and strict quoting. The Japanese header is mapped to English
names (HEADERS); a header that is not exactly the site or the shelter layout
stops the run.

Types come from the names: no is INTEGER; latitude and longitude are DOUBLE;
the eight hazard columns (flood ... volcanic) and same_address_as_site /
same_address_as_shelter are BOOLEAN, where GSI's definition is "1" for yes and
an empty cell for no, so "1" is true and empty is false; everything else is
VARCHAR, an empty cell NULL, text kept as written (line breaks included).
Each value is checked before the cast: no must be digits; latitude and
longitude must be decimal numbers inside 20..46 N and 122..154 E (Japan,
Okinotorishima to Etorofu, Yonaguni to Minamitorishima); common_id must be the
14-character ID of the Cabinet Office rule (E, 5-digit municipality code,
5-digit facility code, 2-digit type code, 1 sequence character); a flag
must be "1" or empty. Anything else stops the run through error() with the
column, the row's no and the value.

A Point geometry is added from (longitude, latitude), with no
reprojection. GSI does not state a geodetic datum for these coordinates; its
GeoJSON carries no crs member, which RFC 7946 reads as WGS 84 longitude and
latitude, and the GeoParquet metadata leaves crs unset, which GeoParquet reads
as OGC:CRS84 (the same). Rows keep the order of the CSV (by no), and the
files are written without bloom filters.

    uv run python scripts/03_export_parquet.py
"""

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "parquet"
SUBSETS = {"sites": "mergeFromCity_2.csv", "shelters": "mergeFromCity_1.csv"}

HEADERS = {
    "NO": "no",
    "共通ID": "common_id",
    "都道府県名及び市町村名": "municipality",
    "施設・場所名": "name",
    "住所": "address",
    "洪水": "flood",
    "崖崩れ、土石流及び地滑り": "landslide",
    "高潮": "storm_surge",
    "地震": "earthquake",
    "津波": "tsunami",
    "大規模な火事": "large_fire",
    "内水氾濫": "inland_flooding",
    "火山現象": "volcanic",
    "指定避難所との住所同一": "same_address_as_shelter",
    "指定緊急避難場所との住所同一": "same_address_as_site",
    "その他市町村長が必要と認める事項": "other_matters",
    "受入対象者": "eligible_evacuees",
    "緯度": "latitude",
    "経度": "longitude",
    "備考": "remarks",
}
HAZARDS = ("flood", "landslide", "storm_surge", "earthquake", "tsunami", "large_fire",
           "inland_flooding", "volcanic")  # fmt: skip
LAYOUTS = (
    ["no", "common_id", "municipality", "name", "address", *HAZARDS,
     "same_address_as_shelter", "latitude", "longitude", "remarks"],
    ["no", "common_id", "municipality", "name", "address", "same_address_as_site",
     "other_matters", "eligible_evacuees", "latitude", "longitude", "remarks"],
)  # fmt: skip
BOUNDS = {"latitude": (20, 46), "longitude": (122, 154)}
TEXT_PATTERNS = {"common_id": "E[0-9]{12}[0-9A-Za-z]"}


def read_header(path: Path) -> list[str]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return next(csv.reader(f))


def column_names(header: list[str]) -> list[str]:
    names = [HEADERS.get(h) for h in header]
    if names not in [list(x) for x in LAYOUTS]:
        raise ValueError(f"a header of neither the site nor the shelter layout: {header}")
    return names


def column_type(name: str) -> str:
    if name == "no":
        return "INTEGER"
    if name in BOUNDS:
        return "DOUBLE"
    if name in HAZARDS or name.startswith("same_address_as_"):
        return "BOOLEAN"
    return "VARCHAR"


def _fail(path: Path, name: str, what: str, c: str) -> str:
    return (
        f"error('{path.name}: {name} is not {what} (no ' || coalesce(\"no\", '?') || '): ' "
        f"|| coalesce({c}, 'empty'))"
    )


def _expr(path: Path, name: str) -> str:
    c, t = f'"{name}"', column_type(name)
    if t == "INTEGER":
        return f"case when regexp_full_match({c}, '[0-9]+') then cast({c} as integer) else {_fail(path, name, 'an integer', c)} end"
    if t == "DOUBLE":
        lo, hi = BOUNDS[name]
        ok = f"regexp_full_match({c}, '-?[0-9]+(\\.[0-9]+)?') and cast({c} as double) between {lo} and {hi}"
        return f"case when {ok} then cast({c} as double) else {_fail(path, name, f'a number in {lo}..{hi}', c)} end"
    if t == "BOOLEAN":
        return f"case when {c} is null then false when {c} = '1' then true else {_fail(path, name, '1 or empty', c)} end"
    if name in TEXT_PATTERNS:
        pat = TEXT_PATTERNS[name]
        return f"case when regexp_full_match({c}, '{pat}') then {c} else {_fail(path, name, pat, c)} end"
    return c


def select_sql(path: Path, names: list[str]) -> str:
    cols = ", ".join(f"'{n}': 'VARCHAR'" for n in names)
    src = (
        f"read_csv('{path}', header = true, columns = {{{cols}}}, delim = ',', quote = '\"', "
        "escape = '\"', strict_mode = true, auto_detect = false, encoding = 'utf-8')"
    )
    exprs = [f'{_expr(path, n)} as "{n}"' for n in names]
    lon, lat = _expr(path, "longitude"), _expr(path, "latitude")
    exprs.append(
        f"('POINT (' || cast({lon} as varchar) || ' ' || cast({lat} as varchar) || ')')"
        "::GEOMETRY as geometry"
    )
    return f"select {', '.join(exprs)} from {src}"


def csv_records(path: Path) -> int:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return sum(1 for _ in csv.reader(f)) - 1


def export(src: Path, out: Path) -> int:
    import duckdb

    con = duckdb.connect(
        config={"autoload_known_extensions": False, "autoinstall_known_extensions": False}
    )
    names = column_names(read_header(src))
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    con.execute(
        f"copy (select * from ({select_sql(src, names)}) order by no) to '{tmp}' "
        "(format parquet, compression zstd, row_group_size 100000, write_bloom_filter false)"
    )
    got = con.sql(f"select count(*) from read_parquet('{tmp}')").fetchone()[0]
    want = csv_records(src)
    if got != want:
        tmp.unlink()
        raise SystemExit(f"{src.name}: {got} rows written, the CSV has {want} records")
    tmp.replace(out)
    return got


def newest(raw: Path) -> Path:
    dirs = sorted(p.parent for p in raw.glob("*/MANIFEST.json"))
    if not dirs:
        raise SystemExit("no data/raw/<date>/MANIFEST.json; run scripts/01_download.py")
    return dirs[-1]


def main() -> int:
    d = newest(RAW)
    for subset, name in SUBSETS.items():
        src = d / name
        if not src.exists():
            raise SystemExit(f"{src} missing; run scripts/01_download.py")
        out = OUT / f"{subset}.parquet"
        n = export(src, out)
        print(
            f"{d.name}/{name} -> {out.relative_to(ROOT)}: {n:,} rows, {out.stat().st_size:,} bytes"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
