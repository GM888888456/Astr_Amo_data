# -*- coding: utf-8 -*-
"""生存状态（饱食度/水分/食材柜）：衰减必须按真实时间差算。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from store import DataStore  # noqa: E402
from store_vitals import Hunger, hunger_of  # noqa: E402

BOT = "陪伴"
T0 = 1_700_000_000.0
HOUR = 3600.0


class VitalsCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DataStore(os.path.join(self.tmp.name, "t.db"))
        self.store.vitals_tick(BOT, now=T0)

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_first_tick_does_not_decay(self) -> None:
        data = self.store.vitals_get(BOT)
        self.assertEqual(round(data["satiety"], 1), 80.0)
        self.assertEqual(round(data["hydration"], 1), 80.0)

    def test_four_hours_costs_ten_satiety(self) -> None:
        data = self.store.vitals_tick(BOT, now=T0 + 4 * HOUR)
        self.assertEqual(round(data["satiety"], 1), 70.0)
        # 水分掉得快：2 小时 -10
        self.assertEqual(round(data["hydration"], 1), 60.0)

    def test_restart_does_not_lose_time(self) -> None:
        """隔了 10 小时才结算一次，和每小时结算结果必须一样。"""
        self.store.vitals_tick(BOT, now=T0 + 10 * HOUR)
        jumped = self.store.vitals_get(BOT)

        fresh = DataStore(os.path.join(self.tmp.name, "t2.db"))
        try:
            fresh.vitals_tick(BOT, now=T0)
            for hour in range(1, 11):
                fresh.vitals_tick(BOT, now=T0 + hour * HOUR)
            stepped = fresh.vitals_get(BOT)
        finally:
            fresh.close()
        self.assertAlmostEqual(jumped["satiety"], stepped["satiety"], places=1)
        self.assertAlmostEqual(jumped["hydration"], stepped["hydration"], places=1)

    def test_eat_and_drink_clamp(self) -> None:
        at = T0 + 8 * HOUR                               # 80 - 8h x 2.5 = 60
        data = self.store.vitals_eat(BOT, 30, note="酸菜鱼", now=at)
        self.assertEqual(round(data["satiety"], 1), 90.0)
        data = self.store.vitals_eat(BOT, 999, now=at)
        self.assertEqual(round(data["satiety"], 1), 100.0)
        data = self.store.vitals_drink(BOT, 999, now=at)
        self.assertEqual(round(data["hydration"], 1), 100.0)
        # 水位线不能超过 100
        self.assertEqual(round(data["satiety"], 1), 100.0)

    def test_levels(self) -> None:
        self.assertEqual(hunger_of(100), Hunger.FULL)
        self.assertEqual(hunger_of(80), Hunger.FULL)
        self.assertEqual(hunger_of(79.9), Hunger.NORMAL)
        self.assertEqual(hunger_of(30), Hunger.NORMAL)
        self.assertEqual(hunger_of(29.9), Hunger.HUNGRY)
        self.assertEqual(hunger_of(10), Hunger.HUNGRY)
        self.assertEqual(hunger_of(9.9), Hunger.STARVING)
        self.assertEqual(hunger_of(0), Hunger.STARVING)

    def test_pantry(self) -> None:
        self.store.pantry_add(BOT, "鸡蛋", 6)
        self.assertEqual(self.store.pantry_qty(BOT, "鸡蛋"), 6)
        ok = self.store.pantry_take(BOT, "鸡蛋", 2)
        self.assertTrue(ok["ok"])
        self.assertAlmostEqual(self.store.pantry_qty(BOT, "鸡蛋"), 4)
        bad = self.store.pantry_take(BOT, "鸡蛋", 99)
        self.assertFalse(bad["ok"])
        self.assertAlmostEqual(self.store.pantry_qty(BOT, "鸡蛋"), 4, msg="不够时不能动库存")


if __name__ == "__main__":
    unittest.main()
