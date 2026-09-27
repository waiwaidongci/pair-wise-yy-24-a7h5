import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import DomainError, RadioDB

AIR_DATE = "2026-09-28"
WEEKDAY = date(2026, 9, 28).weekday()


class ReplacementSuggestionTest(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.db = RadioDB(self.path)
        self.news = self.db.add_program("早间新闻", "talk", 30, "2026-01-01", "2026-12-31", None, 0, ["华东"])
        self.music = self.db.add_program("晨间轻音乐", "music", 30, "2026-01-01", "2026-12-31", "青柠", 45, ["华东"])
        self.ad = self.db.add_program("青柠广告", "ad", 5, "2026-01-01", "2026-12-31", "青柠", 0, ["华东"])
        self.north_only = self.db.add_program("华北专题", "talk", 30, "2026-01-01", "2026-12-31", None, 0, ["华北"])
        self.expired = self.db.add_program("过期综艺", "talk", 30, "2026-01-01", "2026-06-30", None, 0, ["华东"])
        self.calm = self.db.add_program("午间清谈", "talk", 30, "2026-01-01", "2026-12-31", None, 0, ["华东"])
        self.db.add_sponsor_policy("青柠", 90)

    def tearDown(self):
        self.db.close()
        os.unlink(self.path)

    def _reasons(self, result, program_id):
        for item in result["ineligible"]:
            if item["program_id"] == program_id:
                return {r["category"]: r for r in item["reasons"]}
        self.fail(f"节目 {program_id} 不在不合适列表中")

    def test_candidates_sorted_by_remaining_gap_with_margins(self):
        self.db.schedule_slot(AIR_DATE, "09:00", self.music, "华东")
        self.db.schedule_slot(AIR_DATE, "14:00", self.ad, "华东")
        slot = self.db.schedule_slot(AIR_DATE, "12:00", self.news, "华东")
        result = self.db.suggest_replacements(slot)
        self.assertIsNone(result["summary"])
        self.assertEqual(slot, result["slot"]["id"])
        ids = [c["program_id"] for c in result["candidates"]]
        self.assertEqual([self.calm, self.music], ids)
        music = result["candidates"][1]
        self.assertEqual(35, music["sponsor_margin"])   # 距 14:00 广告 125 分钟，要求 90
        self.assertEqual(105, music["cooldown_margin"])  # 距 09:00 同节目 150 分钟，要求 45
        calm = result["candidates"][0]
        self.assertIsNone(calm["sponsor_margin"])
        self.assertIsNone(calm["cooldown_margin"])
        self.assertEqual("duration", self._reasons(result, self.ad)["duration"]["category"])
        self.assertIn("license", self._reasons(result, self.north_only))
        self.assertIn("license", self._reasons(result, self.expired))
        self.assertIn("current", self._reasons(result, self.news))

    def test_summary_names_blocking_categories_when_no_candidates(self):
        slot = self.db.schedule_slot(AIR_DATE, "12:00", self.news, "华东")
        self.db.add_blocked_window("华东", WEEKDAY, "12:00", "12:30", "午间检修")
        result = self.db.suggest_replacements(slot)
        self.assertEqual([], result["candidates"])
        summary = result["summary"]
        self.assertIn("没有可替换的节目", summary)
        self.assertIn("禁播时段 4 个", summary)   # music/calm/华北专题/过期综艺 均撞检修
        self.assertIn("版权授权 2 个", summary)   # 华北专题 + 过期综艺
        self.assertIn("时长不符 1 个", summary)   # 5 分钟广告
        self.assertNotIn("当前节目", summary)

    def test_time_conflict_and_cooldown_remaining(self):
        self.db.schedule_slot(AIR_DATE, "11:30", self.music, "华东")
        slot = self.db.schedule_slot(AIR_DATE, "12:00", self.news, "华东")
        # 正常流程建不出与目标时段重叠的排期，直接插入模拟历史脏数据
        self.db.conn.execute(
            "INSERT INTO slots(air_date,start_time,duration_minutes,program_id,region,created_at) VALUES(?,?,?,?,?,?)",
            (AIR_DATE, "12:15", 30, self.calm, "华东", "2026-09-01T00:00:00"),
        )
        self.db.conn.commit()
        result = self.db.suggest_replacements(slot)
        music = self._reasons(result, self.music)
        self.assertIn("conflict", music)
        self.assertEqual(45, music["cooldown"]["remaining"])  # 与 11:30 同节目间隔 0，差 45
        calm = self._reasons(result, self.calm)
        self.assertIn("conflict", calm)

    def test_sponsor_rule_remaining(self):
        self.db.schedule_slot(AIR_DATE, "12:50", self.ad, "华东")
        promo = self.db.add_program("青柠专题", "talk", 30, "2026-01-01", "2026-12-31", "青柠", 0, ["华东"])
        slot = self.db.schedule_slot(AIR_DATE, "12:00", self.news, "华东")
        result = self.db.suggest_replacements(slot)
        promo_reasons = self._reasons(result, promo)
        self.assertEqual(35, promo_reasons["sponsor"]["remaining"])  # 距广告 55 分钟，要求 90
        music = self._reasons(result, self.music)
        self.assertIn("sponsor", music)
        self.assertEqual([self.calm], [c["program_id"] for c in result["candidates"]])

    def test_requires_planned_slot(self):
        slot = self.db.schedule_slot(AIR_DATE, "12:00", self.news, "华东")
        self.db.replace_slot(slot, self.calm)
        with self.assertRaisesRegex(DomainError, "尚未播出"):
            self.db.suggest_replacements(slot)
        with self.assertRaisesRegex(DomainError, "排期不存在"):
            self.db.suggest_replacements(9999)

    def test_adopt_candidate_via_existing_replace_flow(self):
        slot = self.db.schedule_slot(AIR_DATE, "12:00", self.news, "华东")
        result = self.db.suggest_replacements(slot)
        chosen = result["candidates"][0]["program_id"]
        replaced = self.db.replace_slot(slot, chosen)
        self.assertEqual("replaced", replaced["status"])
        self.assertEqual(chosen, replaced["program_id"])
        self.assertEqual(self.news, replaced["replaced_from"])


if __name__ == "__main__":
    unittest.main()
