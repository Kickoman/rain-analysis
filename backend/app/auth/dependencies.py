"""Authentication dependencies for FastAPI endpoints."""

from fastapi import Request, HTTPException, status
from ..models import APIKey


def require_api_key(required_scope: str):
    """
    Factory function to create a dependency that checks API key scope.
    
    Args:
        required_scope: Required scope ("read", "write", or "admin")
    
    Returns:
        Dependency function that validates API key scope
    
    Example:
        @router.get("/data")
        async def get_data(api_key: APIKey = Depends(require_api_key("read"))):
            ...
    """
    def check_scope(request: Request) -> APIKey:
        """
        Dependency to check API key scope.
        
        Requires that the request has been authenticated via middleware
        and that the API key has sufficient scope.
        
        Args:
            request: FastAPI request object with state.api_key set by middleware
        
        Returns:
            APIKey: The authenticated API key
        
        Raises:
            HTTPException: If no API key is present or if scope is insufficient
        """
        if not hasattr(request.state, "api_key"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required"
            )
        
        api_key = request.state.api_key
        
        # Scope hierarchy: admin > write > read
        scope_hierarchy = {"read": 1, "write": 2, "admin": 3}
        
        required_level = scope_hierarchy.get(required_scope, 0)
        actual_level = scope_hierarchy.get(api_key.scope, 0)
        
        if actual_level < required_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required: {required_scope}, have: {api_key.scope}"
            )
        
        return api_key
    
    return check_scope
