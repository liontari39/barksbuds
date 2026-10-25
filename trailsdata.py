"""Dog-friendly hiking trails in NYC, Long Island and Westchester.

Every entry was checked against an official park or agency page on CHECKED. Rules here are summaries; the
official page and posted signs always win. Only add a trail when an official source says dogs are allowed there,
and only list distance, difficulty, parking and fees the official source states. Leave a field as "" if unknown.

Deliberately left out (dogs not allowed on trails per official rules): Nassau County parks and preserves (dogs only in
county dog runs), Forest Park trails/natural areas (NYC Parks), Westchester County nature preserves and sanctuaries,
the Jamaica Bay Wildlife Refuge (Gateway), and Long Island state parks not on the State Parks dog list (e.g. Caumsett,
Cold Spring Harbor, Connetquot). Pins are approximate trailhead/area locations from OpenStreetMap.
"""

CHECKED = "2026-10-24"

REGIONS = [("nyc", "New York City"), ("li", "Long Island"), ("wch", "Westchester")]
REGION_LABEL = dict(REGIONS)

# Shared official rule summaries and sources --------------------------------------------------------------
NYC_DOGS = "NYC Parks: dogs must be on a leash no longer than 6 ft (off-leash only in dog runs and designated off-leash areas during posted hours). Carry proof of license and rabies vaccination."
NYC_DOG_SRC = ("NYC Parks dog rules", "https://www.nycgovparks.org/facilities/dogareas")
NYS_DOGS = "NY State Parks: leash no longer than 6 ft (retractables included), up to 2 pets per person in day-use areas; staff may ask for proof of rabies vaccination. No pets in buildings, playgrounds, pools, boardwalks or guarded beaches."
NYS_DOG_SRC = ("NY State Parks pet regulation (9 NYCRR 377.2)", "https://www.law.cornell.edu/regulations/new-york/9-NYCRR-377.2")
LI_DOGS = "Long Island State Parks: dogs allowed only in the specific areas listed for this park, on a leash no longer than 6 ft. Not in buildings, camping, bathing or picnic areas, or on improved walks and boardwalks."
LI_DOG_SRC = ("Walking Your Dog in Long Island State Parks (PDF)", "https://parks.ny.gov/sites/default/files/2025-11/Walking%20Your%20Dog.pdf")
WCH_DOGS = "Westchester County Parks: dogs must be leashed (6 ft max), up to 3 dogs per person. Not allowed in picnic areas, playgrounds or county nature preserves and sanctuaries."
WCH_DOG_SRC = ("Westchester County Parks rules", "https://parks.westchestercountyny.gov/be-informed/overview")
SC_DOGS = "Suffolk County Parks: dogs on a leash no longer than 6 ft; carry proof of vaccination. Not in buildings, picnic or swimming areas, or where signs say no."
SC_DOG_SRC = ("Suffolk County Parks rules", "https://www.suffolkcountyny.gov/Departments/Parks/Rules-and-Regulations")
NPS_DOGS = "Gateway National Recreation Area: pets allowed on multi-use paths, sidewalks and paved roads, on a leash at all times."
NPS_DOG_SRC = ("Gateway pets page (NPS)", "https://www.nps.gov/gate/planyourvisit/pets.htm")

NYC_BEACH = "No dogs on NYC beach sand during the beach season; dogs may go on the sand from October 2 to the Friday before Memorial Day."

PELHAM = "https://www.nycgovparks.org/park-features/hiking/pelham-bay-park"
VCP = "https://www.nycgovparks.org/park-features/hiking/van-cortlandt-park"
GREENBELT = "https://www.nycgovparks.org/park-features/hiking/greenbelt"
GB_MAP = ("Greenbelt trail map (PDF)", "https://www.nycgovparks.org/sub_your_park/vt_the_greenbelt/images/trailmap_brochure.pdf")

TRAILS = [
    # ---------------------------------------------------------------- New York City
    dict(slug="kazimiroff-nature-trail", name="Kazimiroff Nature Trail", park="Pelham Bay Park", region="nyc", area="Bronx",
         lat=40.87446, lng=-73.78867, dogs=NYC_DOGS, distance="Blue loop 1.24 mi; Red loop 0.94 mi", difficulty="",
         parking="Orchard Beach area (the trail is on Hunter Island, next to Orchard Beach).",
         restrictions=[NYC_BEACH], sources=[("NYC Parks: Pelham Bay Park hiking", PELHAM), NYC_DOG_SRC]),
    dict(slug="siwanoy-trail", name="Siwanoy Trail", park="Pelham Bay Park", region="nyc", area="Bronx",
         lat=40.86562, lng=-73.80537, dogs=NYC_DOGS, distance="More than 3 mi", difficulty="",
         parking="", restrictions=[NYC_BEACH], sources=[("NYC Parks: Pelham Bay Park hiking", PELHAM), NYC_DOG_SRC]),
    dict(slug="cass-gallagher-nature-trail", name="Cass Gallagher Nature Trail", park="Van Cortlandt Park", region="nyc", area="Bronx",
         lat=40.90426, lng=-73.89208, dogs=NYC_DOGS, distance="1.4 mi", difficulty="Moderate",
         parking="", restrictions=[], access="A short walk from Broadway and Mosholu Avenue, near the horse stables.",
         sources=[("NYC Parks: Van Cortlandt Park hiking", VCP), NYC_DOG_SRC]),
    dict(slug="john-muir-trail", name="John Muir Trail", park="Van Cortlandt Park", region="nyc", area="Bronx",
         lat=40.90117, lng=-73.88360, dogs=NYC_DOGS, distance="About 2 mi, crossing the park east to west", difficulty="",
         parking="", restrictions=[], sources=[("NYC Parks: Van Cortlandt Park hiking", VCP), NYC_DOG_SRC]),
    dict(slug="old-croton-aqueduct-trail-van-cortlandt", name="Old Croton Aqueduct Trail (Van Cortlandt section)", park="Van Cortlandt Park",
         region="nyc", area="Bronx", lat=40.90464, lng=-73.88247, dogs=NYC_DOGS, distance="2.3 mi", difficulty="Easy to moderate",
         parking="", access="Enter at Dickinson Avenue and Van Cortlandt Park South, or at Mosholu Parkway and West Gun Hill Road.",
         restrictions=[], sources=[("NYC Parks: Van Cortlandt Park hiking", VCP), NYC_DOG_SRC]),
    dict(slug="john-kieran-nature-trail", name="John Kieran Nature Trail", park="Van Cortlandt Park", region="nyc", area="Bronx",
         lat=40.89389, lng=-73.89100, dogs=NYC_DOGS, distance="0.8 mi", difficulty="", parking="", restrictions=[],
         access="Loops through the lake area and freshwater wetlands near the Parade Ground.",
         sources=[("NYC Parks: Van Cortlandt Park hiking", VCP), NYC_DOG_SRC]),
    dict(slug="inwood-hill-park-trails", name="Inwood Hill Park trails (Orange, Blue, White)", park="Inwood Hill Park", region="nyc", area="Manhattan",
         lat=40.87227, lng=-73.92543, dogs=NYC_DOGS,
         distance="Orange 1.7 mi; Blue 1.7 mi (paved); White 1.5 mi", difficulty="Orange moderate to vigorous; Blue moderate; White easy",
         parking="", restrictions=[], sources=[("NYC Parks: Inwood Hill Park hiking", "https://www.nycgovparks.org/park-features/hiking/inwood-hill-park"), NYC_DOG_SRC]),
    dict(slug="riverdale-park-trails", name="Riverdale Park Red and Blue Trails", park="Riverdale Park", region="nyc", area="Bronx",
         lat=40.89671, lng=-73.91327, dogs=NYC_DOGS, distance="Red just under 1 mi; Blue 0.6 mi", difficulty="",
         parking="Parking lot at Spaulding Lane (Red Trail start); also an entrance at West 254th Street.", restrictions=[],
         sources=[("NYC Parks: Riverdale Park hiking", "https://www.nycgovparks.org/park-features/hiking/riverdale-park"), NYC_DOG_SRC]),
    dict(slug="greenbelt-blue-trail", name="Greenbelt Blue Trail", park="Staten Island Greenbelt", region="nyc", area="Staten Island",
         lat=40.59041, lng=-74.13084, dogs=NYC_DOGS + " The Greenbelt trail map asks you to keep your pet leashed.",
         distance="9.3 mi (the Greenbelt's longest trail)", difficulty="Easy to moderate",
         parking="Street parking at the Brielle Avenue start and at the Deere Park end.", restrictions=[],
         sources=[("NYC Parks: Greenbelt hiking", GREENBELT), GB_MAP, NYC_DOG_SRC]),
    dict(slug="greenbelt-white-trail", name="Greenbelt White Trail", park="Staten Island Greenbelt", region="nyc", area="Staten Island",
         lat=40.58217, lng=-74.14401, dogs=NYC_DOGS + " The Greenbelt trail map asks you to keep your pet leashed.",
         distance="Nearly 6 mi across three Greenbelt parks", difficulty="Mostly easy, sometimes moderate",
         parking="Parking is widely available at both ends.", access="Starts in Willowbrook Park and crosses Rockland Avenue into LaTourette Park.", restrictions=[],
         sources=[("NYC Parks: Greenbelt hiking", GREENBELT), GB_MAP, NYC_DOG_SRC]),
    dict(slug="cunningham-park-trails", name="Cunningham Park Orange and White Trails", park="Cunningham Park", region="nyc", area="Queens",
         lat=40.72855, lng=-73.76347, dogs=NYC_DOGS, distance="Orange loop 1.3 mi; White 1.1 mi", difficulty="",
         parking="", access="The White Trail is accessible from the corner of Union Turnpike and Francis Lewis Boulevard.", restrictions=[],
         sources=[("NYC Parks: Cunningham Park hiking", "https://www.nycgovparks.org/park-features/hiking/cunningham-park"), NYC_DOG_SRC]),
    dict(slug="great-kills-park-path", name="Great Kills Park multi-use path", park="Great Kills Park (Gateway)", region="nyc", area="Staten Island",
         lat=40.54365, lng=-74.12615, dogs=NPS_DOGS, distance="", difficulty="",
         parking="Parking at Crooke's Point requires a permit.",
         restrictions=["No pets on the Great Kills swimming beach from Memorial Day weekend through Labor Day."],
         sources=[("NPS: Great Kills Park", "https://www.nps.gov/places/000/great-kills-park.htm"), NPS_DOG_SRC]),

    # ---------------------------------------------------------------- Westchester
    dict(slug="rockefeller-state-park-preserve", name="Carriage roads and 13 Bridges Loop", park="Rockefeller State Park Preserve", region="wch",
         area="Pleasantville", lat=41.10772, lng=-73.83095, dogs=NYS_DOGS,
         distance="About 45 mi of carriage roads; 13 Bridges Loop 1.9 mi", difficulty="Wide, easy carriage roads; 13 Bridges Loop is even to moderate grade",
         parking="Vehicle fee $6, collected daily year-round 8 a.m. to 4:30 p.m. at the pay station. 125 Phelps Way (Route 117), Pleasantville. Open dawn to dusk.",
         restrictions=["Managed deer bowhunting in designated areas October through December; trails next to hunting areas are posted."],
         sources=[("NY State Parks: Rockefeller State Park Preserve", "https://parks.ny.gov/visit/state-parks/rockefeller-state-park-preserve"), NYS_DOG_SRC]),
    dict(slug="old-croton-aqueduct-state-historic-park", name="Old Croton Aqueduct Trail", park="Old Croton Aqueduct State Historic Park", region="wch",
         area="Yonkers to Cortlandt", lat=41.01165, lng=-73.87707, dogs=NYS_DOGS,
         distance="26.2 mi, from Van Cortlandt Park to the Croton Dam", difficulty="",
         parking="No parking areas of its own; street parking near the many cross streets. No charge to use the trail. Open sunrise to sunset. Pin: park office at the Keeper's House, 15 Walnut St, Dobbs Ferry.",
         restrictions=[],
         sources=[("NY State Parks: Old Croton Aqueduct SHP", "https://parks.ny.gov/visit/state-parks/old-croton-aqueduct-state-historic-park"), NYS_DOG_SRC]),
    dict(slug="ward-pound-ridge-reservation", name="Ward Pound Ridge Reservation trails", park="Ward Pound Ridge Reservation", region="wch",
         area="Cross River", lat=41.24647, lng=-73.58680, dogs=WCH_DOGS, distance="", difficulty="",
         parking="Parking $5 with a Westchester Park Pass, $10 without; charged daily Memorial Day to Labor Day and on weekends otherwise. Open 8 a.m. to dusk. Route 35 and 121 South, Cross River.",
         restrictions=[],
         sources=[("Westchester County: Ward Pound Ridge", "https://parks.westchestercountyny.gov/ward-pound-ridge-reservation"), WCH_DOG_SRC]),
    dict(slug="blue-mountain-reservation", name="Blue Mountain Reservation trails", park="Blue Mountain Reservation", region="wch",
         area="Peekskill", lat=41.26709, lng=-73.91565, dogs=WCH_DOGS, distance="", difficulty="",
         parking="Parking $5 with a Park Pass, $10 without; weekends only in May and September, daily May 23 through Labor Day (2026). 435 Welcher Avenue, Peekskill. Open 8 a.m. to dusk.",
         access="The 12-mile Briarcliff-Peekskill Trailway connects to the reservation.", restrictions=[],
         sources=[("Westchester County: Blue Mountain Reservation", "https://parks.westchestercountyny.gov/blue-mountain-reservation"), WCH_DOG_SRC]),
    dict(slug="croton-gorge-park", name="Croton Gorge Park (north end of the Old Croton Aqueduct)", park="Croton Gorge Park", region="wch",
         area="Cortlandt", lat=41.22180, lng=-73.85312, dogs=WCH_DOGS, distance="", difficulty="",
         parking="Parking $5 with a Park Pass, $10 without, cash only; weekends only in May and September, daily May 23 through Labor Day (2026). 350 Yorktown Road (Route 129), Croton-on-Hudson. Open 8 a.m. to dusk.",
         access="The Old Croton Aqueduct trail begins here.", restrictions=[],
         sources=[("Westchester County: Croton Gorge Park", "https://parks.westchestercountyny.gov/croton-gorge-park"), WCH_DOG_SRC]),

    # ---------------------------------------------------------------- Long Island
    dict(slug="hempstead-lake-state-park", name="Hempstead Lake trails and paths", park="Hempstead Lake State Park", region="li",
         area="West Hempstead (Nassau)", lat=40.68173, lng=-73.64185, dogs=LI_DOGS,
         where="All park trails and paths, including the unpaved path in the Field 3 area and by Schodack and South Ponds. Not in buildings or picnic areas.",
         distance="", difficulty="",
         parking="Vehicle fee $8, collected on set days April 4 to October 12, 2026 (weekends and holidays in spring and fall, daily in summer). Open sunrise to sunset. 1000 Lake Drive, West Hempstead.",
         restrictions=[],
         sources=[("NY State Parks: Hempstead Lake", "https://parks.ny.gov/visit/state-parks/hempstead-lake-state-park"), LI_DOG_SRC]),
    dict(slug="bethpage-state-park", name="Bethpage northwest-corner trails", park="Bethpage State Park", region="li",
         area="Farmingdale", lat=40.74846, lng=-73.46128, dogs=LI_DOGS, where="Any trails in the northwest corner of the park.",
         distance="", difficulty="",
         parking="Vehicle fee $8 on set days (2026: weekends from April 4, daily in summer, weekends through November 8). 99 Quaker Meeting House Road, Farmingdale.",
         restrictions=[],
         sources=[("NY State Parks: Bethpage", "https://parks.ny.gov/visit/state-parks/bethpage-state-park"), LI_DOG_SRC]),
    dict(slug="belmont-lake-state-park", name="Belmont Lake undeveloped trail", park="Belmont Lake State Park", region="li",
         area="North Babylon", lat=40.70864, lng=-73.32902, dogs=LI_DOGS,
         where="The undeveloped trail from the northeast corner of the parking lot to the maintenance buildings, plus the areas by the ballfields and the dog run.",
         distance="", difficulty="",
         parking="Vehicle fee $8 on set days April 4 to October 12, 2026. Southern State Parkway exit 38. The park also has a fenced dog run.",
         restrictions=["No dogs in picnic areas or playgrounds."],
         sources=[("NY State Parks: Belmont Lake", "https://parks.ny.gov/visit/state-parks/belmont-lake-state-park"), LI_DOG_SRC]),
    dict(slug="heckscher-state-park", name="Heckscher undeveloped trails", park="Heckscher State Park", region="li",
         area="East Islip", lat=40.70883, lng=-73.16578, dogs=LI_DOGS, where="Undeveloped trails west of the toll booths.",
         distance="", difficulty="",
         parking="Memorial Day to Labor Day, park behind Field 4 and walk to Field 5; Labor Day to Memorial Day, park in Field 5. Vehicle fee $8 on set days ($10 from June 27 to September 7, 2026).",
         restrictions=[],
         sources=[("NY State Parks: Heckscher", "https://parks.ny.gov/visit/state-parks/heckscher-state-park"), LI_DOG_SRC]),
    dict(slug="sunken-meadow-east-trails", name="Sunken Meadow east-end back trails", park="Sunken Meadow State Park", region="li",
         area="Kings Park", lat=40.89623, lng=-73.24388, dogs=LI_DOGS,
         where="Only the back trails and undeveloped areas at the east end of the park, reached by Old Dock Road, and the area east of the Sunken Meadow Parkway and south of Route 25A, reached from 25A.",
         distance="", difficulty="", parking="Use Old Dock Road or Route 25A access. Dogs may not come in through the park entrances.",
         restrictions=["No dogs anywhere in the main park."],
         sources=[("NY State Parks: Sunken Meadow", "https://parks.ny.gov/visit/state-parks/sunken-meadow-state-park-governor-alfred-e-smith"), LI_DOG_SRC]),
    dict(slug="brookhaven-state-park", name="Brookhaven State Park trails", park="Brookhaven State Park", region="li",
         area="Ridge", lat=40.92348, lng=-72.86626, dogs=LI_DOGS, where="All trails, on leash.",
         distance="", difficulty="",
         parking="No entrance fee. Open weekdays 8:30 a.m. to 3:30 p.m., weekends 8 a.m. to 4 p.m. 2500 William Floyd Parkway, Ridge.",
         restrictions=["Hunting season November 1 to January 31: check current signs before you go."],
         sources=[("NY State Parks: Brookhaven", "https://parks.ny.gov/visit/state-parks/brookhaven-state-park"), LI_DOG_SRC]),
    dict(slug="montauk-point-state-park", name="Montauk Point dog-friendly stretch", park="Montauk Point State Park", region="li",
         area="Montauk", lat=41.07001, lng=-71.88526, dogs=LI_DOGS,
         where="Only the area from west of the refreshment stand to just beyond Oyster Pond.", distance="", difficulty="",
         parking="Vehicle fee $8, 8 a.m. to 4 p.m. on set days (2026: weekends from April 4, daily May 23 to October 12, weekends and holidays to November 11).",
         restrictions=["Hunting is allowed on weekdays in winter (deer season from November 1); check the park page before you go."],
         sources=[("NY State Parks: Montauk Point", "https://parks.ny.gov/visit/state-parks/montauk-point-state-park"), LI_DOG_SRC]),
    dict(slug="shadmoor-state-park", name="Shadmoor bluff trails", park="Shadmoor State Park", region="li",
         area="Montauk", lat=41.03872, lng=-71.92735, dogs=LI_DOGS, where="Park wide.", distance="", difficulty="",
         parking="No parking fee. 900 Montauk Highway, Montauk.", restrictions=[],
         sources=[("NY State Parks: Shadmoor", "https://parks.ny.gov/visit/state-parks/shadmoor-state-park"), LI_DOG_SRC]),
    dict(slug="camp-hero-state-park", name="Camp Hero trails", park="Camp Hero State Park", region="li",
         area="Montauk", lat=41.06241, lng=-71.87771, dogs=LI_DOGS, where="Undeveloped areas that are open to the public.",
         distance="", difficulty="",
         parking="Vehicle fee $8, 8 a.m. to 4 p.m. on set days (2026: weekends from April 4, daily May 23 to October 12, weekends and holidays to November 11).",
         restrictions=[],
         sources=[("NY State Parks: Camp Hero", "https://parks.ny.gov/visit/state-parks/camp-hero-state-park"), LI_DOG_SRC]),
    dict(slug="blydenburgh-county-park", name="Stump Pond loop", park="Blydenburgh County Park", region="li",
         area="Smithtown", lat=40.83571, lng=-73.22324, dogs=SC_DOGS + " The park page invites dog owners to hike with their dogs.",
         distance="5.7 mi loop around Stump Pond", difficulty="",
         parking="Main entrance on Veterans Memorial Highway, Smithtown. The New Mill Road entrance and its parking lot have been closed since August 2024. The park also has a dog run.",
         restrictions=[],
         sources=[("Suffolk County: Blydenburgh County Park", "https://www.suffolkcountyny.gov/Departments/Parks/Our-Parks/Blydenburgh-County-Park"), SC_DOG_SRC]),
    dict(slug="west-hills-walt-whitman-trail", name="Walt Whitman Trail to Jayne's Hill", park="West Hills County Park", region="li",
         area="Melville", lat=40.80868, lng=-73.42954, dogs=SC_DOGS,
         distance="", difficulty="",
         parking="For hiking, use the north entrance off Sweet Hollow Road, Melville.",
         access="Climbs to Jayne's Hill, Long Island's highest point (400 ft).", restrictions=[],
         sources=[("Suffolk County: West Hills County Park", "https://www.suffolkcountyny.gov/Departments/Parks/Our-Parks/West-Hills-County-Park"), SC_DOG_SRC]),
]

for _t in TRAILS:
    for _k in ("where", "access"):
        _t.setdefault(_k, "")

BY_SLUG = {t["slug"]: t for t in TRAILS}
