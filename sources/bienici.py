"""bienici.com — agrège les annonces de la plupart des agences (et quelques particuliers).

On utilise l'API JSON que le site appelle lui-même pour afficher ses résultats.
"""

import json
import logging

from . import http_get

NAME = "bienici"
LABEL = "Bien'ici"

API_URL = "https://www.bienici.com/realEstateAds.json"
# ID de zone Bien'ici = -ID de relation OpenStreetMap :
# Paris (7444), Hauts-de-Seine (7449), Seine-Saint-Denis (7389), Val-de-Marne (7458).
ZONE_IDS = ["-7444", "-7449", "-7389", "-7458"]
PAGE_SIZE = 100
MAX_PAGES = 10

ACCOUNT_TYPES = {"agency": "Agence", "network": "Réseau d'agences", "mandatary": "Mandataire", "particulier": "Particulier", "owner": "Particulier"}

logger = logging.getLogger("logement_watch.bienici")


def build_filters(max_rent: float, page: int) -> dict:
    return {
        "size": PAGE_SIZE,
        "from": (page - 1) * PAGE_SIZE,
        "page": page,
        "filterType": "rent",
        "propertyType": ["flat", "house"],
        "maxPrice": int(max_rent),
        "maxRooms": 1,
        "sortBy": "publicationDate",
        "sortOrder": "desc",
        "onTheMarket": [True],
        "zoneIdsByTypes": {"zoneIds": ZONE_IDS},
    }


def to_listing(ad: dict) -> dict:
    photos = ad.get("photos") or []
    title = (ad.get("title") or "").strip()
    surface = ad.get("surfaceArea")
    if not title:
        title = f"{'Studio' if ad.get('isStudio') else 'T1'}{f' {surface:g} m²' if surface else ''} — {ad.get('city', '')}"
    price = ad.get("price")
    return {
        "id": ad["id"],
        "title": title,
        "url": f"https://www.bienici.com/annonce/{ad['id']}",
        # Sur Bien'ici, `price` d'une location est le loyer charges comprises.
        "rent": float(price) if price is not None else None,
        "rent_text": f"{price:g} € CC" if price is not None else None,
        "surface": float(surface) if surface else None,
        "city": ad.get("city"),
        "postal_code": ad.get("postalCode"),
        "kind": "Studio" if ad.get("isStudio") else f"{ad.get('roomsQuantity') or 1} pièce",
        "image": photos[0].get("url") if photos else None,
        "description": ad.get("description") or "",
        "solo": True,
        "publisher": ad.get("accountDisplayName") or ACCOUNT_TYPES.get(ad.get("accountType"), ad.get("accountType")),
        "warnings": [],
    }


def fetch(max_rent: float) -> list[dict]:
    listings: dict[str, dict] = {}
    for page in range(1, MAX_PAGES + 1):
        response = http_get(API_URL, params={"filters": json.dumps(build_filters(max_rent, page))})
        data = response.json()
        for ad in data.get("realEstateAds", []):
            listings[ad["id"]] = to_listing(ad)
        if page * PAGE_SIZE >= data.get("total", 0):
            break
    logger.info("Bien'ici : %d annonce(s) studio/T1 ≤ %g €.", len(listings), max_rent)
    return list(listings.values())
