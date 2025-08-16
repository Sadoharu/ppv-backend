# backend/api/v1/protected.py
"""Захищений ендпойнт для перевірки JWT (cookie access_token)."""

from fastapi import APIRouter, Depends
from backend.api.deps import require_auth
from backend import models

router = APIRouter(tags=["protected"])

@router.get("/content")
def protected_content(sess: models.Session = Depends(require_auth)):
    """
    200 OK – якщо cookie access_token валідна і сесія активна.
    401     – в усіх інших випадках (кидається у require_auth).
    """
    return {"message": "Secret content here"}
