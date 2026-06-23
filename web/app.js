const state = {
  data: null,
  page: "overview",
  activeMatchId: null,
  stakeAmount: 1000,
  stakeMode: "profit",
  selectedReportIds: [],
  busy: false,
};

const PAGE_LABELS = {
  overview: "总览",
  schedule: "赛程",
  review: "复盘",
  sources: "数据源",
};

const OUTCOME_LABELS = {
  home: "主胜",
  draw: "平局",
  away: "客胜",
};

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function pct(value, digits = 1) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return `${(number * 100).toFixed(digits)}%`;
}

function money(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return `${number.toFixed(0)}元`;
}

function sp(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return number.toFixed(2);
}

function dateKey(value) {
  if (!value) return "未定";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10) || "未定";
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function dateLabel(key) {
  if (key === "未定") return "时间待定";
  const [, mm, dd] = key.split("-");
  return `${mm}-${dd}`;
}

function formatTime(value) {
  if (!value) return "时间待定";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  const hh = String(date.getHours()).padStart(2, "0");
  const mi = String(date.getMinutes()).padStart(2, "0");
  return `${mm}-${dd} ${hh}:${mi} 北京时间`;
}

function formatStamp(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).replace("T", " ").slice(0, 16);
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  const hh = String(date.getHours()).padStart(2, "0");
  const mi = String(date.getMinutes()).padStart(2, "0");
  return `${mm}-${dd} ${hh}:${mi}`;
}

function normalize(value) {
  return String(value || "").replace(/\s+/g, "").toLowerCase();
}

function fixtureKey(fixture) {
  return `${normalize(fixture?.home_team)}|${normalize(fixture?.away_team)}|${dateKey(fixture?.kickoff)}`;
}

function isFinished(fixture) {
  return fixture?.status === "finished" || (fixture?.home_score != null && fixture?.away_score != null);
}

function isPendingResult(fixture) {
  const kickoff = fixture?.kickoff ? new Date(fixture.kickoff) : null;
  return !isFinished(fixture) && kickoff && !Number.isNaN(kickoff.getTime()) && kickoff.getTime() + 2 * 60 * 60 * 1000 < Date.now();
}

function isPlayableUpcoming(fixture) {
  const kickoff = fixture?.kickoff ? new Date(fixture.kickoff) : null;
  if (isFinished(fixture) || isPendingResult(fixture)) return false;
  if (!kickoff || Number.isNaN(kickoff.getTime())) return true;
  return kickoff.getTime() + 2 * 60 * 60 * 1000 >= Date.now();
}

function fixtureStatusText(fixture) {
  if (isFinished(fixture)) return "完赛";
  if (isPendingResult(fixture)) return "待补赛果";
  return "未开赛";
}

function handicapText(value, homeTeam = "主队") {
  if (value === null || value === undefined || value === "") return "让球待确认";
  const number = Number(value);
  if (!Number.isFinite(number)) return `让球 ${value}`;
  if (number < 0) return `${homeTeam}让${Math.abs(number)}球`;
  if (number > 0) return `${homeTeam}受让${number}球`;
  return "不让球";
}

function toast(message) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.hidden = false;
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => {
    el.hidden = true;
  }, 2600);
}

async function fetchJson(url, options = {}, label = "请求") {
  const response = await fetch(url, {
    cache: "no-store",
    ...options,
    headers: {
      ...(options.headers || {}),
      "X-Requested-With": "fetch",
    },
  });
  const text = await response.text();
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    throw new Error(`${label}没有返回JSON：${text.replace(/\s+/g, " ").slice(0, 90)}`);
  }
  const payload = JSON.parse(text);
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `${label}失败`);
  }
  return payload;
}

function setBusy(value) {
  state.busy = value;
  document.body.classList.toggle("is-busy", value);
  document.querySelectorAll("button").forEach((button) => {
    button.disabled = value;
  });
}

async function loadState() {
  setBusy(true);
  try {
    state.data = await fetchJson("/api/state", {}, "加载状态");
    syncSelections();
    render();
  } catch (error) {
    renderError(error);
  } finally {
    setBusy(false);
  }
}

async function postJson(url, body = {}, label = "操作") {
  setBusy(true);
  try {
    const payload = await fetchJson(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }, label);
    if (payload.state) state.data = payload.state;
    syncSelections();
    render();
    toast(payload.message || `${label}完成`);
    return payload;
  } catch (error) {
    toast(`${label}失败：${error.message}`);
    throw error;
  } finally {
    setBusy(false);
  }
}

async function refresh(matchId = null) {
  return postJson("/api/refresh", matchId ? { match_id: matchId } : {}, matchId ? "刷新当前比赛" : "刷新全部预测");
}

async function selectFixture(key, mode = "single", download = false) {
  const payload = await postJson("/api/matches/select", { fixture_key: key, mode }, mode === "next4" ? "从这场起预测4场" : "加入此场预测");
  const selected = payload.selected || [];
  if (selected.length) {
    state.activeMatchId = selected[0];
    state.page = "detail";
    syncSelections(selected);
    render();
    if (download) downloadReport(selected, mode === "single" ? "单场下注决策报告" : "未来四场下注决策报告");
  }
}

function syncSelections(preferred = null) {
  const ids = matches().map((match) => match.match_id);
  if (preferred?.length) {
    state.selectedReportIds = preferred.filter((id) => ids.includes(id));
    return;
  }
  const kept = state.selectedReportIds.filter((id) => ids.includes(id));
  state.selectedReportIds = kept.length ? kept : ids.slice(0, 4);
}

function matches() {
  return state.data?.matches || [];
}

function fixtures() {
  return state.data?.fixtures || { scheduled: [], finished: [] };
}

function predictionOf(item) {
  return item?.prediction || null;
}

function marketScenario(prediction) {
  return prediction?.scenarios?.find((row) => row.scenario === "market") || prediction?.scenarios?.[0] || null;
}

function leaderText(item) {
  const prediction = predictionOf(item);
  const summary = prediction?.summary || {};
  if (summary.main_lean) return summary.main_lean;
  const probs = marketScenario(prediction)?.probabilities || {};
  const key = ["home", "draw", "away"].sort((a, b) => Number(probs[b] || 0) - Number(probs[a] || 0))[0];
  if (key === "home") return item.home_team;
  if (key === "away") return item.away_team;
  if (key === "draw") return "平局";
  return "暂无结论";
}

function scoreText(prediction) {
  const scores = prediction?.summary?.score_group || prediction?.value_model?.top_scores?.map((row) => row.score) || marketScenario(prediction)?.top_scores?.map((row) => row.score) || [];
  return scores.slice(0, 4).join(" / ") || "比分待确认";
}

function reliability(prediction) {
  const score = Number(prediction?.data_completeness?.score ?? prediction?.summary?.data_score ?? 0);
  if (score >= 75) return { text: "数据较充分", tone: "good", score };
  if (score >= 55) return { text: "可预测但需谨慎", tone: "warn", score };
  return { text: "数据不足", tone: "bad", score };
}

function topPicks(prediction, limit = 4, includeLongshot = false) {
  const sporttery = prediction?.sporttery || {};
  const rows = [
    ...(sporttery.action_summary?.core || []),
    ...(sporttery.action_summary?.support || []),
    ...(includeLongshot ? sporttery.action_summary?.hedge || [] : []),
    ...(sporttery.candidate_pool || []),
  ];
  const seen = new Set();
  return rows
    .filter((row) => row && row.sp != null && !["不可用", "不可下单", "放弃"].includes(row.action_tier || row.decision || ""))
    .filter((row) => {
      const key = `${row.match_id}|${row.play_type}|${row.selection}|${row.sp}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .sort((a, b) => Number(b.action_score ?? 0) - Number(a.action_score ?? 0))
    .slice(0, limit);
}

function pickLabel(row) {
  if (!row) return "暂无可买项";
  return `${row.play_type} ${row.selection}@${sp(row.sp)}`;
}

function pickReason(row) {
  return row?.action_reason || row?.reason || row?.score_note || "按官方SP、模型概率和风险收益筛选";
}

function matchForFixture(fixture) {
  const home = normalize(fixture.home_team);
  const away = normalize(fixture.away_team);
  return matches().find((match) => {
    const homeNames = [match.home_team, ...(match.home_aliases || [])].map(normalize);
    const awayNames = [match.away_team, ...(match.away_aliases || [])].map(normalize);
    return homeNames.includes(home) && awayNames.includes(away);
  });
}

function scheduleRows() {
  const rows = [
    ...(fixtures().finished || []),
    ...(fixtures().scheduled || []),
  ].map((fixture) => ({ fixture, predictionMatch: matchForFixture(fixture), key: fixtureKey(fixture) }));
  const seen = new Set(rows.map((row) => row.key));
  matches().forEach((match) => {
    const key = fixtureKey(match);
    if (!seen.has(key)) rows.push({ fixture: match, predictionMatch: match, key });
  });
  return rows.sort((a, b) => String(a.fixture.kickoff || "").localeCompare(String(b.fixture.kickoff || "")));
}

function newestFinished(limit = 5) {
  return scheduleRows()
    .filter((row) => isFinished(row.fixture))
    .sort((a, b) => String(b.fixture.kickoff || "").localeCompare(String(a.fixture.kickoff || "")))
    .slice(0, limit);
}

function nearestUpcoming(limit = 8) {
  return scheduleRows()
    .filter((row) => isPlayableUpcoming(row.fixture))
    .sort((a, b) => String(a.fixture.kickoff || "").localeCompare(String(b.fixture.kickoff || "")))
    .slice(0, limit);
}

function render() {
  renderNav();
  if (state.page === "detail") return renderDetail();
  if (state.page === "schedule") return renderSchedule();
  if (state.page === "review") return renderReview();
  if (state.page === "sources") return renderSources();
  return renderOverview();
}

function renderNav() {
  const tabs = document.getElementById("tabs");
  tabs.innerHTML = Object.entries(PAGE_LABELS)
    .map(([id, label]) => `<button class="tab ${state.page === id ? "active" : ""}" data-page="${id}">${label}</button>`)
    .join("");
}

function renderOverview() {
  const content = document.getElementById("content");
  const current = matches();
  const upcoming = nearestUpcoming(8);
  const finished = newestFinished(5);
  const status = state.data?.refresh_status || {};
  content.innerHTML = `
    <section class="hero-panel">
      <div>
        <span class="eyebrow">COMMAND DESK</span>
        <h2>先看哪场能下，再看怎么下</h2>
        <p>首页只保留最重要的路径：最新完赛复盘、最近待开比赛、当前预测和报告下载。朋友打开后不需要理解模型结构，也能知道下一步点哪里。</p>
      </div>
      <div class="hero-actions">
        <button data-action="schedule-query">刷新赛程和赛果</button>
        <button class="secondary" data-action="refresh-all">刷新当前预测</button>
        <button class="secondary" data-page="schedule">赛程挂历</button>
      </div>
    </section>

    <section class="metric-row">
      ${metric("当前预测", current.length, "已加入模型的比赛")}
      ${metric("待开比赛", fixtures().scheduled?.length || 0, `首页显示最近${upcoming.length}场`)}
      ${metric("最新完赛", fixtures().finished?.length || 0, `首页显示最近${finished.length}场`)}
      ${metric("最近刷新", formatStamp(status.last_finished_at), status.last_ok === false ? "上次失败" : "自动/手动刷新状态")}
    </section>

    <section class="desk-grid">
      <div class="panel">
        <div class="panel-head">
          <div>
            <h3>最近待开比赛</h3>
            <p>从这里加入预测，或者直接从某场起预测4场。</p>
          </div>
          <button class="secondary" data-page="schedule">全部赛程</button>
        </div>
        <div class="match-list">
          ${upcoming.length ? upcoming.map(renderUpcomingRow).join("") : empty("暂无待开比赛，先刷新赛程。")}
        </div>
      </div>
      <div class="panel">
        <div class="panel-head">
          <div>
            <h3>最新完赛复盘</h3>
            <p>先看偏差，再决定下一轮是否要调权重。</p>
          </div>
          <button class="secondary" data-page="review">全部复盘</button>
        </div>
        <div class="match-list">
          ${finished.length ? finished.map(renderFinishedRow).join("") : empty("暂无完赛数据，刷新赛程后显示。")}
        </div>
      </div>
    </section>

    <section class="panel priority">
      <div class="panel-head">
        <div>
          <h3>当前四场预测</h3>
          <p>每场只给三个动作：看预测、刷新、下载报告。</p>
        </div>
        <button data-action="download-selected">下载所选报告</button>
      </div>
      <div class="current-grid">
        ${current.length ? current.map(renderPredictionCard).join("") : empty("还没有预测场次。在待开比赛中加入单场或未来4场。")}
      </div>
    </section>

    ${renderReportPanel()}
  `;
}

function metric(label, value, sub) {
  return `<div class="metric"><span>${esc(label)}</span><strong>${esc(value)}</strong><em>${esc(sub)}</em></div>`;
}

function empty(text) {
  return `<div class="empty">${esc(text)}</div>`;
}

function renderUpcomingRow(row) {
  const fixture = row.fixture;
  const match = row.predictionMatch;
  const prediction = predictionOf(match);
  const key = row.key;
  return `
    <article class="compact-card">
      <div class="compact-main">
        <span>${esc(formatTime(fixture.kickoff))}</span>
        <strong>${esc(fixture.home_team)} vs ${esc(fixture.away_team)}</strong>
        <em>${esc(fixture.stage || fixture.source || "赛程")} · ${esc(handicapText(match?.sporttery_handicap ?? fixture.sporttery_handicap, fixture.home_team))}</em>
      </div>
      ${prediction ? renderMiniDecision(match) : `<div class="card-note">还没加入预测。</div>`}
      <div class="inline-actions">
        ${prediction ? `
          <button data-open-match="${esc(match.match_id)}">看预测</button>
          <button class="secondary" data-download-report="single" data-report-match="${esc(match.match_id)}">下载</button>
        ` : `
          <button data-select-fixture="${esc(key)}" data-select-mode="single">加入预测</button>
          <button class="secondary" data-select-fixture="${esc(key)}" data-select-mode="next4">预测4场</button>
        `}
      </div>
    </article>
  `;
}

function renderFinishedRow(row) {
  const fixture = row.fixture;
  const actual = fixture.home_score == null ? "-" : `${fixture.home_score}-${fixture.away_score}`;
  const match = row.predictionMatch;
  return `
    <article class="compact-card finished">
      <div class="compact-main">
        <span>${esc(formatTime(fixture.kickoff))}</span>
        <strong>${esc(fixture.home_team)} vs ${esc(fixture.away_team)}</strong>
        <em>${esc(fixture.stage || fixture.source || "完赛")}</em>
      </div>
      <div class="score-chip">${esc(actual)}</div>
      <div class="inline-actions">
        ${match ? `<button class="secondary" data-open-match="${esc(match.match_id)}">看赛前预测</button>` : `<span class="muted">无赛前预测</span>`}
      </div>
    </article>
  `;
}

function renderPredictionCard(match) {
  const prediction = predictionOf(match);
  const market = marketScenario(prediction);
  const rel = reliability(prediction);
  const picks = topPicks(prediction, 3, true);
  const checked = state.selectedReportIds.includes(match.match_id);
  return `
    <article class="prediction-card">
      <label class="select-report"><input type="checkbox" data-report-select="${esc(match.match_id)}" ${checked ? "checked" : ""}>写入报告</label>
      <div class="card-title">
        <span>${esc(formatTime(match.kickoff))}</span>
        <h3>${esc(match.home_team)} vs ${esc(match.away_team)}</h3>
      </div>
      <div class="decision-line">${esc(leaderText(match))}</div>
      <div class="prob-row">
        <div><span>主胜</span><b>${pct(market?.probabilities?.home, 0)}</b></div>
        <div><span>平</span><b>${pct(market?.probabilities?.draw, 0)}</b></div>
        <div><span>客胜</span><b>${pct(market?.probabilities?.away, 0)}</b></div>
      </div>
      <div class="tag-line">
        <span>${esc(handicapText(prediction?.sporttery?.handicap ?? match.sporttery_handicap, match.home_team))}</span>
        <span class="${rel.tone}">${esc(rel.text)} ${rel.score || "-"}/100</span>
        <span>比分 ${esc(scoreText(prediction))}</span>
      </div>
      <div class="pick-stack">
        ${picks.length ? picks.slice(0, 3).map((row) => `<div>${esc(pickLabel(row))}<small>${esc(pickReason(row))}</small></div>`).join("") : `<div>暂无可买推荐<small>可能是SP缺失或价值不足。</small></div>`}
      </div>
      <div class="card-actions">
        <button data-open-match="${esc(match.match_id)}">查看预测详情</button>
        <button class="secondary" data-refresh="${esc(match.match_id)}">刷新</button>
        <button class="secondary" data-download-report="single" data-report-match="${esc(match.match_id)}">下载</button>
      </div>
    </article>
  `;
}

function renderMiniDecision(match) {
  const prediction = predictionOf(match);
  const market = marketScenario(prediction);
  return `
    <div class="mini-decision">
      <b>${esc(leaderText(match))}</b>
      <span>主/平/客 ${pct(market?.probabilities?.home, 0)} / ${pct(market?.probabilities?.draw, 0)} / ${pct(market?.probabilities?.away, 0)}</span>
    </div>
  `;
}

function renderReportPanel() {
  const selected = new Set(state.selectedReportIds);
  const current = matches();
  return `
    <section class="panel report-panel">
      <div class="panel-head">
        <div>
          <h3>报告下载</h3>
          <p>勾选场次后下载 HTML 报告，浏览器打开后可打印为 PDF。</p>
        </div>
        <div class="inline-actions">
          <button data-action="download-selected">下载所选</button>
          <button class="secondary" data-action="download-all">下载当前四场</button>
        </div>
      </div>
      <div class="report-grid">
        ${current.length ? current.map((match) => `
          <label>
            <input type="checkbox" data-report-select="${esc(match.match_id)}" ${selected.has(match.match_id) ? "checked" : ""}>
            <span>${esc(match.home_team)} vs ${esc(match.away_team)}</span>
          </label>
        `).join("") : empty("暂无可下载场次")}
      </div>
    </section>
  `;
}

function renderSchedule() {
  const content = document.getElementById("content");
  const rows = scheduleRows();
  const groups = new Map();
  rows.forEach((row) => {
    const status = isFinished(row.fixture) ? "finished" : isPendingResult(row.fixture) ? "pending" : "scheduled";
    const key = `${dateKey(row.fixture.kickoff)}|${status}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  });
  content.innerHTML = `
    <section class="page-head">
      <div>
        <h2>赛程挂历</h2>
        <p>按北京时间分组。未预测场次可以直接加入；已预测场次可以进入详情或下载报告。</p>
      </div>
      <button data-action="schedule-query">刷新赛程和赛果</button>
    </section>
    <section class="calendar-layout">
      ${[...groups.entries()].slice(0, 48).map(([key, items]) => {
        const [day, status] = key.split("|");
        return `
          <div class="day-column">
            <div class="day-head"><strong>${esc(dateLabel(day))}</strong><span>${esc(status === "finished" ? "完赛" : status === "pending" ? "待补赛果" : "待开")} · ${items.length}场</span></div>
            ${items.map((row) => renderScheduleItem(row)).join("")}
          </div>
        `;
      }).join("") || empty("暂无赛程")}
    </section>
  `;
}

function renderScheduleItem(row) {
  const fixture = row.fixture;
  const match = row.predictionMatch;
  const key = row.key;
  return `
    <article class="schedule-item ${isFinished(fixture) ? "done" : ""}">
      <span>${esc(formatTime(fixture.kickoff))}</span>
      <strong>${esc(fixture.home_team)} vs ${esc(fixture.away_team)}</strong>
      <em>${esc(fixture.stage || fixture.source || fixtureStatusText(fixture))}</em>
      ${isFinished(fixture) ? `<b>${fixture.home_score ?? "-"}-${fixture.away_score ?? "-"}</b>` : ""}
      <div class="inline-actions">
        ${match ? `
          <button data-open-match="${esc(match.match_id)}">详情</button>
          <button class="secondary" data-refresh="${esc(match.match_id)}">刷新</button>
        ` : `
          <button data-select-fixture="${esc(key)}" data-select-mode="single">加入</button>
          <button class="secondary" data-select-fixture="${esc(key)}" data-select-mode="next4">预测4场</button>
        `}
      </div>
    </article>
  `;
}

function renderReview() {
  const content = document.getElementById("content");
  const summary = state.data?.backtest_summary || {};
  const finished = newestFinished(40);
  content.innerHTML = `
    <section class="page-head">
      <div>
        <h2>赛后复盘</h2>
        <p>把完赛比分、预测方向、Brier、Log Loss 和 ROI 放在一起，方便看模型哪里偏。</p>
      </div>
      <div class="inline-actions">
        <button data-action="archive">归档当前预测</button>
        <button class="secondary" data-action="backtest">运行回测</button>
      </div>
    </section>
    <section class="metric-row">
      ${metric("回测样本", summary.count || 0, "需要赛前归档")}
      ${metric("Top1命中", summary.top1_accuracy == null ? "-" : pct(summary.top1_accuracy), "方向第一选择")}
      ${metric("Top2命中", summary.top2_accuracy == null ? "-" : pct(summary.top2_accuracy), "前二方向覆盖")}
      ${metric("平均ROI", summary.avg_roi == null ? "-" : pct(summary.avg_roi), "单项回测参考")}
    </section>
    <section class="panel">
      <h3>最新完赛</h3>
      <div class="match-list">${finished.length ? finished.map(renderFinishedRow).join("") : empty("暂无完赛。")}</div>
    </section>
    <section class="panel">
      <h3>调参提醒</h3>
      ${(summary.tuning_suggestions || []).length ? `<ul>${summary.tuning_suggestions.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : empty("暂无建议。")}
    </section>
  `;
}

function renderSources() {
  const content = document.getElementById("content");
  const sources = state.data?.sources || [];
  const health = state.data?.source_health || {};
  const deployment = state.data?.deployment || {};
  content.innerHTML = `
    <section class="page-head">
      <div>
        <h2>数据源状态</h2>
        <p>这里不是给朋友看的核心页，是给你判断“为什么数据没抓到”的排查页。</p>
      </div>
      <button data-action="schedule-query">刷新数据源</button>
    </section>
    <section class="panel">
      <h3>抓取概况</h3>
      <div class="metric-row">
        ${metric("体彩", deployment.sporttery_meta?.count ?? "-", deployment.sporttery_meta?.error || "无错误")}
        ${metric("500", deployment.fivehundred_meta?.count ?? "-", deployment.fivehundred_meta?.error || "无错误")}
        ${metric("爱彩", deployment.aicai_meta?.count ?? "-", deployment.aicai_meta?.error || "无错误")}
        ${metric("刷新", state.data?.refresh_status?.last_ok === false ? "失败" : "正常", formatStamp(state.data?.refresh_status?.last_finished_at))}
      </div>
    </section>
    <section class="panel">
      <h3>源列表</h3>
      <table>
        <thead><tr><th>数据源</th><th>类型</th><th>状态</th><th>成功/失败</th><th>最近错误</th></tr></thead>
        <tbody>
          ${sources.map((source) => {
            const item = health[source.source_id] || {};
            return `<tr>
              <td><strong>${esc(source.name || source.source_id)}</strong><br><span>${esc(source.url || source.source_id)}</span></td>
              <td>${esc(source.type || "-")}</td>
              <td>${source.enabled === false ? "停用" : "启用"}</td>
              <td>${item.success_count || 0}/${item.failure_count || 0}</td>
              <td>${esc(item.last_error || "-")}</td>
            </tr>`;
          }).join("") || `<tr><td colspan="5">暂无数据源配置。</td></tr>`}
        </tbody>
      </table>
    </section>
  `;
}

function renderDetail() {
  const match = matches().find((item) => item.match_id === state.activeMatchId) || matches()[0];
  if (!match) {
    state.page = "overview";
    return renderOverview();
  }
  state.activeMatchId = match.match_id;
  const prediction = predictionOf(match);
  const market = marketScenario(prediction);
  const rel = reliability(prediction);
  const picks = topPicks(prediction, 8, true);
  const content = document.getElementById("content");
  content.innerHTML = `
    <section class="detail-hero">
      <div>
        <button class="ghost" data-page="overview">返回总览</button>
        <span class="eyebrow">MATCH DECISION</span>
        <h2>${esc(match.home_team)} vs ${esc(match.away_team)}</h2>
        <p>${esc(formatTime(match.kickoff))} · ${esc(match.stage || "世界杯")} · ${esc(handicapText(prediction?.sporttery?.handicap ?? match.sporttery_handicap, match.home_team))}</p>
      </div>
      <div class="hero-actions">
        <button data-refresh="${esc(match.match_id)}">刷新本场</button>
        <button class="secondary" data-download-report="single" data-report-match="${esc(match.match_id)}">下载本场报告</button>
      </div>
    </section>
    <section class="detail-grid">
      <div class="panel">
        <h3>主判断</h3>
        <div class="big-verdict">${esc(leaderText(match))}</div>
        <div class="prob-row large">
          <div><span>主胜</span><b>${pct(market?.probabilities?.home)}</b></div>
          <div><span>平局</span><b>${pct(market?.probabilities?.draw)}</b></div>
          <div><span>客胜</span><b>${pct(market?.probabilities?.away)}</b></div>
        </div>
        <p class="basis">${esc(prediction?.summary?.reference || shortBasis(match))}</p>
        <div class="tag-line">
          <span class="${rel.tone}">${esc(rel.text)} ${rel.score || "-"}/100</span>
          <span>比分池 ${esc(scoreText(prediction))}</span>
          <span>爆冷 ${esc(prediction?.summary?.upset_level || "-")}</span>
        </div>
      </div>
      <div class="panel">
        <h3>优先可买项</h3>
        <div class="pick-stack">${picks.length ? picks.map(renderPickLine).join("") : empty("暂无可买项。")}</div>
      </div>
    </section>
    <section class="panel">
      <div class="panel-head">
        <div>
          <h3>资金测算</h3>
          <p>输入总金额，按不同目标拆分。让球胜平负是否支持单关，以体彩最终页面为准。</p>
        </div>
        <label class="stake-input">金额 <input type="number" min="2" step="2" value="${state.stakeAmount}" data-stake></label>
      </div>
      <div class="mode-tabs">
        ${[
          ["safe", "保守"],
          ["profit", "赚钱优先"],
          ["aggressive", "激进"],
          ["longshot", "以小博大"],
        ].map(([id, label]) => `<button class="${state.stakeMode === id ? "active" : "secondary"}" data-mode="${id}">${label}</button>`).join("")}
      </div>
      ${renderStakePlan(prediction)}
    </section>
    <section class="detail-grid">
      <div class="panel">
        <h3>官方/500可售字段</h3>
        ${renderOddsTable(match, prediction)}
      </div>
      <div class="panel">
        <h3>支线风险提醒</h3>
        ${renderSideLine(prediction)}
      </div>
    </section>
    <section class="panel">
      <h3>放弃项</h3>
      ${renderAbandon(prediction)}
    </section>
  `;
}

function shortBasis(match) {
  const prediction = predictionOf(match);
  const market = marketScenario(prediction);
  return `${leaderText(match)}；主/平/客 ${pct(market?.probabilities?.home, 0)} / ${pct(market?.probabilities?.draw, 0)} / ${pct(market?.probabilities?.away, 0)}；比分参考 ${scoreText(prediction)}。`;
}

function renderPickLine(row) {
  return `
    <div class="pick-line">
      <strong>${esc(pickLabel(row))}</strong>
      <span>模型 ${pct(row.model_prob)} · EV ${row.ev == null ? "-" : pct(row.ev)} · 风险 ${row.risk_score ?? "-"}</span>
      <em>${esc(pickReason(row))}</em>
    </div>
  `;
}

function renderStakePlan(prediction) {
  const picks = topPicks(prediction, 12, state.stakeMode !== "safe");
  const filtered = picks.filter((row) => {
    if (state.stakeMode === "safe") return !["比分", "半全场"].includes(row.play_type);
    if (state.stakeMode === "profit") return !["比分"].includes(row.play_type) || row.action_tier === "主推";
    if (state.stakeMode === "aggressive") return true;
    return ["比分", "半全场", "总进球"].includes(row.play_type);
  }).slice(0, state.stakeMode === "longshot" ? 6 : 5);
  if (!filtered.length) return empty("当前模式没有合适候选。");
  const weights = filtered.map((row, index) => {
    if (state.stakeMode === "longshot") return 1;
    if (index === 0) return 3;
    if (row.action_tier === "主推") return 2;
    return 1;
  });
  const stakes = splitStake(state.stakeAmount, weights);
  return `
    <table>
      <thead><tr><th>玩法</th><th>选项</th><th>投入</th><th>SP</th><th>命中返奖</th><th>说明</th></tr></thead>
      <tbody>
        ${filtered.map((row, index) => {
          const stake = stakes[index] || 0;
          return `<tr>
            <td>${esc(row.play_type)}</td>
            <td><strong>${esc(row.selection)}</strong></td>
            <td>${money(stake)}</td>
            <td>${sp(row.sp)}</td>
            <td>${money(stake * Number(row.sp || 0))}</td>
            <td>${esc(pickReason(row))}</td>
          </tr>`;
        }).join("")}
      </tbody>
    </table>
  `;
}

function splitStake(total, weights) {
  const amount = Math.max(2, Math.floor(Number(total || 0) / 2) * 2);
  const sum = weights.reduce((a, b) => a + b, 0) || 1;
  const raw = weights.map((w) => Math.floor((amount * w / sum) / 2) * 2);
  let used = raw.reduce((a, b) => a + b, 0);
  let index = 0;
  while (used + 2 <= amount && raw.length) {
    raw[index % raw.length] += 2;
    used += 2;
    index += 1;
  }
  return raw;
}

function renderOddsTable(match, prediction) {
  const sourceRows = match.odds_summary || [];
  const optionRows = prediction?.sporttery?.options || [];
  const rows = sourceRows.length ? sourceRows : groupOptions(optionRows);
  if (!rows.length) return empty("暂无官方SP。");
  return `
    <table>
      <thead><tr><th>玩法</th><th>选项</th></tr></thead>
      <tbody>
        ${rows.map((row) => `<tr><td>${esc(row.play)}</td><td>${(row.options || []).map((item) => `${esc(item.name)}@${sp(item.sp)}`).join(" / ")}</td></tr>`).join("")}
      </tbody>
    </table>
  `;
}

function groupOptions(options) {
  const groups = new Map();
  options.filter((row) => row.sp != null).forEach((row) => {
    if (!groups.has(row.play_type)) groups.set(row.play_type, []);
    groups.get(row.play_type).push({ name: row.selection, sp: row.sp });
  });
  return [...groups.entries()].map(([play, opts]) => ({ play, options: opts.slice(0, 8) }));
}

function renderSideLine(prediction) {
  const folk = prediction?.sporttery?.folk_parallel || prediction?.summary?.folk_parallel || {};
  return `
    <div class="side-box">
      <strong>${esc(folk.side_prediction || "支线未录入明确方向")}</strong>
      <p>${esc(folk.model_relation || folk.action_hint || "支线只能作为风险标签，不能直接替代主线模型。")}</p>
      <em>${esc(folk.betting_advice || "如果支线与主线冲突，只进入防冷或降仓，不直接反买。")}</em>
    </div>
  `;
}

function renderAbandon(prediction) {
  const rows = prediction?.sporttery?.abandon_list || [];
  if (!rows.length) return empty("暂无明确放弃项。");
  return `
    <table>
      <thead><tr><th>玩法</th><th>选项</th><th>原因</th></tr></thead>
      <tbody>
        ${rows.slice(0, 12).map((row) => `<tr><td>${esc(row.play_type)}</td><td>${esc(row.selection)}</td><td>${esc(row.reason || "风险收益不匹配")}</td></tr>`).join("")}
      </tbody>
    </table>
  `;
}

function renderError(error) {
  document.getElementById("tabs").innerHTML = "";
  document.getElementById("content").innerHTML = `
    <section class="panel error-panel">
      <h2>页面加载失败</h2>
      <p>${esc(error.message || error)}</p>
      <button data-action="reload">重新读取</button>
    </section>
  `;
}

function downloadReport(ids = state.selectedReportIds, title = "世界杯下注决策报告") {
  const idSet = new Set(ids || []);
  const rows = matches().filter((match) => !idSet.size || idSet.has(match.match_id));
  if (!rows.length) {
    toast("没有可下载的场次");
    return;
  }
  const html = buildReportHtml(rows, title);
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
  a.href = url;
  a.download = `${title}_${stamp}.html`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  toast(`已生成${rows.length}场报告`);
}

function buildReportHtml(rows, title) {
  const generated = new Date().toLocaleString("zh-CN", { hour12: false });
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>${esc(title)}</title>
  <style>
    body{margin:0;background:#eef3f8;color:#0f172a;font:14px/1.6 "Microsoft YaHei",Arial,sans-serif}.page{width:1120px;margin:0 auto;padding:28px}.cover{background:#0b1f3a;color:#fff;border-radius:8px;padding:26px;margin-bottom:16px}.cover h1{margin:0 0 8px;font-size:28px}.block{background:#fff;border:1px solid #cbd5e1;border-radius:8px;padding:16px;margin:14px 0;break-inside:avoid}table{width:100%;border-collapse:collapse}th,td{border:1px solid #cbd5e1;padding:8px;text-align:left;vertical-align:top}th{background:#10213a;color:#fff}.muted{color:#64748b}.tag{display:inline-block;border-radius:999px;padding:2px 8px;background:#e0f2fe;color:#075985;font-weight:700}@media print{body{background:#fff}.page{width:auto;padding:0}.block,.cover{break-inside:avoid}}
  </style></head><body><main class="page">
  <section class="cover"><h1>${esc(title)}</h1><p>生成时间：${esc(generated)} · 90分钟口径 · 出票前以体彩最终让球、SP和停售时间为准</p></section>
  <section class="block"><h2>一、总览</h2>${reportOverview(rows)}</section>
  <section class="block"><h2>二、下单优先项</h2>${reportPicks(rows)}</section>
  <section class="block"><h2>三、场次详情</h2>${rows.map(reportMatchBlock).join("")}</section>
  <section class="block"><h2>四、提醒</h2><p>本报告是参考，不保证盈利。若临场让球、SP、首发或停售时间变化，必须重新刷新预测。</p></section>
  </main></body></html>`;
}

function reportOverview(rows) {
  return `<table><thead><tr><th>时间</th><th>比赛</th><th>让球</th><th>主判断</th><th>比分参考</th></tr></thead><tbody>${rows.map((match) => {
    const prediction = predictionOf(match);
    return `<tr><td>${esc(formatTime(match.kickoff))}</td><td>${esc(match.home_team)} vs ${esc(match.away_team)}</td><td>${esc(handicapText(prediction?.sporttery?.handicap ?? match.sporttery_handicap, match.home_team))}</td><td>${esc(leaderText(match))}</td><td>${esc(scoreText(prediction))}</td></tr>`;
  }).join("")}</tbody></table>`;
}

function reportPicks(rows) {
  const picks = rows.flatMap((match) => topPicks(predictionOf(match), 4, true).map((row) => ({ match, row })));
  if (!picks.length) return "<p>暂无可买推荐。</p>";
  return `<table><thead><tr><th>比赛</th><th>玩法</th><th>选项/SP</th><th>理由</th></tr></thead><tbody>${picks.map(({ match, row }) => `<tr><td>${esc(match.home_team)} vs ${esc(match.away_team)}</td><td>${esc(row.play_type)}</td><td><strong>${esc(row.selection)} @ ${sp(row.sp)}</strong></td><td>${esc(pickReason(row))}</td></tr>`).join("")}</tbody></table>`;
}

function reportMatchBlock(match) {
  const prediction = predictionOf(match);
  return `<div class="block"><h3>${esc(match.home_team)} vs ${esc(match.away_team)}</h3><p><strong>判断：</strong>${esc(leaderText(match))}</p><p><strong>依据：</strong>${esc(prediction?.summary?.reference || shortBasis(match))}</p><p><strong>支线：</strong>${esc(prediction?.summary?.folk_parallel?.side_prediction || "未录入")}</p></div>`;
}

document.getElementById("refreshAll").addEventListener("click", () => refresh());
document.getElementById("reloadState").addEventListener("click", () => loadState());

document.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;

  const page = button.dataset.page;
  if (page) {
    state.page = page;
    state.activeMatchId = null;
    render();
    return;
  }

  const openMatch = button.dataset.openMatch;
  if (openMatch) {
    state.page = "detail";
    state.activeMatchId = openMatch;
    render();
    return;
  }

  const refreshId = button.dataset.refresh;
  if (refreshId) {
    refresh(refreshId);
    return;
  }

  const selectKey = button.dataset.selectFixture;
  if (selectKey) {
    selectFixture(selectKey, button.dataset.selectMode || "single", button.dataset.downloadAfter === "true");
    return;
  }

  const reportScope = button.dataset.downloadReport;
  if (reportScope === "single") {
    downloadReport([button.dataset.reportMatch], "单场下注决策报告");
    return;
  }

  const action = button.dataset.action;
  if (action === "reload") loadState();
  if (action === "refresh-all") refresh();
  if (action === "schedule-query") postJson("/api/schedule/query", {}, "刷新赛程和赛果");
  if (action === "archive") postJson("/api/predictions/archive", {}, "归档当前预测");
  if (action === "backtest") postJson("/api/backtest/run", {}, "运行回测");
  if (action === "download-selected") downloadReport(state.selectedReportIds, "所选场次下注决策报告");
  if (action === "download-all") downloadReport(matches().slice(0, 4).map((match) => match.match_id), "当前四场下注决策报告");
});

document.addEventListener("change", (event) => {
  const report = event.target.closest("input[data-report-select]");
  if (report) {
    const selected = new Set(state.selectedReportIds);
    if (report.checked) selected.add(report.dataset.reportSelect);
    else selected.delete(report.dataset.reportSelect);
    state.selectedReportIds = [...selected];
    return;
  }
  const stake = event.target.closest("input[data-stake]");
  if (stake) {
    state.stakeAmount = Math.max(2, Number(stake.value || 2));
    renderDetail();
  }
});

document.addEventListener("input", (event) => {
  const stake = event.target.closest("input[data-stake]");
  if (stake) state.stakeAmount = Math.max(2, Number(stake.value || 2));
});

document.addEventListener("click", (event) => {
  const mode = event.target.closest("button[data-mode]");
  if (!mode) return;
  state.stakeMode = mode.dataset.mode;
  renderDetail();
});

loadState();
