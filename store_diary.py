# -*- coding: utf-8 -*-
"""日记：她的私人日记。

以前是终端插件目录下的 txt 文件（`diary/2026/11/13/我的日记….txt`），
现在归记忆库保管——回忆类的东西都在这一边，终端只管「当下」。
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import Dict
from typing import List

if TYPE_CHECKING:  # 只给类型检查看
    from .store_util import _bot_filter, _now
else:
    try:
        from .store_util import _bot_filter, _now
    except ImportError:
        from store_util import _bot_filter, _now

if TYPE_CHECKING:
    from .store_types import StoreLike as _StoreBase
else:
    _StoreBase = object


class DiaryMixin(_StoreBase):
    def diary_put(self, bot_id: str, day: str, text: str, title: str = "") -> bool:
        day = str(day or "").strip()
        body = str(text or "")
        if not day or not body.strip():
            return False
        with self.lock:
            self.conn.execute(
                "INSERT INTO diary(bot_id, day, title, text, updated) VALUES(?,?,?,?,?) "
                "ON CONFLICT(bot_id, day) DO UPDATE SET title=excluded.title, "
                "text=excluded.text, updated=excluded.updated",
                (str(bot_id), day, str(title or "")[:80], body, _now()),
            )
            self.conn.commit()
        return True

    def diary_get(self, bot_id: str, day: str) -> str:
        with self.lock:
            row = self.conn.execute(
                "SELECT text FROM diary WHERE bot_id=? AND day=?", (str(bot_id), str(day))
            ).fetchone()
        return str(row["text"] or "") if row else ""

    def diary_list(self, bot_id: str = "") -> List[Dict[str, Any]]:
        where, params = _bot_filter(bot_id)
        with self.lock:
            rows = self.conn.execute(
                "SELECT day, title, length(text) AS chars, updated FROM diary WHERE 1=1"
                + where + " ORDER BY day DESC", params,
            ).fetchall()
        return [dict(row) for row in rows]

    def diary_delete(self, bot_id: str, day: str) -> bool:
        with self.lock:
            cur = self.conn.execute(
                "DELETE FROM diary WHERE bot_id=? AND day=?", (str(bot_id), str(day))
            )
            self.conn.commit()
            return bool(cur.rowcount)

    def diary_count(self, bot_id: str = "") -> int:
        where, params = _bot_filter(bot_id)
        with self.lock:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM diary WHERE 1=1" + where, params
            ).fetchone()
        return int((row["n"] if row else 0) or 0)
