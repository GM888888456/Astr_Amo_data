# -*- coding: utf-8 -*-
"""衣柜：她的衣服库。

以前存在终端插件的 ``wardrobe.json`` 里，现在由记忆库统一保管。

这里只存**数据**，不存搭配规则：什么场合穿什么、JK 衬衣只能配 JK 格裙，
这些判定留在终端（终端是唯一大脑），记忆库只管记住她有哪些衣服。
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING
from typing import Any
from typing import Dict
from typing import List

if TYPE_CHECKING:  # 只给类型检查看
    from .store_util import _bot_filter, _now
else:  # 运行时：包模式优先，按文件直接加载时退回绝对导入
    try:
        from .store_util import _bot_filter, _now
    except ImportError:  # 直接按文件加载时
        from store_util import _bot_filter, _now

if TYPE_CHECKING:
    from .store_types import StoreLike as _StoreBase
else:  # 运行时用 object：协议里的声明不能进 MRO
    _StoreBase = object


class WardrobeMixin(_StoreBase):
    """wardrobe 表：一件衣服一行，id 由终端生成（`w` + 十位十六进制）。"""

    @staticmethod
    def _wardrobe_row(row: Any) -> Dict[str, Any]:
        item = dict(row)
        try:
            scenes = json.loads(item.get("scenes") or "[]")
        except Exception:
            scenes = []
        item["scenes"] = [str(scene) for scene in scenes if scene] if isinstance(scenes, list) else []
        item["enabled"] = bool(item.get("enabled", 1))
        item["created"] = float(item.get("created") or 0)
        return item

    def wardrobe_rows(self, bot_id: str = "", only_enabled: bool = False) -> List[Dict[str, Any]]:
        where, params = _bot_filter(bot_id)
        sql = ("SELECT id, name, slot, scenes, gender, note, enabled, created "
               "FROM wardrobe WHERE 1=1" + where)
        if only_enabled:
            sql += " AND enabled=1"
        sql += " ORDER BY created ASC, id ASC"
        with self.lock:
            rows = self.conn.execute(sql, params).fetchall()
        return [self._wardrobe_row(row) for row in rows]

    def wardrobe_count(self, bot_id: str = "", only_enabled: bool = True) -> int:
        where, params = _bot_filter(bot_id)
        sql = "SELECT COUNT(*) AS n FROM wardrobe WHERE 1=1" + where
        if only_enabled:
            sql += " AND enabled=1"
        with self.lock:
            row = self.conn.execute(sql, params).fetchone()
        return int((row["n"] if row else 0) or 0)

    def wardrobe_save(self, bot_id: str, item: Dict[str, Any]) -> bool:
        """新增或更新一件衣服（按 id upsert）。"""
        if not isinstance(item, dict):
            return False
        item_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        if not item_id or not name:
            return False
        scenes = item.get("scenes")
        if not isinstance(scenes, list):
            scenes = []
        payload = json.dumps([str(scene) for scene in scenes if scene], ensure_ascii=False)
        with self.lock:
            self.conn.execute(
                "INSERT INTO wardrobe(bot_id, id, name, slot, scenes, gender, note, enabled, created, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(bot_id, id) DO UPDATE SET "
                "name=excluded.name, slot=excluded.slot, scenes=excluded.scenes, "
                "gender=excluded.gender, note=excluded.note, enabled=excluded.enabled, "
                "updated_at=excluded.updated_at",
                (str(bot_id), item_id, name[:40], str(item.get("slot") or "")[:16], payload,
                 str(item.get("gender") or "通用")[:8], str(item.get("note") or "")[:120],
                 1 if item.get("enabled", True) else 0, float(item.get("created") or 0), _now()),
            )
            self.conn.commit()
        return True

    def wardrobe_replace_all(self, bot_id: str, items: List[Dict[str, Any]]) -> int:
        """整库替换（第一次从终端搬过来、或按市场目录重建时用）。"""
        rows = [item for item in (items or []) if isinstance(item, dict)
                and str(item.get("id") or "").strip() and str(item.get("name") or "").strip()]
        with self.lock:
            self.conn.execute("DELETE FROM wardrobe WHERE bot_id=?", (str(bot_id),))
            for item in rows:
                scenes = item.get("scenes") if isinstance(item.get("scenes"), list) else []
                self.conn.execute(
                    "INSERT OR REPLACE INTO wardrobe(bot_id, id, name, slot, scenes, gender, note, enabled, created, updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (str(bot_id), str(item.get("id")), str(item.get("name"))[:40],
                     str(item.get("slot") or "")[:16],
                     json.dumps([str(scene) for scene in scenes if scene], ensure_ascii=False),
                     str(item.get("gender") or "通用")[:8], str(item.get("note") or "")[:120],
                     1 if item.get("enabled", True) else 0, float(item.get("created") or 0), _now()),
                )
            self.conn.commit()
        return len(rows)

    def wardrobe_delete(self, bot_id: str, item_id: str) -> bool:
        with self.lock:
            cur = self.conn.execute(
                "DELETE FROM wardrobe WHERE bot_id=? AND id=?", (str(bot_id), str(item_id))
            )
            self.conn.commit()
            return bool(cur.rowcount)

    def wardrobe_clear(self, bot_id: str) -> int:
        with self.lock:
            cur = self.conn.execute("DELETE FROM wardrobe WHERE bot_id=?", (str(bot_id),))
            self.conn.commit()
            return max(0, cur.rowcount or 0)
