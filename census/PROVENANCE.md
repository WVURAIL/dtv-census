# Transmitter-census provenance

The source workbook is `TV_Stations_UHF_within500mi_DRAO.xlsx`, retrieved on
2026-06-09. It is a manually compiled listing from FCC LMS and ISED station
information, not a propagation simulation. The inclusion rule was every UHF
ATSC television station listed within 500 statute miles of DRAO
(`49.3208 N`, `119.6239 W`). We used the station class and frequency-tolerance
fields to interpret possible pilot offsets. We did not use the census alone
to claim that a station was detectable at CHIME.

## Optional field-strength screen

The workbook also contains `detectability_db` for a limited nearby subset.
These values came from a RabbitEars Signal Search Map study run on
2026-06-09 at 12:15 ET, shareable ID `2738863`. The study radius was 120
statute miles, and receive height was set to the tool maximum of 99,999,999 ft
AGL. This setting largely removes terrain blocking. Therefore, these field
strengths are optimistic upper-bound estimates, not site predictions.

The final merged CSV contains 42 rows with field strength. Before the
channel-sharing merge, 43 values were present. Rows outside the 120-mile study
have no field strength and fall back to distance when the association code
needs a rank. The earlier record says that the RabbitEars result-list printout
was archived with the source material; no separate copy is present in this
checkout.

## Deterministic reduction

Regenerate the committed CSV (reduction + ISED overlay) with:

```bash
python ingest/apply_ised_overlay.py
```

(`census_from_xlsx.py` alone reproduces the reduction stage, i.e. the
pre-overlay census.)

The reduction applies the following rules:

The row counts below were independently reproduced by running the committed
reduction over the retained workbook. The RabbitEars study settings above are
recorded source metadata; the separate result-list printout is unavailable,
so those settings were not independently verified here.

1. The workbook contains 521 rows. We retain the 485 rows whose `Type` is
   `on-air`. We remove 23 `off-air` rows because they do not describe a
   current emission, 9 analog rows because they have no ATSC pilot, and 4
   ATSC 3.0 rows because OFDM does not contain the 8-VSB pilot used here.
2. We parse every integer in `Physical Ch(s)` and emit one row for each value
   in 14--36. Multi-channel entries therefore expand. One on-air entry,
   `CH5643-DT`, has no UHF token and is excluded; it is VHF-only. Channels
   2--13 occupy 54--216 MHz and lie below CHIME's 400--800 MHz band.
3. The expansion produces 494 emitter-channel rows. Four pairs share an RF
   channel and site, so we merge each pair into one physical carrier. The
   final CSV contains 490 emitter-channel rows: 93 with service class
   `Full-power` and 397 in the other recorded classes.
4. `detectability_db` is the RabbitEars field strength in dBuV/m when one is
   available. Otherwise it is blank. Association ranking then falls back to
   distance.
5. We convert distance from miles to kilometers and carry the bearing,
   frequency tolerance, CHIME channel index, nominal pilot frequency, city,
   and state or province through when present. Five output rows have no CHIME
   index and retain `nan` for nominal pilot frequency because those fields are
   absent in the source workbook.

## Frequency-tolerance boundary

At the unmerged source-row level, full-power, Class A, and Relay entries use
`±1 kHz`, while Translator and LPTV entries use `None specified`. The merge
promotes the service class to the more primary partner but retains the first
row's frequency-tolerance field. Consequently, two merged rows
(`KJYY-LD+KOPB-TV` and `KCKW-LD+KEZI`) are labeled `Full-power` while retaining
`None specified`. Analyses should treat this as a channel-sharing provenance
case rather than infer tolerance from the merged class alone.


## Upstream source material (this repository)

The section above was written inside pilot-proxy, where the workbook was the
earliest committed ancestor. In this repository the upstream chain is present:

- `sources/rabbitears/dtv_120m.pdf` **is** the archived RabbitEars result-list
  printout referred to above: it carries shareable ID `2738863`, study
  date/time 2026-06-09 12:15:16 ET, search distance 120 miles, and receive
  height 99,999,999 ft AGL. The "no separate copy is present in this checkout"
  caveat no longer applies here.
- `sources/rabbitears/` also holds the RabbitEars master-list and source
  workbooks and the per-city station printouts.
- `sources/ised/` holds the small ISED White Space TV-station extract and the
  field-description PDFs for the full SMS snapshot on the team SharePoint
  (`RFI Mitigation/Canada-SMS-Allocations/`).
- `sources/coordinates/` holds the 500-mile site-coordinate listings.

The workbook itself remains a manual compilation from FCC LMS and ISED
station information; nothing in this repository regenerates it. The
deterministic part of the chain starts at `census_from_xlsx.py`.


## ISED overlay (2026-08-19)

The committed `census.csv` is the reduction above plus the ISED overlay
(`ingest/apply_ised_overlay.py`), which corrects the Canadian side against
the licence records in `sources/ised/ws_data.csv` (verdicts in
`VERIFICATION.md`):

1. **Coordinates.** The 67 Canadian on-air rows matched to an ISED digital
   licence take the licensed transmitter site; distance and bearing are
   recomputed from DRAO (46 rows moved by more than 1 km — the workbook had
   anchored many rows on the community rather than the transmitter; e.g.
   CHKL-1 moved 17.7 → 37.8 km, in agreement with the archived RabbitEars
   printout).
2. **Status and evidence.** Two Canadian rows reported on air but lacking a
   current ISED digital licence were dropped (CH4369-DT ch 16 South Slocan
   Valley, CH2523 ch 19 Hasler Flats). Nine workbook-analog stations holding
   digital licences and two in-radius licensed LPTVs with no usable on-air
   workbook row were added to the *maximum-envelope* census. Those 11 rows are
   explicitly labelled `licensed_candidate`: licensing is not treated as
   proof of an active emission. Rows supported by both an on-air workbook
   report and an ISED digital licence are `reported_on_air_licensed`; US rows,
   pending an FCC LMS cross-check, are `reported_on_air_unverified`.
3. **ERP.** An `erp_kw` column carries the ISED effective radiated power on
   the 78 matched, promoted, or added Canadian rows; US rows are blank until
   an FCC LMS ingest exists.

The result is 499 emitter-channel rows. The `schema_version` and
`evidence_status` fields make the product contract and inclusion scenario
machine-readable, while preserving the existing inclusive count used by the
surrounding-interference analysis. US rows pass through the overlay untouched
and remain workbook-faithful.
