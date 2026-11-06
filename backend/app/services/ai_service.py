"""
手工编写大模型对话 + Tool Calling
"""

import traceback
from openai import OpenAI
from app.common.exceptions import BusinessException
from app.config import settings
from app.schemas.ai import ChatMessage, ChatRequest
import json
from sqlalchemy.orm import Session
from app.services import kb_service, equipment_service, lab_service
from openai.types.chat import ChatCompletionToolParam

SYSTEM_PROMPT = """你是智能实验室预约系统的助手，回答要简洁。
如果下面提供了实验室资料，请依据资料回答规则、安全、文档里的开放时间说明。
查询当前有哪些开放实验室、某实验室有哪些设备时，必须调用工具，不要编造。
你不能替用户提交预约，也不能直接改数据库。
如果用户要预约，请说明去「实验室列表」选择后提交，等待管理员审核。
"""

TOOLS: list[ChatCompletionToolParam] = [
    {
        "type": "function",
        "function": {
            "name": "list_open_labs",
            "description": "查询当前开放中的实验室列表，可以按名称关键字来筛选",
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {
                        "type": "string",
                        "description": "实验室的名称关键字，可以为空",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_lab_equipments",
            "description": "查询某个实验室下的设备列表",
            "parameters": {
                "type": "object",
                "properties": {
                    "lab_id": {
                        "type": "integer",
                        "description": "实验室 ID",
                    },
                    "keywords": {
                        "type": "string",
                        "description": "设备名称的关键字，可以为空",
                    },
                },
            },
        },
    },
]


# name: 工具名称，arguments: 工具参数
def run_tool(db: Session, name: str, arguments: str) -> str:
    """运行工具"""

    # 解析参数
    try:
        # json.loads: 将json字符串转为字典
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        # json.dumps: 将字典转为json字符串
        return json.dumps({"error": "参数不是合法的json"}, ensure_ascii=False)

    try:
        if name == "list_open_labs":
            keywords = (args.get("keywords") or "").strip() or None
            page = lab_service.get_lab_page_list(
                db, page=1, page_size=10, keywords=keywords, status=1
            )
            rows = [
                {
                    "id": item.id,
                    "name": item.name,
                    "location": item.location,
                    "capacity": item.capacity,
                    "open_time": item.open_time,
                    "close_time": item.close_time,
                }
                for item in page.list
            ]
            return json.dumps({"total": page.total, "labs": rows}, ensure_ascii=False)

        if name == "list_lab_equipments":
            lab_id = args.get("lab_id")
            if not lab_id:
                return json.dumps(
                    {"error": "参数缺少实验室 lab_id"}, ensure_ascii=False
                )

            keywords = (args.get("keywords") or "").strip() or None
            page = equipment_service.get_equipment_page_list(
                db, page=1, page_size=10, lab_id=int(lab_id), keywords=keywords
            )
            rows = [
                {
                    "id": item.id,
                    "name": item.name,
                    "lab_id": item.lab_id,
                    "lab_name": item.lab_name,
                    "spec": item.spec,
                    "quantity": item.quantity,
                    "status": item.status,
                }
                for item in page.list
            ]
            return json.dumps(
                {"total": page.total, "equipments": rows}, ensure_ascii=False
            )

        return json.dumps({"error": f"未找到工具：{name}"}, ensure_ascii=False)

    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def get_client() -> OpenAI:
    """创建OPENAI的客户端"""
    if not settings.LLM_API_KEY:
        raise BusinessException(message="未获取到大模型的API Key")
    return OpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL)


def chat(db: Session, data: ChatRequest):
    """大模型对话"""
    if not data.messages:
        raise BusinessException(message="对话内容为空")

    history = []
    for message in data.messages:
        if message.role in ("user", "assistant") and message.content.strip():
            history.append(message.model_dump())
    if not history:
        raise BusinessException(message="请输入您要对话的内容")

    # 从历史消息倒序查找，拿到最近一条用户提问；找不到就返回空字符串
    question = next(
        (item["content"] for item in reversed(history) if item["role"] == "user"), ""
    )
    # 从向量库检索
    knowledge = kb_service.search(query=question)

    print("--------------------------------------------------------------------")
    print(f"检索到的最相关2条向量库的内容（前2条）---ai_service--->：\n{knowledge}")
    print("--------------------------------------------------------------------")

    system_prompt = SYSTEM_PROMPT
    if knowledge:
        system_prompt += "\n\n以下是检索到的实验室的资料：\n" + knowledge

    client = get_client()

    messages = [
        # 系统提示词
        {"role": "system", "content": system_prompt},
        # 对话上下文
        *history,
    ]

    try:
        for _ in range(3):
            # 模型判断要不要调用工具
            res = client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
            )

            # 大模型返回结果
            msg = res.choices[0].message
            tool_calls = msg.tool_calls or []

            # 没有工具调用时，直接返回大模型文本结果
            if not tool_calls:
                content = msg.content
                if not content or not content.strip():
                    raise BusinessException(message="大模型没有返回内容")
                return content

            # 有工具调用时，告诉大模型需要调用哪些工具
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments,
                            },
                        }
                        for call in tool_calls
                    ],
                }
            )

            # 逐个执行工具、追加tool运行结果到聊天上下文
            for call in tool_calls:
                result = run_tool(db, call.function.name, call.function.arguments)
                messages.append(
                    {"role": "tool", "content": result, "tool_call_id": call.id}
                )
    except Exception:
        traceback.print_exc()
        raise BusinessException(message="大模型调用失败，请稍后重试")
