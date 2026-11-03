from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.utils.jwt import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

"""
访问：GET /api/user/info
传入auth：Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
"""


def get_current_user(
    token: str = Depends(
        oauth2_scheme
    ),  # 就会提取 Authorization: Bearer eyJhbGciOiJIUzI1NiIs...，拿到token
    db: Session = Depends(get_db),
) -> User:
    """JWT token 鉴权验证合法性"""
    try:
        payload = decode_access_token(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效，请重新登录"
        )

    # 获取到用户ID
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的登录凭证"
        )

    # 从数据库根据用户ID查询用户信息
    user = db.query(User).filter(User.id == user_id).first()

    # Token 有效不代表账号仍存在，查不到用户时拒绝本次访问。
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在，请重新登录",
        )

    # 账号状态判断
    if user.status != 1:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户被禁用"
        )

    return user
