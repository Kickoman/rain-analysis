#!/usr/bin/env python3
"""Generate an admin API key for rain-analysis backend."""

import asyncio
import argparse
import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.models import APIKey
from app.auth.crypto import generate_api_key
from app.config import settings


async def create_admin_key(owner: str, environment: str, description: str = None):
    """
    Create an admin API key and store it in the database.
    
    Args:
        owner: Owner name/email for the key
        environment: "live" or "test"
        description: Optional description for the key
    """
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    full_key, key_hash, key_prefix = generate_api_key(environment)
    
    async with async_session() as session:
        admin_key = APIKey(
            key_hash=key_hash,
            key_prefix=key_prefix,
            owner=owner,
            description=description or f"Admin key for {owner}",
            scope="admin",
            rate_limit_rpm=1000,
            rate_limit_rph=10000,
            rate_limit_rpd=100000,
            is_active=True
        )
        session.add(admin_key)
        await session.commit()
        await session.refresh(admin_key)
        
        print(f"\n✓ Admin API key created!")
        print(f"\n🔑 API Key (save this): {full_key}")
        print(f"   Key ID: {admin_key.id}")
        print(f"   Owner: {admin_key.owner}")
        print(f"   Prefix: {admin_key.key_prefix}")
        print(f"   Scope: {admin_key.scope}")
        print(f"\n⚠️  Keep this key secure! It won't be shown again.\n")
    
    await engine.dispose()


def main():
    """Parse arguments and create admin key."""
    parser = argparse.ArgumentParser(
        description="Generate an admin API key for rain-analysis backend"
    )
    parser.add_argument(
        "owner",
        help="Owner name or email for the API key"
    )
    parser.add_argument(
        "--environment",
        choices=["live", "test"],
        default="live",
        help="Key environment (default: live)"
    )
    parser.add_argument(
        "--description",
        help="Optional description for the key"
    )
    
    args = parser.parse_args()
    
    try:
        asyncio.run(create_admin_key(
            owner=args.owner,
            environment=args.environment,
            description=args.description
        ))
    except Exception as e:
        print(f"\n❌ Error creating admin key: {e}\n", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
