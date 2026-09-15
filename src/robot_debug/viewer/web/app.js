const state = {
  episodes: [], warnings: [], primaryId: null, comparisonId: null,
  traces: new Map(), linked: true, refreshMs: 2000,
};

const outcomeLabels = {
  success: "SUCCESS", task_failure: "TASK FAILURE", episode_timeout: "TIMEOUT",
  infrastructure_error: "INFRA ERROR",
};
const byId = (id) => document.getElementById(id);
const episodeById = (id) => state.episodes.find((episode) => episode.episode_id === id);
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
  const nominal = representativeNominal(state.episodes, primary);
  return state.episodes.filter((episode) => !isNominal(episode) || episode.episode_id === (nominal && nominal.episode_id));
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

function renderComparisonStory(primary, comparison) {
  const perturbed = isPerturbed(primary) ? primary : isPerturbed(comparison) ? comparison : null;
  const perturbedArea = perturbationArea(perturbed);
  const suffix = perturbedArea == null ? "" : ` at ${perturbedArea.toFixed(2)}% image occlusion`;
  const displayed = comparison || primary;
  const policyNote = displayed && displayed.outcome === "infrastructure_error" ? " / POLICY NOT EVALUATED" : "";
  setText(byId("comparison-conclusion"), primary && comparison
    ? `${outcomeLabel(primary)} → ${outcomeLabel(comparison)}${suffix}${perturbationPosition(perturbed)}${policyNote}`
    : primary ? "Add a second episode to enable comparison" : "No experiment evidence found");
  setText(byId("primary-role"), primary && !isPerturbed(primary)
    ? "REFERENCE / NOMINAL" : "PRIMARY / INVESTIGATION");
  setText(byId("comparison-role"), isPerturbed(comparison)
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
  const signature = visible.map((item) => item.episode_id).join("|");
  if (select.dataset.signature !== signature) {
    select.replaceChildren();
    visible.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.episode_id;
      option.textContent = `${item.run_name} / ${outcomeLabels[item.outcome]}`;
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
  if (!episode) { setText(aside, "NO DIAGNOSTIC EVIDENCE"); return; }
  const title = document.createElement("h2"); title.textContent = "Diagnostic identity";
  const detail = document.createElement("pre");
  detail.textContent = JSON.stringify({ task: episode.instruction, task_id: episode.task_id,
    initial_state: episode.episode_index, seed: episode.seed, env_seed: episode.env_seed,
    perturbation: isPerturbed(episode) ? episode.perturbation : "NOMINAL / NO FAULT",
    provenance: episode.provenance }, null, 2);
  aside.append(title, detail);
  if (episode.outcome === "infrastructure_error") {
    const status = document.createElement("p"); status.className = "failure-detail";
    status.textContent = "INFRA ERROR — POLICY NOT EVALUATED"; aside.append(status);
  }
  if (episode.failure_detail) {
    const error = document.createElement("pre"); error.className = "failure-detail";
    error.textContent = episode.failure_detail; aside.append(error);
  }
}

function renderRunList() {
  const list = byId("run-list"); const filter = byId("outcome-filter");
  const visible = displayEpisodes().filter((item) => filter.value === "all" || item.outcome === filter.value);
  const signature = visible.map((item) => item.episode_id).join("|");
  if (list.dataset.signature !== signature) {
    list.replaceChildren();
    visible.forEach((episode) => {
      const item = document.createElement("li"); const button = document.createElement("button");
      const fault = episode.perturbation;
      const area = isPerturbed(episode) ? `${((fault.width || 0) * (fault.height || 0) * 100).toFixed(2)}% MASK` : "NOMINAL";
      button.type = "button"; button.dataset.episodeId = episode.episode_id; button.dataset.outcome = episode.outcome;
      button.textContent = `${outcomeLabels[episode.outcome]} · ${episode.steps} STEPS\n${episode.run_name}\n${area}${perturbationPosition(episode)}`;
      button.addEventListener("click", () => { state.primaryId = episode.episode_id; render(); });
      item.append(button); list.append(item);
    });
    list.dataset.signature = signature;
  }
  list.querySelectorAll("button").forEach((button) => button.setAttribute(
    "aria-current", button.dataset.episodeId === state.primaryId ? "true" : "false"));
}

function render() {
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
  setText(byId("notices"), state.warnings.join(" · "));
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
["primary", "comparison"].forEach((channel) => byId(`${channel}-select`).addEventListener("change", (event) => { state[channel === "primary" ? "primaryId" : "comparisonId"] = event.target.value; render(); }));
window.setInterval(() => { if (state.linked && !primaryVideo.paused && comparisonVideo.src && Math.abs(primaryVideo.currentTime - comparisonVideo.currentTime) > .12) comparisonVideo.currentTime = Math.min(primaryVideo.currentTime, comparisonVideo.duration || primaryVideo.currentTime); }, 250);
refreshCatalog().catch(showFatalError);
window.setInterval(() => refreshCatalog().catch(showFatalError), state.refreshMs);
