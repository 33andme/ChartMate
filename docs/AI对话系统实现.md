# AI 对话系统实现

## 涉及文件
- `agent.py` — LangChain Agent 封装
- `tools.py` — 工具定义与执行
- `memory.py` — 用户 AI 记忆模块
- `rag.py` — 知识库检索
- `main.py` — `/api/chat` 接口（第 1019-1121 行）

---

## 整体流程

```
用户发送消息
  ↓
main.py: POST /api/chat
  ↓
1. 读取档案星盘 → 构建 System Prompt（astro_utils.build_astro_system_prompt）
2. 读取用户 AI 记忆 → 追加到 System Prompt（memory.get_user_memories）
3. 读取最近 10 条历史对话（chat_logs 表）
  ↓
agent.py: run_agent()
  ├── RAG 检索：用用户消息在向量库中搜索相关知识（rag.search）
  ├── 同步历史到 LangChain Memory（sync_history_to_memory）
  └── 执行 AgentExecutor（最多 3 轮工具调用）
  ↓
返回 AI 回复
  ↓
main.py: 存储对话到 chat_logs 表
  ↓
asyncio.create_task: 后台异步提取记忆（memory.extract_and_save_memories）
```

---

## 1. System Prompt 构建

**文件：`astro_utils.py` → `build_astro_system_prompt()`**

将用户档案的星盘数据（太阳/月亮/上升星座、全部行星落座）格式化成 Markdown，注入到 system prompt 开头，让 AI 以占星师身份回答。

追加内容（来自 `memory.py → build_memory_prompt()`）：
```
【关于用户的记忆】
- [偏好] 用户喜欢看感情运势
- [人物] 用户男友是双子座
```

---

## 2. LangChain Agent（`agent.py`）

使用 **OpenAI Tools Agent** 架构，对接硅基流动 OpenAI 兼容接口。

### 模型配置（`build_llm()`，第 22 行）
```python
ChatOpenAI(
    model=model,
    openai_api_key=AI_API_KEY,
    openai_api_base="https://api.siliconflow.cn/v1",
    temperature=0.8,
    max_tokens=1500,
)
```

### Prompt 模板（`build_agent_executor()`，第 153 行）
```
[system]       ← 星盘数据 + 记忆
[chat_history] ← LangChain Memory 中的历史对话
[human]        ← 本轮用户消息
[agent_scratchpad] ← 工具调用中间步骤
```

### 对话记忆（`get_session_memory()`，第 100 行）
- 使用 `ConversationBufferWindowMemory(k=10)` 保留最近 10 轮
- 以 `user_id + profile_id` 为 key 存储在进程内存 `_memory_store` 中
- 新会话首次加载时从数据库历史同步（`sync_history_to_memory()`）

---

## 3. 工具调用（`tools.py` + `agent.py`）

Agent 可调用两个工具：

### search_web（`tools.py` 第 57 行）
调用 DuckDuckGo 即时答案 API（无需 Key），用于：
- 查询当前星象/行星位置
- 天文事件、节气
- 最新占星资讯

### query_user_data（`tools.py` 第 83 行）
从请求 context 中读取用户数据，支持三种查询类型：
| data_type | 返回内容 |
|-----------|---------|
| `profile` | 姓名、出生城市、MBTI 等基本信息 |
| `astral_detail` | 完整星盘 JSON（所有行星度数） |
| `fortune_history` | 最近 7 天运势历史记录 |

---

## 4. RAG 知识库注入（`rag.py` + `agent.py` 第 191 行）

```python
relevant_docs = rag_search(rag_query)  # 向量相似度检索，返回前3条
if relevant_docs:
    system_prompt += "\n\n【知识库参考】\n" + "\n---\n".join(relevant_docs)
```

检索到相关知识时，回复末尾追加 `📚 参考了知识库` 标记。

---

## 5. 异步记忆提取（`memory.py` 第 51 行）

每次对话结束后，`main.py` 用 `asyncio.create_task` 在后台异步运行：

1. 取最近 6 条对话
2. 调用 AI 接口（轻量模型 Qwen3-8B）提取值得记住的信息
3. 返回结构化 JSON：`[{"type": "entity|preference|fact", "content": "..."}]`
4. 去重后写入 `user_memories` 表

记忆类型：
- `entity`：人物关系（"用户男友是双子座"）
- `preference`：偏好习惯（"用户不喜欢太长的回答"）
- `fact`：重要事实（"用户今年25岁"）

---

## 6. 降级机制

| 场景 | 降级行为 |
|------|---------|
| AgentExecutor 执行失败 | 直接调用 LLM，不带工具（`agent.py` 第 212 行） |
| AI_API_KEY 未配置 | 返回模拟回复（`main.py _mock_ai_response()`） |
| RAG 向量库为空 | 跳过知识库注入 |
