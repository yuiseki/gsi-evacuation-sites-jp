#!/usr/bin/env python3
"""Check every fetch under data/raw/ against its MANIFEST.json, and the Parquet against the CSVs.

For each raw file: present, size and sha256 as in the manifest, and decoded
strictly in the encoding the manifest records (UTF-8 with BOM for the data
CSVs and the lists, UTF-8 for GeoJSON, cp932 for the notice). Then:
  - a data CSV is read to the end with the csv module, every record has as
    many cells as the header, the header is the site or the shelter layout
    of 03_export_parquet.py, and NO runs 1, 2, 3, ...; its record count is printed
  - a GeoJSON is a FeatureCollection of Points with one feature per record of
    the CSV of the same name, in the same order, with the same 共通ID, and
    coordinates equal to the CSV's rounded to six decimals (GSI rounds them)
  - a list (publicHistoryListData.csv, ...) is read with the csv module

For the Parquet of the newest fetch (data/parquet/sites.parquet and
shelters.parquet), against the records of the national CSV:
  - as many rows, the column names column_names() gives plus geometry, each of
    the type its name gives
  - every cell equal to the CSV's, row by row: text as text (empty as NULL),
    no as int, latitude and longitude as float, flags "1" as true and empty
    as false; geometry the point (float(経度), float(緯度))
  - GeoParquet metadata naming geometry, Point, and no crs (OGC:CRS84)
  - a plain DuckDB with extension autoloading turned off opens it
  - no row group carries a bloom filter

Prints one ok/FAIL line per check and exits non-zero on any failure.

    uv run python scripts/02_verify.py
"""

import csv
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PQ = ROOT / "data" / "parquet"

_spec = importlib.util.spec_from_file_location("export", ROOT / "scripts" / "03_export_parquet.py")
export = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(export)

LISTS = ("publicHistoryListData.csv", "countrySetData.csv", "prefectureListData.csv")
ROUND = 5e-7 + 1e-9  # six decimals, half a unit, and float noise


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_records(path: Path, encoding: str) -> tuple[list[str], list[list[str]]]:
    """(header, records), decoded strictly; ValueError on a record of another width."""
    with open(path, newline="", encoding=encoding, errors="strict") as f:
        rows = list(csv.reader(f))
    header, records = rows[0], rows[1:]
    for i, r in enumerate(records, start=2):
        if len(r) != len(header):
            raise ValueError(
                f"record {i - 1} (line {i} or later) has {len(r)} cells, the header {len(header)}"
            )
    return header, records


def typed(name: str, raw: str):
    """What the Parquet should hold for one CSV cell."""
    t = export.column_type(name)
    if t == "INTEGER":
        return int(raw)
    if t == "DOUBLE":
        return float(raw)
    if t == "BOOLEAN":
        return raw == "1"
    return raw if raw != "" else None


def point_xy(wkt: str) -> tuple[float, float]:
    mt = re.fullmatch(r"POINT \((\S+) (\S+)\)", wkt)
    if not mt:
        raise ValueError(f"not a point: {wkt}")
    return float(mt.group(1)), float(mt.group(2))


def geojson_problems(gj: dict, header: list[str], records: list[list[str]]) -> list[str]:
    """Where a GeoJSON disagrees with the CSV of the same name; [] when it does not."""
    if gj.get("type") != "FeatureCollection":
        return ["not a FeatureCollection"]
    feats = gj["features"]
    if len(feats) != len(records):
        return [f"{len(feats)} features, the CSV has {len(records)} records"]
    iid, ilat, ilon = header.index("共通ID"), header.index("緯度"), header.index("経度")
    out = []
    for i, (f, r) in enumerate(zip(feats, records, strict=True), start=1):
        g = f.get("geometry") or {}
        if g.get("type") != "Point":
            out.append(f"row {i}: geometry {g.get('type')}")
            continue
        x, y = g["coordinates"][:2]
        if f["properties"].get("共通ID") != r[iid]:
            out.append(f"row {i}: 共通ID {f['properties'].get('共通ID')}, the CSV {r[iid]}")
        elif abs(x - float(r[ilon])) > ROUND or abs(y - float(r[ilat])) > ROUND:
            out.append(f"row {i}: ({x}, {y}), the CSV ({r[ilon]}, {r[ilat]})")
    return out


class Checks:
    def __init__(self):
        self.failures = 0

    def __call__(self, ok: bool, what: str) -> bool:
        print(("ok   " if ok else "FAIL ") + what, flush=True)
        self.failures += not ok
        return ok


def verify_dir(d: Path, check: Checks) -> dict[str, int]:
    """Check one fetch; returns the record count of each data CSV."""
    files = json.loads((d / "MANIFEST.json").read_text())["files"]
    counts: dict[str, int] = {}
    tables: dict[str, tuple] = {}
    for name in sorted(files, key=lambda n: (n.endswith(".geojson"), n)):
        e = files[name]
        p, tag = d / name, f"{d.name}/{name}"
        if not check(p.exists(), f"{tag}: present"):
            continue
        if not check(p.stat().st_size == e["bytes"] and sha256(p) == e["sha256"],
                     f"{tag}: {e['bytes']:,} bytes, sha256 as in the manifest"):  # fmt: skip
            continue
        enc = e.get("encoding", "utf-8")
        try:
            if name.endswith(".txt"):
                p.read_bytes().decode(enc)
                check(True, f"{tag}: decodes as {enc}")
            elif Path(name).name in LISTS:
                with open(p, newline="", encoding=enc, errors="strict") as f:
                    n = sum(1 for r in csv.reader(f) if r and r[0])
                check(True, f"{tag}: {n:,} rows ({enc})")
            elif name.endswith(".csv"):
                header, records = read_records(p, enc)
                export.column_names(header)
                seq = [r[0] for r in records] == [str(i) for i in range(1, len(records) + 1)]
                check(seq, f"{tag}: {len(records):,} records ({enc}), NO runs 1..{len(records)}")
                counts[name] = len(records)
                tables[name] = (header, records)
            elif name.endswith(".geojson"):
                gj = json.loads(p.read_text(encoding=enc))
                twin = name[: -len(".geojson")] + ".csv"
                if twin in tables:
                    probs = geojson_problems(gj, *tables[twin])
                    check(not probs, f"{tag}: {len(gj['features']):,} Points, as {twin} "
                                     f"({probs[:3] or 'same ids, coordinates within 6 decimals'})")  # fmt: skip
                else:
                    check(gj.get("type") == "FeatureCollection",
                          f"{tag}: {len(gj['features']):,} features (no CSV beside it)")  # fmt: skip
        except (OSError, UnicodeDecodeError, csv.Error, ValueError, KeyError) as ex:
            check(False, f"{tag}: {ex}")
    return counts


def verify_parquet(d: Path, check: Checks) -> None:
    import duckdb

    for subset, name in export.SUBSETS.items():
        p = PQ / f"{subset}.parquet"
        if not check(p.exists(), f"{subset}: {p.relative_to(ROOT)} present"):
            continue
        header, records = read_records(d / name, "utf-8-sig")
        names = export.column_names(header)
        con = duckdb.connect()
        rel = con.sql(f"select * from '{p}' order by no")
        check(rel.columns == [*names, "geometry"], f"{subset}: columns {', '.join(rel.columns)}")
        types = dict(zip(rel.columns, (str(t) for t in rel.types), strict=True))
        wrong = {c: t for c, t in types.items() if c != "geometry" and t != export.column_type(c)}
        check(not wrong and types.get("geometry", "").startswith("GEOMETRY"),
              f"{subset}: every column of the type its name gives ({wrong or 'all'})")  # fmt: skip
        got = con.sql(
            f"select * exclude (geometry), geometry::varchar from '{p}' order by no"
        ).fetchall()
        check(len(got) == len(records), f"{subset}: {len(got):,} rows, {name} has {len(records):,}")
        ilat, ilon = names.index("latitude"), names.index("longitude")
        diff = []
        for i, (r, row) in enumerate(zip(records, got, strict=False), start=1):
            for c, raw, g in zip(names, r, row, strict=False):
                if typed(c, raw) != g:
                    diff.append((i, c, raw, g))
            if point_xy(row[-1]) != (float(r[ilon]), float(r[ilat])):
                diff.append((i, "geometry", r[ilon], r[ilat], row[-1]))
        cells = len(records) * (len(names) + 1)
        check(
            not diff, f"{subset}: all {cells:,} cells equal the CSV ({diff[:3] or 'none differ'})"
        )
        kv = dict(
            con.sql(f"select decode(key), decode(value) from parquet_kv_metadata('{p}')").fetchall()
        )
        geo = json.loads(kv.get("geo", "{}"))
        col = geo.get("columns", {}).get("geometry", {})
        check(geo.get("primary_column") == "geometry" and col.get("geometry_types") == ["Point"]
              and "crs" not in col,
              f"{subset}: GeoParquet {geo.get('version')}, Point, crs unset (OGC:CRS84), bbox {col.get('bbox')}")  # fmt: skip
        plain = duckdb.connect(
            config={"autoload_known_extensions": False, "autoinstall_known_extensions": False}
        )
        try:
            q = f"select count(*) from '{p}' where municipality like '茨城県%'"
            n = plain.sql(q).fetchone()[0]
            check(True, f"{subset}: a DuckDB without extensions opens it ({n:,} rows in 茨城県)")
        except duckdb.Error as ex:
            check(False, f"{subset}: a DuckDB without extensions fails on it: {ex}")
        bloom = con.sql(
            "select count(*) filter (where bloom_filter_offset is not null) "
            f"from parquet_metadata('{p}')"
        ).fetchone()[0]
        check(bloom == 0, f"{subset}: no bloom filters")


def main() -> int:
    dirs = sorted(p.parent for p in RAW.glob("*/MANIFEST.json"))
    if not dirs:
        print("FAIL no MANIFEST.json under data/raw/")
        return 1
    check = Checks()
    for d in dirs:
        counts = verify_dir(d, check)
        print(f"{d.name}: " + ", ".join(f"{k} {v:,}" for k, v in counts.items()))
    verify_parquet(dirs[-1], check)
    print("all ok" if not check.failures else f"{check.failures} failure(s)")
    return 1 if check.failures else 0


if __name__ == "__main__":
    sys.exit(main())
