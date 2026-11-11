"""Raw gateway JSON / page JSON / HTML -> clean dicts for every /fotocasa/*
endpoint. Pure functions, no I/O.

Three card shapes carry the same listing and are normalised to ONE output
record (`_card`):
  * the gateway's realEstates[] (advertiser{}, transactions[], multimedias[],
    features[{key, value[]}], address{location{level1..8}})
  * the HTML pages' resultsV2.items[] / searchResponse.items[] (clientAlias,
    rawPrice, multimedia[], features[{key, value}], address{locationIds})
  * the gateway's promotionClassifieds[] (a realEstates card with a
    promotion{} block)
and the detail page's realEstateAdDetailEntityV2 (decoded, typed features)
plus its legacy realEstate twin (Spanish literals, the other-features table,
the client microsite link) are merged into the details record.

Every site page embeds <script id="__initial_props__" type="application/json">
with the page's data (initial_props()); the agencies directory is the one
server-rendered HTML surface, read with BeautifulSoup.

Value conventions (shared with the other scraper packages):
  * prices   {"amount": 2995000, "currency": "EUR", "period": null | "month",
              "previous_amount": 3200000 | null, "drop": 205000 | null}
  * dates    ISO 8601 as the site gives them ("2026-09-22T18:31:10Z")
  * keys     snake_case; `link` not `url`; booleans as questions; absent -> null

Fixtures captured 2026-11-07 (fotocasa/fixtures/): gateway answers for a
Madrid sale / rent / share / new-construction / premises-transfer search, an
English-culture page, one agency's listing, an empty search and an unknown
agency; five typeahead answers (Madrid, Salamanca, a zip code, a street,
no match); detail pages (professional sale, rental, private rental, the
same sale in English, a new-build unit, a hidden-street villa whose page
carries the "N/A" / -1 placeholders, a dead id); a new-development page
and a dead one; the Fortuny minisite (+ page 2, a dead slug); the Madrid
and Barrio de Salamanca agency directories (+ past the end, an unknown
place, and Marbella's page of 2026-11-10 whose counters printed 0); the Madrid and Barrio de Salamanca price indexes (+ a dead slug);
the Calle Serrano area page (+ a dead slug) and a filtered Madrid list page.
Two blobs the parsers never read are cut from the page fixtures (2026-11-10):
the site's i18n translation dictionary (`window.__INITIAL_DATA__.i18n`) and
the agency pages' SPA route tables (`routeInfo.routes`).
"""
import html as html_module
import re
from datetime import datetime, timezone

import fastjson
from bs4 import BeautifulSoup

from fotocasa import refs

_PROPS_RE = re.compile(r'<script[^>]*\bid="__initial_props__"[^>]*>(.*?)</script>', re.S)
_INT_RE = re.compile(r"-?\d[\d.]*")
_DECIMAL_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
_WS_RE = re.compile(r"\s+")


# ---- scalar helpers ------------------------------------------------------------------

def _clean(text):
    if text is None:
        return None
    text = html_module.unescape(str(text))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(_WS_RE.sub(" ", line).strip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text or None


def _flat(text):
    """Whitespace collapsed to one line."""
    if text is None:
        return None
    text = _WS_RE.sub(" ", html_module.unescape(str(text))).strip()
    return text or None


def _int(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    match = _INT_RE.search(str(value))
    if not match:
        return None
    try:
        return int(match.group(0).replace(".", ""))
    except ValueError:
        return None


def _float(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _DECIMAL_RE.search(str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def _positive(value):
    """Numbers the site zero-fills (or sets to -1) for "unknown" -> null."""
    number = _int(value) if not isinstance(value, float) else value
    return number if number and number > 0 else None


# The site's placeholders for a hidden street: "N/A" as the street name and
# -1 as its number. They leak into its address strings and SEO titles
# ("Casa o chalet en venta en N/a, -1, Las Brisas, Marbella"; 64 of 400
# Marbella cards on 2026-11-07), so they are cut out of every text.
_NA_RE = re.compile(r"\bN/A\b\s*(?:,\s*)?", re.I)
_MINUS_ONE_RE = re.compile(r"(^|,\s*|\s)-1(\s*,\s*|\s*$)")


def _strip_placeholders(text):
    """"N/a, -1, Nueva Andalucía" -> "Nueva Andalucía"; "Calle X, -1" -> "Calle X";
    a text made only of placeholders -> None."""
    if text is None:
        return None
    text = _NA_RE.sub("", _flat(text) or "")
    text = _MINUS_ONE_RE.sub(lambda m: m.group(1) if "," in m.group(2) else "", text)
    text = _WS_RE.sub(" ", text).strip(" ,")
    return text or None


def _bool(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    low = str(value).strip().lower()
    if low in ("yes", "true", "1"):
        return True
    if low in ("no", "false", "0", ""):
        return False
    return None


def _iso(value):
    """The site's timestamps -> ISO 8601 (UTC marked, sub-second dropped);
    its zero date (0001-01-01) and 0 -> null."""
    if value in (None, "", 0, "0001-01-01T00:00:00"):
        return None
    if isinstance(value, (int, float)):
        if value < 10 ** 11:
            return None
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = str(value).strip()
    match = re.match(r"^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}:\d{2}))?", text)
    if not match:
        return None
    if match.group(2):
        suffix = "Z" if text.endswith("Z") or "+" in text[19:] else ""
        return f"{match.group(1)}T{match.group(2)}{suffix}"
    return match.group(1)


def _name(table, key, fallback_prefix=None):
    """An id -> our name from `table`; an unknown id keeps the id as a string."""
    if key is None:
        return None
    if key in table:
        return table[key]
    return str(key) if fallback_prefix is None else f"{fallback_prefix}_{key}"


def _lower(value):
    return value.lower() if isinstance(value, str) and value else None


def _link(path):
    return refs.absolute(path) if path else None


def _photo(url):
    """The CDN link as the site hands it (…?rule=original = full size)."""
    return url or None


def _first(values):
    if isinstance(values, list):
        return values[0] if values else None
    return values


# ---- page JSON -------------------------------------------------------------------------

def initial_props(html):
    """The page's <script id="__initial_props__"> JSON, or None when the
    page carries none (a block page, a site error page)."""
    match = _PROPS_RE.search(html or "")
    if not match:
        return None
    try:
        return fastjson.loads(match.group(1))
    except ValueError:
        return None


def page_title(html):
    match = re.search(r"<title>([^<]*)</title>", html or "", re.I)
    return _flat(match.group(1)) if match else None


# ---- addresses ---------------------------------------------------------------------

def _coords(lat, lng, accuracy=None):
    lat, lng = _float(lat), _float(lng)
    if lat is None or lng is None or (lat == 0 and lng == 0):
        return None
    out = {"latitude": lat, "longitude": lng}
    if accuracy is not None:
        out["is_exact"] = bool(accuracy)
    return out


def _combined(ids):
    if not ids:
        return None
    text = str(ids).replace("_", ",")
    return text if re.match(r"^[0-9]+(?:,[0-9]+){8}$", text) else None


def _gateway_address(address):
    """The gateway card's address{} -> our address block."""
    address = address or {}
    loc = address.get("location") or {}
    return {
        "street": _strip_placeholders(address.get("ubication")),
        "neighborhood": _flat(loc.get("level8")),
        "district": _flat(loc.get("level7")),
        "municipality": _flat(loc.get("level5")),
        "region": _flat(loc.get("level3")),
        "province": _flat(loc.get("level2")),
        "autonomous_community": _flat(loc.get("level1")),
        "country": _flat(loc.get("country")),
        "zip_code": _flat(address.get("zipCode")),
        "location_id": _combined(",".join(str(loc.get(k) or 0) for k in (
            "countryId", "level1Id", "level2Id", "level3Id", "level4Id", "level5Id", "level6Id", "level7Id",
            "level8Id"))) if loc else None,
        "coordinates": _coords((address.get("coordinates") or {}).get("latitude"),
                               (address.get("coordinates") or {}).get("longitude"),
                               1 if (address.get("coordinates") or {}).get("accuracy") else 0),
    }


def _page_address(address, coordinates=None):
    """The page cards' / detail's address{} (street{}, locationIds{}) -> ours."""
    address = address or {}
    street = address.get("street") or {}
    street_name = _strip_placeholders(street.get("name"))
    if street_name and street.get("type"):
        street_name = f"{_flat(street['type'])} {street_name}".strip()
    number = _positive(street.get("number"))
    ids = address.get("locationIds") or {}
    combined = _combined(ids.get("combinedLocationIdsString")) or _combined(address.get("combinedLocationId")) \
        or (_combined(",".join(str(ids.get(k) or 0) for k in (
            "countryId", "autonomousCommunityId", "provinceId", "regionId", "level4Id", "localityId", "level6Id",
            "municipalityId", "neighborhoodId"))) if ids else None)
    coords = address.get("coordinates") or coordinates or {}
    return {
        "street": street_name,
        "street_number": number,
        "neighborhood": _flat(address.get("neighborhood")) or _flat(address.get("upperLevel")),
        "district": _flat(address.get("municipality")) if address.get("locality") else _flat(address.get("district")),
        "municipality": _flat(address.get("locality")) or _flat(address.get("municipality")),
        # the agency minisite's cards carry the legacy key names (county,
        # regionLevel1 / regionLevel2) instead of region / autonomousCommunity
        "region": _flat(address.get("region")) or _flat(address.get("county")),
        "province": _flat(address.get("province")) or _flat(address.get("regionLevel2")),
        "autonomous_community": _flat(address.get("autonomousCommunity")) or _flat(address.get("regionLevel1")),
        "country": _flat(address.get("country")),
        "zip_code": _flat(address.get("zipCode")),
        "location_id": combined,
        "coordinates": _coords(coords.get("lat", coords.get("latitude")), coords.get("lng", coords.get("longitude")),
                               1 if address.get("isExact") else 0),
    }


# ---- listing cards ------------------------------------------------------------------

_CARD_FEATURE_KEYS = {"surface", "rooms", "bathrooms", "floor", "conservationState", "conservationStatus",
                      "surfaceLand", "antiquity", "orientation", "energyCertificate", "hotWater"}


def _features(items):
    """A card's features[] (gateway: value lists; pages: scalars) -> the
    numeric facts + the amenity flags it carries."""
    facts, amenities = {}, []
    for item in items or []:
        key = item.get("key")
        value = _first(item.get("value"))
        if key is None:
            continue
        if key in _CARD_FEATURE_KEYS:
            facts[key] = value
        elif value not in (None, 0, False, "0"):
            amenities.append(key)
    return facts, amenities


# Card feature keys (gateway + page shapes) -> the refs.AMENITIES vocabulary.
_AMENITY_NAMES = {
    "air_conditioner": "air_conditioning", "heater": "heating", "elevator": "lift", "cabinets": "wardrobes",
    "equiped_kitchen": "equipped_kitchen", "household_appliances": "appliances", "private_garden": "garden",
    "private_pool": "swimming_pool", "private_garage": "parking", "community_zone": "community_area",
    "fitness_center": "gym", "porter_service": "porter", "childrens_zone": "childrens_area",
    "sport_area": "sports_area", "heatpump": "heat_pump", "video_dvd": "dvd_player",
}
# The descriptive dynamicFeatures of page cards; the status ones (IS_AUCTIONED,
# IS_OCCUPIED, IS_RENTED, NO_VISIT_ALLOWED, ...) are not amenities and are
# reported by properties/details' own flags instead.
_DYNAMIC_AMENITIES = {
    "IS_EXTERIOR": "exterior", "IS_LUXURY": "luxury", "HAS_A_FIREPLACE": "fireplace",
    "IS_ADAPTED_FOR_WHEELCHAIR": "wheelchair_accessible", "IS_MODERN": "modern", "IS_VILLA": "villa",
    "IS_SINGLE_FAMILY_HOME": "single_family_home",
}


def _amenity_name(key):
    return _AMENITY_NAMES.get(key, key)


def _amenities_from_ids(ids, labels=None):
    """Site amenity ids (with their page labels as a fallback) -> names."""
    out = []
    for raw in ids or []:
        number = _int(raw)
        name = refs.AMENITIES.get(number) if number is not None else None
        if name is None and labels:
            label = labels.get(str(raw)) or labels.get(raw)
            name = _snake_label(label)
        if name and name not in out:
            out.append(name)
    return out


def _snake_label(text):
    text = _flat(text)
    if not text:
        return None
    return re.sub(r"[^0-9a-z]+", "_", text.lower()).strip("_") or None


def _price(amount, drop=None, periodicity_id=None):
    amount = _positive(amount)
    if amount is None:
        return None
    drop = _positive(drop)
    return {
        "amount": amount,
        "currency": refs.CURRENCY,
        "period": refs.PERIODICITIES.get(_int(periodicity_id) or 0),
        "previous_amount": amount + drop if drop else None,
        "drop": drop,
    }


def _card_core(card_id, type_id, subtype_id, transaction_id):
    return {
        "id": str(card_id) if card_id is not None else None,
        "transaction": _name(refs.TRANSACTION_NAMES, _int(transaction_id)),
        "property_type": _name(refs.PROPERTY_TYPE_NAMES, _int(type_id)),
        "property_subtype": _name(refs.SUBTYPE_NAMES, _int(subtype_id)),
    }


def _facts(facts):
    condition = _positive(facts.get("conservationState")) or _positive(facts.get("conservationStatus"))
    return {
        "rooms": _positive(facts.get("rooms")),
        "bathrooms": _positive(facts.get("bathrooms")),
        "surface_m2": _positive(facts.get("surface")),
        "land_surface_m2": _positive(facts.get("surfaceLand")),
        "floor": _name(refs.FLOORS, _positive(facts.get("floor"))),
        "orientation": _name(refs.ORIENTATIONS, _positive(facts.get("orientation"))),
        "condition": _name(refs.CONDITION_NAMES, condition),
        "age": _name(refs.ANTIQUITIES, _positive(facts.get("antiquity"))),
        "energy_rating": _name(refs.ENERGY_RATINGS, _positive(facts.get("energyCertificate"))),
    }


def _promotion_summary(promotion):
    if not promotion:
        return None
    typologies = []
    for typ in promotion.get("typologies") or []:
        facts, amenities = _features(typ.get("features"))
        typologies.append({
            "id": str(typ.get("id")) if typ.get("id") is not None else None,
            "property_subtype": _name(refs.SUBTYPE_NAMES, _int(typ.get("subtypeId"))),
            "price": _price(typ.get("price")),
            **_facts(facts),
            "amenities": sorted(_amenity_name(a) for a in amenities) or None,
        })
    return {
        "name": _flat(promotion.get("name")),
        "link": _link(promotion.get("url")),
        "typologies_count": _positive(promotion.get("typologiesCounter")),
        "typologies": typologies or None,
    }


def gateway_card(card):
    """One realEstates[] / promotionClassifieds[] row of the gateway -> record."""
    if not isinstance(card, dict):
        return None
    adv = card.get("advertiser") or {}
    tx = (card.get("transactions") or [{}])[0] or {}
    facts, amenities = _features(card.get("features"))
    photos = [{"link": _photo(m.get("url")), "room": _flat(m.get("roomType"))}
              for m in card.get("multimedias") or [] if m.get("url")]
    detail = card.get("detail") or {}
    link = _link(next(iter(detail.values()), None)) if isinstance(detail, dict) else None
    advertiser_type = refs.ADVERTISER_TYPES.get(_int(adv.get("typeId")))
    return {
        **_card_core(card.get("id"), card.get("typeId"), card.get("subtypeId"), tx.get("transactionTypeId")),
        "link": link,
        "price": _price(_first(tx.get("value")), tx.get("reduced"), tx.get("periodicityId")),
        **_facts(facts),
        "amenities": sorted(set(_amenity_name(a) for a in amenities)) or None,
        "description": _clean(card.get("description")),
        "address": _gateway_address(card.get("address")),
        "photos": photos or None,
        "photos_count": len(photos) or None,
        "advertiser": {
            "id": str(adv["clientId"]) if adv.get("clientId") else None,
            "name": _flat(adv.get("clientAlias")) or ("Private seller" if advertiser_type == "private" else None),
            "type": advertiser_type,
            "phone": _flat(adv.get("phone")),
            "logo": _photo(((adv.get("logo") or {}).get("multimedia") or {}).get("url")),
            "link": refs.agency_link(adv["urlAlias"]) if adv.get("urlAlias") and advertiser_type == "professional"
            else None,
        } if adv else None,
        "new_development": _promotion_summary(card.get("promotion")),
        "published_at": _iso(card.get("date")),
        "is_new": _bool(card.get("isNew")),
        "is_featured": _bool(card.get("isTop")),
        "is_new_construction": bool(card.get("promotion")) or _bool(card.get("isNewConstruction")) or False,
        "has_virtual_tour": _bool(card.get("isVirtualTour")),
        "has_video": _bool(card.get("hasVgo")),
        "has_floor_plan": _bool(card.get("hasDescriptionPlan")),
        "has_subsidies": _bool(card.get("hasSubsidies")),
        "is_external_contact": _bool(card.get("isExternalContact")),
    }


def page_card(item):
    """One resultsV2.items[] / searchResponse.items[] row of a site page -> record."""
    if not isinstance(item, dict):
        return None
    facts, amenities = _features(item.get("features"))
    for key in item.get("dynamicFeatures") or []:
        if key in _DYNAMIC_AMENITIES:
            amenities.append(_DYNAMIC_AMENITIES[key])
    photos = [{"link": _photo(m.get("url") or m.get("src")), "room": _flat(m.get("roomType"))}
              for m in item.get("multimedia") or [] if (m.get("url") or m.get("src"))]
    detail = item.get("detail") or {}
    if isinstance(detail, dict):
        path = detail.get("es-ES") or next(iter(detail.values()), None)
    else:
        path = item.get("detailUrl")
    advertiser_type = refs.ADVERTISER_TYPES.get(_int(item.get("clientTypeId")))
    client_url = item.get("clientUrl")
    promotion = None
    if item.get("promotionId"):
        promotion = {
            "id": str(item["promotionId"]),
            "name": _flat(item.get("promotionTitle")),
            "link": _link(item.get("promotionUrl")),
            "typologies_count": _positive(item.get("promotionTypologiesCounter")),
        }
    published = item.get("publicationDate") or (item.get("date") or {}).get("timestamp")
    return {
        **_card_core(item.get("id"), item.get("typeId"), item.get("subtypeId"), item.get("transactionTypeId")),
        "link": _link(path),
        "price": _price(item.get("rawPrice", item.get("price")), item.get("reducedPrice"), item.get("periodicityId")),
        **_facts(facts),
        "amenities": sorted(set(_amenity_name(a) for a in amenities)) or None,
        "description": _clean(item.get("description")),
        "address": _page_address(item.get("address"), item.get("coordinates")),
        "photos": photos or None,
        "photos_count": len(photos) or None,
        "advertiser": {
            "id": str(item["clientId"]) if item.get("clientId") else None,
            "name": _flat(item.get("clientAlias")) or ("Private seller" if advertiser_type == "private" else None),
            "type": advertiser_type,
            "phone": _flat(item.get("phone")),
            "logo": _photo(item.get("promotionLogo")) if advertiser_type == "professional" else None,
            "link": _link(client_url) if client_url and "/pro/" in client_url else None,
        },
        "new_development": promotion,
        "published_at": _iso(published),
        "is_new": _bool(item.get("isNew")),
        "is_featured": _bool(item.get("isTop")) or _bool(item.get("isSuperTop")) or False,
        "is_new_construction": _bool(item.get("isNewConstruction")) or False,
        "has_virtual_tour": _bool(item.get("isVirtualTour")),
        "has_video": bool(item.get("hasVideo")),
        "has_floor_plan": _bool(item.get("hasFloorPlans")),
        "has_subsidies": _bool(item.get("hasSubsidies")),
        "is_external_contact": _bool(item.get("isExternalContact")),
    }


# ---- search answers ----------------------------------------------------------------

def _facet(row):
    return {
        "name": _flat(row.get("literal")),
        "location_id": _combined(row.get("combinedLocation") or row.get("combinedLocationdId")),
        "slug": _flat(row.get("segments")),
        "listings_count": _int(row.get("counter")),
        "is_selected": bool(row.get("selected")),
    }


def _breadcrumb(breadcrumb):
    """The gateway's breadcrumb{} (one list per level) -> location facets."""
    if not isinstance(breadcrumb, dict):
        return None
    out = {}
    for level, rows in breadcrumb.items():
        if level == "edistricts" or not isinstance(rows, list) or not rows:
            continue
        name = {"countries": "countries", "provinces": "provinces", "regions": "regions",
                "municipalities": "municipalities", "localities": "localities", "districts": "districts",
                "neighborhoods": "neighborhoods"}.get(level, level)
        items = []
        for row in rows:
            facet = _facet(row)
            subs = row.get("subLocations")
            if isinstance(subs, list) and subs:
                facet["sub_locations"] = [_facet(s) for s in subs]
            items.append(facet)
        out[name] = items
    return out or None


def selected_location(breadcrumb):
    """The deepest selected row of the gateway's breadcrumb (name, slug,
    location_id), or None (province / region queries select nothing)."""
    if not isinstance(breadcrumb, dict):
        return None
    levels = {"neighborhoods": "neighborhood", "districts": "district", "localities": "locality",
              "municipalities": "municipality", "regions": "region", "provinces": "province", "countries": "country"}
    for level, name in levels.items():
        for row in breadcrumb.get(level) or []:
            if row.get("selected"):
                return {"name": _flat(row.get("literal")), "slug": _flat(row.get("segments")),
                        "location_id": _combined(row.get("combinedLocation")), "level": name}
    return None


def _client(client):
    """The gateway's `client` block (present with clientId=) -> agency summary."""
    if not isinstance(client, dict) or not client:
        return None
    phones = [p for p in (client.get("phones") or []) if p]
    if client.get("mobile"):
        phones.append(client["mobile"])
    return {
        "id": str(client["clientId"]) if client.get("clientId") else None,
        "name": _flat(client.get("clientAlias")),
        "slug": _flat(client.get("urlAlias")),
        "link": refs.agency_link(client["urlAlias"]) if client.get("urlAlias") else None,
        "logo": _photo(client.get("logo")),
        "address": _flat(client.get("address")),
        "website": _flat(client.get("web")),
        "email": _flat(client.get("email")),
        "phones": [_flat(p) for p in phones] or None,
        "description": _clean(client.get("description")),
        "listings_count": (_int(client.get("totalBuy")) or 0) + (_int(client.get("totalRent")) or 0)
        if client.get("totalBuy") is not None else None,
        "for_sale_count": _int(client.get("totalBuy")),
        "for_rent_count": _int(client.get("totalRent")),
        "new_developments_count": _int(client.get("totalON")),
        "homes_count": _int(client.get("totalCountFlat")),
        "premises_count": _int(client.get("totalCountBussines")),
        "land_count": _int(client.get("totalCountLand")),
        "provinces_count": _int(client.get("provincesCount")),
    }


def parse_search(payload, language=refs.DEFAULT_LANGUAGE):
    """The gateway search JSON -> {count, results, new_developments, facets,
    location, slugs, agency}."""
    results = [gateway_card(c) for c in payload.get("realEstates") or []]
    promos = [gateway_card(c) for c in payload.get("promotionClassifieds") or []]
    href = (payload.get("hrefLang") or {}).get(refs.DEFAULT_LANGUAGE) or {}
    return {
        "count": _int(payload.get("count")) or 0,
        "results": [r for r in results if r],
        "new_developments": [r for r in promos if r] or None,
        "location": selected_location(payload.get("breadcrumb")),
        "slugs": {"location": _flat(href.get("location")), "zone": _flat(href.get("zone"))} if href else None,
        "facets": _breadcrumb(payload.get("breadcrumb")),
        "agency": _client(payload.get("client")),
    }


def parse_list_page(html):
    """A server-rendered search page (plain list or area page) -> the same
    shape as parse_search plus the page's own link / title / mean prices.
    The page lists 30 rows plus, usually, one promoted card on top (31
    cards); all are kept. ValueError when the page carries no search."""
    props = initial_props(html)
    search = (props or {}).get("initialSearch") if props else None
    if not search or not isinstance(search.get("result"), dict):
        raise ValueError("not a fotocasa search page")
    result = search["result"]
    v2 = result.get("resultsV2") or {}
    items = v2.get("items")
    if items is None:
        items = result.get("realEstates") or []
    cards = [page_card(i) for i in items]
    promos = [gateway_card(c) for c in v2.get("promotionClassifieds") or []]
    page = v2.get("page") or {}
    ctx = props.get("searchContext") or search.get("params") or {}
    href = (search.get("hrefLang") or {}).get(refs.DEFAULT_LANGUAGE) or {}
    mean = search.get("locationMeanPrice") or {}
    canonical = None
    for row in (props.get("seo") or {}).get("link") or []:
        if row.get("rel") == "canonical":
            canonical = row.get("href")
    return {
        "count": _int(result.get("count") if result.get("count") is not None else v2.get("totalItems")) or 0,
        "results": [c for c in cards if c],
        "new_developments": [r for r in promos if r] or None,
        "location": {
            "name": _flat(ctx.get("locationLiteral")) or _flat(props.get("geoFilterLiteral")),
            "slug": "/".join(s for s in (href.get("location"), href.get("zone")) if s) or None,
            "location_id": _combined(ctx.get("combinedLocationIds")),
            "level": _lower(ctx.get("level")),
            "area": _flat(ctx.get("area")) or _flat((search.get("params") or {}).get("area")),
        },
        "slugs": {"location": _flat(href.get("location")), "zone": _flat(href.get("zone"))} if href else None,
        "facets": _breadcrumb({
            "districts": (v2.get("locationFacets") or {}).get("districts") or [],
            "neighborhoods": (v2.get("locationFacets") or {}).get("neighborhoods") or [],
        }) if v2.get("locationFacets") else None,
        "agency": None,
        "link": canonical or _link(ctx.get("pathname")),
        "title": _flat(search.get("h1")),
        "page": _int(page.get("number")),
        "page_size": _int(page.get("size")) or refs.ITEMS_PER_PAGE,
        "transaction": _name(refs.TRANSACTION_NAMES, _int(ctx.get("transactionTypeId"))),
        "property_type": _name(refs.PROPERTY_TYPE_NAMES, _int(ctx.get("propertyTypeId"))),
        "mean_prices": {
            "sale_price_per_m2": _float(mean.get("meanSalePrice")) or None,
            "rent_price_per_m2": _float(mean.get("meanRentPrice")) or None,
            "sale_history": [{"month": _month(r.get("period")), "price_per_m2": _float(r.get("meanPriceSqm"))}
                             for r in mean.get("sale") or []] or None,
            "rent_history": [{"month": _month(r.get("period")), "price_per_m2": _float(r.get("meanPriceSqm"))}
                             for r in mean.get("rent") or []] or None,
        } if mean else None,
    }


def _month(period):
    """"20261001" -> "2026-10"."""
    text = str(period or "")
    return f"{text[:4]}-{text[4:6]}" if len(text) >= 6 and text[:6].isdigit() else None


# ---- suggestions ----------------------------------------------------------------------

def parse_suggestions(payload):
    """The typeahead list -> place rows. A street / urbanisation carries an
    `area` slug instead of a combined id (searchable through the area
    page), a zip code carries neither."""
    out = []
    for row in payload or []:
        if not isinstance(row, dict):
            continue
        ids = row.get("combinedLocationIds")
        combined = _combined(ids)
        kind = _lower(row.get("type"))
        area = ids if (kind == "area" and ids and not combined) else None
        coords = row.get("coordinates") or {}
        out.append({
            "name": _flat(row.get("text")),
            "short_name": _flat(row.get("baseText")),
            "level": refs.LOCATION_LEVELS.get(row.get("level"), _lower(row.get("level"))),
            "kind": kind,
            "location_id": combined,
            "area": area,
            "code": _flat(row.get("code")) if combined or area else None,
            "coordinates": _coords(coords.get("latitude"), coords.get("longitude")),
            "has_children": _bool(row.get("hasChildren")),
            "is_point_of_interest": _bool(row.get("isPoi")),
            "score": _float(row.get("score")),
        })
    return out


# ---- detail pages ---------------------------------------------------------------------

def is_detail_page(html):
    props = initial_props(html)
    return bool(props and isinstance(props.get("realEstateAdDetailEntityV2"), dict))


def _typed_features(features):
    """The V2 features[] ({type, value}) -> dict by type (lower snake)."""
    out = {}
    for row in features or []:
        kind = row.get("type")
        if kind:
            out[kind] = row.get("value")
    return out


def _snake(value):
    if not isinstance(value, str) or not value:
        return None
    return value.strip().lower()


def _yes(value):
    return _bool(value) if isinstance(value, str) and value.upper() in ("YES", "NO") else None


def _energy(energy, typed):
    """The V2 energyCertificate{} + ENERGY / EMISSIONS typed features."""
    energy = energy or {}
    perf = energy.get("energyPerformanceCertificateType")
    if not energy and not typed.get("ENERGY"):
        return None
    consumption = typed.get("ENERGY") or {}
    emissions = typed.get("EMISSIONS") or {}
    rating = _flat(energy.get("energyEfficiencyRatingType")) or _flat(consumption.get("letter"))
    emissions_rating = _flat(energy.get("environmentImpactRatingType")) or _flat(emissions.get("letter"))
    if not rating and not emissions_rating:
        return None
    return {
        "status": _snake(perf),
        "rating": rating,
        "consumption_kwh_m2_year": _positive(energy.get("energyEfficiency", consumption.get("value")))
        if _int(energy.get("energyEfficiency", consumption.get("value"))) not in (None, 999) else None,
        "emissions_rating": emissions_rating,
        "emissions_kg_co2_m2_year": _positive(energy.get("environmentImpact", emissions.get("value")))
        if _int(energy.get("environmentImpact", emissions.get("value"))) not in (None, 999) else None,
    }


def _publisher(v2, legacy):
    pub = v2.get("publisher") or {}
    agency = v2.get("agency") or {}
    kind = _snake(pub.get("type") or agency.get("type"))
    if kind == "particular":
        kind = "private"
    url = pub.get("url") or ""
    slug_match = re.search(r"/pro/([a-z0-9-]+)/", url)
    phone = _flat(pub.get("phone")) or _flat(legacy.get("phone"))
    return {
        "id": str(pub.get("id") or agency.get("id") or legacy.get("clientId") or "") or None,
        "name": _flat(pub.get("alias")) or _flat(agency.get("alias")) or _flat(legacy.get("clientAlias")),
        "legal_name": _flat(pub.get("name")) or _flat(agency.get("name")),
        "type": kind,
        "phone": phone,
        "contact_name": _flat(legacy.get("contactName")) if kind != "private" else None,
        "reference": _flat(pub.get("reference")) or _flat(legacy.get("reference")),
        "logo": _photo(pub.get("logo") or agency.get("logo")),
        "website": _flat(agency.get("web")),
        "slug": slug_match.group(1) if slug_match else None,
        "link": _link(url) if slug_match else None,
        "listings_link": _link(legacy.get("clientUrl")) if legacy.get("clientUrl") else None,
        "has_quality_seal": _bool(legacy.get("hasQualitySeal")),
    }


def parse_detail(html, property_id=None, canonical_url=None):
    """A listing page -> the details record. ValueError when the page is not
    a listing (a site error page)."""
    props = initial_props(html)
    if not props or not isinstance(props.get("realEstateAdDetailEntityV2"), dict):
        raise ValueError("not a fotocasa listing page")
    v2 = props["realEstateAdDetailEntityV2"]
    legacy = props.get("realEstate") or {}
    typed = _typed_features(v2.get("features"))
    legacy_features = legacy.get("features") or {}
    price = v2.get("price") or {}
    photos = [{"link": _photo(m.get("url")), "position": _int(m.get("position"))}
              for m in v2.get("multimedias") or [] if m.get("type") == "image" and m.get("url")]
    videos = [{"link": m.get("url"), "position": _int(m.get("position"))}
              for m in v2.get("multimedias") or [] if m.get("type") not in (None, "image") and m.get("url")]
    uris = {}
    for row in v2.get("uris") or []:
        lang = (row.get("language") or "")[:2]
        if lang and row.get("value"):
            uris[lang] = refs.absolute(row["value"])
    detail_links = legacy.get("detail") or {}
    for culture, path in detail_links.items():
        uris.setdefault(culture[:2], refs.absolute(path))
    # amenities come from the legacy block's amenity ids (otherFeaturesIds /
    # the otherFeatures {id: label} table), named with the same vocabulary as
    # the search cards and the `features` filter, whatever the page language;
    # the lift lives only in the V2 typed features (`has_lift`)
    other = legacy.get("otherFeatures") or {}
    ids = legacy.get("otherFeaturesIds") if isinstance(legacy.get("otherFeaturesIds"), list) else list(other)
    amenities = _amenities_from_ids(ids, other)
    if not amenities:
        # a new-build unit's page leaves the legacy table empty
        # (otherFeaturesIds false); its amenity ids ride unitDetail.extras
        amenities = _amenities_from_ids([e.get("id") for e in (props.get("unitDetail") or {}).get("extras") or []
                                         if isinstance(e, dict)])
    if _yes(typed.get("ELEVATOR")) and "lift" not in amenities:
        amenities.append("lift")
    rooms = _positive(legacy_features.get("rooms"))
    typology = _snake(typed.get("TYPOLOGY"))
    pid = str(v2.get("propertyId") or property_id or legacy.get("id") or "") or None
    occupancy = _snake(typed.get("OCCUPANCY_STATUS"))
    rental_duration = _snake(typed.get("RENTAL_DURATION"))
    conservation = _snake(typed.get("CONSERVATION_STATE"))
    promo = props.get("projectDetail") or {}
    unit = props.get("unitDetail") or {}
    rent_index = v2.get("rentReferenceIndex") or {}
    return {
        "id": pid,
        "title": _strip_placeholders(props.get("seoTitle")) or _strip_placeholders(props.get("propertyTitle")),
        "link": uris.get("es") or canonical_url,
        "links": uris or None,
        "transaction": _name(refs.TRANSACTION_NAMES, _int(v2.get("transactionTypeId"))),
        "property_type": _name(refs.PROPERTY_TYPE_NAMES, _int(v2.get("propertyTypeId"))),
        "property_subtype": _name(refs.SUBTYPE_NAMES, _int(v2.get("propertySubtypeId"))),
        "typology": typology,
        "price": _price(price.get("amount"), price.get("amountDrop"), price.get("periodicity")),
        "is_price_shown": _bool(legacy.get("showPrice")),
        "rooms": rooms,
        "bathrooms": _positive(legacy_features.get("bathrooms")),
        "surface_m2": _positive(legacy_features.get("surface")),
        "land_surface_m2": _positive(v2.get("groundSurface")) or _positive(legacy_features.get("surfaceLand")),
        "floor": _snake(typed.get("FLOOR")) or _name(refs.FLOORS, _positive(legacy_features.get("floor"))),
        "orientation": _snake(typed.get("ORIENTATION")) or _name(refs.ORIENTATIONS,
                                                                  _positive(legacy_features.get("orientation"))),
        "condition": refs.CONDITION_NAMES.get(_positive(legacy_features.get("conservationState")))
        or ({"almost_new": "almost_new", "very_good": "very_good", "good": "good", "for_renovation": "needs_renovation",
             "refurbished": "refurbished", "new_home": "new_build"}.get(conservation, conservation)),
        "age": _snake(typed.get("ANTIQUITY")) or _name(refs.ANTIQUITIES, _positive(legacy_features.get("antiquity"))),
        "construction": {"secondhand": "second_hand", "newconstruction": "new_construction"}.get(
            _snake(v2.get("constructionType")), _snake(v2.get("constructionType"))),
        "heating": _snake(typed.get("HEATING")) or _name(refs.HEATINGS, _positive(legacy_features.get("heating"))),
        "hot_water": _snake(typed.get("HOT_WATER")) or _name(refs.HEATINGS, _positive(legacy_features.get("hotWater"))),
        "has_lift": _yes(typed.get("ELEVATOR")),
        "is_furnished": _yes(typed.get("FURNISHED")),
        "occupancy": occupancy.replace("is_", "", 1) if occupancy else None,
        "rental_duration": rental_duration.replace("is_", "", 1) if rental_duration else None,
        "energy_certificate": _energy(v2.get("energyCertificate"), typed),
        "amenities": amenities or None,
        "description": _clean(v2.get("description")) or _clean(next(iter((legacy.get("descriptions") or {}).values()),
                                                                     None)),
        "address": _page_address(v2.get("address"), legacy.get("coordinates")),
        "photos": photos or None,
        "photos_count": len(photos) or None,
        "videos": videos or None,
        "has_virtual_tour": _bool(legacy.get("isVirtualTour")),
        "advertiser": _publisher(v2, legacy),
        "new_development": {
            "id": str(promo.get("id") or legacy.get("promotionId") or ""),
            "name": _flat(promo.get("name")),
            "link": _link(legacy.get("promotionUrl")) if promo else None,
            "unit_reference": _flat(unit.get("agencyReference")),
            "delivery_date": _iso(promo.get("keyDeliveryDate")),
        } if promo or legacy.get("promotionId") else None,
        "is_new_construction": _bool(legacy.get("isNewConstruction")) or bool(promo),
        "is_auctioned": _bool(v2.get("isAuctioned")),
        "is_bare_ownership": _bool(v2.get("isBareOwnership")),
        "is_occupied": _bool(v2.get("isOccupied")),
        "has_tenants": _bool(v2.get("isRentedWithTenants")),
        "is_temporary_rental": _bool(v2.get("isTemporaryRental")),
        "has_subsidies": bool(legacy["subsidies"]) if isinstance(legacy.get("subsidies"), list) else None,
        "is_external_contact": _bool(v2.get("isExternalContact")) if "isExternalContact" in v2
        else _bool(legacy.get("isExternalContact")),
        "external_contact_link": _flat(v2.get("externalContactUrl")) or None,
        "rent_reference_index": {
            "last_rent_price": _positive(rent_index.get("lastRentPrice")),
            "index": _positive(rent_index.get("rentPriceIndex")),
        } if rent_index and (rent_index.get("lastRentPrice") or rent_index.get("rentPriceIndex")) else None,
        "published_at": _iso(v2.get("creationDate")) or _iso((legacy.get("date") or {}).get("timestamp")),
        "updated_at": _iso(legacy.get("alterDate")),
        "is_new": _bool(legacy.get("isNew")),
        # isOpportunity is a paid highlight product (the bundle's
        # productHighLightTypesDictionary), like highlight and premium
        "is_featured": bool(_bool(legacy.get("highlight")) or _bool(legacy.get("isPremium"))
                            or _bool(legacy.get("isOpportunity"))),
        "breadcrumb": [{"name": _flat(b.get("text")), "link": _link(b.get("url"))}
                       for b in props.get("breadcrumb") or [] if b.get("text")] or None,
        "location_slugs": {
            "location": _flat((legacy.get("relatedGeoInfo") or {}).get("locationSlug")),
            "zone": _flat((legacy.get("relatedGeoInfo") or {}).get("zoneSlug")),
        } if legacy.get("relatedGeoInfo") else None,
    }


# ---- new developments -----------------------------------------------------------------

def is_promotion_page(html):
    props = initial_props(html)
    return bool(props and isinstance(props.get("projectDetail"), dict) and not props.get("unitDetail"))


def _unit(unit, promotion_link=None):
    """A unit row: the project's units[] (transactions[], floorId, extras[])
    or a projectGroupUnits[].units[] row (flat price)."""
    tx = (unit.get("transactions") or [{}])[0] or {}
    price = unit.get("price", tx.get("price"))
    periodicity = unit.get("paymentPeriodicityId", tx.get("paymentPeriodicityId"))
    extras = []
    for extra in unit.get("extras") or []:
        if not isinstance(extra, dict):
            continue
        # the id is the site's amenity id; its keyName carries typos ("wardroves")
        name = refs.AMENITIES.get(_int(extra.get("id"))) or (_camel_to_snake(extra["keyName"])
                                                            if extra.get("keyName") else None)
        if name and name not in extras:
            extras.append(name)
    media = unit.get("multimedias") or {}
    photos = [{"link": _photo(u)} for u in media.get("picture") or [] if u] if isinstance(media, dict) else []
    unit_id = str(unit.get("id")) if unit.get("id") is not None else None
    return {
        "id": unit_id,
        "reference": _flat(unit.get("agencyReference")),
        "link": f"{promotion_link}/{unit_id}".replace("/obra-nueva/", "/vivienda/obra-nueva/", 1)
        if promotion_link and unit_id else None,
        "transaction": _name(refs.TRANSACTION_NAMES, _int(unit.get("transactionTypeId", tx.get("transactionTypeId")))),
        "property_subtype": _name(refs.SUBTYPE_NAMES, _int(unit.get("subtypeId"))),
        "price": _price(price, None, periodicity),
        "rooms": _positive(unit.get("rooms")),
        "bathrooms": _positive(unit.get("baths")),
        "surface_m2": _positive(unit.get("surface")),
        "land_surface_m2": _positive(unit.get("groundSurface")),
        "floor": _name(refs.FLOORS, _positive(unit.get("floorId", unit.get("floor")))),
        "door": _flat(unit.get("door")),
        "stair": _flat(unit.get("stair")),
        "orientation": _name(refs.ORIENTATIONS, _positive(unit.get("orientationId"))),
        "heating": _name(refs.HEATINGS, _positive(unit.get("heatingId"))),
        "hot_water": _name(refs.HEATINGS, _positive(unit.get("hotWaterId"))),
        "energy_rating": _name(refs.ENERGY_RATINGS, _positive(unit.get("energyCertificate"))),
        "amenities": sorted(extras) or None,
        "photos": photos or None,
        "photos_count": len(photos) or None,
    }


def _camel_to_snake(text):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", text).lower()


def parse_promotion(html, promotion_id=None, canonical_url=None):
    """A new-development page -> the promotion record."""
    props = initial_props(html)
    if not props or not isinstance(props.get("projectDetail"), dict):
        raise ValueError("not a fotocasa new-development page")
    project = props["projectDetail"]
    v2 = props.get("realEstatePromotionDetailEntityV2") or {}
    legacy = props.get("realEstate") or project.get("realEstate") or {}
    adv = project.get("advertiser") or {}
    publisher = v2.get("publisher") or {}
    agency = v2.get("agency") or {}
    media = project.get("multimedias") or {}
    photos = [{"link": _photo(u)} for u in media.get("picture") or [] if u]
    if not photos:
        photos = [{"link": _photo(m.get("url"))} for m in v2.get("multimedias") or []
                  if m.get("type") == "image" and m.get("url")]
    uris = {}
    for row in v2.get("uris") or []:
        lang = (row.get("language") or "")[:2]
        if lang and row.get("value"):
            uris[lang] = refs.absolute(row["value"])
    pid = str(project.get("id") or v2.get("id") or promotion_id or "") or None
    geo = project.get("relatedGeoInfo") or {}
    link = uris.get("es") or canonical_url or refs.promotion_link(pid, geo.get("locationSlug"))
    groups = []
    for group in props.get("projectGroupUnits") or []:
        groups.append({
            "rooms": _positive(group.get("bedrooms")) if group.get("bedrooms") is not None else None,
            "units_count": _positive(group.get("totalUnits")),
            "min_price": _positive(group.get("minPrice")),
            "max_price": _positive(group.get("maxPrice")),
            "min_surface_m2": _positive(group.get("minSize")),
            "max_surface_m2": _positive(group.get("maxSize")),
            "unit_ids": [str(u["id"]) for u in group.get("units") or [] if u.get("id") is not None] or None,
        })
    units = [_unit(u, link) for u in project.get("units") or []]
    slug_match = re.search(r"/pro/([a-z0-9-]+)/", publisher.get("url") or "")
    location = project.get("address") or {}
    energy = v2.get("energyCertificate") or {}
    return {
        "id": pid,
        "name": _flat(project.get("name")) or _flat(v2.get("name")),
        "title": _flat(props.get("seoTitle")),
        "link": link,
        "links": uris or None,
        "transaction": _name(refs.TRANSACTION_NAMES, _int(legacy.get("transactionTypeId"))) or "buy",
        "property_type": _name(refs.PROPERTY_TYPE_NAMES, _int(legacy.get("propertyTypeId"))) or "homes",
        "price_range": {"min": _positive(project.get("minPrice")), "max": _positive(project.get("maxPrice")),
                        "currency": refs.CURRENCY},
        "rent_range": {"min": _positive(project.get("minRentPrice")), "max": _positive(project.get("maxRentPrice")),
                       "currency": refs.CURRENCY} if _positive(project.get("maxRentPrice")) else None,
        "rooms_range": {"min": _positive(project.get("minRooms")), "max": _positive(project.get("maxRooms"))},
        "bathrooms_range": {"min": _positive(project.get("minBathrooms")), "max": _positive(project.get("maxBathrooms"))},
        "surface_range_m2": {"min": _positive(project.get("minSurface")), "max": _positive(project.get("maxSurface"))},
        "units_count": len(units) or None,
        "units": units or None,
        "unit_groups": groups or None,
        "delivery_date": _iso(project.get("keyDeliveryDate")) or _iso(v2.get("keyDeliveryDate")),
        "is_finished": _bool(v2.get("finalized")),
        # the promotion page carries rating letters only (its numeric fields
        # are rating ids, not kWh / kg CO2)
        "energy_certificate": _energy({k: v for k, v in energy.items()
                                       if k in ("energyPerformanceCertificateType", "energyEfficiencyRatingType",
                                                "environmentImpactRatingType")}, {}),
        "extras": [_flat(x) for x in project.get("extras") or [] if x] or None,
        "description": _clean(next(iter((project.get("description") or {}).values()), None)
                              if isinstance(project.get("description"), dict) else project.get("description"))
        or _clean(v2.get("description")),
        "address": {
            **_page_address(v2.get("address") or {}),
            "coordinates": _coords((location.get("coordinates") or {}).get("latitude"),
                                   (location.get("coordinates") or {}).get("longitude"))
            or _page_address(v2.get("address") or {})["coordinates"],
        },
        "photos": photos or None,
        "photos_count": len(photos) or None,
        "virtual_tours": [u for u in media.get("virtualTour") or [] if u] or None,
        "quality_reports": [u for u in media.get("qualityReport") or [] if u] or None,
        "videos": [u for u in media.get("video") or [] if u] or None,
        "advertiser": {
            "id": str(adv.get("clientId") or publisher.get("id") or "") or None,
            "name": _flat(adv.get("promoterName")) or _flat(publisher.get("alias")),
            "legal_name": _flat(publisher.get("name")) or _flat(agency.get("name")),
            "type": "professional" if _int(project.get("clientType")) == 3 else refs.ADVERTISER_TYPES.get(
                _int(project.get("clientType"))),
            "phone": _flat(adv.get("phone")) or _flat(publisher.get("phone")),
            "logo": _photo(publisher.get("logo") or agency.get("logo") or legacy.get("promotionLogo")),
            "website": _flat(agency.get("web")),
            "slug": slug_match.group(1) if slug_match else None,
            "link": _link(publisher.get("url")) if slug_match else None,
            "listings_link": _link((adv.get("logo") or {}).get("url")),
        },
        "published_at": _iso(v2.get("creationDate")),
        "updated_at": _iso(v2.get("alterDate")),
        "location_slugs": {"location": _flat(geo.get("locationSlug")), "zone": _flat(geo.get("zoneSlug"))}
        if geo else None,
    }


# ---- agency minisite ---------------------------------------------------------------------

def is_agency_page(html):
    props = initial_props(html)
    return bool(props and isinstance(props.get("minisiteInfo"), dict))


def _hours(business_hours):
    if not isinstance(business_hours, dict):
        return None
    out = {}
    for day, row in business_hours.items():
        if not isinstance(row, dict):
            continue
        out[day] = {"is_closed": _bool(row.get("closed")), "hours": row.get("hours") or None}
    return out or None


def parse_agency(html, canonical_url=None):
    """The minisite -> {profile, listing: {count, results, page}}."""
    props = initial_props(html)
    if not props or not isinstance(props.get("minisiteInfo"), dict):
        raise ValueError("not a fotocasa agency page")
    info = props["minisiteInfo"]
    site = info.get("agencyMinisite") or {}
    counters = info.get("agencyCounters") or site.get("agencyCounters") or {}
    tx = counters.get("transactionTypes") or {}
    pt = counters.get("propertyTypes") or {}
    coords = site.get("coordinates") or {}
    details = site.get("minisiteDetails") or {}
    inventory = site.get("inventory") or {}
    slug = _flat(site.get("slug")) or _flat(site.get("agencyUrlAlias"))
    active = ((site.get("activeUrls") or {}).get("fotocasa") or {})
    search = props.get("searchResponse") or {}
    params = props.get("searchParams") or {}
    cards = [page_card(i) for i in search.get("items") or []]
    client_id = None
    for row in search.get("items") or []:
        if row.get("clientId"):
            client_id = str(row["clientId"])
            break
    profile = {
        "id": client_id,
        "slug": slug,
        "name": _flat(site.get("agency")),
        "link": refs.agency_link(slug) if slug else canonical_url,
        "links": {k: v for k, v in active.items() if v} or None,
        "logo": _photo(site.get("logo")),
        "description": _clean(site.get("description")),
        "address": _flat(site.get("address")),
        "town": _flat(site.get("town")),
        "province": _flat(site.get("province")),
        "zip_code": _flat(site.get("zipCode")),
        "coordinates": _coords(coords.get("latitude"), coords.get("longitude")),
        "map_link": _flat(site.get("addressUrl")),
        "phones": [_flat(p) for p in site.get("phoneList") or [] if p] or None,
        "email": _flat(site.get("email")),
        "website": _flat(site.get("web")),
        "website_domain": _flat(site.get("webDomain")),
        "social_networks": site.get("socialNetworks") or None,
        "languages": details.get("languages") or None,
        "business_hours": _hours(details.get("businessHours")),
        "member_since": _iso(site.get("createdAt")),
        "has_quality_seal": _bool(site.get("hasQualitySeal")),
        "official_registrations": [_flat(r) if not isinstance(r, dict) else r
                                   for r in site.get("officialRegistrations") or []] or None,
        "agents_count": _int(site.get("agentsCounter")),
        "franchisees_count": _int(site.get("franchiseesCounter")),
        "parent": _flat(site.get("parentPublisher")) if isinstance(site.get("parentPublisher"), str)
        else site.get("parentPublisher"),
        "listings_count": _int(counters.get("totalProperties")) or _int(info.get("propertiesCount")),
        "for_sale_count": _int(tx.get("buy")),
        "for_rent_count": _int(tx.get("rent")),
        "share_count": _int(tx.get("share")),
        "new_developments_count": _int(counters.get("promotions")) or _int(inventory.get("promotions")),
        "listings_by_type": {
            "homes": _int(pt.get("flat")), "premises": _int(pt.get("bussines")), "land": _int(pt.get("land")),
            "garages": _int(pt.get("garage")), "storage_rooms": _int(pt.get("boxRoom")),
        } if pt else None,
        "inventory": [{
            "transaction": _name(refs.TRANSACTION_NAMES, _int(c.get("transactionTypeId"))),
            "property_type": _name(refs.PROPERTY_TYPE_NAMES, _int(c.get("propertyTypeId"))),
            "count": _int(c.get("count")),
        } for c in inventory.get("counters") or []] or None,
    }
    listing = {
        "count": _int(search.get("totalItems")) or 0,
        "results": [c for c in cards if c],
        "page": _int(params.get("currentPage")) or 1,
        "page_size": _int(params.get("resultsPerPage")) or refs.AGENCY_PAGE_ITEMS,
        "transaction": _name(refs.TRANSACTION_NAMES, _int(params.get("transactionTypeId"))),
        "property_type": _name(refs.PROPERTY_TYPE_NAMES, _int(params.get("propertyTypeId"))),
    }
    return {"profile": profile, "listing": listing}


# ---- agencies directory -----------------------------------------------------------------

def parse_directory(html, canonical_url=None):
    """One agencies-directory page -> {title, totals, results, has_next}."""
    soup = BeautifulSoup(html or "", "lxml")
    results = []
    for card in soup.select("article.re-CardPackMinimal"):
        link = None
        for node in card.select("[data-promiseref]"):
            link = node.get("data-promiseref")
            if link:
                break
        slug_match = re.search(r"/pro/([a-z0-9-]+)/?", link or "")
        title = card.select_one(".re-CardHeader-title")
        logo = card.select_one("img.re-image-client")
        cover = card.select_one("picture.re-image")
        cover_url = None
        if cover is not None:
            match = re.search(r"url\('([^']+)'\)", cover.get("style") or "")
            cover_url = match.group(1) if match else None
        stats = {}
        for item in card.select(".re-description-item"):
            label = item.select_one("label")
            value = _flat(label.get_text()) if label else None
            text = _flat(item.get_text().replace(value or "", "", 1)) if value else _flat(item.get_text())
            if text:
                stats[text.lower()] = value
        def _stat(*needles):
            for key, value in stats.items():
                if all(n in key for n in needles):
                    return value
            return None
        in_zone = _int(_stat("en esta zona"))
        published = _int(_stat("publicados"))
        if published is not None and in_zone and published < in_zone:
            # the site's counter sometimes prints 0 published next to hundreds
            # in the zone (Marbella, 2026-11-10): an impossible total -> unknown
            published = None
        results.append({
            "id": _flat(card.get("data-agency-id")),
            "name": _flat(card.get("data-agency-name")) or (_flat(title.get_text()) if title else None),
            "slug": slug_match.group(1) if slug_match else None,
            "link": link or (refs.agency_link(slug_match.group(1)) if slug_match else None),
            "logo": logo.get("src") if logo is not None else None,
            "cover_photo": cover_url,
            "listings_in_zone_count": in_zone,
            "listings_count": published,
            "lowest_price": _price(_stat("precio")),
            "transaction": "rent" if any("alquiler" in k for k in stats) else "buy",
        })
    subtitle = soup.select_one(".re-FeedProperties-subtitle")
    totals = None
    if subtitle is not None:
        text = _flat(subtitle.get_text()) or ""
        sale = re.search(r"([\d.]+)\s+inmobiliarias", text)
        rent = re.search(r"([\d.]+)\s+agencias", text)
        totals = {"for_sale_agencies": _int(sale.group(1)) if sale else None,
                  "for_rent_agencies": _int(rent.group(1)) if rent else None}
        if results and not totals["for_sale_agencies"] and not totals["for_rent_agencies"]:
            # "0 inmobiliarias … 0 agencias" above a page of agencies is the
            # same broken counter: unknown, not zero
            totals = {"for_sale_agencies": None, "for_rent_agencies": None}
    title = soup.select_one("h1")
    pages = [int(p) for p in re.findall(r"[?&]pagina=(\d+)", html or "")]
    current = soup.select_one(".sui-MoleculePagination-item.current")
    current_page = _int(current.get_text()) if current is not None else None
    return {
        "title": _flat(title.get_text()) if title else page_title(html),
        "totals": totals,
        "results": results,
        "page": current_page,
        "last_page_seen": max(pages) if pages else None,
        "link": canonical_url,
    }


# ---- price index -----------------------------------------------------------------------------

def _delta(delta):
    if not isinstance(delta, dict):
        return None
    out = {"1_month": _float(delta.get("oneMonth")), "3_months": _float(delta.get("threeMonths")),
           "6_months": _float(delta.get("sixMonths")), "12_months": _float(delta.get("twelveMonths"))}
    return out if any(v is not None for v in out.values()) else None


def _history(rows):
    out = [{"month": _month(r.get("period")), "price_per_m2": _float(r.get("meanPriceSqm"))}
           for r in rows or [] if r.get("period")]
    return out or None


def _zone(row, level):
    if not isinstance(row, dict):
        return None
    evolution = row.get("priceEvolution") or {}
    temp = row.get("marketTemperature") or {}
    return {
        "id": _flat(row.get("id")),
        "name": _flat(row.get("name")),
        "slug": _flat(row.get("slug")),
        "level": level,
        "sale": {
            "median_price_per_m2": _float(row.get("medianPriceSqm")),
            "mean_price_per_m2": _float(row.get("meanPriceSqm")),
            "p25_price_per_m2": _float(row.get("p25PriceSqm")),
            "p75_price_per_m2": _float(row.get("p75PriceSqm")),
            "change_percent": _delta(row.get("sellPriceIndexDelta")),
            "market_temperature": _lower(temp.get("sell")),
            "history": _history(evolution.get("sale")),
        },
        "rent": {
            "median_price_per_m2": _float(row.get("medianRentPriceSqm")),
            "change_percent": _delta(row.get("rentPriceIndexDelta")),
            "market_temperature": _lower(temp.get("rent")),
            "history": _history(evolution.get("rent")),
        },
        "currency": refs.CURRENCY,
        "listings_count": _int(row.get("adsListingCount")),
        "building_decades": row.get("buildingDecades") or None,
        "is_indexable": _bool(row.get("isIndexable")),
    }


def parse_price_index(html, canonical_url=None):
    """A price-index page (municipality or district) -> the record."""
    props = initial_props(html)
    if not props or not (props.get("municipality") or props.get("district")):
        raise ValueError("not a fotocasa price-index page")
    level = "district" if props.get("district") else "municipality"
    row = props.get("district") or props.get("municipality")
    crumbs = props.get("breadcrumb") or {}
    children_key = "neighborhoods" if level == "district" else "districts"
    children = [_zone(c, children_key[:-1]) for c in row.get(children_key) or []]
    related = (crumbs.get(level) or {}).get("related") or []
    return {
        **_zone(row, level),
        "link": canonical_url or refs.absolute(refs.price_index_path(
            (crumbs.get("municipality") or {}).get("slug") or row.get("slug"),
            row.get("slug") if level == "district" else None)),
        "municipality": {"id": _flat(row.get("municipalityId")), "name": _flat(row.get("municipalityName")) or _flat(
            (crumbs.get("municipality") or {}).get("name")), "slug": _flat((crumbs.get("municipality") or {}).get("slug"))}
        if level == "district" else None,
        "province": {"id": _flat(row.get("provinceId")), "name": _flat(row.get("provinceName")) or _flat(
            (crumbs.get("province") or {}).get("name")), "slug": _flat((crumbs.get("province") or {}).get("slug"))},
        children_key: [c for c in children if c] or None,
        "related": [{"name": _flat(r.get("name")), "slug": _flat(r.get("slug"))} for r in related] or None,
        "page": _flat(props.get("page")),
    }
