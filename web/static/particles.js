"use strict";
// Independent, time-based drift; reduced motion retains a static field. No input tracking.
(function () {
  var canvas = document.getElementById("rl-bg-canvas");
  if (!canvas || !canvas.getContext) return;
  var ctx = canvas.getContext("2d");
  var media = window.matchMedia("(prefers-reduced-motion: reduce)");
  var width = 0, height = 0, points = [], rafId = null, last = 0;
  var colors = ["198,37,61", "41,42,47", "229,98,46", "240,163,58"];
  function resize() {
    var rect = canvas.parentElement.getBoundingClientRect();
    width = document.documentElement.clientWidth; height = Math.round(rect.height);
    canvas.parentElement.style.setProperty("--rl-field-width", width + "px");
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = width * dpr; canvas.height = height * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    var count = width < 760 ? 16 : width < 1100 ? 44 : 68;
    points = [];
    for (var i = 0; i < count; i++) {
      // Keep most structure toward the edges, preserving the central reading field.
      var x = Math.random() * width;
      if (i % 4 !== 0) x = i % 2 ? Math.random() * width * .23 : width * (.77 + Math.random() * .23);
      var depth = .6 + Math.random() * .8;
      // Average velocity is 1.8x the previous field, with distinct near/far layers.
      var tone = i % 23 === 0 ? 3 : i % 6 === 0 ? 2 : i % 2;
      points.push({ x: x, y: Math.random() * height, vx: (Math.random() - .5) * 10.8 * depth,
        vy: (Math.random() - .5) * 10.8 * depth, r: 1.4 + depth * 1.35,
        alpha: .28 + depth * .24, color: colors[tone], connected: i % 4 !== 0 });
    }
    restart();
  }
  function draw(dt) {
    ctx.clearRect(0, 0, width, height);
    points.forEach(function (p, i) {
      p.x += p.vx * dt; p.y += p.vy * dt;
      if (p.x < 0 || p.x > width) p.vx *= -1;
      if (p.y < 0 || p.y > height) p.vy *= -1;
      // A soft reading zone protects the central heading/body without a visible cutout.
      var edge = Math.min(1, Math.abs(p.x - width / 2) / (width * .34));
      var opacity = p.alpha * (.4 + .6 * edge);
      ctx.beginPath(); ctx.fillStyle = "rgba(" + p.color + "," + opacity + ")";
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2); ctx.fill();
      var links = 0;
      for (var j = i + 1; p.connected && j < points.length && links < 2; j++) {
        var q = points[j], dist = Math.hypot(p.x - q.x, p.y - q.y);
        if (q.connected && dist < 120) {
          links++;
          ctx.strokeStyle = "rgba(181,78,62," + (.22 * edge * (1 - dist / 120)) + ")";
          ctx.lineWidth = .8; ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y); ctx.stroke();
        }
      }
    });
  }
  function step(now) {
    draw(last ? Math.min((now - last) / 1000, .05) : 0); last = now;
    rafId = window.requestAnimationFrame(step);
  }
  function restart() {
    if (rafId) window.cancelAnimationFrame(rafId);
    rafId = null; last = 0;
    draw(0);
    if (!media.matches && !document.hidden && !canvas.parentElement.hidden && width && height)
      rafId = window.requestAnimationFrame(step);
  }
  new ResizeObserver(resize).observe(canvas.parentElement);
  window.addEventListener("resize", resize);
  new MutationObserver(restart).observe(canvas.parentElement, { attributes: true, attributeFilter: ["hidden"] });
  media.addEventListener("change", restart);
  document.addEventListener("visibilitychange", restart);
})();
