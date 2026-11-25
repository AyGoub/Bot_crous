"""arpej.fr — résidences étudiantes et jeunes actifs ARPEJ.

La page « Nos résidences » indique pour chacune « complet » ou « N disponible(s) ». Une
résidence est donc considérée comme une annonce tant qu'elle a au moins une place libre :
on est notifié quand elle passe de complet à disponible.
"""

import logging
import re
import time

from bs4 import BeautifulSoup

from . import find_postal_code, http_get, parse_number

NAME = "arpej"
LABEL = "ARPEJ"

INDEX_URL = "https://www.arpej.fr/fr/nos-residences/"
REGION = "Île-de-France"
AVAILABLE_RE = re.compile(r"(\d+)\s+disponible", re.IGNORECASE)
PRICE_RE = re.compile(r"dès\s+([\d\s.,]+)\s*€", re.IGNORECASE)
SURFACE_RE = re.compile(r"Surface de\s+([\d.,]+)\s*à\s*([\d.,]+)\s*m²", re.IGNORECASE)
# « Logements clés en main pour : Étudiants » suivi de « Cette résidence... » ou de l'adresse.
AUDIENCE_RE = re.compile(r"Logements clés en main pour\s*:\s*(.+?)(?=\s+(?:Cette résidence|\d))", re.IGNORECASE)

logger = logging.getLogger("logement_watch.arpej")


def parse_index(html: str) -> list[dict]:
    """Résidences d'Île-de-France ayant au moins une place disponible."""
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for region in soup.find_all(class_="residences-index__region"):
        title = region.find(class_="residences-index__region-title")
        if not title or REGION.lower() not in title.get_text(" ", strip=True).lower():
            continue
        for item in region.find_all("li", class_="residences-index__item"):
            link = item.find("a", href=True)
            if not link:
                continue
            meta = " ".join(m.get_text(" ", strip=True) for m in item.find_all(class_="residences-index__meta"))
            available = AVAILABLE_RE.search(meta)
            if not available:
                continue  # « complet »
            city_el = item.find_parent("li", class_="residences-index__city")
            city_title = city_el.find(["h3", "h4", "span", "p"]) if city_el else None
            price = PRICE_RE.search(meta)
            results.append({
                "url": link["href"],
                "id": link["href"].rstrip("/").split("/")[-1],
                "name": link.get_text(" ", strip=True),
                "city": city_title.get_text(" ", strip=True) if city_title else None,
                "rent": parse_number(price.group(1)) if price else None,
                "available": int(available.group(1)),
            })
    return results


def enrich(residence: dict) -> dict:
    """Ajoute code postal, surfaces et public visé depuis la page de la résidence."""
    soup = BeautifulSoup(http_get(residence["url"]).text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    surface = SURFACE_RE.search(text)
    audience = AUDIENCE_RE.search(text)
    title = soup.find("h1")
    img = soup.find("meta", property="og:image")
    count = residence["available"]
    kind = f"Résidence pour {audience.group(1).strip()}" if audience else "Résidence"
    if "accepte la colocation" in text.lower():
        kind += " (studios + quelques colocations)"
    return {
        "id": residence["id"],
        "title": f"{title.get_text(' ', strip=True) if title else residence['name']} — "
                 f"{count} logement{'s' if count > 1 else ''} disponible{'s' if count > 1 else ''}",
        "url": residence["url"],
        "rent": residence["rent"],
        "rent_text": f"dès {residence['rent']:g} € CC" if residence["rent"] else None,
        # On garde la plus petite surface proposée.
        "surface": parse_number(surface.group(1)) if surface else None,
        "city": residence["city"],
        "postal_code": find_postal_code(text),
        "kind": kind,
        "image": img.get("content") if img else None,
        "description": "",
        "solo": True,
        "warnings": [],
    }


def fetch(max_rent: float) -> list[dict]:
    residences = [r for r in parse_index(http_get(INDEX_URL).text) if r["rent"] is None or r["rent"] <= max_rent]
    listings = []
    for residence in residences:
        time.sleep(0.5)
        listings.append(enrich(residence))
    logger.info("ARPEJ : %d résidence(s) d'Île-de-France avec des places disponibles.", len(listings))
    return listings
