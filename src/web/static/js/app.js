/* 앱 셸 동작: 테마, 내 여행 기록 패널, 작업실 교체, 플로팅 챗봇 위젯, Ctrl+K, 입력창. 색은 다루지 않는다(토큰만 사용). */
(function () {
  "use strict";
  var root = document.documentElement;
  // 작업실 교체는 htmx 가 주소를 바꾼다(hx-push-url). 뒤로가기는 아래 popstate 에서 직접 다시 불러오므로 htmx 의 화면 스냅샷은 쓰지 않는다
  if (window.htmx) htmx.config.historyCacheSize = 0;

  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) {} return null; }
  function $(s, c) { return (c || document).querySelector(s); }

  function currentTheme() {
    var t = root.getAttribute("data-theme");
    if (t) return t;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function menu(open) {
    var sb = $("#sidebar"), bd = $("#sidebar-backdrop");
    if (!sb) return;
    sb.setAttribute("data-open", open ? "true" : "false");
    if (bd) bd.classList.toggle("hidden", !open);
    document.querySelectorAll('[data-action="open-menu"]').forEach(function (b) { b.setAttribute("aria-expanded", open ? "true" : "false"); });
    if (open) { var c = sb.querySelector('button[data-action="close-menu"]'); if (c && c.offsetParent !== null) c.focus(); }
    else closeHistoryMenus();
  }

  /* ---------- 공통 GNB: 전체메뉴 패널(1024px 미만), 여행지 드롭다운 ---------- */
  var gnbOpener = null;

  function gnbPanel(open) {
    var p = $("#gnb-panel");
    if (!p) return;
    p.setAttribute("data-open", open ? "true" : "false");
    document.querySelectorAll('[data-action="open-gnb"]').forEach(function (b) { b.setAttribute("aria-expanded", open ? "true" : "false"); });
    if (open) {
      gnbOpener = document.activeElement;
      var c = p.querySelector('button[data-action="close-gnb"]');
      if (c) c.focus();
    } else if (gnbOpener && gnbOpener.focus && document.activeElement && p.contains(document.activeElement)) {
      gnbOpener.focus();
    }
  }

  function destMenu(open) {
    var m = $("#gnb-dest-menu"), b = $('[data-action="toggle-dest-menu"]');
    if (!m || !b) return;
    m.hidden = !open;
    b.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function destMenuOpen() { var m = $("#gnb-dest-menu"); return !!m && !m.hidden; }

  // 바깥을 누르면 여행지 드롭다운을 닫는다
  document.addEventListener("click", function (e) {
    if (destMenuOpen() && !e.target.closest("[data-dest-menu]")) destMenu(false);
  });

  // 검색 결과: 지원 여행지면 그 도시가 선택된 계획 모달을 열고, 미지원이면 안내가 그대로 남는다
  document.addEventListener("htmx:afterSwap", function (e) {
    var box = e.target;
    if (!box || !box.hasAttribute || !box.hasAttribute("data-search-result")) return;
    var hit = box.querySelector("[data-search-open]");
    if (!hit) return;
    var dest = hit.getAttribute("data-plan-dest");
    box.innerHTML = "";
    var form = box.closest("form"), q = form && form.querySelector("input[name=q]");
    if (q) q.value = "";
    openPlan({ destination: dest });
  });

  // 검색 입력을 고치면 이전 안내를 지운다
  document.addEventListener("input", function (e) {
    var t = e.target;
    if (t && t.name === "q" && t.form && t.form.hasAttribute("data-gnb-search")) {
      var box = t.form.querySelector("[data-search-result]");
      if (box) box.innerHTML = "";
    }
  });

  /* ---------- 내 여행 계획 로컬 저장 (PlanStore) ----------
     localStorage `smart-travel:plans` = 최신순 배열(최대 20). 같은 thread_id 는 덮어쓴다.
     저장소가 없거나(비공개 창), 용량 초과이거나, JSON 이 깨져도 예외를 밖으로 내지 않고 화면은 그대로 동작한다. */
  var PlanStore = (function () {
    var KEY = "smart-travel:plans", MAX = 20;

    function valid(p) {
      return p && typeof p === "object" && typeof p.thread_id === "string" && p.thread_id &&
        p.trip && typeof p.trip === "object" && typeof p.trip.destination === "string";
    }

    function read() {
      try {
        var raw = localStorage.getItem(KEY);
        if (!raw) return [];
        var arr = JSON.parse(raw);
        if (!Array.isArray(arr)) throw new Error("not array");
        return arr.filter(valid);
      } catch (e) {
        try { localStorage.removeItem(KEY); } catch (e2) {}   // 깨진 값은 버리고 초기화
        return [];
      }
    }

    function write(arr) {
      try { localStorage.setItem(KEY, JSON.stringify(arr)); return true; } catch (e) { return false; }
    }

    function list() { return read(); }
    function get(tid) { return read().filter(function (p) { return p.thread_id === tid; })[0] || null; }

    function save(plan) {
      if (!valid(plan)) return false;
      var arr = read(), prev = null;
      arr = arr.filter(function (p) { if (p.thread_id === plan.thread_id) prev = p; return p.thread_id !== plan.thread_id; });
      if (prev && prev.saved_at) plan.saved_at = prev.saved_at;   // 처음 저장한 시각은 유지, updated_at 만 갱신
      arr.unshift(plan);
      arr.sort(function (a, b) { return String(b.updated_at || "").localeCompare(String(a.updated_at || "")); });
      arr = arr.slice(0, MAX);
      while (!write(arr) && arr.length > 1) arr = arr.slice(0, Math.ceil(arr.length / 2));   // 용량 초과: 오래된 것부터 덜어낸다
      return true;
    }

    function remove(tid) { return write(read().filter(function (p) { return p.thread_id !== tid; })); }

    return { KEY: KEY, MAX: MAX, list: list, get: get, save: save, remove: remove };
  })();
  window.PlanStore = PlanStore;

  // 서버가 가진 계획(GET /plan/{id}.json)을 받아 저장한다. DOM 을 긁지 않는다.
  function savePlan(tid) {
    if (!tid || !window.fetch) return;
    fetch("/plan/" + encodeURIComponent(tid) + ".json", { headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (p) { if (p) PlanStore.save(p); })
      .catch(function () {});
  }

  function session() { return $("#chat-session"); }

  function currentThread() {
    var s = session();
    return s ? s.getAttribute("data-thread") : "";
  }

  function debugQuery(sep) { return /[?&]debug=1/.test(location.search) ? sep + "debug=1" : ""; }

  // 이 기기에 저장된 사본을 읽기 전용 작업실로 연다 (POST /plan/offline?workspace=1). 보드, 제목, 대화 스레드, thread 정보가 함께 바뀐다.
  function openLocal(plan, push) {
    if (!window.fetch || !window.htmx) return;
    var url = "/planner?thread_id=" + encodeURIComponent(plan.thread_id) + debugQuery("&");
    fetch("/plan/offline?workspace=1&thread_id=" + encodeURIComponent(plan.thread_id) + debugQuery("&"),
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(plan) })
      .then(function (r) { return r.ok ? r.text() : null; })
      .then(function (html) {
        var target = $("#board-root");
        if (!html || !target) return;
        if (push && history.pushState) history.pushState(null, "", url);
        htmx.swap(target, html, { swapStyle: "innerHTML" });
      })
      .catch(function () {});
  }

  // 서버에 대화가 없는데 이 기기에 저장본이 있으면, 저장본으로 읽기 전용 보드를 다시 그린다
  function restoreOffline() {
    var s = session();
    if (!s || !window.fetch) return;
    if (s.getAttribute("data-empty") !== "true" || s.getAttribute("data-autostart") === "true") return;
    var plan = PlanStore.get(s.getAttribute("data-thread"));
    if (plan) openLocal(plan, false);
  }

  /* ---------- 내 여행 기록 패널 ---------- */
  function ago(iso) {
    var t = new Date(iso).getTime();
    if (isNaN(t)) return "";
    var sec = Math.max(0, Math.floor((Date.now() - t) / 1000));
    if (sec < 60) return "방금";
    if (sec < 3600) return Math.floor(sec / 60) + "분 전";
    if (sec < 86400) return Math.floor(sec / 3600) + "시간 전";
    var d = Math.floor(sec / 86400);
    return d === 1 ? "어제" : d + "일 전";
  }

  // 지금 보는 항목에 aria-current 를 단다
  function markCurrent() {
    var cur = currentThread();
    document.querySelectorAll("#history-list li[data-thread-id]").forEach(function (li) {
      var a = li.querySelector("[data-history-link]");
      if (!a) return;
      if (li.getAttribute("data-thread-id") === cur) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
  }

  // 서버에는 없고 이 기기(PlanStore)에만 있는 계획을 같은 목록에 끼워 넣는다. thread_id 로 중복을 제거한다
  function renderLocal() {
    var list = $("#history-list"), tpl = $("#history-local-tpl"), chipTpl = $("#history-chip-tpl");
    if (!list || !tpl || !chipTpl) return;
    list.querySelectorAll("li[data-local]").forEach(function (li) { li.remove(); });
    var serverIds = (list.getAttribute("data-server-ids") || "").split(" ");
    var plans = [];
    try { plans = PlanStore.list(); } catch (e) {}
    plans = plans.filter(function (p) { return serverIds.indexOf(p.thread_id) < 0; });
    plans.sort(function (a, b) { return String(b.saved_at || b.updated_at || "").localeCompare(String(a.saved_at || a.updated_at || "")); });
    plans.forEach(function (p) {
      var li = tpl.content.cloneNode(true).querySelector("li");
      var ts = p.saved_at || p.updated_at || "";
      var label = p.summary || (p.trip && p.trip.destination_ko) || "여행 계획";
      li.setAttribute("data-thread-id", p.thread_id);
      li.setAttribute("data-ts", ts);
      var a = li.querySelector("[data-local-open]");
      a.href = "/planner?thread_id=" + encodeURIComponent(p.thread_id) + debugQuery("&");
      li.querySelector("[data-summary]").textContent = label;
      var places = li.querySelector("[data-places]");
      ((p.trip && p.trip.places) || []).slice(0, 3).forEach(function (name) {
        var chip = chipTpl.content.cloneNode(true).querySelector("span");
        chip.textContent = String(name);
        places.appendChild(chip);
      });
      if (!places.children.length) places.hidden = true;
      var tm = li.querySelector("[data-time]");
      tm.textContent = ago(ts);
      if (ts) tm.setAttribute("datetime", ts);
      li.querySelector("[data-action=history-menu]").setAttribute("aria-label", label + " 기록 메뉴");
      var del = li.querySelector("[data-action=history-delete]");
      del.setAttribute("data-thread-id", p.thread_id);
      del.setAttribute("data-label", label);
      var anchor = null;
      list.querySelectorAll('li[data-kind="trip"]').forEach(function (x) {
        if (!anchor && String(x.getAttribute("data-ts") || "") < ts) anchor = x;
      });
      if (!anchor) anchor = list.querySelector('li[data-group="chat"], #history-more');
      list.insertBefore(li, anchor);
    });
    var empty = $("#history-empty");
    if (empty) empty.hidden = plans.length > 0;
    markCurrent();
  }

  function refreshHistory() {
    if (!window.htmx || !$("#history")) return;
    var q = "?thread_id=" + encodeURIComponent(currentThread()) + debugQuery("&");
    htmx.ajax("GET", "/threads" + q, { target: "#history", swap: "outerHTML" });
  }

  function closeHistoryMenus(except) {
    document.querySelectorAll('[data-action="history-menu"][aria-expanded="true"]').forEach(function (b) {
      if (b === except) return;
      b.setAttribute("aria-expanded", "false");
      var m = b.parentNode.querySelector("[role=menu]");
      if (m) m.hidden = true;
    });
  }

  function toggleHistoryMenu(btn) {
    var m = btn.parentNode.querySelector("[role=menu]");
    if (!m) return;
    var open = m.hidden;
    closeHistoryMenus(btn);
    m.hidden = !open;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) { var first = m.querySelector("[role=menuitem]"); if (first) first.focus(); }
  }

  // 작업실 영역을 thread 로 교체한다. 주소는 이미 바뀐 상태(뒤로가기)에서 호출한다
  function loadWorkspace(tid) {
    if (!window.htmx || !$("#board-root")) return;
    var q = (tid ? "?thread_id=" + encodeURIComponent(tid) : "") + debugQuery(tid ? "&" : "?");
    htmx.ajax("GET", "/planner" + q, { target: "#board-root", swap: "innerHTML" });
  }

  // 작업실이 새 thread 로 교체된 뒤: 챗봇 상태, 기록 패널 표시, 스크롤을 맞춘다
  function syncSession() {
    var s = session();
    if (!s) return;
    var auto = s.getAttribute("data-autostart") === "true";
    setBusy(auto);   // 이전 thread 의 스트림은 요소가 지워지며 닫힌다. 새 계획이면 새 스트림이 이미 시작됐다
    if (auto) setOpen(true, { focus: false, save: false });
    stick = true; scrollThread(true);
    var main = $("#main"); if (main) main.scrollTop = 0;
    menu(false);
    markCurrent();
    var dot = $("#chat-dot"); if (dot) dot.classList.add("hidden");
    if (s.getAttribute("data-offline") !== "true") restoreOffline();
  }

  window.addEventListener("popstate", function () {
    if (location.pathname !== "/planner" || !$("#board-root")) return;
    var tid = new URLSearchParams(location.search).get("thread_id") || "";
    if (tid && tid === currentThread()) return;
    loadWorkspace(tid);
  });
  document.addEventListener("htmx:historyCacheMiss", function (e) { e.preventDefault(); });   // 위 popstate 가 직접 불러온다

  document.addEventListener("htmx:afterSettle", function (e) {
    var t = e.detail && e.detail.elt ? e.detail.elt : e.target;
    if (t && t.id === "board-root") syncSession();
    else if (t && t.id === "history") renderLocal();
  });
  document.addEventListener("htmx:afterSwap", function (e) {
    var t = e.target;
    if (t && t.id === "history-more") renderLocal();
  });
  document.addEventListener("plans-changed", renderLocal);

  /* 삭제 확인 (<dialog>): scope "local" 은 이 기기의 사본만, "history" 는 서버 기록과 사본을 함께 지운다 */
  var pendingDelete = null;

  function askDelete(tid, opener, scope, label) {
    var dlg = $("#delete-modal");
    if (!dlg || !tid || !dlg.showModal) return;
    var plan = PlanStore.get(tid), name = $("#delete-modal-name");
    var text = label || (plan && plan.summary) || "";
    if (name) name.textContent = text ? "(" + text + ")" : "";
    var title = $("#delete-modal-title"), desc = $("#delete-modal-note");
    if (title) title.textContent = scope === "history" ? "이 기록을 삭제할까요?" : "이 기기에서 계획을 삭제할까요?";
    if (desc) desc.textContent = scope === "history"
      ? "서버에 저장된 대화와 이 기기의 사본이 함께 지워지고 되돌릴 수 없어요."
      : "이 브라우저에 저장된 사본만 지워져요.";
    pendingDelete = { tid: tid, opener: opener, scope: scope || "local" };
    dlg.showModal();
  }

  function finishDelete(ok) {
    var dlg = $("#delete-modal");
    if (dlg && dlg.open) dlg.close();
    var p = pendingDelete;
    pendingDelete = null;
    if (!ok || !p) return;
    if (p.scope === "history") {
      var done = function () {
        PlanStore.remove(p.tid);
        var wasCurrent = p.tid === currentThread();
        var li = document.querySelector('#history-list li[data-thread-id="' + p.tid + '"]');
        if (li) li.remove();
        document.dispatchEvent(new CustomEvent("plans-changed"));
        if (wasCurrent) loadWorkspace("");   // 지운 기록을 보고 있었다면 가장 최근 기록(없으면 빈 화면)으로
        else refreshHistory();
      };
      if (window.fetch) fetch("/threads/" + encodeURIComponent(p.tid), { method: "DELETE" }).then(done, done); else done();
      return;
    }
    PlanStore.remove(p.tid);
    document.dispatchEvent(new CustomEvent("plans-changed"));
    if (p.opener && p.opener.closest("#board-trip, #offline-board")) { p.opener.textContent = "삭제했어요"; p.opener.disabled = true; }
  }

  /* ---------- 챗봇 위젯 ---------- */
  var widget = $("#chat-widget"), fab = $("#chat-fab"), thread = $("#thread");
  var busy = false, stick = true;

  function isOpen() { return !!widget && widget.getAttribute("data-open") === "true"; }

  function setOpen(open, opts) {
    if (!widget || !fab) return;
    opts = opts || {};
    widget.setAttribute("data-open", open ? "true" : "false");
    fab.setAttribute("aria-expanded", open ? "true" : "false");
    fab.setAttribute("aria-label", open ? "AI 여행 비서 닫기" : "AI 여행 비서 열기");
    if (opts.save !== false) store("chat-open", open ? "1" : "0");
    if (open) {
      var dot = $("#chat-dot");
      if (dot) dot.classList.add("hidden");
      stick = true;
      scrollThread(true);
      if (opts.focus !== false) { var ta = chatInput(); if (ta) ta.focus(); }
    } else if (opts.focusFab) fab.focus();
  }

  function chatInput() { return widget ? $("textarea", widget) : null; }

  function openChat() { if (!isOpen()) setOpen(true); else { var ta = chatInput(); if (ta) ta.focus(); } }

  function setBusy(b) {
    busy = b;
    var st = $("#chat-status");
    if (st) st.textContent = b ? "답변 작성 중…" : "대기 중";
    var btn = $("#chat-form button[type=submit]");
    if (btn) btn.disabled = b;
  }

  function nowStamp() {
    return new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false });
  }

  function scrollThread(force) {
    if (!thread) return;
    if (force || stick) thread.scrollTop = thread.scrollHeight;
  }

  if (thread) thread.addEventListener("scroll", function () {
    stick = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 80;
  });

  function fillInput(text) {
    var ta = chatInput();
    if (ta) { ta.value = text; }
    setOpen(true);
  }

  // 여행지 선택 카드: 챗봇을 열고 질문을 바로 전송한다 (답변 작성 중이면 무시)
  function askNow(text) {
    var ta = chatInput();
    setOpen(true, { focus: false });
    if (!ta || !ta.form || busy) return;
    ta.value = text;
    ta.form.requestSubmit();
  }

  // 마지막 사용자 질문을 다시 보낸다 (오류 카드/메시지의 "다시 시도")
  function retryLast() {
    var msgs = document.querySelectorAll("#thread [data-user-msg]");
    var ta = chatInput();
    setOpen(true);
    if (!msgs.length || !ta || !ta.form || busy) return;
    ta.value = msgs[msgs.length - 1].textContent.trim();
    ta.form.requestSubmit();
  }

  /* ---------- 새 여행 계획 모달 ---------- */
  var planModal = $("#plan-modal");
  var WD = "일월화수목금토";

  function parseISO(s) { var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || ""); return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null; }
  function fmtMDW(d) { return (d.getMonth() + 1) + "/" + d.getDate() + "(" + WD.charAt(d.getDay()) + ")"; }
  function planDays() { var h = $("#plan-days-value"); return h ? parseInt(h.value, 10) || 3 : 3; }

  function updateDuration() {
    var out = $("#plan-duration"), start = $("#plan-start");
    if (!out || !start) return;
    var s = parseISO(start.value), n = planDays();
    if (!s) { out.textContent = "출발일을 골라 주세요."; return; }
    var e = new Date(s.getFullYear(), s.getMonth(), s.getDate() + n - 1);
    out.textContent = fmtMDW(s) + " ~ " + fmtMDW(e) + " · " + (n - 1) + "박 " + n + "일";
  }

  function setDays(n, focus) {
    var group = $("#plan-days"), h = $("#plan-days-value");
    if (!group || !h) return;
    h.value = String(n);
    group.querySelectorAll("[role=radio]").forEach(function (b) {
      var on = parseInt(b.getAttribute("data-days"), 10) === n;
      b.setAttribute("aria-checked", on ? "true" : "false");
      b.tabIndex = on ? 0 : -1;
      if (on && focus) b.focus();
    });
    updateDuration();
  }

  function updateCount() {
    var out = $("#plan-count");
    if (!out || !planModal) return;
    var max = parseInt(planModal.getAttribute("data-max-places"), 10) || 10;
    var n = planModal.querySelectorAll("input[name=places]:checked").length;
    var txt = $("#plan-places-text");
    var extra = txt && txt.value ? txt.value.split(/[,，、]/).filter(function (x) { return x.trim(); }).length : 0;
    out.textContent = "(" + (n + extra) + "/" + max + "곳)";
  }

  function openPlan(prefill) {
    if (!planModal || !planModal.showModal) return;
    var form = $("#plan-form"), start = $("#plan-start"), err = $("#plan-errors"), chips = $("#places-chips");
    var today = planModal.getAttribute("data-today");
    if (form) form.reset();
    if (err) err.innerHTML = "";
    if (start) { start.min = today; start.value = today; }
    setDays(3);
    if (chips) chips.innerHTML = '<p class="text-sm leading-6 text-text-muted">여행지를 고르면 가이드의 주요 명소가 여기에 나타나요.</p>';
    if (prefill) {
      if (start && prefill.start >= today) start.value = prefill.start;
      setDays(parseInt(prefill.days, 10) || 3);
      var radio = planModal.querySelector('input[name=destination][value="' + prefill.destination + '"]');
      if (radio) {
        radio.checked = true;
        var q = "/places?city=" + encodeURIComponent(prefill.destination);
        (prefill.places || "").split("|").filter(Boolean).forEach(function (p) { q += "&selected=" + encodeURIComponent(p); });
        if (window.htmx) htmx.ajax("GET", q, { target: "#places-chips", swap: "innerHTML" });
      }
    }
    updateDuration(); updateCount();
    menu(false); gnbPanel(false); destMenu(false);
    if (!planModal.open) planModal.showModal();
    var first = planModal.querySelector("input[name=destination]:checked") || planModal.querySelector("input[name=destination]");
    if (first) first.focus();
  }

  function closePlan() { if (planModal && planModal.open) planModal.close(); }

  if (planModal) {
    planModal.addEventListener("click", function (e) { if (e.target === planModal) closePlan(); });   // 배경 클릭
    planModal.addEventListener("input", function (e) {
      if (e.target.id === "plan-start") updateDuration();
      updateCount();
    });
    planModal.addEventListener("change", updateCount);
    planModal.addEventListener("htmx:afterSwap", updateCount);
    planModal.addEventListener("click", function (e) {
      var b = e.target.closest("#plan-days [role=radio]");
      if (b) setDays(parseInt(b.getAttribute("data-days"), 10));
    });
    planModal.addEventListener("keydown", function (e) {
      var b = e.target.closest && e.target.closest("#plan-days [role=radio]");
      if (b && (e.key === "ArrowRight" || e.key === "ArrowDown" || e.key === "ArrowLeft" || e.key === "ArrowUp")) {
        e.preventDefault();
        var max = parseInt(planModal.getAttribute("data-max-days"), 10) || 5, n = planDays();
        n = (e.key === "ArrowRight" || e.key === "ArrowDown") ? Math.min(max, n + 1) : Math.max(1, n - 1);
        setDays(n, true);
        return;
      }
      if (e.key === "Tab") {   // 포커스 트랩: 모달 안에서만 순환
        var items = Array.prototype.filter.call(
          planModal.querySelectorAll("button, input:not([type=hidden]), a[href]"),
          function (el) { return !el.disabled && el.tabIndex >= 0; });
        if (!items.length) return;
        var first = items[0], last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    });
  }

  // 작업실에서 "계획 만들기"가 성공하면(화면은 htmx 가 교체한다) 모달을 닫는다. 실패(400)면 모달 안에 오류가 남는다
  document.addEventListener("htmx:afterRequest", function (e) {
    if (e.target && e.target.id === "plan-form" && e.detail.successful) closePlan();
  });

  // 검증 오류(400)는 #plan-errors 에 그대로 보여 준다
  document.addEventListener("htmx:beforeSwap", function (e) {
    var xhr = e.detail && e.detail.xhr;
    if (xhr && xhr.status === 400 && e.detail.target && e.detail.target.id === "plan-errors") {
      e.detail.shouldSwap = true; e.detail.isError = false;
    }
  });

  document.addEventListener("click", function (e) {
    // data-plan-dest(+ data-plan-days, data-plan-places): 여행지·일수·장소가 미리 채워진 계획 모달을 연다
    var pd = e.target.closest("[data-plan-dest]");
    if (pd) {
      openPlan({ destination: pd.getAttribute("data-plan-dest"), days: pd.getAttribute("data-plan-days"),
        places: pd.getAttribute("data-plan-places") });
      return;
    }
    var loc = e.target.closest("[data-local-open]");
    if (loc && !(e.ctrlKey || e.metaKey || e.shiftKey || e.button)) {   // 이 기기에 저장된 사본: 페이지 이동 없이 읽기 전용 작업실로
      e.preventDefault();
      var li = loc.closest("li"), plan = li && PlanStore.get(li.getAttribute("data-thread-id"));
      if (plan) openLocal(plan, true);
      return;
    }
    if (!e.target.closest("[data-action=history-menu], [role=menu]")) closeHistoryMenus();
    var el = e.target.closest("[data-action],[data-fill],[data-ask]");
    if (!el) return;
    var a = el.getAttribute("data-action");
    if (el.hasAttribute("data-ask")) askNow(el.getAttribute("data-ask"));
    else if (el.hasAttribute("data-fill")) fillInput(el.getAttribute("data-fill"));
    else if (a === "toggle-chat") setOpen(!isOpen(), { focusFab: false });
    else if (a === "close-chat") setOpen(false, { focusFab: true });
    else if (a === "toggle-theme") {
      var next = currentTheme() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      store("theme", next);
    } else if (a === "open-gnb") gnbPanel(true);
    else if (a === "close-gnb") gnbPanel(false);
    else if (a === "toggle-dest-menu") destMenu(!destMenuOpen());
    else if (a === "open-menu") menu(true);
    else if (a === "close-menu") menu(false);
    else if (a === "history-menu") toggleHistoryMenu(el);
    else if (a === "history-delete") { closeHistoryMenus(); askDelete(el.getAttribute("data-thread-id"), el, "history", el.getAttribute("data-label")); }
    else if (a === "new-plan") openPlan();
    else if (a === "edit-plan") openPlan({ destination: el.getAttribute("data-destination"), start: el.getAttribute("data-start"),
      days: el.getAttribute("data-days"), places: el.getAttribute("data-places") });
    else if (a === "close-plan") closePlan();
    else if (a === "delete-local-plan") askDelete(el.getAttribute("data-thread-id") || currentThread(), el);
    else if (a === "confirm-delete") finishDelete(true);
    else if (a === "cancel-delete") finishDelete(false);
    else if (a === "focus-input") openChat();
    else if (a === "retry") retryLast();
  });

  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) { e.preventDefault(); openChat(); return; }
    if (e.key === "Escape") {
      if (planModal && planModal.open) return;   // 모달은 <dialog> 가 직접 닫는다
      if (destMenuOpen()) { destMenu(false); var tb = $('[data-action="toggle-dest-menu"]'); if (tb) tb.focus(); return; }
      var gp = $("#gnb-panel");
      if (gp && gp.getAttribute("data-open") === "true") { gnbPanel(false); return; }
      var hm = document.querySelector('[data-action="history-menu"][aria-expanded="true"]');
      if (hm) { closeHistoryMenus(); hm.focus(); return; }
      var sb = $("#sidebar");
      if (sb && sb.getAttribute("data-open") === "true") { menu(false); var ob = $('[data-action="open-menu"]'); if (ob && ob.offsetParent !== null) ob.focus(); return; }
      if (isOpen()) setOpen(false, { focusFab: true });
    }
    var t = e.target;
    if (t && t.tagName === "TEXTAREA" && e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      if (t.value.trim() && !busy && t.form) t.form.requestSubmit();
    }
  });

  // 헤더 제목(#page-title)이 SSE 로 교체되면 탭 제목도 같이 바꾼다
  (function syncTitle() {
    var h = $("#page-title");
    if (!h || !window.MutationObserver) return;
    var host = h.parentNode, suffix = " · 스마트 여행 비서";
    new MutationObserver(function () {
      var cur = $("#page-title");
      if (cur) document.title = cur.textContent.trim() + suffix;
    }).observe(host, { childList: true, subtree: true, characterData: true });
  })();

  function stampTimes() {
    document.querySelectorAll("[data-time]:empty").forEach(function (p) {
      if (p.getAttribute("data-time") !== "late") p.textContent = nowStamp();
    });
  }

  document.addEventListener("htmx:beforeRequest", function (e) {
    if (e.target && e.target.id === "chat-form") setBusy(true);
  });
  document.addEventListener("htmx:afterRequest", function (e) {
    var f = e.target;
    if (!f || f.id !== "chat-form") return;
    if (!e.detail.successful) { setBusy(false); return; }
    var ta = $("textarea", f);
    if (ta) { ta.value = ""; ta.focus(); }
    var chips = $("[data-intro-chips]");
    if (chips) chips.remove();
    var tid = $('input[name="thread_id"]');
    if (tid && tid.value && window.history && history.replaceState) history.replaceState(null, "", "/planner?thread_id=" + encodeURIComponent(tid.value) + (/[?&]debug=1/.test(location.search) ? "&debug=1" : ""));
    // 입력 검증 오류 등 스트림이 없는 응답이면 바로 대기 상태로 돌아간다
    var body = (e.detail.xhr && e.detail.xhr.responseText) || "";
    if (body.indexOf("sse-connect") < 0) setBusy(false);
    scrollThread(true);
  });
  document.addEventListener("htmx:afterSwap", function () { stampTimes(); scrollThread(); });
  document.addEventListener("htmx:sseError", function () { setBusy(false); });
  document.addEventListener("htmx:sseMessage", function (e) {
    var type = e.detail && e.detail.type;
    scrollThread();
    if (type === "answer" && !isOpen()) { var dot = $("#chat-dot"); if (dot) dot.classList.remove("hidden"); }
    if (type === "done") {
      var late = document.querySelectorAll('[data-time="late"]:empty');
      if (late.length) late[late.length - 1].textContent = nowStamp();
      setBusy(false);
      // 계획 생성·상세 요청이 끝날 때마다 서버가 가진 계획을 이 기기에 저장(갱신)한다
      var tidEl = $('input[name="thread_id"]');
      if (tidEl) savePlan(tidEl.value);
      // 답변이 끝나면 내 여행 기록을 갱신 (대화는 그래프 실행 후에야 체크포인터에 저장된다)
      refreshHistory();
    }
  });

  if (window.matchMedia) window.matchMedia("(min-width: 1024px)").addEventListener("change", function () { menu(false); gnbPanel(false); });

  // 주소에 thread_id 가 없이 최근 기록이 열렸다면 주소에 실제 thread 를 적어 둔다(뒤로가기·새로고침이 같은 화면을 가리키게)
  (function fixUrl() {
    var s = session();
    if (location.pathname !== "/planner" || !s || /[?&]thread_id=/.test(location.search)) return;
    if (s.getAttribute("data-empty") === "true" || !history.replaceState) return;
    history.replaceState(null, "", "/planner?thread_id=" + encodeURIComponent(currentThread()) + debugQuery("&"));
  })();

  restoreOffline();
  renderLocal();

  // 초기 열림 상태: 저장값 우선. 없으면 빈 대화의 첫 방문일 때 데스크톱만 열어 둔다
  if (widget) {
    var saved = store("chat-open");
    var desktop = window.matchMedia && window.matchMedia("(min-width: 640px)").matches;
    var open = saved === "1" || saved === "0" ? saved === "1" : ((session() && session().getAttribute("data-empty") === "true") && desktop);
    if (session() && session().getAttribute("data-autostart") === "true") { open = true; setBusy(true); }   // 계획 생성 스트림이 바로 시작된다
    if (open) setOpen(true, { focus: false, save: false });
    scrollThread(true);
  }
})();
