#v0.5
# backend/services/codegen.py
from __future__ import annotations
import secrets
from typing import Optional, Iterable, Set, List
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

# Нечіткі символи прибрані (0/O/I/L)
DEFAULT_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
DEFAULT_LENGTH = 8

def _resolve_alphabet_and_length() -> tuple[str, int]:
    """
    Ледаче читання конфігів. Якщо settings недоступний — дефолти.
    """
    try:
        from backend.core.config import settings
        alphabet = getattr(settings, "code_alphabet", None) or DEFAULT_ALPHABET
        length = int(getattr(settings, "code_length", DEFAULT_LENGTH))
        return str(alphabet), int(length)
    except Exception:
        return DEFAULT_ALPHABET, DEFAULT_LENGTH

def generate_plain_code(
    length: Optional[int] = None,
    alphabet: Optional[str] = None,
) -> str:
    if alphabet is None or length is None:
        dfa, dfl = _resolve_alphabet_and_length()
        alphabet = alphabet or dfa
        length = length or dfl
    # Завжди верхній регістр: уніфікує збереження/перевірку
    return "".join(secrets.choice(alphabet) for _ in range(int(length))).upper()

def generate_unique_code(
    db: Session,
    Model,
    field_name: str = "code_plain",
    length: Optional[int] = None,
    alphabet: Optional[str] = None,
    max_attempts: int = 8,
) -> str:
    """
    Генерує унікальний plaintext-код, перевіряючи по БД.
    Підходить для reissue та одиночних створень.
    """
    for _ in range(int(max_attempts)):
        plain = generate_plain_code(length=length, alphabet=alphabet)
        field = getattr(Model, field_name)
        # дешевий EXISTS
        exists_stmt = select(field).where(field == plain).limit(1)
        if db.execute(exists_stmt).first() is None:
            return plain
    # якщо «не щастить» — віддай будь-який, і нехай INSERT зловить колізію
    return generate_plain_code(length=length, alphabet=alphabet)

def generate_unique_codes_bulk(
    db: Session,
    Model,
    field_name: str = "code_plain",
    n: int = 1,
    length: Optional[int] = None,
    alphabet: Optional[str] = None,
    max_rounds: int = 10,
) -> List[str]:
    """
    Ефективна генерація N унікальних кодів.
    Працює і проти міжсобойних колізій у партії, і проти колізій із БД.

    Алгоритм:
      1) генеруємо пачку кандидатів (із запасом),
      2) одним SELECT ... IN(...) відкидаємо ті, що вже є в БД,
      3) додаємо в результат, поки не назбираємо N, інакше — наступний раунд.
    """
    field = getattr(Model, field_name)
    result: List[str] = []
    chosen: Set[str] = set()  # захист від дублів у самій партії
    rounds = 0

    while len(result) < int(n) and rounds < max_rounds:
        rounds += 1
        need = int(n) - len(result)
        # генеруємо з невеликим «оверсайзом», щоб зменшити шанси перебору
        batch_size = max(need * 2, 16)
        candidates = {generate_plain_code(length=length, alphabet=alphabet) for _ in range(batch_size)}
        candidates -= chosen
        if not candidates:
            continue

        # перевірка проти БД одним запитом
        existing = {
            row[0]
            for row in db.execute(select(field).where(field.in_(list(candidates)))).all()
        }
        unique = list(candidates - existing)
        unique.sort()  # стабільність (не обов'язково)

        take = unique[:need]
        result.extend(take)
        chosen.update(take)

    if len(result) < int(n):
        # fallback — добиваємо одиночними (рідко, але надійно)
        while len(result) < int(n):
            result.append(generate_unique_code(db, Model, field_name, length, alphabet))
    return result
