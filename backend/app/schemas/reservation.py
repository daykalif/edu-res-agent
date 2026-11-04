from pydantic import BaseModel


# user_id 不需要让前端传，api层直接可以获取当前登录用户。
class ReservationCreateRequest(BaseModel):
    lab_id: int
    equipment_id: int | None = None
    date: str
    start_time: str
    end_time: str
    remark: str | None = None
