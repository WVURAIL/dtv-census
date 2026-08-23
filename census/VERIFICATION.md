# Census verification against ISED — 2026-08-19

`ingest/verify_against_ised.py` cross-checks the workbook's Canadian rows
against `sources/ised/ws_data.csv` (ISED White Space extract, "Television and
Other Licensed Service Stations"; a dated snapshot of a daily-updated
database). Regenerate this report by running the script; this note records
the verdicts from the snapshot in this repository.

## Verdicts (measured against the ISED snapshot)

- **44 of 70** on-air Canadian emitter-channel rows are confirmed by callsign
  **and** transmitter position (≤ 10 km).
- **24 rows** match by callsign but sit 11–61 km from the ISED site. The
  offsets are city-systematic (all Vancouver rows ≈ 16.5 km, Calgary 12.5 km,
  Edmonton 13–21 km): for these rows the workbook's coordinates — and
  therefore its distance/bearing and the derived `census.csv` values — anchor
  on the **community**, not the transmitter site. Largest cases:
  CHNU-DT ch24 (61 km), CHEK-DT ch16 (41 km), and, nearest to DRAO,
  **CHKL-1 ch30 Penticton: workbook 11 mi vs ISED 23.5 mi** — the archived
  RabbitEars printout (`sources/rabbitears/dtv_120m.pdf`) also says 23.5 mi,
  so two independent sources agree the workbook coordinate is the city, not
  the site.
- **1 row** matches by position with a different callsign: CHBC-DT ch24 ↔
  ISED CHKL-DT — the known channel-sharing pair (the reduction already merges
  them); ISED licenses the shared emitter under CHKL-DT. Consistent.
- **2 rows have no ISED digital record**: CH4369-DT ch16 South Slocan Valley
  (95 mi; nearest same-channel digital is CHWW-DT 12 km away — possibly the
  same relay under another listing, unresolved) and CH2523 ch19 Hasler Flats
  (449 mi; no ISED trace).
- **11 ISED digital LPTV emitters within 500 mi have no on-air workbook
  row** — ten of them the workbook lists as *analog* (the Prince
  George-area cluster, 390–404 mi, ERP ≈ 15–20 dBW); CH4433-DT ch19 is
  absent entirely. Either the RabbitEars status is stale or the ISED digital
  licences are not yet on air; unresolved without a third source.
- **44 further licensed in-band emitters** (RRBS / non-protected data
  services, nearest at 181 mi on ch 19) are not TV stations and carry no
  ATSC pilot, but occupy the same allocations; the census has never counted
  them.
- Coordinate offsets over all 68 matches: median 6.1 km, max 61 km.

## Scope

The extract covers Canada only; the workbook's 440 US rows (FCC LMS
territory) are not verified here. Analog and off-air workbook rows were not
checked beyond the status cross-references above.

## Corrections applied (2026-08-19)

All three correction classes are applied by `ingest/apply_ised_overlay.py`,
which regenerates the committed `census.csv` (reduction + overlay; see the
ISED-overlay section of PROVENANCE.md for the rules and counts: 67 rows
re-sited, 2 dropped, 9 promoted, 2 added, `erp_kw` on 78 Canadian rows,
499 rows total). The ISED record governs licensed transmitter coordinates
and digital authorization, while the workbook remains the record of the
original on-air compilation. The 9 promoted and 2 added authorizations remain
unconfirmed emissions and are labelled `licensed_candidate` in the CSV.

Still open:

- US-side verification and ERP (FCC LMS ingest; 440 rows).
- CH4369-DT ch 16 was dropped for lack of any ISED licence; if it is later
  shown to be a genuinely distinct relay rather than a stale listing beside
  CHWW-DT (12 km away), restore it via the workbook and note it here.
