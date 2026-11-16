"""Sources d'annonces. Chaque module expose `NAME`, `LABEL` et `fetch() -> list[dict]`.

Chaque annonce renvoyée est un dict normalisé :
    id, title, url, rent (float | None, charges comprises), rent_text, surface (float | None),
    city, postal_code, kind, image, description, warnings (list[str])
`fetch()` lève `SourceUnavailable` si le site est indisponible ou limite le trafic : on garde
alors l'état précédent de cette source au lieu de considérer ses annonces comme disparues.
"""

import re

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 20

POSTAL_CODE_RE = re.compile(r"\b(\d{5})\b")
NUMBER_RE = re.compile(r"\d+(?:[\s  ]\d{3})*(?:[.,]\d+)?")


class SourceUnavailable(Exception):
    pass


def http_get(url: str, **kwargs) -> requests.Response:
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"}
    headers.update(kwargs.pop("headers", {}))
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, **kwargs)
    except requests.RequestException as e:
        raise SourceUnavailable(f"connexion impossible : {e}") from e
    if response.status_code in (403, 429, 503):
        raise SourceUnavailable(f"HTTP {response.status_code} (limitation de trafic probable)")
    if response.status_code != 200:
        raise SourceUnavailable(f"HTTP {response.status_code} inattendu")
    return response


def parse_number(text: str | None) -> float | None:
    """Premier nombre d'un texte français : '1 234,56 €' -> 1234.56."""
    if not text:
        return None
    match = NUMBER_RE.search(text)
    if not match:
        return None
    raw = re.sub(r"[\s  ]", "", match.group(0)).replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def find_postal_code(text: str | None) -> str | None:
    if not text:
        return None
    match = POSTAL_CODE_RE.search(text)
    return match.group(1) if match else None
