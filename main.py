"""
main.py - FastAPI 主应用
包含所有 API 路由 + sqladmin 后台管理
"""
import json
import os
import asyncio
from datetime import datetime, date
from typing import Optional, List

import httpx
from fastapi import FastAPI, Depends, HTTPException, status, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr
from sqlmodel import Session, select
from sqlalchemy.exc import IntegrityError

# Admin
from sqladmin import Admin, ModelView, BaseView, expose
from sqladmin.authentication import AuthenticationBackend

from database import create_db_and_tables, engine, get_session
from models import User, Profile, DailyFortune, ChatLog, Post, Comment, PostLike, VerifyCode, ChatRoom, ChatMessage, KnowledgeDoc, UserMemory
from auth import (
    get_current_user, get_optional_user,
    send_verify_code,
    create_access_token, hash_password,
    register_user, login_with_password,
)
from astro_utils import calculate_chart, build_astro_system_prompt, generate_fortune_by_astro
from rag import search as rag_search, add_document, delete_document, extract_text, get_chunks
from tools import TOOL_DEFINITIONS, execute_tool
from memory import get_user_memories, build_memory_prompt, extract_and_save_memories
from agent import run_agent

# ── 应用初始化 ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="占星 APP API",
    description="简易版测测 - 占星命盘系统",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件（前端页面）
os.makedirs("static", exist_ok=True)
os.makedirs("uploads", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


@app.on_event("startup")
def on_startup():
    create_db_and_tables()
    print("✅ 数据库表创建/确认完毕")


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN PANEL - sqladmin 后台
# ══════════════════════════════════════════════════════════════════════════════

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = form.get("username")
        password = form.get("password")
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            request.session.update({"token": "admin-authenticated"})
            return True
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return request.session.get("token") == "admin-authenticated"


admin = Admin(
    app,
    engine,
    authentication_backend=AdminAuth(secret_key=os.getenv("SECRET_KEY", "astro-admin-secret")),
    title="占星APP后台",
    base_url="/admin",
)


class UserAdmin(ModelView, model=User):
    column_list = [User.id, User.email, User.is_vip, User.vip_expiry, User.created_at]
    column_searchable_list = [User.email]
    column_sortable_list = [User.id, User.created_at, User.is_vip]
    column_filters = [User.is_vip]
    name = "用户管理"
    name_plural = "用户列表"
    icon = "fa-solid fa-users"

    async def delete_model(self, request, pk):
        """级联删除用户及其全部关联数据，绕过 MySQL 外键约束"""
        from sqlmodel import Session as DBSession
        with DBSession(engine) as sess:
            uid = int(pk)

            # 1. 对话记录
            for item in sess.exec(select(ChatLog).where(ChatLog.user_id == uid)).all():
                sess.delete(item)

            # 2. 本人发帖的点赞 & 评论（先清子表再删帖）
            for post in sess.exec(select(Post).where(Post.user_id == uid)).all():
                for like in sess.exec(select(PostLike).where(PostLike.post_id == post.id)).all():
                    sess.delete(like)
                for cmt in sess.exec(select(Comment).where(Comment.post_id == post.id)).all():
                    sess.delete(cmt)
                sess.delete(post)

            # 3. 用户在别人帖子上的点赞 & 评论
            for item in sess.exec(select(PostLike).where(PostLike.user_id == uid)).all():
                sess.delete(item)
            for item in sess.exec(select(Comment).where(Comment.user_id == uid)).all():
                sess.delete(item)

            # 4. 档案及其每日运势
            for profile in sess.exec(select(Profile).where(Profile.user_id == uid)).all():
                for fortune in sess.exec(
                    select(DailyFortune).where(DailyFortune.profile_id == profile.id)
                ).all():
                    sess.delete(fortune)
                sess.delete(profile)

            # 5. 验证码记录
            user_obj = sess.get(User, uid)
            if user_obj:
                for vc in sess.exec(
                    select(VerifyCode).where(VerifyCode.email == user_obj.email)
                ).all():
                    sess.delete(vc)

            sess.commit()

        # 最后调用父类删除 User 本身
        await super().delete_model(request, pk)


class ProfileAdmin(ModelView, model=Profile):
    column_list = [Profile.id, Profile.user_id, Profile.name, Profile.relationship,
                   Profile.birth_city, Profile.birth_time, Profile.is_self]
    column_searchable_list = [Profile.name]
    column_sortable_list = [Profile.id, Profile.user_id]
    name = "档案管理"
    name_plural = "档案列表"
    icon = "fa-solid fa-id-card"

    async def delete_model(self, request, pk):
        """删档案前先清掉运势缓存和对话记录"""
        from sqlmodel import Session as DBSession
        with DBSession(engine) as sess:
            pid = int(pk)
            for item in sess.exec(select(DailyFortune).where(DailyFortune.profile_id == pid)).all():
                sess.delete(item)
            for item in sess.exec(select(ChatLog).where(ChatLog.profile_id == pid)).all():
                sess.delete(item)
            sess.commit()
        await super().delete_model(request, pk)


class PostAdmin(ModelView, model=Post):
    column_list = [Post.id, Post.user_id, Post.content, Post.like_count, Post.created_at]
    column_sortable_list = [Post.id, Post.like_count, Post.created_at]
    name = "帖子管理"
    name_plural = "社区帖子"
    icon = "fa-solid fa-newspaper"

    async def delete_model(self, request, pk):
        """删帖前先清掉点赞和评论子记录"""
        from sqlmodel import Session as DBSession
        with DBSession(engine) as sess:
            pid = int(pk)
            for item in sess.exec(select(PostLike).where(PostLike.post_id == pid)).all():
                sess.delete(item)
            for item in sess.exec(select(Comment).where(Comment.post_id == pid)).all():
                sess.delete(item)
            sess.commit()
        await super().delete_model(request, pk)


class ChatLogAdmin(ModelView, model=ChatLog):
    column_list = [ChatLog.id, ChatLog.user_id, ChatLog.role, ChatLog.model_version, ChatLog.created_at]
    column_sortable_list = [ChatLog.id, ChatLog.created_at]
    name = "对话记录"
    name_plural = "AI对话记录"
    icon = "fa-solid fa-comments"


class DailyFortuneAdmin(ModelView, model=DailyFortune):
    column_list = [DailyFortune.id, DailyFortune.profile_id, DailyFortune.fortune_date]
    column_sortable_list = [DailyFortune.id, DailyFortune.fortune_date]
    name = "运势缓存"
    name_plural = "每日运势"
    icon = "fa-solid fa-star"


_KNOWLEDGE_UPLOAD_HTML = """
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>知识库管理</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
body {{ background: #f8f9fa; }}
.container {{ max-width: 860px; margin: 40px auto; }}
.card {{ border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,.08); }}
.badge-type {{ font-size: .75rem; }}
</style>
</head>
<body>
<div class="container">
  <div class="d-flex align-items-center mb-4 gap-3">
    <a href="/admin" class="btn btn-outline-secondary btn-sm"><i class="fa fa-arrow-left"></i> 返回后台</a>
    <h4 class="mb-0"><i class="fa-solid fa-book me-2 text-primary"></i>知识库管理</h4>
  </div>

  {alert}

  <div class="card mb-4">
    <div class="card-header fw-bold">上传文档</div>
    <div class="card-body">
      <form method="post" action="/admin/knowledge/upload" enctype="multipart/form-data">
        <div class="mb-3">
          <label class="form-label">选择文件（支持 PDF / DOCX / TXT）</label>
          <input type="file" name="file" class="form-control" accept=".pdf,.docx,.doc,.txt" required>
        </div>
        <button type="submit" class="btn btn-primary"><i class="fa fa-upload me-1"></i>上传并入库</button>
      </form>
    </div>
  </div>

  <div class="card">
    <div class="card-header fw-bold">已入库文档（{doc_count} 个）</div>
    <div class="card-body p-0">
      <table class="table table-hover mb-0">
        <thead class="table-light">
          <tr>
            <th>文件名</th><th>类型</th><th>切块数</th><th>上传时间</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          {rows}
        </tbody>
      </table>
    </div>
  </div>
</div>
</body>
</html>
"""


class KnowledgeAdmin(BaseView):
    name = "知识库管理"
    icon = "fa-solid fa-book"

    @expose("/knowledge", methods=["GET"])
    async def a_list(self, request: Request):
        from fastapi.responses import RedirectResponse
        if not request.session.get("token") == "admin-authenticated":
            return RedirectResponse("/admin/login")

        from sqlmodel import Session as DBSession
        with DBSession(engine) as sess:
            docs = sess.exec(select(KnowledgeDoc).order_by(KnowledgeDoc.uploaded_at.desc())).all()

        alert = request.query_params.get("msg", "")
        alert_html = ""
        if alert:
            cls = "success" if "成功" in alert else "danger"
            alert_html = f'<div class="alert alert-{cls}">{alert}</div>'

        rows = ""
        for d in docs:
            rows += (
                f"<tr>"
                f"<td><a href='/admin/knowledge/chunks/{d.id}' class='text-decoration-none'>{d.filename}</a></td>"
                f"<td><span class='badge bg-secondary badge-type'>{d.file_type.upper()}</span></td>"
                f"<td>{d.chunk_count}</td>"
                f"<td>{d.uploaded_at.strftime('%Y-%m-%d %H:%M')}</td>"
                f"<td>"
                f"<a href='/admin/knowledge/chunks/{d.id}' class='btn btn-sm btn-outline-primary me-1'><i class='fa fa-eye'></i></a>"
                f"<form method='post' action='/admin/knowledge/delete' style='display:inline'>"
                f"<input type='hidden' name='doc_id' value='{d.id}'>"
                f"<button class='btn btn-sm btn-outline-danger' onclick=\"return confirm('确认删除？')\"><i class='fa fa-trash'></i></button>"
                f"</form>"
                f"</td>"
                f"</tr>"
            )
        if not rows:
            rows = "<tr><td colspan='5' class='text-center text-muted py-4'>暂无文档，请上传第一个文件</td></tr>"

        html = _KNOWLEDGE_UPLOAD_HTML.format(
            alert=alert_html, doc_count=len(docs), rows=rows
        )
        return HTMLResponse(html)

    @expose("/knowledge/chunks/{doc_id}", methods=["GET"])
    async def b_chunks(self, request: Request):
        from fastapi.responses import RedirectResponse
        if not request.session.get("token") == "admin-authenticated":
            return RedirectResponse("/admin/login")

        doc_id = request.path_params.get("doc_id")
        from sqlmodel import Session as DBSession
        with DBSession(engine) as sess:
            doc = sess.get(KnowledgeDoc, int(doc_id))
        if not doc:
            return RedirectResponse("/admin/knowledge?msg=文档不存在")

        chunks = get_chunks(str(doc_id))

        chunk_html = ""
        for c in chunks:
            idx = c["chunk_index"] + 1
            text = c["text"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            chunk_html += (
                f"<div class='chunk-card'>"
                f"<div class='chunk-header'>切块 #{idx}</div>"
                f"<div class='chunk-body'>{text}</div>"
                f"</div>"
            )
        if not chunk_html:
            chunk_html = "<p class='text-muted text-center py-4'>暂无切块数据</p>"

        html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>切块预览 - {doc.filename}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
<style>
body {{ background: #f8f9fa; }}
.container {{ max-width: 900px; margin: 40px auto; }}
.chunk-card {{ background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; margin-bottom: 16px; overflow: hidden; }}
.chunk-header {{ background: #f0f4ff; padding: 6px 14px; font-size: .8rem; font-weight: 600; color: #4a6cf7; border-bottom: 1px solid #e0e0e0; }}
.chunk-body {{ padding: 12px 14px; font-size: .88rem; line-height: 1.7; white-space: pre-wrap; word-break: break-all; color: #333; }}
</style>
</head>
<body>
<div class="container">
  <div class="d-flex align-items-center mb-4 gap-3">
    <a href="/admin/knowledge" class="btn btn-outline-secondary btn-sm">← 返回列表</a>
    <div>
      <h5 class="mb-0">{doc.filename}</h5>
      <small class="text-muted">共 {len(chunks)} 个切块 · {doc.file_type.upper()} · {doc.uploaded_at.strftime('%Y-%m-%d %H:%M')}</small>
    </div>
  </div>
  {chunk_html}
</div>
</body>
</html>"""
        return HTMLResponse(html)

    @expose("/knowledge/upload", methods=["POST"])
    async def c_upload(self, request: Request):
        from fastapi.responses import RedirectResponse
        if not request.session.get("token") == "admin-authenticated":
            return RedirectResponse("/admin/login")

        form = await request.form()
        file: UploadFile = form.get("file")
        if not file or not file.filename:
            return RedirectResponse("/admin/knowledge?msg=请选择文件", status_code=303)

        ext = file.filename.rsplit(".", 1)[-1].lower()
        if ext not in ("pdf", "docx", "doc", "txt"):
            return RedirectResponse("/admin/knowledge?msg=不支持的文件类型，请上传 PDF/DOCX/TXT", status_code=303)

        file_bytes = await file.read()
        try:
            text = extract_text(file_bytes, file.filename)
        except Exception as e:
            return RedirectResponse(f"/admin/knowledge?msg=文件解析失败: {e}", status_code=303)

        if not text.strip():
            return RedirectResponse("/admin/knowledge?msg=文件内容为空，无法入库", status_code=303)

        from sqlmodel import Session as DBSession
        with DBSession(engine) as sess:
            doc = KnowledgeDoc(filename=file.filename, file_type=ext, chunk_count=0)
            sess.add(doc)
            sess.commit()
            sess.refresh(doc)
            doc_id = str(doc.id)

        chunk_count = add_document(doc_id, text, {"doc_id": doc_id, "filename": file.filename})

        with DBSession(engine) as sess:
            doc = sess.get(KnowledgeDoc, int(doc_id))
            doc.chunk_count = chunk_count
            sess.add(doc)
            sess.commit()

        return RedirectResponse(f"/admin/knowledge?msg=上传成功，共切分 {chunk_count} 个文本块", status_code=303)

    @expose("/knowledge/delete", methods=["POST"])
    async def d_delete(self, request: Request):
        from fastapi.responses import RedirectResponse
        if not request.session.get("token") == "admin-authenticated":
            return RedirectResponse("/admin/login")

        form = await request.form()
        doc_id = form.get("doc_id")
        if not doc_id:
            return RedirectResponse("/admin/knowledge?msg=缺少文档ID", status_code=303)

        delete_document(str(doc_id))

        from sqlmodel import Session as DBSession
        with DBSession(engine) as sess:
            doc = sess.get(KnowledgeDoc, int(doc_id))
            if doc:
                sess.delete(doc)
                sess.commit()

        return RedirectResponse("/admin/knowledge?msg=删除成功", status_code=303)


admin.add_view(UserAdmin)
admin.add_view(ProfileAdmin)
admin.add_view(PostAdmin)
admin.add_view(ChatLogAdmin)
admin.add_view(DailyFortuneAdmin)
admin.add_view(KnowledgeAdmin)


# ══════════════════════════════════════════════════════════════════════════════
# Pydantic 请求/响应模型
# ══════════════════════════════════════════════════════════════════════════════

class SendCodeRequest(BaseModel):
    email: str

class RegisterRequest(BaseModel):
    email: str
    code: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class ProfileCreate(BaseModel):
    name: str
    relationship: str = "本人"
    is_self: bool = False
    birth_city: str
    current_city: str
    birth_time: str  # ISO格式字符串 "1995-08-15T14:30:00"
    timezone: str = "Asia/Shanghai"
    gender: Optional[str] = None
    mbti: Optional[str] = None

class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    current_city: Optional[str] = None
    gender: Optional[str] = None
    mbti: Optional[str] = None

class ChatRequest(BaseModel):
    message: str
    profile_id: int
    session_id: Optional[str] = None  # 前端用于区分对话会话

class PostCreate(BaseModel):
    content: str
    images: Optional[List[str]] = []

class CommentCreate(BaseModel):
    post_id: int
    content: str

class LikeRequest(BaseModel):
    post_id: int


# ══════════════════════════════════════════════════════════════════════════════
# ── 工具函数 ──────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

def profile_to_dict(profile: Profile) -> dict:
    """将 Profile 对象转换为前端友好的字典"""
    astral = profile.get_astral_config()
    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "is_self": profile.is_self,
        "name": profile.name,
        "relationship": profile.relationship,
        "birth_city": profile.birth_city,
        "current_city": profile.current_city,
        "birth_time": profile.birth_time.isoformat() if profile.birth_time else None,
        "timezone": profile.timezone,
        "gender": profile.gender,
        "mbti": profile.mbti,
        "sun_sign_cn": astral.get("sun_sign_cn", ""),
        "moon_sign_cn": astral.get("moon_sign_cn", ""),
        "asc_sign_cn": astral.get("asc_sign_cn", ""),
        "has_astral": bool(profile.astral_config),
    }


# ══════════════════════════════════════════════════════════════════════════════
# API: Auth 认证
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/auth/send-code", summary="发送验证码")
def send_code(req: SendCodeRequest, session: Session = Depends(get_session)):
    """发送邮箱验证码（生产环境将通过邮件发送）"""
    code = send_verify_code(req.email, session)
    response = {"message": "验证码已发送至您的邮箱，请查收"}

    # 仅在测试环境下返回验证码（方便开发测试）
    if os.getenv("ENV", "test") == "test":
        response["debug_code"] = code

    return response


@app.get("/api/auth/check-email", summary="检查邮箱是否已注册")
def check_email(email: str, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.email == email)).first()
    return {"registered": bool(user), "exists": bool(user), "user_id": user.id if user else None}


@app.post("/api/auth/register", summary="注册（验证码+密码）")
def register(req: RegisterRequest, session: Session = Depends(get_session)):
    """新用户注册：邮箱验证码 + 设置密码"""
    user, token = register_user(req.email, req.code, req.password, session)
    return {
        "token": token,
        "user": {
            "id": user.id,
            "email": user.email,
            "is_vip": user.is_vip,
            "vip_expiry": None,
        },
        "message": "注册成功，欢迎加入！",
    }


@app.post("/api/auth/login", summary="登录（邮箱+密码）")
def login(req: LoginRequest, session: Session = Depends(get_session)):
    """已注册用户登录：邮箱 + 密码"""
    user, token = login_with_password(req.email, req.password, session)
    return {
        "token": token,
        "user": {
            "id": user.id,
            "email": user.email,
            "is_vip": user.is_vip,
            "vip_expiry": user.vip_expiry.isoformat() if user.vip_expiry else None,
        },
        "message": "登录成功",
    }


@app.get("/api/auth/me", summary="获取当前用户信息")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "is_vip": current_user.is_vip,
        "vip_expiry": current_user.vip_expiry.isoformat() if current_user.vip_expiry else None,
        "created_at": current_user.created_at.isoformat(),
    }


# VIP 套餐配置
VIP_PLANS = {
    "monthly":  {"name": "月度会员", "days": 30,  "price": 9.9},
    "quarterly":{"name": "季度会员", "days": 90,  "price": 24.9},
    "yearly":   {"name": "年度会员", "days": 365, "price": 68.0},
}


@app.post("/api/vip/activate", summary="激活VIP（模拟支付）")
def activate_vip(
    plan: str = "monthly",
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """模拟VIP激活，生产环境需接入支付宝/微信支付"""
    if plan not in VIP_PLANS:
        raise HTTPException(status_code=400, detail="无效的套餐类型")

    config = VIP_PLANS[plan]
    from datetime import timedelta

    # 已是VIP则在到期时间基础上续费，否则从现在开始
    base_time = current_user.vip_expiry if (current_user.is_vip and current_user.vip_expiry and current_user.vip_expiry > datetime.utcnow()) else datetime.utcnow()
    current_user.is_vip = True
    current_user.vip_expiry = base_time + timedelta(days=config["days"])
    session.add(current_user)
    session.commit()
    session.refresh(current_user)

    return {
        "message": f"🎉 {config['name']}激活成功！",
        "is_vip": True,
        "vip_expiry": current_user.vip_expiry.isoformat(),
        "plan": config,
    }


@app.get("/api/vip/plans", summary="获取VIP套餐列表")
def get_vip_plans():
    return {"plans": VIP_PLANS}




@app.post("/api/profile", summary="创建档案（自动计算星盘）")
def create_profile(
    req: ProfileCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """
    创建档案后，自动调用 astro_utils 计算星盘数据并存入 astral_config
    """
    # 解析出生时间
    try:
        birth_time = datetime.fromisoformat(req.birth_time)
    except ValueError:
        raise HTTPException(status_code=400, detail="出生时间格式错误，请使用 ISO 格式: 1995-08-15T14:30:00")

    # 如果是本人档案，确保只有一个
    if req.is_self:
        existing_self = session.exec(
            select(Profile)
            .where(Profile.user_id == current_user.id)
            .where(Profile.is_self == True)
        ).first()
        if existing_self:
            raise HTTPException(status_code=400, detail="已存在本人档案，请勿重复创建")

    # ── 计算星盘 ──────────────────────────────────────────────────────────────
    try:
        astral_data = calculate_chart(
            birth_time=birth_time,
            birth_city=req.birth_city,
            timezone=req.timezone,
        )
        astral_config_str = json.dumps(astral_data, ensure_ascii=False)

        # 获取地点验证结果
        location_warning = None
        if "warning" in astral_data:
            location_warning = astral_data["warning"]
        elif "info" in astral_data:
            location_warning = astral_data["info"]

    except Exception as e:
        print(f"星盘计算失败: {e}")
        astral_config_str = None
        location_warning = f"星盘计算错误: {str(e)}"

    profile = Profile(
        user_id=current_user.id,
        is_self=req.is_self,
        name=req.name,
        relationship=req.relationship,
        birth_city=req.birth_city,
        current_city=req.current_city,
        birth_time=birth_time,
        timezone=req.timezone,
        gender=req.gender,
        mbti=req.mbti,
        astral_config=astral_config_str,
    )
    session.add(profile)
    session.commit()
    session.refresh(profile)

    return {
        "message": "档案创建成功，星盘已计算",
        "profile": profile_to_dict(profile),
        "astral_config": profile.get_astral_config(),
        "location_warning": location_warning
    }


@app.get("/api/profile", summary="获取我的所有档案")
def get_profiles(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    profiles = session.exec(
        select(Profile).where(Profile.user_id == current_user.id)
    ).all()
    return {"profiles": [profile_to_dict(p) for p in profiles]}


@app.get("/api/profiles", summary="获取我的所有档案（别名）")
def get_profiles_alias(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """与 /api/profile 相同，提供 /api/profiles 的复数形式作为别名"""
    profiles = session.exec(
        select(Profile).where(Profile.user_id == current_user.id)
    ).all()
    return {"profiles": [profile_to_dict(p) for p in profiles]}


@app.get("/api/profile/{profile_id}", summary="获取单个档案详情")
def get_profile(
    profile_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    profile = session.get(Profile, profile_id)
    if not profile or profile.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="档案不存在")
    return {
        "profile": profile_to_dict(profile),
        "astral_config": profile.get_astral_config(),
    }


@app.delete("/api/profile/{profile_id}", summary="删除档案")
def delete_profile(
    profile_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    profile = session.get(Profile, profile_id)
    if not profile or profile.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="档案不存在")

    try:
        # 删除档案关联的数据
        # 1. 删除每日运势记录
        daily_fortunes = session.exec(
            select(DailyFortune).where(DailyFortune.profile_id == profile_id)
        ).all()
        for fortune in daily_fortunes:
            session.delete(fortune)

        # 2. 删除AI对话记录
        chat_logs = session.exec(
            select(ChatLog).where(ChatLog.profile_id == profile_id)
        ).all()
        for log in chat_logs:
            session.delete(log)

        # 3. 删除档案本身
        session.delete(profile)
        session.commit()
        return {"message": "档案已删除"}
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"删除档案失败: {str(e)}")


# ══════════════════════════════════════════════════════════════════════════════
# API: Synastry 合盘分析
# ══════════════════════════════════════════════════════════════════════════════

class SynastryRequest(BaseModel):
    profile_id1: int  # 第一个档案ID
    profile_id2: int  # 第二个档案ID

@app.post("/api/synastry", summary="计算合盘分析")
@app.post("/api/synastry/calculate", summary="计算合盘分析")
def calculate_synastry_api(
    request: SynastryRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """
    计算两个档案的合盘分析
    需要用户拥有这两个档案或其中一个档案
    """
    from astro_utils import calculate_synastry

    # 获取两个档案
    profile_1 = session.get(Profile, request.profile_id1)
    profile_2 = session.get(Profile, request.profile_id2)

    if not profile_1:
        raise HTTPException(status_code=404, detail=f"档案 {request.profile_id1} 不存在")
    if not profile_2:
        raise HTTPException(status_code=404, detail=f"档案 {request.profile_id2} 不存在")

    # 权限检查：用户必须拥有至少其中一个档案
    if profile_1.user_id != current_user.id and profile_2.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="您没有权限分析这些档案")

    # 计算合盘
    try:
        # 这里我们需要先初始化synastry_result变量
        synastry_result = None
        synastry_result = calculate_synastry(
            profile_1.get_astral_config(),
            profile_2.get_astral_config(),
            profile_1.name,
            profile_2.name
        )

        if "error" in synastry_result:
            raise HTTPException(status_code=400, detail=synastry_result["error"])

        # 构建完整的响应格式
        response = {
            "profiles": {
                "profile1": {
                    "id": profile_1.id,
                    "name": profile_1.name,
                    "gender": profile_1.gender,
                    "relationship": profile_1.relationship,
                    "birth_time": profile_1.birth_time.isoformat() if profile_1.birth_time else None,
                    "birth_city": profile_1.birth_city,
                },
                "profile2": {
                    "id": profile_2.id,
                    "name": profile_2.name,
                    "gender": profile_2.gender,
                    "relationship": profile_2.relationship,
                    "birth_time": profile_2.birth_time.isoformat() if profile_2.birth_time else None,
                    "birth_city": profile_2.birth_city,
                }
            },
            "synastry": synastry_result
        }

        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"合盘计算错误: {str(e)}")



# ══════════════════════════════════════════════════════════════════════════════
# API: Fortune 每日运势
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/fortune", summary="获取每日运势（有缓存）")
def get_fortune(
    profile_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """
    运势获取逻辑：
    1. 检查今日是否已有缓存 → 有则直接返回
    2. 没有则生成运势 → 存入数据库 → 返回
    """
    profile = session.get(Profile, profile_id)
    if not profile or profile.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="档案不存在")

    today = date.today()

    # ── 检查缓存 ──────────────────────────────────────────────────────────────
    cached = session.exec(
        select(DailyFortune)
        .where(DailyFortune.profile_id == profile_id)
        .where(DailyFortune.fortune_date == today)
    ).first()

    if cached:
        return {
            "cached": True,
            "date": today.isoformat(),
            "profile": {"id": profile.id, "name": profile.name},
            "scores": cached.get_scores(),
            "content": cached.get_content(),
        }

    # ── 生成运势 ──────────────────────────────────────────────────────────────
    astral_config = profile.get_astral_config()
    if not astral_config:
        # 如果没有星盘数据，先重新计算
        try:
            astral_config = calculate_chart(
                birth_time=profile.birth_time,
                birth_city=profile.birth_city,
                timezone=profile.timezone,
            )
            profile.astral_config = json.dumps(astral_config, ensure_ascii=False)
            session.add(profile)
            session.commit()
        except Exception:
            raise HTTPException(status_code=500, detail="星盘数据计算失败，无法生成运势")

    fortune_data = generate_fortune_by_astro(astral_config, today)

    # 存入数据库缓存
    daily_fortune = DailyFortune(
        profile_id=profile_id,
        fortune_date=today,
        scores=json.dumps(fortune_data["scores"], ensure_ascii=False),
        content=json.dumps(fortune_data["content"], ensure_ascii=False),
    )
    session.add(daily_fortune)
    session.commit()

    return {
        "cached": False,
        "date": today.isoformat(),
        "profile": {"id": profile.id, "name": profile.name},
        "scores": fortune_data["scores"],
        "content": fortune_data["content"],
        "calculation_method": fortune_data.get("calculation_method", "unknown"),
    }


# ══════════════════════════════════════════════════════════════════════════════
# API: AI Chat 对话
# ══════════════════════════════════════════════════════════════════════════════

# AI 配置
_ai_base = os.getenv("AI_BASE_URL", "https://api.deepseek.com/v1")
# 兼容两种格式：末尾含 /chat/completions 的完整 URL，或只到 /v1 的 base URL
AI_CHAT_URL = _ai_base if _ai_base.endswith("/chat/completions") else f"{_ai_base}/chat/completions"
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_FREE_MODEL = os.getenv("AI_FREE_MODEL", "deepseek-chat")
AI_VIP_MODEL = os.getenv("AI_VIP_MODEL", "deepseek-chat")


async def _post_ai(payload: dict) -> dict:
    """底层 HTTP 调用 AI API"""
    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(AI_CHAT_URL, headers=headers, json=payload)
        if response.status_code != 200:
            raise HTTPException(status_code=502, detail=f"AI 服务调用失败: {response.text}")
        return response.json()


async def call_ai_with_tools(
    messages: list,
    model: str,
    context: dict,
    rag_query: str = "",
) -> str:
    """带工具调用和 RAG 检索的 Agent 循环（最多 3 轮工具调用）"""
    if not AI_API_KEY:
        return _mock_ai_response(messages[-1]["content"] if messages else "")

    # RAG 检索，注入到 system prompt
    if rag_query:
        relevant_docs = rag_search(rag_query)
        if relevant_docs:
            rag_context = "\n\n【知识库参考】\n" + "\n---\n".join(relevant_docs)
            messages = list(messages)
            messages[0] = {**messages[0], "content": messages[0]["content"] + rag_context}

    payload = {
        "model": model,
        "messages": messages,
        "tools": TOOL_DEFINITIONS,
        "tool_choice": "auto",
        "temperature": 0.8,
        "max_tokens": 1500,
    }

    for _ in range(3):
        data = await _post_ai(payload)
        choice = data["choices"][0]
        finish_reason = choice.get("finish_reason", "stop")

        if finish_reason == "tool_calls":
            assistant_msg = choice["message"]
            payload["messages"] = list(payload["messages"]) + [assistant_msg]
            for tc in assistant_msg.get("tool_calls", []):
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}
                result = await execute_tool(tc["function"]["name"], args, context)
                payload["messages"].append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })
        else:
            return choice["message"]["content"]

    # 超过最大轮次，返回最后一次内容
    return choice["message"]["content"]


async def call_ai_api(
    messages: list,
    model: str,
    stream: bool = False,
) -> str:
    """调用 DeepSeek / OpenAI 兼容 API（无工具版，保留兼容）"""
    if not AI_API_KEY:
        return _mock_ai_response(messages[-1]["content"] if messages else "")

    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.8,
        "max_tokens": 1000,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(AI_CHAT_URL, headers=headers, json=payload)
        if response.status_code != 200:
            raise HTTPException(status_code=502, detail=f"AI 服务调用失败: {response.text}")
        data = response.json()
        return data["choices"][0]["message"]["content"]


def _mock_ai_response(user_message: str) -> str:
    """AI API 未配置时的模拟回复"""
    responses = [
        "根据您的星盘，今天的行星能量对您非常有利。太阳与木星形成三分相，预示着好运将至！",
        "您的月亮星座显示出强烈的直觉力，今天适合相信自己的第六感做决定。",
        "金星正在影响您的第七宫，爱情运势颇佳，适合表达感情或加深与伴侣的联结。",
        "水星逆行期间，沟通需要格外谨慎，重要合同或承诺建议推迟到逆行结束后再进行。",
        "土星能量提醒您脚踏实地，长期规划比短期冲动更适合您现在的星象。",
    ]
    import random
    return random.choice(responses) + f"\n\n（注：AI API 未配置，这是模拟回复。您的问题：「{user_message[:50]}」）"


@app.post("/api/chat", summary="AI 占星对话")
async def chat(
    req: ChatRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """
    AI 对话核心逻辑：
    1. 根据 is_vip 选择模型
    2. 将 astral_config 注入 System Prompt
    3. 携带历史对话（最近10条）
    4. 存储对话记录
    """
    # 验证档案归属
    profile = session.get(Profile, req.profile_id)
    if not profile or profile.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="档案不存在")

    # 选择模型
    model = AI_VIP_MODEL if current_user.is_vip else AI_FREE_MODEL
    model_version = "vip" if current_user.is_vip else "free"

    # 构建 System Prompt（注入星盘数据）
    astral_config = profile.get_astral_config()
    profile_dict = {
        "name": profile.name,
        "birth_city": profile.birth_city,
        "relationship": profile.relationship,
    }
    system_prompt = build_astro_system_prompt(profile_dict, astral_config)

    # 注入用户记忆到 system prompt
    memories = get_user_memories(session, current_user.id, req.profile_id)
    memory_text = build_memory_prompt(memories)
    if memory_text:
        system_prompt += memory_text

    # 获取历史对话（最近10条，保持上下文）
    history = session.exec(
        select(ChatLog)
        .where(ChatLog.user_id == current_user.id)
        .where(ChatLog.profile_id == req.profile_id)
        .order_by(ChatLog.id.desc())
        .limit(10)
    ).all()
    history.reverse()

    # 调用 LangChain Agent（工具调用 + RAG 检索 + 对话记忆）
    try:
        ai_reply = await run_agent(
            user_message=req.message,
            system_prompt=system_prompt,
            model=model,
            context={"profile": profile, "session": session, "user": current_user},
            history_logs=history,
            rag_query=req.message,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 调用异常: {str(e)}")

    # 存储对话记录
    user_log = ChatLog(
        user_id=current_user.id,
        profile_id=req.profile_id,
        role="user",
        content=req.message,
        model_version=model_version,
    )
    ai_log = ChatLog(
        user_id=current_user.id,
        profile_id=req.profile_id,
        role="ai",
        content=ai_reply,
        model_version=model_version,
    )
    session.add(user_log)
    session.add(ai_log)
    session.commit()

    # 异步提取记忆（不阻塞响应）
    conversation_for_memory = [
        {"role": "user" if log.role == "user" else "assistant", "content": log.content}
        for log in history
    ] + [
        {"role": "user", "content": req.message},
        {"role": "assistant", "content": ai_reply},
    ]
    from database import DATABASE_URL
    asyncio.create_task(extract_and_save_memories(
        user_id=current_user.id,
        profile_id=req.profile_id,
        conversation=conversation_for_memory,
        db_url=DATABASE_URL,
    ))

    return {
        "reply": ai_reply,
        "model_version": model_version,
        "profile": {"id": profile.id, "name": profile.name},
    }


@app.get("/api/chat/history", summary="获取对话历史")
def get_chat_history(
    profile_id: int,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    logs = session.exec(
        select(ChatLog)
        .where(ChatLog.user_id == current_user.id)
        .where(ChatLog.profile_id == profile_id)
        .order_by(ChatLog.id.asc())
        .limit(limit)
    ).all()
    return {
        "history": [
            {
                "id": log.id,
                "role": log.role,
                "content": log.content,
                "model_version": log.model_version,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ]
    }


@app.delete("/api/chat/history", summary="清空对话历史")
def clear_chat_history(
    profile_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    logs = session.exec(
        select(ChatLog)
        .where(ChatLog.user_id == current_user.id)
        .where(ChatLog.profile_id == profile_id)
    ).all()
    for log in logs:
        session.delete(log)
    session.commit()
    return {"message": f"已清空 {len(logs)} 条对话记录"}


# ══════════════════════════════════════════════════════════════════════════════
# API: Community 社区
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/posts", summary="获取社区帖子列表")
def get_posts(
    page: int = 1,
    page_size: int = 10,
    current_user: Optional[User] = Depends(get_optional_user),
    session: Session = Depends(get_session),
):
    offset = (page - 1) * page_size
    posts = session.exec(
        select(Post)
        .order_by(Post.created_at.desc())
        .offset(offset)
        .limit(page_size)
    ).all()

    # 获取已登录用户的点赞状态
    liked_post_ids = set()
    if current_user:
        likes = session.exec(
            select(PostLike).where(PostLike.user_id == current_user.id)
        ).all()
        liked_post_ids = {like.post_id for like in likes}

    result = []
    for post in posts:
        # 获取发布者信息
        author = session.get(User, post.user_id)
        # 获取评论数
        comment_count = len(session.exec(
            select(Comment).where(Comment.post_id == post.id)
        ).all())

        result.append({
            "id": post.id,
            "content": post.content,
            "images": post.get_images(),
            "like_count": post.like_count,
            "comment_count": comment_count,
            "is_liked": post.id in liked_post_ids,
            "created_at": post.created_at.isoformat(),
            "author": {
                "id": author.id if author else 0,
                "email": author.email[:3] + "***" + author.email[author.email.find("@"):] if author else "",
            },
        })

    return {"posts": result, "page": page, "page_size": page_size}


@app.post("/api/posts", summary="发布帖子")
def create_post(
    req: PostCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="帖子内容不能为空")

    post = Post(
        user_id=current_user.id,
        content=req.content.strip(),
        images=json.dumps(req.images or [], ensure_ascii=False),
        like_count=0,
    )
    session.add(post)
    session.commit()
    session.refresh(post)

    return {
        "message": "发布成功",
        "post": {
            "id": post.id,
            "content": post.content,
            "images": post.get_images(),
            "created_at": post.created_at.isoformat(),
        }
    }


@app.post("/api/posts/like", summary="点赞/取消点赞")
def toggle_like(
    req: LikeRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """点赞切换逻辑：已点赞则取消，未点赞则添加"""
    post = session.get(Post, req.post_id)
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")

    # 查找已有点赞记录
    existing_like = session.exec(
        select(PostLike)
        .where(PostLike.user_id == current_user.id)
        .where(PostLike.post_id == req.post_id)
    ).first()

    if existing_like:
        # 取消点赞
        session.delete(existing_like)
        post.like_count = max(0, post.like_count - 1)
        session.add(post)
        session.commit()
        return {"liked": False, "like_count": post.like_count, "message": "已取消点赞"}
    else:
        # 添加点赞
        new_like = PostLike(user_id=current_user.id, post_id=req.post_id)
        post.like_count += 1
        session.add(new_like)
        session.add(post)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return {"liked": True, "like_count": post.like_count, "message": "已点赞"}
        return {"liked": True, "like_count": post.like_count, "message": "点赞成功"}


@app.get("/api/posts/{post_id}/comments", summary="获取评论列表")
def get_comments(
    post_id: int,
    session: Session = Depends(get_session),
):
    comments = session.exec(
        select(Comment)
        .where(Comment.post_id == post_id)
        .order_by(Comment.id.asc())
    ).all()
    result = []
    for comment in comments:
        author = session.get(User, comment.user_id)
        result.append({
            "id": comment.id,
            "content": comment.content,
            "created_at": comment.created_at.isoformat(),
            "author": {
                "id": author.id if author else 0,
                "email": author.email[:3] + "***" + author.email[author.email.find("@"):] if author else "",
            },
        })
    return {"comments": result}


@app.post("/api/posts/comment", summary="发表评论")
def add_comment(
    req: CommentCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    post = session.get(Post, req.post_id)
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")

    comment = Comment(
        post_id=req.post_id,
        user_id=current_user.id,
        content=req.content.strip(),
    )
    session.add(comment)
    session.commit()
    session.refresh(comment)
    return {"message": "评论成功", "comment_id": comment.id}


# ══════════════════════════════════════════════════════════════════════════════
# API: 好友系统
# ══════════════════════════════════════════════════════════════════════════════

class FriendRequest(BaseModel):
    friend_id: int

@app.post("/api/friends", summary="添加好友")
def add_friend(
    request: FriendRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """添加好友（创建聊天室）"""
    target_user = session.get(User, request.friend_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="目标用户不存在")

    if request.friend_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能添加自己为好友")

    # 确保user1_id < user2_id，避免重复聊天室
    user1_id = min(current_user.id, request.friend_id)
    user2_id = max(current_user.id, request.friend_id)

    # 查找现有聊天室
    existing_room = session.exec(
        select(ChatRoom).where(
            (ChatRoom.user1_id == user1_id) &
            (ChatRoom.user2_id == user2_id)
        )
    ).first()

    if existing_room:
        return {"message": "已经是好友关系", "room_id": existing_room.id}

    # 创建新聊天室
    new_room = ChatRoom(
        user1_id=user1_id,
        user2_id=user2_id
    )
    session.add(new_room)
    session.commit()
    session.refresh(new_room)

    return {"message": "好友添加成功", "room_id": new_room.id}

@app.get("/api/friends", summary="获取好友列表")
def get_friends(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """获取用户的好友列表"""
    # 查找用户参与的所有聊天室
    rooms = session.exec(
        select(ChatRoom).where(
            (ChatRoom.user1_id == current_user.id) |
            (ChatRoom.user2_id == current_user.id)
        )
    ).all()

    friends = []
    for room in rooms:
        # 获取对方用户信息
        other_user_id = room.user2_id if room.user1_id == current_user.id else room.user1_id
        other_user = session.get(User, other_user_id)

        if not other_user:
            continue

        # 获取对方的自我档案
        profile = session.exec(
            select(Profile)
            .where(Profile.user_id == other_user_id)
            .where(Profile.is_self == True)
        ).first()

        friend_info = {
            "id": other_user.id,
            "name": f"用户{other_user.id}" if not profile else profile.name,
            "email": other_user.email
        }

        # 添加星座信息
        if profile and profile.astral_config:
            astral = profile.get_astral_config()
            friend_info["sun_sign_cn"] = astral.get("sun_sign_cn", "未知")

        friends.append(friend_info)

    return {"friends": friends}

@app.delete("/api/friends/{friend_id}", summary="删除好友")
def remove_friend(
    friend_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """删除好友（删除聊天室）"""
    # 确保user1_id < user2_id
    user1_id = min(current_user.id, friend_id)
    user2_id = max(current_user.id, friend_id)

    # 查找聊天室
    room = session.exec(
        select(ChatRoom).where(
            (ChatRoom.user1_id == user1_id) &
            (ChatRoom.user2_id == user2_id)
        )
    ).first()

    if not room:
        raise HTTPException(status_code=404, detail="好友关系不存在")

    # 删除聊天消息
    messages = session.exec(
        select(ChatMessage).where(ChatMessage.room_id == room.id)
    ).all()

    for msg in messages:
        session.delete(msg)

    # 删除聊天室
    session.delete(room)
    session.commit()

    return {"message": "好友已删除"}

@app.get("/api/friends/check/{user_id}", summary="检查好友状态")
def check_friend_status(
    user_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """检查与指定用户是否为好友"""
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="不能检查自己为好友")

    # 确保user1_id < user2_id
    user1_id = min(current_user.id, user_id)
    user2_id = max(current_user.id, user_id)

    # 查找聊天室
    room = session.exec(
        select(ChatRoom).where(
            (ChatRoom.user1_id == user1_id) &
            (ChatRoom.user2_id == user2_id)
        )
    ).first()

    return {"is_friend": bool(room), "room_id": room.id if room else None}


# ══════════════════════════════════════════════════════════════════════════════
# API: 用户聊天系统
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════════
# API: 用户资料
# ══════════════════════════════════════════════════════════════════════════════════

@app.get("/api/user/{user_id}", summary="获取用户资料")
def get_user_profile(
    user_id: int,
    current_user: Optional[User] = Depends(get_optional_user),
    session: Session = Depends(get_session),
):
    """
    获取指定用户的公开资料。
    - 公开展示：邮箱(部分隐藏)、档案星盘数据
    - 如果是当前用户自己，返回完整信息
    """
    # 查找用户
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 查找用户的星盘档案
    self_profile = session.exec(
        select(Profile)
        .where(Profile.user_id == user_id)
        .where(Profile.is_self == True)
    ).first()

    # 获取用户邮箱（对非本人部分隐藏）
    is_self = current_user and current_user.id == user_id
    email = user.email if is_self else f"{user.email[:3]}***{user.email[user.email.find('@'):]}"

    # 构建用户资料
    user_data = {
        "user": {
            "id": user.id,
            "name": f"用户{user.id}" if not self_profile else self_profile.name,
            "email": email
        }
    }

    # 如果有星盘档案，添加星盘信息
    if self_profile:
        user_data["profile"] = {
            "mbti": self_profile.mbti,
            "location": self_profile.current_city,
            "is_self": self_profile.is_self,
            "relationship": self_profile.relationship
        }

        astral_config = self_profile.get_astral_config()
        if astral_config:
            user_data["astral_config"] = {
                "sun_sign_cn": astral_config.get("sun_sign_cn", "未知"),
                "moon_sign_cn": astral_config.get("moon_sign_cn", "未知"),
                "asc_sign_cn": astral_config.get("asc_sign_cn", "未知")
            }

    # 检查好友状态（如果当前用户已登录）
    if current_user and current_user.id != user_id:
        # 确保user1_id < user2_id
        user1_id = min(current_user.id, user_id)
        user2_id = max(current_user.id, user_id)

        # 检查是否为好友
        existing_room = session.exec(
            select(ChatRoom).where(
                (ChatRoom.user1_id == user1_id) &
                (ChatRoom.user2_id == user2_id)
            )
        ).first()

        user_data["is_friend"] = bool(existing_room)

    return user_data


class StartChatRequest(BaseModel):
    target_user_id: int

class SendMessageRequest(BaseModel):
    room_id: int
    content: str
    message_type: str = "text"

@app.get("/api/chats", summary="获取用户聊天室列表")
def get_chat_rooms(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """获取用户的所有聊天室"""
    # 查找用户参与的所有聊天室
    rooms = session.exec(
        select(ChatRoom).where(
            (ChatRoom.user1_id == current_user.id) |
            (ChatRoom.user2_id == current_user.id)
        ).order_by(ChatRoom.last_message_at.desc())
    ).all()

    result = []
    for room in rooms:
        # 获取对方用户信息
        other_user_id = room.user2_id if room.user1_id == current_user.id else room.user1_id
        other_user = session.get(User, other_user_id)

        # 获取最新消息
        last_message = session.exec(
            select(ChatMessage).where(ChatMessage.room_id == room.id)
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        ).first()

        # 统计未读消息数
        unread_count = session.exec(
            select(ChatMessage).where(
                (ChatMessage.room_id == room.id) &
                (ChatMessage.sender_id != current_user.id) &
                (ChatMessage.is_read == False)
            )
        ).all()

        result.append({
            "room_id": room.id,
            "other_user": {
                "id": other_user.id,
                "email": other_user.email,
            },
            "last_message": {
                "content": last_message.content if last_message else "",
                "created_at": last_message.created_at.isoformat() if last_message else room.created_at.isoformat(),
            },
            "unread_count": len(unread_count),
        })

    return {"chat_rooms": result}


@app.post("/api/chats", summary="开始与用户聊天")
def start_chat(
    request: StartChatRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """开始与指定用户聊天，返回聊天室ID"""
    target_user = session.get(User, request.target_user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="目标用户不存在")

    if request.target_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能与自己聊天")

    # 确保user1_id < user2_id，避免重复聊天室
    user1_id = min(current_user.id, request.target_user_id)
    user2_id = max(current_user.id, request.target_user_id)

    # 查找现有聊天室
    existing_room = session.exec(
        select(ChatRoom).where(
            (ChatRoom.user1_id == user1_id) &
            (ChatRoom.user2_id == user2_id)
        )
    ).first()

    if existing_room:
        return {"room_id": existing_room.id, "exists": True}

    # 创建新聊天室
    new_room = ChatRoom(
        user1_id=user1_id,
        user2_id=user2_id
    )
    session.add(new_room)
    session.commit()
    session.refresh(new_room)

    return {"room_id": new_room.id, "exists": False}


@app.get("/api/chats/{room_id}/messages", summary="获取聊天消息历史")
def get_chat_messages(
    room_id: int,
    page: int = 1,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """获取指定聊天室的消息历史"""
    # 验证用户是否有权限访问此聊天室
    room = session.get(ChatRoom, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="聊天室不存在")

    if room.user1_id != current_user.id and room.user2_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此聊天室")

    # 获取消息
    offset = (page - 1) * limit
    messages = session.exec(
        select(ChatMessage).where(ChatMessage.room_id == room_id)
        .order_by(ChatMessage.created_at.desc())
        .offset(offset).limit(limit)
    ).all()

    # 标记对方发送的消息为已读
    unread_messages = session.exec(
        select(ChatMessage).where(
            (ChatMessage.room_id == room_id) &
            (ChatMessage.sender_id != current_user.id) &
            (ChatMessage.is_read == False)
        )
    ).all()

    for msg in unread_messages:
        msg.is_read = True
    session.commit()

    # 格式化返回
    result = []
    for msg in reversed(messages):  # 按时间正序返回
        sender = session.get(User, msg.sender_id)
        result.append({
            "id": msg.id,
            "sender": {
                "id": msg.sender_id,
                "email": sender.email,
                "is_me": msg.sender_id == current_user.id,
            },
            "content": msg.content,
            "message_type": msg.message_type,
            "created_at": msg.created_at.isoformat(),
        })

    return {"messages": result}


@app.post("/api/chats/send", summary="发送消息")
def send_message(
    request: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """发送聊天消息"""
    # 验证聊天室权限
    room = session.get(ChatRoom, request.room_id)
    if not room:
        raise HTTPException(status_code=404, detail="聊天室不存在")

    if room.user1_id != current_user.id and room.user2_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权在此聊天室发送消息")

    # 创建消息
    message = ChatMessage(
        room_id=request.room_id,
        sender_id=current_user.id,
        content=request.content.strip(),
        message_type=request.message_type,
    )

    if not message.content:
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    session.add(message)

    # 更新聊天室的最后消息时间
    room.last_message_at = datetime.utcnow()

    session.commit()
    session.refresh(message)

    return {
        "message": "发送成功",
        "message_id": message.id,
        "created_at": message.created_at.isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# API: 文件上传
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/upload", summary="上传图片")
async def upload_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    # 验证文件类型
    allowed_types = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="只支持 JPG/PNG/GIF/WebP 格式")

    # 生成文件名
    import uuid
    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "jpg"
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = f"uploads/{filename}"

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:  # 5MB 限制
        raise HTTPException(status_code=400, detail="图片大小不能超过 5MB")

    with open(filepath, "wb") as f:
        f.write(content)

    return {"url": f"/uploads/{filename}", "filename": filename}


# ══════════════════════════════════════════════════════════════════════════════
# 健康检查
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/", include_in_schema=False)
def root_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/static/login.html")


@app.get("/api/astro/test", summary="测试flatlib库是否可用")
def test_astro_lib():
    """测试flatlib库是否可用，返回当前太阳位置"""
    from astro_utils import test_flatlib
    return test_flatlib()


@app.get("/api/cities", summary="获取系统支持的城市列表")
def get_cities():
    """
    返回系统内置的所有城市列表，按省份分组，前端可用于城市选择下拉框
    """
    from astro_utils import CITY_COORDS

    # 过滤掉default和别名城市（以防重复）
    cities = []
    added = set()

    # 城市省份分组
    city_provinces = {
        "北京市": ["北京"],
        "天津市": ["天津"],
        "上海市": ["上海"],
        "重庆市": ["重庆"],
        "河北省": ["石家庄", "唐山", "保定", "邯郸", "沧州", "廊坊"],
        "山西省": ["太原"],
        "辽宁省": ["沈阳", "大连", "鞍山"],
        "吉林省": ["长春"],
        "黑龙江省": ["哈尔滨", "大庆"],
        "江苏省": ["南京", "苏州", "无锡", "常州", "南通", "徐州", "盐城"],
        "浙江省": ["杭州", "宁波", "温州", "嘉兴", "绍兴", "金华"],
        "安徽省": ["合肥"],
        "福建省": ["福州", "厦门", "泉州"],
        "江西省": ["南昌"],
        "山东省": ["济南", "青岛", "烟台", "威海", "临沂", "淄博", "菏泽"],
        "河南省": ["郑州"],
        "湖北省": ["武汉", "黄冈"],
        "湖南省": ["长沙"],
        "广东省": ["广州", "深圳", "珠海", "佛山", "东莞", "中山", "湛江"],
        "广西壮族自治区": ["南宁", "柳州"],
        "海南省": ["海口"],
        "四川省": ["成都", "绵阳"],
        "贵州省": ["贵阳"],
        "云南省": ["昆明"],
        "西藏自治区": ["拉萨"],
        "陕西省": ["西安"],
        "甘肃省": ["兰州"],
        "青海省": ["西宁"],
        "宁夏回族自治区": ["银川"],
        "新疆维吾尔自治区": ["乌鲁木齐"],
        "内蒙古自治区": ["呼和浩特", "包头"],
        "香港特别行政区": ["香港"],
        "澳门特别行政区": ["澳门"],
        "台湾省": ["台北"]
    }

    # 省份显示顺序（按照行政区划代码排序）
    province_order = [
        "北京市", "天津市", "上海市", "重庆市",  # 直辖市
        "河北省", "山西省", "内蒙古自治区",      # 华北
        "辽宁省", "吉林省", "黑龙江省",         # 东北
        "江苏省", "浙江省", "安徽省", "福建省", "江西省", "山东省",  # 华东
        "河南省", "湖北省", "湖南省",           # 华中
        "广东省", "广西壮族自治区", "海南省",    # 华南
        "四川省", "贵州省", "云南省", "西藏自治区",  # 西南
        "陕西省", "甘肃省", "青海省", "宁夏回族自治区", "新疆维吾尔自治区",  # 西北
        "香港特别行政区", "澳门特别行政区", "台湾省"  # 特别行政区
    ]

    # 逆向建立映射表
    city_to_province = {}
    for province, city_list in city_provinces.items():
        for city in city_list:
            city_to_province[city] = province

    # 将城市分组返回，按照省份顺序排序
    province_cities = {}
    for province in province_order:
        if province in city_provinces:
            province_cities[province] = []

    other_cities = []

    for city, coords in CITY_COORDS.items():
        # 跳过default和已添加的城市
        if city == "default" or city in added:
            continue

        # 如果城市名带"市"，跳过它（我们会使用不带"市"的版本）
        if city.endswith("市") and city[:-1] in CITY_COORDS:
            continue

        # 过滤掉一些特殊的别名
        if city in ["北平"]:  # 历史名称
            continue

        city_data = {
            "name": city,
            "latitude": coords[0],
            "longitude": coords[1]
        }

        # 按省份分组
        if city in city_to_province:
            province = city_to_province[city]
            if province in province_cities:
                province_cities[province].append(city_data)
        else:
            other_cities.append(city_data)

        added.add(city)

    # 在每个省份内按城市名排序
    for province in province_cities:
        province_cities[province].sort(key=lambda x: x["name"])

    # 其他城市排序
    other_cities.sort(key=lambda x: x["name"])

    # 创建有序返回结构
    ordered_provinces = {}
    for province in province_order:
        if province in province_cities and province_cities[province]:
            ordered_provinces[province] = province_cities[province]

    return {
        "grouped_cities": ordered_provinces,
        "other_cities": other_cities
    }


# ══════════════════════════════════════════════════════════════════════════════
# API: Debug & Test 调试端点
# ══════════════════════════════════════════════════════════════════════════════

    # 代码已移动到合并后的 calculate_synastry_api 函数中

@app.get("/api/debug/verify-codes", summary="查看验证码记录（仅测试环境可用）")
def debug_verify_codes(email: str, session: Session = Depends(get_session)):
    """查看指定邮箱的验证码记录，仅在测试环境可用"""
    # 确保仅在测试环境中可用
    if os.getenv("ENV", "test") != "test":
        raise HTTPException(status_code=403, detail="此接口仅在测试环境可用")

    codes = session.exec(
        select(VerifyCode)
        .where(VerifyCode.email == email)
        .order_by(VerifyCode.id.desc())
    ).all()

    result = []
    for code in codes:
        result.append({
            "id": code.id,
            "email": code.email,
            "code": code.code,  # 仅在测试环境显示
            "is_used": code.is_used,
            "expires_at": code.expires_at.isoformat() if code.expires_at else None,
            "is_expired": datetime.utcnow() > code.expires_at if code.expires_at else True,
        })

    return {"verify_codes": result}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
