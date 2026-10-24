# BarksBuds dog run seed data: Queens, Nassau, Suffolk

Built 2026-10-24 from public sources only. Unknown fields are left blank, not guessed.

- `dog_runs_li_queens.csv` / `.json`: 73 records
  - 57 dog runs/parks: Queens 16 fenced NYC Parks runs, Nassau 21, Suffolk 20
  - 16 Queens off-leash areas (unfenced, NYC Parks courtesy hours: opening–9am and 9pm–closing; MacNeil and Yellowstone 6–9am only)
- Amenity fields use `yes` / `no` / `partial` / `seasonal` / `nearby` / `minimal`, or blank when the source is silent.
- `coord_source` says where each lat/lng came from. Queens values are centroids of NYC Open Data polygons. Long Island values are OpenStreetMap Nominatim geocodes, either an address point or a park centroid. Check every pin before launch.

Sources:
- NYC Open Data Dog Runs (hxx3-bwgv)
- NYC Parks DPR_DogRuns_001.json
- Nassau County Dog Runs page
- Town of Hempstead and Town of Oyster Bay dog park pages
- Suffolk County Parks Dog Parks page
- Brookhaven Pooch Pass PDF
- Huntington, Great Neck Park District, Manorhaven, Long Beach and Valley Stream official pages
- LI-DOG Nassau and Suffolk listings
- News 12, Suffolk Times, and BringFido (flagged where used)

The exact source for each row is in `source_url` / `source_url_2`.
