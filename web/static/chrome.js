(function () {
  "use strict";
  var toggle = document.getElementById("nav-toggle");
  var nav = document.getElementById("primary-nav");
  function closeMenu() { nav.classList.remove("open"); toggle.setAttribute("aria-expanded", "false"); }
  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      toggle.setAttribute("aria-expanded", nav.classList.toggle("open") ? "true" : "false");
    });
    nav.querySelectorAll("a, button").forEach(function (link) { link.addEventListener("click", closeMenu); });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && nav.classList.contains("open")) { closeMenu(); toggle.focus(); }
    });
  }
  document.querySelectorAll(".rl-back-btn").forEach(function (back) {
    back.addEventListener("click", function (event) {
      var sameOrigin = false;
      try { sameOrigin = new URL(document.referrer).origin === window.location.origin; } catch (_) {}
      if (window.history.length > 1 && (sameOrigin || (window.history.state && window.history.state.redLab))) {
        event.preventDefault(); window.history.back();
      }
    });
  });
  // v6.1 Phase 2/3: lanes are derived from the descriptor's own cards (each carrying its real
  // start_stage/end_stage), never a hardcoded ["v1", "v2"] -- a single-target descriptor has
  // exactly one card and must not be forced through a two-lane assumption.
  window.rlUpdateLanes = function (stage, realStageOrder, container) {
    var current = realStageOrder.indexOf(stage);
    container.querySelectorAll("[data-lane]").forEach(function (card) {
      var start = realStageOrder.indexOf(card.dataset.startStage);
      var last = realStageOrder.indexOf(card.dataset.endStage);
      var status = current < start ? "Not started" : current === start ? "Starting" : current <= last ? "Active" : "Complete";
      card.dataset.state = status.toLowerCase().replace(" ", "-");
      var statusEl = card.querySelector(".lane-status");
      if (statusEl) statusEl.textContent = status;
    });
  };

  // v6.1 Phase 2/3: build the endpoint cards, "same model" note, stage checklist and footer
  // note from one evaluation descriptor -- the correct semantic DOM for paired vs single-target
  // evaluations is generated here, never approximated by hiding pre-rendered markup with CSS.
  window.rlRenderProgress = function (descriptor, refs) {
    if (refs.cardsEl) {
      refs.cardsEl.textContent = "";
      descriptor.cards.forEach(function (card) {
        var div = document.createElement("div");
        div.className = "version-card " + card.lane;
        div.dataset.lane = card.lane;
        div.dataset.state = "not-started";
        div.dataset.startStage = card.start_stage;
        div.dataset.endStage = card.end_stage;
        var status = document.createElement("span");
        status.className = "lane-status";
        status.textContent = "Not started";
        var title = document.createElement("p");
        title.className = "version-card-title";
        title.textContent = card.title;
        var note = document.createElement("p");
        note.className = "version-card-note";
        note.textContent = card.note;
        div.appendChild(status);
        div.appendChild(title);
        div.appendChild(note);
        refs.cardsEl.appendChild(div);
      });
    }
    if (refs.sameModelLabelEl) {
      if (descriptor.same_model_note) {
        refs.sameModelLabelEl.hidden = false;
        if (refs.sameModelNoteEl) refs.sameModelNoteEl.textContent = descriptor.same_model_note;
      } else {
        refs.sameModelLabelEl.hidden = true;
      }
    }
    if (refs.stageListEl) {
      refs.stageListEl.textContent = "";
      descriptor.stages.forEach(function (stage) {
        var li = document.createElement("li");
        li.dataset.stage = stage.maps_to;
        li.textContent = stage.label;
        refs.stageListEl.appendChild(li);
      });
    }
    if (refs.footerNoteEl) refs.footerNoteEl.textContent = descriptor.footer_note;
    // v7: the target/configuration summary is rendered from the descriptor's own recorded
    // evaluation id, kind and target ids -- never from a hardcoded V1/V2 assumption, so a
    // single-target evaluation shows exactly one target and no implied second endpoint.
    if (refs.configEl) {
      refs.configEl.textContent = "";
      var rows = [
        ["Evaluation", descriptor.evaluation_id],
        ["Design", descriptor.kind === "paired" ? "Paired · two endpoints" : "Single configured target"],
        ["Targets", (descriptor.target_ids || []).join(", ") ||
          descriptor.cards.map(function (c) { return c.lane; }).join(", ")]
      ];
      rows.forEach(function (row) {
        if (!row[1]) return;
        var li = document.createElement("li");
        var label = document.createElement("b");
        label.textContent = row[0];
        li.appendChild(label);
        li.appendChild(document.createTextNode(row[1]));
        refs.configEl.appendChild(li);
      });
    }
  };

  // v7: the orange selector tag restates the selected evaluation's real shape in words.
  // Emotion is the paired V1/V2 evaluation; sentiment is one configured target with no V2.
  window.rlSelectorTag = function (tagEl, evaluationId) {
    if (!tagEl) return;
    tagEl.textContent = evaluationId === "sentiment.core"
      ? "Sentiment · single target"
      : "Emotion · paired V1 + V2";
  };
})();
