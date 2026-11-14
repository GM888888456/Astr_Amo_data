# -*- coding: utf-8 -*-
"""日记存记忆库：以前是终端目录下的 txt 文件。"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from store import DataStore  # noqa: E402

BOT = "b"


def _tmpdir() -> str:
    base = os.environ.get("AMO_DATA_TEST_TMP") or tempfile.gettempdir()
    os.makedirs(base, exist_ok=True)
    return tempfile.mkdtemp(dir=base)


class DiaryStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = _tmpdir()
        self.store = DataStore(os.path.join(self.tmp, "d.db"))

    def tearDown(self):
        self.store.close()

    def test_put_and_get(self):
        self.assertTrue(self.store.diary_put(BOT, "2026-11-13", "今天很累", "我的日记"))
        self.assertEqual(self.store.diary_get(BOT, "2026-11-13"), "今天很累")

    def test_put_overwrites_same_day(self):
        self.store.diary_put(BOT, "2026-11-13", "旧内容")
        self.store.diary_put(BOT, "2026-11-13", "新内容")
        self.assertEqual(self.store.diary_get(BOT, "2026-11-13"), "新内容")
        self.assertEqual(self.store.diary_count(BOT), 1)

    def test_empty_text_is_rejected(self):
        self.assertFalse(self.store.diary_put(BOT, "2026-11-13", "   "))
        self.assertEqual(self.store.diary_count(BOT), 0)

    def test_list_sorted_newest_first(self):
        self.store.diary_put(BOT, "2026-11-11", "a")
        self.store.diary_put(BOT, "2026-11-13", "c")
        days = [row["day"] for row in self.store.diary_list(BOT)]
        self.assertEqual(days, ["2026-11-13", "2026-11-11"])

    def test_delete(self):
        self.store.diary_put(BOT, "2026-11-13", "a")
        self.assertTrue(self.store.diary_delete(BOT, "2026-11-13"))
        self.assertFalse(self.store.diary_delete(BOT, "2026-11-13"))
        self.assertEqual(self.store.diary_get(BOT, "2026-11-13"), "")

    def test_bot_isolation(self):
        self.store.diary_put("b1", "2026-11-13", "一号")
        self.store.diary_put("b2", "2026-11-13", "二号")
        self.assertEqual(self.store.diary_get("b1", "2026-11-13"), "一号")
        self.assertEqual(self.store.diary_get("b2", "2026-11-13"), "二号")


if __name__ == "__main__":
    unittest.main()
