from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.common.response import PageResponse
from app.models.lab import Lab
from app.schemas.lab import LabCreateRequest, LabResponse, LabUpdateRequest


def get_lab_page_list(
    db: Session, page: int, page_size: int, keywords: str | None = None
):
    query = db.query(Lab)
    if keywords:
        query = query.filter(
            or_(Lab.name.ilike(f"%{keywords}%"), Lab.location.ilike(f"%{keywords}%"))
        )
    total = query.count()

    # 这里的 `item` 是 SQLAlchemy 的 ORM 对象（盒子，靠 `.id`、`.name` 拿属性）。
    items = (
        query.order_by(Lab.id.desc())  # 按照 Lab 的 id 倒序排序（新的数据排在前面）
        .offset((page - 1) * page_size)  # 跳过前面多少条：计算本页之前已经跳过的数据量
        .limit(page_size)  # 限制最多取出 page_size 条，也就是一页条数
        .all()  # 执行查询，拿到全部结果列表
    )
    return PageResponse(
        # items 是 [ORM 对象 1, ORM 对象 2 ...]，循环后变成 [LabResponse 对象 1, LabResponse 对象 2 ...]
        list=[LabResponse.model_validate(item) for item in items],
        total=total,
    )


"""
代码解析：
1. 前端 → FastAPI
    前端发的是 JSON 字符串（比如 `{"name":"A实验室","capacity":20}`）
    FastAPI 自动把 JSON 解析成字典，再喂给 `LabCreateRequest`，变成 Pydantic 请求模型实例（Python 对象）

    > 
    > 👉 这一步：JSON → dict → LabCreateRequest

2. 存数据库
    调用 `data.model_dump()`：把 LabCreateRequest 转成 dict
    `Lab(**dict)`：用这个字典，创建 SQLAlchemy ORM 对象
    `db.add / commit`：ORM 最终变成数据库里的一行记录

    > 
    > 👉 这一步：Pydantic 请求模型 → dict → ORM 对象 → 数据库行

3. 查出来、返回前端
    数据库查出 ORM 对象
    `LabResponse.model_validate(lab)`：依靠 `from_attributes=True`，把 ORM 对象 → LabResponse 响应模型（Pydantic 对象）
    FastAPI 最后自动把 LabResponse 再序列化回 JSON 丢给前端

    > 
    > 👉 这一步：数据库行 → ORM 对象 → LabResponse → JSON
"""


# 前端JSON → 通过fastapi转为dict → 通过LabCreateRequest转为LabCreateRequest对象
def create_lab(db: Session, data: LabCreateRequest):
    # 查询：有没有同名的实验室。 .first() 拿到第一个结果
    exists = db.query(Lab).filter(Lab.name == data.name).first()
    if exists:
        raise BusinessException(message="实验室名称已存在")

    # 把请求模型转成字典，给SQLAlchemy ORM新建对象（LabCreateRequest → dict → ORM 对象）
    lab = Lab(**data.model_dump())

    db.add(lab)  # 加入会话，标记待新增
    db.commit()  # 提交事务，写入数据库
    db.refresh(lab)  # 从数据库刷新这个对象（拿回数据库自动生成的id等）

    # 把ORM对象转为返回给前端的响应模型（这里依赖 from_attributes=True）
    return LabResponse.model_validate(lab)


def update_lab(db: Session, lab_id: int, data: LabUpdateRequest):
    lab = db.query(Lab).filter(Lab.id == lab_id).first()
    if not lab:
        raise BusinessException(message="实验室不存在")

    # 把 Pydantic 的 `data`（你的 `LabUpdateRequest`）转成字典，值是 `None` 的字段直接丢掉，不放进字典里。
    payload = data.model_dump(exclude_none=True)

    if "name" in payload:
        exists = (
            db.query(Lab).filter(Lab.name == payload["name"], Lab.id != lab_id).first()
        )
        if exists:
            raise BusinessException(message="实验室名称已存在")

    for field, value in payload.items():
        setattr(lab, field, value)
    db.commit()
    db.refresh(lab)
    return LabResponse.model_validate(lab)


def delete_lab(db: Session, lab_id: int):
    lab = db.query(Lab).filter(Lab.id == lab_id).first()
    if not lab:
        raise BusinessException(message="实验室不存在")
    db.delete(lab)
    db.commit()
