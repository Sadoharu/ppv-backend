from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import AdminUser
from backend.schemas.admin_users import AdminUserCreate, AdminUserResponse, AdminUserUpdate
from backend.services.authn.passwords import hash_password
from backend.api.deps import require_admin

# Цей роутер буде доступний ТІЛЬКИ для super-адміна
router = APIRouter(
    prefix="/admins",
    tags=["admin:management"],
    dependencies=[Depends(require_admin("super"))]
)

@router.get("/", response_model=List[AdminUserResponse])
def list_admins(db: Session = Depends(get_db)):
    """Показати всіх адміністраторів системи."""
    # Сортуємо по ID
    admins = db.query(AdminUser).order_by(AdminUser.id.asc()).all()
    return admins

@router.post("/", response_model=AdminUserResponse, status_code=status.HTTP_201_CREATED)
def create_admin(
    payload: AdminUserCreate,
    db: Session = Depends(get_db)
):
    """Створити нового адміністратора."""
    # 1. Перевірка чи існує email
    existing = db.query(AdminUser).filter(AdminUser.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Admin with this email already exists"
        )

    # 2. Створення
    new_user = AdminUser(
        email=payload.email,
        role=payload.role,
        hashed_password=hash_password(payload.password)
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return new_user

@router.patch("/{user_id}", response_model=AdminUserResponse)
def update_admin(
    user_id: int,
    payload: AdminUserUpdate,
    db: Session = Depends(get_db),
    # Отримуємо поточного адміна, щоб не дати йому знизити власні права або заблокувати себе
    current_admin: AdminUser = Depends(require_admin("super"))
):
    """Оновити роль або пароль адміністратора."""
    target_user = db.get(AdminUser, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Захист: не можна змінювати роль самому собі через цей ендпоінт (щоб випадково не втратити доступ)
    # Хоча супер-адмін може це зробити, краще попередити.
    if target_user.id == current_admin.id and payload.role and payload.role != "super":
        raise HTTPException(status_code=400, detail="Cannot demote yourself via API. Ask another super-admin.")

    if payload.email:
        # Перевірка на унікальність, якщо міняємо email
        existing = db.query(AdminUser).filter(AdminUser.email == payload.email).first()
        if existing and existing.id != user_id:
             raise HTTPException(status_code=400, detail="Email already taken")
        target_user.email = payload.email

    if payload.role:
        target_user.role = payload.role
    
    if payload.password:
        target_user.hashed_password = hash_password(payload.password)

    db.commit()
    db.refresh(target_user)
    return target_user

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_admin(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_admin("super"))
):
    """Видалити адміністратора."""
    if user_id == current_admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself.")

    target_user = db.get(AdminUser, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    db.delete(target_user)
    db.commit()
    return None