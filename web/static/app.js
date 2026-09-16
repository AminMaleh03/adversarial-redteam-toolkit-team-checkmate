(function () {
  "use strict";
  var viewHome = document.getElementById("view-home");
  var viewExecution = document.getElementById("view-execution");
  var execHeading = document.getElementById("exec-heading");
  var execBack = document.getElementById("exec-back");
  var navLiveDemo = document.getElementById("nav-live-demo");
  var runBtn = document.getElementById("run-btn");
  var retryBtn = document.getElementById("retry-btn");
  var evaluationSelect = document.getElementById("demo-evaluation");
  var modelDescription = document.getElementById("model-description");
  var modelIdentity = document.getElementById("model-identity");
  var heroControlPaired = document.getElementById("hero-control-paired");
  var heroControlSingle = document.getElementById("hero-control-single");
  var sameModelLabelEl = document.getElementById("same-model-label");
  var sameModelNoteEl = document.getElementById("same-model-note");
  var cardsEl = document.getElementById("version-context");
  var stageListEl = document.getElementById("stage-list");
  var footerNoteEl = document.getElementById("exec-model-note");
  var timer = null;
  var launching = false;
  var checking = false;
  var generation = 0;
  var activeRunId = null;
  var activeEvaluationId = null;
  var renderedEvaluationId = null;
  var POLL_MS = 1500;

  // v6.1 Phase 2: one descriptor per registry evaluation (emotion.core paired, sentiment.core
  // single-target) -- the progress DOM is generated from whichever one matches the run's real
  // evaluation_id, never a fixed V1/V2 template shown for every evaluation.
  var descriptorsEl = document.getElementById("demo-descriptors");
  var DESCRIPTORS = descriptorsEl ? JSON.parse(descriptorsEl.textContent) : {};

  function descriptorFor(evaluationId) {
    return DESCRIPTORS[evaluationId] || DESCRIPTORS["emotion.core"];
  }

  function renderProgressFor(evaluationId) {
    if (renderedEvaluationId === evaluationId) return;
    renderedEvaluationId = evaluationId;
    window.rlRenderProgress(descriptorFor(evaluationId), {
      cardsEl: cardsEl, sameModelLabelEl: sameModelLabelEl, sameModelNoteEl: sameModelNoteEl,
      stageListEl: stageListEl, footerNoteEl: footerNoteEl,
    });
  }

  function executionRoute() { return window.location.hash === "#demo"; }
  function showHome() {
    generation++;
    clearTimeout(timer); timer = null;
    viewHome.hidden = false; viewExecution.hidden = true; execBack.hidden = true;
    document.body.classList.remove("has-back");
    navLiveDemo.removeAttribute("aria-current");
    document.getElementById("nav-home").setAttribute("aria-current", "page");
  }
  function activateExecutionView() {
    if (!executionRoute()) window.history.pushState({ redLab: "demo" }, "", "/#demo");
    var entering = viewExecution.hidden;
    viewHome.hidden = true; viewExecution.hidden = false; execBack.hidden = false;
    document.body.classList.add("has-back");
    document.getElementById("exec-failure").hidden = true;
    document.getElementById("exec-body").hidden = false;
    navLiveDemo.setAttribute("aria-current", "page");
    document.getElementById("nav-home").removeAttribute("aria-current");
    if (entering) execHeading.focus();
  }
  function showFailure(message) {
    execHeading.textContent = "Live demo paused";
    document.getElementById("exec-body").hidden = true;
    document.getElementById("exec-failure").hidden = false;
    document.getElementById("exec-error").textContent = message;
    retryBtn.disabled = false;
  }
  function ensurePolling() {
    if (timer !== null || !executionRoute()) return;
    timer = setTimeout(function () { timer = null; poll(); }, POLL_MS);
  }
  function applyState(state) {
    if (!executionRoute()) return;
    // A late response from a previous model/run must never replace the selected view.
    if ((activeRunId && state.run_id && state.run_id !== activeRunId) ||
        (activeEvaluationId && state.evaluation_id && state.evaluation_id !== activeEvaluationId)) return;
    if (state.status === "complete") {
      // Replace transient execution on completion, reload and BFCache reattachment.
      // Fresh Home visits must never redirect to a previous visitor's result.
      if (state.result_url) window.location.replace(state.result_url);
      else showFailure("The run finished but its results are unavailable. Please retry.");
      return;
    }
    if (state.status === "failed" || state.status === "busy") {
      showFailure(state.error || "Red Lab is running another experiment. Please try again shortly."); return;
    }
    if (state.status !== "running") {
      showFailure("There is no active demo to rejoin. Start a new live demo."); return;
    }
    renderProgressFor(state.evaluation_id || "emotion.core");
    execHeading.textContent = state.stage === "complete" ? "Opening your results…" : state.message || "Running…";
    var pct = state.percent || 0;
    document.getElementById("progress-fill").style.width = pct + "%";
    var bar = document.getElementById("progress-bar");
    bar.setAttribute("aria-valuenow", String(pct));
    bar.setAttribute("aria-valuetext", pct + "%, " + execHeading.textContent);
    document.getElementById("exec-percent").textContent = pct + "%";
    var descriptor = descriptorFor(state.evaluation_id || "emotion.core");
    var stageItems = stageListEl.querySelectorAll("li");
    stageItems.forEach(function (item) {
      var mappedIndex = descriptor.stage_order.indexOf(item.dataset.stage);
      item.classList.toggle("done", mappedIndex < state.stage_index);
      item.classList.toggle("active", mappedIndex === state.stage_index);
    });
    window.rlUpdateLanes(state.stage, descriptor.stage_order, viewExecution);
    ensurePolling();
  }
  function poll() {
    var current = generation;
    fetch("/api/status", { cache: "no-store" })
      .then(function (res) { if (!res.ok) throw new Error(); return res.json(); })
      .then(function (state) { if (current === generation) applyState(state); })
      .catch(function () {
        if (current === generation && executionRoute()) {
          execHeading.textContent = "Reconnecting to live progress…"; ensurePolling();
        }
      });
  }
  function startRun() {
    if (launching) return;
    launching = true; activateExecutionView();
    execHeading.textContent = "Launching adversarial test…";
    activeEvaluationId = evaluationSelect ? evaluationSelect.value : "emotion.core";
    renderProgressFor(activeEvaluationId);
    fetch("/api/run", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ evaluation_id: activeEvaluationId, mode: "demo" })
    })
      .then(function (res) {
        return res.json().then(function (data) { return { ok: res.ok, status: res.status, data: data }; });
      })
      .then(function (response) {
        launching = false;
        if (!response.ok) {
          showFailure(response.data.detail || "Red Lab is running another experiment. Please try again shortly.");
          return;
        }
        activeRunId = response.data.run_id;
        applyState(response.data);
      })
      .catch(function () {
        // The POST may have succeeded before the response was lost: reconcile, never repost.
        launching = false; poll();
      });
  }
  function goToLiveDemo() {
    if (checking || launching) return;
    checking = true;
    var wasExecution = executionRoute();
    var current = generation;
    var selected = evaluationSelect ? evaluationSelect.value : "emotion.core";
    fetch("/api/status", { cache: "no-store" })
      .then(function (res) { if (!res.ok) throw new Error(); return res.json(); })
      .then(function (state) {
        checking = false;
        if (current !== generation) return;
        // A server-side job can keep running after Back leaves the execution view (Back
        // only stops client polling). Reattaching here must never bind the freshly
        // selected evaluation to a different in-flight run's progress.
        if (state.status === "running" && state.evaluation_id && state.evaluation_id !== selected) {
          showFailure("Red Lab is running another experiment. Please try again shortly.");
          return;
        }
        if (state.status === "running" || (wasExecution && state.status === "complete")) {
          activeRunId = state.run_id; activeEvaluationId = state.evaluation_id;
          activateExecutionView(); applyState(state);
        } else startRun();
      })
      .catch(function () {
        checking = false;
        if (current !== generation) return;
        activateExecutionView(); execHeading.textContent = "Reconnecting to live progress…"; ensurePolling();
      });
  }
  runBtn.addEventListener("click", goToLiveDemo);
  retryBtn.addEventListener("click", goToLiveDemo);
  navLiveDemo.addEventListener("click", function (event) { event.preventDefault(); goToLiveDemo(); });
  document.getElementById("nav-home").addEventListener("click", function (event) {
    event.preventDefault();
    if (executionRoute()) window.history.pushState({ redLab: "home" }, "", "/");
    showHome();
  });
  function reconcile(fresh) {
    generation++; clearTimeout(timer); timer = null;
    if (executionRoute()) { activateExecutionView(); poll(); }
    else if (window.location.hash === "#run") {
      window.history.replaceState({ redLab: "home" }, "", "/"); showHome(); goToLiveDemo();
    } else {
      showHome();
      if (fresh) {
        var current = generation;
        fetch("/api/status", { cache: "no-store" }).then(function (res) { return res.json(); })
          .then(function (state) {
            if (current === generation && state.status === "running") {
              activeRunId = state.run_id; activeEvaluationId = state.evaluation_id;
              if (evaluationSelect && state.evaluation_id) evaluationSelect.value = state.evaluation_id;
              activateExecutionView(); applyState(state);
            }
          }).catch(function () {});
      }
    }
  }
  window.addEventListener("popstate", function () { reconcile(false); });
  window.addEventListener("pageshow", function (event) { if (event.persisted) reconcile(false); });
  window.addEventListener("pagehide", function () { generation++; clearTimeout(timer); timer = null; });
  function updateModelCopy() {
    var sentiment = evaluationSelect && evaluationSelect.value === "sentiment.core";
    if (modelDescription) modelDescription.textContent = sentiment ?
      "Single-target, two-label sentiment robustness evaluation; no before/after claim is made." :
      "Paired, seven-label emotion robustness comparison.";
    if (modelIdentity) modelIdentity.textContent = sentiment ?
      "Model: distilbert-base-uncased-finetuned-sst-2-english · 2 sentiment labels" :
      "Model: j-hartmann/emotion-english-distilroberta-base · 7 emotion labels";
    // V6.5: the V1/V2 hardening badges only ever applied to emotion -- sentiment has no
    // sentiment_v2, so it gets its own single-target indicator instead of inheriting them.
    if (heroControlPaired) heroControlPaired.hidden = sentiment;
    if (heroControlSingle) heroControlSingle.hidden = !sentiment;
  }
  if (evaluationSelect) evaluationSelect.addEventListener("change", function () {
    generation++; clearTimeout(timer); timer = null;
    activeRunId = null; activeEvaluationId = null;
    updateModelCopy(); showHome();
  });
  updateModelCopy();
  reconcile(true);

  // V6.5: rotate the hero statement among its ~3 accurate messages. All lines are stacked
  // in one CSS grid cell (app.css's .hero-statement), so swapping .is-active never resizes
  // the container -- no layout jump. Reduced-motion visitors get a static first line.
  var heroLines = document.querySelectorAll(".hero-statement-line");
  if (heroLines.length > 1 && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    var heroIndex = 0;
    setInterval(function () {
      heroLines[heroIndex].classList.remove("is-active");
      heroIndex = (heroIndex + 1) % heroLines.length;
      heroLines[heroIndex].classList.add("is-active");
    }, 5000);
  }
})();
