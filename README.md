# gsi-evacuation-sites-jp

A reproducible copy of the designated emergency evacuation sites (指定緊急避難場所)
and designated shelters (指定避難所) of Japan, as the Geospatial Information
Authority of Japan (GSI, 国土地理院) publishes them, with the national CSVs
converted to GeoParquet.

- Source page: <https://www.gsi.go.jp/bousaichiri/hinanbasho.html>
- Download site: <https://hinanmap.gsi.go.jp/index.html> (terms), then
  <https://hinanmap.gsi.go.jp/hinanjocp/hinanbasho/koukaidate.html> (listing)
- Producer: GSI, from what each municipality registers under the Disaster
  Countermeasures Basic Act (災害対策基本法 49-4, 49-7)

## What is fetched

The national files, which GSI builds from every municipality that publishes:

| file | what | format |
|---|---|---|
| `mergeFromCity_2.csv` | 指定緊急避難場所, designated emergency evacuation sites, with a 1/empty flag per hazard type | CSV, UTF-8 with BOM |
| `mergeFromCity_2.geojson` | the same, as Points | GeoJSON, coordinates rounded to 6 decimals |
| `mergeFromCity_1.csv` | 指定避難所, designated shelters | CSV, UTF-8 with BOM |
| `mergeFromCity_1.geojson` | the same, as Points | GeoJSON |

with the three lists the listing page reads (`publicHistoryListData.csv`, one
row per municipality with its first publication date, last update and status;
`prefectureListData.csv`; `countrySetData.csv`) and the notice GSI puts in every
download (`ご利用上の注意.txt`, Shift_JIS). About 167 MB, 8 files, 9 requests.

Per-prefecture (47) and per-municipality (about 1,700) files exist too, with
the same rows split up; `--level prefecture` and `--level municipality` fetch
them, but the full collection is the national files. GSI offers no Shapefile;
the Shapefiles on G空間情報センター (geospatial.jp) were made by AIGID from
GSI's data and are not taken.

GSI regenerates the files in place every morning (about 00:30 UTC) and
states no release number. Each fetch goes to `data/raw/<date>/`, where `<date>`
is the latest 最終更新日 in the municipality list, the date the page shows for
the national data. Only the newest fetch is exported and published.

## Licence

GSI's content terms (国土地理院コンテンツ利用規約,
<https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html>) apply the Public
Data License 1.0 (PDL1.0), which states that it is compatible with CC BY 4.0
and lets users use the content under CC BY. Credit GSI, say that the data was
processed, and pass on GSI's notice: the data is what municipalities
registered, may be out of date or incomplete, and the municipality is to be
asked for the current state. See `data/LICENSE`.

## How to run

```sh
uv run python scripts/01_download.py --dry-run   # what would be fetched, with its size
uv run python scripts/01_download.py             # the full collection: the national files into data/raw/<date>/
uv run python scripts/03_export_parquet.py       # newest national CSVs -> data/parquet/{sites,shelters}.parquet
uv run python scripts/02_verify.py               # raw files against MANIFEST.json, GeoJSON and Parquet against the CSVs
uv run python -m pytest                          # unit tests
uv run python src/publish.py                     # dry run: the files that would go to the Hub
uv run python src/publish.py --push              # upload to huggingface.co/datasets/yuiseki/gsi-evacuation-sites-jp
```

`01_download.py` takes `--level national prefecture municipality`,
`--only <codes>` (`mergeFromCity`, `08000`, `08220`, ...), `--kind site shelter`,
`--format csv geojson` and `--limit N`, and prints the number of requests and
the bytes the server states before fetching. It uses the Python standard
library only, waits at least one second between requests, backs off on 429 and
503, and turns on TLS legacy renegotiation, which GSI's servers need and
OpenSSL 3 refuses by default. Each file is written to `.part`, checked
against Content-Length and renamed; the manifest is written after every file.
To resume an interrupted run, run the same command again: files whose manifest
entry still has the same URL and sha256 are skipped. A later day with a newer
最終更新日 goes to a new directory.

`03_export_parquet.py` types columns by name (see its docstring), checks every
value with a regular expression before the cast and stops on one that does not
fit, and adds a Point geometry from longitude and latitude without
reprojection. GSI states no datum; its GeoJSON has no `crs`, which RFC 7946
reads as WGS 84, and the GeoParquet leaves `crs` unset (OGC:CRS84).

## Layout

```
scripts/01_download.py         read the listing page and its lists, fetch the files, write MANIFEST.json
scripts/03_export_parquet.py   newest national CSVs -> GeoParquet
scripts/02_verify.py           raw files against MANIFEST.json; GeoJSON and Parquet against the CSVs
src/publish.py                 upload to the Hugging Face Hub (dry run by default)
tests/                         unit tests; tests/fixtures/ holds the listing page, trimmed lists and trimmed files
data/README.md                 the dataset card (tracked)
data/LICENSE                   terms of use and what the Parquet changes (tracked)
data/provenance.yaml           source, files, counts, checks, modifications (tracked)
data/raw/<date>/               files as served, plus MANIFEST.json (not in git)
data/parquet/                  the GeoParquet (not in git)
```

`MANIFEST.json` records, for each file, its URL, bytes, sha256,
Last-Modified, fetch time (UTC), encoding, and what the lists state: level,
code, kind, and the municipality or prefecture name, dates, status flag and
comment. GSI states no row counts.
