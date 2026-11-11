# 🏠 Fotocasa Scraper

Fotocasa Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Fotocasa property data for free.

## ✨ What Can I Get?

- 🏡 **Full details on 900K+ Spanish listings** — price & price drops, m², rooms, floor, energy rating, amenities, GPS, photos & agent phone
- 🔍 **Search 488K+ homes for sale your way** — any city, district, street or zip code, 20+ filters, plus rentals, rooms & business transfers
- 📈 **6+ years of housing prices** — median sale & rent €/m², 1/3/6/12-month change and market temperature for any city or district
- 🏗️ **11K+ new builds & every agency** — unit-by-unit prices, sizes & delivery dates, plus agency phones, emails & websites

## 🎥 Example: A Full Fotocasa Listing

```json
{
  "id": "159718048",
  "title": "Casa o chalet en venta en Lomas de Marbella Club, Marbella",
  "link": "https://www.fotocasa.es/es/comprar/vivienda/marbella/aire-acondicionado-calefaccion-parking-jardin-terraza-zona-comunitaria-patio-piscina-internet-no-amueblado/159718048/d",
  "transaction": "buy",
  "property_subtype": "house",
  "price": { "amount": 5950000, "currency": "EUR", "period": null, "previous_amount": null, "drop": null },
  "rooms": 5,
  "bathrooms": 6,
  "surface_m2": 615,
  "orientation": "south",
  "condition": "almost_new",
  "energy_certificate": { "status": "valid", "rating": "G", "emissions_rating": "G" },
  "amenities": ["garden", "terrace", "swimming_pool", "jacuzzi", "gym", "sauna"],
  "description": "Ubicado en Lomas de Marbella Club, una prestigiosa urbanización en la Milla de Oro...",
  "address": {
    "neighborhood": "Lomas de Marbella Club",
    "district": "Milla de Oro",
    "municipality": "Marbella",
    "province": "Málaga",
    "zip_code": "29602",
    "coordinates": { "latitude": 36.5078988216048, "longitude": -4.931613603138742, "is_exact": false }
  },
  "photos": [
    { "link": "https://static.fotocasa.es/images/ads/ad543bc5-1fd7-49c3-bef4-27d169e49f6f?rule=original", "position": 1 }
  ],
  "photos_count": 44,
  "advertiser": { "name": "NEWBERY REAL ESTATE", "type": "professional", "phone": "+34951089075", "reference": "N904", "link": "https://www.fotocasa.es/es/pro/newbery-real-estate/" },
  "published_at": "2021-04-16T06:22:06"
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Fotocasa Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/fotocasa-scraper
cd fotocasa-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/properties/details?property=159718048"
```

```json
{
  "id": "159718048",
  "title": "Casa o chalet en venta en Lomas de Marbella Club, Marbella",
  "transaction": "buy",
  "property_subtype": "house",
  "price": { "amount": 5950000, "currency": "EUR", "period": null, "previous_amount": null, "drop": null },
  "rooms": 5,
  "bathrooms": 6,
  "surface_m2": 615,
  "orientation": "south",
  "condition": "almost_new",
  "energy_certificate": { "status": "valid", "rating": "G", "emissions_rating": "G" },
  "amenities": ["air_conditioning", "garden", "terrace", "swimming_pool", "jacuzzi", "gym", "sauna"],
  "address": { "neighborhood": "Lomas de Marbella Club", "district": "Milla de Oro", "municipality": "Marbella" },
  "photos_count": 44,
  "advertiser": { "name": "NEWBERY REAL ESTATE", "type": "professional", "phone": "+34951089075" }
}
```

All 8 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

8 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Property Details | `/properties/details` | Everything about one listing: price, specs, amenities, GPS, photos, agent |
| Search Properties | `/properties/search` | Up to 400 listings per page, 20+ filters, 9 sort orders |
| Search Locations | `/locations/search` | Location IDs for any Spanish city, district, street or zip |
| New Development Details | `/promotions/details` | Every new-build unit with price, size and delivery date |
| Housing Price Index | `/prices/index` | Sale and rent €/m², trends and 6+ years of monthly history |
| Search Agencies | `/agencies/search` | Every agency of a city or district, with listing counts |
| Agency Details | `/agencies/details` | Address, phones, email, website, listing counts and latest listings |
| Agency Listings | `/agencies/listings` | Every listing of one agency, filtered your way |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-fotocasa-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-fotocasa-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-fotocasa-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/properties/details",
    params={"property": "159718048"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Fotocasa Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://www.omkar.cloud/l/fotocasa-scraper-github-whatsapp)

[![Ask Us by Email about Fotocasa Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Fotocasa%20Scraper%20API&body=I%20need%20help%20using%20the%20Fotocasa%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Zap Imoveis Scraper**](https://github.com/omkarcloud/zap-imoveis-scraper) — ZAP Imóveis Brazil listings: prices, condo fees, IPTU, photos & agencies

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/fotocasa-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/fotocasa-scraper)
