# BarksBuds dog run seed data: NYC (all five boroughs), Long Island, Westchester

Built 2026-10-24 from public sources only. Unknown fields are left blank, not guessed.

- `dog_runs_region.csv` / `.json`: 221 records (replaces `dog_runs_li_queens.*`)

| Area | Dog runs/parks | Off-leash areas | Pinned | No pin |
|---|---|---|---|---|
| Manhattan | 39 | 3 | 42 | 0 |
| Brooklyn | 19 | 21 | 40 | 0 |
| Bronx | 17 | 12 | 29 | 0 |
| Queens | 16 | 16 | 32 | 0 |
| Staten Island | 5 | 11 | 16 | 0 |
| Nassau | 21 | 0 | 19 | 2 |
| Suffolk | 20 | 0 | 18 | 2 |
| Westchester | 20 | 1 | 20 | 1 |
| **Total** | **157** | **64** | **216** | **5** |

- NYC off-leash areas are unfenced, with NYC Parks courtesy hours: opening–9am and 9pm–closing. Exceptions noted per row: MacNeil, Yellowstone and Snug Harbor are 6–9am only; Randalls Island is before 9am and after 9pm; South Beach is on sand only between Labor Day and Memorial Day. The Westchester off-leash row is Rye Town Park (unfenced, permit required).
- Westchester County Parks require dogs on leash and have no county-run off-leash parks, so Westchester rows are city, town and village dog parks, plus one private one (Ridge Hill). Mount Vernon and Scarsdale have no public dog park we could confirm.
- Amenity fields use `yes` / `no` / `partial` / `seasonal` / `nearby` / `minimal`, or blank when the source is silent.
- `coord_source` says where each lat/lng came from:
  - "Centroid of NYC Open Data dog run polygon" is the run itself.
  - "Centroid of NYC Parks property polygon" is the whole park (NYC off-leash areas and runs with no polygon). It is approximate.
  - US Census geocoder and OpenStreetMap Nominatim results are address points or park centroids. They are approximate. Check every pin before launch.
- NYC neighborhoods for the four boroughs added in this version come from an OpenStreetMap reverse geocode of the pin, and are blank where OSM has none.

Sources:
- NYC Open Data Dog Runs (hxx3-bwgv), NYC Parks Properties (enfh-gkve), NYC Parks DPR_DogRuns_001.json
- Nassau County, Town of Hempstead, Town of Oyster Bay and Suffolk County Parks dog park pages; Brookhaven Pooch Pass PDF
- Official city/town/village pages: White Plains, Greenburgh, New Rochelle, Port Chester, Mamaroneck, Peekskill, Cortlandt, Yorktown, Somers, Croton-on-Hudson, Bedford, Sleepy Hollow, Pleasantville, Yonkers
- LI-DOG, Suburbs 101, Yonkers Times, Rye Record, MyHometownBronxville, BringFido and others (flagged in `notes` where used)

The exact source for each row is in `source_url` / `source_url_2`.
