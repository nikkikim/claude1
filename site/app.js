/* Daily News Digest — 정적 웹앱. 데이터: data/index.json, data/YYYY-MM-DD.json (build_site.py가 생성)
   모든 본문은 textContent로만 넣어서 기사 내용이 HTML로 해석되지 않는다. */
(function () {
  "use strict";
  var CFG = window.SITE_CONFIG || {};
  var CATS = {
    "세계 이슈": "#e03131", "경제·증시": "#1c7ed6", "코인": "#e8890c", "문화예술": "#9c36b5",
    "AI": "#e64980", "정치·사회": "#2f9e44", "IT·과학": "#0c8599", "스포츠": "#5c7cfa"
  };
  var DOW = ["일", "월", "화", "수", "목", "금", "토"];
  var $ = function (id) { return document.getElementById(id); };
  var state = { dates: [], heads: {}, current: null, viewY: 0, viewM: 0, cache: {} };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function safeUrl(u) { return /^https?:\/\//i.test(String(u || "")) ? String(u) : "#"; }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function ymd(y, m, d) { return y + "-" + pad(m + 1) + "-" + pad(d); }
  function parse(s) { var p = s.split("-"); return { y: +p[0], m: +p[1] - 1, d: +p[2] }; }
  function longDate(s) { var p = parse(s); var w = DOW[new Date(p.y, p.m, p.d).getDay()]; return p.y + "년 " + (p.m + 1) + "월 " + p.d + "일 (" + w + ")"; }
  function store(op, k, v) { try { return op === "get" ? localStorage.getItem(k) : op === "set" ? localStorage.setItem(k, v) : localStorage.removeItem(k); } catch (e) { return null; } }

  /* ---------- 테마 ---------- */
  function applyTheme(t) { if (t) document.documentElement.setAttribute("data-theme", t); else document.documentElement.removeAttribute("data-theme"); }
  applyTheme(store("get", "theme"));
  $("themeBtn").addEventListener("click", function () {
    var cur = document.documentElement.getAttribute("data-theme") ||
      (window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    var next = cur === "dark" ? "light" : "dark";
    applyTheme(next); store("set", "theme", next);
  });

  /* ---------- 달력 ---------- */
  function has(s) { return state.heads.hasOwnProperty(s); }
  function renderCalendar() {
    var y = state.viewY, m = state.viewM;
    $("calTitle").textContent = y + "년 " + (m + 1) + "월";
    var grid = $("calGrid"); grid.textContent = "";
    DOW.forEach(function (w) { grid.appendChild(el("div", "cal-dow", w)); });
    var first = new Date(y, m, 1).getDay(), days = new Date(y, m + 1, 0).getDate();
    for (var i = 0; i < first; i++) grid.appendChild(el("div"));
    var t = new Date(), todayS = ymd(t.getFullYear(), t.getMonth(), t.getDate());
    for (var d = 1; d <= days; d++) {
      var s = ymd(y, m, d), dow = (first + d - 1) % 7;
      var b = el("button", "cal-day" + (dow === 0 ? " sun" : dow === 6 ? " sat" : ""), String(d));
      b.type = "button";
      if (s === todayS) b.classList.add("today");
      if (has(s)) {
        b.classList.add("has"); b.title = state.heads[s] || s;
        b.setAttribute("aria-label", longDate(s) + " 브리핑 보기");
        (function (ds) { b.addEventListener("click", function () { go(ds); closeMenu(); }); })(s);
      } else { b.disabled = true; }
      if (s === state.current) { b.classList.add("sel"); b.setAttribute("aria-current", "date"); }
      grid.appendChild(b);
    }
    var inMonth = state.dates.filter(function (s) { return s.indexOf(y + "-" + pad(m + 1)) === 0; });
    $("calCount").textContent = "이 달 " + inMonth.length + "개 · 전체 " + state.dates.length + "개";
    var list = $("monthList"); list.textContent = "";
    inMonth.forEach(function (s) {
      var li = el("li"), b = el("button", s === state.current ? "sel" : "");
      b.type = "button";
      b.appendChild(el("span", "d", longDate(s)));
      b.appendChild(el("span", "h", state.heads[s] || ""));
      b.addEventListener("click", function () { go(s); closeMenu(); });
      li.appendChild(b); list.appendChild(li);
    });
    if (!inMonth.length) { var li0 = el("li", "muted small", "이 달에는 보관된 브리핑이 없습니다."); list.appendChild(li0); }
    var minD = state.dates.length ? parse(state.dates[state.dates.length - 1]) : null;
    var maxD = state.dates.length ? parse(state.dates[0]) : null;
    $("prevMonth").disabled = !!minD && (y < minD.y || (y === minD.y && m <= minD.m));
    $("nextMonth").disabled = !!maxD && (y > maxD.y || (y === maxD.y && m >= maxD.m));
  }
  function shiftMonth(delta) {
    var d = new Date(state.viewY, state.viewM + delta, 1);
    state.viewY = d.getFullYear(); state.viewM = d.getMonth(); renderCalendar();
  }
  $("prevMonth").addEventListener("click", function () { shiftMonth(-1); });
  $("nextMonth").addEventListener("click", function () { shiftMonth(1); });
  $("latestBtn").addEventListener("click", function () { if (state.dates.length) go(state.dates[0]); closeMenu(); });
  $("brand").addEventListener("click", function (e) { e.preventDefault(); if (state.dates.length) go(state.dates[0]); });
  function closeMenu() { $("sidebar").classList.remove("open"); $("menuBtn").setAttribute("aria-expanded", "false"); }
  $("menuBtn").addEventListener("click", function () {
    var open = $("sidebar").classList.toggle("open");
    $("menuBtn").setAttribute("aria-expanded", open ? "true" : "false");
  });

  /* ---------- 날씨 ---------- */
  function skyIcon(s) {
    s = String(s || "");
    if (/천둥/.test(s)) return "⛈️"; if (/눈|싸락/.test(s)) return "❄️"; if (/비|소나기|이슬비/.test(s)) return "🌧️";
    if (/안개/.test(s)) return "🌫️"; if (/흐림/.test(s)) return "☁️"; if (/구름/.test(s)) return "⛅";
    if (/대체로 맑음/.test(s)) return "🌤️"; if (/맑음/.test(s)) return "☀️"; return "🌡️";
  }
  function renderWeather(list) {
    var box = el("section", "panel weather"); box.appendChild(el("h2", null, "🌤 오늘의 날씨"));
    var g = el("div", "wgrid"), ref = list[0].date;
    list.forEach(function (w) {
      var c = el("div", "wcard"), head = el("div", "wcity", w.city);
      if (w.date !== ref) { var p = parse(w.date); head.appendChild(el("small", null, "현지 " + (p.m + 1) + "/" + p.d + "일")); }
      c.appendChild(head);
      var main = el("div", "wmain");
      main.appendChild(el("span", "wico", skyIcon(w.sky)));
      main.appendChild(el("span", "wtemp", w.now || w.hi));
      main.appendChild(el("span", "wsky", w.sky));
      c.appendChild(main);
      var r1 = el("div", "wrow"); r1.appendChild(el("b", null, "최저 " + w.lo + " / 최고 " + w.hi)); c.appendChild(r1);
      var r2 = el("div", "wrow wmood " + (/따뜻/.test(w.mood) ? "up" : /쌀쌀/.test(w.mood) ? "down" : ""), w.mood + " (" + w.diff + ")"); c.appendChild(r2);
      c.appendChild(el("div", "wrow", w.precip));
      if (w.tomorrow) c.appendChild(el("div", "wrow muted", "내일 " + w.tomorrow));
      g.appendChild(c);
    });
    box.appendChild(g); return box;
  }

  /* ---------- 본문 ---------- */
  function colorOf(topic) { return CATS[topic] || "#667085"; }
  function metaLine(d) {
    var m = d.meta; if (!m) return "";
    var p = ["기사 " + (m.articles || 0) + "건", "매체 " + (m.outlets || 0) + "곳"];
    p.push(d.ai === false ? "AI 요약 없음" : "요약 모델: " + (String(d.model || "").replace(":free", "") || "알 수 없음"));
    if (m.failed_feeds && m.failed_feeds.length) p.push("읽지 못한 매체: " + m.failed_feeds.join(", "));
    return p.join(" · ");
  }
  function renderDigest(date, d) {
    var v = $("view"); v.textContent = "";
    var idx = state.dates.indexOf(date);
    var nav = el("div", "day-nav");
    var older = el("button", null, "← 이전 브리핑"); older.type = "button";
    var newer = el("button", null, "다음 브리핑 →"); newer.type = "button";
    older.disabled = idx < 0 || idx >= state.dates.length - 1; newer.disabled = idx <= 0;
    older.addEventListener("click", function () { go(state.dates[idx + 1]); });
    newer.addEventListener("click", function () { go(state.dates[idx - 1]); });
    nav.appendChild(older); nav.appendChild(newer); v.appendChild(nav);

    (d.notices || []).forEach(function (n) {
      var box = el("section", "notice"); box.appendChild(el("h2", null, n.title || "알림"));
      (n.lines || []).forEach(function (x) { box.appendChild(el("p", null, x)); });
      v.appendChild(box);
    });
    var hero = el("section", "hero");
    hero.appendChild(el("div", "date", longDate(date)));
    hero.appendChild(el("h1", null, d.headline || "뉴스 브리핑"));
    hero.appendChild(el("span", "badge", d.ai === false ? "헤드라인 모드" : "AI 요약"));
    v.appendChild(hero);

    if (d.weather && d.weather.length) v.appendChild(renderWeather(d.weather));
    if (d.message && d.message.ko) {
      var q = el("section", "panel quote"); q.appendChild(el("h2", null, "☀️ 오늘의 한마디"));
      q.appendChild(el("p", "ko", d.message.ko)); q.appendChild(el("p", "en", d.message.en || "")); v.appendChild(q);
    }
    var secs = d.sections || [];
    var core = secs.filter(function (s) { return s.overview && String(s.overview).trim(); });
    if (core.length) {
      var cp = el("section", "panel core"); cp.appendChild(el("h2", null, "📌 카테고리별 오늘의 핵심"));
      var ul = el("ul");
      core.forEach(function (s, i) {
        var li = el("li"), a = el("a", "chip", s.topic); a.href = "#sec-" + secs.indexOf(s); a.style.setProperty("--c", colorOf(s.topic));
        a.addEventListener("click", function (e) { e.preventDefault(); jump(secs.indexOf(s)); });
        li.appendChild(a); li.appendChild(el("p", null, String(s.overview).trim())); ul.appendChild(li);
      });
      cp.appendChild(ul); v.appendChild(cp);
    }
    if (secs.length) {
      var cn = el("nav", "catnav"); cn.setAttribute("aria-label", "카테고리 바로가기");
      secs.forEach(function (s, i) {
        var a = el("a", "chip", s.topic + " " + (s.items || []).length); a.href = "#sec-" + i; a.style.setProperty("--c", colorOf(s.topic));
        a.addEventListener("click", function (e) { e.preventDefault(); jump(i); });
        cn.appendChild(a);
      });
      v.appendChild(cn);
    }
    secs.forEach(function (s, i) {
      var sec = el("section", "section"); sec.id = "sec-" + i; sec.style.setProperty("--c", colorOf(s.topic));
      sec.appendChild(el("h2", null, s.topic));
      (s.items || []).forEach(function (it) {
        var card = el("article", "item"), a = el("a", "t", it.title || "");
        a.href = safeUrl(it.link); a.target = "_blank"; a.rel = "noopener noreferrer";
        card.appendChild(a);
        if (it.summary) card.appendChild(el("p", null, it.summary));
        var src = el("div", "src");
        String(it.source || "").split(",").forEach(function (x) { x = x.trim(); if (x) src.appendChild(el("span", null, x)); });
        card.appendChild(src); sec.appendChild(card);
      });
      v.appendChild(sec);
    });
    var foot = el("footer", "foot");
    foot.appendChild(el("div", null, d.ai === false ? "AI 요약 없이 각 신문사의 제목과 발췌문을 모은 목록입니다. 자세한 내용은 원문을 확인하세요."
      : "AI가 자동 요약한 내용이므로 중요한 사항은 원문을 확인하세요."));
    var ml = metaLine(d); if (ml) foot.appendChild(el("div", null, ml));
    if (d.outlets && Object.keys(d.outlets).length) {
      var det = el("details"); det.appendChild(el("summary", null, "참고한 신문사"));
      Object.keys(d.outlets).forEach(function (r) { det.appendChild(el("div", null, r + ": " + d.outlets[r].join(", "))); });
      foot.appendChild(det);
    }
    v.appendChild(foot);
  }
  function jump(i) { var t = $("sec-" + i); if (t) t.scrollIntoView({ behavior: "smooth", block: "start" }); }

  /* ---------- 이동/불러오기 ---------- */
  function go(date) { if (location.hash.slice(1) === date) show(date); else location.hash = date; }
  function show(date) {
    if (!has(date)) { return showEmpty(); }
    state.current = date; var p = parse(date); state.viewY = p.y; state.viewM = p.m; renderCalendar();
    document.title = longDate(date) + " · Daily News Digest";
    if (state.cache[date]) { renderDigest(date, state.cache[date]); window.scrollTo(0, 0); return; }
    $("view").textContent = ""; $("view").appendChild(el("p", "muted center", "불러오는 중…"));
    fetch("data/" + date + ".json", { cache: "no-cache" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status); return r.json();
    }).then(function (d) {
      state.cache[date] = d; if (state.current === date) { renderDigest(date, d); window.scrollTo(0, 0); }
    }).catch(function (e) {
      $("view").textContent = ""; $("view").appendChild(el("div", "empty", "브리핑을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요. (" + e.message + ")"));
    });
  }
  function showEmpty() {
    var v = $("view"); v.textContent = "";
    v.appendChild(el("div", "empty", state.dates.length ? "선택한 날짜에는 보관된 브리핑이 없습니다. 달력에서 점이 찍힌 날짜를 눌러 보세요."
      : "아직 보관된 브리핑이 없습니다. 내일 아침 첫 브리핑이 올라오면 여기에 나타납니다."));
    renderCalendar();
  }
  window.addEventListener("hashchange", function () { var h = location.hash.slice(1); if (/^\d{4}-\d{2}-\d{2}$/.test(h)) show(h); });

  /* ---------- 이메일 보내기 ---------- */
  var dlg = $("mailDialog");
  function repoInfo() {
    var repo = CFG.repo || "";
    if (!repo) { var o = location.hostname.split(".")[0], r = location.pathname.split("/")[1]; if (o && r) repo = o + "/" + r; }
    return { repo: repo, workflow: CFG.workflow || "daily-news.yml", ref: CFG.ref || "main" };
  }
  function setStatus(msg, kind) { var s = $("sendStatus"); s.textContent = msg; s.className = "status" + (kind ? " " + kind : ""); }
  function mailtoHref() {
    var d = state.cache[state.current] || {}, lines = [];
    lines.push(d.headline || "뉴스 브리핑", "");
    (d.sections || []).forEach(function (s) { if (s.overview) lines.push("■ " + s.topic + ": " + String(s.overview).trim(), ""); });
    lines.push("전체 보기: " + location.href.split("#")[0] + "#" + (state.current || ""));
    var body = lines.join("\n"); if (body.length > 1500) body = body.slice(0, 1480) + "…\n\n" + lines[lines.length - 1];
    return "mailto:?subject=" + encodeURIComponent("[뉴스 브리핑] " + (state.current || "") + " " + (d.headline || "")) + "&body=" + encodeURIComponent(body);
  }
  function openMail() {
    var info = repoInfo();
    $("mailTarget").textContent = state.current ? longDate(state.current) + " 브리핑을 보냅니다." : "보관된 브리핑이 없어 보낼 수 없습니다.";
    $("sendNow").disabled = !state.current; setStatus("");
    $("openActions").href = "https://github.com/" + info.repo + "/actions/workflows/" + info.workflow;
    $("mailtoLink").href = mailtoHref();
    $("tokenBox").open = !store("get", "gh_token");
    $("tokenInput").value = "";
    if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
  }
  $("mailBtn").addEventListener("click", openMail);
  dlg.addEventListener("click", function (e) { if (e.target === dlg) dlg.close(); });
  $("saveToken").addEventListener("click", function () {
    var t = $("tokenInput").value.trim();
    if (!/^(github_pat_|ghp_)[A-Za-z0-9_]{20,}$/.test(t)) { setStatus("토큰 형식이 올바르지 않습니다(github_pat_ 으로 시작).", "err"); return; }
    store("set", "gh_token", t); $("tokenInput").value = ""; setStatus("토큰을 이 브라우저에 저장했습니다. 이제 '지금 보내기'를 누르세요.", "ok");
  });
  $("clearToken").addEventListener("click", function () { store("remove", "gh_token"); setStatus("저장된 토큰을 지웠습니다.", "ok"); });
  $("sendNow").addEventListener("click", function () {
    var token = store("get", "gh_token");
    if (!token) { $("tokenBox").open = true; setStatus("먼저 아래 '처음 한 번만 설정'에서 토큰을 저장하거나, 'GitHub에서 직접 실행'을 이용하세요.", "err"); return; }
    var info = repoInfo(), btn = $("sendNow"); btn.disabled = true; setStatus("요청을 보내는 중…");
    fetch("https://api.github.com/repos/" + info.repo + "/actions/workflows/" + info.workflow + "/dispatches", {
      method: "POST",
      headers: { "Accept": "application/vnd.github+json", "Authorization": "Bearer " + token, "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json" },
      body: JSON.stringify({ ref: info.ref, inputs: { resend: "true", resend_date: state.current } })
    }).then(function (r) {
      if (r.status === 204) { setStatus("✅ 발송을 요청했습니다. 1~2분 안에 메일이 도착합니다. (여러 번 눌러도 됩니다)", "ok"); }
      else if (r.status === 401 || r.status === 403 || r.status === 404) { setStatus("권한이 없습니다(" + r.status + "). 토큰의 저장소 선택과 'Actions: Read and write' 권한을 확인하세요.", "err"); }
      else if (r.status === 422) { setStatus("요청이 거부되었습니다(422). 워크플로가 아직 이 기능을 지원하지 않거나 브랜치 이름이 다릅니다.", "err"); }
      else { setStatus("실패했습니다(HTTP " + r.status + "). 잠시 후 다시 시도하세요.", "err"); }
    }).catch(function () { setStatus("네트워크 오류로 요청하지 못했습니다.", "err"); })
      .then(function () { btn.disabled = !state.current; });
  });

  /* ---------- 시작 ---------- */
  fetch("data/index.json", { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(function (list) {
      list.sort(function (a, b) { return a.d < b.d ? 1 : -1; });
      state.dates = list.map(function (x) { return x.d; });
      list.forEach(function (x) { state.heads[x.d] = x.h || ""; });
      var n = new Date(); state.viewY = n.getFullYear(); state.viewM = n.getMonth();
      var h = location.hash.slice(1);
      if (state.dates.length) { show(/^\d{4}-\d{2}-\d{2}$/.test(h) && has(h) ? h : state.dates[0]); }
      else { var p = new Date(); state.viewY = p.getFullYear(); state.viewM = p.getMonth(); renderCalendar(); showEmpty(); }
    }).catch(function (e) {
      $("view").textContent = ""; $("view").appendChild(el("div", "empty", "데이터를 불러오지 못했습니다. (" + e.message + ")")); renderCalendar();
    });
})();
