"use strict";
// A simple list and detail view of the diagnoses registered by robot_debug.case_register.
// Everything is rendered with textContent; the report is shown as preformatted text.
const el = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text != null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
};
const byId = (id) => document.getElementById(id);
const roleTitles = { original: "Original failure", minimal: "Minimal failing scene", reference: "Passing reference" };

async function getJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response.json();
}

function listLabel(item) {
  const bits = [item.name || item.case_id.slice(0, 12)];
  if (item.mode) bits.push(item.mode);
  if (item.suite != null) bits.push(`${item.suite} task ${item.task_id}`);
  return bits.join(" · ");
}

function renderList(items) {
  const list = byId("diagnosis-list");
  list.replaceChildren();
  byId("diagnosis-status").textContent = items.length
    ? `${items.length} registered diagnos${items.length === 1 ? "is" : "es"}`
    : "No registered diagnoses yet. Run faultline diagnose first.";
  items.forEach((item) => {
    const entry = el("li");
    const button = el("button", listLabel(item));
    button.type = "button";
    button.addEventListener("click", () => showDetail(item.case_id));
    entry.append(button);
    list.append(entry);
  });
}

function field(label, value) {
  if (value == null || value === "") return null;
  const row = el("p");
  row.append(el("strong", label + ": "), document.createTextNode(String(value)));
  return row;
}

function renderDetail(item) {
  const main = byId("diagnosis-detail");
  main.replaceChildren(el("h2", item.name || item.case_id));
  [field("Case", item.case_id), field("Mode", item.mode), field("Task", item.instruction),
   field("Failing start", item.failing_start), field("Reference start", item.reference_start),
   field("Stop reason", item.stop_reason), field("Reduced", item.reduced),
   field("Minimal cause", item.sentence), field("Hypothesis verdict", item.hypothesis_verdict),
   field("Explanation", item.explanation_status)].forEach((row) => row && main.append(row));
  const videos = el("section");
  videos.append(el("h3", "Videos"));
  ["original", "minimal", "reference"].forEach((role) => {
    const video = (item.videos || {})[role];
    const figure = el("figure");
    figure.append(el("figcaption", roleTitles[role]));
    if (video && video.url) {
      const player = document.createElement("video");
      player.controls = true;
      player.preload = "metadata";
      player.src = video.url;
      figure.append(player, el("p", video.outcome ? `Outcome: ${video.outcome}` : ""));
    } else {
      figure.append(el("p", "Video not available"));
    }
    videos.append(figure);
  });
  main.append(videos);
  if (item.explanation && item.explanation.interpretation) {
    main.append(el("h3", "Nemotron interpretation (human review required)"),
                el("pre", JSON.stringify(item.explanation.interpretation, null, 2)));
  }
  main.append(el("h3", "Report"), el("pre", item.report == null ? "No report was registered." : item.report));
}

async function showDetail(caseId) {
  try {
    renderDetail((await getJson(`/api/diagnoses/${caseId}`)).diagnosis);
  } catch (error) {
    byId("diagnosis-detail").replaceChildren(el("p", error.message));
  }
}

getJson("/api/diagnoses")
  .then((payload) => renderList(payload.diagnoses || []))
  .catch((error) => { byId("diagnosis-status").textContent = error.message; });
