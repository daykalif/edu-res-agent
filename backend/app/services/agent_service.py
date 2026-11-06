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


def build_agent(db: Session, current_user: User):
    # 定义工具
    tools = agent_tools.build_tools(db, current_user)

    # 创建LLM实例
    llm = ChatOpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        model=settings.LLM_MODEL,
        temperature=0,  # 模型温度，调高会生成更多、更Creative的输出；数字越小，输出越 deterministic
    ).bind_tools(
        tools
    )  # 把工具描述注册给大模型，让模型知道有哪些工具、参数是什么，有能力输出 tool_call。

    # agent_node：LLM 思考节点，接收当前所有对话消息，调用模型，返回模型输出。
    def agent_node(state: MessagesState):
        """langGraph 执行的工作流 的节点"""
        response = llm.invoke(state["messages"])
        return {"messages": [response]}

    graph = StateGraph(MessagesState)  # 初始化工作流实例
    graph.add_node("agent", agent_node)  # 调用大模型的节点
    graph.add_node("tools", ToolNode(tools))  # tool call的节点
    graph.add_edge(START, "agent")  # 流程的起点，call LLM
    # 看有无tool_call，有就继续call，没有就END 输出
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")  # 让agent看tool调用的结果
    return graph.compile()


# 对外暴露的业务入口（胶水层）；职责：接收前端对话请求、消息格式转换、调用 Agent 图、捕获异常、提取最终模型文本返回给前端。
def run_agent(db: Session, current_user: User, data: ChatRequest):
    """大模型对话"""
    if not data.messages:
        raise BusinessException(message="对话内容为空")

    history = []
    for message in data.messages:
        if message.role == "user" and message.content.strip():
            history.append(HumanMessage(content=message.content.strip()))
        elif message.role == "assistant" and message.content.strip():
            history.append(AIMessage(content=message.content.strip()))
    if not history:
        raise BusinessException(message="请输入您要对话的内容")

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
