"""Marshmallow request schemas for every /fotocasa/* route.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair):

    property    a numeric listing id (184433815) OR any fotocasa.es listing link
    promotion   a numeric new-development id (20678485) OR its fotocasa.es link
    agency      a minisite slug (fortuny-madrid-real-estate), a numeric client
                id, a /pro/<slug>/ link, an /inmobiliarias/<name>-<id> link or
                a listing link carrying ?clientId=
    location    a place name ("Madrid", "Barrio de Salamanca, Madrid"), a
                combined location id from locations/search
                ("724,14,28,173,0,28079,0,0,0"), a street / urbanisation area
                slug from locations/search ("calle-serrano-madrid-capital")
                OR any fotocasa.es search link (its filters and page are kept)

The filter vocabularies are the site's own enums (fotocasa/refs.py, read
from its JS bundle on 2026-11-07). `language` picks the rendering locale
of the site's pages and of the links in the answers (es, en, ca, de).
"""
from marshmallow import ValidationError, validates_schema

from schema_fields import (BaseSchema, ChoiceField, CommaListField, Flag, PageField, PageSizeField, PositiveInt,
                           QueryField, RefField, StrippedString)
from fotocasa import refs


class PropertyRefField(RefField):
    resolver = staticmethod(refs.resolve_property)


class PromotionRefField(RefField):
    resolver = staticmethod(refs.resolve_promotion)


class AgencyRefField(RefField):
    resolver = staticmethod(refs.resolve_agency)


class _ClassifiedField(StrippedString):
    """Keeps the raw value after a no-network classification (api.py
    resolves names through the typeahead)."""
    classifier = None

    def __init__(self, **kwargs):
        kwargs.setdefault("required", True)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        if value is None:
            return None
        try:
            type(self).classifier(value)
        except ValueError as e:
            raise ValidationError(str(e))
        return value


class LocationField(_ClassifiedField):
    classifier = staticmethod(refs.classify_location)


class PriceIndexLocationField(_ClassifiedField):
    classifier = staticmethod(refs.resolve_price_index_location)


class DirectoryLocationField(_ClassifiedField):
    classifier = staticmethod(refs.resolve_directory_location)


def _language():
    return ChoiceField(list(refs.LANGUAGES), load_default=refs.DEFAULT_LANGUAGE, metadata={
        "description": "language of the site pages and of the links in the answer: es (default), en, ca or de"})


def _transaction():
    return ChoiceField(list(refs.TRANSACTIONS), load_default="buy", metadata={
        "description": "buy (default), rent, share (rooms), rent_to_buy or transfer (business transfers of premises)"})


def _property_type():
    return ChoiceField(list(refs.PROPERTY_TYPES), load_default="homes", metadata={
        "description": "homes (default; new builds via new_construction=true), garages, land, premises, offices, "
                       "storage_rooms or buildings"})


class _FilterMixin:
    """The search filters shared by properties/search and agencies/listings
    (the gateway's own filter params)."""
    subtypes = CommaListField(allowed=list(refs.SUBTYPES), upper=False, max_items=10, metadata={
        "description": "home subtypes, comma-separated: flat, apartment, house, semi_detached, penthouse, duplex, "
                       "loft, rural_house, ground_floor, studio (land: land, residential_land, industrial_land, "
                       "constructible_land, non_constructible_land; premises: commercial_store, industrial_building)"})
    min_price = PositiveInt(metadata={"description": "minimum price in EUR (monthly rent for rentals)"})
    max_price = PositiveInt(metadata={"description": "maximum price in EUR (monthly rent for rentals)"})
    min_rooms = PositiveInt(max_value=10, metadata={"description": "minimum bedrooms (1-10)"})
    max_rooms = PositiveInt(max_value=10, metadata={"description": "maximum bedrooms (1-10)"})
    min_bathrooms = PositiveInt(max_value=10, metadata={"description": "minimum bathrooms (1-10)"})
    max_bathrooms = PositiveInt(max_value=10, metadata={"description": "maximum bathrooms (1-10)"})
    min_surface = PositiveInt(metadata={"description": "minimum built area in m²"})
    max_surface = PositiveInt(metadata={"description": "maximum built area in m²"})
    condition = CommaListField(allowed=list(refs.CONDITIONS), upper=False, max_items=6, metadata={
        "description": "conservation states, comma-separated: almost_new, very_good, good, needs_renovation, "
                       "refurbished, new_build"})
    features = CommaListField(allowed=list(refs.FEATURES), upper=False, max_items=20, metadata={
        "description": "required features, comma-separated: air_conditioning, wardrobes, heating, parking, garden, "
                       "parquet, terrace, storage_room, community_area, lift, yard, swimming_pool, community_pool, "
                       "furnished, not_furnished, kitchen, equipped_kitchen, appliances, community_parking, porter, "
                       "balcony, jacuzzi, pets_allowed, internet, cellar, sauna, golf, alarm, solar_energy, "
                       "video_intercom, armored_door, laundry, seafront, sea_views, mountain_views, guest_bathroom, "
                       "home_automation, smoke_outlet, loading_area, access_24_7, community_fees_included"})
    published = ChoiceField(list(refs.PUBLISHED), metadata={
        "description": "only listings published in the last_24_hours, last_48_hours, last_week or last_month"})
    new_construction = Flag(metadata={"description": "true = new builds only (homes)"})
    price_drop = Flag(metadata={"description": "true = only listings whose price was reduced"})
    bank_owned = Flag(metadata={"description": "true = only bank-owned listings"})
    with_photos = Flag(metadata={"description": "true = only listings with photos"})
    with_video = Flag(metadata={"description": "true = only listings with a video or virtual tour"})
    rental_duration = ChoiceField(list(refs.RENTAL_DURATIONS), metadata={
        "description": "rentals: long_term or temporary (seasonal)"})
    text = StrippedString(load_default=None, validate=lambda v: v is None or len(v) <= 100, metadata={
        "description": "free text the listing must mention (a street, 'terraza', a reference)"})
    sort = ChoiceField(list(refs.SORTS), load_default="relevance", metadata={
        "description": "relevance (default), newest, oldest, price_asc, price_desc, size_asc, size_desc, "
                       "price_per_m2_asc, price_per_m2_desc"})

    @validates_schema
    def _ranges(self, data, **kwargs):
        for low, high in (("min_price", "max_price"), ("min_rooms", "max_rooms"), ("min_bathrooms", "max_bathrooms"),
                          ("min_surface", "max_surface")):
            if data.get(low) and data.get(high) and data[low] > data[high]:
                raise ValidationError(f"{low} must not exceed {high}.", high)


class LocationsSearchSchema(BaseSchema):
    query = QueryField(max_length=80, metadata={
        "description": "place name, street, urbanisation or zip code prefix (Madrid, Chamberí, Calle Serrano, 28001); "
                       "the site's own typeahead"})
    language = _language()


class PropertiesSearchSchema(_FilterMixin, BaseSchema):
    location = LocationField(metadata={
        "description": "place name, a location id from locations/search (724,14,28,173,0,28079,0,0,0), a street / "
                       "urbanisation area slug from locations/search (calle-serrano-madrid-capital) or any "
                       "fotocasa.es search link"})
    transaction = _transaction()
    property_type = _property_type()
    page = PageField(max_page=refs.HTML_MAX_PAGES, metadata={"description": "page number (default 1)"})
    per_page = PageSizeField(default=refs.ITEMS_PER_PAGE, max_size=refs.MAX_PAGE_SIZE, metadata={
        "description": f"results per page, 1-{refs.MAX_PAGE_SIZE} (default {refs.ITEMS_PER_PAGE}; a search link or "
                       f"an area slug always serves {refs.ITEMS_PER_PAGE})"})
    language = _language()


class PropertyDetailsSchema(BaseSchema):
    property = PropertyRefField(metadata={
        "description": "fotocasa listing id (184433815) or any listing link (…/<id>/d)"})
    language = _language()


class PromotionDetailsSchema(BaseSchema):
    promotion = PromotionRefField(metadata={
        "description": "new-development id (20678485) or its fotocasa.es link (…/comprar/obra-nueva/<location>/<id>)"})
    language = _language()


class AgencyDetailsSchema(BaseSchema):
    agency = AgencyRefField(metadata={
        "description": "agency slug (fortuny-madrid-real-estate), numeric client id (9202757120653), a /pro/<slug>/ "
                       "link or an /inmobiliarias/<name>-<id> link"})
    language = _language()


class AgencyListingsSchema(_FilterMixin, BaseSchema):
    agency = AgencyRefField(metadata={
        "description": "agency slug (fortuny-madrid-real-estate), numeric client id (9202757120653), a /pro/<slug>/ "
                       "link or an /inmobiliarias/<name>-<id> link"})
    transaction = _transaction()
    property_type = _property_type()
    location = StrippedString(load_default=None, metadata={
        "description": "optional location id from locations/search to narrow the agency's listings "
                       "(default: all of Spain)"})
    page = PageField(max_page=refs.HTML_MAX_PAGES, metadata={"description": "page number (default 1)"})
    per_page = PageSizeField(default=refs.ITEMS_PER_PAGE, max_size=refs.MAX_PAGE_SIZE, metadata={
        "description": f"results per page, 1-{refs.MAX_PAGE_SIZE} (default {refs.ITEMS_PER_PAGE})"})
    language = _language()

    @validates_schema
    def _location_shape(self, data, **kwargs):
        location = data.get("location")
        if location:
            try:
                kind, _value = refs.classify_location(location)
            except ValueError as e:
                raise ValidationError(str(e), "location")
            if kind != "combined":
                raise ValidationError("Must be a location id from locations/search (724,14,28,173,0,28079,0,0,0).",
                                      "location")


class AgenciesSearchSchema(BaseSchema):
    location = DirectoryLocationField(metadata={
        "description": "place name (Madrid, Barrio de Salamanca), a location id from locations/search, a directory "
                       "slug (madrid-capital, madrid-capital/barrio-de-salamanca) or a fotocasa.es agencies-directory "
                       "link"})
    page = PageField(max_page=500, metadata={"description": f"page of {refs.DIRECTORY_ITEMS_PER_PAGE} agencies"})


class PriceIndexSchema(BaseSchema):
    location = PriceIndexLocationField(metadata={
        "description": "municipality or district: a place name (Madrid, Barrio de Salamanca), a location id from "
                       "locations/search, a slug (madrid-capital, madrid-capital/barrio-de-salamanca) or a "
                       "fotocasa.es price-index link"})
