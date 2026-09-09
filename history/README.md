# Transmitter-history evidence

This project owns the reviewed transmitter-event sidecar and channel-versus-time
figures used to investigate the dissertation's transmitter-state questions.
It currently describes **11 selected transmitters and 26 dated records**.
The selection answers specific dissertation questions; it is neither a ranking
of received interference nor a complete cochannel inventory.

The overview puts source-backed reference RF channels and exact callsigns on the
y-axis, with calendar record dates on the x-axis. It distinguishes operator
on-air/shutdown months, ISED date fields, administrative decisions/certificates,
and an FCC filing receipt. Unknown operating history remains visible. The second
page lists all 44 transmitters in the October 2018 shutdown cohort, alongside
ISED's existing and planned channels. No continuous on/off line is inferred.

## Reproduce and inspect

From the dtv-census repository:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-history.txt -r requirements-dev.txt
.venv/bin/python history/transmitter_history.py history/reviewed_history_2026-09-09.json
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .venv/bin/python history/transmitter_history.py \
  history/reviewed_history_2026-09-09.json --output-dir output/pdf
.venv/bin/python -m pytest -q
```

Validation and rendering use the stored files; they make no network requests.
The outputs are `output/pdf/transmitter-history-2026-09-09.pdf` (two pages),
`.png` (overview), `-cohort.png` (appendix), `-cohort.json` (all exact joins), and
`-receipt.json` (renderer, sidecar, source and output SHA256 hashes). The plot
receipt also records matplotlib's version. Different font/library versions may
produce different binary figure hashes without changing the evidence. Generated
`output/` and temporary `tmp/` renders are ignored by Git; the dated release in
`../results/transmitter_history_followup_2026-09-09/` retains reviewed outputs.

Use `pdftoppm -png` to inspect both PDF pages when changing the layout. The
2026-09-09 release was visually checked after rendering. The source dates are
calendar dates; no UTC times or time-zone assumptions are inserted.

## What the evidence establishes

The six Okanagan actors are CHBC-DT/CHKL-DT (Kelowna), CHBC-DT-1/CHKL-DT-1
(Penticton), and CHBC-DT-2/CHKL-DT-2 (Vernon). Their reference channels are
27/24, 32/30, and 20/22 respectively. The three other Canadian shutdown actors
are CITM-DT (21), CHAN-DT-6 (23), and CKTN-DT-2 (23): these are precisely the
BC shutdown-cohort rows with existing digital channels 14-36 in the
[ISED transition schedule](https://ised-isde.canada.ca/site/spectrum-management-telecommunications/en/devices-and-equipment/digital-television-dtv-transition-schedule).
K20EH-D (20, Hood River) and CIFG-DT (29, Prince George) complete the selected
questions. Reference channels do not reconstruct channel use at earlier dates.

Corus's November 2019 supplementary brief reports the shutdown of 44
rebroadcasting transmitters during **October 2018**; its January 2020 response
repeats the account. The original deletion workbook gives the exact 44 identities.
These original application files are archived here, with hashes and locators
for [application 2018-0936-0](https://services.crtc.gc.ca/pub/DocWebBroker/OpenDocument.aspx?AppNo=201809360)
and [application 2019-1119-9](https://services.crtc.gc.ca/pub/DocWebBroker/OpenDocument.aspx?AppNo=201911199).
The corresponding [CRTC 2019-209 decision](https://crtc.gc.ca/eng/archive/2019/2019-209.htm)
is dated **13 June 2019**. That administrative date is separate from the reported
shutdown month. The six Okanagan multiplex actors are absent from the 44.

All 44 exact identities match the ISED planning table. Its document date label
is 2017-04-12, but the retained bytes were retrieved on 2026-09-09; this is not
an archived 2017 capture. Taghum's independent CKTN-DT-2 row says **23 D**.
That resolves the usable reference channel without modifying the original
engineering map's malformed `CH232` label. Bowen's row has existing **39 D**
and planned **28**; Santa Rosa has existing **44 D** and planned **23**. Neither
planned channel is backfilled into the 2018 shutdown history. Phase deadlines
and secondary-operation footnotes describe the plan, not observed transitions.

The indexed [Shaw report dated 30 September 2014](https://crtc.gc.ca/eng/bcasting/ann_rep/shaw_t2.pdf)
lists October 2012 digital on-air months for the six Okanagan actors. Current
ISED records instead contain 2013 ON_AIR dates for the three CHKL identities.
Both sources remain visible; the discrepancy is unresolved. The
[4 December 2020 multiplex approval](https://crtc.gc.ca/eng/archive/2020/2020-391.htm)
and ISED's 7 October 2021 certificate-effective fields do not establish when
CHBC carriers actually stopped and CHKL multiplexes started.

**Exact service identity matters.** The [2017 CRTC list](https://crtc.gc.ca/eng/archive/2017/2017-150.htm)
contains both CHAN-DT-2 and CHAN-TV-2 at Bowen Island. The 2019 deletion identifies
the DT record; the [2020 list](https://crtc.gc.ca/eng/archive/2020/2020-71.htm)
retains the TV record. Removing DT/TV suffixes would manufacture a resumption.
These lists also do not prove two simultaneous physical carriers. An initial
2026-103 service-list lead failed source rechecking: it is an ownership notice,
not the proposed appendix. That observation is explicitly rejected in the
source sidecar and supports no figure event.

For K20EH-D, the retained FCC LMS extract identifies facility **35472**, a
suspension-notification filing, and a **16 May 2024** receipt/status date. The
[underlying notification](https://enterpriseefiling.fcc.gov/dataentry/public/tv/publicAppSearch.html?filingVersionId=25076f918f81e30b018f824b4d72034c)
was unavailable from this environment. Its actual cessation date and any later
resumption are unresolved. A current licence record or undated operator
translator list cannot fill that gap.

## Source classes and review safeguards

`reviewed_history_2026-09-09.json` binds every source to its URL, local file,
SHA256, access class and locator. The following classes remain distinct:

- **Original document:** directly retained ISED HTML and Corus application
  bytes. The Corus `.doc` and `.xls` filenames contain OOXML containers; their
  original bytes and names are preserved.
- **Derived source extract:** compact ISED/FCC records and the 44-row cohort
  extraction. They preserve parent-archive hashes. The complete bulk archives
  remain in the earlier regulatory release rather than being duplicated here.
- **Search-index observation:** primary-source text exposed by the search tool,
  with short retrieved snippets, retrieval date and source URL. These are
  research observations, not copies of the original CRTC/Shaw documents; direct
  requests returned HTTP 403. Source absence is not RF silence.

`cohort_from_workbook()` re-extracts the original Appendix A and checks all 44
ordered distinct identities. Rendering requires it to equal the stored cohort.
`schedule_records()` checks the ISED header, channel/mode fields and duplicate
callsigns. The join preserves DT/TV and suffixes. The renderer verifies reference
channels against exact source records. The event schema refuses continuous
RF/null intervals, invented time zones, narrowed month bounds and administrative
spans. It preserves the full month as `[first day, next month's first day)`;
that is date uncertainty, not a verified off interval.

## What still requires records

| Question | Concrete missing evidence |
|---|---|
| Forty-four shutdowns | Per-station shutdown day/time and subsequent restart/continuous-state history. |
| Six multiplex actors | Operator completion/rescan or engineering cutover record linking each CHBC carrier and CHKL host, with date/time and subsequent state. |
| K20EH-D | Actual suspension form contents, amendments and later resumption notices for facility 35472. |
| Discrepant on-air dates | Original operator/engineering records explaining October 2012 versus ISED's 2013 fields. |
| Allocation-level noise reference | A reviewed complete cochannel-candidate scope and independently supported states covering the observation interval for every candidate. |

No verified continuous RF intervals or allocation-null intervals are exported.
The existing RFIsher state-join contract requires timezone-aware interval bounds,
source/review hashes, independence review and complete candidate coverage for an
allocation-off claim. These calendar events do not satisfy that contract. This
work narrows transmitter identity and event leads without declaring any CANFAR
histogram a physical noise-only reference.
