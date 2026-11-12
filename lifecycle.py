# -*- coding: utf-8 -*-
"""记忆的生命周期：哪些会忘、哪些永远不忘。

遗忘是做减法，最容易做错——**删掉一条关系事实，不是「她忘了」，是「她换了个人」**。
所以这里的原则只有一条：

    **拿不准就保留。** 删除不可逆，猜错的方向必须是安全的那个。

分三层：

- ``core``：关系、资产、职业、城市、偏好、当日 look —— **永不进删除队列**；
- ``fact``：约定、共同经历、礼物事实 —— 只降权，不自动删；
- ``event``：单次流水、临时提醒、行程 —— 7 天降权、14 天真删。

``kind`` 是各模块自由填的字符串，**不能直接当 TTL 依据**（一个笔误就能删错东西）。
这里把它映射成 tier，映射不到的按 ``fact`` 处理——也就是保留。
"""

from __future__ import annotations

#: 明确属于「事件流水」的 kind：这些可以删。
EVENT_KINDS = frozenset({
    "weather_alert", "reminder", "temporary", "draw_record", "photo_record",
    "expense", "bill", "route", "travel_snippet", "outfit_history",
    "event", "ephemeral", "notice", "share_record",
})

#: 明确属于「核心状态」的 kind：这些永远不删。
CORE_KINDS = frozenset({
    "relationship", "relation", "asset", "finance_core", "profile", "preference",
    "identity", "bot_id", "daily_look", "city", "habit", "pinned",
})

#: 两段策略（天）。改这里就改了全部行为。
EVENT_FADE_DAYS = 7      # 之后降权，只有被明确检索才出
EVENT_DELETE_DAYS = 14   # 之后真删
#: 兼容旧名字：现在没有单独的「归档期」，归档和删除是同一天（先归档再删）。
#: 留着这个常量是因为外部代码和返回值里还在用它。
EVENT_ARCHIVE_DAYS = EVENT_DELETE_DAYS

TIER_CORE = "core"
TIER_FACT = "fact"
TIER_EVENT = "event"


def tier_for(kind: str, importance: float = 0.5) -> str:
    """按 kind 判 tier。认不出的一律 fact（= 不删）。"""
    key = str(kind or "").strip().lower()
    if not key:
        return TIER_FACT
    if key in CORE_KINDS:
        return TIER_CORE
    if key in EVENT_KINDS:
        return TIER_EVENT
    # 重要性很高的，即使 kind 没登记也当事实
    try:
        if float(importance) >= 0.85:
            return TIER_FACT
    except Exception:
        pass
    return TIER_FACT


def should_pin(kind: str, importance: float = 0.5) -> bool:
    """要不要永久钉住。

    core 自动钉；fact 里重要性 >= 0.9 的也钉——那多半是用户反复强调过的事。
    """
    tier = tier_for(kind, importance)
    if tier == TIER_CORE:
        return True
    try:
        return tier == TIER_FACT and float(importance) >= 0.9
    except Exception:
        return False


def cleanup_plan(row: dict, now: int) -> str:
    """给一条记忆定性：keep / fade / archive / delete。

    只对 event 层做处置；core / fact 一律 keep。pinned 永远 keep。
    """
    if not isinstance(row, dict):
        return "keep"
    if int(row.get("pinned") or 0):
        return "keep"
    tier = str(row.get("tier") or TIER_FACT)
    if tier != TIER_EVENT:
        return "keep"
    created = int(row.get("created_at") or 0)
    if created <= 0:
        return "keep"
    age_days = (now - created) / 86400.0
    if age_days >= EVENT_DELETE_DAYS:
        return "delete"
    if age_days >= EVENT_FADE_DAYS:
        return "fade"
    return "keep"


def fade_weight(row: dict, now: int) -> float:
    """召回排序用的权重：过期的 event 要往下压，但压不死。"""
    plan = cleanup_plan(row, now)
    if plan == "keep":
        return 1.0
    if plan == "fade":
        return 0.6
    return 0.0
