"""
auth.py - 认证逻辑
- 邮箱验证码注册/登录
- JWT Token 签发与验证
- 测试环境固定验证码: 123456
"""
import os
import random
import string
from datetime import datetime, timedelta
from typing import Optional, Tuple

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

# passlib 1.7.x 访问 bcrypt.__about__.__version__，bcrypt 4.x 删除了该属性；打补丁兼容
import bcrypt as _bcrypt
if not hasattr(_bcrypt, '__about__'):
    _bcrypt.__about__ = type('_about', (), {'__version__': _bcrypt.__version__})()
from sqlmodel import Session, select

from database import get_session
from models import User, VerifyCode

# ── 配置 ────────────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "astro-secret-key-change-in-production-2024")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24 * 7  # 7天有效期
IS_TEST_ENV = os.getenv("ENV", "test") == "test"  # 测试环境使用固定验证码
FIXED_TEST_CODE = "123456"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


# ══════════════════════════════════════════════════════════════════════════════
# 密码工具
# ══════════════════════════════════════════════════════════════════════════════

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# ══════════════════════════════════════════════════════════════════════════════
# JWT Token
# ══════════════════════════════════════════════════════════════════════════════

def create_access_token(user_id: int, email: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """解码 Token，返回 payload；失败则抛异常"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ══════════════════════════════════════════════════════════════════════════════
# 依赖注入：获取当前用户
# ══════════════════════════════════════════════════════════════════════════════

def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
) -> User:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(token)
    user_id = int(payload.get("sub", 0))
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


def get_optional_user(
    token: Optional[str] = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
) -> Optional[User]:
    """可选认证，未登录返回 None"""
    if not token:
        return None
    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub", 0))
        return session.get(User, user_id)
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 验证码逻辑
# ══════════════════════════════════════════════════════════════════════════════

def generate_verify_code() -> str:
    """生成6位数字验证码"""
    if IS_TEST_ENV:
        return FIXED_TEST_CODE
    return "".join(random.choices(string.digits, k=6))


def send_verify_code(email: str, session: Session) -> str:
    """
    发送验证码（生产环境将通过邮件发送）
    """
    # 每次发码前清除旧记录，避免同一邮箱积累多条有效验证码
    old_codes = session.exec(
        select(VerifyCode).where(VerifyCode.email == email)
    ).all()
    for old in old_codes:
        session.delete(old)

    code = generate_verify_code()
    expires_at = datetime.utcnow() + timedelta(minutes=10)

    verify_code = VerifyCode(
        email=email,
        code=code,
        expires_at=expires_at,
        is_used=False,
    )
    session.add(verify_code)
    session.commit()

    # 发送验证码邮件
    from email_service import send_verification_code_email
    success = send_verification_code_email(email, code)

    if not success and not IS_TEST_ENV:
        # 如果非测试环境下发送失败，记录错误但不抛出异常
        print(f"⚠️ 发送验证码邮件失败: {email}")

    return code  # 测试环境返回 code


def validate_verify_code(email: str, code: str, session: Session) -> bool:
    """验证验证码是否正确且未过期"""
    # 打印调试信息
    print(f"DEBUG: 验证码检查 - 邮箱: {email}, 验证码: {code}")

    # 标准化验证码（去除空格、转为大写）
    code = code.strip()

    # 查询最新的验证码记录
    record = session.exec(
        select(VerifyCode)
        .where(VerifyCode.email == email)
        .order_by(VerifyCode.id.desc())
    ).first()

    # 无记录
    if not record:
        print(f"DEBUG: 未找到验证码记录 - {email}")
        return False

    print(f"DEBUG: 找到验证码记录 - 存储的验证码: {record.code}, 是否已使用: {record.is_used}, 过期时间: {record.expires_at}")

    # 已使用
    if record.is_used:
        print(f"DEBUG: 验证码已使用 - {email}")
        return False

    # 已过期
    if datetime.utcnow() > record.expires_at:
        print(f"DEBUG: 验证码已过期 - {email}")
        return False

    # 验证码不匹配
    if record.code != code:
        print(f"DEBUG: 验证码不匹配 - 输入:{code} vs 存储:{record.code}")
        return False

    # 验证通过，标记为已使用
    record.is_used = True
    session.add(record)
    session.commit()
    print(f"DEBUG: 验证码验证成功 - {email}")
    return True


# ══════════════════════════════════════════════════════════════════════════════
# 注册 / 登录 核心逻辑
# ══════════════════════════════════════════════════════════════════════════════

def register_or_login_with_code(
    email: str,
    code: str,
    session: Session,
) -> Tuple[User, str, bool]:
    """
    邮箱验证码 注册/登录 二合一
    Returns: (user, token, is_new_user)
    """
    # 1. 验证验证码
    if not validate_verify_code(email, code, session):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码错误或已过期",
        )

    # 2. 查找或创建用户
    user = session.exec(select(User).where(User.email == email)).first()
    is_new_user = False

    if not user:
        # 新用户注册：用验证码作为初始密码哈希，首次登录后可凭此验证码重置
        user = User(
            email=email,
            password_hash=hash_password(code),
            created_at=datetime.utcnow(),
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        is_new_user = True

    # 3. 签发 Token
    token = create_access_token(user.id, user.email)
    return user, token, is_new_user


# ══════════════════════════════════════════════════════════════════════════════
# 新版：注册/登录 分离
# ══════════════════════════════════════════════════════════════════════════════

def register_user(
    email: str,
    code: str,
    password: str,
    session: Session,
) -> Tuple[User, str]:
    """注册新用户：验证码 + 密码"""
    existing = session.exec(select(User).where(User.email == email)).first()
    if existing:
        raise HTTPException(status_code=400, detail="该邮箱已注册，请直接登录")

    if not validate_verify_code(email, code, session):
        raise HTTPException(status_code=400, detail="验证码错误或已过期")

    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码不能少于6位")

    user = User(
        email=email,
        password_hash=hash_password(password),
        created_at=datetime.utcnow(),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    token = create_access_token(user.id, user.email)
    return user, token


def login_with_password(
    email: str,
    password: str,
    session: Session,
) -> Tuple[User, str]:
    """密码登录：邮箱 + 密码"""
    user = session.exec(select(User).where(User.email == email)).first()
    if not user:
        raise HTTPException(status_code=400, detail="该邮箱未注册，请先注册")
    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=400, detail="密码错误")
    token = create_access_token(user.id, user.email)
    return user, token
