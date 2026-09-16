"use strict";
// Red Lab v7 landing field: about 17 small glowing dots drifting and pulsing behind the
// hero, each with its own staggered phase and period. The two large blurred conic swirls
// are pure CSS (app.css, #view-home::before/::after); this file only draws the dots.
// Independent, time-based drift; no input tracking. Reduced motion keeps a static field:
// the one-shot draw(0) still paints the dots, the animation loop simply never starts.
(function () {
  var canvas = document.getElementById("rl-bg-canvas");
  if (!canvas || !canvas.getContext) return;
  var ctx = canvas.getContext("2d");
  var media = window.matchMedia("(prefers-reduced-motion: reduce)");
  var DOT_COUNT = 17;
  var width = 0, height = 0, dots = [], rafId = null, last = 0, elapsed = 0;
  // Warm red / orange / amber, matching the CSS swirl hues.
  var colors = ["255, 122, 122", "255, 150, 92", "255, 186, 110"];
  function resize() {
    var rect = canvas.parentElement.getBoundingClientRect();
    width = document.documentElement.clientWidth; height = Math.round(rect.height);
    canvas.parentElement.style.setProperty("--rl-field-width", width + "px");
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = width * dpr; canvas.height = height * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    dots = [];
    for (var i = 0; i < DOT_COUNT; i++) {
      // Weighted toward the margins so the central reading column stays clear, and each dot
      // gets its own phase and period -- the pulses are staggered, never in lockstep.
      var side = i % 2 ? 1 : -1;
      var x = width / 2 + side * width * (.2 + (i % 5) * .06 + Math.random() * .12);
      dots.push({
        x: Math.max(6, Math.min(width - 6, x)),
        y: Math.random() * height,
        vx: (Math.random() - .5) * 9, vy: (Math.random() - .5) * 9,
        r: 1.5 + (i % 4) * .7, base: .22 + (i % 3) * .1,
        phase: (i / DOT_COUNT) * Math.PI * 2, period: 3.2 + (i % 5) * .9,
        color: colors[i % colors.length]
      });
    }
    restart();
  }
  function draw(dt) {
    elapsed += dt;
    ctx.clearRect(0, 0, width, height);
    dots.forEach(function (p) {
      p.x += p.vx * dt; p.y += p.vy * dt;
      if (p.x < 0 || p.x > width) p.vx *= -1;
      if (p.y < 0 || p.y > height) p.vy *= -1;
      // A soft reading zone protects the central heading/body without a visible cutout.
      var edge = Math.min(1, Math.abs(p.x - width / 2) / (width * .32));
      var pulse = .65 + .35 * Math.sin(p.phase + (elapsed / p.period) * Math.PI * 2);
      var opacity = p.base * pulse * (.35 + .65 * edge);
      var glow = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.r * 6);
      glow.addColorStop(0, "rgba(" + p.color + "," + opacity + ")");
      glow.addColorStop(1, "rgba(" + p.color + ", 0)");
      ctx.fillStyle = glow;
      ctx.beginPath(); ctx.arc(p.x, p.y, p.r * 6, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "rgba(" + p.color + "," + Math.min(1, opacity * 2.4) + ")";
      ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2); ctx.fill();
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
