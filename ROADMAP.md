# Roadmap: from DTV census to a general station-census tool

## Where figure 3.2 comes from today

The dissertation's transmitter-field map is rendered inside the dissertation
bundle (`figure_src/broadcast_figures.py::fig_census_map`) from two frozen
export tables that pilot-proxy derives from this repository's
`census/census.csv` (`census_full_500mi` and `census_inner_120mi` — column
subsets). Nothing here draws the map yet, and TikZ is not involved: the
figure is matplotlib over a DRAO-centred azimuthal-equidistant projection,
with the 499 emitter-channel maximum envelope aggregated into coincident sites at
render time. Under the agreed architecture — repositories own data-backed
figures — the renderer belongs here; moving it in is step 1 below, after
which the dissertation imports the finished figure instead of rendering it.

## The generalization: plug in licence extracts, get a census and a map

One tool, three stages, each already half-present in this repository:

1. **Ingest adapters → one station-record schema**
   (callsign, service, frequency/channel, lat, lon, ERP, class, status,
   licence id, source, snapshot date, evidence status):
   - ISED SMS extracts — the ws/tsl schema knowledge lives in
     `ingest/extract_tv_records.py` and `ingest/verify_against_ised.py`'s
     loader; promote it into a proper adapter.
   - FCC — ULS weekly dumps (every licensed service, amateur included) and
     LMS (broadcast). New adapters, same output schema.
2. **Census core** — query = (center as lat/lon or place, radius,
   service/band filters) → ranked station table. Default rank
   ERP/distance²; detectability scores plug in where a propagation model
   exists (the RabbitEars column here is the worked example).
3. **Render** — AEQD map centred on the query point, sites aggregated with
   multiplicity (exactly the figure-3.2 treatment), plus the CSV.

CLI sketch:

```
station-census --center 29.76,-95.36 --radius-mi 100 --source uls:HD.dat --service amateur --out houston-hams/
station-census --center DRAO --radius-mi 500 --source ised:ws_data.csv --band 470-608 --out dtv/
```

"All the ham radios within 100 miles of Houston" is then one command.

## Ground rules (what makes it reusable rather than clever-once)

- Every adapter documents its upstream download URL, update cadence, and
  schema authority (the committed field-description PDFs model this), and
  stamps the snapshot date into its output.
- The common schema is versioned and validated at the adapter boundary; the
  core and renderer never see source-specific columns.
- The DTV census stays as the flagship worked example and regression test —
  the tool must reproduce `census/census.csv` and the 3.2 map from raw
  inputs.
- Rename the repository to `station-census` when this lands.
