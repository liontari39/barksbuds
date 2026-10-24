#!/bin/sh
# Print all waitlist signups as CSV (also always mirrored at data/waitlist.csv)
cd "$(dirname "$0")" && sqlite3 -header -csv data/waitlist.db "SELECT * FROM signups ORDER BY id" 2>/dev/null || cat data/waitlist.csv
