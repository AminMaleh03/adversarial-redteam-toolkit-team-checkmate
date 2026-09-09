(function () {
  "use strict";

  var runBtn = document.getElementById("run-btn");
  var ctaNote = document.getElementById("cta-note");
  var progressPanel = document.getElementById("progress-panel");
  var progressMessage = document.getElementById("progress-message");
  var progressFill = document.getElementById("progress-fill");
  var progressError = document.getElementById("progress-error");
  var stageItems = document.querySelectorAll(".stage-list li");
  var POLL_MS = 1500;
  var polling = false;

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

  function applyState(state) {
    if (state.status === "running") {
      progressPanel.hidden = false;
      progressError.hidden = true;
      progressMessage.textContent = state.message || "Running...";
      progressFill.style.width = (state.percent || 0) + "%";
      setStageClasses(state.stage_index);
      if (!polling) {
        polling = true;
        setTimeout(poll, POLL_MS);
      }
    } else if (state.status === "complete") {
      progressFill.style.width = "100%";
      progressMessage.textContent = "Complete";
      setStageClasses(stageItems.length);
      if (state.result_url) {
        window.location.href = state.result_url;
      }
    } else if (state.status === "failed") {
      progressPanel.hidden = false;
      progressError.hidden = false;
      progressError.textContent = state.error || "The live run failed. Please try again.";
      if (runBtn) {
        runBtn.disabled = false;
        runBtn.textContent = "Run Live Attack Test";
      }
    }
  }

  function poll() {
    fetch("/api/status")
      .then(function (res) { return res.json(); })
      .then(function (state) {
        applyState(state);
        if (state.status === "running") {
          setTimeout(poll, POLL_MS);
        } else {
          polling = false;
        }
      })
      .catch(function () {
        polling = false;
      });
  }

  function startRun() {
    if (!runBtn || runBtn.disabled) return;
    runBtn.disabled = true;
    runBtn.textContent = "Starting...";
    if (ctaNote) ctaNote.textContent = "Starting the live run inside this container...";
    fetch("/api/run", { method: "POST" })
      .then(function (res) { return res.json(); })
      .then(function (state) {
        applyState(state);
        if (state.status === "running" && !polling) {
          polling = true;
          setTimeout(poll, POLL_MS);
        }
      })
      .catch(function () {
        runBtn.disabled = false;
        runBtn.textContent = "Run Live Attack Test";
      });
  }

  if (runBtn) {
    runBtn.addEventListener("click", startRun);
  }

  // A run may already be active if another visitor started one -- show live progress
  // instead of the idle welcome state, without redirecting anyone into an old result.
  fetch("/api/status")
    .then(function (res) { return res.json(); })
    .then(function (state) {
      if (state.status === "running") {
        if (runBtn) {
          runBtn.disabled = true;
          runBtn.textContent = "A live run is already in progress...";
        }
        applyState(state);
      }
    })
    .catch(function () {});
})();
