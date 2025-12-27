# backend/services/authz/policy.py
#v0.5
from __future__ import annotations
from typing import Optional
from sqlalchemy import select, exists
from sqlalchemy.orm import Session

from backend import models

def code_allows_event(db: Session, code: "models.AccessCode", event_id: Optional[int]) -> bool:
    """
    Політика доступу (deny-by-default).

    1) Якщо event_id is None → True (нема контексту події).
    2) Якщо code.allow_all_events або code.allow_all → True.
    3) Якщо code.event_id заданий → дозволити лише при точному збігу.
    4) Інакше → дозволити тільки якщо існує M2M-зв'язок (CodeAllowedEvent) з цим event_id.
       (відсутність зв'язків = заборона)
    """
    # 1) Немає контексту події — не обмежуємо
    if event_id is None:
        return True

    # 2) Універсальний код
    if any(getattr(code, name, False) for name in ("allow_all_events", "allow_all")):
        return True

    # 3) Пряма прив'язка коду до однієї події
    fixed_eid = getattr(code, "event_id", None)
    if fixed_eid is not None:
        return int(fixed_eid) == int(event_id)

    # 4) M2M: білий список дозволених подій
    stmt = select(
        exists().where(
            models.CodeAllowedEvent.code_id == code.id,
            models.CodeAllowedEvent.event_id == int(event_id),
        )
    )
    return bool(db.execute(stmt).scalar())
