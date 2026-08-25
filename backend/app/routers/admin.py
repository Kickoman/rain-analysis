"""Admin endpoints for API key management."""
from fastapi import APIRouter, Depends, HTTPException, status, Request, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
import threading

from ..database import get_db
from ..models import APIKey, AdminAuditLog
from ..schemas.api_key import (
    APIKeyCreate,
    APIKeyResponse,
    APIKeyCreateResponse,
    APIKeyUpdate,
)
from ..auth.crypto import generate_api_key
from ..auth.dependencies import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/keys", response_model=APIKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_key(
    key_data: APIKeyCreate,
    admin_key: APIKey = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new API key.
    
    Only admin users can create new API keys.
    The full key is returned only once - it cannot be retrieved later.
    
    Args:
        key_data: API key creation data
        admin_key: The authenticated admin API key (from dependency)
        db: Database session
    
    Returns:
        APIKeyCreateResponse with full key and key metadata
    """
    # Generate the API key
    full_key, key_hash, key_prefix = generate_api_key(key_data.environment)
    
    # Create the database record
    new_key = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        owner=key_data.owner,
        description=key_data.description,
        scope=key_data.scope,
        rate_limit_rpm=key_data.rate_limit_rpm,
        rate_limit_rph=key_data.rate_limit_rph,
        rate_limit_rpd=key_data.rate_limit_rpd,
        expires_at=key_data.expires_at,
        is_active=True
    )
    
    db.add(new_key)
    await db.commit()
    await db.refresh(new_key)
    
    # Create audit log entry
    audit = AdminAuditLog(
        admin_key_id=admin_key.id,
        action="create_key",
        target_key_id=new_key.id,
        details={
            "owner": key_data.owner,
            "scope": key_data.scope,
            "key_prefix": key_prefix
        }
    )
    db.add(audit)
    await db.commit()
    
    return APIKeyCreateResponse(
        key=full_key,
        key_info=APIKeyResponse.model_validate(new_key)
    )


@router.get("/keys", response_model=List[APIKeyResponse])
async def list_keys(
    admin_key: APIKey = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    List all API keys.
    
    Only admin users can list all API keys.
    
    Args:
        admin_key: The authenticated admin API key (from dependency)
        db: Database session
    
    Returns:
        List of all API keys (without the actual key values)
    """
    result = await db.execute(select(APIKey).order_by(APIKey.created_at.desc()))
    keys = result.scalars().all()
    return [APIKeyResponse.model_validate(k) for k in keys]


@router.get("/keys/{key_id}", response_model=APIKeyResponse)
async def get_key(
    key_id: int,
    admin_key: APIKey = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Get details of a specific API key.
    
    Only admin users can view API key details.
    
    Args:
        key_id: ID of the API key to retrieve
        admin_key: The authenticated admin API key (from dependency)
        db: Database session
    
    Returns:
        API key details (without the actual key value)
    
    Raises:
        HTTPException: If key is not found
    """
    result = await db.execute(select(APIKey).where(APIKey.id == key_id))
    key = result.scalar_one_or_none()
    
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )
    
    return APIKeyResponse.model_validate(key)


@router.patch("/keys/{key_id}", response_model=APIKeyResponse)
async def update_key(
    key_id: int,
    update_data: APIKeyUpdate,
    admin_key: APIKey = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Update API key limits or status.
    
    Only admin users can update API keys.
    Allows updating rate limits and active status.
    
    Args:
        key_id: ID of the API key to update
        update_data: Fields to update
        admin_key: The authenticated admin API key (from dependency)
        db: Database session
    
    Returns:
        Updated API key details
    
    Raises:
        HTTPException: If key is not found
    """
    result = await db.execute(select(APIKey).where(APIKey.id == key_id))
    key = result.scalar_one_or_none()
    
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )
    
    # Track what changed for audit log
    changes = {}
    
    # Update only the fields that were provided
    if update_data.rate_limit_rpm is not None:
        key.rate_limit_rpm = update_data.rate_limit_rpm
        changes["rate_limit_rpm"] = update_data.rate_limit_rpm
    if update_data.rate_limit_rph is not None:
        key.rate_limit_rph = update_data.rate_limit_rph
        changes["rate_limit_rph"] = update_data.rate_limit_rph
    if update_data.rate_limit_rpd is not None:
        key.rate_limit_rpd = update_data.rate_limit_rpd
        changes["rate_limit_rpd"] = update_data.rate_limit_rpd
    if update_data.is_active is not None:
        key.is_active = update_data.is_active
        changes["is_active"] = update_data.is_active
    
    await db.commit()
    await db.refresh(key)
    
    # Create audit log entry
    audit = AdminAuditLog(
        admin_key_id=admin_key.id,
        action="update_key",
        target_key_id=key.id,
        details=changes
    )
    db.add(audit)
    await db.commit()
    
    return APIKeyResponse.model_validate(key)


@router.delete("/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_key(
    key_id: int,
    admin_key: APIKey = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Deactivate an API key.
    
    Only admin users can deactivate API keys.
    This sets is_active=False rather than deleting the record.
    
    Args:
        key_id: ID of the API key to deactivate
        admin_key: The authenticated admin API key (from dependency)
        db: Database session
    
    Raises:
        HTTPException: If key is not found or already inactive
    """
    result = await db.execute(select(APIKey).where(APIKey.id == key_id))
    key = result.scalar_one_or_none()
    
    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )
    
    if not key.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="API key is already inactive"
        )
    
    key.is_active = False
    await db.commit()
    
    # Create audit log entry
    audit = AdminAuditLog(
        admin_key_id=admin_key.id,
        action="deactivate_key",
        target_key_id=key.id,
        details={"key_prefix": key.key_prefix}
    )
    db.add(audit)
    await db.commit()


@router.post("/ml/trigger-daily-task")
async def trigger_daily_task(
    admin_key: APIKey = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Manually trigger daily ML task (admin only).
    
    Useful for testing the daily task without waiting for the scheduled time.
    The task runs in a background thread to avoid blocking the request.
    
    Args:
        admin_key: The authenticated admin API key (from dependency)
        db: Database session
    
    Returns:
        Success message indicating the task was triggered
    """
    from ..ml.daily_task import run_daily_task
    
    # Run in background thread to avoid blocking
    thread = threading.Thread(target=run_daily_task, daemon=True)
    thread.start()
    
    # Create audit log entry
    audit = AdminAuditLog(
        admin_key_id=admin_key.id,
        action="trigger_daily_ml_task",
        target_key_id=None,
        details={"status": "triggered"}
    )
    db.add(audit)
    await db.commit()
    
    return {
        "message": "Daily ML task triggered successfully",
        "status": "running_in_background"
    }
