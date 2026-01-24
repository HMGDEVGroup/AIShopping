from __future__ import annotations

import re
from typing import Optional, Set

# Retailers that typically require a paid membership to purchase
MEMBERSHIP_RETAILERS: Set[str] = {
    "costco",
    "sam's club",
    "bjs",
    "bj's",
}

# Retailers we want to "prefer" in sorting (optional boost)
PREFERRED_RETAILERS: list[str] = [
    "costco",
    "amazon",
    "walmart",
    "target",
    "best buy",
    "home depot",
    "lowe's",
]

def normalize_retailer_name(source: Optional[str]) -> Optional[str]:
    """
    Normalize store/source strings from shopping results so:
      - "Costco.com", "COSTCO", "Costco Wholesale" => "Costco"
      - "Sam’s Club" => "Sam's Club"
      - "BJ’s" => "BJ's"
    """
    if not source:
        return source

    s = source.strip()

    # Remove obvious suffixes
    s = re.sub(r"\.com$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\.net$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\.org$", "", s, flags=re.IGNORECASE)

    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()

    low = s.lower()

    # Costco normalization
    if "costco" in low:
        return "Costco"

    # Sam's Club normalization
    if "sam" in low and "club" in low:
        return "Sam's Club"

    # BJ's normalization
    if low.startswith("bj") or "bj" in low:
        return "BJ's"

    # Title case fallback (keeps "Best Buy" etc readable)
    return s


def is_membership_retailer(source: Optional[str]) -> bool:
    if not source:
        return False
    low = source.strip().lower()
    return any(m in low for m in MEMBERSHIP_RETAILERS)


def preferred_rank(source: Optional[str]) -> int:
    """
    Smaller rank = higher priority in sorting.
    Not required for correctness, but helps Costco show up near the top.
    """
    if not source:
        return 999

    low = source.strip().lower()

    for i, pref in enumerate(PREFERRED_RETAILERS):
        if pref in low:
            return i
    return 999
