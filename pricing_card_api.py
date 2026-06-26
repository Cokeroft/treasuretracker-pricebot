"""
Thin client for the TreasureTracker card API.
"""

import logging
from dataclasses import dataclass

import aiohttp

import config

logger = logging.getLogger(__name__)


class CardNotFoundError(Exception):
    """Raised when the API returns a 404 for a given card id."""


class CardApiError(Exception):
    """Raised for any other non-success response from the card API."""


@dataclass
class CardVariant:
    variant_id: str
    label: str
    finish: str
    tcgplayer_url: str | None
    tcgplayer_image_url: str | None


@dataclass
class Card:
    id: str
    name: str
    set: str
    rarity: str
    variants: list[CardVariant]


def _parse_card(payload: dict) -> Card:
    variants = []
    for v in payload.get("variants", []):
        variants.append(
            CardVariant(
                variant_id=v.get("variant_id", ""),
                label=v.get("label", "Unknown Variant"),
                finish=v.get("finish", ""),
                tcgplayer_url=v.get("tcgplayer_url"),
                tcgplayer_image_url=v.get("tcgplayer_image_url"),
            )
        )
    return Card(
        id=payload["id"],
        name=payload.get("name", payload["id"]),
        set=payload.get("set", ""),
        rarity=payload.get("rarity", ""),
        variants=variants,
    )


async def fetch_card(card_id: str) -> Card:
    """
    Fetch a card (with all its variants) from the TreasureTracker API.

    Raises:
        CardNotFoundError: if the card_id doesn't exist (404).
        CardApiError: for any other failure (network, 5xx, malformed payload).
    """
    url = f"{config.CARD_API_BASE_URL}/cards/{card_id}"
    logger.info("Fetching card data: %s", url)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 404:
                    raise CardNotFoundError(f"Card '{card_id}' not found")
                if resp.status != 200:
                    body = await resp.text()
                    raise CardApiError(
                        f"Card API returned {resp.status} for '{card_id}': {body[:200]}"
                    )
                payload = await resp.json()
    except aiohttp.ClientError as e:
        raise CardApiError(f"Network error fetching card '{card_id}': {e}") from e

    try:
        return _parse_card(payload)
    except (KeyError, TypeError) as e:
        raise CardApiError(f"Malformed card payload for '{card_id}': {e}") from e
