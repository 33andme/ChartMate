"""
astro_utils.py - 星盘计算工具
优先使用 flatlib（专业占星学库，基于 Swiss Ephemeris）
无法导入时自动降级到 Mock 模式
"""
import json
import math
import hashlib
import random
from datetime import datetime, date
from typing import Optional
import pytz

# ── flatlib 导入 ────────────────────────────────────────────────────────────────
try:
    from flatlib.datetime import Datetime
    from flatlib.geopos import GeoPos
    from flatlib.chart import Chart
    from flatlib import const
    import flatlib as _flatlib
    FLATLIB_AVAILABLE = True
    # 星历文件路径（flatlib 安装自带）
    _EPHE_PATH = _flatlib.PATH_RES + 'swefiles'
except ImportError:
    FLATLIB_AVAILABLE = False
    _EPHE_PATH = ""
    print("⚠️  flatlib 未安装，将使用模拟星盘数据。运行: pip install flatlib")


# ── 城市经纬度字典 ────────────────────────────────────────────────────────────
CITY_COORDS = {
    "北京": (39.9042, 116.4074), "上海": (31.2304, 121.4737),
    "广州": (23.1291, 113.2644), "深圳": (22.5431, 114.0579),
    "成都": (30.5728, 104.0668), "杭州": (30.2741, 120.1551),
    "武汉": (30.5928, 114.3055), "西安": (34.3416, 108.9398),
    "重庆": (29.5630, 106.5516), "南京": (32.0603, 118.7969),
    "天津": (39.3434, 117.3616), "苏州": (31.2989, 120.5853),
    "郑州": (34.7466, 113.6253), "长沙": (28.2278, 112.9388),
    "济南": (36.6512, 117.1201), "哈尔滨": (45.8038, 126.5349),
    "沈阳": (41.8057, 123.4315), "青岛": (36.0671, 120.3826),
    "宁波": (29.8683, 121.5440), "厦门": (24.4798, 118.0894),
    "昆明": (25.0389, 102.7183), "贵阳": (26.6470, 106.6302),
    "福州": (26.0745, 119.2965), "合肥": (31.8206, 117.2272),
    "南宁": (22.8170, 108.3665), "乌鲁木齐": (43.8256, 87.6168),
    "兰州": (36.0611, 103.8343), "太原": (37.8706, 112.5489),
    "石家庄": (38.0428, 114.5149), "南昌": (28.6820, 115.8579),
    "海口": (20.0440, 110.1999), "拉萨": (29.6500, 91.1000),
    "香港": (22.3193, 114.1694), "澳门": (22.1987, 113.5439),
    "台北": (25.0330, 121.5654),
    # 新增城市
    "长春": (43.8172, 125.3240), "大连": (38.9146, 121.6146),
    "无锡": (31.5487, 120.3119), "佛山": (23.0218, 113.1220),
    "东莞": (23.0210, 113.7510), "温州": (27.9992, 120.6670),
    "金华": (29.0784, 119.6478), "泉州": (24.8741, 118.6750),
    "常州": (31.8101, 119.9733), "徐州": (34.2583, 117.1859),
    "嘉兴": (30.7607, 120.7534), "烟台": (37.4636, 121.4481),
    "威海": (37.5130, 122.1199), "珠海": (22.2708, 113.5767),
    "盐城": (33.3479, 120.1633), "临沂": (35.0653, 118.3267),
    "淄博": (36.8134, 118.0648), "绍兴": (30.0307, 120.5806),
    "唐山": (39.6505, 118.1821), "呼和浩特": (40.8414, 111.7520),
    "银川": (38.4872, 106.2309), "西宁": (36.6171, 101.7784),
    "包头": (40.6574, 109.8398), "南通": (32.0147, 120.8707),
    "大庆": (46.5957, 125.1045), "保定": (38.8747, 115.4588),
    "中山": (22.5200, 113.3926), "鞍山": (41.1096, 123.0076),
    "廊坊": (39.5376, 116.6846), "菏泽": (35.2378, 115.4806),
    "柳州": (24.3255, 109.4280), "绵阳": (31.4679, 104.6796),
    "沧州": (38.3047, 116.8387), "黄冈": (30.4612, 114.8750),
    "湛江": (21.2707, 110.3594), "邯郸": (36.6123, 114.5391),
    # 添加别名
    "北平": (39.9042, 116.4074),  # 北京的旧称
    "南京市": (32.0603, 118.7969), # 带"市"的城市名
    "广州市": (23.1291, 113.2644),
    "上海市": (31.2304, 121.4737),
    "深圳市": (22.5431, 114.0579),
    "default": (39.9042, 116.4074),
}

PLANET_CN = {
    "Sun": "太阳", "Moon": "月亮", "Mercury": "水星", "Venus": "金星",
    "Mars": "火星", "Jupiter": "木星", "Saturn": "土星",
    "Uranus": "天王星", "Neptune": "海王星", "Pluto": "冥王星",
    "Asc": "上升点", "MC": "天顶",
}

SIGN_CN = {
    "Aries": "白羊座", "Taurus": "金牛座", "Gemini": "双子座",
    "Cancer": "巨蟹座", "Leo": "狮子座", "Virgo": "处女座",
    "Libra": "天秤座", "Scorpio": "天蝎座", "Sagittarius": "射手座",
    "Capricorn": "摩羯座", "Aquarius": "水瓶座", "Pisces": "双鱼座",
}

SIGN_EMOJI = {
    "Aries": "♈", "Taurus": "♉", "Gemini": "♊", "Cancer": "♋",
    "Leo": "♌", "Virgo": "♍", "Libra": "♎", "Scorpio": "♏",
    "Sagittarius": "♐", "Capricorn": "♑", "Aquarius": "♒", "Pisces": "♓",
}

# 黄道12宫顺序（与度数对应）
SIGNS_ORDER = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]

# 太阳星座日期范围（Mock 备用）
SUN_SIGN_DATES = [
    (( 3, 21), ( 4, 19), "Aries"),
    (( 4, 20), ( 5, 20), "Taurus"),
    (( 5, 21), ( 6, 20), "Gemini"),
    (( 6, 21), ( 7, 22), "Cancer"),
    (( 7, 23), ( 8, 22), "Leo"),
    (( 8, 23), ( 9, 22), "Virgo"),
    (( 9, 23), (10, 22), "Libra"),
    ((10, 23), (11, 21), "Scorpio"),
    ((11, 22), (12, 21), "Sagittarius"),
    ((12, 22), ( 1, 19), "Capricorn"),
    (( 1, 20), ( 2, 18), "Aquarius"),
    (( 2, 19), ( 3, 20), "Pisces"),
]


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def get_city_coords(city_name: str):
    """
    获取城市坐标，返回包含详细信息的字典
    """
    # 尝试精确匹配
    if city_name in CITY_COORDS:
        return {
            "lat": CITY_COORDS[city_name][0],
            "lon": CITY_COORDS[city_name][1],
            "found": True,
            "match_type": "exact",
            "matched_city": city_name
        }

    # 尝试模糊匹配
    for city, coords in CITY_COORDS.items():
        if city in city_name or city_name in city:
            return {
                "lat": coords[0],
                "lon": coords[1],
                "found": True,
                "match_type": "fuzzy",
                "matched_city": city
            }

    # 没有匹配，返回默认值
    return {
        "lat": CITY_COORDS["default"][0],
        "lon": CITY_COORDS["default"][1],
        "found": False,
        "match_type": "default",
        "matched_city": "北京"
    }


def get_sun_sign_by_date(birth_date: datetime) -> str:
    month, day = birth_date.month, birth_date.day
    for (start_m, start_d), (end_m, end_d), sign in SUN_SIGN_DATES:
        if start_m <= end_m:
            if (month == start_m and day >= start_d) or \
               (month == end_m and day <= end_d) or \
               (start_m < month < end_m):
                return sign
        else:
            # start_m > end_m 说明该星座跨年（如摩羯座 12/22-1/19），需分段判断
            if (month == start_m and day >= start_d) or \
               (month == end_m and day <= end_d) or \
               month > start_m or month < end_m:
                return sign
    return "Capricorn"


def _lon_to_sign_info(lon_deg: float) -> dict:
    """把黄道经度（0-360）转成星座信息"""
    lon_deg = lon_deg % 360
    sign = SIGNS_ORDER[int(lon_deg / 30)]
    return {
        "sign":    sign,
        "sign_cn": SIGN_CN[sign],
        "emoji":   SIGN_EMOJI[sign],
        "degree":  round(lon_deg % 30, 2),
    }


# ── 主计算入口 ────────────────────────────────────────────────────────────────

def calculate_chart(
    birth_time: datetime,
    birth_city: str,
    timezone: str = "Asia/Shanghai"
) -> dict:
    # 获取城市坐标信息
    city_info = get_city_coords(birth_city)
    lat, lon = city_info["lat"], city_info["lon"]

    # 创建结果字典，添加地点验证信息
    result = {}

    # 如果用户输入的地点不存在，添加警告信息
    if not city_info["found"]:
        result["warning"] = f"未找到地点 '{birth_city}'，使用默认位置（北京）"
    elif city_info["match_type"] == "fuzzy":
        result["info"] = f"模糊匹配到地点：{city_info['matched_city']}"

    # 计算星盘
    if FLATLIB_AVAILABLE:
        try:
            chart_data = _calculate_with_flatlib(birth_time, birth_city, lat, lon, timezone)
            result.update(chart_data)
            return result
        except Exception as e:
            print(f"⚠️  flatlib 计算出错，降级到 Mock: {e}")

    # 降级到mock计算
    chart_data = _calculate_mock(birth_time, birth_city, lat, lon)
    result.update(chart_data)
    return result


def _calculate_with_flatlib(
    birth_time: datetime,
    birth_city: str,
    lat: float,
    lon: float,
    timezone: str
) -> dict:
    """使用 flatlib 精确计算星盘（专业占星学库）"""

    # 本地时间 → UTC
    tz = pytz.timezone(timezone)
    local_dt = tz.localize(birth_time) if birth_time.tzinfo is None \
               else birth_time.astimezone(tz)
    utc_dt = local_dt.astimezone(pytz.utc)

    # 创建 flatlib 时间对象
    dt_str = utc_dt.strftime("%Y/%m/%d")
    time_str = utc_dt.strftime("%H:%M:%S")
    dt = Datetime(dt_str, time_str, '+00:00')

    # 创建地理位置对象
    pos = GeoPos(lat, lon)

    # 每次创建 Chart 前强制设置路径，防止被其他调用覆盖
    import swisseph as _swe
    _swe.set_ephe_path(_EPHE_PATH)

    # 创建星盘（显式传入所有天体，否则默认只加载传统七星，天王/海王/冥王会 KeyError）
    chart = Chart(dt, pos, IDs=const.LIST_OBJECTS)
    planets_map = {
        const.SUN:     "Sun",
        const.MOON:    "Moon",
        const.MERCURY: "Mercury",
        const.VENUS:   "Venus",
        const.MARS:    "Mars",
        const.JUPITER: "Jupiter",
        const.SATURN:  "Saturn",
        const.URANUS:  "Uranus",
        const.NEPTUNE: "Neptune",
        const.PLUTO:   "Pluto",
    }

    planets_data = {}

    # 获取行星数据
    for flatlib_id, pid in planets_map.items():
        try:
            planet = chart.get(flatlib_id)
            lon_deg = planet.lon
            info = _lon_to_sign_info(lon_deg)

            # 检测逆行（flatlib 中通过速度判断）
            retrograde = hasattr(planet, 'lonspeed') and planet.lonspeed < 0

            planets_data[pid] = {
                **info,
                "retrograde": retrograde,
                "planet_cn": PLANET_CN.get(pid, pid),
            }
        except Exception as e:
            print(f"⚠️  获取 {pid} 数据出错: {e}")
            continue

    # 获取上升点和天顶
    try:
        asc = chart.get(const.ASC)
        mc = chart.get(const.MC)

        asc_info = _lon_to_sign_info(asc.lon)
        mc_info = _lon_to_sign_info(mc.lon)

        planets_data["Asc"] = {**asc_info, "retrograde": False, "planet_cn": "上升点"}
        planets_data["MC"] = {**mc_info, "retrograde": False, "planet_cn": "天顶"}

    except Exception as e:
        print(f"⚠️  获取上升点/天顶数据出错: {e}")

    # 宫位计算（等宫制，从上升点开始）
    houses_data = {}
    if "Asc" in planets_data:
        asc_deg = asc.lon
        for i in range(1, 13):
            h_deg = (asc_deg + (i - 1) * 30) % 360
            h_info = _lon_to_sign_info(h_deg)
            houses_data[f"house_{i}"] = {
                "sign": h_info["sign"],
                "sign_cn": h_info["sign_cn"],
                "degree": round(h_deg, 2),
            }

    sun_sign = planets_data.get("Sun", {}).get("sign", "Aries")
    moon_sign = planets_data.get("Moon", {}).get("sign", "Taurus")
    asc_sign = planets_data.get("Asc", {}).get("sign", "Leo")

    return {
        "calculated_at": datetime.utcnow().isoformat(),
        "birth_city": birth_city,
        "coordinates": {"lat": lat, "lon": lon},
        "sun_sign": sun_sign,
        "sun_sign_cn": SIGN_CN[sun_sign],
        "moon_sign": moon_sign,
        "moon_sign_cn": SIGN_CN[moon_sign],
        "asc_sign": asc_sign,
        "asc_sign_cn": SIGN_CN[asc_sign],
        "planets": planets_data,
        "houses": houses_data,
        "method": "flatlib",
    }


def _calculate_mock(
    birth_time: datetime,
    birth_city: str,
    lat: float,
    lon: float
) -> dict:
    """flatlib 不可用时的 Mock 降级（太阳星座仍用真实日期推算）"""
    # 用出生信息生成确定性哈希，确保同一用户每次获得相同的模拟星盘
    seed_str = f"{birth_time.year}{birth_time.month}{birth_time.day}{lat}{lon}"
    hash_val = int(hashlib.md5(seed_str.encode()).hexdigest(), 16)

    planet_ids = ["Sun", "Moon", "Mercury", "Venus", "Mars",
                  "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto", "Asc", "MC"]

    planets_data = {}
    for i, pid in enumerate(planet_ids):
        sign = SIGNS_ORDER[(hash_val + i * 7) % 12]
        planets_data[pid] = {
            "sign":       sign,
            "sign_cn":    SIGN_CN[sign],
            "emoji":      SIGN_EMOJI[sign],
            "degree":     round((hash_val + i * 13) % 30, 2),
            "retrograde": bool((hash_val + i) % 5 == 0),
            "planet_cn":  PLANET_CN.get(pid, pid),
        }

    # 太阳星座用真实日期覆盖
    real_sun = get_sun_sign_by_date(birth_time)
    planets_data["Sun"].update({
        "sign": real_sun, "sign_cn": SIGN_CN[real_sun], "emoji": SIGN_EMOJI[real_sun],
    })

    houses_data = {}
    for i in range(1, 13):
        sign = SIGNS_ORDER[(hash_val + i * 3) % 12]
        houses_data[f"house_{i}"] = {
            "sign": sign, "sign_cn": SIGN_CN[sign],
            "degree": round((hash_val + i * 11) % 360, 2),
        }

    sun_sign  = planets_data["Sun"]["sign"]
    moon_sign = planets_data["Moon"]["sign"]
    asc_sign  = planets_data["Asc"]["sign"]

    return {
        "calculated_at": datetime.utcnow().isoformat(),
        "birth_city":    birth_city,
        "coordinates":   {"lat": lat, "lon": lon},
        "sun_sign":      sun_sign,
        "sun_sign_cn":   SIGN_CN[sun_sign],
        "moon_sign":     moon_sign,
        "moon_sign_cn":  SIGN_CN[moon_sign],
        "asc_sign":      asc_sign,
        "asc_sign_cn":   SIGN_CN[asc_sign],
        "planets":       planets_data,
        "houses":        houses_data,
        "method":        "mock",
    }


# ── AI 提示词构建 ─────────────────────────────────────────────────────────────

def build_astro_system_prompt(profile_data: dict, astral_config: dict) -> str:
    name         = profile_data.get("name", "用户")
    birth_city   = profile_data.get("birth_city", "")
    sun_sign_cn  = astral_config.get("sun_sign_cn", "未知")
    moon_sign_cn = astral_config.get("moon_sign_cn", "未知")
    asc_sign_cn  = astral_config.get("asc_sign_cn", "未知")
    planets      = astral_config.get("planets", {})
    method       = astral_config.get("method", "mock")
    method_note  = "（精确天文星历计算 - Swiss Ephemeris）" if method == "flatlib" else "（模拟数据，仅供参考）"

    planet_lines = []
    for pid, pdata in planets.items():
        retro = "（逆行）" if pdata.get("retrograde") else ""
        planet_lines.append(
            f"  - {pdata.get('planet_cn', pid)}: {pdata.get('sign_cn', '')} {pdata.get('degree', 0)}° {retro}"
        )

    return f"""你是一位专业的占星师和命理顾问，精通西方占星学。请根据用户的星盘数据来回答问题。

## 用户档案
- **姓名**: {name}
- **出生地**: {birth_city}
- **太阳星座**: {sun_sign_cn}（代表自我、本质、核心特质）
- **月亮星座**: {moon_sign_cn}（代表情感、内心、潜意识）
- **上升星座**: {asc_sign_cn}（代表外在形象、第一印象）
- **数据来源**: {method_note}

## 星盘行星配置
{chr(10).join(planet_lines) or "  暂无数据"}

## 回答要求
1. 结合上述星盘数据进行个性化分析，避免泛泛而谈
2. 语气温和、积极、有洞察力，像一位知心的占星师朋友
3. 对于负面倾向，用成长视角来解读
4. 回答简洁有力，重点突出，适当使用星座符号增加趣味性
5. 如果用户问与占星无关的问题，温柔地引导回占星话题
"""


# ── 每日运势生成（基于真实天文数据）──────────────────────────────────────────
def generate_fortune_by_astro(astral_config: dict, target_date) -> dict:
    """基于用户星盘和当日真实天象计算运势"""
    sun_sign  = astral_config.get("sun_sign", "Aries")
    moon_sign = astral_config.get("moon_sign", "Taurus")
    asc_sign  = astral_config.get("asc_sign", "Leo")
    planets   = astral_config.get("planets", {})
    birth_city = astral_config.get("birth_city", "北京")  # 获取出生地

    # 获取当日天象（使用北京时间中午12点作为基准）
    detailed_info = {}
    if FLATLIB_AVAILABLE:
        try:
            daily_positions = _calculate_daily_positions(target_date, birth_city)
            scores = _calculate_fortune_scores(astral_config, daily_positions)
            detailed_info = {
                "calculation_method": "flatlib",
                "date": str(target_date),
                "daily_positions": {k: {"sign": v["sign"]} for k, v in daily_positions.items()},
                "aspects": scores.get("details", [])
            }
        except Exception as e:
            print(f"⚠️  真实运势计算出错，使用备选方案: {e}")
            scores = _fallback_fortune_scores(sun_sign, moon_sign, target_date)
            detailed_info = {
                "calculation_method": "fallback",
                "error": str(e),
                "date": str(target_date)
            }
    else:
        scores = _fallback_fortune_scores(sun_sign, moon_sign, target_date)
        detailed_info = {
            "calculation_method": "fallback",
            "error": "flatlib not available",
            "date": str(target_date)
        }

    sign_short = {
        "Aries": "白羊", "Taurus": "金牛", "Gemini": "双子",
        "Cancer": "巨蟹", "Leo": "狮子", "Virgo": "处女",
        "Libra": "天秤", "Scorpio": "天蝎", "Sagittarius": "射手",
        "Capricorn": "摩羯", "Aquarius": "水瓶", "Pisces": "双鱼",
    }.get(sun_sign, "")

    # 基于太阳星座和当日运势分数生成建议
    advice_pool = {
        "Aries":       ["今天火星能量旺盛，适合主动出击", "勇于表达自己的想法，魅力十足"],
        "Taurus":      ["稳扎稳打，今日有利于财务积累", "享受美好事物，慢下来感受生活"],
        "Gemini":      ["信息流通顺畅，沟通带来好运", "灵感迸发，多尝试新事物"],
        "Cancer":      ["家庭运势佳，关注内心感受", "直觉敏锐，相信第六感"],
        "Leo":         ["今日魅力爆棚，适合社交展示", "创意能量高涨，勇于表现"],
        "Virgo":       ["细节决定成败，工作事半功倍", "健康管理好时机，注重饮食规律"],
        "Libra":       ["人际关系和谐，合作运势佳", "美感提升，适合艺术创作"],
        "Scorpio":     ["洞察力超强，看穿表象本质", "深度思考带来突破"],
        "Sagittarius": ["探索欲旺盛，适合学习新知", "乐观心态吸引好运"],
        "Capricorn":   ["事业心旺盛，目标明确前行", "踏实努力终有回报"],
        "Aquarius":    ["创新思维活跃，与众不同的视角", "团队合作中大放异彩"],
        "Pisces":      ["灵感如泉涌，艺术感知力强", "善用直觉做决定"],
    }
    avoid_pool = {
        "Aries":       ["避免冲动行事，三思而后行", "控制脾气，以和为贵"],
        "Taurus":      ["避免固执己见，保持灵活", "不要过于贪图享乐"],
        "Gemini":      ["避免分心太多，聚焦重要事项", "慎防信息过载"],
        "Cancer":      ["避免情绪化决策", "不要封闭自己，多与人交流"],
        "Leo":         ["避免过于自我中心", "谦虚听取他人意见"],
        "Virgo":       ["避免过度批判自己和他人", "完美主义适可而止"],
        "Libra":       ["避免优柔寡断，勇于做决定", "不要为了和谐委屈自己"],
        "Scorpio":     ["避免猜疑过重", "学会放手，不必控制一切"],
        "Sagittarius": ["避免做事半途而废", "注意言语分寸"],
        "Capricorn":   ["避免工作太拼，注意休息", "不要太过压抑情感"],
        "Aquarius":    ["避免脱离实际", "与身边的人保持联结"],
        "Pisces":      ["避免逃避现实", "注意边界感，学会拒绝"],
    }

    # 根据运势分数选择建议（高分选择积极建议，低分选择谨慎建议）
    overall_score = scores.get("overall", 75)
    advice_choices = advice_pool.get(sun_sign, ["保持积极心态，好运自然来"])
    avoid_choices = avoid_pool.get(sun_sign, ["避免负面情绪影响判断"])

    # 使用确定性选择（基于日期和分数）
    date_seed = hash(f"{target_date}{sun_sign}")
    advice = advice_choices[abs(date_seed + overall_score) % len(advice_choices)]
    avoid = avoid_choices[abs(date_seed - overall_score) % len(avoid_choices)]

    lucky_colors = ["红色", "橙色", "黄色", "绿色", "蓝色", "紫色", "粉色", "白色", "金色", "银色"]
    lucky_directions = ["东", "南", "西", "北", "东南", "东北", "西南", "西北"]

    # 处理行星相位信息
    aspects_info = detailed_info.get("aspects", [])
    aspects_text = ""

    if aspects_info:
        for aspect in aspects_info:
            planet_cn = aspect.get("planet_cn", "行星")
            aspect_type = aspect.get("aspect_type", "相位")
            influence = "积极" if aspect.get("is_positive") else "需注意"

            aspects_text += f"{planet_cn}{aspect_type}：{influence}。"

    # 添加行星相位解读，如果有的话
    planet_insight = ""
    if aspects_text:
        planet_insight = f"今日行星解读：{aspects_text}"

    content = {
        "summary": f"{sign_short}座今日整体运势{scores['overall']}分，{advice.replace('今天', '今日')}",
        "advice": advice,
        "avoid": avoid,
        "lucky_color": lucky_colors[abs(date_seed) % len(lucky_colors)],
        "lucky_number": (abs(date_seed) % 9) + 1,
        "lucky_direction": lucky_directions[abs(date_seed) % len(lucky_directions)],
        "planet_insight": planet_insight
    }

    return {
        "scores": scores,
        "content": content,
        "details": detailed_info,
        "calculation_method": detailed_info.get("calculation_method", "unknown")
    }

# ── 合盘分析功能 ──────────────────────────────────────────────────────────────

def calculate_synastry(astral_1: dict, astral_2: dict, name_1: str = "甲", name_2: str = "乙") -> dict:
    """计算两个人的合盘分析"""

    planets_1 = astral_1.get("planets", {})
    planets_2 = astral_2.get("planets", {})

    if not planets_1 or not planets_2:
        return {"error": "缺少星盘数据"}

    # 分析相位关系
    aspects = _analyze_synastry_aspects(planets_1, planets_2, name_1, name_2)

    # 计算兼容性分数
    compatibility = _calculate_compatibility_scores(aspects, astral_1, astral_2)

    # 生成合盘解读
    interpretation = _generate_synastry_interpretation(aspects, compatibility, astral_1, astral_2, name_1, name_2)

    return {
        "person_1": {"name": name_1, "sun": astral_1.get("sun_sign_cn"), "moon": astral_1.get("moon_sign_cn"), "asc": astral_1.get("asc_sign_cn")},
        "person_2": {"name": name_2, "sun": astral_2.get("sun_sign_cn"), "moon": astral_2.get("moon_sign_cn"), "asc": astral_2.get("asc_sign_cn")},
        "compatibility_scores": compatibility,
        "aspects": aspects,
        "interpretation": interpretation,
        "calculated_at": datetime.utcnow().isoformat(),
    }


def _analyze_synastry_aspects(planets_1: dict, planets_2: dict, name_1: str, name_2: str) -> list:
    """分析两人星盘的相位关系"""

    # 重要行星优先级（用于合盘分析）
    important_planets = ["Sun", "Moon", "Venus", "Mars", "Mercury", "Jupiter", "Saturn", "Asc"]

    aspects = []

    for p1_id in important_planets:
        if p1_id not in planets_1:
            continue

        p1_data = planets_1[p1_id]
        p1_lon = _get_planet_longitude(p1_data)

        for p2_id in important_planets:
            if p2_id not in planets_2:
                continue

            p2_data = planets_2[p2_id]
            p2_lon = _get_planet_longitude(p2_data)

            # 计算相位
            aspect_angle = _get_aspect_angle(p1_lon, p2_lon)
            aspect_info = _get_synastry_aspect_info(aspect_angle)

            if aspect_info:  # 有相位关系
                aspects.append({
                    "person_1_planet": p1_id,
                    "person_1_planet_cn": PLANET_CN.get(p1_id, p1_id),
                    "person_1_name": name_1,
                    "person_2_planet": p2_id,
                    "person_2_planet_cn": PLANET_CN.get(p2_id, p2_id),
                    "person_2_name": name_2,
                    "aspect": aspect_info["name"],
                    "aspect_cn": aspect_info["name_cn"],
                    "angle": round(aspect_angle, 1),
                    "influence": aspect_info["influence"],
                    "description": aspect_info["description"],
                })

    # 按影响强度排序
    aspects.sort(key=lambda x: abs(x["influence"]), reverse=True)
    return aspects[:15]  # 只保留最强的15个相位，避免解读信息过载


def _get_synastry_aspect_info(angle: float) -> dict:
    """获取合盘相位信息"""

    synastry_aspects = [
        {"angle": 0, "orb": 8, "name": "Conjunction", "name_cn": "合相", "influence": 5,
         "description": "能量融合，强化彼此特质"},
        {"angle": 60, "orb": 6, "name": "Sextile", "name_cn": "六分相", "influence": 3,
         "description": "和谐互补，容易合作"},
        {"angle": 90, "orb": 8, "name": "Square", "name_cn": "刑相", "influence": -3,
         "description": "紧张冲突，需要调和"},
        {"angle": 120, "orb": 8, "name": "Trine", "name_cn": "三分相", "influence": 4,
         "description": "天然和谐，互相支持"},
        {"angle": 180, "orb": 8, "name": "Opposition", "name_cn": "对分相", "influence": -2,
         "description": "互相吸引又对立，需要平衡"},
    ]

    for aspect in synastry_aspects:
        if abs(angle - aspect["angle"]) <= aspect["orb"]:
            return aspect

    return None


def _calculate_compatibility_scores(aspects: list, astral_1: dict, astral_2: dict) -> dict:
    """计算兼容性分数"""

    scores = {
        "overall": 0,        # 整体兼容性
        "love": 0,          # 爱情兼容性
        "communication": 0, # 沟通兼容性
        "values": 0,        # 价值观兼容性
        "emotional": 0,     # 情感兼容性
        "sexual": 0,        # 性吸引力
    }

    # 基础分数
    base_scores = {k: 60 for k in scores.keys()}

    # 根据相位调整分数
    for aspect in aspects:
        p1 = aspect["person_1_planet"]
        p2 = aspect["person_2_planet"]
        influence = aspect["influence"]

        # 不同行星组合影响不同的兼容性维度
        planet_influences = {
            ("Sun", "Sun"): {"overall": 3, "values": 2},
            ("Sun", "Moon"): {"overall": 4, "emotional": 3},
            ("Moon", "Moon"): {"emotional": 4, "overall": 2},
            ("Venus", "Venus"): {"love": 3, "values": 2},
            ("Venus", "Mars"): {"love": 4, "sexual": 5},
            ("Mars", "Mars"): {"sexual": 3, "overall": 1},
            ("Mercury", "Mercury"): {"communication": 4},
            ("Sun", "Mercury"): {"communication": 2, "overall": 1},
            ("Moon", "Venus"): {"emotional": 3, "love": 2},
            ("Sun", "Venus"): {"love": 2, "overall": 2},
            ("Moon", "Mars"): {"emotional": 2, "sexual": 2},
        }

        # 查找匹配的行星组合（考虑顺序）
        combo_key = (p1, p2)
        reverse_combo_key = (p2, p1)

        influences = planet_influences.get(combo_key) or planet_influences.get(reverse_combo_key)

        if influences:
            for category, weight in influences.items():
                scores[category] += influence * weight

    # 应用基础分数和限制范围
    for category in scores:
        scores[category] = max(20, min(100, base_scores[category] + scores[category]))

    return scores


def _generate_synastry_interpretation(aspects: list, compatibility: dict, astral_1: dict, astral_2: dict, name_1: str, name_2: str) -> dict:
    """生成合盘解读"""

    sun_1 = astral_1.get("sun_sign", "")
    sun_2 = astral_2.get("sun_sign", "")

    # 太阳星座兼容性分析
    fire_signs = ["Aries", "Leo", "Sagittarius"]
    earth_signs = ["Taurus", "Virgo", "Capricorn"]
    air_signs = ["Gemini", "Libra", "Aquarius"]
    water_signs = ["Cancer", "Scorpio", "Pisces"]

    def get_element(sign):
        if sign in fire_signs: return "火"
        if sign in earth_signs: return "土"
        if sign in air_signs: return "风"
        if sign in water_signs: return "水"
        return "未知"

    element_1 = get_element(sun_1)
    element_2 = get_element(sun_2)

    # 元素兼容性
    element_compatibility = {
        ("火", "火"): "同为火象星座，你们都充满热情和活力，容易产生强烈的化学反应，但也可能因为都太冲动而产生摩擦。",
        ("火", "风"): "火象与风象的组合很有活力，风能助火燃烧得更旺，你们的关系会充满激情和创意。",
        ("火", "土"): "火象与土象的组合需要耐心磨合，火的热情可以激发土的潜能，而土的稳定可以给火提供支撑。",
        ("火", "水"): "火象与水象是考验耐性的组合，水能温润火的冲动，火能激发水的热情，需要更多理解。",
        ("土", "土"): "同为土象星座，你们都很务实稳重，关系稳定可靠，但可能缺少一些激情和变化。",
        ("土", "水"): "土象与水象是很好的组合，土能给水提供安全感，水能滋润土的心田，相处和谐。",
        ("风", "风"): "同为风象星座，你们都喜欢思考和交流，精神契合度很高，但可能在实际执行上需要更多行动力。",
        ("风", "水"): "风象与水象的组合有一种特殊的浪漫，风能带来新思维，水能提供情感深度。",
        ("水", "水"): "同为水象星座，你们情感共鸣很强，能深刻理解彼此的内心，但要避免过于情绪化。",
    }

    element_desc = element_compatibility.get((element_1, element_2)) or element_compatibility.get((element_2, element_1)) or "你们的星座组合很特别，需要用心经营。"

    # 重要相位分析
    key_aspects = [asp for asp in aspects[:5] if abs(asp["influence"]) >= 3]

    overall_score = compatibility["overall"]
    if overall_score >= 85:
        overall_desc = "你们的星盘非常和谐，是天生一对的组合！"
    elif overall_score >= 70:
        overall_desc = "你们的兼容性很不错，有很好的发展前景。"
    elif overall_score >= 55:
        overall_desc = "你们的关系需要一些努力和理解，但很有潜力。"
    else:
        overall_desc = "你们的星盘存在一些挑战，需要更多的包容和沟通。"

    return {
        "overall_description": overall_desc,
        "element_analysis": f"{name_1}是{element_1}象星座，{name_2}是{element_2}象星座。{element_desc}",
        "key_aspects": key_aspects,
        "love_advice": _get_love_advice(compatibility["love"], sun_1, sun_2),
        "communication_tips": _get_communication_tips(compatibility["communication"]),
    }


def _get_love_advice(love_score: int, sun_1: str, sun_2: str) -> str:
    """根据爱情兼容性分数生成建议"""
    if love_score >= 80:
        return "你们在爱情方面很有默契，彼此深深吸引，要珍惜这份缘分。"
    elif love_score >= 65:
        return "你们的爱情需要时间培养，多一些浪漫和惊喜会让关系更甜蜜。"
    elif love_score >= 50:
        return "在爱情方面你们需要更多的耐心和理解，学会欣赏彼此的不同。"
    else:
        return "爱情路上可能会有一些波折，但真诚的沟通和相互包容能化解困难。"


def _get_communication_tips(comm_score: int) -> str:
    """根据沟通兼容性分数生成建议"""
    if comm_score >= 80:
        return "你们沟通很顺畅，能够很好地理解彼此的想法。"
    elif comm_score >= 65:
        return "多倾听对方的观点，避免因为小事产生误解。"
    elif comm_score >= 50:
        return "学会用对方能理解的方式表达自己，耐心是关键。"
    else:
        return "沟通是你们关系中的重要课题，建议多花时间了解彼此的表达习惯。"


def _calculate_daily_positions(target_date, city_name="北京"):
    """计算指定日期的行星位置"""
    from flatlib.datetime import Datetime
    from flatlib.geopos import GeoPos
    from flatlib.chart import Chart
    from flatlib import const

    # 确保target_date是字符串格式的日期
    if isinstance(target_date, (datetime, date)):
        dt_str = target_date.strftime("%Y/%m/%d")
    else:
        # 尝试解析字符串格式的日期
        try:
            parsed_date = datetime.strptime(str(target_date), "%Y-%m-%d").date()
            dt_str = parsed_date.strftime("%Y/%m/%d")
        except ValueError:
            # 如果解析失败，使用今天的日期
            dt_str = datetime.now().strftime("%Y/%m/%d")
            print(f"⚠️ 日期解析失败: {target_date}，使用当前日期")

    # 使用北京时间中午12点作为基准
    time_str = "12:00:00"
    dt = Datetime(dt_str, time_str, '+08:00')  # 北京时间

    # 获取地点坐标
    city_info = get_city_coords(city_name)
    lat, lon = city_info["lat"], city_info["lon"]

    # 创建地点对象
    pos = GeoPos(lat, lon)

    # 每次创建 Chart 前强制设置路径，防止被其他调用覆盖
    import swisseph as _swe
    _swe.set_ephe_path(_EPHE_PATH)

    # 创建当日星盘（显式传入所有天体）
    chart = Chart(dt, pos, IDs=const.LIST_OBJECTS)

    positions = {}
    planets_map = {
        const.SUN: "Sun", const.MOON: "Moon", const.MERCURY: "Mercury",
        const.VENUS: "Venus", const.MARS: "Mars", const.JUPITER: "Jupiter",
        const.SATURN: "Saturn", const.URANUS: "Uranus", const.NEPTUNE: "Neptune",
        const.PLUTO: "Pluto"
    }

    for flatlib_id, pid in planets_map.items():
        try:
            planet = chart.get(flatlib_id)
            positions[pid] = {
                "lon": planet.lon,
                "sign": _lon_to_sign_info(planet.lon)["sign"],
                "retrograde": hasattr(planet, 'lonspeed') and planet.lonspeed < 0
            }
        except Exception as e:
            print(f"⚠️  获取{pid}位置失败: {e}")
            continue

    return positions


def _calculate_fortune_scores(user_astral: dict, daily_positions: dict):
    """基于用户星盘和当日天象计算运势分数"""
    user_planets = user_astral.get("planets", {})

    base_scores = {
        "overall": 75, "love": 75, "wealth": 75,
        "career": 75, "study": 75, "social": 75,
    }

    aspect_bonuses = _analyze_daily_aspects(user_planets, daily_positions)

    # details 是列表，单独取出，不参与数值计算
    details = aspect_bonuses.pop("details", [])

    for category, bonus in aspect_bonuses.items():
        if category in base_scores:
            base_scores[category] = max(50, min(99, base_scores[category] + bonus))

    base_scores["details"] = details
    return base_scores


def _analyze_daily_aspects(user_planets: dict, daily_positions: dict):
    """分析用户本命盘与当日天象的相位关系"""
    bonuses = {
        "overall": 0, "love": 0, "wealth": 0,
        "career": 0, "study": 0, "social": 0,
    }

    # 重要行星的影响权重
    planet_weights = {
        "Sun": {"overall": 3, "career": 2, "social": 1},
        "Moon": {"overall": 2, "love": 2, "social": 1, "study": 1},
        "Venus": {"love": 3, "social": 2, "overall": 1, "wealth": 1},
        "Mars": {"career": 2, "overall": 2, "love": 1, "wealth": 1},
        "Mercury": {"study": 3, "career": 1, "social": 1, "wealth": 1},
        "Jupiter": {"wealth": 3, "overall": 2, "career": 1, "social": 1},
        "Saturn": {"career": 2, "wealth": 1, "overall": -1, "study": 1},
    }

    # 记录分析结果，用于解读
    aspect_details = []

    for user_pid, user_data in user_planets.items():
        if user_pid not in daily_positions or user_pid not in planet_weights:
            continue

        daily_data = daily_positions[user_pid]
        user_lon = _get_planet_longitude(user_data)
        daily_lon = daily_data["lon"]

        # 计算相位
        aspect_angle = _get_aspect_angle(user_lon, daily_lon)
        aspect_strength = _get_aspect_strength(aspect_angle)
        aspect_type = _get_aspect_type(aspect_angle)

        # 记录显著相位
        if aspect_type and abs(aspect_strength) >= 2:
            aspect_details.append({
                "planet": user_pid,
                "planet_cn": PLANET_CN.get(user_pid, user_pid),
                "angle": round(aspect_angle, 1),
                "aspect_type": aspect_type,
                "strength": aspect_strength,
                "is_positive": aspect_strength > 0
            })

        # 应用行星权重
        weights = planet_weights[user_pid]
        for category, weight in weights.items():
            bonuses[category] += aspect_strength * weight

    # 按照强度排序
    aspect_details.sort(key=lambda x: abs(x["strength"]), reverse=True)

    # 添加相位详情到结果
    bonuses["details"] = aspect_details[:3]  # 仅保留前3个最显著的相位

    return bonuses


def _get_aspect_type(angle):
    """获取相位类型名称"""
    aspects = {
        (0, 8): "合相",
        (60, 6): "六分相",
        (90, 8): "刑相",
        (120, 8): "三分相",
        (180, 8): "对分相",
    }

    for (target_angle, orb), name in aspects.items():
        if abs(angle - target_angle) <= orb:
            return name

    return None


def _get_planet_longitude(planet_data: dict):
    """从行星数据获取黄道经度"""
    sign = planet_data.get("sign", "Aries")
    degree = planet_data.get("degree", 0)
    sign_base = {
        "Aries": 0, "Taurus": 30, "Gemini": 60, "Cancer": 90,
        "Leo": 120, "Virgo": 150, "Libra": 180, "Scorpio": 210,
        "Sagittarius": 240, "Capricorn": 270, "Aquarius": 300, "Pisces": 330,
    }
    return sign_base.get(sign, 0) + degree


def _get_aspect_angle(lon1: float, lon2: float):
    """计算两个黄道经度之间的相位角度"""
    diff = abs(lon1 - lon2)
    if diff > 180:
        diff = 360 - diff
    return diff


def _get_aspect_strength(angle: float):
    """根据相位角度返回影响强度"""
    # 主要相位及其影响强度
    aspects = [
        (0, 8, 5),    # 合相 - 强化能量
        (60, 6, 3),   # 六分相 - 和谐
        (90, 8, -2),  # 刑相 - 紧张挑战
        (120, 8, 4),  # 三分相 - 和谐流动
        (180, 8, -1), # 对分相 - 对立平衡
    ]

    for target_angle, orb, strength in aspects:
        if abs(angle - target_angle) <= orb:
            return strength

    return 0  # 无相位


def _fallback_fortune_scores(sun_sign: str, moon_sign: str, target_date):
    """备选运势计算方案（当flatlib不可用时）"""
    seed = f"{target_date}{sun_sign}{moon_sign}"
    hash_val = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    # 用固定种子初始化 Random，保证同一天同一用户的运势分数不变
    rng = random.Random(hash_val)

    return {
        "overall": rng.randint(65, 95),
        "love": rng.randint(60, 99),
        "wealth": rng.randint(60, 99),
        "career": rng.randint(60, 99),
        "study": rng.randint(60, 99),
        "social": rng.randint(60, 99),
    }

# 测试函数，验证flatlib可用性
def test_flatlib():
    """测试flatlib库是否可用，返回当前太阳位置"""
    if not FLATLIB_AVAILABLE:
        return {"status": "error", "message": "flatlib 未安装", "available": False}

    try:
        # 获取今日行星位置
        today = datetime.now().date()
        positions = _calculate_daily_positions(today)

        return {
            "status": "success",
            "message": "flatlib 可用",
            "available": True,
            "today": today.isoformat(),
            "sun_position": positions.get("Sun", {})
        }
    except Exception as e:
        return {"status": "error", "message": f"flatlib 测试失败: {str(e)}", "available": False}