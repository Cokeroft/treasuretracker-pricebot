"""
Builds the Discord embed shown for a price-check result, matching the
agreed format: every variant listed, with price + seller + verified
checkmark where found, or a clear "no listing" note where not.
"""

import discord


def _format_variant_line(result: dict) -> str:
    label = result["variant_label"]
    url = result.get("tcgplayer_url")
    title = f"**[{label}]({url})**" if url else f"**{label}**"

    if not result.get("found"):
        reason = result.get("reason", "not_found")
        note = {
            "no_listing_url": "no TCGPlayer listing on file",
            "no_near_mint_foil": "no NM foil listing found",
            "scrape_error": "couldn't check (scrape error)",
        }.get(reason, "not found")
        return f"{title}\n> {note}"

    price = result["price"]
    seller = result["seller_name"]
    verified_mark = " ✅" if result.get("is_verified") else ""
    return f"{title}\n> ${price:.2f} — {seller}{verified_mark}"


def build_price_check_embed(card_name: str, card_id: str, results: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title=f"{card_name} ({card_id}) — Price Check",
        description="Cheapest verified Near Mint Foil listing per variant",
        color=discord.Color.blue(),
    )

    if not results:
        embed.add_field(name="No variants found", value="—", inline=False)
        return embed

    # Discord embed fields cap around 1024 chars each and a max of 25 fields.
    # Group variants in chunks to stay safely within both limits and keep
    # related entries readable together.
    lines = [_format_variant_line(r) for r in results]

    chunk_size = 5
    for idx in range(0, len(lines), chunk_size):
        chunk = lines[idx: idx + chunk_size]
        embed.add_field(
            name="\u200b",  # zero-width space; we don't need a header per chunk
            value="\n\n".join(chunk),
            inline=False,
        )

    found_count = sum(1 for r in results if r.get("found"))
    embed.set_footer(
        text=f"{found_count}/{len(results)} variants had a verified NM foil listing"
    )

    return embed
