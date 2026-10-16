/* 랜딩 히어로 캐러셀: 이전/다음, 점 인디케이터, 6초 자동 넘김.
   마우스를 올리거나 포커스가 안에 있으면 멈추고, prefers-reduced-motion 이면 자동 넘김을 하지 않는다. 키보드 좌우 이동. */
/* 내 여행 계획: 이 기기에 저장된 계획(PlanStore)이 있을 때만 섹션을 보여 준다. 카드는 <template> 을 복제해 textContent 로만 채운다. */
(function () {
  "use strict";
  var section = document.getElementById("my-plans");
  var tpl = document.getElementById("my-plan-card"), chipTpl = document.getElementById("my-plan-chip");
  if (!section || !tpl || !chipTpl) return;
  var ul = section.querySelector("[data-my-plans]");

  function stamp(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return (d.getMonth() + 1) + "/" + d.getDate() + " " + ("0" + d.getHours()).slice(-2) + ":" + ("0" + d.getMinutes()).slice(-2);
  }

  function render() {
    var plans = [];
    try { plans = window.PlanStore ? window.PlanStore.list() : []; } catch (e) {}
    ul.textContent = "";
    plans.slice(0, 8).forEach(function (p) {
      var node = tpl.content.cloneNode(true);
      var a = node.querySelector("[data-plan-link]");
      a.href = "/planner?thread_id=" + encodeURIComponent(p.thread_id);
      node.querySelector("[data-summary]").textContent = p.summary || p.trip.destination_ko || "여행 계획";
      var places = node.querySelector("[data-places]");
      ((p.trip && p.trip.places) || []).slice(0, 4).forEach(function (name) {
        var chip = chipTpl.content.cloneNode(true);
        chip.querySelector("li").textContent = String(name);
        places.appendChild(chip);
      });
      if (!places.children.length) places.hidden = true;
      var t = node.querySelector("[data-saved]");
      t.textContent = stamp(p.updated_at || p.saved_at);
      if (p.updated_at || p.saved_at) t.setAttribute("datetime", p.updated_at || p.saved_at);
      node.querySelector("[data-thread-id]").setAttribute("data-thread-id", p.thread_id);
      ul.appendChild(node);
    });
    section.hidden = ul.children.length === 0;
  }

  render();
  document.addEventListener("plans-changed", render);
  window.addEventListener("pageshow", function (e) { if (e.persisted) render(); });
})();

(function () {
  "use strict";
  var hero = document.getElementById("hero");
  if (!hero) return;
  var slides = Array.prototype.slice.call(hero.querySelectorAll("[data-slide]"));
  var dots = Array.prototype.slice.call(hero.querySelectorAll("[data-dot]"));
  var track = hero.querySelector("[data-track]");
  var toggle = hero.querySelector("[data-carousel-toggle]");
  var counter = hero.querySelector("[data-counter]");
  if (slides.length < 2) return;

  var INTERVAL = 6000;
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var index = 0, timer = null, userPaused = reduce, hovering = false, focusing = false;

  function show(i, byUser) {
    index = (i + slides.length) % slides.length;
    slides.forEach(function (s, n) { s.setAttribute("data-active", n === index ? "true" : "false"); });
    dots.forEach(function (d, n) {
      if (n === index) d.setAttribute("aria-current", "true"); else d.removeAttribute("aria-current");
    });
    if (counter) counter.textContent = (index + 1) + " / " + slides.length;
    if (byUser && track) track.setAttribute("aria-live", "polite");
  }

  function running() { return !userPaused && !hovering && !focusing; }

  function schedule() {
    if (timer) { clearTimeout(timer); timer = null; }
    if (track) track.setAttribute("aria-live", running() ? "off" : "polite");
    if (!running()) return;
    timer = setTimeout(function () { show(index + 1); schedule(); }, INTERVAL);
  }

  function setToggle() {
    if (!toggle) return;
    toggle.setAttribute("aria-label", userPaused ? "자동 넘김 시작" : "자동 넘김 멈춤");
    toggle.setAttribute("data-paused", userPaused ? "true" : "false");
  }

  function go(i) { show(i, true); schedule(); }

  hero.addEventListener("click", function (e) {
    var b = e.target.closest("[data-prev],[data-next],[data-dot],[data-carousel-toggle]");
    if (!b) return;
    if (b.hasAttribute("data-prev")) go(index - 1);
    else if (b.hasAttribute("data-next")) go(index + 1);
    else if (b.hasAttribute("data-dot")) go(parseInt(b.getAttribute("data-dot"), 10));
    else { userPaused = !userPaused; setToggle(); schedule(); }
  });

  hero.addEventListener("keydown", function (e) {
    if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return;
    var t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
    if (e.key === "ArrowLeft") { e.preventDefault(); go(index - 1); }
    else if (e.key === "ArrowRight") { e.preventDefault(); go(index + 1); }
  });

  hero.addEventListener("mouseenter", function () { hovering = true; schedule(); });
  hero.addEventListener("mouseleave", function () { hovering = false; schedule(); });
  hero.addEventListener("focusin", function () { focusing = true; schedule(); });
  hero.addEventListener("focusout", function (e) {
    if (!hero.contains(e.relatedTarget)) { focusing = false; schedule(); }
  });
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) { if (timer) { clearTimeout(timer); timer = null; } } else schedule();
  });

  setToggle();
  show(0);
  schedule();
})();
