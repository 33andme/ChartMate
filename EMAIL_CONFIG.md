# 邮箱验证码配置说明

为了启用邮箱验证码功能，请在环境变量中配置以下参数：

## 必要的环境变量

```bash
# 邮件服务器设置
SMTP_SERVER=smtp.qq.com          # SMTP服务器地址
SMTP_PORT=465                    # SMTP端口，一般为465(SSL)或587(TLS)
SMTP_USER=your-email@qq.com      # 发件人邮箱
SMTP_PASSWORD=your-password      # 邮箱授权码（不是邮箱登录密码）
SMTP_USE_SSL=true                # 是否使用SSL连接，一般为true
SENDER_NAME=星座星盘系统          # 发件人显示名称

# 环境设置
ENV=production                   # 环境类型：test为测试环境(固定验证码)，production为生产环境(实际发送邮件)
```

## 获取邮箱授权码

以QQ邮箱为例，获取授权码的步骤：

1. 登录QQ邮箱网页版
2. 点击"设置" → "账户"
3. 在"POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务"部分，开启"POP3/SMTP服务"
4. 按照提示操作，获取授权码
5. 将获取到的授权码填入`SMTP_PASSWORD`环境变量

## 其他邮箱设置

常见邮箱服务器设置：

- QQ邮箱：
  - SMTP_SERVER=smtp.qq.com
  - SMTP_PORT=465
  - SMTP_USE_SSL=true

- 163邮箱：
  - SMTP_SERVER=smtp.163.com
  - SMTP_PORT=465
  - SMTP_USE_SSL=true

- Gmail：
  - SMTP_SERVER=smtp.gmail.com
  - SMTP_PORT=587
  - SMTP_USE_SSL=false（使用TLS）

## 测试环境

在测试环境中（ENV=test），系统会生成固定验证码123456，并在API响应中返回debug_code，不会实际发送邮件。

## 生产环境

在生产环境中（ENV=production），系统会实际发送邮件，并且不会在API响应中返回验证码。