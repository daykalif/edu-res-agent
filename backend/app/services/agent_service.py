"""
通过LangGraph实现Tool Calling
"""

from langchain_openai import ChatOpenAI
from sqlalchemy.orm import Session
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.common.exceptions import BusinessException
from app.models.user import User
from app.schemas.ai import ChatRequest
from app.services import agent_tools
from app.config import settings
from collections.abc import AsyncIterator
from typing import Any

# 工具英文名 → 页面上给人看的中文过程文案
TOOL_LABELS = {
    "search_lab_docs": "检索实验室知识库",
    "list_open_labs": "查询开放实验室",
    "list_lab_equipments": "查询实验室设备",
    "create_lab_reservation": "提交预约",
    "get_today": "获取今天日期",
}


SYSTEM_PROMPT = """你是智能实验室预约系统的 Agent，回答要简洁。

你可以：
1. 使用 search_lab_docs 查询实验室的规则、安全、开放时间等问题
2. 使用 list_open_labs / list_lab_equipments  查询真实的实验室和设备
3. 在用户进行了预约确认后，使用 create_lab_reservation 来进行真实的预约落库
4. 使用 get_today 来进行日期的换算

## 必须遵守
当用户提到了 今天、明天、后天 等日期相关的问题，请先调用 get_today 来获取日期，**不要直接返回 我需要确定明天的具体日期**。

在提交预约之前必须向用户复述：实验室ID与名称（或设备ID和名称）、日期、开始时间、结束时间。并得到用户确认再进行实际操作。
用户没说【确认】【确认预约】【就这样预约】等确定性回复之前，不要调用 create_lab_reservation。
工作流的确认环节里如果缺少了 lab_id，请先 list_open_labs 查到了 lab_id 再创建，不要瞎写。
工作流的确认环节里如果缺少了 equipment_id，请先 list_lab_equipments 查到了 equipment_id 再创建，不要瞎写。

预约成功后状态是待审核，必须管理员确认后实验室（或设备）才能使用。
不要瞎编数据库里没有的实验室或者设备信息。
如果是问开放时间或者实验室规则，优先调用 search_lab_docs，不要凭空回复。
"""

# 工具英文名 → 页面上给人看的中文过程文案
TOOL_LABELS = {
    "search_lab_docs": "检索实验室知识库",
    "list_open_labs": "查询开放实验室",
    "list_lab_equipments": "查询实验室设备",
    "create_lab_reservation": "提交预约",
    "get_today": "获取今天日期",
}


# 工作流编排
def build_agent(db: Session, current_user: User):
    # 定义工具
    tools = agent_tools.build_tools(db, current_user)

    # 创建LLM实例
    llm = ChatOpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        model=settings.LLM_MODEL,
        temperature=0,  # 模型温度，调高会生成更多、更Creative的输出；数字越小，输出越 deterministic
        streaming=True,  # 开启流式输出，astream_events 才能收到逐字返回的 token
    ).bind_tools(
        tools
    )  # 把工具描述注册给大模型，让模型知道有哪些工具、参数是什么，有能力输出 tool_call。

    # agent_node：LLM 思考节点，接收当前所有对话消息，调用模型，返回模型输出。
    async def agent_node(state: MessagesState):
        """langGraph 执行的工作流 的节点"""
        response = await llm.ainvoke(state["messages"])
        return {"messages": [response]}

    graph = StateGraph(MessagesState)  # 初始化工作流实例
    graph.add_node("agent", agent_node)  # 调用大模型的节点
    graph.add_node("tools", ToolNode(tools))  # tool call的节点
    graph.add_edge(START, "agent")  # 流程的起点，call LLM
    # 看有无tool_call，有就继续call，没有就END 输出
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")  # 让agent看tool调用的结果
    return graph.compile()


# 历史会话组装
def _build_history(data: ChatRequest) -> list:
    """前端只传 user/assistant 文本，转成 LangChain 消息对象。"""
    history = []
    for message in data.messages or []:
        if message.role == "user" and message.content.strip():
            history.append(HumanMessage(content=message.content.strip()))
        elif message.role == "assistant" and message.content.strip():
            history.append(AIMessage(content=message.content.strip()))
    if not history:
        raise BusinessException(message="请输入您要对话的内容")
    return history


# 工具结果预览
def _tool_output_preview(output: Any, limit: int = 200) -> str:  # 默认截取200个字符展示
    """把工具结果收成短预览，避免整段 JSON 刷到前端过程区。"""
    # LangGraph 里工具结果经常是 ToolMessage，正文在 .content
    if isinstance(output, ToolMessage):
        output = output.content
    # output 有可能是 dict -> str  \"{"aaa":"123"}"\
    text = output if isinstance(output, str) else str(output)
    # 太长就截断，末尾加省略号
    return text if len(text) <= limit else text[:limit] + "…"


def _chunk_text(chunk: Any) -> str:
    """从模型流式 chunk 里抠出纯文本。

    content 有时是 str，有时是 [{type, text}, ...] 这种块列表，要统一成字符串。
    """
    if chunk is None:
        return ""
    # chunk 可能是 AIMessageChunk，真正字在 .content
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(part.get("text") or "")
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
    return str(content) if content is not None else ""


# 【流式输出】
async def stream_agent(
    db: Session, current_user: User, data: ChatRequest  # data:前端传过来的聊天请求
) -> AsyncIterator[dict]:  # 返回：异步迭代器（async for 去循环拿数据，也就是 yield）
    """生成器：边跑 Agent 边 yield 事件，供 SSE 推给前端。

    事件类型：status / tool_start / tool_end / token / done / error
    """
    try:
        # 把前端传的对话消息，组装成 LangChain 消息对象列表（HumanMessage/AIMessage）
        history = _build_history(data)
        # 根据当前用户、数据库，构造你的 LangGraph Agent 图实例（Manager-Worker 那套 Agent）
        agent = build_agent(db, current_user)
        # 组装输入：系统提示词 + 用户历史对话。  *history：把列表拆开，和 SystemMessage 拼成完整 messages
        inputs = {"messages": [SystemMessage(content=SYSTEM_PROMPT), *history]}

        # yield 先交出这一条，生成器暂停，调用方再次取值时继续执行
        yield {"type": "status", "message": "正在思考…"}

        # astream_events：图每走一步（调工具、吐字）都会冒出一个内部事件
        async for event in agent.astream_events(
            inputs,
            version="v2",
            config={"recursion_limit": 10},  # 图执行步数上限，防 agent⇄tools 空转
        ):
            print("event:", event.get("event"), event.get("name"))
            kind = event.get("event")
            if kind == "on_tool_start":
                """
                分支 1：on_tool_start → Agent 准备调用工具
                yield 给前端：工具名字、中文标签（TOOL_LABELS 是一个字典，把内部工具名翻译成前端展示用的中文）
                前端可以渲染：🔧 正在调用【检索实验室知识库】这种提示。
                """
                name = event.get("name") or ""
                yield {
                    "type": "tool_start",
                    "name": name,
                    "label": TOOL_LABELS.get(name, name),  # 没有中文映射就退回英文名
                }
            elif kind == "on_tool_end":
                """
                分支 2：on_tool_end → 工具执行完毕，拿到返回结果

                - _tool_output_preview：对工具返回的原始结果做截断、精简预览
                - ⚠️ 重点注释：只给前端预览！完整原始数据不会推前端，完整数据留在 Agent 图内部的 messages 里，继续给大模型后续推理使用，前端看不到原始全部返回，省流量、防泄露。
                """
                name = event.get("name") or ""
                yield {
                    "type": "tool_end",
                    "name": name,
                    "label": TOOL_LABELS.get(name, name),
                    # 只给预览；完整结果仍在图内部 messages 里给模型用
                    "preview": _tool_output_preview(
                        (event.get("data") or {}).get("output")
                    ),
                }
            elif kind == "on_chat_model_stream":
                """
                分支 3：`on_chat_model_stream` → 模型输出文字流
                这里做了一个**过滤逻辑**：
                LangGraph 图里可能有很多节点（子 agent、工具节点），很多节点也会触发模型调用。
                `langgraph_node != "agent"` 的直接跳过，**只把主 agent 节点吐出的文字发给前端**，避免子 Agent 内部思考、中间草稿这些噪声文字乱飘到页面上。
                `_chunk_text`：对文字块做清洗（比如剔除空白、特殊标记），有文字就吐出 `token` 事件，前端逐字拼接渲染打字效果。
                """

                # 只收 agent 节点的字；其它内部节点的噪声丢掉
                meta = event.get("metadata") or {}
                if meta.get("langgraph_node") not in (None, "agent"):
                    continue
                text = _chunk_text((event.get("data") or {}).get("chunk"))
                if text:
                    yield {"type": "token", "content": text}

        # 正常跑完：不要在 done 里再带一份全文，前端已经用 token 拼好了
        yield {"type": "done"}
    except BusinessException as exc:
        # 流已经是 SSE，错误也要用 yield，别 raise 成普通 JSON
        yield {"type": "error", "message": exc.message}
    except Exception:
        yield {"type": "error", "message": "大模型调用失败，请稍后重试"}


# 【一次性返回】对外暴露的业务入口（胶水层）；职责：接收前端对话请求、消息格式转换、调用 Agent 图、捕获异常、提取最终模型文本返回给前端。
def run_agent(db: Session, current_user: User, data: ChatRequest):
    """大模型对话"""
    if not data.messages:
        raise BusinessException(message="对话内容为空")

    # 构建历史会话
    history = _build_history(data)
    agent = build_agent(db, current_user)
    try:
        result = agent.invoke(
            {"messages": [SystemMessage(content=SYSTEM_PROMPT), *history]},
            # 图执行步数上限（agent、tools 每执行一次各算一步）
            config={"recursion_limit": 10},
        )
    except BusinessException:
        raise
    except Exception:
        raise BusinessException(message="大模型调用失败，请稍后重试")

    messages = result.get("messages") or []

    if not messages:
        raise BusinessException(message="大模型没有任何返回内容")

    for message in reversed(messages):
        if isinstance(message, AIMessage) and message.content.strip():
            """
            一段代码是做兼容兜底的，专门解决一个坑：

            新版 OpenAI / 兼容接口（Qwen、DeepSeek 等）里，**AIMessage 的 content 不再一定是纯字符串，还可以是数组格式（多模态结构）**
            示例这种结构：
                content = [
                    {"type": "text", "text": "你预约的实验室是A实验室"},
                ]

            而不是简单的：
                content = "你预约的实验室是A实验室"
            """

            content = message.content.strip()

            """
            1. `if isinstance(content, list)`：判断 content 是不是列表
            2. 遍历列表里每一个 `part`：
                - 如果 part 是字典：取它的 `text` 字段，拿不到就为空字符串 `""`
                - 如果 part 不是字典：直接转成字符串
            3. `"".join(...)`：把所有文本片段拼接成一整个字符串
            """
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            # 接完成后，去掉首尾空白；非空才返回，避免返回空白内容给前端。
            if str(content).strip():
                return str(content).strip()
