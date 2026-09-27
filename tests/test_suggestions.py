import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import DomainError, RadioDB


class ReplacementSuggestionTest(unittest.TestCase):
    """安全换播建议：候选排序、拒绝原因、无候选归因、采纳流程。"""

    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.db = RadioDB(self.path)
        self.current = self.db.add_program("午间音乐", "music", 30, "2026-01-01", "2026-12-31", None, 0, ["华东"])
        self.safe = self.db.add_program("备用音乐", "music", 30, "2026-01-01", "2026-12-31", None, 0, ["华东"])
        self.sponsored = self.db.add_program("清茶剧场", "talk", 30, "2026-01-01", "2026-12-31", "清茶", 0, ["华东"])
        self.expired = self.db.add_program("过期节目", "music", 30, "2026-01-01", "2026-06-30", None, 0, ["华东"])
        self.outside = self.db.add_program("异地节目", "music", 30, "2026-01-01", "2026-12-31", None, 0, ["华南"])
        self.cooling = self.db.add_program("冷却节目", "music", 30, "2026-01-01", "2026-12-31", None, 120, ["华东"])
        self.rival = self.db.add_program("青柠专题", "talk", 30, "2026-01-01", "2026-12-31", "青柠", 0, ["华东"])
        self.short = self.db.add_program("短资讯", "talk", 15, "2026-01-01", "2026-12-31", None, 0, ["华东"])
        self.db.add_sponsor_policy("清茶", 60)
        self.db.add_sponsor_policy("青柠", 90)
        # 目标排期：2026-09-28 09:00 华东，时长 30 分钟
        self.slot = self.db.schedule_slot("2026-09-28", "09:00", self.current, "华东")
        # 清茶 06:00-06:30：距 09:00 间隔 150 分钟，满足 60 分钟政策（余量 90）
        self.db.schedule_slot("2026-09-28", "06:00", self.sponsored, "华东")
        # 冷却节目 07:00-07:30：距 09:00 缺口 90 分钟，不足 120 分钟冷却（还差 30）
        self.db.schedule_slot("2026-09-28", "07:00", self.cooling, "华东")
        # 青柠 08:00-08:30：距 09:00 仅 30 分钟，不足 90 分钟赞助间隔（还差 60）
        self.db.schedule_slot("2026-09-28", "08:00", self.rival, "华东")

    def tearDown(self):
        self.db.close()
        os.unlink(self.path)

    def test_candidates_ranked_by_remaining_spacing(self):
        result = self.db.suggest_replacements(self.slot)
        self.assertEqual("", result["message"])
        self.assertEqual([], result["blocked_by"])
        candidate_ids = [c["program_id"] for c in result["candidates"]]
        # 无冷却无赞助约束的最安全，排第一；清茶剧场赞助余量 90 分钟排第二
        self.assertEqual([self.safe, self.sponsored], candidate_ids)
        self.assertIsNone(result["candidates"][0]["cooldown_margin"])
        self.assertIsNone(result["candidates"][0]["sponsor_margin"])
        self.assertEqual(90, result["candidates"][1]["sponsor_margin"])
        self.assertEqual(0, result["candidates"][1]["sponsor_remaining"])

    def test_rejected_programs_carry_reasons(self):
        result = self.db.suggest_replacements(self.slot)
        rejected = {r["program_id"]: r for r in result["rejected"]}
        # 当前节目和不同时长的节目不进入评估
        self.assertNotIn(self.current, rejected)
        self.assertNotIn(self.short, rejected)
        self.assertEqual(["版权"], [i["category"] for i in rejected[self.expired]["issues"]])
        self.assertIn("授权窗口", rejected[self.expired]["issues"][0]["detail"])
        self.assertEqual(["版权"], [i["category"] for i in rejected[self.outside]["issues"]])
        self.assertIn("未授权", rejected[self.outside]["issues"][0]["detail"])
        cooling = rejected[self.cooling]
        self.assertEqual(["节目冷却"], [i["category"] for i in cooling["issues"]])
        self.assertEqual(30, cooling["cooldown_remaining"])
        self.assertIn("还差 30 分钟", cooling["issues"][0]["detail"])
        rival = rejected[self.rival]
        self.assertEqual(["赞助规则"], [i["category"] for i in rival["issues"]])
        self.assertEqual(60, rival["sponsor_remaining"])
        self.assertIn("还差 60 分钟", rival["issues"][0]["detail"])
        # 被拒节目按剩余间隔升序：版权类(0) 在前，然后冷却(30)、赞助(60)
        order = [r["program_id"] for r in result["rejected"]]
        self.assertLess(order.index(self.outside), order.index(self.cooling))
        self.assertLess(order.index(self.cooling), order.index(self.rival))

    def test_no_candidates_names_blocking_rules(self):
        handle, path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        db = RadioDB(path)
        try:
            current = db.add_program("当前节目", "music", 30, "2026-01-01", "2026-12-31", None, 0, ["华东"])
            db.add_program("过期节目", "music", 30, "2026-01-01", "2026-06-30", None, 0, ["华东"])
            db.add_program("短节目", "music", 15, "2026-01-01", "2026-12-31", None, 0, ["华东"])
            slot = db.schedule_slot("2026-09-28", "09:00", current, "华东")
            result = db.suggest_replacements(slot)
            self.assertEqual([], result["candidates"])
            self.assertEqual(["版权"], result["blocked_by"])
            self.assertIn("版权", result["message"])
        finally:
            db.close()
            os.unlink(path)

    def test_no_same_duration_programs_at_all(self):
        handle, path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        db = RadioDB(path)
        try:
            current = db.add_program("当前节目", "music", 30, "2026-01-01", "2026-12-31", None, 0, ["华东"])
            db.add_program("短节目", "music", 15, "2026-01-01", "2026-12-31", None, 0, ["华东"])
            slot = db.schedule_slot("2026-09-28", "09:00", current, "华东")
            result = db.suggest_replacements(slot)
            self.assertEqual([], result["candidates"])
            self.assertEqual([], result["rejected"])
            self.assertIn("同时长", result["message"])
        finally:
            db.close()
            os.unlink(path)

    def test_blackout_window_blocks_everything(self):
        # 排期创建后新增禁播时段（2026-09-28 是周一），所有候选都被禁播挡住
        self.db.add_blocked_window("华东", 0, "08:00", "10:00", "临时检修")
        result = self.db.suggest_replacements(self.slot)
        self.assertEqual([], result["candidates"])
        self.assertIn("禁播", result["blocked_by"])
        self.assertIn("禁播", result["message"])

    def test_suggestion_only_for_planned_slots(self):
        self.db.replace_slot(self.slot, self.safe)
        with self.assertRaisesRegex(DomainError, "planned"):
            self.db.suggest_replacements(self.slot)
        with self.assertRaisesRegex(DomainError, "排期不存在"):
            self.db.suggest_replacements(9999)

    def test_adopt_candidate_via_existing_replace_flow(self):
        result = self.db.suggest_replacements(self.slot)
        chosen = result["candidates"][0]["program_id"]
        slot = self.db.replace_slot(self.slot, chosen)
        self.assertEqual("replaced", slot["status"])
        self.assertEqual(chosen, slot["program_id"])
        self.assertEqual(self.current, slot["replaced_from"])

    def test_rejected_candidate_would_fail_actual_replace(self):
        # 建议结果与现有替换校验一致：被拒节目真的无法通过 replace_slot
        with self.assertRaisesRegex(DomainError, "冷却"):
            self.db.replace_slot(self.slot, self.cooling)
        with self.assertRaisesRegex(DomainError, "赞助商"):
            self.db.replace_slot(self.slot, self.rival)


if __name__ == "__main__":
    unittest.main()
