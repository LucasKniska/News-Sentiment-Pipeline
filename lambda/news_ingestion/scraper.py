import logging

import trafilatura
from trafilatura.settings import use_config

logger = logging.getLogger(__name__)

# trafilatura logs a warning per URL it can't parse cleanly; that's expected
# for paywalled/bot-blocked sites and would otherwise drown out our own logs.
logging.getLogger("trafilatura").setLevel(logging.WARNING)

# trafilatura's default User-Agent self-identifies as "trafilatura/<version>",
# which basic bot filters reject outright (confirmed empirically: every fetch
# failed under the default UA). A real browser UA at least clears that bar -
# it still won't get past heavier bot-management (e.g. Cloudflare), which
# blocks on TLS/behavioral fingerprinting regardless of headers.
_CONFIG = use_config()
_CONFIG.set(
    "DEFAULT",
    "USER_AGENTS",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)


def fetch_article_text(url: str) -> str | None:
    try:
        downloaded = trafilatura.fetch_url(url, config=_CONFIG)
    except Exception:
        logger.warning("Failed to fetch article at %s", url, exc_info=True)
        return None

    if downloaded is None:
        logger.warning("Fetch returned no content for %s", url)
        return None

    try:
        extracted = trafilatura.extract(downloaded)
    except Exception:
        logger.warning("Failed to extract article text from %s", url, exc_info=True)
        return None

    if not extracted:
        logger.warning("Extraction found no article text for %s", url)
        return None

    return extracted
