from operator import or_
from app.common.exceptions import BusinessException
from app.common.response import PageResponse
from app.models.equipment import Equipment
from app.models.lab import Lab
from app.schemas.equipment import (
    EquipmentResponse,
    EquipmentCreateRequest,
    EquipmentUpdateRequest,
)
from sqlalchemy.orm import Session


def get_equipment_page_list(
    db: Session,  # 数据库会话
    page: int,  # 页码，从1开始
    page_size: int,  # 每页条数
    keywords: str | None = None,  # 设备名称搜索关键词
    lab_id: int | None = None,  # 筛选所属实验室ID
):
    """分页模糊查询列表"""
    # select * from equipment where name like '%计算机%';
    query = db.query(Equipment)
    if lab_id:
        query = query.filter(Equipment.lab_id == lab_id)
    if keywords:
        query = query.filter(Equipment.name.ilike(f"%{keywords}%"))
    total = query.count()

    # 这里的 `item` 是 SQLAlchemy 的 ORM 对象（盒子，靠 `.xxx` 拿属性）。
    items = (
        query.order_by(Equipment.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    result = []

    # [ORM 对象 1, ORM 对象 2 ...] 转换为响应对象，[EquipmentResponse 对象1, EquipmentResponse 对象2 ...]
    for item in items:
        res = EquipmentResponse.model_validate(item)
        res.lab_name = item.lab.name if item.lab else None
        result.append(res)
    return PageResponse(list=result, total=total)


def create_equipment(db: Session, data: EquipmentCreateRequest):
    """新增"""
    exist = db.query(Equipment).filter(Equipment.name == data.name).first()
    if exist:
        raise BusinessException(message="实验室设备已存在")

    # 把请求模型转成字典，给SQLAlchemy ORM新建对象（EquipmentCreateRequest → dict → ORM 对象）
    # data.model_dump() 会把 lab_id 一起打包，赋值给 Equipment.lab_id，外键建立，relationship lab 就可以正常关联查到实验室。
    equipment = Equipment(**data.model_dump())

    db.add(equipment)
    db.commit()
    db.refresh(equipment)

    # 把ORM对象转为返回给前端的响应模型（这里依赖 from_attributes=True）
    res = EquipmentResponse.model_validate(equipment)

    # 返回时，实验设备信息增加所属实验室名称返回给前端
    res.lab_name = equipment.lab.name if equipment.lab else None
    return res


def update_equipment(db: Session, equipment_id: int, data: EquipmentUpdateRequest):
    """更新设备信息"""
    # 1. 根据设备id查出这条设备记录
    equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not equipment:
        raise BusinessException(message="实验室设备不存在")

    # 2. model_dump(exclude_none=True)：只拿前端传过来、不为None的字段
    # 意思：前端不传的字段，不参与更新，保留原来数据库的值
    payload = data.model_dump(exclude_none=True)

    # 取出要更新后的 lab_id 和 name；如果 payload 里没传，沿用旧值
    lab_id = payload.get("lab_id", equipment.lab_id)
    name = payload.get("name", equipment.name)

    # 3. 校验目标实验室是否真实存在
    lab = db.query(Lab).filter(Lab.id == lab_id).first()
    if not lab:
        raise BusinessException(message="实验室不存在")

    # 4. 查重校验：【同一个实验室下不能重名】
    exist = (
        db.query(Equipment)
        .filter(
            Equipment.lab_id == lab_id,  # 在目标实验室
            Equipment.name == name,  # 设备名字一样
            Equipment.id != equipment_id,  # 排除自己本身这条记录！重点！
        )
        .first()
    )
    if exist:
        raise BusinessException(message="同一个实验室不能存在同名的设备")

    # 5. 循环把前端传来的字段批量赋值到ORM对象上
    for filed, value in payload.items():
        setattr(equipment, filed, value)

    # 提交事务、刷新数据
    db.commit()
    db.refresh(equipment)

    # 组装返回对象
    res = EquipmentResponse.model_validate(equipment)
    res.lab_name = equipment.lab.name if equipment.lab else None
    return res


def delete_equipment(db: Session, equipment_id: int):
    """删除"""
    equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not equipment:
        raise BusinessException(message="实验室设备不存在")
    db.delete(equipment)
    db.commit()
