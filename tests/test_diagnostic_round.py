import hashlib
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


SOURCE_ROOT = Path(__file__).parents[1] / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))


class ReverseEvaluator:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = self.maximum_active = 0
        self.started = []

    def __call__(self, request, *, launch_observer):
        with self.lock:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            self.started.append(request.case_id)
            number = len(self.started)
        launch_observer(8000 + number, f"vla-eval-{8000 + number}")
        time.sleep((5 - int(request.case_id[-1])) * .01)
        request.output_dir.mkdir()
        evidence = request.output_dir / "aggregate.json"
        evidence.write_text("{}", encoding="utf-8")
        with self.lock:
            self.active -= 1
        return {"status": "valid", "outcome": "policy_failure", "evidence_paths": [str(evidence)]}


class DiagnosticRoundTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "round"
        self.root.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def requests(self):
        from robot_debug.diagnostic_round import RoundRequest
        requests = []
        for number in range(1, 5):
            config = self.root / "configs" / f"case-{number}.yaml"
            config.parent.mkdir(exist_ok=True)
            output = self.root / "runs" / f"case-{number}"
            config.write_text(f"case: {number}\noutput_dir: {json.dumps(str(output))}\n",
                              encoding="utf-8")
            requests.append(RoundRequest(f"case-{number}", config, output))
        return tuple(requests)

    def test_round_uses_shared_scheduler_with_durable_ordered_results(self):
        from robot_debug.diagnostic_round import run_round
        evaluator = ReverseEvaluator()
        ledger = self.root / "ledger.json"
        import robot_debug.diagnostic_round as module
        shared = module.run_schedule

        with patch.object(module, "run_schedule", wraps=shared) as scheduled:
            summary = run_round(self.requests(), workers=2, launch_cutoff=60,
                                evaluator=evaluator, ledger_path=ledger, round_root=self.root)

        self.assertEqual(1, scheduled.call_count)
        self.assertEqual(2, evaluator.maximum_active)
        self.assertTrue(summary.certifying)
        self.assertEqual(["case-1", "case-2", "case-3", "case-4"],
                         [result.case_id for result in summary.results])
        durable = json.loads(ledger.read_text(encoding="utf-8"))
        self.assertEqual(["case-1", "case-2", "case-3", "case-4"], durable["case_ids"])
        self.assertEqual(hashlib.sha256(self.requests()[0].config_path.read_bytes()).hexdigest(),
                         durable["items"][0]["config_hash"])
        self.assertTrue(all(record["state"] == "terminal"
                            for record in durable["attempt_records"].values()))

    def test_unknown_identity_is_uncertain_and_resume_refuses_relaunch(self):
        from robot_debug.diagnostic_round import run_round
        request = self.requests()[:1]
        ledger = self.root / "uncertain.json"

        def uncertain(_request, *, launch_observer):
            launch_observer(None, None)
            return {"status": "valid", "outcome": "policy_failure", "evidence_paths": []}

        first = run_round(request, workers=1, launch_cutoff=60, evaluator=uncertain,
                          ledger_path=ledger, round_root=self.root)
        self.assertFalse(first.certifying)
        self.assertEqual("uncertain", first.results[0].status)
        with self.assertRaisesRegex(ValueError, "uncertain|resume"):
            run_round(request, workers=1, launch_cutoff=60, evaluator=uncertain,
                      ledger_path=ledger, round_root=self.root, resume=True)

    def test_timeout_is_uncertain_and_non_certifying(self):
        from robot_debug.diagnostic_round import run_round
        request = self.requests()[:1]
        ledger = self.root / "timeout.json"

        def timeout(_request, *, launch_observer):
            launch_observer(9999, "vla-eval-9999")
            raise subprocess.TimeoutExpired("evaluator", 1)

        summary = run_round(request, workers=1, launch_cutoff=60, evaluator=timeout,
                            ledger_path=ledger, round_root=self.root)
        self.assertFalse(summary.certifying)
        self.assertEqual("uncertain", summary.results[0].status)
        with self.assertRaisesRegex(ValueError, "uncertain|resume"):
            run_round(request, workers=1, launch_cutoff=60, evaluator=timeout,
                      ledger_path=ledger, round_root=self.root, resume=True)

    def test_rejects_unsafe_or_aliased_paths_before_launch(self):
        from robot_debug.diagnostic_round import RoundRequest, run_round
        outside = self.root.parent / "outside.yaml"
        outside.write_text("outside", encoding="utf-8")
        unsafe = RoundRequest("case-1", outside, self.root / "runs" / "one")
        with self.assertRaisesRegex(ValueError, "config_path.*round root"):
            run_round((unsafe,), workers=1, launch_cutoff=60, evaluator=ReverseEvaluator(),
                      ledger_path=self.root / "ledger.json", round_root=self.root)
        duplicate = self.requests()[:2]
        duplicate = (duplicate[0], RoundRequest("case-2", duplicate[1].config_path,
                                                 duplicate[0].output_dir))
        with self.assertRaisesRegex(ValueError, "output_dir.*unique"):
            run_round(duplicate, workers=1, launch_cutoff=60, evaluator=ReverseEvaluator(),
                      ledger_path=self.root / "second.json", round_root=self.root)

    def test_shares_lifecycle_and_rejects_overlapping_outputs(self):
        from robot_debug.diagnostic_round import RoundRequest, run_round
        requests = self.requests()[:2]
        nested = (requests[0], RoundRequest("case-2", requests[1].config_path,
                                             requests[0].output_dir / "nested"))
        with self.assertRaisesRegex(ValueError, "non-overlapping"):
            run_round(nested, workers=1, launch_cutoff=60, evaluator=ReverseEvaluator(),
                      ledger_path=self.root / "nested.json", round_root=self.root)
        observed = []
        def evaluator(request, *, launch_observer, lifecycle):
            observed.append(lifecycle)
            launch_observer(8123, "vla-eval-8123")
            request.output_dir.mkdir(); evidence = request.output_dir / "aggregate.json"
            evidence.write_text("{}", encoding="utf-8")
            return {"status": "valid", "outcome": "success", "evidence_paths": [str(evidence)]}
        run_round(requests[:1], workers=1, launch_cutoff=60, evaluator=evaluator,
                  ledger_path=self.root / "lifecycle.json", round_root=self.root)
        self.assertEqual(1, len(observed))
        self.assertFalse(observed[0].stop_requested.is_set())

    def test_binds_config_output_dir_and_rejects_duplicate_config_paths(self):
        from robot_debug.diagnostic_round import RoundRequest, run_round
        request = self.requests()[:1]
        request[0].config_path.write_text(
            f"output_dir: {json.dumps(str(self.root / 'runs' / 'not-the-requested-output'))}\n",
            encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "output_dir.*RoundRequest"):
            run_round(request, workers=1, launch_cutoff=60, evaluator=ReverseEvaluator(),
                      ledger_path=self.root / "binding.json", round_root=self.root)
        requests = self.requests()[:2]
        duplicate_config = (requests[0], RoundRequest("case-2", requests[0].config_path,
                                                       requests[1].output_dir))
        with self.assertRaisesRegex(ValueError, "config_path.*unique"):
            run_round(duplicate_config, workers=1, launch_cutoff=60, evaluator=ReverseEvaluator(),
                      ledger_path=self.root / "config-duplicate.json", round_root=self.root)

    def test_rejects_noncertifying_outcomes_and_evidence_from_another_case(self):
        from robot_debug.diagnostic_round import run_round
        request = self.requests()[:1]

        def wrong_outcome(item, *, launch_observer):
            launch_observer(8111, "vla-eval-8111")
            item.output_dir.mkdir(parents=True)
            evidence = item.output_dir / "aggregate.json"
            evidence.write_text("{}", encoding="utf-8")
            return {"status": "valid", "outcome": "inconclusive", "evidence_paths": [str(evidence)]}

        summary = run_round(request, workers=1, launch_cutoff=60, evaluator=wrong_outcome,
                            ledger_path=self.root / "bad-outcome.json", round_root=self.root)
        self.assertFalse(summary.certifying)
        self.assertEqual("invalid_evidence", summary.results[0].status)

    def test_round_root_has_one_fresh_atomic_launch_owner(self):
        from robot_debug.diagnostic_round import RoundRequest, run_round
        first = run_round(self.requests(), workers=2, launch_cutoff=60, evaluator=ReverseEvaluator(),
                          ledger_path=self.root / "first.json", round_root=self.root)
        self.assertTrue(first.certifying)
        config = self.root / "configs" / "other.yaml"
        output = self.root / "runs" / "other"
        config.write_text(f"output_dir: {json.dumps(str(output))}\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "launches|fresh round"):
            run_round((RoundRequest("other", config, output),), workers=1, launch_cutoff=60,
                      evaluator=ReverseEvaluator(), ledger_path=self.root / "second.json",
                      round_root=self.root)

    def test_resume_requires_clean_authoritative_complete_summary(self):
        from robot_debug.diagnostic_round import run_round
        requests = self.requests()
        ledger = self.root / "clean.json"
        first = run_round(requests, workers=2, launch_cutoff=60, evaluator=ReverseEvaluator(),
                          ledger_path=ledger, round_root=self.root)
        self.assertTrue(first.certifying)
        resumed = run_round(requests, workers=2, launch_cutoff=60,
                            evaluator=lambda *_args, **_kwargs: self.fail("must not relaunch"),
                            ledger_path=ledger, round_root=self.root, resume=True)
        self.assertTrue(resumed.certifying)
        durable = json.loads(ledger.read_text(encoding="utf-8"))
        durable["valid_count"] = 0
        ledger.write_text(json.dumps(durable), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "authoritative|clean"):
            run_round(requests, workers=2, launch_cutoff=60, evaluator=ReverseEvaluator(),
                      ledger_path=ledger, round_root=self.root, resume=True)


if __name__ == "__main__":
    unittest.main()
