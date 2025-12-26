from pydantic import BaseModel, EmailStr, constr

class LoginRequest(BaseModel):
    code: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class AdminLogin(BaseModel):
    email: EmailStr
    password: constr(min_length=6)

class AdminToken(BaseModel):
    access_token: str