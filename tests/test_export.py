import importlib.util
import json
from pathlib import Path

import duckdb
import pytest

HERE = Path(__file__).parent
FX = HERE / "fixtures"
_spec = importlib.util.spec_from_file_location(
    "export", HERE.parent / "scripts" / "03_export_parquet.py"
)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

SITES = FX / "mergeFromCity_2.csv"
SHELTERS = FX / "mergeFromCity_1.csv"


def test_the_site_header_gets_english_names():
    assert m.column_names(m.read_header(SITES)) == [
        "no", "common_id", "municipality", "name", "address", "flood", "landslide",
        "storm_surge", "earthquake", "tsunami", "large_fire", "inland_flooding", "volcanic",
        "same_address_as_shelter", "latitude", "longitude", "remarks",
    ]  # fmt: skip


def test_the_shelter_header_gets_english_names():
    assert m.column_names(m.read_header(SHELTERS)) == [
        "no", "common_id", "municipality", "name", "address", "same_address_as_site",
        "other_matters", "eligible_evacuees", "latitude", "longitude", "remarks",
    ]  # fmt: skip


@pytest.mark.parametrize(
    "header",
    [
        ["NO", "共通ID", "施設・場所名"],
        [
            "NO",
            "共通ID",
            "都道府県名及び市町村名",
            "施設・場所名",
            "住所",
            "未知の列",
            "緯度",
            "経度",
            "備考",
        ],
        [],
    ],
)
def test_an_unknown_header_stops_the_run(header):
    with pytest.raises(ValueError):
        m.column_names(header)


@pytest.mark.parametrize(
    ("name", "sql"),
    [
        ("no", "INTEGER"),
        ("latitude", "DOUBLE"),
        ("longitude", "DOUBLE"),
        ("flood", "BOOLEAN"),
        ("volcanic", "BOOLEAN"),
        ("same_address_as_site", "BOOLEAN"),
        ("same_address_as_shelter", "BOOLEAN"),
        ("common_id", "VARCHAR"),
        ("name", "VARCHAR"),
        ("eligible_evacuees", "VARCHAR"),
        ("remarks", "VARCHAR"),
    ],
)
def test_column_type_comes_from_the_name(name, sql):
    assert m.column_type(name) == sql


def _rel(path):
    con = duckdb.connect()
    names = m.column_names(m.read_header(path))
    return con.sql(m.select_sql(path, names))


def test_sites_are_typed_and_keep_every_row_in_order():
    rel = _rel(SITES)
    assert rel.columns[-1] == "geometry"
    types = dict(zip(rel.columns, (str(t) for t in rel.types), strict=True))
    assert types["no"] == "INTEGER" and types["flood"] == "BOOLEAN"
    assert types["latitude"] == "DOUBLE" and types["geometry"].startswith("GEOMETRY")
    rows = rel.fetchall()
    assert [r[0] for r in rows] == [1, 2, 864, 6215]
    first = dict(zip(rel.columns, rows[0], strict=True))
    assert first["common_id"] == "E0110000001202"
    assert first["flood"] is True and first["storm_surge"] is False
    assert first["latitude"] == 43.03806002377 and first["longitude"] == 141.48471007692
    assert first["remarks"] is None
    assert (
        rows[3][3] == "北星町地区高台（日高自動車道）\n※建設予定"
    )  # a line break inside a quoted cell
    assert rows[2][-2] == "津波災害は３階以上"


def test_the_geometry_is_the_point_of_longitude_and_latitude():
    con = duckdb.connect()
    names = m.column_names(m.read_header(SHELTERS))
    got = con.sql(
        f"select geometry::varchar, longitude, latitude from ({m.select_sql(SHELTERS, names)})"
    ).fetchall()
    assert got[0] == ("POINT (141.4847101 43.03806002)", 141.4847101, 43.03806002)


def test_shelters_keep_trailing_line_breaks_and_text():
    rows = _rel(SHELTERS).fetchall()
    assert rows[-1][7] == "妊婦、乳幼児等" and rows[-1][10] == "妊婦、乳幼児等\n"
    assert rows[2][7] == "要配慮者" and rows[2][5] is False


@pytest.mark.parametrize(
    ("old", "new", "column"),
    [
        (",1,1,,1,,1,,,1,43.03806002377,", ",1,2,,1,,1,,,1,43.03806002377,", "landslide"),
        (",43.03806002377,", ",43.0.3,", "latitude"),
        (",43.03806002377,", ",,", "latitude"),
        (",43.03806002377,", ",-43.0,", "latitude"),
        ("1,E0110000001202,", "x,E0110000001202,", "no"),
        ("1,E0110000001202,", "1,0110000001202,", "common_id"),
    ],
)
def test_a_value_that_does_not_fit_stops_the_export(tmp_path, old, new, column):
    text = SITES.read_bytes().decode("utf-8-sig")
    assert old in text
    p = tmp_path / "mergeFromCity_2.csv"
    p.write_bytes(b"\xef\xbb\xbf" + text.replace(old, new, 1).encode())
    with pytest.raises(duckdb.Error, match=column):
        _rel(p).fetchall()


def test_export_writes_geoparquet_without_bloom_filters(tmp_path):
    out = tmp_path / "sites.parquet"
    n = m.export(SITES, out)
    assert n == 4
    con = duckdb.connect()
    kv = dict(
        con.sql(f"select decode(key), decode(value) from parquet_kv_metadata('{out}')").fetchall()
    )
    geo = json.loads(kv["geo"])
    assert geo["primary_column"] == "geometry"
    assert geo["columns"]["geometry"]["geometry_types"] == ["Point"]
    assert "crs" not in geo["columns"]["geometry"]  # GeoParquet's default, OGC:CRS84
    bloom = con.sql(
        "select count(*) filter (where bloom_filter_offset is not null) "
        f"from parquet_metadata('{out}')"
    ).fetchone()[0]
    assert bloom == 0


def test_newest_version_is_the_latest_directory_with_a_manifest(tmp_path):
    for v in ("2026-09-30", "2026-10-05", "2026-10-06"):
        (tmp_path / v).mkdir()
    for v in ("2026-09-30", "2026-10-05"):
        (tmp_path / v / "MANIFEST.json").write_text("{}")
    assert m.newest(tmp_path).name == "2026-10-05"
