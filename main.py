"""Veille des studios / T1 à Paris + petite couronne (CROUS, Bien'ici) avec notification Discord."""

import json
import logging
import os
import random
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone

import requests

from sources import SourceUnavailable, bienici, crous

# --- Critères de recherche (modifiables via variables d'environnement) ----------------------
MAX_RENT = float((os.environ.get("MAX_RENT") or "800"))  # loyer max charges comprises
TARGET_RENT = float((os.environ.get("TARGET_RENT") or "700"))  # en dessous : signalé "bon prix"
# 9 m² = surface minimale d'un logement décent (décret 2002-120) : en dessous, c'est illégal.
MIN_SURFACE = float((os.environ.get("MIN_SURFACE") or "9"))
DEPARTMENTS = tuple(d.strip() for d in (os.environ.get("DEPARTMENTS") or "75,92,93,94").split(","))

STATE_FILE = os.environ.get("STATE_FILE", "seen_listings.json")
REQUEST_TIMEOUT = 15
MAX_INITIAL_SUMMARY = 15

# Annonces de logement partagé : on cherche uniquement à vivre seul.
SHARED_KEYWORDS = (
    "colocation", "coloc ", "colocataire", "coliving", "co-living", "chez l'habitant",
    "sous-location", "sous location", "logement partage", "appartement partage",
)
# Indices fréquents d'arnaque (faux propriétaire, paiement avant visite...).
SCAM_KEYWORDS = (
    "western union", "mandat cash", "transcash", "moneygram", "coupon pcs", "a l'etranger",
    "je suis actuellement", "remise des cles par", "envoyer les cles", "airbnb", "payer avant",
)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
# Loyer au m² sous lequel une annonce à Paris + petite couronne est suspecte.
SUSPICIOUS_PRICE_PER_M2 = 15

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("logement_watch")


def normalize(text: str | None) -> str:
    """Minuscules sans accents, pour comparer des mots-clés."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return text.lower().replace("’", "'")


def keep_listing(listing: dict) -> tuple[bool, str]:
    """Filtre commun à toutes les sources. Renvoie (garder, raison du rejet)."""
    if not listing.get("solo"):
        return False, "pas de logement individuel"
    if listing["rent"] is not None and listing["rent"] > MAX_RENT:
        return False, f"loyer {listing['rent']:g} € > {MAX_RENT:g} €"
    if listing["surface"] is not None and listing["surface"] < MIN_SURFACE:
        return False, f"surface {listing['surface']:g} m² < {MIN_SURFACE:g} m²"
    postal_code = listing.get("postal_code")
    if postal_code and not postal_code.startswith(DEPARTMENTS):
        return False, f"hors zone ({postal_code})"
    title = normalize(listing["title"])
    # Une "chambre" seule est en général dans un logement partagé, mais une chambre de
    # bonne / de service est un petit logement indépendant : on la garde.
    if "chambre" in title and "de bonne" not in title and "de service" not in title:
        return False, "chambre (logement partagé probable)"
    for keyword in SHARED_KEYWORDS:
        if keyword in title:
            return False, f"logement partagé ({keyword.strip()})"
    return True, ""


def scam_warnings(listing: dict) -> list[str]:
    warnings = []
    text = normalize(f"{listing['title']} {listing.get('description', '')}")
    found = [k for k in SCAM_KEYWORDS if k in text]
    if found:
        warnings.append(f"mots suspects : {', '.join(found)}")
    if EMAIL_RE.search(listing["title"]):
        warnings.append("adresse e-mail dans le titre")
    rent, surface = listing["rent"], listing["surface"]
    if rent and surface and surface >= 10 and rent / surface < SUSPICIOUS_PRICE_PER_M2:
        warnings.append(f"prix anormalement bas ({rent / surface:.0f} €/m²)")
    if "code civil" in text or "residence secondaire" in text:
        warnings.append("bail code civil / résidence secondaire (moins protecteur)")
    return warnings


# --- État ------------------------------------------------------------------------------------
def load_state(path: str) -> dict:
    state = {"listings": {}, "initialized_sources": []}
    if not os.path.exists(path):
        return state
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Impossible de lire %s (%s), on repart d'un état vide.", path, e)
        return state
    if "listings" in data:
        state.update(data)
    else:
        # Ancien format (CROUS seul, {id: meta}).
        state["listings"] = {f"crous:{k}": v for k, v in data.items()}
    return state


def save_state(path: str, state: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


# --- Discord ---------------------------------------------------------------------------------
def post_discord(webhook_url: str, payload: dict) -> None:
    for _ in range(3):
        resp = requests.post(webhook_url, json=payload, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 429:
            time.sleep(float(resp.json().get("retry_after", 2)))
            continue
        resp.raise_for_status()
        return
    resp.raise_for_status()


def listing_embed(listing: dict, source_label: str) -> dict:
    rent = listing["rent"]
    good_price = rent is not None and rent <= TARGET_RENT
    if listing["warnings"]:
        color = 0xE67E22  # orange
    elif good_price:
        color = 0x2ECC71  # vert
    else:
        color = 0x3498DB  # bleu

    title = listing["title"] or "Nouveau logement"
    if good_price:
        title = f"🔥 {title}"
    embed = {
        "title": title[:256],
        "url": listing["url"],
        "color": color,
        "footer": {"text": source_label},
        "fields": [],
    }
    location = " ".join(x for x in (listing.get("postal_code"), listing.get("city")) if x)
    if location:
        embed["fields"].append({"name": "Lieu", "value": location[:1024], "inline": False})
    if listing.get("rent_text"):
        embed["fields"].append({"name": "Loyer", "value": listing["rent_text"], "inline": True})
    if listing["surface"]:
        value = f"{listing['surface']:g} m²"
        if rent:
            value += f" ({rent / listing['surface']:.0f} €/m²)"
        embed["fields"].append({"name": "Surface", "value": value, "inline": True})
    if listing.get("kind"):
        embed["fields"].append({"name": "Type", "value": listing["kind"][:1024], "inline": True})
    if listing.get("publisher"):
        embed["fields"].append({"name": "Publié par", "value": str(listing["publisher"])[:1024], "inline": True})
    if listing["warnings"]:
        embed["fields"].append({
            "name": "⚠️ Prudence",
            "value": "\n".join(f"• {w}" for w in listing["warnings"])[:1024]
            + "\nNe paie jamais rien avant d'avoir visité et signé le bail.",
            "inline": False,
        })
    if listing.get("image"):
        embed["thumbnail"] = {"url": listing["image"]}
    return embed


def summary_embed(source_label: str, listings: list[dict]) -> dict:
    """Premier passage sur une source : un seul message récapitulatif au lieu de centaines."""
    best = sorted(listings, key=lambda l: (bool(l["warnings"]), l["rent"] or 0))[:MAX_INITIAL_SUMMARY]
    lines = []
    for l in best:
        parts = [l["rent_text"] or "?"]
        if l["surface"]:
            parts.append(f"{l['surface']:g} m²")
        parts.append(" ".join(x for x in (l.get("postal_code"), l.get("city")) if x))
        lines.append(f"[{' · '.join(parts)}]({l['url']})")
    return {
        "title": f"{source_label} : {len(listings)} annonce(s) déjà en ligne",
        "description": (
            "Première vérification de cette source : je ne t'envoie que les "
            f"{len(best)} moins chères, puis uniquement les nouvelles.\n\n" + "\n".join(lines)
        )[:4096],
        "color": 0x95A5A6,
    }


# --- Programme principal ---------------------------------------------------------------------
SOURCES = [
    (crous, lambda: crous.fetch()),
    (bienici, lambda: bienici.fetch(MAX_RENT)),
]


def main() -> int:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        logger.error("La variable d'environnement DISCORD_WEBHOOK_URL n'est pas définie.")
        return 1

    state = load_state(STATE_FILE)
    previous = state["listings"]
    next_listings: dict[str, dict] = {}
    initialized = set(state["initialized_sources"])

    for module, fetch in SOURCES:
        prefix = f"{module.NAME}:"
        time.sleep(random.uniform(1, 3))
        try:
            raw = fetch()
        except SourceUnavailable as e:
            logger.warning("%s indisponible (%s) : on garde son état précédent.", module.LABEL, e)
            next_listings.update({k: v for k, v in previous.items() if k.startswith(prefix)})
            continue
        except Exception:
            logger.exception("Erreur inattendue sur %s : on garde son état précédent.", module.LABEL)
            next_listings.update({k: v for k, v in previous.items() if k.startswith(prefix)})
            continue

        kept = []
        for listing in raw:
            ok, reason = keep_listing(listing)
            if ok:
                listing["warnings"] = listing["warnings"] + scam_warnings(listing)
                kept.append(listing)
            else:
                logger.debug("Ignoré %s%s : %s", prefix, listing["id"], reason)
        logger.info("%s : %d annonce(s) correspondent aux critères.", module.LABEL, len(kept))

        current_ids = {prefix + l["id"] for l in kept}
        # On ne garde que les annonces encore en ligne : une annonce retirée puis remise en
        # ligne plus tard (même ID) doit pouvoir renotifier.
        next_listings.update({k: v for k, v in previous.items() if k in current_ids})
        new = [l for l in kept if prefix + l["id"] not in previous]

        def remember(listing: dict) -> None:
            next_listings[prefix + listing["id"]] = {
                "title": listing["title"],
                "url": listing["url"],
                "rent": listing["rent"],
                "first_seen": datetime.now(timezone.utc).isoformat(),
            }

        if module.NAME not in initialized:
            try:
                if new:
                    post_discord(webhook_url, {"embeds": [summary_embed(module.LABEL, new)]})
            except requests.RequestException as e:
                logger.error("Échec de l'envoi Discord du récapitulatif %s : %s", module.LABEL, e)
                continue
            for listing in new:
                remember(listing)
            initialized.add(module.NAME)
            continue

        # Les moins chères d'abord.
        for listing in sorted(new, key=lambda l: l["rent"] or 0):
            try:
                post_discord(webhook_url, {"embeds": [listing_embed(listing, module.LABEL)]})
            except requests.RequestException as e:
                logger.error("Échec de l'envoi Discord pour %s%s : %s", prefix, listing["id"], e)
                continue
            remember(listing)
            time.sleep(1)
        logger.info("%s : %d nouvelle(s) annonce(s) notifiée(s).", module.LABEL, len(new))

    new_state = {"listings": next_listings, "initialized_sources": sorted(initialized)}
    if new_state != state:
        save_state(STATE_FILE, new_state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
