from pydantic import BaseModel, ConfigDict


class EquipmentResponse(BaseModel):
    id: int
    lab_id: int
    lab_name: str | None = None  # 列表要显示实验室名称，所以 Response 多一个 lab_name
    name: str
    description: str | None = None
    img: str | None = None
    spec: str | None = None
    quantity: int
    status: int

    model_config = ConfigDict(from_attributes=True)


class EquipmentCreateRequest(BaseModel):
    lab_id: int  # 所属实验室ID，绑定实验室的核心
    name: str
    description: str | None = None
    img: str | None = None
    spec: str | None = None
    quantity: int = 1
    status: int = 1


class EquipmentUpdateRequest(BaseModel):
    lab_id: int | None = None
    name: str | None = None
    description: str | None = None
    img: str | None = None
    spec: str | None = None
    quantity: int | None = None
    status: int | None = None
