"""
Central configuration for the TreasureTracker Price Bot.
Everything is driven by environment variables so behavior can be changed
on Railway (or locally via a .env file) without touching code.
"""

import os

try:
    # Locally, load variables from a .env file if present (e.g. via PyCharm run).
    # On Railway, env vars are injected directly by the platform, so this is a
    # no-op there -- python-dotenv simply won't find a .env file and that's fine.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# --- Discord ---
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
# The bot listens for mentions like "@price-bot fetch OP01-016"
# command prefix used when mentioning the bot, e.g. "fetch"
COMMAND_NAME = os.getenv("COMMAND_NAME", "fetch")

# Comma-separated list of Discord channel IDs the bot is allowed to respond
# in, e.g. "123456789012345678" or "123456789012345678,987654321098765432".
# Leave empty/unset to allow the bot to respond in ANY channel it can see.
# To get a channel ID: enable Developer Mode (User Settings -> Advanced),
# then right-click the channel -> Copy Channel ID.
_raw_allowed_channels = os.getenv("ALLOWED_CHANNEL_IDS", "").strip()
ALLOWED_CHANNEL_IDS: set[int] = {
    int(cid.strip()) for cid in _raw_allowed_channels.split(",") if cid.strip()
}

# --- TreasureTracker API ---
CARD_API_BASE_URL = os.getenv(
    "CARD_API_BASE_URL", "https://treasuretracker-production.up.railway.app"
)

# --- Queue behavior ---
# Max number of price-check jobs allowed to be queued at once.
# Easily toggleable via Railway env var without a redeploy of code logic.
MAX_QUEUE_SIZE = int(os.getenv("MAX_QUEUE_SIZE", "5"))

# --- Scraping behavior ---
# Hard cap on how many TCGPlayer result pages we'll walk per variant
# while searching for a Near Mint Foil listing from a trusted seller.
MAX_SCRAPE_PAGES = int(os.getenv("MAX_SCRAPE_PAGES", "2"))

# How many variant pages to scrape concurrently (separate browser tabs/contexts).
# Keep this modest -- TCGPlayer will rate limit / block aggressively if too high.
SCRAPE_CONCURRENCY = int(os.getenv("SCRAPE_CONCURRENCY", "3"))

# Per-page navigation timeout, in milliseconds.
PAGE_TIMEOUT_MS = int(os.getenv("PAGE_TIMEOUT_MS", "30000"))

# Whether a listing must show at least one trust badge
# (Certified Hobby Shop / Gold Star / WPN Seller) to count as "verified".
REQUIRE_VERIFIED_SELLER = _get_bool("REQUIRE_VERIFIED_SELLER", True)

# Run the browser headless (set False only for local debugging).
HEADLESS = _get_bool("HEADLESS", True)

# --- Logging ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
