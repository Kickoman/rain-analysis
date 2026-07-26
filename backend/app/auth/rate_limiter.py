"""In-memory rate limiter for API key rate limiting."""

from datetime import datetime, timedelta
from typing import Dict, Optional
import asyncio
from collections import defaultdict


class InMemoryRateLimiter:
    """In-memory rate limiter that tracks requests per key."""

    def __init__(self):
        """Initialize the rate limiter with empty counters."""
        self._counters: Dict[str, Dict[str, list]] = defaultdict(
            lambda: {"minute": [], "hour": [], "day": []}
        )
        self._lock = asyncio.Lock()

    async def check_rate_limit(
        self,
        key_id: int,
        rpm: Optional[int],
        rph: Optional[int],
        rpd: Optional[int],
    ) -> bool:
        """
        Check if request is within rate limits.

        Args:
            key_id: API key database ID
            rpm: Requests per minute limit (None = unlimited)
            rph: Requests per hour limit (None = unlimited)
            rpd: Requests per day limit (None = unlimited)

        Returns:
            True if request is allowed, False if rate limit exceeded
        """
        async with self._lock:
            now = datetime.utcnow()
            counters = self._counters[str(key_id)]

            # Clean old timestamps
            counters["minute"] = [
                t for t in counters["minute"] if t > now - timedelta(minutes=1)
            ]
            counters["hour"] = [
                t for t in counters["hour"] if t > now - timedelta(hours=1)
            ]
            counters["day"] = [
                t for t in counters["day"] if t > now - timedelta(days=1)
            ]

            # Check limits
            if rpm and len(counters["minute"]) >= rpm:
                return False
            if rph and len(counters["hour"]) >= rph:
                return False
            if rpd and len(counters["day"]) >= rpd:
                return False

            # Record request
            counters["minute"].append(now)
            counters["hour"].append(now)
            counters["day"].append(now)

            return True

    async def get_remaining(
        self, key_id: int, rpm: int, rph: int, rpd: int
    ) -> dict:
        """
        Get remaining requests for each time window.

        Args:
            key_id: API key database ID
            rpm: Requests per minute limit
            rph: Requests per hour limit
            rpd: Requests per day limit

        Returns:
            Dictionary with remaining counts for each window
        """
        async with self._lock:
            now = datetime.utcnow()
            counters = self._counters[str(key_id)]

            minute_count = len(
                [t for t in counters["minute"] if t > now - timedelta(minutes=1)]
            )
            hour_count = len(
                [t for t in counters["hour"] if t > now - timedelta(hours=1)]
            )
            day_count = len(
                [t for t in counters["day"] if t > now - timedelta(days=1)]
            )

            return {
                "rpm_remaining": rpm - minute_count if rpm else None,
                "rph_remaining": rph - hour_count if rph else None,
                "rpd_remaining": rpd - day_count if rpd else None,
            }
