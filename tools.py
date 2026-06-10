"""
tools.py - AI 工具调用定义和执行
支持：网络搜索（DuckDuckGo）、用户数据查询
"""
import json
import httpx

# OpenAI function calling 格式的工具描述，由 call_ai_with_tools 在请求时传给模型
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "搜索互联网获取实时信息，适用于：当前星象/行星位置、"
                "天文事件、节气、最新占星资讯等需要实时数据的问题"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，建议用中文或英文简洁描述"
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_user_data",
            "description": (
                "查询当前用户的个人数据，适用于：用户询问自己的星盘详情、"
                "历史运势记录、个人档案信息等"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "data_type": {
                        "type": "string",
                        "enum": ["profile", "fortune_history", "astral_detail"],
                        "description": (
                            "profile=基本档案信息，"
                            "fortune_history=近期运势记录，"
                            "astral_detail=完整星盘行星数据"
                        ),
                    }
                },
                "required": ["data_type"],
            },
        },
    },
]


async def _search_web(query: str) -> str:
    """调用 DuckDuckGo 即时答案 API（无需 Key）"""
    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            resp = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            data = resp.json()

        parts = []
        if data.get("AbstractText"):
            parts.append(data["AbstractText"])
        for topic in data.get("RelatedTopics", [])[:3]:
            if isinstance(topic, dict) and topic.get("Text"):
                parts.append(topic["Text"])

        if parts:
            return "\n".join(parts)
        return f"未找到关于「{query}」的即时结果，建议用户自行查阅最新资讯。"

    except Exception as e:
        return f"搜索失败: {str(e)}"


def _query_user_data(data_type: str, context: dict) -> str:
    """从 context 中读取用户数据并格式化返回"""
    profile = context.get("profile")
    user = context.get("user")

    if not profile:
        return "未找到用户档案信息。"

    if data_type == "profile":
        return json.dumps({
            "姓名": profile.name,
            "关系": profile.relationship,
            "出生城市": profile.birth_city,
            "当前城市": getattr(profile, "current_city", ""),
            "出生时间": str(profile.birth_time),
            "性别": profile.gender or "未填写",
            "MBTI": profile.mbti or "未填写",
        }, ensure_ascii=False, indent=2)

    if data_type == "astral_detail":
        astral = profile.get_astral_config()
        if not astral:
            return "该档案尚未生成星盘数据，请先在档案页面计算星盘。"
        return json.dumps(astral, ensure_ascii=False, indent=2)

    if data_type == "fortune_history":
        from sqlmodel import Session, select
        from models import DailyFortune
        from database import engine
        with Session(engine) as s:
            records = s.exec(
                select(DailyFortune)
                .where(DailyFortune.profile_id == profile.id)
                .order_by(DailyFortune.fortune_date.desc())
                .limit(7)
            ).all()
        if not records:
            return "暂无运势历史记录。"
        result = []
        for r in records:
            scores = r.get_scores()
            content = r.get_content()
            result.append({
                "日期": str(r.fortune_date),
                "综合": scores.get("overall"),
                "爱情": scores.get("love"),
                "事业": scores.get("career"),
                "建议": content.get("advice", ""),
            })
        return json.dumps(result, ensure_ascii=False, indent=2)

    return "未知的查询类型。"


async def execute_tool(tool_name: str, args: dict, context: dict) -> str:
    """分发并执行工具调用"""
    if tool_name == "search_web":
        return await _search_web(args.get("query", ""))
    if tool_name == "query_user_data":
        return _query_user_data(args.get("data_type", "profile"), context)
    return f"未知工具: {tool_name}"
