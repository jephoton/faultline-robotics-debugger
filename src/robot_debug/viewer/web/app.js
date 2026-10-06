const state = {
  episodes: [], warnings: [], primaryId: null, comparisonId: null,
  traces: new Map(), linked: true, refreshMs: 2000, reduction: null,
  cases: [], caseId: "all", caseSelected: false, caseError: null,
  recipe: null, recipeCaseId: null, caseSignature: null,
  explanations: null, explanationCaseId: null, explanationReportId: null,
  explanationNewestReportId: null,
  explanationRequestGeneration: 0,
};

const outcomeLabels = {
  success: "SUCCESS", task_failure: "TASK FAILURE", episode_timeout: "TIMEOUT",
  infrastructure_error: "INFRA ERROR",
};
const byId = (id) => document.getElementById(id);
const episodeById = (id) => state.episodes.find((episode) => episode.episode_id === id);
const selectedCase = () => state.cases.find((item) => item.case_id === state.caseId);
function caseSignature(item) {
  if (!item) return state.caseId;
  if (item.status === "unavailable") return `${item.case_id}:unavailable`;
  return JSON.stringify([item.case_id, item.capabilities, item.policy, item.runtime, item.evidence.episodes]);
}
function caseEpisodeMatches(saved, episode) {
  return saved.episode_id === episode.episode_id;
}
function savedRoleFor(episode) {
  const chosen = selectedCase();
  if (!episode || !chosen || chosen.status === "unavailable") return null;
  const saved = chosen.evidence.episodes.find((item) => caseEpisodeMatches(item, episode));
  return saved ? saved.role : null;
}
function caseEpisodes() {
  const selected = selectedCase();
  if (!selected || selected.status === "unavailable" ||
      selected.capabilities.inspection.status !== "available") return [];
  const matches = [];
  selected.evidence.episodes.forEach((saved) => {
    const exact = state.episodes.find((episode) => caseEpisodeMatches(saved, episode));
    if (exact && !matches.some((episode) => episode.episode_id === exact.episode_id)) matches.push(exact);
  });
  return matches;
}
function isPerturbed(episode) {
  const fault = episode && episode.perturbation;
  return Boolean(fault && typeof fault === "object" && fault.enabled === true);
}
const isNominal = (episode) => !isPerturbed(episode);
function matchesPrimary(nominal, primary) {
  return primary && nominal.instruction === primary.instruction &&
    nominal.seed === primary.seed && nominal.env_seed === primary.env_seed;
}
function representativeNominal(episodes, primary) {
  const nominals = episodes.filter(isNominal);
  const matches = nominals.filter((episode) => matchesPrimary(episode, primary));
  return (matches.length ? matches : nominals).sort((left, right) => {
    const runPreference = Number(left.run_name !== "nominal") - Number(right.run_name !== "nominal");
    if (runPreference) return runPreference;
    const episodePreference = Number(left.episode_index || 0) - Number(right.episode_index || 0);
    return episodePreference || left.episode_id.localeCompare(right.episode_id);
  })[0] || null;
}
function displayEpisodes(primary = episodeById(state.primaryId)) {
  const source = state.caseId === "all" ? state.episodes : caseEpisodes();
  const nominal = representativeNominal(source, primary);
  return source.filter((episode) => !isNominal(episode) || episode.episode_id === (nominal && nominal.episode_id));
}
const formatSeconds = (value) => `${Number(value || 0).toFixed(2)} s`;
function setText(element, value) { element.textContent = value == null ? "—" : String(value); }
function showNonFatalError(error) { setText(byId("notices"), error.message || error); }
function showFatalError(error) { setText(byId("connection-status"), "UNAVAILABLE"); showNonFatalError(error); }
function outcomeLabel(episode) { return episode ? outcomeLabels[episode.outcome] : "NO EVIDENCE"; }
function perturbationArea(episode) {
  const fault = episode && episode.perturbation;
  return isPerturbed(episode) ? Number(fault.width || 0) * Number(fault.height || 0) * 100 : null;
}
function perturbationPosition(episode) {
  const fault = episode && episode.perturbation;
  if (!isPerturbed(episode)) return "";
  const x = fault.x;
  const y = fault.y;
  return typeof fault.x === "number" && typeof fault.y === "number" && Number.isFinite(x) && Number.isFinite(y)
    ? ` · x=${x.toFixed(2)} y=${y.toFixed(2)}`
    : "";
}

function compareExplanationReports(left, right) {
  const time = left.provenance.created_at.localeCompare(right.provenance.created_at);
  return time || left.report_id.localeCompare(right.report_id);
}
function newestExplanationReport(envelope) {
  if (!envelope || !Array.isArray(envelope.reports) || !envelope.reports.length) return null;
  return envelope.reports.slice().sort(compareExplanationReports).at(-1) || null;
}
function availableEpisodeForEvidence(evidenceId) {
  return caseEpisodes().find((episode) => episode.episode_id === evidenceId) || null;
}
function beginExplanationRequest(caseId, clearPrevious) {
  state.explanationRequestGeneration += 1;
  state.explanationCaseId = caseId;
  if (clearPrevious) {
    state.explanations = null;
    state.explanationReportId = null;
    state.explanationNewestReportId = null;
  }
  return state.explanationRequestGeneration;
}
function commitExplanationResponse(caseId, generation, payload) {
  if (state.caseId !== caseId || state.explanationCaseId !== caseId ||
      state.explanationRequestGeneration !== generation) return false;
  const envelope = payload && Array.isArray(payload.reports) && Array.isArray(payload.warnings)
    ? payload : { reports: [], warnings: ["Explanation records are unavailable."] };
  state.explanations = envelope;
  const newest = newestExplanationReport(envelope);
  const newestId = newest ? newest.report_id : null;
  const selectedStillExists = envelope.reports.some(
    (record) => record.report_id === state.explanationReportId);
  if (newestId !== state.explanationNewestReportId || !selectedStillExists) {
    state.explanationReportId = newestId;
  }
  state.explanationNewestReportId = newestId;
  return true;
}
async function refreshExplanations(caseId) {
  const generation = beginExplanationRequest(caseId, false);
  if (!/^[0-9a-f]{64}$/.test(caseId)) {
    commitExplanationResponse(caseId, generation, { reports: [], warnings: [] });
    renderExplanations();
    return;
  }
  try {
    const response = await fetch(`/api/cases/${caseId}/explanations`, { cache: "no-store" });
    if (!response.ok) throw new Error(`explanation request failed: ${response.status}`);
    const payload = await response.json();
    if (commitExplanationResponse(caseId, generation, payload)) renderExplanations();
  } catch (_) {
    if (commitExplanationResponse(caseId, generation, {
      reports: [], warnings: ["Explanation records are temporarily unavailable."],
    })) renderExplanations();
  }
}

function appendText(container, text, className) {
  const paragraph = document.createElement("p");
  if (className) paragraph.className = className;
  paragraph.textContent = text;
  container.append(paragraph);
  return paragraph;
}
function appendCitations(container, evidenceIds) {
  const citations = document.createElement("div"); citations.className = "evidence-citations";
  evidenceIds.forEach((evidenceId) => {
    const episode = availableEpisodeForEvidence(evidenceId);
    if (!episode) {
      const unavailable = document.createElement("span"); unavailable.className = "unavailable-citation";
      unavailable.textContent = `${evidenceId} · episode unavailable`; citations.append(unavailable); return;
    }
    const button = document.createElement("button"); button.type = "button";
    button.textContent = evidenceId; button.setAttribute("aria-label", `Show evidence episode ${evidenceId}`);
    button.addEventListener("click", () => {
      const exact = availableEpisodeForEvidence(evidenceId);
      if (!exact) return;
      state.primaryId = exact.episode_id;
      if (state.comparisonId === exact.episode_id) state.comparisonId = (defaultComparison() || {}).episode_id || null;
      render();
    });
    citations.append(button);
  });
  container.append(citations);
}
function renderExplanationFacts(container, report) {
  const facts = report.report.facts;
  appendText(container, `Reported episodes: ${facts.total_episodes} · Reduced mask area: ${(facts.reduced_mask_area_fraction * 100).toFixed(2)}%.`);
  Object.entries(facts.counts_by_role).forEach(([role, counts]) => {
    const raw = Object.entries(counts.raw_outcomes).filter(([, count]) => count).map(([name, count]) => `${name} ${count}`).join(", ") || "none";
    const gate = Object.entries(counts.gate_outcomes).filter(([, count]) => count).map(([name, count]) => `${name} ${count}`).join(", ") || "none";
    appendText(container, `${role}: raw ${raw}; gate ${gate}.`);
  });
  appendText(container, report.report.disclaimer);
}
function renderExplanationInterpretation(container, record) {
  const report = record.report;
  if (report.interpretation_status === "absent") {
    appendText(container, "Absent — no model interpretation was supplied. Review the deterministic facts above.");
    return;
  }
  if (report.interpretation_status === "rejected") {
    appendText(container, "Rejected — supplied model output failed local structural validation and is not shown.");
    return;
  }
  const interpretation = report.interpretation;
  [["Observations", interpretation.observations], ["Hypotheses", interpretation.hypotheses]].forEach(([label, entries]) => {
    appendText(container, label);
    if (!entries.length) appendText(container, "None supplied.");
    entries.forEach((entry) => {
      const item = appendText(container, entry.text);
      appendCitations(item, entry.evidence_ids);
    });
  });
  appendText(container, "Limitations");
  if (!interpretation.limitations.length) appendText(container, "None supplied; human review is still required.");
  interpretation.limitations.forEach((text) => appendText(container, text));
}
function renderExplanationProvenance(container, provenance) {
  appendText(container, "Modality: Text-only");
  appendText(container, provenance.source === "offline"
    ? "Source: offline · Provider: not used · Model: not used"
    : `Source: live · Provider: ${provenance.provider} · Model: ${provenance.model}`);
  const latency = provenance.latency_seconds == null ? "unknown" : `${provenance.latency_seconds} s`;
  const tokens = provenance.prompt_tokens == null ? "unknown" : `${provenance.prompt_tokens} input + ${provenance.completion_tokens} output`;
  const estimate = provenance.estimated_cost_usd == null ? "unknown" : `$${provenance.estimated_cost_usd}`;
  appendText(container, `Request status: ${provenance.request_status} · Latency (recorded): ${latency}`);
  appendText(container, `Token usage (recorded): ${tokens} · Estimated cost: ${estimate} · Billed cost: unknown`);
  appendText(container, `Recorded at: ${provenance.created_at}`);
}
function renderExplanations() {
  const disclosure = byId("case-explanations");
  const renderSignature = state.caseId === "all"
    ? "all"
    : state.explanationCaseId !== state.caseId || state.explanations === null
    ? `${state.caseId}:loading`
    : JSON.stringify([state.caseId, state.explanationReportId,
      state.explanations.reports.map((record) => record.report_id), state.explanations.warnings]);
  if (disclosure.dataset.renderSignature === renderSignature) return;
  disclosure.dataset.renderSignature = renderSignature;
  const status = byId("explanation-status");
  const historyControl = byId("explanation-history-control");
  const history = byId("explanation-history");
  const facts = byId("explanation-facts");
  const interpretation = byId("explanation-interpretation");
  const provenance = byId("explanation-provenance");
  [facts, interpretation, provenance].forEach((container) => container.replaceChildren());
  history.replaceChildren(); historyControl.hidden = true;
  if (state.caseId === "all") {
    setText(status, "Select an available case to inspect deterministic facts and stored interpretations."); return;
  }
  if (state.explanationCaseId !== state.caseId || state.explanations === null) {
    setText(status, "Loading explanation history…"); return;
  }
  const reports = state.explanations.reports.slice().sort(compareExplanationReports).reverse();
  const warnings = state.explanations.warnings;
  if (!reports.length) {
    setText(status, warnings.length ? `No current report. ${warnings.join(" · ")}` : "No explanation report stored for this case.");
    return;
  }
  reports.forEach((record) => {
    const option = document.createElement("option"); option.value = record.report_id;
    option.textContent = `${record.provenance.created_at} · ${record.report.interpretation_status} · ${record.report_id.slice(0, 12)}`;
    history.append(option);
  });
  historyControl.hidden = false;
  if (!reports.some((record) => record.report_id === state.explanationReportId)) state.explanationReportId = reports[0].report_id;
  history.value = state.explanationReportId;
  const record = reports.find((item) => item.report_id === state.explanationReportId) || reports[0];
  setText(status, `${reports.length} stored report(s) · showing ${record.provenance.created_at}${warnings.length ? ` · ${warnings.join(" · ")}` : ""}`);
  renderExplanationFacts(facts, record);
  renderExplanationInterpretation(interpretation, record);
  renderExplanationProvenance(provenance, record.provenance);
}

async function refreshReduction() {
  // The read-only API validates session_summary.json, replay_case.json, and accepted lineage.
  try {
    const response = await fetch("/api/reduction", { cache: "no-store" });
    if (!response.ok) { state.reduction = null; return; }
    const payload = await response.json();
    state.reduction = payload && payload.reduction && payload.reduction.metrics ? payload.reduction : null;
  } catch (_) { state.reduction = null; }
}

async function refreshRecipe(caseId) {
  state.recipeCaseId = caseId;
  state.recipe = null;
  if (!/^[0-9a-f]{64}$/.test(caseId)) return;
  const requestedSignature = state.caseSignature;
  try {
    const response = await fetch(`/api/cases/${caseId}/recipe`, { cache: "no-store" });
    if (!response.ok) throw new Error(`recipe request failed: ${response.status}`);
    const payload = await response.json();
    if (state.caseId === caseId && state.caseSignature === requestedSignature) state.recipe = payload;
  } catch (_) {
    if (state.caseId === caseId && state.caseSignature === requestedSignature) state.recipe = { recipe: null, missing: ["recipe endpoint unavailable"] };
  }
  renderCaseWorkbench();
}

async function refreshCases() {
  try {
    const response = await fetch("/api/cases", { cache: "no-store" });
    if (!response.ok) throw new Error(`case request failed: ${response.status}`);
    const payload = await response.json();
    state.cases = Array.isArray(payload.cases) ? payload.cases : [];
    state.caseError = null;
    const previous = state.caseId;
    if (!state.caseSelected && (state.caseId === "all" || !selectedCase())) {
      const first = state.cases.find((item) => item.case_id && item.status !== "unavailable");
      state.caseId = first ? first.case_id : "all";
    } else if (state.caseId !== "all" && !selectedCase()) state.caseId = "all";
    const chosen = selectedCase();
    const signature = caseSignature(chosen);
    if (previous !== state.caseId || state.caseSignature !== signature ||
        (state.recipe && state.recipe.missing && state.recipe.missing.includes("recipe endpoint unavailable")) ||
        (state.caseId !== "all" && state.recipeCaseId !== state.caseId)) {
      state.caseSignature = signature;
      refreshRecipe(state.caseId);
    }
    if (previous !== state.caseId || state.explanationCaseId !== state.caseId) {
      beginExplanationRequest(state.caseId, true);
      renderExplanations();
    }
    refreshExplanations(state.caseId);
  } catch (_) { state.caseError = "Saved case index unavailable; showing existing episode evidence."; }
  renderCaseWorkbench();
}

function renderCaseWorkbench() {
  const select = byId("case-select");
  const signature = state.cases.map((item) => `${item.case_id || "invalid"}:${item.status || "case"}`).join("|");
  if (select.dataset.signature !== signature) {
    select.replaceChildren();
    const all = document.createElement("option"); all.value = "all"; all.textContent = "All saved evidence"; select.append(all);
    state.cases.forEach((item) => {
      if (!item.case_id || !/^[0-9a-f]{64}$/.test(item.case_id)) return;
      const option = document.createElement("option"); option.value = item.case_id;
      option.textContent = `${item.case_id.slice(0, 12)} · ${item.status === "unavailable" ? "UNAVAILABLE" : item.task.suite + " task " + item.task.task_id}`;
      select.append(option);
    });
    select.dataset.signature = signature;
  }
  select.value = state.caseId;
  const chosen = selectedCase();
  const status = byId("case-status");
  if (state.caseError) setText(status, state.caseError);
  else if (!state.cases.length) setText(status, "No saved cases yet. Import an existing M4 reduction locally: python scripts/manage_cases.py import-m4 --source-root <artifacts-directory> --workspace <case-workspace-outside-source-root>");
  else if (state.caseId === "all") setText(status, "All saved evidence · choose a case to inspect its verified scope.");
  else if (chosen && chosen.status === "unavailable") setText(status, "Saved case entry unavailable. Its source evidence cannot be inspected.");
  else setText(status, `Case ${state.caseId.slice(0, 12)} · ${caseEpisodes().length}/${chosen.evidence.episodes.length} exactly linked episode(s) · saved historical evidence`);
  const fields = [["case-inspection", "inspection"], ["case-recipe-status", "replay_recipe"],
    ["case-replay", "exercised_replay"], ["case-history", "historical_failure"]];
  fields.forEach(([id, key]) => {
    const capability = chosen && chosen.capabilities && chosen.capabilities[key];
    setText(byId(id), capability ? capability.status : "—");
  });
  setText(byId("case-detail-reasons"), chosen && chosen.capabilities
    ? fields.map(([, key]) => {
      const capability = chosen.capabilities[key];
      return `${key.replaceAll("_", " ")}: ${(capability.reasons || capability.missing || []).join(", ") || "no additional reason recorded"}`;
    }).join(" · ") : "");
  if (!chosen || chosen.status === "unavailable") {
    setText(byId("case-prerequisites"), "Select an available case to inspect recipe prerequisites.");
    setText(byId("case-measurements"), "Source-reported measurements unavailable.");
    setText(byId("case-recipe"), "");
    setText(byId("case-export"), "");
    return;
  }
  const missing = chosen.capabilities.replay_recipe.missing || [];
  const media = chosen.evidence.media_availability || {};
  setText(byId("case-prerequisites"), `Missing replay inputs: ${missing.length ? missing.join(", ") : "none"}. Media: ${media.status || "unknown"}. Reduced rectangle is local to this saved search budget; global minimality is unverified. Stopping reason was not retained in this imported case. ${missing.length ? "A metadata directory can still be exported, but the replay recipe remains incomplete." : ""}`);
  const measurements = chosen.measurements || {};
  const shown = (value) => value == null ? "unknown" : value;
  setText(byId("case-measurements"), `Source-reported time: ${shown(measurements.source_reported_elapsed_seconds)} s · Physical episodes: ${shown(measurements.physical_episode_count)} · Valid episodes: ${shown(measurements.valid_episode_count)} · Cost: ${shown(measurements.cost)}`);
  setText(byId("case-recipe"), state.recipeCaseId === state.caseId && state.recipe &&
    state.recipe.missing && state.recipe.missing.includes("recipe endpoint unavailable")
    ? "Validated recipe unavailable. The case endpoint could not be read; retry by refreshing this page."
    : chosen.capabilities.replay_recipe.status === "complete" &&
    state.recipeCaseId === state.caseId && state.recipe && state.recipe.recipe
    ? JSON.stringify(state.recipe.recipe, null, 2)
    : `Replay recipe ${chosen.capabilities.replay_recipe.status}. ${missing.length ? "Add the missing pinned inputs before replay." : "Loading validated recipe…"}`);
  setText(byId("case-export"), chosen.capabilities.inspection.status === "available"
    ? `python scripts/manage_cases.py export --workspace <case-workspace-outside-source-root> --case-id ${chosen.case_id} --output <new-directory>`
    : "Export unavailable while inspection is unavailable.");
}

function renderComparisonStory(primary, comparison) {
  const perturbed = isPerturbed(primary) ? primary : isPerturbed(comparison) ? comparison : null;
  const perturbedArea = perturbationArea(perturbed);
  const suffix = perturbedArea == null ? "" : ` at ${perturbedArea.toFixed(2)}% image occlusion`;
  const displayed = comparison || primary;
  const policyNote = displayed && displayed.outcome === "infrastructure_error" ? " / POLICY NOT EVALUATED" : "";
  setText(byId("comparison-conclusion"), primary && comparison
    ? `${outcomeLabel(primary)} → ${outcomeLabel(comparison)}${suffix}${perturbationPosition(perturbed)}${policyNote}`
    : primary ? "Add a second episode to enable comparison" : "No experiment evidence found");
  const firstRole = savedRoleFor(primary);
  const secondRole = savedRoleFor(comparison);
  setText(byId("primary-role"), firstRole ? `SAVED CASE / ${firstRole.toUpperCase()}` : primary && !isPerturbed(primary)
    ? "REFERENCE / NOMINAL" : "PRIMARY / INVESTIGATION");
  setText(byId("comparison-role"), secondRole ? `SAVED CASE / ${secondRole.toUpperCase()}` : isPerturbed(comparison)
    ? "INVESTIGATION / PERTURBED" : "COMPARISON / REFERENCE");
  byId("comparison-conclusion").dataset.outcome = displayed ? displayed.outcome : "";
}

function defaultComparison() {
  const primary = episodeById(state.primaryId);
  const candidates = displayEpisodes(primary).filter((item) => item.episode_id !== state.primaryId);
  const nominal = candidates.find((item) => isNominal(item) && matchesPrimary(item, primary));
  return nominal || candidates.find(isPerturbed) || null;
}

async function refreshCatalog() {
  const response = await fetch("/api/runs", { cache: "no-store" });
  if (!response.ok) throw new Error(`catalog request failed: ${response.status}`);
  const snapshot = await response.json();
  await refreshCases();
  await refreshReduction();
  state.episodes = snapshot.episodes;
  state.warnings = snapshot.warnings;
  let visible = displayEpisodes();
  if (!visible.some((item) => item.episode_id === state.primaryId)) {
    const primary = visible.find(isPerturbed) || visible[0];
    state.primaryId = primary ? primary.episode_id : null;
    visible = displayEpisodes(episodeById(state.primaryId));
  }
  if (!visible.some((item) => item.episode_id === state.comparisonId)) {
    const comparison = defaultComparison();
    state.comparisonId = comparison ? comparison.episode_id : null;
  }
  render();
}

function renderChannel(channel, id) {
  const select = byId(`${channel}-select`);
  const visible = displayEpisodes();
  const signature = `${state.caseId}:` + visible.map((item) => item.episode_id).join("|");
  if (select.dataset.signature !== signature) {
    select.replaceChildren();
    visible.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.episode_id;
      option.textContent = `${savedRoleFor(item) ? savedRoleFor(item) + " · " : ""}${item.run_name} / ${outcomeLabels[item.outcome]}`;
      select.append(option);
    });
    select.dataset.signature = signature;
  }
  select.value = id || "";
  const episode = episodeById(id);
  const video = byId(`${channel}-video`);
  const empty = byId(`${channel}-empty`);
  if (video.dataset.episodeId !== (id || "")) {
    video.pause();
    if (episode && episode.video_path) video.src = `/media/${encodeURI(episode.video_path)}`;
    else video.removeAttribute("src");
    video.load();
    video.dataset.episodeId = id || "";
  }
  video.hidden = !(episode && episode.video_path);
  empty.hidden = Boolean(episode && episode.video_path);
  setText(empty, episode ? "VIDEO NOT RECORDED" : "NO EVIDENCE");
}

function renderDiagnostics(episode) {
  const aside = byId("diagnostics");
  aside.replaceChildren();
  if (!episode) setText(aside, state.caseId === "all" ? "NO DIAGNOSTIC EVIDENCE" : "NO EXACTLY LINKED EPISODE VIDEO OR TRACE");
  else {
    const title = document.createElement("h2"); title.textContent = "Diagnostic identity";
    const detail = document.createElement("pre");
    detail.textContent = JSON.stringify({ task: episode.instruction, task_id: episode.task_id,
      initial_state: episode.episode_index, seed: episode.seed, env_seed: episode.env_seed,
      perturbation: isPerturbed(episode) ? episode.perturbation : "NOMINAL / NO FAULT",
      provenance: episode.provenance }, null, 2);
    aside.append(title, detail);
  }
  if (episode && state.reduction && state.caseId === "all") {
    const reduction = document.createElement("section"); reduction.className = "reduction-lineage";
    const heading = document.createElement("h2"); heading.textContent = `Reduction session / ${state.reduction.session_name}`;
    const facts = document.createElement("dl");
    const metrics = state.reduction.metrics || {};
    [["Parent area", metrics.parent_area_percent], ["Reduced area", metrics.reduced_area_percent],
      ["Area reduction", metrics.area_reduction_percent]].forEach(([label, value]) => {
      const term = document.createElement("dt"); term.textContent = label;
      const valueNode = document.createElement("dd"); valueNode.textContent = `${value.toFixed(2)}%`;
      facts.append(term, valueNode);
    });
    reduction.append(heading, facts);
    if (state.reduction.certification) {
      const certification = document.createElement("p"); certification.className = "reduction-certification";
      certification.textContent = `Certification ${state.reduction.certification}`;
      reduction.append(certification);
    } else {
      const note = document.createElement("p"); note.className = "reduction-warning";
      note.textContent = `Uncertified terminal result: ${state.reduction.terminal_outcome}`; reduction.append(note);
    }
    aside.append(reduction);
  }
  const selected = selectedCase();
  if (selected && selected.status !== "unavailable" && selected.capabilities.inspection.status === "available") {
    const lineage = document.createElement("section"); lineage.className = "reduction-lineage";
    const heading = document.createElement("h2"); heading.textContent = "Saved case reduction lineage"; lineage.append(heading);
    const entries = selected.evidence.lineage || [];
    const summary = document.createElement("p");
    summary.textContent = entries.length
      ? `${entries.length} accepted reduction step(s), within this case's search budget. The final rectangle is not a proven global minimum.`
      : "No reduction lineage stored for this case.";
    lineage.append(summary);
    entries.forEach((entry, index) => {
      const detail = document.createElement("p");
      const rect = entry.rectangle;
      detail.textContent = `${index + 1}. ${entry.edge} by ${entry.delta}: x=${rect.x}, y=${rect.y}, width=${rect.width}, height=${rect.height}`;
      lineage.append(detail);
    });
    aside.append(lineage);
  }
  if (episode && episode.outcome === "infrastructure_error") {
    const status = document.createElement("p"); status.className = "failure-detail";
    status.textContent = "INFRA ERROR — POLICY NOT EVALUATED"; aside.append(status);
  }
  if (episode && episode.failure_detail) {
    const error = document.createElement("pre"); error.className = "failure-detail";
    error.textContent = episode.failure_detail; aside.append(error);
  }
}

function renderRunList() {
  const list = byId("run-list"); const filter = byId("outcome-filter");
  const visible = displayEpisodes().filter((item) => filter.value === "all" || item.outcome === filter.value);
  const signature = `${state.caseId}:` + visible.map((item) => item.episode_id).join("|");
  if (list.dataset.signature !== signature) {
    list.replaceChildren();
    visible.forEach((episode) => {
      const item = document.createElement("li"); const button = document.createElement("button");
      const fault = episode.perturbation;
      const area = isPerturbed(episode) ? `${((fault.width || 0) * (fault.height || 0) * 100).toFixed(2)}% MASK` : "NOMINAL";
      button.type = "button"; button.dataset.episodeId = episode.episode_id; button.dataset.outcome = episode.outcome;
      button.textContent = `${outcomeLabels[episode.outcome]} · ${episode.steps} STEPS\n${savedRoleFor(episode) ? savedRoleFor(episode) + " · " : ""}${episode.run_name}\n${area}${perturbationPosition(episode)}`;
      button.addEventListener("click", () => { state.primaryId = episode.episode_id; render(); });
      item.append(button); list.append(item);
    });
    list.dataset.signature = signature;
  }
  list.querySelectorAll("button").forEach((button) => button.setAttribute(
    "aria-current", button.dataset.episodeId === state.primaryId ? "true" : "false"));
}

function render() {
  renderCaseWorkbench();
  renderExplanations();
  setText(byId("connection-status"), `READ ONLY / ${displayEpisodes().length} EPISODES`);
  const filter = byId("outcome-filter");
  if (filter.options.length === 1) Object.entries(outcomeLabels).forEach(([value, label]) => {
    const option = document.createElement("option"); option.value = value; option.textContent = label; filter.append(option);
  });
  renderRunList();
  const primary = episodeById(state.primaryId);
  setText(byId("summary-strip"), primary ? `${primary.instruction} / ${outcomeLabels[primary.outcome]} / ${primary.steps} STEPS / ${formatSeconds(primary.elapsed_seconds)} / SEED ${primary.seed}` : "NO EVIDENCE — copy experiment artifacts into the configured directory");
  const comparison = episodeById(state.comparisonId);
  renderComparisonStory(primary, comparison);
  renderChannel("primary", state.primaryId); renderChannel("comparison", state.comparisonId); renderDiagnostics(primary);
  setText(byId("notices"), state.caseId === "all" ? state.warnings.join(" · ") : "");
  if (primary) refreshTrace(primary.episode_id).catch(showNonFatalError); else drawTimeline([]);
}

async function refreshTrace(id) {
  if (state.traces.has(id)) { drawTimeline(state.traces.get(id).points); return; }
  const response = await fetch(`/api/episodes/${id}/trace`, { cache: "no-store" });
  if (!response.ok) throw new Error(`trace request failed: ${response.status}`);
  const trace = await response.json(); state.traces.set(id, trace);
  if (state.primaryId === id) { drawTimeline(trace.points); if (trace.warnings.length) showNonFatalError(trace.warnings.join(" · ")); }
}

function drawTimeline(points) {
  const canvas = byId("timeline"); const width = Math.max(320, canvas.clientWidth); const height = 96;
  const ratio = window.devicePixelRatio || 1; canvas.width = width * ratio; canvas.height = height * ratio;
  const context = canvas.getContext("2d"); context.scale(ratio, ratio); context.clearRect(0, 0, width, height);
  context.strokeStyle = "#2b3536"; context.beginPath(); context.moveTo(12, 60); context.lineTo(width - 12, 60); context.stroke();
  if (!points.length) { setText(byId("timeline-detail"), "TRACE NOT RECORDED"); return; }
  const maxStep = Math.max(1, points[points.length - 1].step || points.length - 1);
  points.forEach((point, index) => {
    const x = 12 + ((point.step == null ? index : point.step) / maxStep) * (width - 24);
    context.strokeStyle = "#ffb000"; context.beginPath(); context.moveTo(x, 60); context.lineTo(x, 60 - Math.min(34, Math.abs(Number(point.reward || 0)) * 20)); context.stroke();
    if (point.success) { context.fillStyle = "#70e09a"; context.fillRect(x - 2, 18, 4, 12); }
    if (point.done && !point.success) { context.fillStyle = "#ff5d56"; context.fillRect(x - 2, 75, 4, 12); }
  });
  canvas.onpointermove = (event) => {
    const rectangle = canvas.getBoundingClientRect(); const fraction = (event.clientX - rectangle.left) / rectangle.width;
    const index = Math.max(0, Math.min(points.length - 1, Math.round(fraction * (points.length - 1)))); const point = points[index];
    setText(byId("timeline-detail"), `STEP ${point.step == null ? index : point.step} / REWARD ${point.reward || 0} / DONE ${Boolean(point.done)} / SUCCESS ${Boolean(point.success)}`);
  };
  setText(byId("timeline-detail"), `${points.length} TRACE EVENTS`);
}

let synchronizing = false;
async function playLinked(source, peer) {
  if (!state.linked || synchronizing || !peer.src) return;
  synchronizing = true;
  try { if (Math.abs(peer.currentTime - source.currentTime) > 0.12) peer.currentTime = Math.min(source.currentTime, peer.duration || source.currentTime); await peer.play(); }
  finally { synchronizing = false; }
}
const primaryVideo = byId("primary-video"); const comparisonVideo = byId("comparison-video"); const videos = [primaryVideo, comparisonVideo];
[[primaryVideo, comparisonVideo], [comparisonVideo, primaryVideo]].forEach(([source, peer]) => {
  source.addEventListener("play", () => playLinked(source, peer).catch(showNonFatalError));
  source.addEventListener("pause", () => { if (state.linked && !synchronizing) peer.pause(); });
  source.addEventListener("seeking", () => { if (state.linked && !synchronizing && peer.src && Math.abs(peer.currentTime - source.currentTime) > .12) peer.currentTime = Math.min(source.currentTime, peer.duration || source.currentTime); });
  source.addEventListener("ratechange", () => { if (state.linked && !synchronizing) peer.playbackRate = source.playbackRate; });
});
byId("play-pair").addEventListener("click", () => Promise.all(videos.filter((video) => video.src).map((video) => video.play())).catch(showNonFatalError));
byId("pause-pair").addEventListener("click", () => videos.forEach((video) => video.pause()));
byId("align-pair").addEventListener("click", () => videos.forEach((video) => { video.currentTime = 0; }));
byId("link-playback").addEventListener("change", (event) => {
  state.linked = event.target.checked;
  setText(byId("link-state"), state.linked ? "LINKED" : "UNLINKED");
});
byId("playback-rate").addEventListener("change", (event) => videos.forEach((video) => { video.playbackRate = Number(event.target.value); }));
byId("outcome-filter").addEventListener("change", render);
byId("case-select").addEventListener("change", (event) => {
  state.caseId = event.target.value;
  state.caseSelected = true;
  state.caseSignature = caseSignature(selectedCase());
  beginExplanationRequest(state.caseId, true);
  renderExplanations();
  refreshRecipe(state.caseId);
  refreshExplanations(state.caseId);
  const visible = displayEpisodes();
  state.primaryId = (visible.find(isPerturbed) || visible[0] || {}).episode_id || null;
  state.comparisonId = (defaultComparison() || {}).episode_id || null;
  render();
});
byId("explanation-history").addEventListener("change", (event) => {
  state.explanationReportId = event.target.value;
  renderExplanations();
});
["primary", "comparison"].forEach((channel) => byId(`${channel}-select`).addEventListener("change", (event) => { state[channel === "primary" ? "primaryId" : "comparisonId"] = event.target.value; render(); }));
window.setInterval(() => { if (state.linked && !primaryVideo.paused && comparisonVideo.src && Math.abs(primaryVideo.currentTime - comparisonVideo.currentTime) > .12) comparisonVideo.currentTime = Math.min(primaryVideo.currentTime, comparisonVideo.duration || primaryVideo.currentTime); }, 250);
refreshCatalog().catch(showFatalError);
window.setInterval(() => refreshCatalog().catch(showFatalError), state.refreshMs);
