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
  // Derive endpoint lanes only from the server stage and server-rendered stage order.
  window.rlUpdateLanes = function (stage, items, container) {
    var order = Array.prototype.map.call(items, function (item) { return item.dataset.stage; });
    var current = order.indexOf(stage);
    ["v1", "v2"].forEach(function (version) {
      var card = container.querySelector('[data-lane="' + version + '"]');
      if (!card) return;
      var start = order.indexOf("starting_" + version);
      var last = order.indexOf("attacking_" + version);
      var status = current < start ? "Not started" : current === start ? "Starting" : current <= last ? "Active" : "Complete";
      card.dataset.state = status.toLowerCase().replace(" ", "-");
      card.querySelector(".lane-status").textContent = status;
    });
  };
})();
