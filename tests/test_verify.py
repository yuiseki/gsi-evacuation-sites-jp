import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).parent
FX = HERE / "fixtures"
_spec = importlib.util.spec_from_file_location("verify", HERE.parent / "scripts" / "02_verify.py")
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def test_read_records_counts_quoted_line_breaks_as_one_record():
    header, records = m.read_records(FX / "mergeFromCity_2.csv", "utf-8-sig")
    assert header[0] == "NO" and len(records) == 4
    assert records[3][3] == "北星町地区高台（日高自動車道）\n※建設予定"


def test_a_ragged_record_fails(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("NO,a\n1,2,3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        m.read_records(p, "utf-8")


@pytest.mark.parametrize(
    ("name", "raw", "want"),
    [
        ("no", "12", 12),
        ("latitude", "43.03806002377", 43.03806002377),
        ("flood", "1", True),
        ("flood", "", False),
        ("same_address_as_site", "", False),
        ("remarks", "", None),
        ("remarks", "妊婦、乳幼児等\n", "妊婦、乳幼児等\n"),
    ],
)
def test_typed_is_what_the_parquet_should_hold(name, raw, want):
    assert m.typed(name, raw) == want


@pytest.mark.parametrize("k", ["1", "2"])
def test_the_geojson_matches_its_csv(k):
    header, records = m.read_records(FX / f"mergeFromCity_{k}.csv", "utf-8-sig")
    gj = json.loads((FX / f"mergeFromCity_{k}.geojson").read_text(encoding="utf-8"))
    assert m.geojson_problems(gj, header, records) == []


def test_a_geojson_point_away_from_its_csv_row_is_reported():
    header, records = m.read_records(FX / "mergeFromCity_2.csv", "utf-8-sig")
    gj = json.loads((FX / "mergeFromCity_2.geojson").read_text(encoding="utf-8"))
    gj["features"][1]["geometry"]["coordinates"][0] += 0.001
    gj["features"][2]["properties"]["共通ID"] = "E0000000000000"
    probs = m.geojson_problems(gj, header, records)
    assert len(probs) == 2 and "row 2" in probs[0] and "row 3" in probs[1]


def test_point_wkt_parses_back():
    assert m.point_xy("POINT (141.4847101 43.03806002)") == (141.4847101, 43.03806002)
