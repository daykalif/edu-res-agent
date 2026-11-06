import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.common.response import Response
from app.database import SessionLocal, get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.ai import ChatMessage, ChatRequest
from app.services import agent_service, ai_service

router = APIRouter(prefix="/ai", tags=["AI相关的API"])


@router.post("/chat")
def chat(
    data: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """调用手工编写的工具"""
    # content = ai_service.chat(db, data)
    # return Response.success(data=ChatMessage(role="assistant", content=content))

    """调用通过LangGraph实现的工具"""
    content = agent_service.run_agent(db, current_user, data)
    return Response.success(data=ChatMessage(role="assistant", content=content))


def _sse_line(payload: dict) -> str:
    """拼一条 SSE 帧，以空行结束。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# 流式输出
@router.post("/chat/stream")
async def chat_stream(
    data: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    # 只保存标量 ID，不把鉴权依赖中的 ORM 对象交给流式工具。
    user_id = current_user.id

    async def event_gen():
        # 生成器开始执行时才创建会话，流结束或取消时关闭。
        with SessionLocal() as db:
            stream_user = db.get(User, user_id)
            # 鉴权完成后账号仍可能被删除或禁用，执行工具前再次核对。
            if stream_user is None or stream_user.status != 1:
                yield _sse_line(
                    {"type": "error", "message": "用户不存在或已被禁用，请重新登录"}
                )
                return
            async for event in agent_service.stream_agent(db, stream_user, data):
                yield _sse_line(event)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",  # 告诉浏览器这是 SSE 流
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Nginx 避免整段响应
        },
    )
