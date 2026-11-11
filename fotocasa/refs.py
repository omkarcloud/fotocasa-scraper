"""Reference resolvers, id tables and path builders for /fotocasa/*.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair):

    property    a numeric ad id (184433815) OR any fotocasa.es listing link
                (…/<id>/d, or a new-build unit …/obra-nueva/<loc>/<promo>/<id>)
    promotion   a numeric new-development id (20678485) OR its
                …/obra-nueva/<loc>/<id> link
    agency      a minisite slug (fortuny-madrid-real-estate), a numeric
                client id (9202757120653), a /pro/<slug>/ link, an
                /inmobiliarias/<alias>-<clientId> link or a listing link
                carrying ?clientId=
    location    a place name ("Madrid", "Barrio de Salamanca"), a combined
                location id from locations/search ("724,14,28,173,0,28079,0,0,0"),
                an area slug for a street / urbanisation
                ("calle-serrano-madrid-capital") OR any fotocasa.es search link

The id tables are the site's own enums, read from its main JS bundle
(frtassets.fotocasa.es/_sui/main.6431425e.js) and from live pages on
2026-11-07: transaction and property types, subtypes, conservation states,
the feature ids the search gateway filters on, floors (derived from 15
detail pages whose cards carried distinct floor ids), publication-date
windows and sort keys.
"""
import re
from urllib.parse import parse_qs, unquote, urlparse

SITE = "https://www.fotocasa.es"
GATEWAY = "https://web.gw.fotocasa.es"          # /v2/propertysearch/search, /v1/propertysearch/locationliterals
SEARCH_GATEWAY = "https://search.gw.fotocasa.es"  # /v1/suggest

CURRENCY = "EUR"
ITEMS_PER_PAGE = 30          # the site's own page size (HTML pages always; the gateway's default)
MAX_PAGE_SIZE = 400          # the gateway honours size up to 400 (500 falls back to 30; research 2026-11-07)
GATEWAY_WINDOW = 9960        # the gateway serves rows 1-9,960 of a search; a page ending past ~9,970 comes back
                             # as an unrelated 30-row fallback page (probed 2026-11-10: page 99 x 100 ok,
                             # 100 x 100 / 25 x 400 / 333 x 30 fallback)
HTML_MAX_PAGES = 333         # the HTML list pages stop at 10,000 rows (page 334 serves page 333 again)
DIRECTORY_ITEMS_PER_PAGE = 15
AGENCY_PAGE_ITEMS = 15       # the minisite's own listing page

LANGUAGES = {"es": "es-ES", "en": "en-GB", "ca": "ca-ES", "de": "de-DE"}
DEFAULT_LANGUAGE = "es"

# transactionTypeId (JS: BUY 1, RENT 3, TRANSFER 4, SHARE 5, RENT_WITH_BUY_OPTION 7,
# VACATIONAL 8 — the gateway answers 0 rows for 8, so it is not offered)
TRANSACTIONS = {"buy": 1, "rent": 3, "share": 5, "rent_to_buy": 7, "transfer": 4}
TRANSACTION_NAMES = {v: k for k, v in TRANSACTIONS.items()}
TRANSACTION_NAMES[8] = "holiday_rental"

# propertyTypeId (JS: NEW_HOME 1, HOMES 2, GARAGE 3, LAND 4, PREMISES 5,
# OFFICE 6, BOX_ROOM 7, BUILDING 8, PROMOTIONS 9 — 1 and 9 answer 0 rows on
# the gateway; new builds are homes with isNewConstruction=true)
PROPERTY_TYPES = {"homes": 2, "garages": 3, "land": 4, "premises": 5, "offices": 6,
                  "storage_rooms": 7, "buildings": 8}
PROPERTY_TYPE_NAMES = {v: k for k, v in PROPERTY_TYPES.items()}
PROPERTY_TYPE_NAMES[1] = "new_homes"
PROPERTY_TYPE_NAMES[9] = "promotions"

# propertySubtypeIds (JS IqTA table)
SUBTYPES = {
    "flat": 1, "apartment": 2, "house": 3, "semi_detached": 5, "penthouse": 6, "duplex": 7,
    "loft": 8, "rural_house": 9, "ground_floor": 52, "studio": 54,
    "commercial_store": 0, "industrial_land": 13, "land": 14, "industrial_building": 16,
    "residential_land": 58, "constructible_land": 59, "non_constructible_land": 60,
}
SUBTYPE_NAMES = {v: k for k, v in SUBTYPES.items()}

# conservationStatusIds (JS l9s2 table)
CONDITIONS = {"almost_new": 1, "very_good": 2, "good": 3, "needs_renovation": 4,
              "refurbished": 8, "new_build": 10}
CONDITION_NAMES = {v: k for k, v in CONDITIONS.items()}

# featureIds (JS n0nu table; the public names are ours)
FEATURES = {
    "air_conditioning": 1, "wardrobes": 2, "heating": 3, "parking": 5, "garden": 7,
    "parquet": 9, "terrace": 10, "storage_room": 11, "community_area": 12, "lift": 13,
    "yard": 16, "swimming_pool": 17, "furnished": 19, "not_furnished": 130, "kitchen": 20,
    "appliances": 21, "community_parking": 26, "porter": 28, "balcony": 32, "jacuzzi": 36,
    "pets_allowed": 49, "internet": 52, "cellar": 56, "sauna": 62, "golf": 65, "alarm": 77,
    "solar_energy": 80, "video_intercom": 81, "armored_door": 84, "community_pool": 94,
    "laundry": 109, "seafront": 120, "mountain_views": 121, "guest_bathroom": 122,
    "equipped_kitchen": 131, "sea_views": 133, "home_automation": 79, "smoke_outlet": 100,
    "loading_area": 90, "access_24_7": 88, "community_fees_included": 106,
}
FEATURE_NAMES = {v: k for k, v in FEATURES.items()}

# Every amenity id the site knows (JS n0nu table, 82 ids) -> the name the
# responses use. Ids that are also search filters keep the filter's name, so
# an `amenities` value can be passed back as a `features` value.
AMENITIES = {
    **FEATURE_NAMES,
    4: "ceramic_floor", 6: "stoneware_floor", 8: "satellite_dish", 14: "carpet", 15: "kitchen_office",
    18: "ensuite_bathroom", 22: "oven", 23: "washing_machine", 24: "microwave", 25: "fridge", 27: "dryer",
    29: "tv", 30: "dvd_player", 31: "heat_pump", 42: "gym", 70: "tennis_court", 82: "sports_area",
    83: "childrens_area", 85: "video_surveillance", 86: "storage_room_access_code", 87: "storage_room_alarm",
    89: "free_parking", 91: "free_moving_van", 92: "free_transport", 95: "girls_only", 96: "boys_only",
    97: "non_smokers_only", 98: "automatic_door", 99: "private_security", 101: "hot_water",
    107: "deposit_under_two_months", 118: "deposit_required", 119: "interior_lift", 123: "guest_house",
    124: "laundry_room", 125: "service_room", 126: "designer_furniture", 127: "ambient_music",
    128: "covered_porch", 129: "cinema_room", 161: "professional_report",
}

# otherIds (JS Y42G table)
OTHER_FLAGS = {"bank_owned": 1, "with_photos": 2, "with_video": 3, "price_drop": 8,
               "subsidized": 9, "quality_seal": 10}

PUBLISHED = {"last_24_hours": "ONE_DAY", "last_48_hours": "TWO_DAYS", "last_week": "ONE_WEEK",
             "last_month": "ONE_MONTH"}

RENTAL_DURATIONS = {"long_term": "LONG_TERM", "temporary": "TEMPORARY"}

# public sort -> (sortType, sortOrderDesc)
SORTS = {
    "relevance": ("scoring", True), "newest": ("publicationDate", True),
    "oldest": ("publicationDate", False), "price_asc": ("price", False),
    "price_desc": ("price", True), "size_asc": ("surface", False), "size_desc": ("surface", True),
    "price_per_m2_asc": ("pricem2", False), "price_per_m2_desc": ("pricem2", True),
}

# feature "floor" ids on search cards -> the site's own floor names (detail
# pages print them decoded: 15 ids read on 2026-11-07; 16-20 interpolated
# between the 10th floor and "10TH_OR_MORE" = from the 15th)
FLOORS = {
    1: "basement", 2: "semi_basement", 3: "ground_floor", 4: "mezzanine", 5: "principal",
    6: "1st_floor", 7: "2nd_floor", 8: "3rd_floor", 9: "4th_floor", 10: "5th_floor",
    11: "6th_floor", 12: "7th_floor", 13: "8th_floor", 14: "9th_floor", 15: "10th_floor",
    16: "11th_floor", 17: "12th_floor", 18: "13th_floor", 19: "14th_floor", 20: "15th_floor",
    21: "15th_floor_or_above", 32: "penthouse",
}

ORIENTATIONS = {1: "north", 2: "north_east", 3: "north_west", 4: "south", 5: "south_east",
                6: "south_west", 7: "east", 8: "west"}
ANTIQUITIES = {1: "less_than_1_year", 2: "1_to_5_years", 3: "5_to_10_years", 4: "10_to_20_years",
               5: "20_to_30_years", 6: "30_to_50_years", 7: "50_to_70_years", 8: "70_to_100_years",
               9: "more_than_100_years"}
HEATINGS = {1: "natural_gas", 2: "electricity"}
ENERGY_RATINGS = {1: "A", 2: "B", 3: "C", 4: "D", 5: "E", 6: "F", 7: "G"}
PERIODICITIES = {0: None, 1: "day", 2: "week", 3: "month", 4: "fortnight", 8: "season", 9: "year"}
ADVERTISER_TYPES = {1: "private", 3: "professional"}

# location levels of the suggest API -> our names
LOCATION_LEVELS = {
    "COUNTRY": "country", "AUTONOMOUS_COMMUNITY": "autonomous_community", "PROVINCE": "province",
    "AREA": "area", "REGION": "region", "MUNICIPALITY": "municipality", "LOCALITY": "locality",
    "DISTRICT": "district", "NEIGHBORHOOD": "neighborhood", "URBANIZATION": "urbanization",
    "COAST": "coast", "GEOGRAPHICAL_AREA": "geographical_area", "STREET": "street",
    "ZIP_CODE": "zip_code",
}

# the HTML search-page URL segments (Spanish site) per transaction / property type
_URL_TRANSACTION = {"buy": "comprar", "rent": "alquiler", "share": "compartir",
                    "rent_to_buy": "alquiler-con-opcion-a-compra", "transfer": "traspaso"}
_URL_PROPERTY = {"homes": "viviendas", "garages": "garajes", "land": "terrenos", "premises": "locales",
                 "offices": "oficinas", "storage_rooms": "trasteros", "buildings": "edificios"}
# every spelling the four site languages use for a list page's first two segments
_LINK_TRANSACTIONS = {
    "comprar": "buy", "buy": "buy", "kaufen": "buy",
    "alquiler": "rent", "rent": "rent", "lloguer": "rent", "mieten": "rent",
    "compartir": "share", "share": "share", "teilen": "share",
    "alquiler-con-opcion-a-compra": "rent_to_buy", "rent-with-option-to-buy": "rent_to_buy",
    "lloguer-amb-opcio-a-compra": "rent_to_buy", "mieten-mit-kaufoption": "rent_to_buy",
    "traspaso": "transfer", "transfer": "transfer", "traspas": "transfer", "ubernahme": "transfer",
}
_LINK_PROPERTIES = {
    "viviendas": "homes", "homes": "homes", "habitatges": "homes", "wohnimmobilien": "homes",
    "pisos": "homes", "casas": "homes", "aticos": "homes", "duplex": "homes", "estudios": "homes",
    "lofts": "homes", "plantas-intermedias": "homes", "apartamentos": "homes",
    "garajes": "garages", "garages": "garages", "garatges": "garages", "garagen": "garages",
    "terrenos": "land", "land": "land", "terrenys": "land", "grundstucke": "land",
    "locales": "premises", "premises": "premises", "locals": "premises", "gewerbeflachen": "premises",
    "naves": "premises", "oficinas": "offices", "offices": "offices", "oficines": "offices", "buros": "offices",
    "trasteros": "storage_rooms", "box-rooms": "storage_rooms", "trasters": "storage_rooms",
    "abstellraume": "storage_rooms", "edificios": "buildings", "buildings": "buildings",
    "edificis": "buildings", "gebaude": "buildings",
}

_ID_RE = re.compile(r"^[0-9]{5,12}$")
_CLIENT_ID_RE = re.compile(r"^[0-9]{10,16}$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_COMBINED_RE = re.compile(r"^[0-9]+(?:,[0-9]+){8}$")
_AREA_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")
_DETAIL_RE = re.compile(r"/([0-9]{5,12})/d(?:/|$)")
_UNIT_RE = re.compile(r"/(?:obra-nueva|obra-nova|new-home|neubau)/[^/]+/([0-9]{4,12})/([0-9]{5,12})(?:/|$)")
_PROMOTION_RE = re.compile(r"/(?:obra-nueva|obra-nova|new-home|neubau)/[^/]+/([0-9]{4,12})(?:/|$)")
_PRO_RE = re.compile(r"/pro/([a-z0-9][a-z0-9-]*)(?:/|$)")
_INMOBILIARIAS_RE = re.compile(r"/inmobiliarias/[a-z0-9-]*?-?([0-9]{10,16})(?:/|$)")
_AREA_PATH_RE = re.compile(r"/area/([a-z0-9-]+)/l(?:/([0-9]+))?(?:/|$)")
_LIST_PATH_RE = re.compile(r"^/([a-z]{2})/([a-z-]+)/([a-z-]+)/([a-z0-9-]+)/([a-z0-9-]+)(?:/([a-z0-9-]+))?/l(?:/([0-9]+))?/?$")
_PRICE_INDEX_RE = re.compile(r"/indice-precio-vivienda/([a-z0-9-]+)(?:/([a-z0-9-]+))?(?:/|$)")
_DIRECTORY_RE = re.compile(r"/buscar-agencias-inmobiliarias/([a-z0-9-]+)(?:/([a-z0-9-]+))?(?:/l)?(?:/|$)")


# ---- links ---------------------------------------------------------------------

def _is_link(value):
    return value.startswith(("http://", "https://", "//", "www.fotocasa.es", "fotocasa.es"))


def _as_url(value):
    if value.startswith("//"):
        return "https:" + value
    if value.startswith(("www.", "fotocasa.es")):
        return "https://" + value
    return value


def _host_ok(url):
    host = (urlparse(url).hostname or "").lower()
    return host == "fotocasa.es" or host.endswith(".fotocasa.es")


def parse_site_link(value):
    """A fotocasa.es link -> (path, query dict of single values). ValueError
    for another site."""
    url = _as_url(value.strip())
    if not _host_ok(url):
        raise ValueError("Must be a fotocasa.es link.")
    parsed = urlparse(url)
    path = unquote(parsed.path or "/").rstrip("/") or "/"
    query = {k: v[0] for k, v in parse_qs(parsed.query, keep_blank_values=False).items()}
    return path, query


def absolute(path):
    if not path:
        return None
    if path.startswith("http"):
        return path
    return SITE + path


# ---- resolvers (RefField) ------------------------------------------------------

def resolve_property(value):
    """Bare ad id or any fotocasa.es listing link -> the id (string)."""
    value = (value or "").strip()
    if _ID_RE.match(value):
        return value
    if _is_link(value):
        path, _query = parse_site_link(value)
        match = _UNIT_RE.search(path)
        if match:
            return match.group(2)
        match = _DETAIL_RE.search(path)
        if match:
            return match.group(1)
        raise ValueError("Must be a fotocasa.es listing link (…/<id>/d) or a numeric listing id.")
    raise ValueError("Must be a numeric fotocasa listing id (184433815) or a fotocasa.es listing link.")


def resolve_promotion(value):
    """Bare new-development id or its …/obra-nueva/<location>/<id> link -> the id."""
    value = (value or "").strip()
    if re.match(r"^[0-9]{4,12}$", value):
        return value
    if _is_link(value):
        path, _query = parse_site_link(value)
        match = _PROMOTION_RE.search(path)
        if match:
            return match.group(1)
        raise ValueError("Must be a fotocasa.es new-development link (…/comprar/obra-nueva/<location>/<id>).")
    raise ValueError("Must be a numeric fotocasa new-development id (20678485) or its fotocasa.es link.")


def resolve_agency(value):
    """Minisite slug, numeric client id, /pro/<slug>/ link, /inmobiliarias/
    <alias>-<clientId> link or a listing link with ?clientId= -> the slug or
    ("client", id). The schema keeps the raw form; api.py resolves a client
    id to its minisite through the gateway."""
    value = (value or "").strip()
    if _CLIENT_ID_RE.match(value):
        return {"client_id": value}
    if _is_link(value):
        path, query = parse_site_link(value)
        match = _PRO_RE.search(path)
        if match:
            return {"slug": match.group(1)}
        match = _INMOBILIARIAS_RE.search(path)
        if match:
            return {"client_id": match.group(1)}
        if query.get("clientId") and _CLIENT_ID_RE.match(query["clientId"]):
            return {"client_id": query["clientId"]}
        raise ValueError("Must be a fotocasa.es agency link (…/pro/<slug>/ or …/inmobiliarias/<name>-<clientId>).")
    slug = value.lower()
    if _SLUG_RE.match(slug):
        return {"slug": slug}
    raise ValueError("Must be an agency slug (fortuny-madrid-real-estate), a numeric client id "
                     "or a fotocasa.es agency link.")


def classify_location(value):
    """A properties/search `location` -> (kind, value) without network:
    ("combined", "724,14,…"), ("area", "calle-serrano-madrid-capital"),
    ("link", (path, query)) or ("name", "Madrid")."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Must not be empty.")
    if _COMBINED_RE.match(value):
        return "combined", value
    if _is_link(value):
        return "link", parse_site_link(value)
    low = value.lower()
    if _AREA_SLUG_RE.match(low) and not any(c.isspace() for c in value):
        return "area", low
    return "name", value


def split_list_link(path, query):
    """A fotocasa.es search-page path -> dict(language, transaction,
    property_type, location, zone, feature, page, area) or ValueError.
    Both plain list pages (/es/comprar/viviendas/<loc>/<zone>[/<feature>]/l[/N])
    and area pages (/es/comprar/viviendas/area/<slug>/l[/N]) are accepted;
    the query string carries the filters."""
    match = _LIST_PATH_RE.match(path)
    if not match:
        raise ValueError("Must be a fotocasa.es search link (…/comprar/viviendas/<location>/<zone>/l).")
    language, tx, ptype, loc, zone, feature, page = match.groups()
    transaction = _LINK_TRANSACTIONS.get(tx)
    property_type = _LINK_PROPERTIES.get(ptype)
    if transaction is None or property_type is None:
        raise ValueError("Must be a fotocasa.es search link (…/comprar/viviendas/<location>/<zone>/l).")
    area = None
    if loc == "area":
        area, zone, feature = zone, None, feature
    return {
        "language": language if language in LANGUAGES else DEFAULT_LANGUAGE,
        "transaction": transaction,
        "property_type": property_type,
        "location": loc,
        "zone": zone,
        "feature": feature,
        "page": int(page) if page else 1,
        "area": area,
        "query": query,
    }


def resolve_price_index_location(value):
    """A municipality slug, "municipality/district", a place name or a
    price-index link -> ("slugs", (municipality, district)) | ("name", text)."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Must not be empty.")
    if _is_link(value):
        path, _query = parse_site_link(value)
        match = _PRICE_INDEX_RE.search(path)
        if not match:
            raise ValueError("Must be a fotocasa.es price-index link (…/indice-precio-vivienda/<municipality>/<zone>).")
        district = match.group(2)
        return "slugs", (match.group(1), None if district in (None, "todas-las-zonas") else district)
    low = value.lower()
    if "/" in low:
        parts = [p for p in low.split("/") if p]
        if len(parts) == 2 and all(_AREA_SLUG_RE.match(p) or _SLUG_RE.match(p) for p in parts):
            return "slugs", (parts[0], None if parts[1] == "todas-las-zonas" else parts[1])
        raise ValueError("Must be <municipality-slug>/<district-slug>, a place name or a price-index link.")
    if _COMBINED_RE.match(value):
        return "combined", value
    if _AREA_SLUG_RE.match(low) and not any(c.isspace() for c in value):
        return "slugs", (low, None)
    return "name", value


def resolve_directory_location(value):
    """An agencies-directory `location`: a slug ("madrid-capital",
    "madrid-capital/barrio-de-salamanca"), a combined id, a place name or a
    directory link -> ("slugs", (location, zone)) | ("combined", id) | ("name", text)."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Must not be empty.")
    if _is_link(value):
        path, _query = parse_site_link(value)
        match = _DIRECTORY_RE.search(path)
        if not match:
            raise ValueError("Must be a fotocasa.es agencies-directory link (…/buscar-agencias-inmobiliarias/<location>/<zone>/l).")
        zone = match.group(2)
        return "slugs", (match.group(1), zone if zone and zone != "todas-las-zonas" else None)
    if _COMBINED_RE.match(value):
        return "combined", value
    low = value.lower()
    if "/" in low:
        parts = [p for p in low.split("/") if p]
        if len(parts) == 2 and all(_SLUG_RE.match(p) for p in parts):
            return "slugs", (parts[0], None if parts[1] == "todas-las-zonas" else parts[1])
        raise ValueError("Must be <location-slug>/<zone-slug>, a place name or a directory link.")
    if _AREA_SLUG_RE.match(low) and not any(c.isspace() for c in value):
        return "slugs", (low, None)
    return "name", value


# ---- paths ---------------------------------------------------------------------

def list_path(language, transaction, property_type, location, zone=None, feature=None, page=1, area=None):
    """A Spanish-site search page path. `area` (a street / urbanisation slug
    from the typeahead) replaces location/zone. Other languages rewrite the
    segments on the site (hrefLang), so the Spanish spelling is used for
    every language and the page's own canonical link is returned."""
    tx = _URL_TRANSACTION[transaction]
    pt = _URL_PROPERTY[property_type]
    if area:
        path = f"/es/{tx}/{pt}/area/{area}"
    else:
        path = f"/es/{tx}/{pt}/{location}/{zone or 'todas-las-zonas'}"
    if feature:
        path += f"/{feature}"
    path += "/l"
    if page > 1:
        path += f"/{page}"
    return path


def detail_path(language, property_id, transaction="buy"):
    """Any slug works (the site redirects to the canonical one); the id
    alone (…/vivienda/<id>/d) is a 404. A sale segment for a rental id
    redirects to the list with ?propertyNotFound, so fetch_detail tries
    both. Only the Spanish segments are proven (the English rental segment
    is not /en/rent/home/); other languages are reached through the page's
    own `uris` links."""
    if transaction != "buy":
        return f"/es/alquiler/vivienda/x/x/{property_id}/d"
    return f"/es/comprar/vivienda/x/x/{property_id}/d"


def promotion_path(language, promotion_id):
    return f"/es/comprar/obra-nueva/x/{promotion_id}"


def agency_path(language, slug, transaction=None, property_type=None, page=1):
    path = f"/{language}/pro/{slug}/"
    if transaction or page > 1:
        path += f"{_URL_TRANSACTION[transaction or 'buy']}/{_URL_PROPERTY[property_type or 'homes']}/espana/todas-las-zonas/l"
        if page > 1:
            path += f"/{page}"
    return path


def directory_path(location, zone=None, page=1):
    path = f"/buscar-agencias-inmobiliarias/{location}/{zone or 'todas-las-zonas'}/l"
    if page > 1:
        path += f"?pagina={page}"
    return path


def price_index_path(municipality, district=None):
    return f"/es/indice-precio-vivienda/{municipality}/{district or 'todas-las-zonas'}"


def agency_link(slug):
    return f"{SITE}/es/pro/{slug}/"


def promotion_link(promotion_id, location_slug=None):
    return f"{SITE}/es/comprar/obra-nueva/{location_slug or 'espana'}/{promotion_id}"
