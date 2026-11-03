from pydantic import BaseModel

from app.schemas.user import UserResponse


class LoginRequest(BaseModel):
    username: str
    password: str


# 定义登录返回参数
class LoginResponse(BaseModel):
    token: str
    user: UserResponse


# 定义注册请求参数
class RegisterRequest(BaseModel):
    username: str
    password: str
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    confirmPassword: str | None = None
