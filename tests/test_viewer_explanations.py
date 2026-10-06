"""Read-only viewer integration for evidence-bound explanation sidecars."""

import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from robot_debug.case_io import import_m4
from robot_debug.case_store import register_case
from robot_debug.evidence_packet import make_evidence_packet
from robot_debug.explanation import build_offline_report
from robot_debug.explanation_store import make_stored_report, store_report
from robot_debug.viewer.catalog import ArtifactCatalog
from robot_debug.viewer.server import make_handler
from tests.test_case_io import fixture


class ViewerExplanationServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        fixture(self.source)
        self.workspace = self.base / "workspace"
        self.case = import_m4(self.source)
        register_case(self.case, self.source, self.workspace)
        self.packet = make_evidence_packet(self.case)
        web_root = Path(__file__).resolve().parents[1] / "src" / "robot_debug" / "viewer" / "web"
        handler = make_handler(ArtifactCatalog(self.source), web_root, self.workspace)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:{}".format(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def provenance(self, *, created_at="2026-10-05T12:34:56Z", live=False, **changes):
        value = {
            "source": "offline", "provider": None, "model": None, "endpoint": None,
            "created_at": created_at, "request_status": "offline", "error_code": None,
            "latency_seconds": None, "prompt_tokens": None, "completion_tokens": None,
            "estimated_cost_usd": None, "billed_cost_usd": None, "reservation_usd": 0,
        }
        if live:
            value.update({
                "source": "live", "provider": "nebius-token-factory",
                "model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
                "endpoint": "https://api.tokenfactory.nebius.com/v1/",
                "request_status": "completed", "latency_seconds": 1.25,
                "prompt_tokens": 100, "completion_tokens": 50,
                "estimated_cost_usd": 0.000018, "reservation_usd": 0.02,
            })
        value.update(changes)
        return value

    def save(self, report=None, provenance=None):
        record = make_stored_report(
            self.case["case_id"], self.packet,
            report or build_offline_report(self.packet),
            provenance or self.provenance(),
        )
        store_report(self.workspace, record)
        return record

    def request(self, path, method="GET"):
        request = Request(self.url + path, method=method)
        try:
            with urlopen(request) as response:
                return response.status, dict(response.headers.items()), response.read()
        except HTTPError as error:
            return error.code, dict(error.headers.items()), error.read()

    def endpoint(self):
        return "/api/cases/{}/explanations".format(self.case["case_id"])

    def test_get_returns_exact_history_for_offline_valid_and_rejected_reports(self):
        offline = self.save()
        evidence_id = self.packet["episodes"][0]["evidence_id"]
        response = json.dumps({
            "schema_version": 1,
            "observations": [{"text": "Reported outcome differs.", "evidence_ids": [evidence_id]}],
            "hypotheses": [], "limitations": ["Human review remains required."],
        })
        valid = self.save(build_offline_report(self.packet, response), self.provenance(
            created_at="2026-10-05T12:34:58Z", live=True))
        rejected = self.save(build_offline_report(self.packet, "malformed"), self.provenance(
            created_at="2026-10-05T12:34:57Z", live=True,
            request_status="invalid_response", error_code="invalid_response",
            prompt_tokens=None, completion_tokens=None, estimated_cost_usd=None))

        with patch("urllib.request.urlopen", side_effect=AssertionError("external network used")):
            status, headers, body = self.request(self.endpoint())

        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(json.loads(body), {"reports": [offline, rejected, valid], "warnings": []})

    def test_get_isolates_corrupt_report_and_stale_or_missing_case(self):
        record = self.save()
        reports = self.workspace / self.case["case_id"] / "reports"
        (reports / ("f" * 64 + ".json")).write_text("{bad", encoding="utf-8")

        status, _, body = self.request(self.endpoint())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {
            "reports": [record],
            "warnings": ["one or more report records are unavailable or invalid"],
        })

        (self.source / "failure-reduction" / "replay_case.json").unlink()
        status, _, body = self.request(self.endpoint())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {
            "reports": [], "warnings": ["case evidence is unavailable or changed"],
        })

        missing = "0" * 64
        status, _, body = self.request("/api/cases/{}/explanations".format(missing))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {
            "reports": [], "warnings": ["case evidence is unavailable or changed"],
        })

    def test_endpoint_rejects_bad_ids_and_has_no_http_write_method(self):
        record = self.save()
        report_path = self.workspace / self.case["case_id"] / "reports" / (record["report_id"] + ".json")
        before = report_path.read_bytes()

        bad_status, _, _ = self.request("/api/cases/ABC/explanations")
        post_status, _, _ = self.request(self.endpoint(), method="POST")

        self.assertEqual(bad_status, 400)
        self.assertIn(post_status, (405, 501))
        self.assertEqual(report_path.read_bytes(), before)


class ViewerExplanationBrowserTests(unittest.TestCase):
    def test_browser_selects_newest_safely_navigates_exact_ids_and_isolates_aba_races(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js runtime unavailable")
        asset = Path(__file__).resolve().parents[1] / "src" / "robot_debug" / "viewer" / "web" / "app.js"
        script = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
let source = fs.readFileSync(process.argv[1], 'utf8');
source = source.replace(/^refreshCatalog\(\)\.catch\(showFatalError\);$/m, '');
class Element {
  constructor(tagName = 'DIV') {
    this.tagName = tagName; this.children = []; this.listeners = {}; this.dataset = {};
    this.options = []; this.hidden = false; this.textContent = ''; this.value = '';
  }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  click() { this.listeners.click(); }
  focus() { context.document.activeElement = this; }
  pause() {} load() {} play() { return Promise.resolve(); }
  contains(target) { return this === target || this.children.some((child) => child.contains && child.contains(target)); }
  replaceChildren(...children) {
    if (this.children.some((child) => child.contains && child.contains(context.document.activeElement))) {
      context.document.activeElement = null;
    }
    this.children = children; if (!children.length) this.textContent = '';
    if (this.tagName === 'SELECT') this.options = [...children];
  }
  append(...children) { this.children.push(...children); if (this.tagName === 'SELECT') this.options.push(...children); }
  setAttribute(name, value) { this[name] = value; }
  removeAttribute(name) { delete this[name]; }
  querySelectorAll(tagName) {
    const matches = [];
    const visit = (node) => { if (node.tagName === tagName.toUpperCase()) matches.push(node); (node.children || []).forEach(visit); };
    this.children.forEach(visit); return matches;
  }
  getContext() { return null; }
}
const elements = new Map();
const element = (id) => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
const context = {
  document: { activeElement: null, getElementById(id) { return element(id); }, createElement(tagName) { return new Element(tagName.toUpperCase()); } },
  window: { setInterval() {}, devicePixelRatio: 1 }, console, fetch() { throw new Error('unexpected fetch'); },
};
vm.runInNewContext(source + `\nglobalThis.exposed = { state, newestExplanationReport,
  availableEpisodeForEvidence, beginExplanationRequest, commitExplanationResponse,
  refreshExplanations, renderExplanations, appendCitations }; render = () => { globalThis.renderCalls = (globalThis.renderCalls || 0) + 1; };`, context);
const { state, newestExplanationReport, availableEpisodeForEvidence,
  beginExplanationRequest, commitExplanationResponse, refreshExplanations,
  renderExplanations, appendCitations } = context.exposed;
const A = 'a'.repeat(64), B = 'b'.repeat(64), E = '1'.repeat(16), MISSING = '9'.repeat(16);
const older = { report_id: '1'.repeat(64), provenance: { created_at: '2026-10-05T12:00:00Z' } };
const tieLow = { report_id: '2'.repeat(64), provenance: { created_at: '2026-10-05T13:00:00Z' } };
const tieHigh = { report_id: 'f'.repeat(64), provenance: { created_at: '2026-10-05T13:00:00Z' } };
assert.strictEqual(newestExplanationReport({reports: [tieLow, older, tieHigh]}).report_id, tieHigh.report_id);
state.caseId = A;
state.cases = [{case_id: A, capabilities: {inspection: {status: 'available'}},
  evidence: {episodes: [{episode_id: E}]}}];
state.episodes = [{episode_id: E}, {episode_id: '2'.repeat(16)}];
assert.strictEqual(availableEpisodeForEvidence(E).episode_id, E);
assert.strictEqual(availableEpisodeForEvidence('2'.repeat(16)), null);
assert.strictEqual(availableEpisodeForEvidence('3'.repeat(16)), null);

const firstA = beginExplanationRequest(A, true);
state.caseId = B;
const requestB = beginExplanationRequest(B, true);
state.caseId = A;
const secondA = beginExplanationRequest(A, true);
const fresh = {reports: [tieHigh], warnings: []};
assert.strictEqual(commitExplanationResponse(A, firstA, {reports: [older], warnings: []}), false);
assert.strictEqual(commitExplanationResponse(B, requestB, {reports: [tieLow], warnings: []}), false);
assert.strictEqual(commitExplanationResponse(A, secondA, fresh), true);
assert.strictEqual(state.explanations.reports[0].report_id, tieHigh.report_id);

const baseReport = {
  report_id: 'e'.repeat(64),
  provenance: { source: 'live', provider: 'nebius-token-factory', model: 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B',
    created_at: '2026-10-05T14:00:00Z', request_status: 'completed', latency_seconds: 1.25,
    prompt_tokens: 100, completion_tokens: 50, estimated_cost_usd: 0.000018 },
  report: { interpretation_status: 'validated', disclaimer: 'Deterministic scope only.',
    facts: { total_episodes: 2, reduced_mask_area_fraction: 0.125,
      counts_by_role: { final_candidate: { raw_outcomes: { policy_failure: 1 }, gate_outcomes: { policy_failure: 1 } } } },
    interpretation: { observations: [{ text: '<img src=x onerror=alert(1)>', evidence_ids: [E, MISSING] }],
      hypotheses: [], limitations: ['Human review required.'] } },
};
state.explanations = {reports: [baseReport], warnings: []};
state.explanationCaseId = A; state.explanationReportId = baseReport.report_id;
renderExplanations();
const interpretation = element('explanation-interpretation');
assert.ok(interpretation.children.some((child) => child.textContent === '<img src=x onerror=alert(1)>'));
const buttons = interpretation.querySelectorAll('button');
assert.strictEqual(buttons.length, 1);
assert.strictEqual(buttons[0].textContent, E);
assert.strictEqual(interpretation.querySelectorAll('span')[0].textContent, MISSING + ' · episode unavailable');
buttons[0].click();
assert.strictEqual(state.primaryId, E);
assert.strictEqual(context.renderCalls, 1);
buttons[0].focus();
renderExplanations();
assert.strictEqual(context.document.activeElement, buttons[0]);
assert.strictEqual(interpretation.querySelectorAll('button')[0], buttons[0]);

const absent = JSON.parse(JSON.stringify(baseReport));
absent.report_id = 'c'.repeat(64); absent.report.interpretation_status = 'absent'; absent.report.interpretation = null;
absent.provenance = { source: 'offline', provider: null, model: null, created_at: '2026-10-05T13:30:00Z',
  request_status: 'offline', latency_seconds: null, prompt_tokens: null, completion_tokens: null, estimated_cost_usd: null };
state.explanations = {reports: [absent], warnings: []}; state.explanationReportId = absent.report_id;
renderExplanations();
assert.ok(element('explanation-interpretation').children[0].textContent.startsWith('Absent'));
assert.ok(element('explanation-provenance').children.some((child) => child.textContent.includes('Provider: not used')));
assert.ok(element('explanation-provenance').children.some((child) => child.textContent.includes('Estimated cost: unknown · Billed cost: unknown')));

const rejected = JSON.parse(JSON.stringify(baseReport));
rejected.report_id = 'd'.repeat(64); rejected.report.interpretation_status = 'rejected'; rejected.report.interpretation = null;
state.explanations = {reports: [rejected], warnings: []}; state.explanationReportId = rejected.report_id;
renderExplanations();
assert.ok(element('explanation-interpretation').children[0].textContent.startsWith('Rejected'));

state.caseId = A; state.explanationCaseId = A;
const initialHistory = beginExplanationRequest(A, false);
assert.strictEqual(commitExplanationResponse(A, initialHistory, {reports: [absent, baseReport], warnings: []}), true);
assert.strictEqual(state.explanationReportId, baseReport.report_id);
state.explanationReportId = absent.report_id;
const identicalRefresh = beginExplanationRequest(A, false);
assert.strictEqual(commitExplanationResponse(A, identicalRefresh, {reports: [absent, baseReport], warnings: []}), true);
assert.strictEqual(state.explanationReportId, absent.report_id);
const latest = JSON.parse(JSON.stringify(baseReport));
latest.report_id = 'f'.repeat(64); latest.provenance.created_at = '2026-10-05T15:00:00Z';
const changedRefresh = beginExplanationRequest(A, false);
assert.strictEqual(commitExplanationResponse(A, changedRefresh, {reports: [absent, baseReport, latest], warnings: []}), true);
assert.strictEqual(state.explanationReportId, latest.report_id);

state.explanations = {reports: [], warnings: ['case evidence is unavailable or changed']};
renderExplanations();
assert.ok(element('explanation-status').textContent.includes('No current report'));
assert.ok(element('explanation-status').textContent.includes('unavailable or changed'));

beginExplanationRequest(B, true); state.caseId = B; renderExplanations();
assert.strictEqual(element('explanation-facts').children.length, 0);
assert.strictEqual(element('explanation-interpretation').children.length, 0);
assert.strictEqual(element('explanation-status').textContent, 'Loading explanation history…');

const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return {promise, resolve}; };
const aFirst = deferred(), bOnly = deferred(), aRefresh = deferred();
const pending = [aFirst, bOnly, aRefresh];
context.fetch = () => pending.shift().promise;
const response = (payload) => ({ok: true, json: async () => payload});
(async () => {
  state.caseId = A; const firstRequest = refreshExplanations(A);
  state.caseId = B; const bRequest = refreshExplanations(B);
  state.caseId = A; const refreshRequest = refreshExplanations(A);
  aRefresh.resolve(response({reports: [baseReport], warnings: []}));
  await refreshRequest;
  aFirst.resolve(response({reports: [absent], warnings: []}));
  bOnly.resolve(response({reports: [rejected], warnings: []}));
  await Promise.all([firstRequest, bRequest]);
  assert.strictEqual(state.explanations.reports[0].report_id, baseReport.report_id);
  assert.strictEqual(state.explanationReportId, baseReport.report_id);
})().catch((error) => { console.error(error); process.exitCode = 1; });
"""
        result = subprocess.run([node, "-e", script, str(asset)], capture_output=True,
                                text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_assets_use_collapsed_semantic_disclosure_text_only_rendering_and_cost_labels(self):
        root = Path(__file__).resolve().parents[1] / "src" / "robot_debug" / "viewer" / "web"
        page = (root / "index.html").read_text(encoding="utf-8")
        app = (root / "app.js").read_text(encoding="utf-8")
        css = (root / "styles.css").read_text(encoding="utf-8")

        self.assertIn('<details id="case-explanations">', page)
        self.assertNotIn('<details id="case-explanations" open', page)
        self.assertIn("Nemotron interpretation — human review required", page)
        self.assertIn("Deterministic facts", page)
        for label in ("Text-only", "Estimated cost", "Billed cost: unknown"):
            self.assertIn(label, app)
        self.assertIn("textContent", app)
        self.assertNotIn("innerHTML", app)
        self.assertIn("availableEpisodeForEvidence", app)
        self.assertIn("min-height: 24px", css)
        self.assertIn(":focus-visible", css)
        self.assertIn("min-height: 24px", css[css.index("#case-details summary"):])


if __name__ == "__main__":
    unittest.main()
