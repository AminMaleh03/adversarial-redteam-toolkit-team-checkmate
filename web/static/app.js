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
  var stageItems = document.querySelectorAll(".stage-list li");
  var timer = null;
  var launching = false;
  var checking = false;
  var generation = 0;
  var activeRunId = null;
  var activeEvaluationId = null;
  var POLL_MS = 1500;
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
    execHeading.textContent = state.stage === "complete" ? "Opening your results…" : state.message || "Running…";
    var pct = state.percent || 0;
    document.getElementById("progress-fill").style.width = pct + "%";
    var bar = document.getElementById("progress-bar");
    bar.setAttribute("aria-valuenow", String(pct));
    bar.setAttribute("aria-valuetext", pct + "%, " + execHeading.textContent);
    document.getElementById("exec-percent").textContent = pct + "%";
    stageItems.forEach(function (item, index) {
      item.classList.toggle("done", index < state.stage_index);
      item.classList.toggle("active", index === state.stage_index);
    });
    window.rlUpdateLanes(state.stage, stageItems, viewExecution);
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
    fetch("/api/status", { cache: "no-store" })
      .then(function (res) { if (!res.ok) throw new Error(); return res.json(); })
      .then(function (state) {
        checking = false;
        if (current !== generation) return;
        if (state.status === "running" || (wasExecution && state.status === "complete")) {
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
  }
  if (evaluationSelect) evaluationSelect.addEventListener("change", function () {
    generation++; clearTimeout(timer); timer = null;
    activeRunId = null; activeEvaluationId = null;
    updateModelCopy(); showHome();
  });
  updateModelCopy();
  reconcile(true);
})();
