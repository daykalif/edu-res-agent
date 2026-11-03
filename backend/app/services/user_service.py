from app.common.exceptions import BusinessException
from app.models.user import User
from app.schemas.user import PasswordUpdateRequest, UserResponse, UserUpdateRequest
from sqlalchemy.orm import Session

from app.utils.password import hash_password, verify_password

"""
1. `User`：一般是 **SQLAlchemy 的数据库模型**，里面可能包含敏感字段：`password`、`secret`、内部字段等
2. `UserResponse`：你自己定义的 Pydantic 输出模型，**只保留前端需要展示的字段**（比如 id、昵称、邮箱、头像，不返回密码）
3. `model_validate(user)`
   - Pydantic v2 的方法（替代老版 `parse_obj`）
   - 从 `user` 对象里读取属性，自动映射到 `UserResponse` 的字段
   - 自动做类型校验、格式化
   - ✅ 核心价值：**脱敏！把密码这类敏感字段过滤掉，不返回给前端**
"""


def get_user_info(user: User) -> UserResponse:
    return UserResponse.model_validate(user)


def update_user_info(db: Session, user: User, data: UserUpdateRequest):
    user_dict = data.model_dump(exclude_none=True)  # pydatic对象 → 字典
    for field, value in user_dict.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return UserResponse.model_validate(user)  # 字典 → Pydantic对象


def update_password(db: Session, user: User, data: PasswordUpdateRequest):
    if not verify_password(data.old_password, user.password):
        raise BusinessException(message="原密码错误")
    if data.old_password == data.new_password:
        raise BusinessException(message="新密码不能与原密码相同")
    user.password = hash_password(data.new_password)
    db.commit()
