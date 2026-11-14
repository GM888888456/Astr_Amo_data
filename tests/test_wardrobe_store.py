# -*- coding: utf-8 -*-
"""衣柜存记忆库：只存数据，搭配规则仍在终端。"""

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


def _item(item_id="w0000000001", name="粉色卫衣", **kw):
    data = {"id": item_id, "name": name, "slot": "top", "scenes": ["casual"],
            "gender": "女", "note": "", "enabled": True, "created": 100.0}
    data.update(kw)
    return data


class WardrobeStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = _tmpdir()
        self.store = DataStore(os.path.join(self.tmp, "w.db"))

    def tearDown(self):
        self.store.close()

    def test_save_and_list(self):
        self.assertTrue(self.store.wardrobe_save(BOT, _item()))
        rows = self.store.wardrobe_rows(BOT)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "粉色卫衣")
        self.assertEqual(rows[0]["scenes"], ["casual"])
        self.assertTrue(rows[0]["enabled"])

    def test_bot_isolation(self):
        self.store.wardrobe_save("b1", _item())
        self.store.wardrobe_save("b2", _item("w0000000002", "牛仔裤"))
        self.assertEqual(len(self.store.wardrobe_rows("b1")), 1)
        self.assertEqual(len(self.store.wardrobe_rows("b2")), 1)
        self.assertEqual(self.store.wardrobe_rows("b1")[0]["name"], "粉色卫衣")

    def test_save_is_upsert_and_keeps_created(self):
        self.store.wardrobe_save(BOT, _item())
        self.store.wardrobe_save(BOT, _item(name="米色卫衣"))
        rows = self.store.wardrobe_rows(BOT)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "米色卫衣")
        self.assertEqual(rows[0]["created"], 100.0)

    def test_only_enabled_and_count(self):
        self.store.wardrobe_save(BOT, _item())
        self.store.wardrobe_save(BOT, _item("w0000000002", "旧毛衣", enabled=False))
        self.assertEqual(len(self.store.wardrobe_rows(BOT)), 2)
        self.assertEqual(len(self.store.wardrobe_rows(BOT, only_enabled=True)), 1)
        self.assertEqual(self.store.wardrobe_count(BOT), 1)
        self.assertEqual(self.store.wardrobe_count(BOT, only_enabled=False), 2)

    def test_replace_all_is_full_swap(self):
        self.store.wardrobe_save(BOT, _item())
        n = self.store.wardrobe_replace_all(BOT, [
            _item("w2", "连衣裙", slot="dress"),
            _item("w3", "JK 格裙", slot="jk_skirt"),
        ])
        self.assertEqual(n, 2)
        names = [row["name"] for row in self.store.wardrobe_rows(BOT)]
        self.assertEqual(names, ["连衣裙", "JK 格裙"])

    def test_replace_all_skips_incomplete_rows(self):
        n = self.store.wardrobe_replace_all(BOT, [{"name": ""}, {"id": "w9"}, _item()])
        self.assertEqual(n, 1)

    def test_delete_and_clear(self):
        self.store.wardrobe_save(BOT, _item())
        self.store.wardrobe_save(BOT, _item("w2", "牛仔裤", slot="bottom"))
        self.assertTrue(self.store.wardrobe_delete(BOT, "w0000000001"))
        self.assertFalse(self.store.wardrobe_delete(BOT, "w0000000001"))
        self.assertEqual(self.store.wardrobe_clear(BOT), 1)
        self.assertEqual(self.store.wardrobe_rows(BOT), [])

    def test_scenes_survive_json_roundtrip(self):
        self.store.wardrobe_save(BOT, _item(scenes=["work", "formal"]))
        self.assertEqual(self.store.wardrobe_rows(BOT)[0]["scenes"], ["work", "formal"])


if __name__ == "__main__":
    unittest.main()
