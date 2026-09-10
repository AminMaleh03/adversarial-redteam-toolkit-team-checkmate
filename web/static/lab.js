(function () {
  "use strict";

  var STORAGE_KEY = "labJobId";
  var POLL_MS = 1500;

  var viewInput = document.getElementById("view-lab-input");
  var viewExecution = document.getElementById("view-lab-execution");
  var viewResults = document.getElementById("view-lab-results");

  var form = document.getElementById("lab-form");
  var textarea = document.getElementById("lab-text");
  var counter = document.getElementById("lab-counter");
  var errorEl = document.getElementById("lab-error");
  var submitBtn = document.getElementById("lab-submit");
  var maxChars = textarea ? parseInt(textarea.getAttribute("maxlength"), 10) || 800 : 800;

  var execHeading = document.getElementById("lab-exec-heading");
  var execBody = document.getElementById("lab-exec-body");
  var execFailure = document.getElementById("lab-exec-failure");
  var execError = document.getElementById("lab-exec-error");
  var execBusy = document.getElementById("lab-exec-busy");
  var progressBar = document.getElementById("lab-progress-bar");
  var progressFill = document.getElementById("lab-progress-fill");
  var execPercent = document.getElementById("lab-exec-percent");
  var stageItems = document.querySelectorAll("#lab-stage-list li");

  var retryBtn = document.getElementById("lab-retry-btn");
  var editBtn = document.getElementById("lab-edit-btn");
  var busyRetryBtn = document.getElementById("lab-busy-retry-btn");

  var summaryEl = document.getElementById("lab-summary");
  var cleanCardsEl = document.getElementById("lab-clean-cards");
  var variantsEl = document.getElementById("lab-variants");

  var navTestAnother = document.getElementById("nav-test-another");

  var pollTimer = null;
  var generation = 0;
  var launching = false;
  var lastText = "";

  // ---- view switching -----------------------------------------------------------------
  // navTestAnother (the sticky masthead action) is visible ONLY while viewing results --
  // the one place it's needed -- and hidden in every other state, so it's set explicitly
  // in every branch below rather than relying on a single default.
  function showInput() {
    if (viewInput) viewInput.hidden = false;
    if (viewExecution) viewExecution.hidden = true;
    if (viewResults) viewResults.hidden = true;
    if (navTestAnother) navTestAnother.hidden = true;
  }

  function showExecution() {
    if (viewInput) viewInput.hidden = true;
    if (viewExecution) viewExecution.hidden = false;
    if (viewResults) viewResults.hidden = true;
    if (execBody) execBody.hidden = false;
    if (execFailure) execFailure.hidden = true;
    if (execBusy) execBusy.hidden = true;
    if (navTestAnother) navTestAnother.hidden = true;
    if (execHeading && document.activeElement === document.body) execHeading.focus();
  }

  function showResults() {
    if (viewInput) viewInput.hidden = true;
    if (viewExecution) viewExecution.hidden = true;
    if (viewResults) viewResults.hidden = false;
    if (navTestAnother) navTestAnother.hidden = false;
  }

  function showFailure(message) {
    if (viewInput) viewInput.hidden = true;
    if (viewExecution) viewExecution.hidden = false;
    if (viewResults) viewResults.hidden = true;
    if (execBody) execBody.hidden = true;
    if (execBusy) execBusy.hidden = true;
    if (execFailure) execFailure.hidden = false;
    if (navTestAnother) navTestAnother.hidden = true;
    if (execError) execError.textContent = message || "The Red-Team Lab test failed.";
    if (execHeading) execHeading.textContent = "Live Red-Team Lab";
  }

  function showBusy() {
    if (viewInput) viewInput.hidden = true;
    if (viewExecution) viewExecution.hidden = false;
    if (viewResults) viewResults.hidden = true;
    if (execBody) execBody.hidden = true;
    if (execFailure) execFailure.hidden = true;
    if (execBusy) execBusy.hidden = false;
    if (navTestAnother) navTestAnother.hidden = true;
    if (execHeading) execHeading.textContent = "Live Red-Team Lab";
  }

  // ---- character counter / client-side validation --------------------------------------
  function updateCounter() {
    if (!textarea || !counter) return;
    var len = textarea.value.length;
    counter.textContent = len + " / " + maxChars + " characters";
  }

  function showValidationError(message) {
    if (!errorEl) return;
    errorEl.textContent = message;
    errorEl.hidden = false;
  }

  function clearValidationError() {
    if (!errorEl) return;
    errorEl.hidden = true;
    errorEl.textContent = "";
  }

  if (textarea) {
    textarea.addEventListener("input", updateCounter);
    updateCounter();
  }

  // ---- stage list / progress bar (mirrors app.js's pattern) ----------------------------
  function setStageClasses(currentIndex) {
    stageItems.forEach(function (item, index) {
      item.classList.toggle("done", index < currentIndex);
      item.classList.toggle("active", index === currentIndex);
    });
  }

  function setProgress(percent, message) {
    if (progressFill) progressFill.style.width = percent + "%";
    if (progressBar) {
      progressBar.setAttribute("aria-valuenow", String(percent));
      progressBar.setAttribute("aria-valuetext", percent + "%, " + message);
    }
    if (execPercent) execPercent.textContent = percent + "%";
  }

  // ---- sessionStorage (not localStorage -- per-tab, cleared when the tab closes) --------
  function storeJobId(jobId) {
    try {
      sessionStorage.setItem(STORAGE_KEY, jobId);
    } catch (err) { /* private-mode storage errors are non-fatal */ }
  }

  function readJobId() {
    try {
      return sessionStorage.getItem(STORAGE_KEY);
    } catch (err) {
      return null;
    }
  }

  function clearJobId() {
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch (err) { /* ignore */ }
  }

  // ---- safe DOM helpers -- textContent everywhere except the two explicitly trusted,
  // server-escaped diff fields (see renderVariant) -----------------------------------------
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function formatPercent(value) {
    if (value === null || value === undefined) return "n/a";
    return Math.round(value * 1000) / 10 + "%";
  }

  function formatSigned(value) {
    if (value === null || value === undefined) return "n/a";
    var pct = Math.round(value * 1000) / 10;
    return (pct >= 0 ? "+" : "") + pct + "%";
  }

  function renderScoreList(allScores) {
    var details = document.createElement("details");
    details.className = "lab-scores";
    var summary = el("summary", null, "Full probability distribution");
    details.appendChild(summary);
    if (!allScores) {
      details.appendChild(el("p", "caption", "Not available for this response."));
      return details;
    }
    var list = document.createElement("dl");
    list.className = "lab-score-list";
    Object.keys(allScores).sort().forEach(function (label) {
      list.appendChild(el("dt", null, label));
      list.appendChild(el("dd", null, formatPercent(allScores[label])));
    });
    details.appendChild(list);
    return details;
  }

  function renderResultOutcome(container, resultDict) {
    container.appendChild(el("p", "lab-outcome", resultDict.outcome));
    if (resultDict.label) {
      container.appendChild(el("p", "lab-field",
        "Label: " + resultDict.label + " (" + formatPercent(resultDict.confidence) + ")"));
    }
    container.appendChild(el("p", "caption", "Latency: " + Math.round(resultDict.latency_ms) + " ms"));
    container.appendChild(renderScoreList(resultDict.all_scores));
  }

  function renderCleanCard(version, resultDict) {
    var card = el("div", "version-card " + version);
    var title = el("p", "version-card-title",
      version === "v1" ? "V1 — Unhardened Endpoint" : "V2 — Hardened Endpoint");
    card.appendChild(title);
    renderResultOutcome(card, resultDict);
    return card;
  }

  function renderSummary(summary) {
    summaryEl.textContent = "";
    var rows = [
      ["Variants tested", summary.variants_tested, "variants", "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z"],
      ["V1 label flips", summary.v1_flips, "v1", "M4 7h16m-4-4 4 4-4 4 M20 17H4m4-4-4 4 4 4"],
      ["V2 label flips", summary.v2_flips, "v2", "M4 7h16m-4-4 4 4-4 4 M20 17H4m4-4-4 4 4 4"],
      ["Mitigated by V2", summary.mitigated_by_v2, "mitigated", "M12 2 4 5v6c0 5 4 8 8 11 4-3 8-6 8-11V5z M8 12l3 3 5-6"],
      ["Persisting after hardening", summary.persisting_after_hardening, "persisting", "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 8v5 M12 16v.1"],
      ["Safe rejections", summary.safe_rejections, "rejections", "M12 2 4 5v6c0 5 4 8 8 11 4-3 8-6 8-11V5z M8 12h8"],
      ["Endpoint errors", summary.endpoint_errors, "errors", "M12 3 2 21h20z M12 9v5 M12 17v.1"],
    ];
    var list = document.createElement("dl");
    list.className = "lab-summary-list";
    rows.forEach(function (row) {
      var metric = el("div", "lab-metric lab-metric-" + row[2]);
      metric.appendChild(el("dt", null, row[0]));
      var value = el("dd");
      value.appendChild(el("span", "lab-metric-value", row[1]));
      // Decorative geometry stays inside the definition; labels and values remain text.
      var icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      icon.setAttribute("class", "lab-metric-icon");
      icon.setAttribute("viewBox", "0 0 24 24");
      icon.setAttribute("aria-hidden", "true");
      icon.setAttribute("focusable", "false");
      icon.setAttribute("fill", "none");
      icon.setAttribute("stroke", "currentColor");
      icon.setAttribute("stroke-width", "1.6");
      icon.setAttribute("stroke-linecap", "round");
      icon.setAttribute("stroke-linejoin", "round");
      var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", row[3]);
      icon.appendChild(path);
      value.appendChild(icon);
      metric.appendChild(value);
      list.appendChild(metric);
    });
    summaryEl.appendChild(list);
    summaryEl.appendChild(el("p", "lab-summary-verdict",
      summary.mitigated_by_v2 + " variants mitigated by V2 \u00b7 " +
      summary.persisting_after_hardening + " persist after hardening"));
  }

  function renderVersionOutcome(container, label, versionData) {
    var block = el("div", "lab-variant-version");
    block.appendChild(el("p", "version-card-title", label));
    renderResultOutcome(block, versionData.result);
    var flipText = versionData.flip === null ? "Flip: n/a" :
      "Flip: " + (versionData.flip ? "Yes" : "No");
    block.appendChild(el("p", "lab-field", flipText));
    var tv = versionData.tv_distance;
    block.appendChild(el("p", "lab-field",
      "Distribution shift (TV distance): " + (tv === null || tv === undefined ? "n/a" : tv)));
    if (versionData.confidence_change) {
      block.appendChild(el("p", "caption",
        "Confidence: " + formatPercent(versionData.confidence_change.clean) + " → " +
        formatPercent(versionData.confidence_change.attacked) +
        " (" + formatSigned(versionData.confidence_change.delta) + ")"));
    }
    container.appendChild(block);
  }

  function renderVariant(variant) {
    var card = el("div", "panel lab-variant-card");
    var heading = el("h3", null, variant.label);
    card.appendChild(heading);
    card.appendChild(el("p", "caption", variant.description));

    var diagBadge = el("span", "lab-diagnosis-badge lab-diagnosis-" + variant.diagnosis.toLowerCase(),
      variant.diagnosis_label);
    card.appendChild(diagBadge);
    card.appendChild(el("p", "lab-field", variant.remediation));

    var diffBlock = document.createElement("details");
    diffBlock.className = "lab-diff";
    diffBlock.appendChild(el("summary", null, "Show text change"));
    var originalP = el("p", "lab-diff-line");
    // Trusted, server-escaped HTML (run_all.highlight_diff_html) -- the only two fields in
    // this whole file ever set via innerHTML; everything else on this page is textContent.
    originalP.innerHTML = variant.diff_original_html;
    var attackedP = el("p", "lab-diff-line");
    attackedP.innerHTML = variant.diff_attacked_html;
    diffBlock.appendChild(originalP);
    diffBlock.appendChild(attackedP);
    card.appendChild(diffBlock);

    var versions = el("div", "lab-variant-versions");
    renderVersionOutcome(versions, "V1 — Unhardened Endpoint", variant.v1);
    renderVersionOutcome(versions, "V2 — Hardened Endpoint", variant.v2);
    card.appendChild(versions);

    return card;
  }

  function renderResults(data) {
    renderSummary(data.summary);

    cleanCardsEl.textContent = "";
    var inputLine = el("p", "lab-field", "Your input: " + data.original_text);
    cleanCardsEl.appendChild(inputLine);
    var pair = el("div", "version-context");
    pair.appendChild(renderCleanCard("v1", data.v1_clean));
    pair.appendChild(renderCleanCard("v2", data.v2_clean));
    cleanCardsEl.appendChild(pair);

    variantsEl.textContent = "";
    data.variants.forEach(function (variant) {
      variantsEl.appendChild(renderVariant(variant));
    });

    showResults();
  }

  // ---- polling / reattachment -----------------------------------------------------------
  function applyRunningState(state) {
    if (execHeading) execHeading.textContent = state.message || "Running…";
    setProgress(state.percent, state.message || "");
    setStageClasses(state.stage_index);
    window.rlUpdateLanes(state.stage, stageItems, viewExecution);
  }

  function pollLabStatus(jobId) {
    var current = generation;
    fetch("/api/lab/status/" + encodeURIComponent(jobId))
      .then(function (response) {
        if (current !== generation) return null;
        if (response.status === 404) {
          clearJobId();
          showInput();
          return null;
        }
        return response.json();
      })
      .then(function (state) {
        if (!state || current !== generation) return;
        if (state.status === "running") {
          showExecution();
          applyRunningState(state);
          pollTimer = setTimeout(function () { pollLabStatus(jobId); }, POLL_MS);
        } else if (state.status === "complete") {
          renderResults(state.result);
        } else if (state.status === "failed") {
          showFailure(state.error);
        } else {
          clearJobId();
          showInput();
        }
      })
      .catch(function () {
        if (current === generation && readJobId() === jobId) {
          if (execHeading) execHeading.textContent = "Reconnecting to live progress...";
          pollTimer = setTimeout(function () { pollLabStatus(jobId); }, POLL_MS);
        }
      });
  }

  // ---- starting a run ---------------------------------------------------------------------
  function startLabRun(text) {
    if (launching) return;
    launching = true;
    clearValidationError();
    if (submitBtn) submitBtn.disabled = true;

    fetch("/api/lab/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text }),
    })
      .then(function (response) {
        return response.json().then(function (data) { return { status: response.status, data: data }; });
      })
      .then(function (result) {
        launching = false;
        if (submitBtn) submitBtn.disabled = false;
        var data = result.data;
        if (result.status === 409 || data.status === "busy") {
          showExecution();
          showBusy();
          return;
        }
        if (result.status === 422 || data.status === "invalid") {
          showValidationError(data.error || "Please check your input and try again.");
          return;
        }
        storeJobId(data.job_id);
        showExecution();
        applyRunningState(data);
        pollTimer = setTimeout(function () { pollLabStatus(data.job_id); }, POLL_MS);
      })
      .catch(function () {
        launching = false;
        if (submitBtn) submitBtn.disabled = false;
        showExecution();
        showFailure("Could not start the Red-Team Lab test. Please try again.");
      });
  }

  // ---- event wiring -------------------------------------------------------------------
  if (form) {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var text = textarea ? textarea.value : "";
      var trimmed = text.trim();
      if (!trimmed) {
        showValidationError("Enter at least one character.");
        return;
      }
      if (text.length > maxChars) {
        showValidationError("Limit is " + maxChars + " characters.");
        return;
      }
      lastText = text;
      startLabRun(text);
    });
  }

  if (retryBtn) {
    retryBtn.addEventListener("click", function () { startLabRun(lastText); });
  }
  if (busyRetryBtn) {
    busyRetryBtn.addEventListener("click", function () { startLabRun(lastText); });
  }
  if (editBtn) {
    editBtn.addEventListener("click", function () {
      clearJobId();
      showInput();
      if (textarea) {
        textarea.value = lastText;
        textarea.focus();
      }
      updateCounter();
    });
  }

  // "Test Another Input" -- the ONE reset implementation, called from the sticky masthead
  // action (the only place it now appears; the old bottom-of-results duplicate was removed
  // per the V5.4 final-integration brief). Clears the client-side result state, the
  // sessionStorage job token, and returns to the input form -- never touches verified
  // benchmark data or completed Demo state, which this function has no access to at all.
  function resetToInput() {
    generation++;
    clearTimeout(pollTimer);
    clearJobId();
    lastText = "";
    if (textarea) textarea.value = "";
    updateCounter();
    showInput();
    if (textarea) textarea.focus();
  }
  if (navTestAnother) {
    navTestAnother.addEventListener("click", resetToInput);
  }

  window.addEventListener("pagehide", function () { generation++; clearTimeout(pollTimer); });
  window.addEventListener("pageshow", function (event) {
    if (!event.persisted) return;
    generation++;
    clearTimeout(pollTimer);
    var jobId = readJobId();
    if (jobId) pollLabStatus(jobId); else showInput();
  });

  // ---- reattachment on load -------------------------------------------------------------
  var existingJobId = readJobId();
  if (existingJobId) {
    showExecution();
    pollLabStatus(existingJobId);
  } else {
    showInput();
  }
})();
