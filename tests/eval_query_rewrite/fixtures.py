"""
query_rewrite 评估用例。

每条 fixture 描述一个场景，覆盖三个核心行为：
  1. 补全：query 无偏好时，从画像补全结构化偏好字段
  2. 冲突解析：query 与画像矛盾时，以 query 为准
  3. 工具调用：画像非空时，ReAct agent 应主动查询
"""

FIXTURES = [
    {
        "id": "no-pref-supplement",
        "description": "原始 query 无任何偏好，画像三项均有数据 → 三字段应从画像补全",
        "query": "南京3日游，2026-06-10到2026-06-12",
        "intent_attraction": None,
        "intent_food": None,
        "intent_habit": None,
        "profile": {
            "attraction_prefs": ["夜景", "历史古迹"],
            "food_prefs": ["火锅", "辣味美食"],
            "habit_prefs": ["慢节奏", "喜欢早起"],
        },
        "expectations": {
            "tool_should_be_called": True,
            "supplement_check": [
                "attraction_preference",
                "food_preference",
                "habit_preference",
            ],
            "conflict_field": None,
            "conflict_must_not_contain": [],
        },
    },
    {
        "id": "conflict-food-query-wins",
        "description": "query 明确表示不吃辣，画像偏好辣味/火锅 → food_preference 不应含辣相关词",
        "query": "南京3日游，2026-06-10到2026-06-12，我不喜欢吃辣，也不太想吃火锅",
        "intent_attraction": None,
        "intent_food": "不吃辣",
        "intent_habit": None,
        "profile": {
            "attraction_prefs": ["夜景"],
            "food_prefs": ["火锅", "辣味美食", "麻辣烫"],
            "habit_prefs": ["慢节奏"],
        },
        "expectations": {
            "tool_should_be_called": True,
            # 此用例核心测冲突解析（g_conflict），supplement 只验习惯字段
            # attraction_preference 可能被 LLM 归入 habit 字段，不强制
            "supplement_check": ["habit_preference"],
            "conflict_field": "food_preference",
            # 只检查画像里的具体正向偏好词——它们只会在冲突解析失败时出现
            # "不吃火锅"/"不吃辣" 是正确解析，不在此列
            "conflict_must_not_contain": ["辣味美食", "麻辣烫"],
        },
    },
    {
        "id": "partial-merge",
        "description": "query 提到景点偏好（历史古迹），画像有餐饮/习惯偏好 → 景点合并，餐饮/习惯从画像补全",
        "query": "南京3日游，2026-06-10到2026-06-12，喜欢参观历史景点和博物馆",
        "intent_attraction": "历史古迹、博物馆",
        "intent_food": None,
        "intent_habit": None,
        "profile": {
            "attraction_prefs": ["夜景"],
            "food_prefs": ["本地小吃", "淮扬菜"],
            "habit_prefs": ["不喜欢早起"],
        },
        "expectations": {
            "tool_should_be_called": True,
            "supplement_check": ["food_preference", "habit_preference"],
            "conflict_field": None,
            "conflict_must_not_contain": [],
        },
    },
    {
        "id": "empty-profile",
        "description": "画像为空，query 有景点偏好 → 不应发明偏好，工具可以调用但应优雅返回暂无画像",
        "query": "南京3日游，2026-06-10到2026-06-12，喜欢历史古迹",
        "intent_attraction": "历史古迹",
        "intent_food": None,
        "intent_habit": None,
        "profile": {
            "attraction_prefs": [],
            "food_prefs": [],
            "habit_prefs": [],
        },
        "expectations": {
            # 画像为空，工具调用与否取决于 agent 判断，不强制
            "tool_should_be_called": False,
            "supplement_check": [],  # 画像空，不要求补全
            "conflict_field": None,
            "conflict_must_not_contain": [],
        },
    },
    {
        "id": "no-pref-both",
        "description": "query 无偏好，画像也为空 → 三字段均应为 None，不应凭空发明内容",
        "query": "南京3日游，2026-06-10到2026-06-12",
        "intent_attraction": None,
        "intent_food": None,
        "intent_habit": None,
        "profile": {
            "attraction_prefs": [],
            "food_prefs": [],
            "habit_prefs": [],
        },
        "expectations": {
            "tool_should_be_called": False,
            "supplement_check": [],
            "conflict_field": None,
            "conflict_must_not_contain": [],
            # 额外检查：三字段均应为 None
            "all_prefs_none": True,
        },
    },
]

FIXTURE_INDEX = {fx["id"]: fx for fx in FIXTURES}
