"""Offline tests for the fotocasa parsers, reference resolvers and value
helpers.

    python -m pytest fotocasa/test_parsers.py -q

Fixtures are real www.fotocasa.es answers captured 2026-11-07
(fotocasa/fixtures/): gateway searches (sale, rent, share, new
construction, premises transfer, English culture, one agency, empty,
unknown agency), typeahead answers, detail pages (sale, rent, private
rental, English, new-build unit, a dead id), a new-development page (+ a
dead one), the Fortuny minisite (+ page 2, a dead slug), the agencies
directory (Madrid, a district, past the end, an unknown place), two price
indexes (+ a dead slug), the Calle Serrano area page (+ a dead slug) and a
filtered Madrid list page. No network.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fotocasa import parsers as P, refs  # noqa: E402
from fotocasa import fetch as F  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return json.load(f) if name.endswith(".json") else f.read()


@pytest.fixture(scope="module")
def madrid():
    return P.parse_search(fixture("search_buy_madrid.json"))


@pytest.fixture(scope="module")
def sale_detail():
    return P.parse_detail(fixture("detail_sale_184433815.html"))


@pytest.fixture(scope="module")
def promotion():
    return P.parse_promotion(fixture("promotion_20678485.html"))


@pytest.fixture(scope="module")
def agency():
    return P.parse_agency(fixture("agency_fortuny.html"))


# ---- refs ---------------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("184433815", "184433815"),
    (" 191331052 ", "191331052"),
    ("https://www.fotocasa.es/es/comprar/vivienda/madrid/aire-acondicionado/184433815/d", "184433815"),
    ("https://www.fotocasa.es/en/buy/home/madrid/x/184433815/d?from=list", "184433815"),
    ("www.fotocasa.es/es/alquiler/vivienda/x/x/191331052/d", "191331052"),
    ("https://www.fotocasa.es/es/comprar/vivienda/obra-nueva/madrid-capital/20678485/191171924", "191171924"),
    ("https://www.fotocasa.es/en/buy/home/new-home/madrid-capital/20678485/191171924", "191171924"),
])
def test_resolve_property(value, expected):
    assert refs.resolve_property(value) == expected


@pytest.mark.parametrize("value", ["", "piso", "1234", "https://example.com/x/184433815/d",
                                   "https://www.fotocasa.es/es/comprar/viviendas/madrid-capital/todas-las-zonas/l"])
def test_resolve_property_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_property(value)


def test_resolve_promotion():
    assert refs.resolve_promotion("20678485") == "20678485"
    assert refs.resolve_promotion("https://www.fotocasa.es/es/comprar/obra-nueva/madrid-capital/20678485") == "20678485"
    assert refs.resolve_promotion("https://www.fotocasa.es/en/buy/new-home/madrid-capital/20678485") == "20678485"
    with pytest.raises(ValueError):
        refs.resolve_promotion("https://www.fotocasa.es/es/comprar/vivienda/x/x/184433815/d")


def test_resolve_agency():
    assert refs.resolve_agency("Fortuny-Madrid-Real-Estate") == {"slug": "fortuny-madrid-real-estate"}
    assert refs.resolve_agency("https://www.fotocasa.es/es/pro/fortuny-madrid-real-estate/") == {
        "slug": "fortuny-madrid-real-estate"}
    assert refs.resolve_agency("9202757120653") == {"client_id": "9202757120653"}
    assert refs.resolve_agency("https://www.fotocasa.es/inmobiliarias/espigul-immobiliaria-9202775531783") == {
        "client_id": "9202775531783"}
    assert refs.resolve_agency("https://www.fotocasa.es/es/inmobiliaria-x/comprar/viviendas/espana/todas-las-zonas/l"
                               "?clientId=9202757120653") == {"client_id": "9202757120653"}
    with pytest.raises(ValueError):
        refs.resolve_agency("https://example.com/pro/x/")
    with pytest.raises(ValueError):
        refs.resolve_agency("not a slug!")


def test_classify_location():
    assert refs.classify_location("724,14,28,173,0,28079,0,0,0") == ("combined", "724,14,28,173,0,28079,0,0,0")
    assert refs.classify_location("calle-serrano-madrid-capital") == ("area", "calle-serrano-madrid-capital")
    assert refs.classify_location("Madrid") == ("name", "Madrid")
    assert refs.classify_location("Barrio de Salamanca, Madrid") == ("name", "Barrio de Salamanca, Madrid")
    kind, (path, query) = refs.classify_location(
        "https://www.fotocasa.es/es/comprar/viviendas/madrid-capital/todas-las-zonas/l?maxPrice=300000")
    assert kind == "link" and path == "/es/comprar/viviendas/madrid-capital/todas-las-zonas/l"
    assert query == {"maxPrice": "300000"}
    with pytest.raises(ValueError):
        refs.classify_location("https://example.com/x")


def test_split_list_link():
    link = refs.split_list_link("/es/comprar/viviendas/madrid-capital/todas-las-zonas/l/2", {"minRooms": "2"})
    assert (link["transaction"], link["property_type"], link["location"], link["zone"], link["page"]) == \
        ("buy", "homes", "madrid-capital", "todas-las-zonas", 2)
    link = refs.split_list_link("/en/rent/homes/barcelona-capital/all-zones/l", {})
    assert (link["language"], link["transaction"]) == ("en", "rent")
    link = refs.split_list_link("/es/comprar/viviendas/area/calle-serrano-madrid-capital/l", {})
    assert link["area"] == "calle-serrano-madrid-capital"
    link = refs.split_list_link("/es/comprar/pisos/madrid-capital/todas-las-zonas/banco/l", {})
    assert link["feature"] == "banco"
    with pytest.raises(ValueError):
        refs.split_list_link("/es/comprar/vivienda/x/x/184433815/d", {})


def test_resolve_price_index_location():
    assert refs.resolve_price_index_location("madrid-capital") == ("slugs", ("madrid-capital", None))
    assert refs.resolve_price_index_location("madrid-capital/barrio-de-salamanca") == \
        ("slugs", ("madrid-capital", "barrio-de-salamanca"))
    assert refs.resolve_price_index_location(
        "https://www.fotocasa.es/es/indice-precio-vivienda/madrid-capital/todas-las-zonas") == \
        ("slugs", ("madrid-capital", None))
    assert refs.resolve_price_index_location("Madrid") == ("name", "Madrid")
    assert refs.resolve_price_index_location("724,14,28,173,0,28079,0,0,0") == ("combined", "724,14,28,173,0,28079,0,0,0")


def test_resolve_directory_location():
    assert refs.resolve_directory_location("madrid-capital/barrio-de-salamanca") == \
        ("slugs", ("madrid-capital", "barrio-de-salamanca"))
    assert refs.resolve_directory_location(
        "https://www.fotocasa.es/buscar-agencias-inmobiliarias/madrid-capital/todas-las-zonas/l?pagina=2") == \
        ("slugs", ("madrid-capital", None))
    assert refs.resolve_directory_location("Barcelona") == ("name", "Barcelona")


def test_paths():
    assert refs.list_path("es", "buy", "homes", "madrid-capital") == "/es/comprar/viviendas/madrid-capital/todas-las-zonas/l"
    assert refs.list_path("es", "rent", "homes", "madrid-capital", "chamberi", page=3) == \
        "/es/alquiler/viviendas/madrid-capital/chamberi/l/3"
    assert refs.list_path("es", "buy", "homes", None, area="calle-serrano-madrid-capital") == \
        "/es/comprar/viviendas/area/calle-serrano-madrid-capital/l"
    assert refs.detail_path("es", "184433815") == "/es/comprar/vivienda/x/x/184433815/d"
    assert refs.detail_path("en", "184433815", "rent") == "/es/alquiler/vivienda/x/x/184433815/d"
    assert refs.promotion_path("es", "20678485") == "/es/comprar/obra-nueva/x/20678485"
    assert refs.agency_path("es", "fortuny-madrid-real-estate") == "/es/pro/fortuny-madrid-real-estate/"
    assert refs.agency_path("es", "fortuny-madrid-real-estate", "buy", "homes", 2) == \
        "/es/pro/fortuny-madrid-real-estate/comprar/viviendas/espana/todas-las-zonas/l/2"
    assert refs.directory_path("madrid-capital", None, 2) == "/buscar-agencias-inmobiliarias/madrid-capital/todas-las-zonas/l?pagina=2"
    assert refs.price_index_path("madrid-capital", "barrio-de-salamanca") == \
        "/es/indice-precio-vivienda/madrid-capital/barrio-de-salamanca"


# ---- value helpers -------------------------------------------------------------------------

def test_scalar_helpers():
    assert P._int("12.717") == 12717
    assert P._int("2.995.000 €") == 2995000
    assert P._float("6179,85") == 6179.85
    assert P._positive(0) is None and P._positive(3) == 3
    assert P._iso(1727435227643) == "2024-09-27T11:07:07Z"
    assert P._iso("2026-09-22T18:31:10.987Z") == "2026-09-22T18:31:10Z"
    assert P._iso("2026-02-10T10:00:18.562814482Z") == "2026-02-10T10:00:18Z"
    assert P._iso("0001-01-01T00:00:00") is None
    assert P._iso("2017-01-25") == "2017-01-25"
    assert P._month("20261001") == "2026-10"
    assert P._price(2995000, 205000, 0) == {"amount": 2995000, "currency": "EUR", "period": None,
                                            "previous_amount": 3200000, "drop": 205000}
    assert P._price(1400, 0, 3)["period"] == "month"
    assert P._price(0) is None
    assert P._clean("a\r\n\r\n\r\nb  c") == "a\n\nb c"


# ---- gateway search ------------------------------------------------------------------------

def test_search_madrid_shape(madrid):
    assert madrid["count"] == 12719
    assert len(madrid["results"]) == 30
    assert madrid["location"] == {"name": "Madrid Capital", "slug": "madrid-capital/todas-las-zonas",
                                  "location_id": "724,14,28,173,0,28079,0,0,0", "level": "municipality"}
    assert madrid["slugs"] == {"location": "madrid-capital", "zone": "todas-las-zonas"}
    assert "districts" in madrid["facets"] and madrid["facets"]["districts"][0]["name"] == "Arganzuela"
    assert madrid["facets"]["districts"][0]["location_id"] == "724,14,28,173,0,28079,0,671,0"
    assert madrid["facets"]["districts"][0]["listings_count"] == 536
    assert madrid["agency"] is None
    assert madrid["new_developments"] and madrid["new_developments"][0]["new_development"]["name"] == "RESIDENCIAL AZORES"


def test_search_card(madrid):
    card = madrid["results"][0]
    assert card["id"] == "190909371"
    assert card["link"].startswith("https://www.fotocasa.es/es/comprar/vivienda/madrid-capital/") and card["link"].endswith("/190909371/d")
    assert (card["transaction"], card["property_type"], card["property_subtype"]) == ("buy", "homes", "penthouse")
    assert card["price"] == {"amount": 2990000, "currency": "EUR", "period": None, "previous_amount": None, "drop": None}
    assert (card["rooms"], card["bathrooms"], card["surface_m2"], card["floor"], card["condition"]) == \
        (3, 4, 209, "8th_floor", "very_good")
    assert card["amenities"] == ["air_conditioning", "heating", "lift", "terrace"]
    assert card["address"]["neighborhood"] == "Goya" and card["address"]["district"] == "Barrio de Salamanca"
    assert card["address"]["municipality"] == "Madrid Capital" and card["address"]["zip_code"] == "28009"
    assert card["address"]["location_id"] == "724,14,28,173,0,28079,0,667,18"
    assert card["address"]["coordinates"] == {"latitude": 40.42466, "longitude": -3.673746, "is_exact": False}
    assert card["photos"][0]["link"].startswith("https://static.fotocasa.es/images/ads/") and card["photos"][0]["room"] == "terrace"
    assert card["photos_count"] == len(card["photos"])
    assert card["advertiser"] == {"id": "9202775531783", "name": "ESPÍGUL IMMOBILIARIA", "type": "professional",
                                  "phone": "+34913439848",
                                  "logo": "https://static.fotocasa.es/images/client/fa292226-6f00-4e3d-bede-0b5e7968f6d8/20251006115448?rule=original",
                                  "link": "https://www.fotocasa.es/es/pro/espigul-immobiliaria/"}
    assert card["published_at"] == "2026-09-22T18:31:10Z"
    assert card["is_featured"] is True and card["is_new_construction"] is False
    assert card["new_development"] is None


def test_search_price_drop_card(madrid):
    dropped = [c for c in madrid["results"] if c["price"]["drop"]]
    assert dropped and dropped[0]["price"]["previous_amount"] == dropped[0]["price"]["amount"] + dropped[0]["price"]["drop"]


def test_search_rent():
    parsed = P.parse_search(fixture("search_rent_madrid.json"))
    card = parsed["results"][0]
    assert card["transaction"] == "rent" and card["price"]["period"] == "month" and card["price"]["amount"] == 1400
    assert card["published_at"].endswith("Z")


def test_search_share_and_transfer():
    share = P.parse_search(fixture("search_share_madrid.json"))
    assert share["results"][0]["transaction"] == "share" and share["count"] == 14661
    transfer = P.parse_search(fixture("search_transfer_premises_madrid.json"))
    assert transfer["results"][0]["transaction"] == "transfer" and transfer["results"][0]["property_type"] == "premises"


def test_search_new_construction():
    parsed = P.parse_search(fixture("search_new_construction_madrid.json"))
    card = parsed["results"][0]
    assert card["is_new_construction"] is True
    assert card["link"] == "https://www.fotocasa.es/es/comprar/vivienda/obra-nueva/madrid-capital/20678485/191171924"
    promo = card["new_development"]
    assert promo["name"] == "RESIDENCIAL AZORES" and promo["link"].endswith("/obra-nueva/madrid-capital/20678485")
    assert promo["typologies_count"] == 8 and promo["typologies"][0]["price"]["amount"] == 484900
    assert promo["typologies"][0]["property_subtype"] == "ground_floor"


def test_search_english_culture_links():
    parsed = P.parse_search(fixture("search_buy_madrid_en.json"), "en")
    assert parsed["results"][0]["link"].startswith("https://www.fotocasa.es/en/buy/home/")


def test_search_agency_block():
    parsed = P.parse_search(fixture("search_agency_fortuny.json"))
    assert parsed["count"] == 42
    agency = parsed["agency"]
    assert agency["id"] == "9202757120653" and agency["slug"] == "fortuny-madrid-real-estate"
    assert agency["email"] == "info@fortunyrealestate.com" and agency["phones"] == ["914388268"]
    assert agency["website"] == "https://www.fortunyrealestate.com/"
    assert (agency["for_sale_count"], agency["for_rent_count"], agency["listings_count"]) == (43, 4, 47)
    assert all(c["advertiser"]["name"] == "FORTUNY MADRID REAL ESTATE" for c in parsed["results"])


def test_search_empty_and_unknown_agency():
    empty = P.parse_search(fixture("search_empty.json"))
    assert empty["count"] == 0 and empty["results"] == [] and empty["location"] is None
    unknown = P.parse_search(fixture("search_unknown_agency.json"))
    assert unknown["count"] == 0 and unknown["agency"] is None


def test_selected_location_levels():
    payload = fixture("search_buy_madrid.json")
    assert P.selected_location(payload["breadcrumb"])["level"] == "municipality"
    assert P.selected_location({"regions": [{"literal": "x", "selected": False}]}) is None
    assert P.selected_location(None) is None


# ---- typeahead --------------------------------------------------------------------------------

def test_suggestions():
    rows = P.parse_suggestions(fixture("suggest_madrid.json"))
    assert rows[0] == {"name": "Madrid, Madrid", "short_name": "Madrid", "level": "municipality", "kind": "location",
                       "location_id": "724,14,28,173,0,28079,0,0,0", "area": None, "code": "28079",
                       "coordinates": {"latitude": 40.4096, "longitude": -3.68624}, "has_children": True,
                       "is_point_of_interest": False, "score": rows[0]["score"]}
    assert rows[1]["level"] == "province" and rows[1]["location_id"] == "724,14,28,0,0,0,0,0,0"
    street = P.parse_suggestions(fixture("suggest_calle_serrano.json"))[0]
    assert street["level"] == "street" and street["area"] == "calle-serrano-madrid-capital" and street["location_id"] is None
    zipcode = P.parse_suggestions(fixture("suggest_zip_28001.json"))[0]
    assert zipcode["level"] == "zip_code" and zipcode["location_id"] is None and zipcode["area"] is None
    salamanca = P.parse_suggestions(fixture("suggest_salamanca.json"))
    assert any(r["level"] == "district" and r["name"] == "Barrio de Salamanca, Madrid" for r in salamanca)
    assert any(r["level"] == "urbanization" and r["area"] for r in salamanca)
    assert P.parse_suggestions(fixture("suggest_empty.json")) == []
    assert P.parse_suggestions(None) == []


# ---- detail pages -----------------------------------------------------------------------------

def test_detail_sale(sale_detail):
    d = sale_detail
    assert d["id"] == "184433815"
    assert d["title"] == "Piso en venta en Castellana, Madrid Capital"
    assert d["link"] == "https://www.fotocasa.es/es/comprar/vivienda/madrid/aire-acondicionado-calefaccion-terraza-trastero-ascensor/184433815/d"
    assert set(d["links"]) == {"es", "en", "ca", "de"}
    assert (d["transaction"], d["property_type"], d["property_subtype"], d["typology"]) == ("buy", "homes", "flat", "flat")
    assert d["price"] == {"amount": 2995000, "currency": "EUR", "period": None, "previous_amount": 3200000, "drop": 205000}
    assert (d["rooms"], d["bathrooms"], d["surface_m2"], d["land_surface_m2"]) == (4, 4, 256, None)
    assert (d["floor"], d["orientation"], d["condition"], d["age"], d["construction"]) == \
        ("1st_floor", "east", "very_good", "between_70_and_100_years", "second_hand")
    assert d["has_lift"] is True and d["is_furnished"] is False and d["occupancy"] == "available"
    assert d["energy_certificate"] == {"status": "valid", "rating": "G", "consumption_kwh_m2_year": None,
                                       "emissions_rating": "G", "emissions_kg_co2_m2_year": None}
    # amenity ids [1, 2, 3, 10, 11, 84, 109, 131] + the lift from the V2 typed features
    assert d["amenities"] == ["air_conditioning", "wardrobes", "heating", "terrace", "storage_room", "armored_door",
                              "laundry", "equipped_kitchen", "lift"]
    assert set(d["amenities"]) <= set(refs.AMENITIES.values())
    assert d["is_featured"] is False and d["has_subsidies"] is False and d["is_external_contact"] is False
    assert "is_bank_owned" not in d and "is_franchise" not in d["advertiser"]
    assert d["description"].startswith("Maravillosa vivienda de 256m²")
    assert d["address"]["neighborhood"] == "Castellana" and d["address"]["district"] == "Barrio de Salamanca"
    assert d["address"]["municipality"] == "Madrid" and d["address"]["zip_code"] == "28001"
    assert d["address"]["coordinates"]["is_exact"] is False
    assert d["photos_count"] == 56 and d["photos"][0]["position"] == 1
    adv = d["advertiser"]
    assert adv["id"] == "9202757120653" and adv["type"] == "professional" and adv["phone"] == "+34914388268"
    assert adv["reference"] == "PIS3381" and adv["website"] == "https://www.fortunyrealestate.com/"
    assert adv["slug"] == "fortuny-madrid-real-estate" and adv["link"] == "https://www.fotocasa.es/es/pro/fortuny-madrid-real-estate/"
    assert d["published_at"] == "2024-09-27T11:07:07" and d["updated_at"] is None
    assert d["new_development"] is None and d["is_new_construction"] is False
    assert d["breadcrumb"][0]["name"] == "Madrid"
    assert d["location_slugs"] == {"location": "madrid-capital", "zone": "castellana"}


def test_detail_rent():
    d = P.parse_detail(fixture("detail_rent_191331052.html"))
    assert d["transaction"] == "rent" and d["price"]["period"] == "month" and d["price"]["amount"] == 1400
    assert d["rental_duration"] == "temporary" and d["is_temporary_rental"] is True
    assert d["is_furnished"] is True and d["has_lift"] is False
    assert d["advertiser"]["name"] == "HOUSINGANYWHERE" and d["advertiser"]["phone"] is None


def test_detail_private_seller():
    d = P.parse_detail(fixture("detail_private_rent_191319830.html"))
    assert d["advertiser"]["type"] == "private" and d["advertiser"]["phone"] is None
    assert d["advertiser"]["link"] is None and d["advertiser"]["slug"] is None
    assert d["advertiser"]["listings_link"].endswith("?clientId=9202750520561")


def test_detail_english_rendering():
    d = P.parse_detail(fixture("detail_sale_184433815_en.html"))
    assert d["title"] == "Flat for sale in Castellana, Madrid Capital"
    # amenities are language-independent: the English page names them like the Spanish one
    assert d["amenities"] == P.parse_detail(fixture("detail_sale_184433815.html"))["amenities"]
    assert d["has_lift"] is True
    assert d["floor"] == "1st_floor" and d["age"] == "between_70_and_100_years"


def test_detail_new_build_unit():
    d = P.parse_detail(fixture("detail_new_build_unit_191171924.html"))
    assert d["id"] == "191171924" and d["is_new_construction"] is True
    assert d["new_development"]["id"] == "20678485" and d["new_development"]["name"] == "RESIDENCIAL AZORES"
    assert d["new_development"]["unit_reference"] == "P1 bajo E"
    assert d["condition"] == "new_build" and d["property_subtype"] == "ground_floor"
    # the unit page's legacy amenity table is empty; the ids come from unitDetail.extras
    assert d["amenities"] == ["lift", "storage_room", "community_parking", "air_conditioning", "armored_door",
                              "community_pool", "community_area", "gym", "childrens_area", "ensuite_bathroom",
                              "terrace"]


@pytest.mark.parametrize("raw,expected", [
    ("N/a, -1, Nueva Andalucía", "Nueva Andalucía"),
    ("N/a, Nueva Andalucía", "Nueva Andalucía"),
    ("Avenida Calderón de la Barca, -1, Nueva Andalucía", "Avenida Calderón de la Barca, Nueva Andalucía"),
    ("Calle de Jorge Juan, 171, Barrio de Salamanca", "Calle de Jorge Juan, 171, Barrio de Salamanca"),
    ("Casa o chalet en venta en N/a, -1, Las Brisas, Marbella", "Casa o chalet en venta en Las Brisas, Marbella"),
    ("Calle Mayor, -1", "Calle Mayor"),
    ("N/A", None),
    ("N/a, -1", None),
    (None, None),
])
def test_strip_placeholders(raw, expected):
    assert P._strip_placeholders(raw) == expected


def test_detail_hidden_street():
    """The site's placeholders for a hidden street (name "N/A", number -1)
    never reach the record: street, number and title come back clean."""
    d = P.parse_detail(fixture("detail_hidden_street_160269745.html"))
    assert d["title"] == "Casa o chalet en venta en Las Brisas, Marbella"
    assert d["address"]["street"] is None and d["address"]["street_number"] is None
    assert d["address"]["neighborhood"] == "Las Brisas" and d["address"]["district"] == "Nueva Andalucía"
    assert d["address"]["coordinates"]["is_exact"] is True
    assert d["price"]["amount"] == 11800000 and d["rooms"] == 9
    # 19 amenity ids, every one named from the site's own id table
    assert d["amenities"] == ["air_conditioning", "wardrobes", "garden", "terrace", "community_area",
                              "kitchen_office", "yard", "swimming_pool", "ensuite_bathroom", "appliances", "oven",
                              "tv", "jacuzzi", "gym", "internet", "sports_area", "childrens_area", "armored_door",
                              "equipped_kitchen"]


def test_amenities_from_ids_falls_back_to_the_label():
    assert P._amenities_from_ids([1, 13, 999], {"999": "Piscina Climatizada"}) == \
        ["air_conditioning", "lift", "piscina_climatizada"]
    assert P._amenities_from_ids(None) == []


def test_amenity_vocabulary_matches_the_filters():
    """Every search filter value is also the name responses use for that id."""
    for name, feature_id in refs.FEATURES.items():
        assert refs.AMENITIES[feature_id] == name


def test_detail_not_found_page():
    html = fixture("detail_not_found.html")      # the list page the dead id redirects to
    assert not P.is_detail_page(html)
    with pytest.raises(ValueError):
        P.parse_detail(html)


# ---- new developments -----------------------------------------------------------------------

def test_promotion(promotion):
    p = promotion
    assert p["id"] == "20678485" and p["name"] == "RESIDENCIAL AZORES"
    assert p["link"] == "https://www.fotocasa.es/es/comprar/obra-nueva/madrid-capital/20678485"
    assert p["links"]["en"] == "https://www.fotocasa.es/en/buy/new-home/madrid-capital/20678485"
    assert p["price_range"] == {"min": 484900, "max": 649900, "currency": "EUR"} and p["rent_range"] is None
    assert p["rooms_range"] == {"min": 2, "max": 3} and p["surface_range_m2"] == {"min": 96, "max": 129}
    assert p["units_count"] == 7 and len(p["units"]) == 7
    unit = p["units"][0]
    assert unit["id"] == "191171924" and unit["reference"] == "P1 bajo E" and unit["price"]["amount"] == 484900
    assert unit["link"] == "https://www.fotocasa.es/es/comprar/vivienda/obra-nueva/madrid-capital/20678485/191171924"
    assert unit["floor"] == "ground_floor" and unit["heating"] == "electricity" and "terrace" in unit["amenities"]
    # unit amenities come from the extras' amenity ids (keyNames carry typos like "wardroves")
    assert unit["amenities"] == sorted(["lift", "storage_room", "community_parking", "air_conditioning",
                                        "armored_door", "community_pool", "community_area", "gym",
                                        "childrens_area", "ensuite_bathroom", "terrace"])
    assert unit["photos_count"] == 18
    assert p["unit_groups"][0] == {"rooms": 2, "units_count": 2, "min_price": 484900, "max_price": 544900,
                                   "min_surface_m2": 96, "max_surface_m2": 111, "unit_ids": ["191171924", "188806991"]}
    assert p["energy_certificate"]["rating"] == "A" and p["energy_certificate"]["consumption_kwh_m2_year"] is None
    assert p["address"]["neighborhood"] == "Los Berrocales" and p["address"]["district"] == "Vicálvaro"
    assert p["address"]["coordinates"]["latitude"] == pytest.approx(40.37708, abs=1e-4)
    assert p["photos_count"] == 18 and p["virtual_tours"] == ["https://epsylongroup.com/clientes/premier/Azores/Maqueta/index.html"]
    assert p["advertiser"]["name"] == "PREMIER MADRID" and p["advertiser"]["phone"] == "+34914560997"
    assert p["advertiser"]["slug"] == "premier-madrid"
    assert p["published_at"] == "2026-02-10T10:00:18Z" and p["updated_at"] == "2026-09-09T14:17:58Z"
    assert p["is_finished"] is False


def test_promotion_not_found_page():
    html = fixture("promotion_not_found.html")
    assert not P.is_promotion_page(html)
    with pytest.raises(ValueError):
        P.parse_promotion(html)


# ---- agency minisite ------------------------------------------------------------------------

def test_agency_profile(agency):
    profile = agency["profile"]
    assert profile["id"] == "9202757120653" and profile["slug"] == "fortuny-madrid-real-estate"
    assert profile["name"] == "FORTUNY MADRID REAL ESTATE"
    assert profile["link"] == "https://www.fotocasa.es/es/pro/fortuny-madrid-real-estate/"
    assert profile["links"]["en"] == "https://www.fotocasa.es/en/pro/fortuny-madrid-real-estate/"
    assert profile["email"] == "info@fortunyrealestate.com" and profile["phones"] == ["914 38 82 68"]
    assert profile["website"] == "https://www.fortunyrealestate.com/" and profile["website_domain"] == "www.fortunyrealestate.com"
    assert profile["address"].startswith("calle Monte Esquinza 42") and profile["zip_code"] == "28010"
    assert profile["coordinates"] == {"latitude": 40.43095, "longitude": -3.69161}
    assert profile["member_since"] == "2017-01-25"
    assert (profile["listings_count"], profile["for_sale_count"], profile["for_rent_count"]) == (47, 43, 4)
    assert profile["listings_by_type"]["homes"] == 46
    assert profile["inventory"][0] == {"transaction": "buy", "property_type": "homes", "count": 42}
    assert profile["business_hours"]["monday"] == {"is_closed": False, "hours": None}


def test_agency_listing(agency):
    listing = agency["listing"]
    assert listing["count"] == 42 and listing["page"] == 1 and listing["page_size"] == 15
    assert len(listing["results"]) == 15
    card = listing["results"][0]
    assert card["id"] == "191107804" and card["price"]["amount"] == 1190000
    assert card["floor"] == "6th_floor" and card["condition"] == "very_good" and card["age"] == "more_than_100_years"
    assert "furnished" in card["amenities"] and "exterior" in card["amenities"]
    assert card["advertiser"]["link"] == "https://www.fotocasa.es/es/pro/fortuny-madrid-real-estate/"
    # the minisite's legacy address keys (county, regionLevel1) fill region / community
    assert card["address"]["region"] and card["address"]["autonomous_community"] == "Madrid"
    page2 = P.parse_agency(fixture("agency_fortuny_page2.html"))
    assert page2["listing"]["page"] == 2 and page2["listing"]["count"] == 42


def test_agency_not_found_page():
    html = fixture("agency_not_found.html")
    assert not P.is_agency_page(html)
    with pytest.raises(ValueError):
        P.parse_agency(html)


# ---- agencies directory ---------------------------------------------------------------------

def test_directory():
    d = P.parse_directory(fixture("agencies_directory_madrid.html"))
    assert d["title"] == "Inmobiliarias en Madrid Capital"
    assert d["totals"] == {"for_sale_agencies": 1890, "for_rent_agencies": 647}
    assert d["page"] == 1 and len(d["results"]) == 15
    first = d["results"][0]
    assert first["id"] == "9202765062251" and first["name"] == "ENGEL & VÖLKERS MADRID"
    assert first["slug"] == "engel-volkers-madrid" and first["link"] == "https://www.fotocasa.es/es/pro/engel-volkers-madrid/"
    assert first["logo"].startswith("https://static.fotocasa.es/images/client/")
    assert first["cover_photo"].startswith("https://static.fotocasa.es/images/ads/")
    assert (first["listings_in_zone_count"], first["listings_count"]) == (685, 1409)
    assert first["lowest_price"]["amount"] == 170000 and first["transaction"] == "buy"
    district = P.parse_directory(fixture("agencies_directory_salamanca.html"))
    assert district["title"] == "Inmobiliarias en Barrio de Salamanca (Madrid)" and len(district["results"]) == 15


def test_directory_broken_zero_counters():
    """Marbella's page printed "0 inmobiliarias … 0 agencias" above 15 agencies,
    and 0 published listings next to hundreds in the zone: unknown, not zero."""
    d = P.parse_directory(fixture("agencies_directory_marbella_zero_counters.html"))
    assert len(d["results"]) == 15
    assert d["totals"] == {"for_sale_agencies": None, "for_rent_agencies": None}
    first = d["results"][0]
    assert first["listings_in_zone_count"] > 0 and first["listings_count"] is None
    assert first["lowest_price"]["amount"] > 0


def test_directory_past_end_and_unknown():
    past = P.parse_directory(fixture("agencies_directory_past_end.html"))
    assert past["results"] == [] and past["totals"]["for_sale_agencies"] == 1890
    unknown = P.parse_directory(fixture("agencies_directory_unknown.html"))
    assert unknown["results"] == [] and unknown["totals"] == {"for_sale_agencies": 0, "for_rent_agencies": 0}


# ---- price index ----------------------------------------------------------------------------------

def test_price_index_municipality():
    p = P.parse_price_index(fixture("price_index_madrid.html"))
    assert (p["id"], p["name"], p["slug"], p["level"]) == ("28079", "Madrid Capital", "madrid-capital", "municipality")
    assert p["link"] == "https://www.fotocasa.es/es/indice-precio-vivienda/madrid-capital/todas-las-zonas"
    assert p["sale"]["median_price_per_m2"] == pytest.approx(6179.86, abs=0.01)
    assert p["sale"]["mean_price_per_m2"] == pytest.approx(7064.79, abs=0.01)
    assert p["sale"]["market_temperature"] == "hot" and p["rent"]["market_temperature"] == "hot"
    assert p["sale"]["history"][0] == {"month": "2020-01", "price_per_m2": 4247.31}
    assert p["rent"]["history"][-1] == {"month": "2026-10", "price_per_m2": 23.11}
    assert len(p["sale"]["history"]) == 82
    assert p["province"]["slug"] == "madrid-provincia" and p["municipality"] is None
    assert len(p["districts"]) == 22
    district = p["districts"][0]
    assert district["slug"] == "encinar-de-los-reyes" and district["sale"]["median_price_per_m2"] == 7019.55
    assert district["sale"]["change_percent"] == {"1_month": 1.23, "3_months": 7.28, "6_months": 20.22, "12_months": 19.48}
    assert district["rent"]["median_price_per_m2"] == 21.43
    assert len(p["related"]) == 179 and p["related"][0]["slug"] == "la-acebeda"


def test_price_index_district():
    p = P.parse_price_index(fixture("price_index_barrio_de_salamanca.html"))
    assert (p["slug"], p["level"]) == ("barrio-de-salamanca", "district")
    assert p["municipality"] == {"id": "28079", "name": "Madrid", "slug": "madrid-capital"}
    assert p["sale"]["median_price_per_m2"] == pytest.approx(11923.08, abs=0.01)
    assert p["sale"]["market_temperature"] == "moderate"
    assert len(p["neighborhoods"]) == 6 and p["neighborhoods"][0]["slug"] == "lista"
    assert p["neighborhoods"][0]["rent"]["change_percent"]["12_months"] == 1.57


def test_price_index_not_found_page():
    with pytest.raises(ValueError):
        P.parse_price_index(fixture("price_index_not_found.html"))


# ---- server-rendered search pages --------------------------------------------------------------

def test_area_page():
    p = P.parse_list_page(fixture("list_area_calle_serrano.html"))
    assert p["count"] == 120 and len(p["results"]) == 31 and p["page"] == 1 and p["page_size"] == 30
    assert p["title"] == "Casas y pisos en Calle Serrano, Madrid"
    assert p["link"] == "https://www.fotocasa.es/es/comprar/viviendas/area/calle-serrano-madrid-capital/l"
    assert p["location"]["area"] == "calle-serrano-madrid-capital" and p["location"]["name"] == "Calle Serrano, Madrid"
    assert (p["transaction"], p["property_type"]) == ("buy", "homes")
    card = p["results"][0]
    assert card["id"] == "188840617" and card["price"] == {"amount": 3875000, "currency": "EUR", "period": None,
                                                          "previous_amount": 4280000, "drop": 405000}
    assert card["address"]["neighborhood"] == "Recoletos" and card["address"]["location_id"] == "724,14,28,173,0,28079,0,667,17"
    assert card["address"]["coordinates"]["latitude"] == pytest.approx(40.422, abs=1e-3)
    assert card["floor"] == "5th_floor" and card["photos"][0]["room"] == "living room"
    assert card["advertiser"]["name"] == "Olisson" and card["advertiser"]["link"] == "https://www.fotocasa.es/es/pro/olisson/"


def test_filtered_link_page():
    p = P.parse_list_page(fixture("list_link_filtered_madrid.html"))
    assert p["count"] == 2386 and p["location"]["level"] == "municipality"
    assert p["location"]["location_id"] == "724,14,28,173,0,28079,0,0,0"
    assert p["mean_prices"]["sale_price_per_m2"] > 5000 and len(p["mean_prices"]["sale_history"]) == 24
    assert p["facets"]["districts"][0]["name"] == "Arganzuela"
    assert p["facets"]["districts"][0]["listings_count"] == 32      # the filtered count
    assert p["link"].endswith("?sortType=price&sortOrderDesc=false")


def test_list_page_rejects_other_pages():
    with pytest.raises(ValueError):
        P.parse_list_page(fixture("list_area_not_found.html"))
    with pytest.raises(ValueError):
        P.parse_list_page(fixture("detail_sale_184433815.html"))


# ---- fetch helpers (no network) ---------------------------------------------------------------

def test_block_detection():
    assert F.is_block_page("<html><head><title>Pardon Our Interruption</title>") is True
    assert F.is_block_page(fixture("detail_sale_184433815.html")) is False
    assert F.page_title("<title> x </title>") == "x"


# ---- the gateway's result window (no network) ---------------------------------------------------

def test_gateway_window_blanks_the_fallback_page(monkeypatch):
    """Past ~9,970 rows the gateway answers with an unrelated 30-row fallback
    page; the search must come back empty there and stop paging before it."""
    from fotocasa import api

    monkeypatch.setattr(api, "fetch_search", lambda params: params)
    monkeypatch.setattr(api.parsers, "parse_search",
                        lambda raw, language: {"count": 12703, "results": [{"id": str(raw["pageNumber"])}]})
    madrid = "724,14,28,173,0,28079,0,0,0"
    assert api._gateway_search(madrid, "buy", "homes", 99, 100, "es", {})["results"] == [{"id": "99"}]
    assert api._gateway_search(madrid, "buy", "homes", 100, 100, "es", {})["results"] == []
    assert api._gateway_search(madrid, "buy", "homes", 332, 30, "es", {})["results"] == [{"id": "332"}]
    assert api._gateway_search(madrid, "buy", "homes", 25, 400, "es", {})["results"] == []
    assert api._pagination(12703, 1, 100, refs.GATEWAY_WINDOW // 100)["total_pages"] == 99
    assert api._pagination(12703, 1, 400, refs.GATEWAY_WINDOW // 400)["total_pages"] == 24
    assert api._pagination(250, 1, 100, refs.GATEWAY_WINDOW // 100)["total_pages"] == 3
