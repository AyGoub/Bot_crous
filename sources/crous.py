"""trouverunlogement.lescrous.fr — résidences CROUS."""

import logging
import os
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from . import SourceUnavailable, find_postal_code, http_get, parse_number

NAME = "crous"
LABEL = "CROUS"

# `48` = année universitaire 2026-2027 (l'ID change chaque année : 47 renvoie désormais 404).
# Les bounds couvrent Paris + petite couronne (lon_min, lat_max, lon_max, lat_min) ; le
# rectangle déborde un peu sur le 78/91/95, ce que le filtre par code postal corrige.
DEFAULT_SEARCH_URL = (
    "https://trouverunlogement.lescrous.fr/tools/48/search"
    "?bounds=2.15_48.96_2.62_48.72&locationName=Paris+et+petite+couronne"
)
MAX_PAGES = 10

# Message affiché par le site quand il limite l'accès (page "Vous êtes trop nombreux !").
RATE_LIMIT_MARKER = "trop nombreux"
SURFACE_RE = re.compile(r"\d+(?:[.,]\d+)?\s*m²", re.IGNORECASE)

logger = logging.getLogger("logement_watch.crous")


def search_url() -> str:
    return os.environ.get("CROUS_SEARCH_URL") or DEFAULT_SEARCH_URL


def extract_listing_id(href: str) -> str | None:
    path = urlparse(href).path.rstrip("/")
    segment = path.split("/")[-1] if path else ""
    return segment or None


def parse_card(card, base_url: str) -> dict | None:
    title_el = card.find("h3", class_="fr-card__title")
    link_el = title_el.find("a") if title_el else None
    href = link_el.get("href") if link_el else None
    if not href:
        return None
    listing_id = extract_listing_id(href)
    if listing_id is None:
        return None

    address_el = card.find("p", class_="fr-card__desc")
    address = address_el.get_text(strip=True) if address_el else None
    details = [d.get_text(strip=True) for d in card.find_all(class_="fr-card__detail")]

    # Les détails ne sont pas typés : surface repérée par regex, puis le premier détail
    # restant est le mode d'occupation ("Individuel", "Individuel, Colocation, Couple"...).
    surface_text = None
    kind = None
    for detail in details:
        match = SURFACE_RE.search(detail)
        if match and surface_text is None:
            surface_text = match.group(0)
        elif kind is None:
            kind = detail

    price_el = card.find("p", class_="fr-badge")
    rent_text = price_el.get_text(strip=True) if price_el else None
    img_el = card.find("img")

    return {
        "id": listing_id,
        "title": link_el.get_text(strip=True),
        "url": urljoin(base_url, href),
        # "de 323,31 à 646,61 €" -> on retient le loyer le plus bas proposé.
        "rent": parse_number(rent_text),
        "rent_text": rent_text,
        "surface": parse_number(surface_text),
        "city": address,
        "postal_code": find_postal_code(address),
        "kind": kind,
        "image": urljoin(base_url, img_el["src"]) if img_el and img_el.get("src") else None,
        "description": " ".join(details),
        # Les résidences CROUS sont réservées aux logements meublés individuels ou partagés :
        # on ne garde que celles qui proposent le mode "Individuel".
        "solo": kind is not None and "individuel" in kind.lower(),
        "warnings": [],
    }


def fetch() -> list[dict]:
    base = search_url()
    listings: dict[str, dict] = {}
    for page in range(1, MAX_PAGES + 1):
        url = base if page == 1 else f"{base}&page={page}"
        response = http_get(url)
        # Le site ne déclare pas de charset ; sans ça, requests décode en ISO-8859-1.
        response.encoding = "utf-8"
        if RATE_LIMIT_MARKER in response.text.lower():
            raise SourceUnavailable("page « trop nombreux » détectée")
        soup = BeautifulSoup(response.text, "html.parser")
        page_listings = [l for l in (parse_card(c, response.url) for c in soup.find_all("div", class_="fr-card")) if l]
        new = [l for l in page_listings if l["id"] not in listings]
        for l in new:
            listings[l["id"]] = l
        # Le site renvoie 24 résultats par page ; une page incomplète ou déjà vue = fin.
        if len(page_listings) < 24 or not new:
            break
    logger.info("CROUS : %d résidence(s) dans la zone.", len(listings))
    return list(listings.values())
