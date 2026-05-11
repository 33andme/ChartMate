"""
email_service.py - 邮件服务模块
- SMTP邮件发送功能
- 验证码邮件模板
"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
import logging

# 邮件服务器配置
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.qq.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "your-email@qq.com")  # 需要修改为您的邮箱
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "your-password")  # 需要修改为您的授权码
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "true").lower() == "true"
SENDER_NAME = os.getenv("SENDER_NAME", "星座星盘系统")
IS_TEST_ENV = os.getenv("ENV", "test") == "test"

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("email_service")


def send_email(to_email: str, subject: str, content: str, html_content: str = None) -> bool:
    """
    发送邮件

    Args:
        to_email: 收件人邮箱
        subject: 邮件主题
        content: 纯文本内容
        html_content: HTML格式内容（可选）

    Returns:
        bool: 是否发送成功
    """
    # 测试环境不实际发送邮件
    if IS_TEST_ENV:
        logger.info(f"[测试环境] 模拟发送邮件到 {to_email}, 主题: {subject}")
        return True

    msg = MIMEMultipart('alternative')
    msg['Subject'] = Header(subject, 'utf-8')
    msg['From'] = f"{SMTP_USER}"  # 简化From头部，只使用纯邮箱地址
    msg['To'] = to_email

    # 添加纯文本内容
    text_part = MIMEText(content, 'plain', 'utf-8')
    msg.attach(text_part)

    # 如果提供了HTML内容，添加HTML部分
    if html_content:
        html_part = MIMEText(html_content, 'html', 'utf-8')
        msg.attach(html_part)

    try:
        # 记录发送前的信息
        logger.info(f"尝试发送邮件到 {to_email}, 使用服务器: {SMTP_SERVER}:{SMTP_PORT}")

        # 连接SMTP服务器
        if SMTP_USE_SSL:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
            logger.info("使用SSL连接")
        else:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()  # 使用TLS加密连接
            logger.info("使用TLS连接")

        # 登录
        logger.info(f"尝试登录邮箱: {SMTP_USER}")
        server.login(SMTP_USER, SMTP_PASSWORD)
        logger.info("登录成功")

        # 发送邮件
        server.sendmail(SMTP_USER, to_email, msg.as_string())
        server.quit()

        logger.info(f"邮件已发送至 {to_email}")
        return True
    except Exception as e:
        logger.error(f"发送邮件失败: {str(e)}")
        return False


def send_verification_code_email(to_email: str, code: str) -> bool:
    """
    发送验证码邮件

    Args:
        to_email: 收件人邮箱
        code: 验证码

    Returns:
        bool: 是否发送成功
    """
    subject = "算算 - 验证码"

    # 纯文本内容
    text_content = f"""
    您好！

    您的验证码是: {code}

    该验证码在10分钟内有效，请勿将验证码泄露给他人。
    如非本人操作，请忽略此邮件。

    --
    算算团队
    """

    # HTML内容
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e8e8e8; border-radius: 5px;">
        <div style="text-align: center; margin-bottom: 20px;">
            <h1 style="color: #8a2be2;">算算</h1>
        </div>
        <div style="background-color: #f8f8f8; padding: 15px; border-radius: 4px; margin-bottom: 20px;">
            <p style="font-size: 16px;">您好！</p>
            <p style="font-size: 16px;">您的验证码是：</p>
            <div style="text-align: center; padding: 10px;">
                <span style="font-size: 28px; font-weight: bold; letter-spacing: 5px; color: #8a2be2;">{code}</span>
            </div>
            <p style="font-size: 14px; color: #666;">该验证码在10分钟内有效，请勿将验证码泄露给他人。</p>
            <p style="font-size: 14px; color: #666;">如非本人操作，请忽略此邮件。</p>
        </div>
        <div style="text-align: center; color: #999; font-size: 12px; margin-top: 20px;">
            <p>© 2026 算算团队</p>
        </div>
    </div>
    """

    return send_email(to_email, subject, text_content, html_content)