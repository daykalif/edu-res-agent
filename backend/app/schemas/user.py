from pydantic import BaseModel, ConfigDict


class UserResponse(BaseModel):
    id: int
    username: str
    name: str
    role: str
    phone: str | None = None
    email: str | None = None
    avatar: str | None = None
    status: int
    # 用于告诉Pydantic从数据库对象中获取属性值
    model_config = ConfigDict(from_attributes=True)


# 定义用户信息更新
class UserUpdateRequest(BaseModel):
    name: str | None = None
    password: str | None = None  # 管理员编辑用户时可选修改密码；为空时保持原密码不变。
    role: str | None = None
    phone: str | None = None
    email: str | None = None
    avatar: str | None = None
    status: int | None = None


# 定义用户密码更新的请求参数
class PasswordUpdateRequest(BaseModel):
    old_password: str
    new_password: str
