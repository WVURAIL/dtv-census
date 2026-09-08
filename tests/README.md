# Verification benches

Run from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
make verify PYTHON=.venv/bin/python
```

On Windows, activate a virtual environment and run the equivalent commands:

```powershell
python -m ruff check census ingest tests
python -m pytest -q --cov --cov-report=term-missing
```

`make verify` and CI require Ruff and at least 95% combined statement/branch
coverage across **all** Python files under `census/` and `ingest/`. Subprocess
coverage is enabled, so CLI execution is counted. CI covers Python 3.10,
3.12 and 3.13 on Linux and Windows. Local validation used Python 3.12 on
Ubuntu/WSL; configuring a CI matrix does not imply those remote jobs have run.

## Coverage map

| Bench | Behaviors verified |
|---|---|
| `test_reduction.py` | Both channel parsers, UHF boundaries, status filtering, expansion, accounting, optional values, numeric formatting, source immutability, sharing merges, class/score precedence, preservation of tolerance provenance, distinct emitters, empty inputs, CSV quoting/encoding/schema and reduction CLI. |
| `test_extract.py` | Headered and positional sources, custom columns/windows, inclusive lower/exclusive upper edges, malformed/short/non-finite records, encoding replacement, counters, empty sources, invalid options, source/alias overwrite protection, preservation of an existing output on header errors, streaming and CLI. |
| `test_ised.py` | Callsign/aux normalization, DMS validation, geographic reference values/antipodes, source field mapping, service classification, UHF edges, missing power/coordinates, main-over-aux and highest-known-ERP deduplication, coherent selected-site metadata, and workbook scope/loading. |
| `test_verification.py` | Callsign-plus-position/callsign-only/position-only matches, unmatched and analog hints, missing coordinates, reverse completeness, non-TV reporting, report truncation, coordinate summaries, CSV export, empty inputs and the retained snapshot's 68 matched pairs. |
| `test_overlay.py` | Bearings, pilot frequencies/coarse-channel indices, geometry and dBW-to-kW conversion, US passthrough, sharing-partner matching, callsign precedence, 10 km position boundary, partial coordinates, drops, promotions, additions, deduplication, radius/order, evidence labels and empty output. |
| `test_fcc_lms.py` | Official source fixture, extracted/per-table/combined archives, trailers/BOM/column order, current-licence joins, US/service/status/ATSC filtering, missing/ambiguous joins, corrupt input, DTS sites, physical channels, ERP units/precedence, deduplication, hemispheres/radius, provenance, deterministic CLI output and input preservation. |
| `test_census.py` | Historical 499-row evidence envelope, numeric/schema invariants, US workbook fidelity, UTF-8/LF output and complete byte-identical regeneration. |

All automated tests are offline. Synthetic XLSX/CSV fixtures live in pytest
temporary directories; no test writes to the committed census or source
workbook. A tiny FCC source fixture has its own provenance and source ZIP
hashes. Bulk source data is unnecessary for the default suite.

For a focused run, use `python -m pytest tests/test_fcc_lms.py -q` (or another
bench). For an HTML coverage report, use `python -m pytest --cov
--cov-report=html`; generated reports are ignored by Git. The 95% coverage
gate applies when coverage is requested; ordinary `pytest` remains useful
for focused development runs.

To exercise a full FCC snapshot, follow `sources/fcc/README.md` and run the
loader against the six same-date downloads. This checks the actual join and
filter path on bulk data without making network availability part of CI.

Passing tests and complete code coverage verify the implemented contracts,
not the correctness/completeness of upstream station reports or actual
transmitter operation. Historical workbook choices remain explicit: the
first sharing partner supplies tolerance and other carried-through fields,
and missing workbook pilot frequencies remain `nan`. FCC physical-carrier
sharing adjudication and a dated USA overlay remain separate work.
