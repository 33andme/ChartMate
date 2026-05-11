"""
database.py - MySQL 数据库连接配置 (SQLModel + SQLAlchemy)
"""
import os
from sqlmodel import SQLModel, create_engine, Session
from dotenv import load_dotenv

load_dotenv()

# ─── 数据库连接字符串 ────────────────────────────────────────────────────────────
# 从 .env 文件读取，若未配置则使用默认值
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "root")
DB_NAME = os.getenv("DB_NAME", "astro_app")

DATABASE_URL = (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    "?charset=utf8mb4"
)

# ─── 创建引擎 ────────────────────────────────────────────────────────────────────
engine = create_engine(
    DATABASE_URL,
    echo=False,           # 生产环境设为 False，调试时改为 True
    pool_pre_ping=True,   # 自动检测断开的连接
    pool_recycle=3600,    # 每小时回收连接，防止 MySQL 8h 超时断连
    pool_size=10,
    max_overflow=20,
)


def create_db_and_tables():
    """在应用启动时创建所有表（如果不存在）"""
    SQLModel.metadata.create_all(engine)


def get_session():
    """FastAPI 依赖注入：提供数据库 Session"""
    with Session(engine) as session:
        yield session
