import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tidal_memory import RecallPolicy, TidalMemory


class TidalMemoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "test.db")
        self.memory = TidalMemory(self.path)

    def tearDown(self):
        self.memory.close()
        self.temp.cleanup()

    def test_impression_and_detail_are_separate_paths(self):
        self.memory.remember(
            "小岚喜欢茉莉花茶，不喜欢咖啡。",
            layer="semantic", importance=6, tags="偏好,饮料",
        )
        self.memory.store.upsert_window_impression(
            "old-window", "那天下午聊了饮料和雨天，气氛轻松温柔。", title="雨天",
        )
        opening = self.memory.opening_context("new-window")
        self.assertIn("气氛轻松温柔", opening)
        recalled = self.memory.recall("你记得小岚喜欢喝什么吗？", force=True)
        self.assertIn("茉莉花茶", recalled)
        self.assertNotIn("气氛轻松温柔", recalled)

    def test_trigger_modes(self):
        strict = TidalMemory(
            str(Path(self.temp.name) / "strict.db"),
            policy=RecallPolicy(trigger="explicit"),
        )
        try:
            strict.remember("Rin likes jasmine tea.", tags="drink")
            self.assertEqual(strict.recall("Tell me about tea"), "")
            self.assertIn("jasmine", strict.recall("Do you remember what Rin drinks?"))
        finally:
            strict.close()

    def test_stable_core_and_automatic_fact_extractor(self):
        path = str(Path(self.temp.name) / "extractor.db")
        extracted = TidalMemory(
            path,
            fact_extractor=lambda messages: [{
                "summary": "Rin's birthday is in spring.",
                "layer": "core",
                "importance": 9,
                "tags": "identity",
            }],
        )
        try:
            extracted.close_window("w1", [{"role": "user", "content": "A normal chat."}])
            opening = extracted.opening_context("w2")
            self.assertIn("Stable memory", opening)
            self.assertIn("birthday is in spring", opening)
            self.assertIn("Impressions", opening)
        finally:
            extracted.close()

    def test_repeat_cooldown(self):
        self.memory.remember("Rin likes jasmine tea.", tags="drink")
        first = self.memory.recall("Remember Rin's drink?", force=True)
        second = self.memory.recall("Remember Rin's drink?", force=True)
        self.assertTrue(first)
        self.assertEqual(second, "")

    def test_one_hop_association_is_real_and_background_stays_excluded(self):
        cause = self.memory.remember("Rin missed the last train.", tags="train")
        effect = self.memory.remember("Rin stayed at a small harbor hotel.", tags="hotel")
        background = self.memory.store.upsert_window_impression(
            "w-bg", "They talked about a difficult journey.", title="Journey"
        )
        self.memory.store.link(cause, effect, "caused")
        self.memory.store.link(cause, background, "related")
        output = self.memory.recall("Do you remember the last train?", force=True)
        self.assertIn("last train", output)
        self.assertIn("harbor hotel", output)
        self.assertNotIn("difficult journey", output)

    def test_offline_impression_does_not_quote_transcript(self):
        secret_phrase = "orchid-lantern-7391"
        self.memory.close_window("private", [
            {"role": "user", "content": "Please remember " + secret_phrase + " while we fix code."}
        ])
        opening = self.memory.opening_context("new")
        self.assertIn("technology", opening)
        self.assertNotIn(secret_phrase, opening)

    def test_supersede_archives_old_fact(self):
        old_id = self.memory.remember("Rin lives in Harbor City.", layer="semantic")
        new_id = self.memory.store.supersede(old_id, "Rin lives in Hill City.")
        self.assertTrue(self.memory.store.get(old_id).archived)
        self.assertEqual(self.memory.store.get(old_id).merged_into, new_id)
        recalled = self.memory.recall("Where did Rin live?", force=True)
        self.assertNotIn("Harbor City", recalled)

    def test_rollup_archives_raw_windows(self):
        old = "2025-01-06T12:00:00+00:00"
        ids = [
            self.memory.store.upsert_window_impression("w1", "They cooked and laughed.", occurred_at=old),
            self.memory.store.upsert_window_impression("w2", "They fixed a lamp together.", occurred_at=old),
        ]
        result = self.memory.rollup(
            now=datetime(2025, 3, 1, tzinfo=timezone.utc),
            writer=lambda items, label: f"A warm {label} spent doing ordinary things.",
        )
        self.assertEqual(result["weekly"], 1)
        self.assertTrue(all(self.memory.store.get(mid).archived for mid in ids))
        self.assertIn("warm week", self.memory.opening_context())

    def test_opening_context_is_bounded(self):
        for index in range(5):
            self.memory.store.upsert_window_impression(
                f"w{index}", "x" * 180, occurred_at=f"2026-01-0{index + 1}T12:00:00+00:00"
            )
        context = self.memory.store.impression_ladder(max_chars=250)
        self.assertLessEqual(len(context), 250)
        self.assertEqual(context.count("Recent window"), 1)

    def test_quiet_ongoing_thread_survives_two_window_ladder(self):
        self.memory.store.upsert_window_impression(
            "w1", "They briefly mentioned an ordinary errand.",
            ongoing_threads=[{
                "key": "cat-sitting-job", "label": "The after-work cat-sitting job continues",
                "status": "active",
            }],
        )
        self.memory.store.upsert_window_impression("w2", "They discussed breakfast.")
        self.memory.store.upsert_window_impression("w3", "They fixed a small bug.")
        context = self.memory.opening_context("w4")
        self.assertNotIn("ordinary errand", context)
        self.assertIn("Ongoing: The after-work cat-sitting job continues", context)

    def test_done_thread_suppresses_older_active_state(self):
        thread = {
            "key": "small-bug", "label": "A small rendering bug remains", "status": "active",
        }
        self.memory.store.upsert_window_impression("w1", "They worked on the interface.",
                                                   ongoing_threads=[thread])
        self.memory.store.upsert_window_impression(
            "w2", "They finished the interface fix.",
            ongoing_threads=[{**thread, "status": "done"}],
        )
        self.assertNotIn("A small rendering bug remains", self.memory.opening_context("w3"))


if __name__ == "__main__":
    unittest.main()
