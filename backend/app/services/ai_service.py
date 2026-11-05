from openai import OpenAI
from app.common.exceptions import BusinessException
from app.config import settings
from app.schemas.ai import ChatMessage, ChatRequest
from app.services import kb_service

SYSTEM_PROMPT = """你是智能实验室预约系统的助手，回答要简洁。
如果下面提供了实验室资料，请依据资料回答，不要编造资料里没有的时间、规则、设备。
你目前查不到真实的实验室空闲、设备库存、预约记录。
如果用户问现在哪些实验室能约、某台设备此刻有没有空，请说明去「实验室列表」查看。
除了实验室相关的问题之外，不要回复无关的问题。
"""


def get_client() -> OpenAI:
    """创建OPENAI的客户端"""
    if not settings.LLM_API_KEY:
        raise BusinessException(message="未获取到大模型的API Key")
    return OpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL)


def chat(data: ChatRequest):
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

    print(f"检索到的最相关2条向量库的内容---ai_service--->：\n{knowledge}")

    system_prompt = SYSTEM_PROMPT
    if knowledge:
        system_prompt += "\n\n ----- 以下是检索到的实验室的资料：-----\n" + knowledge

    client = get_client()

    try:
        # 创建对话
        res = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                # 系统提示词
                {"role": "system", "content": system_prompt},
                # 对话上下文
                *history,
            ],
        )

        # 大模型返回结果
        content = res.choices[0].message.content

        if not content.strip():
            raise BusinessException(message="大模型没有返回内容")

        return content
    except Exception:
        raise BusinessException(message="大模型调用失败，请稍后重试")
