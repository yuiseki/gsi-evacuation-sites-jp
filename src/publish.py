#!/usr/bin/env python3
"""Push the card, the licence, the provenance, the Parquet and the newest raw fetch to the Hub.

GSI overwrites its data in place and corrects it, so the dataset follows it:
only the newest data/raw/<date>/ goes up, and its files replace the previous
upload (the Hub's git history keeps the earlier ones). Every raw file goes up
unchanged after its sha256 is checked against that directory's MANIFEST.json,
and the card must declare both Parquet files as the subsets 'sites' and
'shelters'.

    uv run python src/publish.py             # dry run: list the files and their total size
    uv run python src/publish.py --push
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
REPO = "yuiseki/gsi-evacuation-sites-jp"
SUBSETS = ("sites", "shelters")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def subset_entry(name: str) -> str:
    return f"- config_name: {name}\n  data_files: parquet/{name}.parquet\n"


def newest(data: Path) -> Path:
    dirs = sorted(p.parent for p in (data / "raw").glob("*/MANIFEST.json"))
    if not dirs:
        raise SystemExit("no data/raw/<date>/MANIFEST.json; run scripts/01_download.py")
    return dirs[-1]


def collect(data: Path) -> list[str]:
    """The files to upload, relative to data/; stops on anything the card or the manifest refutes."""
    card = (data / "README.md").read_text(encoding="utf-8")
    files = ["README.md", "LICENSE", "provenance.yaml"]
    for s in SUBSETS:
        p = data / "parquet" / f"{s}.parquet"
        if not p.exists():
            raise SystemExit(f"no parquet/{s}.parquet; run scripts/03_export_parquet.py")
        if subset_entry(s) not in card:
            raise SystemExit(f"the card does not declare the subset {s}")
        files.append(f"parquet/{s}.parquet")
    d = newest(data)
    ver = d.name
    if f"raw/{ver}/" not in card:
        raise SystemExit(f"the card does not describe the fetch raw/{ver}/")
    for name, e in json.loads((d / "MANIFEST.json").read_text())["files"].items():
        if sha256(d / name) != e["sha256"]:
            raise SystemExit(f"raw/{ver}/{name} is not the file in its manifest")
        files.append(f"raw/{ver}/{name}")
    files.append(f"raw/{ver}/MANIFEST.json")
    return files


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()

    files = collect(DATA)
    total = 0
    for f in files:
        size = (DATA / f).stat().st_size
        total += size
        print(f"  {size:>12,}  {f}")
    print(f"{a.repo}\n  {len(files)} files, {total:,} bytes ({total / 1e6:.1f} MB)")
    if not a.push:
        print("\ndry run. pass --push to upload")
        return 0

    from huggingface_hub import HfApi

    api = HfApi()
    api.create_repo(a.repo, repo_type="dataset", exist_ok=True, private=False)
    api.upload_folder(
        folder_path=str(DATA),
        repo_id=a.repo,
        repo_type="dataset",
        allow_patterns=files,
        delete_patterns=["raw/**"],  # an older fetch is replaced, as GSI replaces it
    )
    print(f"\npushed to https://huggingface.co/datasets/{a.repo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
