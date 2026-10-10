(function () {
  "use strict";
  var D = window.DASHBOARD_DATA || { stocks: [] };
  var stocks = (D.stocks || []).slice();

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function isNum(v) { return typeof v === "number" && isFinite(v); }
  function fmtPrice(v) {
    return isNum(v) ? "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—";
  }
  function fmtPct(v) {
    if (!isNum(v)) return "—";
    var s = Math.abs(v).toFixed(2) + "%";
    return (v > 0 ? "+" : v < 0 ? "−" : "") + s;
  }
  function fmtCap(v) {
    if (!isNum(v)) return "—";
    var a = Math.abs(v), u = [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]];
    for (var i = 0; i < u.length; i++) {
      if (a >= u[i][0]) return "$" + (v / u[i][0]).toFixed(2) + u[i][1];
    }
    return "$" + v.toFixed(0);
  }
  function dir(v) { return !isNum(v) || v === 0 ? "" : v > 0 ? "up" : "down"; }
  function fmtDate(s) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || "");
    if (!m) return s || "";
    var d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    return d.toLocaleDateString("en-US", { weekday: "short", year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
  }
  function fmtStamp(s) {
    var d = new Date(s);
    if (!s || isNaN(d)) return s || "";
    try {
      return d.toLocaleString("en-GB", { timeZone: "Asia/Hong_Kong", day: "numeric", month: "short", year: "numeric",
        hour: "2-digit", minute: "2-digit", hour12: false }) + " HKT";
    } catch (e) { return s; }
  }
  function safeUrl(u) { return /^https?:\/\//i.test(u || "") ? u : ""; }

  // ---- example banner
  if (D.is_example) {
    var b = el("div", "example-banner", "⚠ Example data — not real prices");
    b.setAttribute("role", "alert");
    b.appendChild(el("small", null, "Prices, moves, reasons and sources are invented for layout preview. Real Stock Watcher results will replace this automatically on rebuild."));
    $("banner-slot").appendChild(b);
  }

  // ---- header
  $("session-date").textContent = D.session_date ? "Session " + fmtDate(D.session_date) : "Session date unavailable";
  $("market-context").textContent = D.market_context || "No market context provided.";

  var withPct = stocks.filter(function (s) { return isNum(s.pct_change); });
  var up = withPct.filter(function (s) { return s.pct_change > 0; }).length;
  var down = withPct.filter(function (s) { return s.pct_change < 0; }).length;
  var movers = stocks.filter(function (s) { return s.mover; })
    .sort(function (a, b) { return Math.abs(b.pct_change || 0) - Math.abs(a.pct_change || 0); });
  var stats = $("stats");
  function stat(n, label, cls) {
    var s = el("div", "stat"); var bb = el("b", cls || null, String(n));
    s.appendChild(bb); s.appendChild(document.createTextNode(label)); stats.appendChild(s);
  }
  stat(stocks.length, "stocks");
  stat(up, "up", "up");
  stat(down, "down", "down");
  stat(movers.length, "movers");
  if (withPct.length) {
    var best = withPct.reduce(function (a, b) { return b.pct_change > a.pct_change ? b : a; });
    var worst = withPct.reduce(function (a, b) { return b.pct_change < a.pct_change ? b : a; });
    stat(best.ticker, " best " + fmtPct(best.pct_change), "up");
    stat(worst.ticker, " worst " + fmtPct(worst.pct_change), "down");
  }

  // ---- movers
  var thr = D.mover_threshold || 3;
  $("movers-sub").textContent = movers.length ? movers.length + " flagged (moves ≥ " + thr + "%)" : "";
  var box = $("movers");
  if (!movers.length) {
    box.appendChild(el("div", "empty", "No movers flagged this session."));
  }
  movers.forEach(function (s) {
    var d = dir(s.pct_change);
    var c = el("article", "card " + d);
    var top = el("div", "card-top");
    var left = el("div");
    left.appendChild(el("div", "tk", s.ticker));
    left.appendChild(el("div", "nm", s.name || ""));
    top.appendChild(left);
    top.appendChild(el("span", "pill num " + d, fmtPct(s.pct_change)));
    c.appendChild(top);
    var px = [];
    if (isNum(s.close)) px.push("Close " + fmtPrice(s.close));
    if (isNum(s.prev_close)) px.push("prev " + fmtPrice(s.prev_close));
    if (isNum(s.market_cap)) px.push("cap " + fmtCap(s.market_cap));
    if (px.length) c.appendChild(el("div", "px num", px.join(" · ")));
    c.appendChild(el("p", "reason" + (s.reason ? "" : " muted"), s.reason || "No reason text provided."));
    if (s.sources && s.sources.length) {
      var ul = el("ul", "sources");
      s.sources.forEach(function (src) {
        var li = el("li");
        li.appendChild(el("span", "outlet", (src.outlet || "Source") + ": "));
        var url = safeUrl(src.url), t = src.title || src.url || "(untitled)";
        if (url) {
          var a = el("a", null, t);
          a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer";
          li.appendChild(a);
        } else {
          li.appendChild(document.createTextNode(t));
        }
        ul.appendChild(li);
      });
      c.appendChild(ul);
    }
    box.appendChild(c);
  });

  // ---- table
  var tbody = document.querySelector("#tbl tbody");
  var ths = document.querySelectorAll("#tbl th");
  var sortKey = "market_cap", sortDir = -1, query = "";

  function render() {
    var col = document.querySelector('#tbl th[data-key="' + sortKey + '"]');
    var type = col ? col.getAttribute("data-type") : "num";
    var rows = stocks.filter(function (s) {
      if (!query) return true;
      return (s.ticker + " " + (s.name || "")).toLowerCase().indexOf(query) !== -1;
    });
    rows.sort(function (a, b) {
      var x = a[sortKey], y = b[sortKey];
      var xm = type === "num" ? !isNum(x) : !x, ym = type === "num" ? !isNum(y) : !y;
      if (xm || ym) return xm === ym ? 0 : xm ? 1 : -1;  // blanks always last
      var r = type === "num" ? x - y : String(x).localeCompare(String(y));
      return r * sortDir || a.ticker.localeCompare(b.ticker);
    });
    tbody.textContent = "";
    rows.forEach(function (s) {
      var tr = el("tr", s.mover ? "is-mover" : "");
      var tdT = el("td", "tk", s.ticker);
      tdT.title = s.name || "";
      tr.appendChild(tdT);
      var tdN = el("td", "col-name", s.name || ""); tdN.title = s.name || ""; tr.appendChild(tdN);
      tr.appendChild(el("td", "r num", fmtPrice(s.close)));
      tr.appendChild(el("td", "r num", fmtPrice(s.prev_close)));
      tr.appendChild(el("td", "r num " + dir(s.pct_change), fmtPct(s.pct_change)));
      tr.appendChild(el("td", "r num", fmtCap(s.market_cap)));
      tbody.appendChild(tr);
    });
    if (!rows.length) {
      var tr0 = el("tr"), td0 = el("td", "muted", "No matches.");
      td0.colSpan = 6; tr0.appendChild(td0); tbody.appendChild(tr0);
    }
    ths.forEach(function (th) {
      th.setAttribute("aria-sort", th.getAttribute("data-key") === sortKey ? (sortDir > 0 ? "ascending" : "descending") : "none");
    });
  }
  ths.forEach(function (th) {
    th.tabIndex = 0;
    function go() {
      var k = th.getAttribute("data-key");
      if (k === sortKey) sortDir = -sortDir;
      else { sortKey = k; sortDir = th.getAttribute("data-type") === "str" ? 1 : -1; }
      render();
    }
    th.addEventListener("click", go);
    th.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
  });
  $("filter").addEventListener("input", function (e) { query = e.target.value.trim().toLowerCase(); render(); });
  render();

  // ---- footer
  var f = $("footer");
  f.appendChild(el("p", null, (D.is_example ? "EXAMPLE DATA. " : "") + "Source: " + (D.source || "unknown") +
    (D.generated_at ? " · digest generated " + fmtStamp(D.generated_at) : "")));
  (D.notes || []).forEach(function (n) { f.appendChild(el("p", null, "Note: " + n)); });
  f.appendChild(el("p", null, "Not investment advice. Rebuilt from Stock Watcher output (python3 build.py). Hosted on GitHub Pages."));
})();
