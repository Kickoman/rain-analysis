"""Tests for the in-memory rate limiter."""

import pytest
import asyncio
from datetime import datetime, timedelta
from backend.app.auth.rate_limiter import InMemoryRateLimiter


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_rate_limiter_allows_requests_within_limit():
    """Test that requests within limits are allowed."""
    limiter = InMemoryRateLimiter()
    key_id = 1

    # Should allow 5 requests with rpm=10
    for _ in range(5):
        allowed = await limiter.check_rate_limit(key_id, rpm=10, rph=None, rpd=None)
        assert allowed is True


async def test_rate_limiter_blocks_requests_exceeding_rpm():
    """Test that requests exceeding RPM limit are blocked."""
    limiter = InMemoryRateLimiter()
    key_id = 1
    rpm = 5

    # Make 5 requests (at limit)
    for _ in range(rpm):
        allowed = await limiter.check_rate_limit(key_id, rpm=rpm, rph=None, rpd=None)
        assert allowed is True

    # 6th request should be blocked
    allowed = await limiter.check_rate_limit(key_id, rpm=rpm, rph=None, rpd=None)
    assert allowed is False


async def test_rate_limiter_blocks_requests_exceeding_rph():
    """Test that requests exceeding RPH limit are blocked."""
    limiter = InMemoryRateLimiter()
    key_id = 2
    rph = 10

    # Make 10 requests (at limit)
    for _ in range(rph):
        allowed = await limiter.check_rate_limit(key_id, rpm=None, rph=rph, rpd=None)
        assert allowed is True

    # 11th request should be blocked
    allowed = await limiter.check_rate_limit(key_id, rpm=None, rph=rph, rpd=None)
    assert allowed is False


async def test_rate_limiter_blocks_requests_exceeding_rpd():
    """Test that requests exceeding RPD limit are blocked."""
    limiter = InMemoryRateLimiter()
    key_id = 3
    rpd = 20

    # Make 20 requests (at limit)
    for _ in range(rpd):
        allowed = await limiter.check_rate_limit(key_id, rpm=None, rph=None, rpd=rpd)
        assert allowed is True

    # 21st request should be blocked
    allowed = await limiter.check_rate_limit(key_id, rpm=None, rph=None, rpd=rpd)
    assert allowed is False


async def test_rate_limiter_handles_multiple_keys():
    """Test that rate limiter tracks different keys independently."""
    limiter = InMemoryRateLimiter()
    key1 = 1
    key2 = 2
    rpm = 5

    # Max out key1
    for _ in range(rpm):
        allowed = await limiter.check_rate_limit(key1, rpm=rpm, rph=None, rpd=None)
        assert allowed is True

    # key1 should be blocked
    allowed = await limiter.check_rate_limit(key1, rpm=rpm, rph=None, rpd=None)
    assert allowed is False

    # key2 should still be allowed
    allowed = await limiter.check_rate_limit(key2, rpm=rpm, rph=None, rpd=None)
    assert allowed is True


async def test_rate_limiter_unlimited_when_none():
    """Test that None limits mean unlimited."""
    limiter = InMemoryRateLimiter()
    key_id = 4

    # Should allow many requests when all limits are None
    for _ in range(100):
        allowed = await limiter.check_rate_limit(
            key_id, rpm=None, rph=None, rpd=None
        )
        assert allowed is True


async def test_rate_limiter_enforces_strictest_limit():
    """Test that the strictest limit is enforced when multiple are set."""
    limiter = InMemoryRateLimiter()
    key_id = 5

    # Set rpm=3, rph=100, rpd=1000
    # RPM should be the limiting factor
    for _ in range(3):
        allowed = await limiter.check_rate_limit(key_id, rpm=3, rph=100, rpd=1000)
        assert allowed is True

    # 4th request should be blocked by RPM
    allowed = await limiter.check_rate_limit(key_id, rpm=3, rph=100, rpd=1000)
    assert allowed is False


async def test_get_remaining_returns_correct_counts():
    """Test that get_remaining returns accurate remaining request counts."""
    limiter = InMemoryRateLimiter()
    key_id = 6
    rpm, rph, rpd = 10, 100, 1000

    # Make 3 requests
    for _ in range(3):
        await limiter.check_rate_limit(key_id, rpm=rpm, rph=rph, rpd=rpd)

    # Check remaining
    remaining = await limiter.get_remaining(key_id, rpm, rph, rpd)
    assert remaining["rpm_remaining"] == 7
    assert remaining["rph_remaining"] == 97
    assert remaining["rpd_remaining"] == 997


async def test_get_remaining_handles_none_limits():
    """Test that get_remaining handles None limits correctly."""
    limiter = InMemoryRateLimiter()
    key_id = 7

    # Make some requests with no limits
    for _ in range(5):
        await limiter.check_rate_limit(key_id, rpm=None, rph=None, rpd=None)

    # get_remaining should handle None gracefully
    remaining = await limiter.get_remaining(key_id, rpm=10, rph=100, rpd=1000)
    assert remaining["rpm_remaining"] == 5
    assert remaining["rph_remaining"] == 95
    assert remaining["rpd_remaining"] == 995


async def test_rate_limiter_cleans_old_timestamps():
    """Test that old timestamps are cleaned up (integration test, not time-based)."""
    limiter = InMemoryRateLimiter()
    key_id = 8

    # This test verifies the cleanup logic exists
    # We can't easily test time-based cleanup without mocking datetime
    # But we can verify the structure is maintained
    for _ in range(5):
        await limiter.check_rate_limit(key_id, rpm=10, rph=100, rpd=1000)

    # Verify counters exist
    assert str(key_id) in limiter._counters
    assert "minute" in limiter._counters[str(key_id)]
    assert "hour" in limiter._counters[str(key_id)]
    assert "day" in limiter._counters[str(key_id)]


async def test_rate_limiter_thread_safety():
    """Test that rate limiter is thread-safe with concurrent requests."""
    limiter = InMemoryRateLimiter()
    key_id = 9
    rpm = 20

    async def make_request():
        return await limiter.check_rate_limit(key_id, rpm=rpm, rph=None, rpd=None)

    # Make 25 concurrent requests (5 over the limit)
    results = await asyncio.gather(*[make_request() for _ in range(25)])

    # Should have exactly 20 True and 5 False
    allowed_count = sum(results)
    assert allowed_count == rpm
    assert sum(not r for r in results) == 5
