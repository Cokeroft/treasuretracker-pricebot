"""
TreasureTracker Price Bot — Discord entrypoint.

Usage in Discord:
    @price-bot fetch OP01-016

This:
  1. Looks up OP01-016 via the TreasureTracker card API (pricing_card_api.py)
  2. Scrapes TCGPlayer for each variant's cheapest verified Near Mint Foil
     listing (scraper.py), running jobs through a bounded queue
     (queue_manager.py, default max 5 -- see MAX_QUEUE_SIZE in config.py)
  3. Replies with a Discord embed (embeds.py)
"""

import asyncio
import logging
import uuid

import discord
from playwright.async_api import async_playwright

import config
import embeds
import pricing_card_api
from queue_manager import Job, PriceCheckQueue, QueueFullError

logging.basicConfig(
    level=config.LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("pricebot")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

price_queue = PriceCheckQueue()

# A single shared Playwright browser instance, reused across jobs.
# Each job opens its own page(s)/tab(s) within this browser rather than
# launching a brand-new browser process every time (much cheaper).
_playwright = None
_browser = None
_browser_lock = asyncio.Lock()


async def get_browser():
    global _playwright, _browser
    async with _browser_lock:
        if _browser is None:
            _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(headless=config.HEADLESS)
            logger.info("Playwright browser launched (headless=%s)", config.HEADLESS)
    return _browser


def parse_command(content: str) -> tuple[str, str] | None:
    """
    Parses a message like "@price-bot fetch OP01-016" (mention is stripped
    by Discord before message_content reaches us as plain text mention
    markup -- we just look for the command keyword and the card id after it).

    Returns (command, card_id) or None if it doesn't match.
    """
    parts = content.strip().split()
    # Expect something like: ["<@123456>", "fetch", "OP01-016"]
    # after stripping the leading mention token.
    filtered = [p for p in parts if not p.startswith("<@")]
    if len(filtered) < 2:
        return None
    command, card_id = filtered[0].lower(), filtered[1]
    return command, card_id


async def run_price_check(message: discord.Message, card_id: str):
    status_msg = await message.reply(f"Looking up **{card_id}**...")

    try:
        card = await pricing_card_api.fetch_card(card_id)
    except pricing_card_api.CardNotFoundError:
        await status_msg.edit(content=f"Couldn't find a card with id `{card_id}`.")
        return
    except pricing_card_api.CardApiError as e:
        logger.error("Card API error for %s: %s", card_id, e)
        await status_msg.edit(content=f"Card API error while looking up `{card_id}`. Try again shortly.")
        return

    if not card.variants:
        await status_msg.edit(content=f"**{card.name}** ({card_id}) has no known variants on file.")
        return

    await status_msg.edit(
        content=(
            f"Found **{card.name}** ({card_id}) with {len(card.variants)} variant(s). "
            f"Checking TCGPlayer for Near Mint Foil pricing — this can take a minute..."
        )
    )

    browser = await get_browser()
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1400, "height": 1000},
    )

    try:
        from scraper import check_variants_price

        variant_pairs = [(v.label, v.tcgplayer_url) for v in card.variants]
        results = await check_variants_price(context, variant_pairs)
    finally:
        await context.close()

    embed = embeds.build_price_check_embed(card.name, card_id, results)
    await status_msg.edit(content=None, embed=embed)


@client.event
async def on_ready():
    price_queue.start()
    logger.info("Logged in as %s", client.user)


@client.event
async def on_message(message: discord.Message):
    logger.info(
        "on_message fired: channel=%s author=%s content=%r mentions=%s",
        message.channel, message.author, message.content, message.mentions,
    )

    if message.author == client.user:
        return

    # Discord auto-creates a role matching the bot's name. If someone selects
    # that role from autocomplete instead of the bot user itself, Discord
    # sends a role mention (<@&ROLE_ID>), which does NOT show up in
    # message.mentions. We can't get the bot's managed role ID without an
    # extra API call, so we match on name as a best-effort nudge.
    role_mentioned = any(
        role.name == client.user.name for role in message.role_mentions
    )

    if client.user not in message.mentions:
        if role_mentioned:
            logger.info("Bot's ROLE was mentioned instead of the bot user -- nudging user.")
            await message.reply(
                "Looks like you mentioned my **role** instead of me directly. "
                "Try typing `@` again and pick the entry under **Members** "
                "(the one with my avatar), not the one under **Roles**."
            )
        else:
            logger.info("Bot was not mentioned in this message -- ignoring.")
        return

    parsed = parse_command(message.content)
    if parsed is None:
        await message.reply(
            f"Usage: `@{client.user.name} {config.COMMAND_NAME} <CARD_ID>` "
            f"(e.g. `@{client.user.name} {config.COMMAND_NAME} OP01-016`)"
        )
        return

    command, card_id = parsed
    if command != config.COMMAND_NAME:
        await message.reply(f"Unknown command `{command}`. Try `{config.COMMAND_NAME}`.")
        return

    job_id = str(uuid.uuid4())[:8]

    async def _coro_factory():
        await run_price_check(message, card_id)

    job = Job(job_id=job_id, coro_factory=_coro_factory, description=f"fetch {card_id}")

    try:
        await price_queue.enqueue(job)
    except QueueFullError:
        await message.reply(
            f"Queue is full ({config.MAX_QUEUE_SIZE} requests already waiting) — "
            f"try again in a bit."
        )
        return

    queue_size = price_queue.queue_size()
    if queue_size > 1:
        await message.reply(f"Queued (`{job_id}`) — {queue_size - 1} request(s) ahead of yours.")


if __name__ == "__main__":
    if not config.DISCORD_BOT_TOKEN:
        raise SystemExit("DISCORD_BOT_TOKEN environment variable is not set.")
    client.run(config.DISCORD_BOT_TOKEN)
