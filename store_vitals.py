# -*- coding: utf-8 -*-
"""生存状态：饱食度、水分、食材柜。

只做**数据和算术**，不做任何业务判断——谁该吃饭、吃得起吃不起，那是金融和终端的事。

三条设计约定：

1. **衰减按真实时间差算，不靠定时器累加。** 进程重启、机器关机、任务卡住，都不会
   让她「饿的量不对」；`tick` 只是把该扣的扣掉，随时可以补算。
2. **表是懒建的。** 不去动 `store_schema.py` 的建表脚本，避免和迁移、备份、快照
   搅在一起；第一次用到时 `CREATE TABLE IF NOT EXISTS` 即可。
3. **只写自己的两张表。** `vitals` 一行一个人格，`pantry` 一行一种食材。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
import time

if TYPE_CHECKING:  # 只给类型检查看
    from .store_util import logger
else:  # 运行时：包模式优先，按文件直接加载时退回绝对导入
    try:
        from .store_util import logger
    except ImportError:  # 直接按文件加载时
        from store_util import logger


if TYPE_CHECKING:
    from .store_types import StoreLike as _StoreBase
else:  # 运行时用 object：协议里的声明不能进 MRO
    _StoreBase = object


# ---------------------------------------------------------------------------
# 饥饿档位
# ---------------------------------------------------------------------------

class Hunger:
    """饥饿档位。用字符串常量而不是 Enum，方便直接进 JSON / 写库。"""

    FULL = "full"          # 饱腹
    NORMAL = "normal"      # 正常
    HUNGRY = "hungry"      # 饥饿
    STARVING = "starving"  # 极度饥饿

    LABELS = {
        FULL: "饱腹",
        NORMAL: "正常",
        HUNGRY: "饥饿",
        STARVING: "极度饥饿",
    }

    ALL = (FULL, NORMAL, HUNGRY, STARVING)

    @classmethod
    def label(cls, level: str) -> str:
        return cls.LABELS.get(str(level or ""), "正常")


def hunger_of(satiety: float, full: float = 80.0, hungry: float = 30.0,
              starving: float = 10.0) -> str:
    """饱食度 → 档位。阈值可配，但**默认就是需求里的 30 / 10**。"""
    try:
        # 先四舍五入到 0.1：不然 80 掉了一秒就变 79.99，面板上还显示 80，
        # 档位却已经跳到「正常」，看着像 bug。
        value = round(float(satiety), 1)
    except (TypeError, ValueError):
        value = 0.0
    if value >= float(full):
        return Hunger.FULL
    if value >= float(hungry):
        return Hunger.NORMAL
    if value >= float(starving):
        return Hunger.HUNGRY
    return Hunger.STARVING


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 每小时的衰减量：饱食 4 小时 -10，水分 2 小时 -10。
SATIETY_PER_HOUR = 2.5
HYDRATION_PER_HOUR = 5.0

#: 新建时的初值。80 是「刚吃过但不是撑」。
DEFAULT_SATIETY = 80.0
DEFAULT_HYDRATION = 80.0

#: 兜底 tick 间隔（分钟）：后台任务多久把时间差结算一次。
DEFAULT_TICK_MINUTES = 30


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


class VitalsMixin(_StoreBase):
    """饱食度 / 水分 / 食材柜。（表懒建，见模块说明）"""

    _vitals_ready = False

    # ---------------------------------------------------------------- 建表

    def _ensure_vitals_schema(self) -> None:
        if getattr(self, "_vitals_ready", False):
            return
        with self.lock:
            conn = self.conn
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS vitals (
                    bot_id     TEXT PRIMARY KEY,
                    satiety    REAL NOT NULL DEFAULT 80,
                    hydration  REAL NOT NULL DEFAULT 80,
                    ticked_at  REAL NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL DEFAULT 0,
                    note       TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS pantry (
                    bot_id     TEXT NOT NULL,
                    item       TEXT NOT NULL,
                    qty        REAL NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY (bot_id, item)
                );
                """
            )
            self._vitals_ready = True

    # ---------------------------------------------------------------- 读

    def vitals_get(self, bot_id: str) -> Dict[str, Any]:
        """读当前状态。**不结算衰减**——要结算用 `vitals_tick`。"""
        self._ensure_vitals_schema()
        bot = str(bot_id or "")
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM vitals WHERE bot_id=?", (bot,)
            ).fetchone()
        if row is None:
            now = time.time()
            return {
                "bot_id": bot,
                "satiety": DEFAULT_SATIETY,
                "hydration": DEFAULT_HYDRATION,
                "level": hunger_of(DEFAULT_SATIETY),
                "label": Hunger.label(hunger_of(DEFAULT_SATIETY)),
                "ticked_at": now,
                "updated_at": now,
                "note": "",
                "existed": False,
            }
        return self._vitals_row(row)

    def _vitals_row(self, row: Any, now: float = 0.0) -> Dict[str, Any]:
        satiety = _clamp(row["satiety"])
        hydration = _clamp(row["hydration"])
        level = hunger_of(satiety)
        return {
            "bot_id": row["bot_id"],
            "satiety": round(satiety, 1),
            "hydration": round(hydration, 1),
            "level": level,
            "label": Hunger.label(level),
            "ticked_at": float(row["ticked_at"] or 0),
            "updated_at": float(row["updated_at"] or 0),
            "note": str(row["note"] or ""),
            "existed": True,
        }

    # ---------------------------------------------------------------- 结算

    def vitals_tick(self, bot_id: str, now: Optional[float] = None) -> Dict[str, Any]:
        """按真实时间差扣饱食度/水分，写回并返回新状态。

        第一次调用只落初值、不扣（`ticked_at` 从当前时间起算）。
        """
        self._ensure_vitals_schema()
        bot = str(bot_id or "")
        stamp = float(now if now is not None else time.time())
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM vitals WHERE bot_id=?", (bot,)
            ).fetchone()
            if row is None:
                self.conn.execute(
                    "INSERT INTO vitals(bot_id, satiety, hydration, ticked_at, updated_at)"
                    " VALUES(?,?,?,?,?)",
                    (bot, DEFAULT_SATIETY, DEFAULT_HYDRATION, stamp, stamp),
                )
                self.conn.commit()
                row = self.conn.execute(
                    "SELECT * FROM vitals WHERE bot_id=?", (bot,)
                ).fetchone()
            last = float(row["ticked_at"] or 0)
            delta = stamp - last
            if delta <= 0:
                return self._vitals_row(row)
            hours = delta / 3600.0
            satiety = _clamp(float(row["satiety"]) - hours * SATIETY_PER_HOUR)
            hydration = _clamp(float(row["hydration"]) - hours * HYDRATION_PER_HOUR)
            self.conn.execute(
                "UPDATE vitals SET satiety=?, hydration=?, ticked_at=?, updated_at=?"
                " WHERE bot_id=?",
                (satiety, hydration, stamp, stamp, bot),
            )
            self.conn.commit()
            row = self.conn.execute(
                "SELECT * FROM vitals WHERE bot_id=?", (bot,)
            ).fetchone()
        return self._vitals_row(row)

    # ---------------------------------------------------------------- 写

    def vitals_eat(self, bot_id: str, amount: float, note: str = "",
                   now: Optional[float] = None) -> Dict[str, Any]:
        """吃东西：饱食度 +amount（上限 100）。内部先结算衰减，别拿旧值加。

        ``now`` 只给测试用；生产环境留空就是当前时间。
        """
        current = self.vitals_tick(bot_id, now)
        target = _clamp(float(current["satiety"]) + max(0.0, float(amount)))
        return self._vitals_write(str(bot_id or ""), satiety=target, note=note)

    def vitals_drink(self, bot_id: str, amount: float, note: str = "",
                     now: Optional[float] = None) -> Dict[str, Any]:
        """喝水：水分 +amount（上限 100）。``now`` 只给测试用。"""
        current = self.vitals_tick(bot_id, now)
        target = _clamp(float(current["hydration"]) + max(0.0, float(amount)))
        return self._vitals_write(str(bot_id or ""), hydration=target, note=note)

    def vitals_set(self, bot_id: str, satiety: Optional[float] = None,
                   hydration: Optional[float] = None, note: str = "") -> Dict[str, Any]:
        """面板/调试用：直接设值。业务代码不要用它（会绕过吃饭逻辑）。"""
        return self._vitals_write(str(bot_id or ""), satiety=satiety,
                                  hydration=hydration, note=note)

    def _vitals_write(self, bot: str, satiety: Optional[float] = None,
                      hydration: Optional[float] = None, note: str = "") -> Dict[str, Any]:
        self._ensure_vitals_schema()
        now = time.time()
        with self.lock:
            self.conn.execute(
                "INSERT INTO vitals(bot_id, satiety, hydration, ticked_at, updated_at, note)"
                " VALUES(?,?,?,?,?,?) ON CONFLICT(bot_id) DO NOTHING",
                (bot, DEFAULT_SATIETY, DEFAULT_HYDRATION, now, now, ""),
            )
            fields: List[str] = ["updated_at=?"]
            params: List[Any] = [now]
            if satiety is not None:
                fields.append("satiety=?")
                params.append(_clamp(satiety))
            if hydration is not None:
                fields.append("hydration=?")
                params.append(_clamp(hydration))
            if note:
                fields.append("note=?")
                params.append(str(note)[:200])
            params.append(bot)
            self.conn.execute(
                "UPDATE vitals SET %s WHERE bot_id=?" % ", ".join(fields), params
            )
            self.conn.commit()
            row = self.conn.execute(
                "SELECT * FROM vitals WHERE bot_id=?", (bot,)
            ).fetchone()
        return self._vitals_row(row)

    # ---------------------------------------------------------------- 食材柜

    def pantry_list(self, bot_id: str) -> List[Dict[str, Any]]:
        self._ensure_vitals_schema()
        with self.lock:
            rows = self.conn.execute(
                "SELECT item, qty, updated_at FROM pantry WHERE bot_id=? AND qty>0"
                " ORDER BY item", (str(bot_id or ""),)
            ).fetchall()
        return [
            {"item": r["item"], "qty": round(float(r["qty"]), 2),
             "updated_at": float(r["updated_at"] or 0)}
            for r in rows
        ]

    def pantry_qty(self, bot_id: str, item: str) -> float:
        self._ensure_vitals_schema()
        with self.lock:
            row = self.conn.execute(
                "SELECT qty FROM pantry WHERE bot_id=? AND item=?",
                (str(bot_id or ""), str(item or "")),
            ).fetchone()
        return float(row["qty"]) if row else 0.0

    def pantry_add(self, bot_id: str, item: str, qty: float = 1.0) -> Dict[str, Any]:
        """买回来的食材进柜。数量用「份」，浮点，够用就行。"""
        self._ensure_vitals_schema()
        bot, name = str(bot_id or ""), str(item or "").strip()
        if not name:
            return {"ok": False, "reason": "食材名不能为空"}
        now = time.time()
        with self.lock:
            self.conn.execute(
                "INSERT INTO pantry(bot_id, item, qty, updated_at) VALUES(?,?,?,?)"
                " ON CONFLICT(bot_id, item) DO UPDATE SET qty=qty+excluded.qty,"
                " updated_at=excluded.updated_at",
                (bot, name, max(0.0, float(qty)), now),
            )
            self.conn.commit()
        return {"ok": True, "item": name, "qty": round(self.pantry_qty(bot, name), 2)}

    def pantry_take(self, bot_id: str, item: str, qty: float = 1.0) -> Dict[str, Any]:
        """做饭消耗食材。**不够就不动**，够不够由调用方先问。"""
        self._ensure_vitals_schema()
        bot, name = str(bot_id or ""), str(item or "").strip()
        want = max(0.0, float(qty))
        have = self.pantry_qty(bot, name)
        if have < want:
            return {"ok": False, "item": name, "have": round(have, 2),
                    "need": round(want, 2), "reason": "食材不够"}
        with self.lock:
            self.conn.execute(
                "UPDATE pantry SET qty=?, updated_at=? WHERE bot_id=? AND item=?",
                (have - want, time.time(), bot, name),
            )
            self.conn.commit()
        return {"ok": True, "item": name, "left": round(have - want, 2)}

    def pantry_clear(self, bot_id: str) -> int:
        self._ensure_vitals_schema()
        with self.lock:
            cur = self.conn.execute("DELETE FROM pantry WHERE bot_id=?",
                                    (str(bot_id or ""),))
            self.conn.commit()
        return int(cur.rowcount or 0)
