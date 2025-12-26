from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional

class AdminUserBase(BaseModel):
    email: EmailStr
    role: str = Field(..., description="Role: super, admin, manager, support, analyst")

    @field_validator('role')
    def validate_role(cls, v):
        allowed_roles = {"super", "admin", "manager", "support", "analyst"}
        if v not in allowed_roles:
            raise ValueError(f"Role must be one of: {', '.join(allowed_roles)}")
        return v

class AdminUserCreate(AdminUserBase):
    password: str = Field(..., min_length=8, description="Minimum 8 characters")

class AdminUserUpdate(BaseModel):
    """Схема для часткового оновлення (PATCH)."""
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    password: Optional[str] = Field(None, min_length=8)

    @field_validator('role')
    def validate_role(cls, v):
        if v is None:
            return v
        allowed_roles = {"super", "admin", "manager", "support", "analyst"}
        if v not in allowed_roles:
            raise ValueError(f"Role must be one of: {', '.join(allowed_roles)}")
        return v

class AdminUserResponse(AdminUserBase):
    id: int
    name: Optional[str] = None  # Додано опціональне поле name
    
    class Config:
        from_attributes = True