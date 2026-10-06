import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "publish", Path(__file__).parents[1] / "src" / "publish.py"
)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


def _data(tmp_path, subsets=("sites", "shelters"), raw=b"x", cited="2026-10-05"):
    d = tmp_path / "data"
    (d / "parquet").mkdir(parents=True)
    for s in ("sites", "shelters"):
        (d / "parquet" / f"{s}.parquet").write_bytes(b"PAR1")
    for v, body in (("2026-09-30", b"old"), ("2026-10-05", raw)):
        (d / "raw" / v).mkdir(parents=True)
        (d / "raw" / v / "mergeFromCity_2.csv").write_bytes(body)
        files = {
            "mergeFromCity_2.csv": {
                "sha256": hashlib.sha256(b"x" if v == "2026-10-05" else body).hexdigest()
            }
        }
        (d / "raw" / v / "MANIFEST.json").write_text(json.dumps({"files": files}))
    text = "---\nconfigs:\n" + "".join(m.subset_entry(s) for s in subsets) + f"---\nraw/{cited}/\n"
    (d / "README.md").write_text(text)
    for f in ("LICENSE", "provenance.yaml"):
        (d / f).write_text("x")
    return d


def test_collect_lists_card_parquet_and_only_the_newest_fetch(tmp_path):
    assert m.collect(_data(tmp_path)) == [
        "README.md", "LICENSE", "provenance.yaml",
        "parquet/sites.parquet", "parquet/shelters.parquet",
        "raw/2026-10-05/mergeFromCity_2.csv", "raw/2026-10-05/MANIFEST.json",
    ]  # fmt: skip


def test_a_subset_the_card_does_not_declare_stops_it(tmp_path):
    with pytest.raises(SystemExit, match="shelters"):
        m.collect(_data(tmp_path, subsets=("sites",)))


def test_a_card_describing_another_fetch_stops_it(tmp_path):
    with pytest.raises(SystemExit, match="2026-10-05"):
        m.collect(_data(tmp_path, cited="2026-09-30"))


def test_a_raw_file_unlike_its_manifest_stops_it(tmp_path):
    with pytest.raises(SystemExit, match="raw/2026-10-05/mergeFromCity_2.csv"):
        m.collect(_data(tmp_path, raw=b"changed"))


def test_subset_entry():
    assert m.subset_entry("sites") == "- config_name: sites\n  data_files: parquet/sites.parquet\n"
