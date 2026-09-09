# dtv-station-census

DTV transmitter and station data for the CHIME/DRAO RFI environment, and the
reduction that turns it into the transmitter census consumed by
[pilot-proxy](https://github.com/WVURAIL/pilot-proxy).

This repository is the home for station-location source material and the
scripts that process it. It exists so that neither the detector repository nor
the dissertation has to carry upstream broadcast-database bulk: pilot-proxy
consumes the derived `census/census.csv`; everything upstream of that file
lives here.

## Transmitter history

[The history project](history/README.md) records dated transmitter evidence and
reproduces a large channel-versus-time overview with a 44-transmitter shutdown
appendix. It separates reported events from administrative dates and preserves
unknown operating intervals.

## The provenance chain

```
ISED SMS extracts + FCC LMS + RabbitEars          (raw; SharePoint, sources/)
        |
        v
TV_Stations_UHF_within500mi_DRAO.xlsx             (curated workbook, census/)
        |
        v  census_from_xlsx.py                    (deterministic reduction)
        |
        v  ingest/apply_ised_overlay.py           (ISED sites, status, ERP)
census/census.csv                                 (499-row maximum envelope)
        |
        v  pilot-proxy analyze-transmitter-census / dissertation export
census_full_500mi.csv + census_inner_120mi.csv    (dissertation fig. 3.2, census table)
```

The reduction policy (on-air ATSC 1.0 only, UHF 14–36 token expansion,
channel-sharing merge) is documented in `census/PROVENANCE.md` and reported on
stdout by the script itself.

The committed table is deliberately a conservative maximum envelope. Its
`schema_version` identifies the stable product contract, and its
`evidence_status` column distinguishes rows reported on air from 11 Canadian
digital licences whose actual emission was not confirmed.  Use
`licensed_candidate` rows when asking "what could be present"; exclude them
when asking "what did the retained station sources report on air."  A licence
alone is never described here as an observed carrier.

The column contract and evidence vocabulary are defined in
[`census/SCHEMA.md`](census/SCHEMA.md).

Regenerate the census:

```bash
python3 ingest/apply_ised_overlay.py
```

## Layout

| Path | Contents |
|---|---|
| `census/` | The curated workbook, the committed reduction, and the derived CSV pilot-proxy consumes, with `PROVENANCE.md`. |
| `sources/rabbitears/` | RabbitEars source material, including `dtv_120m.pdf` — the archived Signal Search Map result list (study `2738863`, run 2026-06-09 12:15 ET, 120 mi, receive height at the tool maximum) that supplies the workbook's `detectability_db` values. |
| `sources/ised/` | The small ISED extracts (`ws_data.csv` — the White Space "Television and Other Licensed Service Stations" table — plus `ssl_data.csv` and `afl_data.csv`) and the field-description PDFs for every extract in the SMS snapshot. |
| `sources/notes/` | Compilation notes (`North American DTV Transmitter Data.docx`). |
| `ingest/` | `extract_tv_records.py`, the frequency-window filter for the large ISED extracts that stay on SharePoint, `verify_against_ised.py`, the Canadian-side census verifier, and `apply_ised_overlay.py`, which regenerates `census.csv` with the ISED corrections. |
| `census/VERIFICATION.md` | Dated cross-check of the workbook's Canadian rows against the ISED extract (`ingest/verify_against_ised.py` regenerates it). |
| `raw/` | Empty, gitignored. Working directory for local copies of the large extracts; see `raw/README.md` for where to get them. |

## USA record loading

`ingest/load_fcc_lms.py` loads US UHF digital-TV licence sites from native
FCC LMS public database tables or ZIP downloads. It follows current granted
licences through transmitter sites and antennas, preserves physical channels
and ERP in kW, and exports candidates with source IDs and snapshot dates.
See [`sources/fcc/README.md`](sources/fcc/README.md) for downloads, usage,
selection rules and limits. Its output is separate from the historical
workbook-derived census until USA matching and sharing are adjudicated.

## Tests

Install `requirements-dev.txt`, then run `make verify` (or
`python -m ruff check census ingest tests` followed by
`python -m pytest -q --cov --cov-report=term-missing`). The suite covers each
processing stage, CLI behavior, malformed inputs and complete regeneration,
with a 95% combined line/branch coverage gate. See
[`tests/README.md`](tests/README.md) for setup and the component coverage map.

## What stays on SharePoint

GitHub rejects files over 100 MB and this repository has no reason to carry
raw national databases. The full raw snapshots live in the team SharePoint
under `WVU RAIL - Documents/RFI Mitigation/`:

| SharePoint item | Size | What it is |
|---|---|---|
| `Canada-SMS-Allocations/tsl_data.csv` | 979 MB | ISED Terrestrial Spectrum Licence Site Data Extract (per `tsl_field_desc.pdf`) |
| `Canada-SMS-Allocations/as_data.csv` | 476 MB | ISED SMS extract (per `as_field_desc.pdf`) |
| `Station-Lists/TAFL_LTAF.csv.xlsx` | 231 MB | Technical and Administrative Frequency List workbook |
| `Station-Lists/xmtrs_120miles.png`, `xmtr_pwr_120m.png` | 13 MB / 285 KB | Transmitter-map renderings (no generator script is known for these) |

To work with a large extract, copy it into `raw/` and filter it down:

```bash
python3 ingest/extract_tv_records.py raw/tsl_data.csv raw/tv_band_tsl.csv
```

## Zero redundancy

Every file has exactly one home: this repository for source material, curated
tables, and scripts; the SharePoint folders above for what a public repository
cannot or should not carry (the two large raw extracts, the TAFL workbook, and
the two map renderings). Two copies exist by contract, not redundancy:
`census/census.csv` is vendored into pilot-proxy `data/census/` as its input
interface, and the dissertation freezes its own export subsets
(`census_full_500mi.csv`, `census_inner_120mi.csv`).

Removed from the tree as derived or superseded (recoverable from the initial
commit, d43bd18): `pilot_proxy_dtv_500mi_coordinates.xlsx` and
`pilot_proxy_dtv_500mi_site_coordinates.csv` (every column recomputable from
`census.csv` plus the census figure's own DRAO-centred projection; the CSV
duplicated a sheet of the workbook outright) and `dtv_500.xlsx` (an earlier
Penticton-centred draft superseded by the census workbook).

## Consumers

- `pilot-proxy` vendors `census/census.csv` as its transmitter-census input
  (`data/census/` in that repository).
- The dissertation's census map and table read the pilot-proxy exports built
  from that file; they never read this repository directly.
