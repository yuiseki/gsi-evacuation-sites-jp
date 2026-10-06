import hashlib
import importlib.util
from pathlib import Path

import pytest

HERE = Path(__file__).parent
FX = HERE / "fixtures"
_spec = importlib.util.spec_from_file_location(
    "download", HERE.parent / "scripts" / "01_download.py"
)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

PAGE = "https://hinanmap.gsi.go.jp/hinanjocp/hinanbasho/koukaidate.html"
BASE = "https://hinanmap.gsi.go.jp/hinanjocp/"


def _text(name: str) -> str:
    return (FX / name).read_text(encoding="utf-8")


def test_the_page_gives_the_file_locations_and_the_three_lists():
    loc = m.parse_page(_text("koukaidate.html"), PAGE)
    assert loc["csv"] == BASE + "defaultFtpData/csv/"
    assert loc["geojson"] == BASE + "defaultFtpData/geoJSON/"
    assert (
        loc["notice"]
        == BASE
        + "assets/notice/%E3%81%94%E5%88%A9%E7%94%A8%E4%B8%8A%E3%81%AE%E6%B3%A8%E6%84%8F.txt"
    )
    assert loc["lists"] == {
        "publicHistoryListData.csv": BASE
        + "defaultFtpData/publicHistoryCSV/publicHistoryListData.csv",
        "countrySetData.csv": BASE + "defaultFtpData/publicHistoryCSV/countrySetData.csv",
        "prefectureListData.csv": BASE + "defaultFtpData/publicHistoryCSV/prefectureListData.csv",
    }
    assert loc["national"] == "mergeFromCity"


def test_a_page_without_the_download_function_stops_the_run():
    with pytest.raises(SystemExit, match="csv"):
        m.parse_page("<html><script>fetch('x')</script></html>", PAGE)


def test_split_lines_like_the_page_keeps_the_last_row_of_a_key():
    rows = m.split_list("01100,a,,\r\n01100,b,,\r\n\r\n,x\r\n")
    assert rows == {"01100": ["01100", "b", "", ""]}


def test_municipality_rows_say_which_kinds_are_published():
    rows = m.split_list(_text("publicHistoryListData.csv"))
    got = {r["code"]: r["kinds"] for r in m.municipalities(rows)}
    assert got["01100"] == ["site", "shelter"]
    assert got["01225"] == ["site"]  # 11: 指定緊急避難場所データのみ公開
    assert got["04302"] == ["shelter"]  # 12: 指定避難所データのみ公開
    assert got["01695"] == []  # 9: データ未登録, no dates
    first = m.municipalities(rows)[0]
    assert first == {"code": "01100", "name": "北海道札幌市", "published": "2023-01-01",
                     "updated": "2026-02-10", "flag": "", "comment": "", "kinds": ["site", "shelter"]}  # fmt: skip


def test_prefecture_and_national_rows():
    pref = m.prefectures(m.split_list(_text("prefectureListData.csv")))
    assert pref[0] == {"code": "01000", "name": "北海道", "updated": "2026-09-30", "flag": "",
                       "kinds": ["site", "shelter"]}  # fmt: skip
    assert m.national(m.split_list(_text("countrySetData.csv"))) == ["site", "shelter"]
    assert m.national({"1": ["1", "1"]}) == ["site"]
    assert m.national({"2": ["2", "2"]}) == ["shelter"]
    assert m.national({"9": ["9", "9"]}) == []


def test_the_version_is_the_latest_update_date_the_page_shows():
    rows = m.split_list(_text("publicHistoryListData.csv"))
    assert m.version(m.municipalities(rows)) == "2026-09-03"  # 01202 函館市


def test_the_file_name_of_a_kind():
    assert m.file_name("mergeFromCity", "site", "csv") == "mergeFromCity_2.csv"
    assert m.file_name("08220", "shelter", "geojson") == "08220_1.geojson"


def _loc():
    return m.parse_page(_text("koukaidate.html"), PAGE)


def _lists():
    return {k: m.split_list(_text(k)) for k in
            ("publicHistoryListData.csv", "prefectureListData.csv", "countrySetData.csv")}  # fmt: skip


def test_targets_national_by_default_with_both_formats():
    t = m.targets(_loc(), _lists(), levels=["national"])
    assert [x["path"] for x in t] == [
        "mergeFromCity_2.csv", "mergeFromCity_2.geojson",
        "mergeFromCity_1.csv", "mergeFromCity_1.geojson",
    ]  # fmt: skip
    assert t[0]["url"] == BASE + "defaultFtpData/csv/mergeFromCity_2.csv"
    assert t[1]["url"] == BASE + "defaultFtpData/geoJSON/mergeFromCity_2.geojson"
    assert t[0]["kind"] == "site" and t[2]["kind"] == "shelter"


def test_targets_by_level_code_kind_format_and_limit():
    t = m.targets(_loc(), _lists(), levels=["municipality"], only={"01225", "04302"})
    assert [x["path"] for x in t] == [
        "municipality/01225_2.csv", "municipality/01225_2.geojson",
        "municipality/04302_1.csv", "municipality/04302_1.geojson",
    ]  # fmt: skip
    assert t[0]["listing"] == {"name": "北海道滝川市", "published": "2017-02-22",
                               "updated": "2025-10-07", "flag": "11",
                               "comment": "指定緊急避難場所データのみ公開"}  # fmt: skip
    t = m.targets(_loc(), _lists(), levels=["prefecture"], kinds={"shelter"}, formats={"csv"})
    assert [x["path"] for x in t] == [
        "prefecture/01000_1.csv",
        "prefecture/02000_1.csv",
        "prefecture/03000_1.csv",
    ]
    t = m.targets(_loc(), _lists(), levels=["municipality"], limit=3)
    assert len(t) == 3


def test_plan_skips_files_whose_manifest_entry_still_matches(tmp_path):
    (tmp_path / "a.csv").write_bytes(b"abc")
    sha = hashlib.sha256(b"abc").hexdigest()
    ts = [{"path": "a.csv", "url": "u"}, {"path": "b.csv", "url": "v"}]
    assert m.plan(ts, {"files": {"a.csv": {"url": "u", "sha256": sha}}}, tmp_path) == [ts[1]]
    assert m.plan(ts, {"files": {"a.csv": {"url": "u", "sha256": "0"}}}, tmp_path) == ts
    assert m.plan(ts, {"files": {"a.csv": {"url": "x", "sha256": sha}}}, tmp_path) == ts


@pytest.mark.parametrize(
    ("status", "retry"), [(429, True), (503, True), (404, False), (500, False)]
)
def test_only_429_and_503_are_retried(status, retry):
    assert m.should_retry(status) is retry


def test_write_manifest_keeps_the_callers_files_dict(tmp_path):
    manifest = {"files": {"b": {"sha256": "2"}}}
    files = manifest["files"]
    m.write_manifest(tmp_path, manifest)
    files["a"] = {"sha256": "1"}
    m.write_manifest(tmp_path, manifest)
    written = m.load_manifest(tmp_path)
    assert list(written["files"]) == ["a", "b"]
