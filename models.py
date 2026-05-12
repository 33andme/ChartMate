"""
models.py - 数据库模型定义 (SQLModel)
严格按照设计文档定义所有表结构
"""
from datetime import datetime, date
from typing import Optional, List
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import Text, UniqueConstraint
import json


# ══════════════════════════════════════════════════════════════════════════════
# 1. Auth & User
# ══════════════════════════════════════════════════════════════════════════════

class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True, max_length=255)
    password_hash: str = Field(max_length=255)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # 用于 sqladmin 显示
    def __str__(self):
        return self.email


# ══════════════════════════════════════════════════════════════════════════════
# 2. Astrology Core - 档案与星盘
# ══════════════════════════════════════════════════════════════════════════════

class Profile(SQLModel, table=True):
    __tablename__ = "profiles"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    is_self: bool = Field(default=False, description="是否是账号本人的档案")
    name: str = Field(max_length=50)
    relationship: str = Field(default="本人", max_length=20,
                               description="如: 本人、伴侣、父母、朋友")
    birth_city: str = Field(max_length=100)
    current_city: str = Field(max_length=100)
    birth_time: datetime = Field(description="出生时间，含日期+时分")
    timezone: str = Field(default="Asia/Shanghai", max_length=50)
    gender: Optional[str] = Field(default=None, max_length=10)
    mbti: Optional[str] = Field(default=None, max_length=10)
    # 存储星盘 JSON，包括行星落座、宫位等
    astral_config: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="星盘 JSON 字符串"
    )

    def get_astral_config(self) -> dict:
        if self.astral_config:
            return json.loads(self.astral_config)
        return {}

    def __str__(self):
        return f"{self.name} ({self.relationship})"


# ══════════════════════════════════════════════════════════════════════════════
# 3. Daily Fortune - 每日运势缓存
# ══════════════════════════════════════════════════════════════════════════════

class DailyFortune(SQLModel, table=True):
    __tablename__ = "daily_fortunes"

    id: Optional[int] = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="profiles.id", index=True)
    fortune_date: date = Field(description="运势日期")
    # scores: {"overall": 85, "love": 72, "wealth": 90, "career": 68, "study": 80, "social": 75}
    scores: str = Field(
        sa_column=Column(Text, nullable=False),
        description="6个维度分数 JSON"
    )
    # content: {"advice": "...", "avoid": "...", "lucky_color": "红色", "lucky_number": 8}
    content: str = Field(
        sa_column=Column(Text, nullable=False),
        description="运势建议内容 JSON"
    )

    def get_scores(self) -> dict:
        if isinstance(self.scores, str):
            return json.loads(self.scores)
        return self.scores or {}

    def get_content(self) -> dict:
        if isinstance(self.content, str):
            return json.loads(self.content)
        return self.content or {}


# ══════════════════════════════════════════════════════════════════════════════
# 4. AI Chat - 对话记录
# ══════════════════════════════════════════════════════════════════════════════

class ChatLog(SQLModel, table=True):
    __tablename__ = "chat_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    profile_id: int = Field(foreign_key="profiles.id", index=True)
    role: str = Field(max_length=10, description="'user' or 'ai'")
    content: str = Field(sa_column=Column(Text, nullable=False))
    model_version: str = Field(default="free", max_length=20,
                                description="ai model version")
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ══════════════════════════════════════════════════════════════════════════════
# 5. Community - 社区
# ══════════════════════════════════════════════════════════════════════════════

class Post(SQLModel, table=True):
    __tablename__ = "posts"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    content: str = Field(sa_column=Column(Text, nullable=False))
    # images: ["https://...", "https://..."]
    images: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="图片URL列表 JSON"
    )
    like_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def get_images(self) -> list:
        if isinstance(self.images, str):
            return json.loads(self.images)
        return self.images or []

    def __str__(self):
        return f"Post#{self.id}"


class Comment(SQLModel, table=True):
    __tablename__ = "comments"

    id: Optional[int] = Field(default=None, primary_key=True)
    post_id: int = Field(foreign_key="posts.id", index=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    content: str = Field(max_length=500)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PostLike(SQLModel, table=True):
    __tablename__ = "post_likes"
    __table_args__ = (
        UniqueConstraint("user_id", "post_id", name="uq_user_post_like"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    post_id: int = Field(foreign_key="posts.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ══════════════════════════════════════════════════════════════════════════════
# 6. 验证码缓存 (内存/简单表，测试环境固定 123456)
# ══════════════════════════════════════════════════════════════════════════════

class VerifyCode(SQLModel, table=True):
    __tablename__ = "verify_codes"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(max_length=255, index=True)
    code: str = Field(max_length=10)
    expires_at: datetime = Field()
    is_used: bool = Field(default=False)


# ══════════════════════════════════════════════════════════════════════════════
# 7. 用户聊天系统
# ══════════════════════════════════════════════════════════════════════════════

class ChatRoom(SQLModel, table=True):
    """聊天室表：记录两个用户之间的聊天室"""
    __tablename__ = "chat_rooms"
    __table_args__ = (
        UniqueConstraint("user1_id", "user2_id", name="uq_chat_room_users"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user1_id: int = Field(foreign_key="users.id", index=True)  # 用户1 ID（较小的ID）
    user2_id: int = Field(foreign_key="users.id", index=True)  # 用户2 ID（较大的ID）
    last_message_at: Optional[datetime] = Field(default=None)  # 最后一条消息时间
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def __str__(self):
        return f"ChatRoom({self.user1_id}-{self.user2_id})"


class ChatMessage(SQLModel, table=True):
    """聊天消息表：具体的消息内容"""
    __tablename__ = "chat_messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    room_id: int = Field(foreign_key="chat_rooms.id", index=True)
    sender_id: int = Field(foreign_key="users.id", index=True)
    message_type: str = Field(default="text", max_length=20)  # text, image 等
    content: str = Field(sa_column=Column(Text))
    is_read: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def __str__(self):
        return f"Message({self.sender_id}: {self.content[:30]}...)"


# ══════════════════════════════════════════════════════════════════════════════
# 9. 用户 AI 记忆
# ══════════════════════════════════════════════════════════════════════════════

class UserMemory(SQLModel, table=True):
    __tablename__ = "user_memories"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    profile_id: Optional[int] = Field(default=None, foreign_key="profiles.id", index=True)
    memory_type: str = Field(max_length=20, description="entity / preference / fact")
    content: str = Field(sa_column=Column(Text), description="记忆内容，自然语言描述")
    source_summary: str = Field(default="", sa_column=Column(Text), description="提取来源的对话摘要")
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def __str__(self):
        return f"[{self.memory_type}] {self.content[:40]}"


# ══════════════════════════════════════════════════════════════════════════════
# 8. RAG 知识库文档记录
# ══════════════════════════════════════════════════════════════════════════════

class KnowledgeDoc(SQLModel, table=True):
    __tablename__ = "knowledge_docs"

    id: Optional[int] = Field(default=None, primary_key=True)
    filename: str = Field(max_length=255)
    file_type: str = Field(max_length=20, description="pdf, docx, txt")
    chunk_count: int = Field(default=0, description="切块数量")
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)
    uploaded_by: str = Field(default="admin", max_length=50)

    def __str__(self):
        return self.filename
