#!/bin/bash
# start.sh - 快速启动脚本（适配Windows Git Bash）

echo "🔮 启动占星APP后端..."
echo ""

# 核心修改：优先找Windows的python，再找python3（适配Git Bash）
PY=""
# 检查Windows系统下的python命令（优先）
if command -v /c/Python*/python.exe &> /dev/null; then
    PY=$(command -v /c/Python*/python.exe | head -n 1)
elif command -v python &> /dev/null; then
    PY=$(command -v python)
elif command -v py &> /dev/null; then
    PY=$(command -v py)
elif command -v python3 &> /dev/null; then
    PY=$(command -v python3)
fi

# 检查Python是否找到
if [ -z "$PY" ]; then
    echo "❌ 未找到 Python，请先安装 Python 3.9+"
    exit 1
fi

# 安装依赖（去掉quiet，方便看安装日志）
echo "📦 安装依赖...（使用Python路径：$PY）"
$PY -m pip install -r requirements.txt

# 启动服务
echo "🚀 启动 FastAPI 服务 http://localhost:8000"
echo "   前端入口: http://localhost:8000/static/index.html"
echo "   API文档:  http://localhost:8000/docs"
echo "   后台管理: http://localhost:8000/admin"
echo "   管理员:   admin / admin123"
echo ""
$PY -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload