"""
memory.py - 用户 AI 记忆模块
负责：从对话中提取记忆、注入记忆到 system prompt、管理记忆的增删改查
记忆严格按 user_id 隔离，不同用户之间完全不可见
"""
import json
import os
import asyncio
from datetime import datetime
from typing import Optional

import httpx
from sqlmodel import Session, select

AI_CHAT_URL = os.getenv("AI_CHAT_URL", "https://api.siliconflow.cn/v1/chat/completions")
AI_API_KEY = os.getenv("AI_API_KEY", "")
EXTRACT_MODEL = os.getenv("AI_FREE_MODEL", "Qwen/Qwen3-8B")

# 每次注入的最大记忆条数
MAX_MEMORIES_INJECT = 15


def get_user_memories(session: Session, user_id: int, profile_id: Optional[int] = None):
    """获取用户的所有记忆，按更新时间倒序"""
    from models import UserMemory
    query = select(UserMemory).where(UserMemory.user_id == user_id)
    if profile_id:
        # 返回通用记忆（profile_id=None）+ 该档案专属记忆
        from sqlalchemy import or_
        query = query.where(
            or_(UserMemory.profile_id == None, UserMemory.profile_id == profile_id)
        )
    query = query.order_by(UserMemory.updated_at.desc()).limit(MAX_MEMORIES_INJECT)
    return session.exec(query).all()


def build_memory_prompt(memories) -> str:
    """将记忆列表格式化为注入 system prompt 的文本段落"""
    if not memories:
        return ""

    lines = []
    type_labels = {"entity": "关系/人物", "preference": "偏好", "fact": "重要事实"}
    for m in memories:
        label = type_labels.get(m.memory_type, m.memory_type)
        lines.append(f"- [{label}] {m.content}")

    return "\n\n【关于用户的记忆】\n" + "\n".join(lines)


async def extract_and_save_memories(
    user_id: int,
    profile_id: Optional[int],
    conversation: list,
    db_url: str,
):
    """
    异步提取对话中的记忆并保存到数据库
    在后台任务中运行，不阻塞 API 响应
    conversation: [{"role": "user/assistant", "content": "..."}]
    """
    if not AI_API_KEY or len(conversation) < 2:
        return

    # 只取最近 6 条对话用于提取，避免 token 浪费
    recent = conversation[-6:]
    conv_text = "\n".join(
        f"{'用户' if m['role'] == 'user' else 'AI'}: {m['content']}"
        for m in recent
        if m.get("role") in ("user", "assistant")
    )

    prompt = f"""从以下对话中提取值得长期记住的用户信息。
只提取明确说出的信息，不要推断或猜测。

对话内容：
{conv_text}

请返回 JSON 数组，每项格式：
{{"type": "entity|preference|fact", "content": "简洁的一句话描述"}}

- entity：人物关系（如"用户男友是双子座"、"用户妈妈是处女座"）
- preference：偏好习惯（如"用户喜欢看感情运势"、"用户不喜欢太长的回答"）
- fact：重要事实（如"用户最近在找工作"、"用户今年25岁"）

如果没有值得记忆的信息，返回空数组 []。
只返回 JSON，不要其他文字。"""

    try:
        headers = {
            "Authorization": f"Bearer {AI_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": EXTRACT_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 500,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(AI_CHAT_URL, headers=headers, json=payload)
            if resp.status_code != 200:
                return
            raw = resp.json()["choices"][0]["message"]["content"].strip()

        # 解析 JSON，兼容 markdown 代码块包裹的情况
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        items = json.loads(raw.strip())
        if not isinstance(items, list) or not items:
            return

    except Exception:
        return

    # 写入数据库
    from sqlalchemy import create_engine
    from sqlmodel import Session as DBSession
    engine = create_engine(db_url)
    with DBSession(engine) as sess:
        from models import UserMemory
        for item in items:
            mem_type = item.get("type", "fact")
            content = item.get("content", "").strip()
            if not content or mem_type not in ("entity", "preference", "fact"):
                continue

            # 检查是否已有相似记忆（简单去重：内容前20字相同则更新）
            existing = sess.exec(
                select(UserMemory)
                .where(UserMemory.user_id == user_id)
                .where(UserMemory.memory_type == mem_type)
            ).all()

            duplicate = next(
                # 前20字相同视为同一条记忆，更新而非新增，防止语义重复积累
                (m for m in existing if content[:20] in m.content or m.content[:20] in content),
                None
            )
            if duplicate:
                duplicate.content = content
                duplicate.updated_at = datetime.utcnow()
                sess.add(duplicate)
            else:
                sess.add(UserMemory(
                    user_id=user_id,
                    profile_id=profile_id,
                    memory_type=mem_type,
                    content=content,
                    source_summary=conv_text[:200],
                ))
        sess.commit()
