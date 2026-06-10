"""
agent.py - LangChain Agent 封装
使用 LangChain 的 OpenAI Tools Agent 架构，对接硅基流动 API
包含：工具调用、RAG 检索注入、对话窗口记忆
"""
import os
import json
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain.tools import Tool, StructuredTool
from langchain.memory import ConversationBufferWindowMemory
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import SystemMessage
from pydantic import BaseModel, Field

from rag import search as rag_search

# ── LLM 配置 ──────────────────────────────────────────────────────────────────

def build_llm(model: str) -> ChatOpenAI:
    """构建 LangChain LLM，对接硅基流动 OpenAI 兼容接口"""
    import httpx
    return ChatOpenAI(
        model=model,
        openai_api_key=os.getenv("AI_API_KEY", ""),
        openai_api_base=os.getenv("AI_BASE_URL", "https://api.siliconflow.cn/v1"),
        temperature=0.8,
        max_tokens=1500,
        http_async_client=httpx.AsyncClient(trust_env=False),
    )


# ── 工具 Schema ───────────────────────────────────────────────────────────────

class SearchWebInput(BaseModel):
    query: str = Field(description="搜索关键词，建议用中文或英文简洁描述")


class QueryUserDataInput(BaseModel):
    data_type: str = Field(
        description="profile=基本档案信息，fortune_history=近期运势记录，astral_detail=完整星盘行星数据",
    )


# ── 工具构建 ──────────────────────────────────────────────────────────────────

def build_tools(context: dict) -> list:
    """
    构建 LangChain Tool 列表
    context 包含 profile、session、user，用于 query_user_data 工具
    """

    def search_web_sync(query: str) -> str:
        try:
            import httpx as _httpx
            resp = _httpx.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10.0,
            )
            data = resp.json()
            parts = []
            if data.get("AbstractText"):
                parts.append(data["AbstractText"])
            for topic in data.get("RelatedTopics", [])[:3]:
                if isinstance(topic, dict) and topic.get("Text"):
                    parts.append(topic["Text"])
            return "\n".join(parts) if parts else f"未找到「{query}」的即时结果。"
        except Exception as e:
            return f"搜索失败: {e}"

    def query_user_data_impl(data_type: str) -> str:
        from tools import _query_user_data
        return _query_user_data(data_type, context)

    search_tool = StructuredTool.from_function(
        func=search_web_sync,
        name="search_web",
        description="搜索互联网获取实时信息，适用于：当前星象/行星位置、天文事件、节气、最新占星资讯等需要实时数据的问题",
        args_schema=SearchWebInput,
    )

    query_tool = StructuredTool.from_function(
        func=query_user_data_impl,
        name="query_user_data",
        description="查询当前用户的个人数据，适用于：用户询问自己的星盘详情、历史运势记录、个人档案信息等",
        args_schema=QueryUserDataInput,
    )

    return [search_tool, query_tool]


# ── 记忆管理 ──────────────────────────────────────────────────────────────────

# 按 user_id + profile_id 缓存 Memory 对象，实现跨请求的 session 记忆
# 进程级 session 缓存，服务重启后清空；多进程/多实例部署时需改为 Redis 等共享存储
_memory_store: dict = {}


def get_session_memory(user_id: int, profile_id: int) -> ConversationBufferWindowMemory:
    """
    获取或创建该用户+档案的对话窗口记忆
    ConversationBufferWindowMemory 保留最近 k 轮对话，自动丢弃更早的内容
    """
    key = f"{user_id}_{profile_id}"
    if key not in _memory_store:
        _memory_store[key] = ConversationBufferWindowMemory(
            k=10,
            memory_key="chat_history",
            return_messages=True,
        )
    return _memory_store[key]


def clear_session_memory(user_id: int, profile_id: int):
    """清除指定用户的 session 记忆（用于退出登录或手动清除）"""
    key = f"{user_id}_{profile_id}"
    _memory_store.pop(key, None)


def sync_history_to_memory(
    memory: ConversationBufferWindowMemory,
    history_logs: list,
):
    """
    将数据库中的历史对话同步到 LangChain Memory
    只在 memory 为空时执行，避免重复添加
    """
    if memory.chat_memory.messages:
        return
    for log in history_logs:
        if log.role == "user":
            memory.chat_memory.add_user_message(log.content)
        else:
            memory.chat_memory.add_ai_message(log.content)


# ── Agent 构建与调用 ──────────────────────────────────────────────────────────

def build_agent_executor(
    system_prompt: str,
    model: str,
    context: dict,
    memory: ConversationBufferWindowMemory,
) -> AgentExecutor:
    """
    构建 LangChain AgentExecutor
    使用 OpenAI Tools Agent（支持并行工具调用）
    """
    llm = build_llm(model)
    tools = build_tools(context)

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])

    agent = create_openai_tools_agent(llm, tools, prompt)

    return AgentExecutor(
        agent=agent,
        tools=tools,
        memory=memory,
        verbose=False,
        max_iterations=3,  # 防止模型陷入工具调用死循环
        handle_parsing_errors=True,
        return_intermediate_steps=False,
    )


async def run_agent(
    user_message: str,
    system_prompt: str,
    model: str,
    context: dict,
    history_logs: list,
    rag_query: str = "",
) -> str:
    """
    主入口：运行 LangChain Agent
    1. RAG 检索注入 system prompt
    2. 同步历史记录到 Memory
    3. 执行 Agent（支持工具调用）
    4. 返回 AI 回复文本
    """
    # RAG 检索注入
    rag_hit = False
    if rag_query:
        relevant_docs = rag_search(rag_query)
        if relevant_docs:
            rag_context = "\n\n【知识库参考】\n" + "\n---\n".join(relevant_docs)
            system_prompt = system_prompt + rag_context
            rag_hit = True

    user_id = context.get("user").id if context.get("user") else 0
    profile_id = context.get("profile").id if context.get("profile") else 0

    memory = get_session_memory(user_id, profile_id)
    sync_history_to_memory(memory, history_logs)

    executor = build_agent_executor(system_prompt, model, context, memory)

    try:
        result = await executor.ainvoke({"input": user_message})
        output = result.get("output", "")
        if rag_hit:
            output = output + "\n\n📚 参考了知识库"
        return output
    except Exception as e:
        # 降级：直接调用 LLM 不带工具
        llm = build_llm(model)
        from langchain_core.messages import HumanMessage, SystemMessage as SM
        msgs = [SM(content=system_prompt), HumanMessage(content=user_message)]
        resp = await llm.ainvoke(msgs)
        output = resp.content
        if rag_hit:
            output = output + "\n\n📚 参考了知识库"
        return output
