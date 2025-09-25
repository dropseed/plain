from __future__ import annotations

from urllib.parse import parse_qs, urlparse


def extract_tracking_params(url: str) -> tuple[str, str, str]:
    """
    Extract tracking parameters from a URL.

    Supports:
    - UTM parameters (utm_source, utm_medium, utm_campaign)
    - Simple ref parameter
    - Auto-detection of tracking IDs (gclid, fbclid)

    Args:
        url: Full URL to parse

    Returns:
        Tuple of (source, medium, campaign) strings
    """
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    source = ""
    medium = ""
    campaign = ""

    # Extract source (priority order)
    if utm_source := params.get("utm_source", [""])[0]:
        source = utm_source.strip().lower()
    elif ref := params.get("ref", [""])[0]:
        source = ref.strip().lower()
    elif "gclid" in params:
        source = "google"
    elif "fbclid" in params:
        source = "facebook"
    elif "msclkid" in params:
        source = "bing"
    elif "ttclid" in params:
        source = "tiktok"
    elif "twclid" in params:
        source = "twitter"

    # Extract medium
    if utm_medium := params.get("utm_medium", [""])[0]:
        medium = utm_medium.strip().lower()
    elif "gclid" in params:
        medium = "cpc"
    elif "fbclid" in params:
        medium = "social"
    elif "msclkid" in params:
        medium = "cpc"
    elif "ttclid" in params:
        medium = "cpc"
    elif "twclid" in params:
        medium = "cpc"

    # Extract campaign
    if utm_campaign := params.get("utm_campaign", [""])[0]:
        campaign = utm_campaign.strip().lower()

    return source, medium, campaign
