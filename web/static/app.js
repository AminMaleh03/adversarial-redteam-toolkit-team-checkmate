(function () {
  "use strict";

  var viewHome = document.getElementById("view-home");
  var viewExecution = document.getElementById("view-execution");
  var runBtn = document.getElementById("run-btn");
  var retryBtn = document.getElementById("retry-btn");
  var navLiveDemo = document.getElementById("nav-live-demo");
  var execHeading = document.getElementById("exec-heading");
  var execBody = document.getElementById("exec-body");
  var execFailure = document.getElementById("exec-failure");
  var execError = document.getElementById("exec-error");
  var progressBar = document.getElementById("progress-bar");
  var progressFill = document.getElementById("progress-fill");
  var execPercent = document.getElementById("exec-percent");
  var stageItems = document.querySelectorAll(".stage-list li");
  var navToggle = document.getElementById("nav-toggle");
  var primaryNav = document.getElementById("primary-nav");
  var POLL_MS = 1500;
  var polling = false;
  var launching = false;
  var redirectTimer = null;
  var COMPLETE_REDIRECT_DELAY_MS = 900;

  // Mobile compact/collapsible menu -- keeps navigation reachable on narrow screens
  // instead of letting the header wrap into an awkward multi-line block. Unchanged by V5.2.
  if (navToggle && primaryNav) {
    navToggle.addEventListener("click", function () {
      var open = primaryNav.classList.toggle("open");
      navToggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    primaryNav.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        primaryNav.classList.remove("open");
        navToggle.setAttribute("aria-expanded", "false");
      });
    });
  }

  function setStageClasses(currentIndex) {
    stageItems.forEach(function (li, idx) {
      li.classList.remove("active", "done");
      if (idx < currentIndex) {
        li.classList.add("done");
      } else if (idx === currentIndex) {
        li.classList.add("active");
      }
    });
  }

  function setProgress(percent, message) {
    var pct = percent || 0;
    progressFill.style.width = pct + "%";
    progressBar.setAttribute("aria-valuenow", String(pct));
    if (message) {
      progressBar.setAttribute("aria-valuetext", pct + "%, " + message);
    }
    if (execPercent) execPercent.textContent = pct + "%";
  }

  // Switches the page from the landing view into the dedicated, viewport-filling execution
  // state (System V5.2). The home hero is fully hidden, not just scrolled past -- the
  // execution view becomes the only visible primary content.
  function activateExecutionView() {
    if (viewHome) viewHome.hidden = true;
    if (viewExecution) {
      viewExecution.hidden = false;
      viewExecution.classList.remove("is-complete");
    }
    if (execFailure) execFailure.hidden = true;
    if (execBody) execBody.hidden = false;
    if (execHeading) execHeading.focus();
  }

  function showFailure(message) {
    if (redirectTimer) {
      clearTimeout(redirectTimer);
      redirectTimer = null;
    }
    if (execHeading) execHeading.textContent = "LIVE DEMO FAILED";
    if (execBody) execBody.hidden = true;
    if (execFailure) execFailure.hidden = false;
    if (execError) execError.textContent = message || "The live run failed. Please try again.";
    if (retryBtn) retryBtn.disabled = false;
  }

  function applyState(state) {
    if (state.status === "running") {
      if (execHeading) execHeading.textContent = state.message || "Running...";
      setProgress(state.percent, state.message);
      setStageClasses(state.stage_index);
      ensurePolling();
    } else if (state.status === "complete") {
      // Same heading element/class as every in-progress stage message (System V5.2 fix --
      // the completion state must feel like the final stage of one experience, not a
      // shrunken afterthought), with a restrained success-color accent, no animation.
      if (execHeading) execHeading.textContent = "Experiment complete";
      if (viewExecution) viewExecution.classList.add("is-complete");
      setProgress(100, "Experiment complete");
      setStageClasses(stageItems.length);
      if (state.result_url && !redirectTimer) {
        redirectTimer = setTimeout(function () {
          window.location.href = state.result_url;
        }, COMPLETE_REDIRECT_DELAY_MS);
      }
    } else if (state.status === "failed") {
      showFailure(state.error);
    }
  }

  function ensurePolling() {
    if (polling) return;
    polling = true;
    setTimeout(poll, POLL_MS);
  }

  function poll() {
    fetch("/api/status")
      .then(function (res) { return res.json(); })
      .then(function (state) {
        polling = false;
        applyState(state);
      })
      .catch(function () {
        polling = false;
      });
  }

  function startRun(triggerBtn) {
    if (launching) return;
    launching = true;
    if (triggerBtn) triggerBtn.disabled = true;
    activateExecutionView();
    if (execHeading) execHeading.textContent = "Launching adversarial test…";
    setProgress(0, "Launching adversarial test");
    setStageClasses(-1);
    fetch("/api/run", { method: "POST" })
      .then(function (res) { return res.json(); })
      .then(function (state) {
        launching = false;
        applyState(state);
      })
      .catch(function () {
        launching = false;
        if (triggerBtn) triggerBtn.disabled = false;
        showFailure("Could not start the live run. Please try again.");
      });
  }

  // Single source of truth for launching a run: the nav "Live Demo" item reuses the exact
  // same startRun()/activateExecutionView() functions the main CTA and Retry use (System
  // V5.2 fix) rather than a second, parallel run-start path. If a run is already active it
  // reattaches to the real state instead of resetting the visible progress back to 0% --
  // and never calls POST /api/run a second time while one is already running.
  function goToLiveDemo(triggerEl) {
    fetch("/api/status")
      .then(function (res) { return res.json(); })
      .then(function (state) {
        if (state.status === "running") {
          activateExecutionView();
          applyState(state);
        } else {
          startRun(triggerEl);
        }
      })
      .catch(function () {
        startRun(triggerEl);
      });
  }

  if (runBtn) {
    runBtn.addEventListener("click", function () { startRun(runBtn); });
  }
  if (retryBtn) {
    retryBtn.addEventListener("click", function () { startRun(retryBtn); });
  }
  if (navLiveDemo) {
    navLiveDemo.addEventListener("click", function (e) {
      e.preventDefault();
      goToLiveDemo(navLiveDemo);
    });
  }

  // A run may already be active if another visitor started one, or this visitor refreshed
  // mid-run -- reattach to that live progress instead of pretending the home page is idle.
  // A completed or failed prior job never auto-navigates a fresh visitor (System V4/V5.2):
  // only a currently RUNNING job causes the execution view to appear on load.
  fetch("/api/status")
    .then(function (res) { return res.json(); })
    .then(function (state) {
      if (state.status === "running") {
        activateExecutionView();
        applyState(state);
      }
    })
    .catch(function () {});
})();
