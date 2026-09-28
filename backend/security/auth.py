from typing import Optional
from fastapi import Header, Query, HTTPException, Security, Depends
from fastapi.security import APIKeyHeader, APIKeyQuery
from backend.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
api_key_query = APIKeyQuery(name="api_key", auto_error=False)

def extract_api_key(
    x_api_key: Optional[str] = Security(api_key_header),
    api_key: Optional[str] = Security(api_key_query),
    authorization: Optional[str] = Header(None)
) -> Optional[str]:
    """
    Extracts API Key from X-API-Key header, Authorization: Bearer <key> header,
    or api_key query parameter (used for MJPEG stream and evidence URLs).
    Also supports direct call with a Starlette Request instance in middleware.
    """
    # Middleware direct call support: extract_api_key(request)
    if hasattr(x_api_key, "headers"):
        req = x_api_key
        h_key = req.headers.get("x-api-key")
        if h_key and h_key.strip():
            return h_key.strip()
        auth = req.headers.get("authorization")
        if auth and auth.strip():
            parts = auth.strip().split(" ")
            if len(parts) == 2 and parts[0].lower() == "bearer":
                return parts[1].strip()
            return auth.strip()
        q_key = req.query_params.get("api_key")
        if q_key and q_key.strip():
            return q_key.strip()
        return None

    if x_api_key and isinstance(x_api_key, str) and x_api_key.strip():
        return x_api_key.strip()
    if api_key and isinstance(api_key, str) and api_key.strip():
        return api_key.strip()
    if authorization and isinstance(authorization, str) and authorization.strip():
        parts = authorization.strip().split(" ")
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        return authorization.strip()
    return None

def require_operator(key: Optional[str] = Depends(extract_api_key)) -> str:
    """
    Enforces OPERATOR or ADMIN authorization for sensitive surveillance reads:
    alerts, vehicle transits, face roster, live video feeds, evidence snapshots,
    and WebSocket ticket issuance.
    """
    if not key:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Provide X-API-Key header or api_key parameter."
        )
    if key in (settings.OPERATOR_API_KEY, settings.ADMIN_API_KEY):
        return "OPERATOR" if key == settings.OPERATOR_API_KEY else "ADMIN"
    raise HTTPException(
        status_code=403,
        detail="Forbidden: Invalid surveillance operator credentials."
    )

def require_admin(key: Optional[str] = Depends(extract_api_key)) -> str:
    """
    Enforces strict ADMIN authorization for state-mutating surveillance operations:
    camera registration/modification/deletion, geofence/tripwire geometry,
    vehicle and face watchlists, station config, and alert lifecycle.
    """
    if not key:
        raise HTTPException(
            status_code=401,
            detail="Administrative authentication required. Provide X-API-Key header or api_key parameter."
        )
    if key == settings.ADMIN_API_KEY:
        return "ADMIN"
    if key == settings.OPERATOR_API_KEY:
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Administrative privileges required. Operator credentials cannot modify system state."
        )
    raise HTTPException(
        status_code=403,
        detail="Forbidden: Invalid administrator credentials."
    )
