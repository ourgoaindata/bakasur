# The master-sheet CSV

`run_*.master.csv` (and `bakasur export-master`) lays out each change-of-zone record the way the
"Substantive Objections" tab of the 39A master sheet does, so the rows can be pasted under its
header. Code: [`sinks/master.py`](../src/bakasur/usecases/land_conversion_39a/sinks/master.py).

- NDZ records are left out, as in the other outputs.
- Records held for review are left out too; they're in `run_*.review.json`.
- Sr No starts at 1 in every file. It isn't the gazette's Sr. No.

## Where each column comes from

| Column | Source |
|---|---|
| Taluka, Rev Village, Name of Applicant | The gazette table |
| S. No. / Sub -Div | The survey cell, split: `74/1, Plot No. 16 (Part)` gives `74/1` and `(part) (plot 16)` |
| Old Zone (Primary) | Every land use in "Published land use", in order. Orchard and Natural Cover are `A-2`, cultivable land and paddy `A-1`, forest `FOREST`, settlement `S-2`/`S-3`. A code printed in the gazette, such as `(S4)`, is used as printed. |
| Old Zone -2 (eco zone) | Overlays named in the same cell: `NC`, `NDS`, `CADA`, `DMS`, `CRZ` (from "HTL"), `Nallah`, `Road` |
| New Zone | "Proposed land use" coded the same way. Settlement is `S-2` in a VP1 village and `S-3` in a VP2 village. |
| VP, AC | The panchayat and assembly constituency from the village list (below) |
| Area requested | "Area proposed" |
| Area recommended | The areas the decision lists ("an area of 405m2 from ..."), summed. If it lists none, the area proposed. |
| Deadline | Gazette date + 30 days |
| Gazette link | `SIII No 28` / `39A/(77)/2026/1114` / `dtd 7-Oct-2026`, as text. The `dtd` date is where the notification is signed ("Panaji, 7th October, 2026."). |
| Gaz Date | The publication date on the masthead ("Panaji, 08th October, 2026 (Asvina ...)"); the filename if the masthead can't be read |
| Total Plot Area | "Total Area (...)" in the published land use |
| TCP Comments | One line per area changed, then "For being within permissible gradient" and "Subject to comments from ..." (Water Resources Department is shortened to WRD) |

The rest (Objection Letter, Signed by?, Screen Shot of Zoning, Co ordinates, Plan and the
inspection notes) are filled by the team and left blank.

Areas are written as in the sheet, `1,777 sqm`, and keep decimals: `199.56 sqm`. Dates are
written `8-October-26`.

## The village list

[`data/goa_villages.csv`](../src/bakasur/data/goa_villages.csv) is a copy of the team's
[List of all Villages in Goa](http://docs.google.com/spreadsheets/d/1kUgWTyYupO3zgR4_-897WXCXaJuWRMJEBJnOudXEdo0/edit),
one row per panchayat, matched on taluka and village (Boma is in both Ponda and Sanguem).
Changes from the sheet:

- Spelling slips fixed: Rachel → Rachol, Magoa → Nagoa, Savador do Mundo → Salvador do Mundo, and similar.
- `survey_ranges` holds the survey numbers of villages split between panchayats, taken from the
  sheet's "(part) means?" notes. Calangute S. Nos 50-84 belong to Candolim panchayat; other S. Nos go
  to the panchayat with no range listed.
- `village_constituency` holds the few villages whose constituency differs from their panchayat's,
  for example Panelim (Panaji).

Gazette spellings that differ from the list (Boma for Bhoma, Arvalem for Arvelem) are in
`VILLAGE_ALIASES` in [`normalize/villages.py`](../src/bakasur/usecases/land_conversion_39a/normalize/villages.py).

When the list has no VP1/VP2 status for a village (municipal and ODP areas), New Zone says
`Settlement`. When the village isn't in the list, VP and AC are blank.

## Checked against the master sheet

On OG19 (`39A/(70)`) and OG21 (`39A/(72)`) the output matches what the team typed for areas,
recommended areas, S-2/S-3, VP and AC, except where the village list and the master sheet disagree:

| Village | Village list | Master sheet |
|---|---|---|
| Dhargalim (Pernem) | VP1, so S-2 | S-3 |
| Curti (Ponda) | AC Ponda | AC Priol |
| Camurlim (Salcete) | AC Cuncolim | AC Nuvem |

The CSV follows the village list. The list needs correcting wherever the master sheet is right.
