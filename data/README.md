---
license: cc-by-4.0
language:
- ja
- en
pretty_name: Designated emergency evacuation sites and shelters of Japan (指定緊急避難場所・指定避難所, GSI)
tags:
- geospatial
- geoparquet
- japan
- disaster
- evacuation
- shelters
- gsi
size_categories:
- 100K<n<1M
configs:
- config_name: sites
  data_files: parquet/sites.parquet
  default: true
- config_name: shelters
  data_files: parquet/shelters.parquet
---

# gsi-evacuation-sites-jp

Every designated emergency evacuation site (指定緊急避難場所) and designated
shelter (指定避難所) in Japan that municipalities have registered with the
Geospatial Information Authority of Japan (GSI, 国土地理院) and agreed to
publish, as GSI distributes them at
<https://www.gsi.go.jp/bousaichiri/hinanbasho.html>, with the national CSVs as
GeoParquet.

Licensed under the GSI Content Terms of Use, which apply the Public Data
License 1.0 (PDL1.0), compatible with CC BY 4.0 (see Licence).

An evacuation site is where people go at once to save their lives, and it is
designated per hazard type; a shelter is where evacuees stay until the danger
is over. GSI's own words: "災害発生時には、指定避難所ではなく、指定緊急避難場所へ避難してください。"
(In a disaster, go to a designated emergency evacuation site, not to a
designated shelter.) Use a site only for the hazards it is flagged for.

GSI's notice, which it asks to be passed on with anything built from this
data (ご利用上の注意, quoted from the notice in its download):

> 1.本データは、災害対策基本法第49条の4・第49条の7に基づき市町村長が指定した指定緊急避難場所・指定避難所の情報を各市町村に登録いただいたものです。
>   なお、最新でない場合や未掲載の場合があるため、最新かつ詳細の状況などは必ず当該市町村にご確認ください。
> 2.「指定緊急避難場所」と「指定避難所」の違いや、指定緊急避難場所が災害種別ごとに指定されていることを理解した上でご利用ください。
> 3.本データは随時更新されますので、利用される場合は、ご注意ください。
> 4.本データを用いた情報を第三者に提供する場合は、上記1．～3．の注意事項が正確に伝わるよう、十分にご留意ください。

In short: the data is what each mayor designated and the municipality
registered; it may be out of date or missing facilities (some municipalities
choose not to publish some), so ask the municipality for the current state;
know the difference between sites and shelters; the data changes at any time;
and pass these cautions on accurately to anyone you provide it to.

## Subsets

| subset | rows | municipalities | made from |
|---|---:|---:|---|
| `sites` | 115,872 | 1,699 | `raw/2026-10-05/mergeFromCity_2.csv` (指定緊急避難場所) |
| `shelters` | 83,391 | 1,718 | `raw/2026-10-05/mergeFromCity_1.csv` (指定避難所) |

Of the 1,747 municipalities in GSI's list, 1,691 publish both kinds, 8 only
sites, 27 only shelters, and 21 nothing (データ未登録, including the six
villages of the Northern Territories).

This is the fetch of 2026-10-06 (UTC). `2026-10-05` is the latest 最終更新日
(last update) in GSI's municipality list, the date the download page shows for
the national data. GSI overwrites its files in place every morning and states
no release number, so this dataset follows it: each upload replaces the
previous one with the newest fetch (the repository's history keeps the older
ones).

### `sites` columns

| column | type | GSI's column | meaning |
|---|---|---|---|
| `no` | INTEGER | NO | row number, 1 upward |
| `common_id` | VARCHAR | 共通ID | national common ID of the Cabinet Office rule: E, municipality code (5), facility code (5), type code (2: `20` for a site), sequence (1) |
| `municipality` | VARCHAR | 都道府県名及び市町村名 | prefecture and municipality, e.g. 北海道札幌市 |
| `name` | VARCHAR | 施設・場所名 | facility or place |
| `address` | VARCHAR | 住所 | address |
| `flood` | BOOLEAN | 洪水 | designated for floods (72,001 sites) |
| `landslide` | BOOLEAN | 崖崩れ、土石流及び地滑り | slope failure, debris flows and landslides (67,444) |
| `storm_surge` | BOOLEAN | 高潮 | storm surges (25,488) |
| `earthquake` | BOOLEAN | 地震 | earthquakes (88,562) |
| `tsunami` | BOOLEAN | 津波 | tsunamis (40,607) |
| `large_fire` | BOOLEAN | 大規模な火事 | large fires (43,177) |
| `inland_flooding` | BOOLEAN | 内水氾濫 | inland (pluvial) flooding (39,422) |
| `volcanic` | BOOLEAN | 火山現象 | volcanic phenomena (10,737) |
| `same_address_as_shelter` | BOOLEAN | 指定避難所との住所同一 | a shelter has the same address (62,076) |
| `latitude` | DOUBLE | 緯度 | decimal degrees |
| `longitude` | DOUBLE | 経度 | decimal degrees |
| `remarks` | VARCHAR | 備考 | notes (3,340 rows) |
| `geometry` | GEOMETRY | | Point (longitude, latitude) |

### `shelters` columns

| column | type | GSI's column | meaning |
|---|---|---|---|
| `no` | INTEGER | NO | row number, 1 upward |
| `common_id` | VARCHAR | 共通ID | as above; type code `11` general shelter (72,825), `12` welfare shelter, 福祉避難所 (10,566) |
| `municipality` | VARCHAR | 都道府県名及び市町村名 | prefecture and municipality |
| `name` | VARCHAR | 施設・場所名 | facility |
| `address` | VARCHAR | 住所 | address |
| `same_address_as_site` | BOOLEAN | 指定緊急避難場所との住所同一 | a site has the same address (56,644) |
| `other_matters` | VARCHAR | その他市町村長が必要と認める事項 | other matters the mayor deems necessary (Ordinance for Enforcement of the Disaster Countermeasures Basic Act, Art. 1-7-2(2)) (1,004 rows) |
| `eligible_evacuees` | VARCHAR | 受入対象者 | who is admitted, for welfare shelters that name them (9,288 rows) |
| `latitude` | DOUBLE | 緯度 | decimal degrees |
| `longitude` | DOUBLE | 経度 | decimal degrees |
| `remarks` | VARCHAR | 備考 | notes (819 rows) |
| `geometry` | GEOMETRY | | Point (longitude, latitude) |

GSI defines each flag as "1" when it applies and an empty cell when it does
not; here "1" is true and empty is false. Other empty cells are NULL. Text is
as GSI wrote it, full-width characters and line breaks inside cells included.
Rows are in GSI's order (by `no`, which follows municipality code).

Coordinates are those of the CSV, unchanged and not reprojected. GSI does not
state a geodetic datum. Its GeoJSON has no `crs` member, which RFC 7946 reads
as WGS 84 longitude and latitude, and the GeoParquet leaves `crs` unset, which
GeoParquet reads as OGC:CRS84, the same. (Japan's JGD2011 and WGS 84 differ by
well under a metre at this scale.)

```python
import duckdb
duckdb.sql("""
  select name, address, latitude, longitude
  from 'hf://datasets/yuiseki/gsi-evacuation-sites-jp/parquet/sites.parquet'
  where municipality = '茨城県つくば市' and tsunami
""")
```

## Raw files

GSI's files, byte for byte, in `raw/2026-10-05/`, with `MANIFEST.json` (URL,
bytes, sha256, Last-Modified, fetch time, encoding, and what GSI's lists say
about each file):

| file | bytes | what |
|---|---:|---|
| `mergeFromCity_2.csv` | 17,001,696 | national 指定緊急避難場所, CSV, UTF-8 with BOM |
| `mergeFromCity_2.geojson` | 86,697,793 | the same, GeoJSON Points |
| `mergeFromCity_1.csv` | 11,704,937 | national 指定避難所, CSV, UTF-8 with BOM |
| `mergeFromCity_1.geojson` | 52,055,067 | the same, GeoJSON Points |
| `publicHistoryListData.csv` | 90,459 | per municipality: code, name, first published, last update, status flag, comment |
| `prefectureListData.csv` | 1,372 | per prefecture: code, name, last update, status flag |
| `countrySetData.csv` | 4 | status flag of the national files |
| `ご利用上の注意.txt` | 1,091 | GSI's notice, Shift_JIS (cp932) |

The GeoJSON holds the same rows as the CSV in the same order, with the
coordinates rounded to six decimals; the Parquet is made from the CSV. GSI
also offers the same rows per prefecture and per municipality; they are not
included. GSI does not offer Shapefiles; those on G空間情報センター were made by
AIGID and are not included either.

## Checked before upload

`scripts/02_verify.py` in the source repository checks every raw file's size
and sha256 against the manifest and decodes it strictly; reads both CSVs to
the end with Python's csv module (`NO` runs 1 to n, every record as wide as
the header); checks that each GeoJSON has one Point per CSV record, in the
same order, with the same 共通ID and coordinates within the six-decimal
rounding; and compares every cell of both Parquet files, geometry included,
with the CSV (3,086,388 cells, none differ). It also checks the GeoParquet
metadata, that a DuckDB without extensions reads the files, and that no row
group carries a bloom filter.

## Licence

The download site (<https://hinanmap.gsi.go.jp/index.html>) and GSI's page of
cautions (<https://www.gsi.go.jp/bousaichiri/hinanbasho-menseki.html>):

> 指定緊急避難場所・指定避難所データ（以下「本データ」という。）を利用される場合は、国土地理院コンテンツ利用規約のほか、以下のご利用上の注意をご確認いただき、内容に同意された場合のみご利用ください。

GSI Content Terms of Use (国土地理院コンテンツ利用規約, amended 20 November
2025, read on 2026-10-06,
<https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html>):

> 本サイトのコンテンツには特段の記載が無い限り公共データ利用規約（第1.0 版） （PDL1.0）が適用されています。

The Public Data License 1.0
(<https://www.digital.go.jp/resources/open_data/public_data_license_v1.0>):

> 本利用ルールは、クリエイティブ・コモンズ・ライセンスの表示4.0 国際ライセンスに規定される著作権利用許諾条件（以下「CC BY」といいます。）と互換性があります。国（本コンテンツが国ではなく地方公共団体によって提供されている場合はその地方公共団体）は、本利用ルールが適用される本コンテンツについて、利用者がCC BYに従って利用することを許諾します。

The terms ask for the source to be credited ("出典：国土地理院ウェブサイト
（当該ページのURL）"), for edited or processed content to say so separately,
and that edited content not be presented as if GSI had made it. The Survey Act
restrictions the terms mention concern basic and public survey results and
the control point records; this data is municipal registration, not a survey
result, and GSI attaches no Survey Act notice to it. Commercial use is
allowed.

The files in `raw/` are GSI's. The Parquet files are an edited form made by
yuiseki/gsi-evacuation-sites-jp, not a GSI product, and GSI has not reviewed
them; what was changed is listed in `LICENSE` beside this file.

## Citation

出典：国土地理院ウェブサイト（https://www.gsi.go.jp/bousaichiri/hinanbasho.html）
「指定緊急避難場所・指定避難所データ」（国土地理院）をもとに yuiseki/gsi-evacuation-sites-jp 作成（GeoParquet 化）

Source: Geospatial Information Authority of Japan, 指定緊急避難場所・指定避難所データ
(designated emergency evacuation sites and designated shelters),
https://www.gsi.go.jp/bousaichiri/hinanbasho.html, fetched 2026-10-06; converted to
GeoParquet by yuiseki/gsi-evacuation-sites-jp.
