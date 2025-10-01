"""Authentication and authorization abstractions for API."""

from abc import ABC, abstractmethod
from fastapi import Request


class SecurityScheme(ABC):
    """
    Abstract base class for authentication/authorization schemes.
    
    Provides extension point for different auth methods:
    - NoOpAuth (MVP - no authentication)
    - APIKeyAuth (check API key in header)
    - JWTAuth (validate JWT token)
    - mTLSAuth (mutual TLS certificate validation)
    
    Design allows swapping implementations without changing endpoint signatures.
    """
    
    @abstractmethod
    async def verify(self, request: Request) -> bool:
        """
        Verify authentication/authorization for the request.
        
        Args:
            request: FastAPI Request object
            
        Returns:
            True if authenticated/authorized, False otherwise
            
        Raises:
            HTTPException: If authentication fails (implementation-specific)
        """
        pass


class NoOpAuth(SecurityScheme):
    """
    No-op authentication for MVP.
    
    Always returns True - no authentication required.
    Use this when API is behind a gateway that handles auth,
    or during development/testing.
    """
    
    async def verify(self, request: Request) -> bool:
        """Always allow access."""
        return True


# Future implementations:
#
# class APIKeyAuth(SecurityScheme):
#     """Validate API key from X-API-Key header."""
#     def __init__(self, valid_keys: set[str]):
#         self.valid_keys = valid_keys
#     
#     async def verify(self, request: Request) -> bool:
#         api_key = request.headers.get("X-API-Key")
#         if not api_key or api_key not in self.valid_keys:
#             raise HTTPException(401, "Invalid API key")
#         return True
#
# class JWTAuth(SecurityScheme):
#     """Validate JWT token from Authorization header."""
#     def __init__(self, secret_key: str, algorithm: str = "HS256"):
#         self.secret_key = secret_key
#         self.algorithm = algorithm
#     
#     async def verify(self, request: Request) -> bool:
#         auth_header = request.headers.get("Authorization")
#         if not auth_header or not auth_header.startswith("Bearer "):
#             raise HTTPException(401, "Missing or invalid Authorization header")
#         
#         token = auth_header.split(" ")[1]
#         try:
#             payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
#             return True
#         except jwt.InvalidTokenError:
#             raise HTTPException(401, "Invalid token")
