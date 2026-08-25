"""Shared application constants."""

# Paths that bypass API-key authentication and are excluded from the
# OpenAPI security requirement. Keep this the single source of truth:
# both the auth middleware and the OpenAPI customizer import it.
EXEMPT_PATHS = frozenset(
    {
        "/",
        "/health",
        "/health/live",
        "/health/ready",
        "/docs",
        "/openapi.json",
        "/redoc",
    }
)
