"""Veille des nouveaux logements CROUS (trouverunlogement.lescrous.fr) avec notification Discord."""

import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

DEFAULT_SEARCH_URL = (
    "https://trouverunlogement.lescrous.fr/tools/47/search"
    "?bounds=-0.413777_49.2162655_-0.3307282_49.1530145&locationName=Caen+%2814000%29"
)
SEARCH_URL = os.environ.get("CROUS_SEARCH_URL") or DEFAULT_SEARCH_URL

STATE_FILE = os.environ.get("STATE_FILE", "seen_listings.json")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 15
MIN_DELAY_SECONDS = 2
MAX_DELAY_SECONDS = 5

# Message affiché par le site CROUS quand il limite l'accès (page "Vous êtes trop nombreux !").
RATE_LIMIT_MARKER = "trop nombreux"

SURFACE_RE = re.compile(r"\d+(?:[.,]\d+)?\s*m²", re.IGNORECASE)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("crous_watch")


def fetch_search_page(url: str) -> requests.Response:
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"}
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    # Le site ne déclare pas de charset dans Content-Type ; requests retombe alors
    # sur ISO-8859-1 par défaut alors que la page est en UTF-8, ce qui corrompt
    # les caractères accentués (adresses, loyers en €).
    response.encoding = "utf-8"
    return response


def is_rate_limited(html_text: str) -> bool:
    return RATE_LIMIT_MARKER in html_text.lower()


def extract_listing_id(href: str) -> str | None:
    path = urlparse(href).path.rstrip("/")
    segment = path.split("/")[-1] if path else ""
    return segment or None


def parse_card(card: BeautifulSoup, base_url: str) -> dict | None:
    title_el = card.find("h3", class_="fr-card__title")
    link_el = title_el.find("a") if title_el else None
    href = link_el.get("href") if link_el else None
    if not href:
        return None

    listing_id = extract_listing_id(href)
    if listing_id is None:
        return None

    address_el = card.find("p", class_="fr-card__desc")
    # Les détails sont rendus en <li> (avec une icône SVG en plus du texte), mais on
    # matche sur la classe seule pour rester robuste si le site change de balise.
    detail_els = card.find_all(class_="fr-card__detail")
    details = [d.get_text(strip=True) for d in detail_els]

    # Les paragraphes de détail ne sont pas typés : on repère la surface via
    # regex et on prend le premier détail restant comme "type" de logement.
    surface = None
    listing_type = None
    for detail in details:
        match = SURFACE_RE.search(detail)
        if match and surface is None:
            surface = match.group(0)
        elif listing_type is None:
            listing_type = detail

    price_el = card.find("p", class_="fr-badge")

    return {
        "id": listing_id,
        "title": link_el.get_text(strip=True),
        "address": address_el.get_text(strip=True) if address_el else None,
        "rent": price_el.get_text(strip=True) if price_el else None,
        "surface": surface,
        "type": listing_type,
        "details": details,
        "url": urljoin(base_url, href),
    }


def parse_listings(html_text: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html_text, "html.parser")
    cards = soup.find_all("div", class_="fr-card")
    listings = []
    for card in cards:
        listing = parse_card(card, base_url)
        if listing:
            listings.append(listing)
    return listings


def load_seen(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Impossible de lire %s (%s), on repart d'un état vide.", path, e)
        return {}


def save_seen(path: str, seen: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def notify_discord(webhook_url: str, listing: dict) -> None:
    embed = {
        "title": listing["title"] or "Nouveau logement CROUS",
        "url": listing["url"],
        "color": 0x0F8000,
        "fields": [],
    }
    if listing["address"]:
        embed["fields"].append({"name": "Adresse", "value": listing["address"], "inline": False})
    if listing["rent"]:
        embed["fields"].append({"name": "Loyer", "value": listing["rent"], "inline": True})
    if listing["surface"]:
        embed["fields"].append({"name": "Surface", "value": listing["surface"], "inline": True})
    if listing["type"]:
        embed["fields"].append({"name": "Type", "value": listing["type"], "inline": True})

    resp = requests.post(webhook_url, json={"embeds": [embed]}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()


def main() -> int:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        logger.error("La variable d'environnement DISCORD_WEBHOOK_URL n'est pas définie.")
        return 1

    time.sleep(random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS))

    try:
        response = fetch_search_page(SEARCH_URL)
    except requests.RequestException as e:
        logger.error("Échec de la connexion au site CROUS : %s", e)
        return 0

    if response.status_code in (429, 503):
        logger.warning("Le site CROUS répond %s (limitation de trafic probable), on abandonne ce run.", response.status_code)
        return 0

    if response.status_code != 200:
        logger.error("Code de statut inattendu du site CROUS : %s", response.status_code)
        return 0

    if is_rate_limited(response.text):
        logger.warning("Page de limitation de trafic détectée sur le site CROUS, on abandonne ce run.")
        return 0

    try:
        listings = parse_listings(response.text, response.url)
    except Exception as e:
        logger.error("Échec du parsing de la page de résultats : %s", e)
        return 0

    logger.info("%d logement(s) trouvé(s) sur la page.", len(listings))

    seen = load_seen(STATE_FILE)
    new_listings = [l for l in listings if l["id"] not in seen]

    if not new_listings:
        logger.info("Aucun nouveau logement.")
        return 0

    logger.info("%d nouveau(x) logement(s) détecté(s).", len(new_listings))

    for listing in new_listings:
        try:
            notify_discord(webhook_url, listing)
        except requests.RequestException as e:
            logger.error("Échec de l'envoi Discord pour %s : %s", listing["id"], e)
            continue

        seen[listing["id"]] = {
            "title": listing["title"],
            "url": listing["url"],
            "first_seen": datetime.now(timezone.utc).isoformat(),
        }
        time.sleep(1)

    save_seen(STATE_FILE, seen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
