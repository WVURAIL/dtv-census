# Census product schema

`census.csv` uses schema `dtv_transmitter_census_v1`. Every row repeats that
token so a CSV copied outside this repository remains self-identifying.
Unknown schema tokens must be rejected rather than interpreted as v1.

| Column | Contract |
|---|---|
| `schema_version` | Exact token `dtv_transmitter_census_v1`. |
| `rf_channel` | Integer ATSC UHF physical channel, 14 through 36. |
| `callsign` | Source callsign; `+` joins partners sharing one carrier. |
| `service_class` | Source service/class label. |
| `detectability_db` | Optional RabbitEars field-strength score in dBuV/m. |
| `distance_km` | Great-circle distance from DRAO in kilometres. |
| `bearing_deg` | True bearing from DRAO in degrees, `[0, 360)`. |
| `frequency_tolerance` | Source frequency-tolerance label. |
| `chime_ch_index` | Historical CHIME coarse-channel index where available. |
| `nominal_pilot_mhz` | Nominal ATSC 1.0 pilot frequency in MHz. |
| `city` | Source community/transmitter name. |
| `state_prov` | Two-letter US state or Canadian province/territory. |
| `erp_kw` | Optional ISED effective radiated power in kW; blank pending FCC ingest. |
| `evidence_status` | One of the evidence categories below. |

Evidence categories are deliberately about source support, not telescope
detection:

- `reported_on_air_licensed`: the workbook reports the Canadian emitter on
  air and an ISED digital licence matches it.
- `reported_on_air_unverified`: the workbook reports the emitter on air, but
  this repository has not yet completed the applicable primary-database
  cross-check (currently the US/FCC rows).
- `licensed_candidate`: an ISED digital licence exists, but retained sources
  do not confirm that the transmitter was emitting. These rows belong to the
  conservative maximum envelope and must not be described as observed
  carriers.
