"""Runnable tests for the /result observer."""
import json
import tempfile
import unittest
import observer


class TestMatrix(unittest.TestCase):
    def test_matrix_has_four_states(self):
        matrix = observer.get_matrix()
        states = sorted([r["state"] for r in matrix])
        self.assertEqual(states, ["pending", "retryable-error", "success", "timeout"])

    def test_describe_state_success(self):
        row = observer.describe_state("success")
        self.assertIsNotNone(row)
        self.assertIn("stop", row["next_action"].lower())

    def test_describe_unknown_returns_none(self):
        self.assertIsNone(observer.describe_state("nope-state"))


class TestNoiseFilter(unittest.TestCase):
    def test_heartbeat_skipped_and_result_kept(self):
        text = "DID-active presence confirmation 001\n" + "agent heartbeat online 002\n" + "how do I use /result for testnet tokens?\n" + "verifiable hydra telemetry proof seq 9\n"
        result = observer.filter_room_log(text)
        self.assertEqual(result["skipped_heartbeat"], 2)
        self.assertEqual(result["kept_count"], 2)
        joined = " ".join(result["kept"])
        self.assertIn("/result", joined)
        self.assertIn("telemetry", joined)

    def test_cursor_tip_kept(self):
        text = "efficiency tip long-poll wait plus cursor cuts read load\nDID-active hello\n"
        result = observer.filter_room_log(text)
        self.assertEqual(result["kept_count"], 1)
        self.assertEqual(result["skipped_heartbeat"], 1)


class TestScanner(unittest.TestCase):
    def test_scan_counts_states(self):
        log = "[12:00:01] call /result cursor: abc success credited\n" + "[12:00:06] call /result cursor: abc pending\n" + "[12:00:11] call /result timeout gateway\n" + "[12:00:16] call /result error 429 retry later\n"
        summary = observer.scan_result_log(log)
        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["counts"]["success"], 1)
        self.assertEqual(summary["counts"]["pending"], 1)
        self.assertEqual(summary["counts"]["timeout"], 1)
        self.assertEqual(summary["counts"]["retryable-error"], 1)

    def test_scan_extracts_cursor_and_timestamp(self):
        log = "12:01:02 call /result cursor: xyz123 pending"
        summary = observer.scan_result_log(log)
        self.assertEqual(summary["total"], 1)
        item = summary["invocations"][0]
        self.assertEqual(item["cursor"], "xyz123")
        self.assertEqual(item["timestamp"], "12:01:02")


class TestRedaction(unittest.TestCase):
    def test_redact_hides_token_patterns(self):
        raw = "token 0x1234567890abcdef1234567890abcdef done"
        red = observer.redact_text(raw)
        self.assertNotIn("1234567890abcdef", red)
        self.assertIn("[REDACTED]", red)

    def test_secret_warning(self):
        self.assertTrue(observer.looks_like_secret("my mnemonic: abc def"))
        self.assertFalse(observer.looks_like_secret("how does /result pending work?"))


class TestChecklistAndBundle(unittest.TestCase):
    def test_checklist_is_dry_run(self):
        lines = observer.generate_checklist(5, 3, start_cursor="c1")
        joined = " ".join(lines).lower()
        self.assertIn("dry run", joined)
        self.assertIn("never calls", joined)
        self.assertIn("5", joined)

    def test_checklist_rejects_bad_interval(self):
        with self.assertRaises(ValueError):
            observer.generate_checklist(0, 3)

    def test_bundle_roundtrip_with_tempfile(self):
        kept = ["how does /result pending work? cursor: c1", "telemetry proof seq 9?"]
        log = "10:00:00 call /result cursor: c1 pending"
        summary = observer.scan_result_log(log)
        checklist = observer.generate_checklist(5, 2)
        bundle = observer.build_bundle(kept, summary, checklist, did_label="did:example:123")
        self.assertEqual(bundle["did_label"], "did:example:123")
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", delete=False, encoding="utf-8") as tmp:
            tmppath = tmp.name
        observer.save_bundle(bundle, tmppath)
        with open(tmppath, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual(loaded["scan_total"], 1)
        self.assertEqual(loaded["kept_count"], 2)
        self.assertIn("disclaimer", loaded)


if __name__ == "__main__":
    unittest.main()
