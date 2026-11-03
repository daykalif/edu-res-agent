from pydantic import BaseModel, ConfigDict


class UserResponse(BaseModel):
    id: int
    username: str
    name: str
    role: str
    phone: str | None = None
    email: str | None = None
    status: int
    # 用于告诉Pydantic从数据库对象中获取属性值
    model_config = ConfigDict(from_attributes=True)
