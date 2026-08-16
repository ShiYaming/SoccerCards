"use strict";

const $ = (id) => document.getElementById(id);
const fmt = (n, d = 0) => n == null ? "—" : n.toLocaleString("zh-CN", {
  minimumFractionDigits: d, maximumFractionDigits: d,
});
const money = (n) => n == null ? "—" : "$" + fmt(n, n < 20 ? 2 : 0);
const eur = (n) => n == null ? "—" : (n >= 1e8 ? "€" + fmt(n / 1e8, 1) + "亿" :
  n >= 1e6 ? "€" + fmt(n / 1e6, 1) + "M" : "€" + fmt(n / 1e4, 1) + "万");

let rows = [];

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* ---------- 渲染 ---------- */

function renderStats(stats) {
  $("stats-bar").innerHTML = [
    ["系列", stats.sets], ["卡片", stats.cards], ["成交记录", stats.sales], ["球员", stats.players],
  ].map(([k, v]) => `<div class="stat"><div class="k">${k}</div><div class="v">${fmt(v)}</div></div>`).join("");
}

function renderTable(data) {
  rows = data;
  const tbody = $("card-tbody");
  if (!data.length) {
    tbody.innerHTML = `<tr><td colspan="11" class="empty">没有匹配的卡片</td></tr>`;
    return;
  }
  tbody.innerHTML = data.map((r) => {
    const f = r.forecast || {};
    return `<tr data-id="${r.card_id}">
      <td><b>${escapeHtml(r.player)}</b><br><span class="muted">${escapeHtml(r.club || "")}</span></td>
      <td>${escapeHtml(r.set_name)}</td>
      <td>${escapeHtml(r.card_number || "")}</td>
      <td>${r.parallel ? `<span class="pill">${escapeHtml(r.parallel)}</span>` : "—"}</td>
      <td class="num">${r.n_sales}</td>
      <td class="num">${money(r.avg_price)}</td>
      <td class="num">${money(r.median_price)}</td>
      <td class="num"><b>${money(r.current_value)}</b></td>
      <td class="num">${money(f["90天"])}</td>
      <td class="num">${money(f["180天"])}</td>
      <td class="num">${money(f["365天"])}</td>
    </tr>`;
  }).join("");
  tbody.querySelectorAll("tr").forEach((tr) =>
    tr.addEventListener("click", () => openDetail(+tr.dataset.id)));
}

/* ---------- SVG 图表 ---------- */

function makeSvg(w, h) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.setAttribute("width", "100%");
  return svg;
}

function forecastChart(container, fc) {
  container.innerHTML = "";
  if (!fc || !fc.points || !fc.points.length) {
    container.innerHTML = `<p class="empty">暂无预测数据</p>`;
    return;
  }
  const W = 620, H = 230, L = 46, R = 14, T = 14, B = 34;
  const xs = [0, ...fc.points.map((p) => p.days)];
  const vals = [fc.base_value, ...fc.points.flatMap((p) => [p.value, p.low, p.high])];
  const lo = Math.min(...vals) * 0.7, hi = Math.max(...vals) * 1.3;
  const X = (d) => L + (d / 365) * (W - L - R);
  const Y = (v) => T + (1 - (Math.log(v) - Math.log(lo)) / (Math.log(hi) - Math.log(lo))) * (H - T - B);
  const svg = makeSvg(W, H);
  const ns = "http://www.w3.org/2000/svg";

  const band = [];
  fc.points.forEach((p) => band.push(`${X(p.days)},${Y(p.high)}`));
  [...fc.points].reverse().forEach((p) => band.push(`${X(p.days)},${Y(p.low)}`));
  const poly = document.createElementNS(ns, "polygon");
  poly.setAttribute("points", band.join(" "));
  poly.setAttribute("fill", "#1f6feb");
  poly.setAttribute("opacity", "0.12");
  svg.appendChild(poly);

  const linePts = [X(0) + "," + Y(fc.base_value),
    ...fc.points.map((p) => `${X(p.days)},${Y(p.value)}`)];
  const line = document.createElementNS(ns, "polyline");
  line.setAttribute("points", linePts.join(" "));
  line.setAttribute("fill", "none");
  line.setAttribute("stroke", "#1f6feb");
  line.setAttribute("stroke-width", "2.5");
  svg.appendChild(line);

  [0, ...fc.points.map((p) => p.days)].forEach((d) => {
    const g = document.createElementNS(ns, "g");
    const l = document.createElementNS(ns, "line");
    l.setAttribute("x1", X(d)); l.setAttribute("y1", T);
    l.setAttribute("x2", X(d)); l.setAttribute("y2", H - B);
    l.setAttribute("stroke", "#e4e9f0"); l.setAttribute("stroke-dasharray", "3 3");
    g.appendChild(l);
    const t = document.createElementNS(ns, "text");
    t.setAttribute("x", X(d)); t.setAttribute("y", H - 12);
    t.setAttribute("text-anchor", "middle"); t.setAttribute("font-size", "11");
    t.setAttribute("fill", "#6b7a8c");
    t.textContent = d === 0 ? "今天" : d / 30 + "个月";
    g.appendChild(t);
    svg.appendChild(g);
  });
  container.appendChild(svg);
}

function salesChart(container, sales) {
  container.innerHTML = "";
  const s = sales.filter((x) => x.price > 0).sort((a, b) => a.sold_at.localeCompare(b.sold_at));
  if (s.length < 2) {
    container.innerHTML = `<p class="empty">成交记录不足（${s.length} 笔）</p>`;
    return;
  }
  const W = 620, H = 220, L = 46, R = 14, T = 14, B = 30;
  const prices = s.map((x) => x.price);
  const hi = Math.max(...prices) * 1.1, lo = Math.min(...prices) * 0.7;
  const t0 = new Date(s[0].sold_at), t1 = new Date(s[s.length - 1].sold_at);
  const span = Math.max(1, t1 - t0);
  const X = (d) => L + (new Date(d) - t0) / span * (W - L - R);
  const Y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const svg = makeSvg(W, H);
  const ns = "http://www.w3.org/2000/svg";
  s.forEach((x) => {
    const c = document.createElementNS(ns, "circle");
    c.setAttribute("cx", X(x.sold_at)); c.setAttribute("cy", Y(x.price));
    c.setAttribute("r", 4); c.setAttribute("fill", "#1f6feb"); c.setAttribute("opacity", "0.75");
    svg.appendChild(c);
  });
  const med = s.map((x) => x.price).sort((a, b) => a - b)[Math.floor(s.length / 2)];
  const ml = document.createElementNS(ns, "line");
  ml.setAttribute("x1", L); ml.setAttribute("y1", Y(med));
  ml.setAttribute("x2", W - R); ml.setAttribute("y2", Y(med));
  ml.setAttribute("stroke", "#d64545"); ml.setAttribute("stroke-dasharray", "5 4");
  svg.appendChild(ml);
  const mt = document.createElementNS(ns, "text");
  mt.setAttribute("x", L + 4); mt.setAttribute("y", Y(med) - 6);
  mt.setAttribute("font-size", "11"); mt.setAttribute("fill", "#d64545");
  mt.textContent = "中位 $" + fmt(med, 2);
  svg.appendChild(mt);
  container.appendChild(svg);
}

/* ---------- 详情 ---------- */

async function openDetail(cardId) {
  const panel = $("detail-panel");
  panel.hidden = false;
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
  $("detail-body").innerHTML = `<p class="empty">加载中…</p>`;
  try {
    const d = await getJSON(`/api/cards/${cardId}`);
    const v = d.valuation || {}, fc = d.forecast || {}, v0 = d.v0 || {};
    const fPts = fc.points || [];
    const prices = d.sales.map((s) => s.price).filter((p) => p > 0);
    const avg = prices.length ? prices.reduce((a, b) => a + b, 0) / prices.length : null;
    const sorted = [...prices].sort((a, b) => a - b);
    const median = sorted.length ? sorted[Math.floor(sorted.length / 2)] : null;
    const pred3 = fPts.find((p) => p.days === 90), pred6 = fPts.find((p) => p.days === 180),
          pred12 = fPts.find((p) => p.days === 365);
    $("detail-title").textContent = `${d.player} #${d.card_number || ""} ${d.parallel || "基卡"}`;
    $("detail-body").innerHTML = `
      <div class="detail-grid">
        <div class="dstat"><div class="k">系列</div><div class="v">${escapeHtml(d.set_name)}</div></div>
        <div class="dstat"><div class="k">球队</div><div class="v">${escapeHtml(d.club || "—")}</div></div>
        <div class="dstat"><div class="k">球员市值</div><div class="v">${eur(d.market_value_eur)}</div></div>
        <div class="dstat"><div class="k">成交均价</div><div class="v">${money(avg)}</div></div>
        <div class="dstat"><div class="k">成交中位价</div><div class="v">${money(median)}</div></div>
        <div class="dstat"><div class="k">样本</div><div class="v">${d.sales.length}</div></div>
        <div class="dstat"><div class="k">当前估值</div><div class="v">${money(v.final_price ?? v.model_price)}</div></div>
      </div>
      <div class="charts">
        <div class="chart-box"><h4>未来估价（当前 + 3 / 6 / 12 个月，阴影为置信区间）</h4><div id="fc-chart"></div></div>
        <div class="chart-box"><h4>近期成交价格</h4><div id="s-chart"></div></div>
      </div>
      <div class="method-note">
        <b>预测方法</b>：基于当前估值 ${money(fc.base_value)} 与近 180 天成交动量
        （日漂移 ${fc.daily_drift_pct == null ? "—" : fmt(fc.daily_drift_pct, 3) + "%"}，波动
        ${fc.sigma_daily_pct == null ? "—" : fmt(fc.sigma_daily_pct, 3) + "%"}）外推。
        ${pred3 ? `3 个月 ${money(pred3.value)}（${money(pred3.low)}–${money(pred3.high)}）` : ""}
        ${pred6 ? `· 6 个月 ${money(pred6.value)}（${money(pred6.low)}–${money(pred6.high)}）` : ""}
        ${pred12 ? `· 1 年 ${money(pred12.value)}（${money(pred12.low)}–${money(pred12.high)}）` : ""}。
        冷门卡（成交少）动量按 0 处理、置信带更宽。仅供参考，不构成投资建议。
      </div>
      <div class="sales-list"><h4>最近成交（${d.sales.length} 笔）</h4>
        <table><thead><tr><th>时间</th><th>价格</th><th>评级</th><th>平台</th><th>标题</th></tr></thead>
        <tbody>${d.sales.map((s) => `<tr>
          <td>${escapeHtml(String(s.sold_at).slice(0, 10))}</td>
          <td class="num">${money(s.price)}</td>
          <td>${escapeHtml(s.grade || "—")}</td>
          <td>${escapeHtml(s.platform)}</td>
          <td style="white-space:normal">${escapeHtml(s.title || "")}</td>
        </tr>`).join("")}</tbody></table>
      </div>`;
    forecastChart($("fc-chart"), fc);
    salesChart($("s-chart"), d.sales);
  } catch (e) {
    $("detail-body").innerHTML = `<p class="empty">加载失败：${escapeHtml(String(e))}</p>`;
  }
}

/* ---------- 初始化 ---------- */

async function init() {
  try {
    const ov = await getJSON("/api/overview");
    renderStats(ov.stats);
    renderTable(ov.top_cards);
    const sets = await getJSON("/api/sets");
    $("set-filter").innerHTML = `<option value="">全部系列</option>` + sets
      .map((s) => `<option value="${s.id}">${escapeHtml(s.name)}（${s.sales}）</option>`)
      .join("");
  } catch (e) {
    $("card-tbody").innerHTML = `<tr><td colspan="10" class="empty">加载失败：${escapeHtml(String(e))}</td></tr>`;
  }
}

let searchTimer = null;
$("search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    const q = $("search").value.trim();
    const set = $("set-filter").value;
    $("table-title").textContent = q ? `搜索结果：${q}` : "主流卡片 · 按成交热度排序";
    try {
      const url = `/api/cards?q=${encodeURIComponent(q)}&limit=50` +
        (set ? `&set_id=${set}` : "");
      const data = await getJSON(url);
      renderTable(data);
    } catch (e) { /* ignore */ }
  }, 250);
});
$("set-filter").addEventListener("change", () => $("search").dispatchEvent(new Event("input")));
$("detail-close").addEventListener("click", () => { $("detail-panel").hidden = true; });

init();
