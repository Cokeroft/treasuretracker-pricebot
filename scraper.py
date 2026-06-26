"""
TCGPlayer listing scraper.

Selectors below were confirmed against a real captured TCGPlayer product page
(saved June 2026). TCGPlayer is a Vue SPA and occasionally changes markup --
if scraping starts silently returning zero results, re-run the inspection
script (inspect_tcgplayer.py) and update selectors here.

Key facts confirmed from the live page:
- Each listing is a <section class="listing-item"> (NOT inside a <table>)
- Default sort is Price + Shipping, ascending
- Default page size is 10 listings/page; total page count is exposed via
  the pagination control, and pages are addressable via ?page=N in the URL
- "Verified" is not a single flag -- it's 0-3 badge icons per seller:
    iconCertified -> Certified Hobby Shop
    iconGold      -> Gold Star Seller
    iconWPN       -> WPN (Wizards Play Network) Seller
  We treat "verified" as "has at least one of these badges" by default.
"""

import asyncio
import logging
import re
from dataclasses import dataclass

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

import config

logger = logging.getLogger(__name__)

LISTING_SELECTOR = ".listing-item"
SELLER_NAME_SELECTOR = ".seller-info__name"
BADGE_SELECTOR = ".filterIcon"
RATING_SELECTOR = ".seller-info__rating"
SALES_SELECTOR = ".seller-info__sales"
CONDITION_SELECTOR = ".listing-item__listing-data__info__condition"
PRICE_SELECTOR = ".listing-item__listing-data__info__price"
# Listings with custom photos (sellers often use these for off-market /
# foreign-language prints, e.g. "*Chinese* MINT Boa Hancock...") carry this
# extra block. Normal English listings never have it. We skip any listing
# that has one, since these aren't reliably the standard English print
# we're trying to price.
PHOTO_LISTING_SELECTOR = ".listing-item__listing-data__listo"

PRICE_RE = re.compile(r"[\d,]+\.\d{2}")


@dataclass
class Listing:
    seller_name: str
    condition_text: str  # e.g. "Near Mint Foil", "Lightly Played Foil"
    price: float
    is_verified: bool
    badge_names: list[str]
    rating_text: str
    sales_text: str
    has_photo_listing: bool


def _wants_near_mint_foil(condition_text: str) -> bool:
    """
    Match condition strings like "Near Mint Foil". TCGPlayer's condition
    labels combine a wear grade with a finish (Foil / non-foil), e.g.
    "Near Mint Foil", "Lightly Played Foil", "Moderately Played Foil".
    We require BOTH "near mint" and "foil" to appear.
    """
    text = condition_text.lower()
    return "near mint" in text and "foil" in text


def _parse_price(price_text: str) -> float | None:
    match = PRICE_RE.search(price_text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group().replace(",", ""))
    except ValueError:
        return None


async def _extract_listings(page: Page) -> list[Listing]:
    """Parse all .listing-item elements currently rendered on the page."""
    listings: list[Listing] = []
    items = page.locator(LISTING_SELECTOR)
    count = await items.count()

    for i in range(count):
        item = items.nth(i)

        try:
            seller_name = (await item.locator(SELLER_NAME_SELECTOR).first.inner_text()).strip()
        except Exception:
            seller_name = "Unknown Seller"

        try:
            condition_text = (
                await item.locator(CONDITION_SELECTOR).first.inner_text()
            ).strip()
        except Exception:
            condition_text = ""

        try:
            price_text = (await item.locator(PRICE_SELECTOR).first.inner_text()).strip()
        except Exception:
            price_text = ""
        price = _parse_price(price_text)
        if price is None:
            # Can't use a listing we can't price -- skip it.
            continue

        badge_locator = item.locator(BADGE_SELECTOR)
        badge_count = await badge_locator.count()
        badge_names: list[str] = []
        for b in range(badge_count):
            alt = await badge_locator.nth(b).get_attribute("alt")
            if alt:
                badge_names.append(alt)

        try:
            rating_text = (await item.locator(RATING_SELECTOR).first.inner_text()).strip()
        except Exception:
            rating_text = ""

        try:
            sales_text = (await item.locator(SALES_SELECTOR).first.inner_text()).strip()
        except Exception:
            sales_text = ""

        has_photo_listing = await item.locator(PHOTO_LISTING_SELECTOR).count() > 0

        listings.append(
            Listing(
                seller_name=seller_name,
                condition_text=condition_text,
                price=price,
                is_verified=len(badge_names) > 0,
                badge_names=badge_names,
                rating_text=rating_text,
                sales_text=sales_text,
                has_photo_listing=has_photo_listing,
            )
        )

    return listings


def _strip_page_param(url: str) -> str:
    """Remove any existing page=N query param so we can set our own."""
    return re.sub(r"([?&])page=\d+&?", lambda m: m.group(1) if m.group(1) == "?" else "", url).rstrip("&?")


def _url_for_page(base_url: str, page_num: int) -> str:
    stripped = _strip_page_param(base_url)
    sep = "&" if "?" in stripped else "?"
    return f"{stripped}{sep}page={page_num}"


async def find_best_near_mint_foil(
    page: Page,
    tcgplayer_url: str,
    require_verified: bool = True,
    max_pages: int = config.MAX_SCRAPE_PAGES,
) -> Listing | None:
    """
    Walk TCGPlayer result pages (in default Price+Shipping ascending order)
    looking for the first Near Mint Foil listing. If require_verified is
    True, skip sellers with zero trust badges and keep looking.

    Returns the matching Listing, or None if nothing found within max_pages.
    """
    for page_num in range(1, max_pages + 1):
        url = _url_for_page(tcgplayer_url, page_num)
        logger.info("Scraping page %s: %s", page_num, url)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=config.PAGE_TIMEOUT_MS)
            # Wait specifically for a listing to render, rather than a fixed sleep.
            await page.wait_for_selector(LISTING_SELECTOR, timeout=config.PAGE_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            logger.warning("Timed out waiting for listings on page %s (%s)", page_num, url)
            break

        listings = await _extract_listings(page)
        if not listings:
            # No more listings -- we've run off the end of pagination.
            break

        for listing in listings:
            if listing.has_photo_listing:
                # Custom-photo listings are frequently off-market/foreign
                # prints (e.g. "*Chinese* MINT ..."), not the standard
                # English print we're trying to price. Skip them entirely.
                continue
            if not _wants_near_mint_foil(listing.condition_text):
                continue
            if require_verified and not listing.is_verified:
                continue
            return listing

    return None


async def check_variant_price(
    page: Page,
    variant_label: str,
    tcgplayer_url: str | None,
) -> dict:
    """
    Wraps find_best_near_mint_foil with error handling and returns a plain
    dict suitable for passing straight into the Discord embed builder.
    """
    if not tcgplayer_url:
        return {
            "variant_label": variant_label,
            "found": False,
            "reason": "no_listing_url",
            "tcgplayer_url": None,
        }

    try:
        listing = await find_best_near_mint_foil(
            page,
            tcgplayer_url,
            require_verified=config.REQUIRE_VERIFIED_SELLER,
        )
    except Exception as e:
        logger.exception("Error scraping variant '%s'", variant_label)
        return {
            "variant_label": variant_label,
            "found": False,
            "reason": "scrape_error",
            "error": str(e),
            "tcgplayer_url": tcgplayer_url,
        }

    if listing is None:
        return {
            "variant_label": variant_label,
            "found": False,
            "reason": "no_near_mint_foil",
            "tcgplayer_url": tcgplayer_url,
        }

    return {
        "variant_label": variant_label,
        "found": True,
        "price": listing.price,
        "seller_name": listing.seller_name,
        "is_verified": listing.is_verified,
        "badge_names": listing.badge_names,
        "condition_text": listing.condition_text,
        "tcgplayer_url": tcgplayer_url,
    }


async def check_variants_price(
    browser_context,
    variants: list[tuple[str, str | None]],
    concurrency: int = config.SCRAPE_CONCURRENCY,
) -> list[dict]:
    """
    Check Near Mint Foil price across multiple variants concurrently
    (bounded by `concurrency` separate browser tabs/pages).

    variants: list of (variant_label, tcgplayer_url) tuples.
    """
    semaphore = asyncio.Semaphore(concurrency)
    results: list[dict | None] = [None] * len(variants)

    async def _worker(index: int, label: str, url: str | None):
        async with semaphore:
            page = await browser_context.new_page()
            try:
                results[index] = await check_variant_price(page, label, url)
            finally:
                await page.close()

    await asyncio.gather(
        *[
            _worker(i, label, url)
            for i, (label, url) in enumerate(variants)
        ]
    )

    return [r for r in results if r is not None]
