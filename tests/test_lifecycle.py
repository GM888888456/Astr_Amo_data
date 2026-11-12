# -*- coding: utf-8 -*-
"""记忆生命周期：谁会忘、谁永远不会忘。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lifecycle import (  # noqa: E402
    EVENT_ARCHIVE_DAYS,
    EVENT_DELETE_DAYS,
    EVENT_FADE_DAYS,
    cleanup_plan,
    fade_weight,
    should_pin,
    tier_for,
)

DAY = 86400
NOW = 1_800_000_000


def row(**kw):
    base = {"created_at": NOW, "tier": "event", "pinned": 0, "importance": 0.5}
    base.update(kw)
    return base


class TierTests(unittest.TestCase):
    def test_core_kinds(self):
        for kind in ("relationship", "asset", "profile", "preference", "daily_look"):
            self.assertEqual(tier_for(kind), "core", kind)

    def test_event_kinds(self):
        for kind in ("expense", "weather_alert", "route", "draw_record"):
            self.assertEqual(tier_for(kind), "event", kind)

    def test_unknown_defaults_to_fact(self):
        """认不出来的 kind 必须按「保留」处理——删错不可逆。"""
        self.assertEqual(tier_for("某个新模块的怪kind"), "fact")

    def test_empty_kind(self):
        self.assertEqual(tier_for(""), "fact")

    def test_typo_in_event_kind_is_safe(self):
        """event 拼错一个字母，最坏结果是「没删掉」，不是「删错」。"""
        self.assertEqual(tier_for("expence"), "fact")


class PinTests(unittest.TestCase):
    def test_core_always_pinned(self):
        self.assertTrue(should_pin("relationship", 0.1))

    def test_event_not_pinned(self):
        self.assertFalse(should_pin("expense", 0.5))

    def test_high_importance_fact_pinned(self):
        self.assertTrue(should_pin("fact", 0.95))

    def test_low_importance_fact_not_pinned(self):
        self.assertFalse(should_pin("fact", 0.3))


class PlanTests(unittest.TestCase):
    def test_fresh_event_kept(self):
        self.assertEqual(cleanup_plan(row(created_at=NOW - 2 * DAY), NOW), "keep")

    def test_event_fades_after_7_days(self):
        self.assertEqual(cleanup_plan(row(created_at=NOW - 8 * DAY), NOW), "fade")

    def test_event_archived_and_deleted_after_14_days(self):
        """7 天降权、14 天删除：没有再单独留一个「归档期」。"""
        at_archive = cleanup_plan(row(created_at=NOW - (EVENT_ARCHIVE_DAYS - 1) * DAY), NOW)
        self.assertEqual(at_archive, "fade")
        self.assertEqual(
            cleanup_plan(row(created_at=NOW - (EVENT_ARCHIVE_DAYS + 1) * DAY), NOW),
            "delete",
        )

    def test_event_deleted_after_14_days(self):
        self.assertEqual(
            cleanup_plan(row(created_at=NOW - (EVENT_DELETE_DAYS + 1) * DAY), NOW),
            "delete",
        )
        self.assertEqual(EVENT_DELETE_DAYS, 14)

    def test_core_never_deleted(self):
        self.assertEqual(
            cleanup_plan(row(tier="core", created_at=NOW - 999 * DAY), NOW), "keep"
        )

    def test_fact_never_deleted(self):
        self.assertEqual(
            cleanup_plan(row(tier="fact", created_at=NOW - 999 * DAY), NOW), "keep"
        )

    def test_pinned_never_deleted(self):
        self.assertEqual(
            cleanup_plan(row(pinned=1, created_at=NOW - 999 * DAY), NOW), "keep"
        )

    def test_missing_created_at_is_safe(self):
        self.assertEqual(cleanup_plan(row(created_at=0), NOW), "keep")

    def test_garbage_input(self):
        self.assertEqual(cleanup_plan({}, NOW), "keep")
        self.assertEqual(cleanup_plan(None, NOW), "keep")


class WeightTests(unittest.TestCase):
    def test_fresh_full_weight(self):
        self.assertEqual(fade_weight(row(created_at=NOW - DAY), NOW), 1.0)

    def test_faded_reduced(self):
        self.assertLess(fade_weight(row(created_at=NOW - 9 * DAY), NOW), 1.0)

    def test_archived_zero(self):
        self.assertEqual(
            fade_weight(row(created_at=NOW - 20 * DAY), NOW), 0.0
        )

    def test_core_full_weight_forever(self):
        self.assertEqual(
            fade_weight(row(tier="core", created_at=NOW - 999 * DAY), NOW), 1.0
        )


class ConstantTests(unittest.TestCase):
    def test_ordering(self):
        self.assertLess(EVENT_FADE_DAYS, EVENT_DELETE_DAYS)
        self.assertEqual(EVENT_ARCHIVE_DAYS, EVENT_DELETE_DAYS, "归档和删除是同一天")


if __name__ == "__main__":
    unittest.main()
