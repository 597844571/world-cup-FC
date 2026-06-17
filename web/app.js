const state = {
  data: null,
  active: "overview",
  bettingMode: "standard",
  stakeAmount: 100,
};

const labels = {
  home: "主胜",
  draw: "平局",
  away: "客胜",
};

const colors = {
  home: "#2563eb",
  draw: "#b45309",
  away: "#16a34a",
};

const RULES_VERSION = "规则 v2.2：官方体彩SP + 去除抽水概率 + 实力排名 + 支线观察";

async function readJsonResponse(response, actionName = "请求") {
  const contentType = response.headers.get("content-type") || "";
  const text = await response.text();
  if (!contentType.includes("application/json")) {
    const preview = text.replace(/\s+/g, " ").slice(0, 90);
    throw new Error(`${actionName}接口没有返回JSON，可能是部署路由缺失或服务端报错：${preview || response.status}`);
  }
  let payload;
  try {
    payload = JSON.parse(text);
  } catch (error) {
    throw new Error(`${actionName}接口JSON解析失败：${error.message || error}`);
  }
  if (!response.ok) {
    throw new Error(payload.error || `${actionName}失败，HTTP ${response.status}`);
  }
  return payload;
}

function pct(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${(value * 100).toFixed(digits)}%`;
}

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function loadState() {
  const response = await fetch("/api/state");
  state.data = await readJsonResponse(response, "加载状态");
  render();
}

async function refresh(matchId = null) {
  setBusy(true);
  try {
    const response = await fetch("/api/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(matchId ? { match_id: matchId } : {}),
    });
    const payload = await readJsonResponse(response, "刷新预测");
    state.data = payload.state;
    showToast(payload.message || (matchId ? "当前比赛已刷新" : "全部比赛已刷新"));
    render();
  } finally {
    setBusy(false);
  }
}

async function postAction(url, message) {
  setBusy(true);
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const payload = await readJsonResponse(response, message || "操作");
    state.data = payload.state || state.data;
    showToast(payload.message || message);
    render();
  } finally {
    setBusy(false);
  }
}

async function selectFixture(fixtureKey, mode = "single") {
  setBusy(true);
  showToast(mode === "next4" ? "正在从这场起生成4场预测..." : "正在加入此场预测...");
  try {
    const response = await fetch("/api/matches/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fixture_key: fixtureKey, mode }),
    });
    const payload = await readJsonResponse(response, "加入预测");
    if (payload.ok === false) {
      showToast(payload.error || "加入预测失败");
      return;
    }
    state.data = payload.state;
    const first = payload.selected?.[0];
    state.active = first || "overview";
    showToast(payload.message || "已加入预测并刷新");
    render();
  } catch (error) {
    showToast(`加入预测失败：${error.message || error}`);
  } finally {
    setBusy(false);
  }
}

function setBusy(isBusy) {
  document.querySelectorAll("button").forEach((button) => {
    if (button.id === "refreshAll" || button.id === "reloadState" || button.dataset.refresh || button.dataset.selectFixture) {
      button.disabled = isBusy;
    }
  });
}

function showToast(message) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.hidden = false;
  setTimeout(() => {
    toast.hidden = true;
  }, 2200);
}

function render() {
  renderTabs();
  if (state.active === "overview") {
    renderOverviewV2();
    return;
  }
  if (state.active === "calendar") {
    renderCalendar();
    return;
  }
  if (state.active.startsWith("day:")) {
    renderScheduleDay(state.active);
    return;
  }
  if (state.active === "schedule") {
    renderScheduleBacktest();
    return;
  }
  const match = state.data?.matches?.find((item) => item.match_id === state.active);
  if (!match) {
    state.active = "overview";
    renderOverview();
    return;
  }
  renderMatch(match);
}

function renderTabs() {
  const tabs = document.getElementById("tabs");
  const scheduleTabs = buildScheduleTabs();
  const buttons = [
    `<button class="tab ${state.active === "overview" ? "active" : ""}" data-tab="overview">总览</button>`,
    `<button class="tab ${state.active === "calendar" ? "active" : ""}" data-tab="calendar">赛程挂历</button>`,
    ...scheduleTabs.map((tab) => {
      const active = state.active === tab.id ? "active" : "";
      return `<button class="tab schedule-tab ${active}" data-tab="${esc(tab.id)}">${esc(tab.label)}<span>${tab.count}</span></button>`;
    }),
    `<button class="tab ${state.active === "schedule" ? "active" : ""}" data-tab="schedule">回测</button>`,
  ];
  tabs.innerHTML = buttons.join("");
  tabs.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      state.active = button.dataset.tab;
      render();
    });
  });
}

function badge(text, level = "") {
  let klass = "badge";
  if (["低", "一致", "中高"].includes(text) || level === "green") klass += " green";
  if (["中低", "轻微分歧", "明显分歧"].includes(text) || level === "amber") klass += " amber";
  if (["高", "高分歧"].includes(text) || level === "red") klass += " red";
  if (level === "blue") klass += " blue";
  return `<span class="${klass}">${esc(text)}</span>`;
}

function formatKickoff(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  const hh = String(date.getHours()).padStart(2, "0");
  const mi = String(date.getMinutes()).padStart(2, "0");
  return `${mm}-${dd} ${hh}:${mi} 北京时间`;
}

function fifaRankText(item) {
  const source = item?.prediction?.match || item || {};
  const rank = source?.fifa_ranking || source?.fifa_rank || {};
  const home = rank.home ?? rank.home_rank ?? item?.home_fifa_rank;
  const away = rank.away ?? rank.away_rank ?? item?.away_fifa_rank;
  if (!home && !away) return "FIFA排名待补";
  return `FIFA排名：${item.home_team || source.home_team || "主队"} 第${home ?? "-"}，${item.away_team || source.away_team || "客队"} 第${away ?? "-"}`;
}

function bjtDateKey(value) {
  if (!value) return "未定";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10) || "未定";
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function dayLabel(dateKey) {
  if (dateKey === "未定") return "时间未定";
  const [, mm, dd] = dateKey.split("-");
  return `${mm}-${dd}`;
}

function fullKickoff(value) {
  if (!value) return "时间待定";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  const hh = String(date.getHours()).padStart(2, "0");
  const mi = String(date.getMinutes()).padStart(2, "0");
  return `${mm}月${dd}日 ${hh}:${mi} 北京时间`;
}

function calendarKickoff(fixture) {
  if (!fixture?.kickoff) return "时间待定";
  const source = String(fixture.source || "");
  const kickoff = String(fixture.kickoff || "");
  const isDateOnlyPublic = !source.includes("中国体彩") && /T00:00(?::00)?(?:$|[+-])/.test(kickoff);
  if (isDateOnlyPublic) {
    const date = new Date(fixture.kickoff);
    if (Number.isNaN(date.getTime())) return `${kickoff.slice(0, 10)} 时间待核对`;
    const mm = String(date.getMonth() + 1).padStart(2, "0");
    const dd = String(date.getDate()).padStart(2, "0");
    return `${mm}月${dd}日 当日时间待核对`;
  }
  return fullKickoff(fixture.kickoff);
}

function normalizeName(value) {
  return String(value || "").replace(/\s+/g, "").toLowerCase();
}

function fixtureStatus(fixture) {
  if (fixture?.status === "finished" || (fixture?.home_score != null && fixture?.away_score != null)) return "finished";
  const kickoff = fixture?.kickoff ? new Date(fixture.kickoff) : null;
  if (kickoff && !Number.isNaN(kickoff.getTime()) && kickoff.getTime() + 2 * 60 * 60 * 1000 < Date.now()) {
    return "pending_result";
  }
  return "scheduled";
}

function matchKey(home, away, kickoff) {
  return `${normalizeName(home)}|${normalizeName(away)}|${bjtDateKey(kickoff)}`;
}

function findPredictionForFixture(fixture) {
  const matches = state.data?.matches || [];
  const exact = matches.find((match) => match.match_id === fixture.match_id);
  if (exact) return exact;
  const fixtureHome = normalizeName(fixture.home_team);
  const fixtureAway = normalizeName(fixture.away_team);
  return matches.find((match) => {
    const homeNames = [match.home_team, ...(match.home_aliases || [])].map(normalizeName);
    const awayNames = [match.away_team, ...(match.away_aliases || [])].map(normalizeName);
    return homeNames.includes(fixtureHome) && awayNames.includes(fixtureAway);
  });
}

function backtestsForMatch(matchId) {
  return (state.data?.backtests || []).filter((row) => row.match_id === matchId);
}

function latestBacktest(rows) {
  if (!rows.length) return null;
  const market = rows.find((row) => row.scenario === "market");
  return market || rows[0];
}

function resultName(key) {
  if (key === "home") return "主胜";
  if (key === "draw") return "平局";
  if (key === "away") return "客胜";
  return "-";
}

function actualResult(fixture) {
  if (fixture.home_score == null || fixture.away_score == null) return null;
  if (fixture.home_score > fixture.away_score) return "home";
  if (fixture.home_score < fixture.away_score) return "away";
  return "draw";
}

function scheduleRows() {
  const fixtureRows = [
    ...(state.data?.fixtures?.finished || []),
    ...(state.data?.fixtures?.scheduled || []),
  ].map((fixture) => {
    const prediction = findPredictionForFixture(fixture);
    const matchId = prediction?.match_id || fixture.match_id;
    return {
      type: "fixture",
      fixture,
      prediction,
      backtests: backtestsForMatch(matchId),
      key: matchKey(fixture.home_team, fixture.away_team, fixture.kickoff),
    };
  });
  const seen = new Set(fixtureRows.map((row) => row.key));
  const predictionOnlyRows = (state.data?.matches || [])
    .filter((match) => !seen.has(matchKey(match.home_team, match.away_team, match.kickoff)))
    .map((match) => ({
      type: "prediction",
      fixture: {
        match_id: match.match_id,
        home_team: match.home_team,
        away_team: match.away_team,
        kickoff: match.kickoff,
        stage: match.stage,
        status: fixtureStatus(match),
        source: "本地预测配置",
      },
      prediction: match,
      backtests: backtestsForMatch(match.match_id),
      key: matchKey(match.home_team, match.away_team, match.kickoff),
    }));
  return [...fixtureRows, ...predictionOnlyRows].sort((a, b) => {
    const officialDelta = Number(isPrimaryScheduleRow(b)) - Number(isPrimaryScheduleRow(a));
    if (officialDelta) return officialDelta;
    return String(a.fixture.kickoff || "").localeCompare(String(b.fixture.kickoff || ""));
  });
}

function isPrimaryScheduleRow(row) {
  const source = String(row.fixture?.source || "");
  return row.type === "prediction" || source.includes("中国体彩") || fixtureStatus(row.fixture) === "finished";
}

function buildScheduleTabs() {
  const groups = new Map();
  scheduleRows().filter(isPrimaryScheduleRow).forEach((row) => {
    const status = fixtureStatus(row.fixture) === "finished" ? "finished" : "scheduled";
    const dateKey = bjtDateKey(row.fixture.kickoff);
    const id = `day:${dateKey}:${status}`;
    const current = groups.get(id) || { id, dateKey, status, count: 0 };
    current.count += 1;
    groups.set(id, current);
  });
  return [...groups.values()]
    .sort((a, b) => `${a.dateKey}:${a.status === "finished" ? 0 : 1}`.localeCompare(`${b.dateKey}:${b.status === "finished" ? 0 : 1}`))
    .slice(0, 10)
    .map((group) => ({
      ...group,
      label: `${dayLabel(group.dateKey)} ${group.status === "finished" ? "完赛" : "赛程"}`,
    }));
}

function calendarGroups() {
  const rows = scheduleRows()
    .filter((row) => fixtureStatus(row.fixture) === "scheduled")
    .sort((a, b) => String(a.fixture.kickoff || "").localeCompare(String(b.fixture.kickoff || "")));
  const groups = new Map();
  rows.forEach((row) => {
    const dateKey = bjtDateKey(row.fixture.kickoff);
    if (!groups.has(dateKey)) groups.set(dateKey, []);
    groups.get(dateKey).push(row);
  });
  return [...groups.entries()].map(([dateKey, items]) => ({ dateKey, items }));
}

function decisionTone(row) {
  const decision = row?.decision || row?.action || "";
  if (decision.includes("可小注")) return "primary";
  if (decision.includes("高风险")) return "risky";
  if (decision.includes("观察") || decision.includes("备选")) return "watch";
  return "watch";
}

function readablePick(row) {
  if (!row) return "等待官方SP";
  const sp = row.sp == null ? `合理线 ${minBuySp(row)}` : `@${Number(row.sp).toFixed(2)}`;
  return `${row.play_type}：${row.selection} ${sp}`;
}

function handicapText(value) {
  if (value === null || value === undefined || value === "") return "未抓到体彩让球";
  const num = Number(value);
  if (Number.isNaN(num)) return `体彩让球 ${value}`;
  if (num > 0) return `主队受让${num}球`;
  if (num < 0) return `主队让${Math.abs(num)}球`;
  return "不让球";
}

function marketScenario(prediction) {
  return prediction?.scenarios?.find((s) => s.scenario === "market") || prediction?.scenarios?.[0];
}

function conclusionText(item, prediction) {
  const lean = String(prediction?.summary?.main_lean || "").trim();
  if (!lean) return "暂无明确主方向";
  if (lean === item.home_team) return `倾向${item.home_team}胜`;
  if (lean === item.away_team) return `倾向${item.away_team}胜`;
  if (lean.includes("平")) return lean;
  return lean;
}

function shortBasisText(item, prediction) {
  const scenario = marketScenario(prediction);
  const probs = scenario?.probabilities || {};
  const sporttery = prediction?.sporttery || {};
  const hText = handicapText(sporttery.handicap ?? item.sporttery_handicap);
  return `${conclusionText(item, prediction)}；${hText}；胜平负 ${pct(probs.home, 0)}/${pct(probs.draw, 0)}/${pct(probs.away, 0)}；${scoreContextText(prediction, topPicks(sporttery, 2, prediction))}。`;
}

function formatSp(value) {
  const num = Number(value);
  if (Number.isNaN(num)) return esc(value);
  return num.toFixed(2);
}

function oddsSelectionRank(selection) {
  const order = ["胜", "平", "负", "让胜", "让平", "让负", "0", "1", "2", "3", "4", "5", "6", "7+"];
  const index = order.indexOf(String(selection));
  return index === -1 ? 99 : index;
}

function predictionOddsRows(prediction) {
  const sporttery = prediction?.sporttery || {};
  const rows = uniqueBetRows([...(sporttery.options || []), ...(sporttery.candidate_pool || [])])
    .filter((row) => row?.sp != null && isOfficialSportteryBet(row));
  const playOrder = ["胜平负", "让球胜平负", "总进球", "比分", "半全场"];
  return playOrder
    .map((play) => {
      const playRows = rows
        .filter((row) => row.play_type === play)
        .sort((a, b) => oddsSelectionRank(a.selection) - oddsSelectionRank(b.selection))
        .slice(0, 6);
      let label = play;
      if (play === "让球胜平负" && sporttery.handicap !== null && sporttery.handicap !== undefined && sporttery.handicap !== "") {
        label = `让球(${sporttery.handicap})`;
      }
      return {
        play: label,
        options: playRows.map((row) => ({ name: row.selection, sp: row.sp })),
      };
    })
    .filter((row) => row.options.length)
    .slice(0, 4);
}

function oddsQuickRows(fixture, prediction) {
  const fromPrediction = predictionOddsRows(prediction);
  if (fromPrediction.length) return fromPrediction;
  return Array.isArray(fixture?.odds_summary) ? fixture.odds_summary.slice(0, 4) : [];
}

function renderOddsQuickView(fixture, prediction) {
  const rows = oddsQuickRows(fixture, prediction);
  if (!rows.length) {
    return `<div class="odds-panel muted-panel">暂无官方SP。公开赛程只提供比赛时间，等中国体彩开售后刷新会自动补充赔率。</div>`;
  }
  return `
    <div class="odds-panel">
      <div class="odds-title">官方SP</div>
      <div class="odds-groups">
        ${rows.map((row) => `
          <div class="odds-group">
            <strong>${esc(row.play)}</strong>
            ${(row.options || []).slice(0, 8).map((option) => `
              <span class="odds-chip">${esc(option.name)} <b>${formatSp(option.sp)}</b></span>
            `).join("")}
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

function marketValue(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(digits);
}

function marketMoveText(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "无变化";
  const num = Number(value);
  if (Math.abs(num) < 0.01) return "基本稳定";
  return num > 0 ? `升 ${num.toFixed(2)}，方向降温` : `降 ${Math.abs(num).toFixed(2)}，方向升温`;
}

function renderMarketContext(prediction) {
  const ctx = prediction?.market_context || {};
  if (!ctx.source) return `<p class="muted">暂无爱彩市场倍率数据。刷新后若爱彩公开接口可用，会自动补充。</p>`;
  const europe = ctx.europe;
  const asia = ctx.asia;
  const total = ctx.total_goals;
  return `
    <div class="planner-note">
      爱彩公开数据只用于观察非体彩市场变化；它不是中国体彩可下单项，最终下单仍以体彩计算器为准。
    </div>
    <table>
      <thead><tr><th>数据项</th><th>初始</th><th>当前</th><th>变化/解释</th></tr></thead>
      <tbody>
        ${europe ? `
          <tr>
            <td>欧赔倍率</td>
            <td>胜 ${marketValue(europe.first?.home)} / 平 ${marketValue(europe.first?.draw)} / 负 ${marketValue(europe.first?.away)}</td>
            <td>胜 ${marketValue(europe.latest?.home)} / 平 ${marketValue(europe.latest?.draw)} / 负 ${marketValue(europe.latest?.away)}</td>
            <td>主 ${esc(marketMoveText(europe.movement?.home))}<br>平 ${esc(marketMoveText(europe.movement?.draw))}<br>客 ${esc(marketMoveText(europe.movement?.away))}</td>
          </tr>
        ` : ""}
        ${asia ? `
          <tr>
            <td>让球市场参考<br><span class="muted">非体彩</span></td>
            <td>${marketValue(asia.first, 2)}</td>
            <td>${marketValue(asia.latest, 2)}<br><span class="muted">主方向 ${marketValue(asia.home_water)} / 客方向 ${marketValue(asia.away_water)}</span></td>
            <td>${esc(marketMoveText(asia.movement))}</td>
          </tr>
        ` : ""}
        ${total ? `
          <tr>
            <td>总进球市场参考<br><span class="muted">非体彩</span></td>
            <td>${marketValue(total.first, 2)}</td>
            <td>${marketValue(total.latest, 2)}<br><span class="muted">偏大 ${marketValue(total.over_water)} / 偏小 ${marketValue(total.under_water)}</span></td>
            <td>${esc(marketMoveText(total.movement))}</td>
          </tr>
        ` : ""}
      </tbody>
    </table>
  `;
}

function predictionBasisItems(item, prediction) {
  const scenario = marketScenario(prediction);
  const probs = scenario?.probabilities || {};
  const sporttery = prediction?.sporttery || {};
  const folkText = folkSignalText(prediction);
  const totalGoals = scenario?.total_goals;
  const hText = handicapText(sporttery.handicap ?? item.sporttery_handicap);
  const bestPicks = topPicks(sporttery, 3, prediction).map((row) => readablePickWithContext(row, prediction)).join("；") || "暂无达到下注门槛的官方SP选项";
  const upset = prediction.upset?.active?.slice(0, 4).map((row) => row.label).join("；") || "没有明显爆冷触发项";
  const expectedGoals = item.expected_goals ? `${Number(item.expected_goals.home || 0).toFixed(2)} - ${Number(item.expected_goals.away || 0).toFixed(2)}` : "未配置";
  return [
    {
      title: "主判断",
      text: `${conclusionText(item, prediction)}。模型胜平负概率为主 ${pct(probs.home)}、平 ${pct(probs.draw)}、客 ${pct(probs.away)}，预期进球 ${expectedGoals}。`,
    },
    {
      title: "官方体彩可买项",
      text: `${hText}。当前官方可买项：${bestPicks}。让球数只作为可下注约束；若和比分主线相反，只能当防穿盘观察。`,
    },
    {
      title: "战术对位",
      text: item.tactical_notes || "暂无稳定战术信息，按实力、官方SP和比分模型为主。",
    },
    {
      title: "赛前变量",
      text: [item.injury_notes, item.weather_notes, item.referee_notes].filter(Boolean).join("；") || "伤停、天气、裁判和首发仍需临场复核。",
    },
    {
      title: "风险点",
      text: `爆冷等级 ${prediction.summary.upset_level}，模型/市场分歧 ${prediction.summary.gap_level}。主要风险：${upset}。`,
    },
    {
      title: "支线观察",
      text: folkText,
    },
    {
      title: "比分与进球",
      text: `${scoreContextText(prediction, topPicks(sporttery, 3, prediction))}；总进球参考 ${totalGoals?.best_range ? `${totalGoals.best_range}球` : "暂无"}。比分只能小仓位覆盖，不作为主要投入方向。`,
    },
  ];
}

function folkSignalText(prediction) {
  const folk = prediction?.sporttery?.folk_parallel || prediction?.summary?.folk_parallel;
  if (!folk || !folk.enabled) return "未录入支线标签。本场只看数据模型、官方SP和赛前信息。";
  const display = Array.isArray(folk.tracks) && folk.tracks.length
    ? folk.tracks.slice(0, 3).map((row) => `${row.track || "支线"}：${row.display || row.label}`).join("；")
    : (folk.display || folk.label || "支线信号");
  const relation = folk.alignment ? `关系：${folk.alignment}` : "";
  const hint = folk.action_hint ? `提示：${folk.action_hint}` : "";
  const note = folk.note ? `备注：${folk.note}` : "";
  return `${display}。${[relation, hint, note].filter(Boolean).join("；")}。支线信号不参与核心概率、EV和仓位计算。`;
}

function renderPredictionBasis(item, prediction) {
  const rows = predictionBasisItems(item, prediction);
  return `
    <div class="basis-head">
      <div>${badge(RULES_VERSION, "blue")}</div>
      <p>下面是本场预测的主要依据，优先解释为什么这样判断，再给下注建议。</p>
    </div>
    <div class="basis-list">
      ${rows.map((row) => `
        <div class="basis-item">
          <div class="basis-title">${esc(row.title)}</div>
          <div class="basis-text">${esc(row.text)}</div>
        </div>
      `).join("")}
    </div>
    ${renderSideSignalPanel(prediction)}
  `;
}

function renderSideSignalPanel(prediction) {
  const folk = prediction?.sporttery?.folk_parallel || prediction?.summary?.folk_parallel;
  if (!folk || !folk.enabled) {
    return `
      <div class="side-signal-panel muted-panel">
        <div class="side-signal-head">
          <strong>支线观察</strong>
          ${badge("未录入", "amber")}
        </div>
        <p>未录入八卦/周易、奇门或紫微标签。本场只按数据模型和官方SP判断。</p>
      </div>
    `;
  }
  const tracks = Array.isArray(folk.tracks) && folk.tracks.length ? folk.tracks : [folk];
  return `
    <div class="side-signal-panel">
      <div class="side-signal-head">
        <strong>支线观察</strong>
        ${badge(folk.alignment || "仅观察", folk.alignment === "可能一致" ? "green" : folk.alignment === "冲突观察" ? "red" : "amber")}
      </div>
      <div class="side-signal-grid">
        ${tracks.slice(0, 4).map((row) => `
          <div class="side-signal-card">
            <span>${esc(row.track || "支线")}</span>
            <strong>${esc(row.display || row.label || "仅观察")}</strong>
            <em>${esc(row.note || row.source || "")}</em>
          </div>
        `).join("")}
      </div>
      <p>${esc(folk.action_hint || "只作风险观察")}。支线信号不参与核心概率、EV和仓位计算。</p>
    </div>
  `;
}

function topPicks(sporttery, limit = 4, prediction = null) {
  const usable = (row) => {
    const notes = `${row.reason || ""} ${(row.rule_notes || []).join(" ")}`;
    if (!["可小注", "观察", "高风险观察"].includes(row.decision)) return false;
    if (row.ev != null && row.ev <= 0) return false;
    if (notes.includes("低总进球高赔")) return false;
    if (row.play_type === "比分" || row.play_type === "半全场") return false;
    return true;
  };
  const candidates = sporttery?.candidate_pool || [];
  const preferred = candidates
    .filter(usable)
    .sort((a, b) => topPickSort(a, b, prediction));
  const fallback = (sporttery?.options || [])
    .filter(usable)
    .sort((a, b) => topPickSort(a, b, prediction) || calculatorOptionSort(a, b));
  return [...preferred, ...fallback]
    .filter((row, index, rows) => rows.findIndex((x) => x.play_type === row.play_type && x.selection === row.selection) === index)
    .slice(0, limit);
}

function topPickSort(a, b, prediction) {
  const aConflict = handicapPickConflict(a, prediction);
  const bConflict = handicapPickConflict(b, prediction);
  if (aConflict.conflict !== bConflict.conflict) return aConflict.conflict ? 1 : -1;
  const decisionDiff = (b.decision === "可小注") - (a.decision === "可小注");
  if (decisionDiff) return decisionDiff;
  return (b.risk_adjusted_score || 0) - (a.risk_adjusted_score || 0);
}

function topScoreText(prediction) {
  const scores = prediction?.sporttery?.score_reference || prediction?.value_model?.top_scores || [];
  return scores.slice(0, 3).map((row) => row.score).join(" / ") || "-";
}

function parseScore(score) {
  const parts = String(score || "").replace(":", "-").split("-").map((x) => Number.parseInt(x, 10));
  if (parts.length !== 2 || parts.some((x) => Number.isNaN(x))) return null;
  return { home: parts[0], away: parts[1] };
}

function handicapSelectionForScore(score, handicap) {
  const parsed = parseScore(score);
  const h = Number(handicap);
  if (!parsed || Number.isNaN(h)) return null;
  const adjusted = parsed.home + h - parsed.away;
  if (adjusted > 0) return "让胜";
  if (adjusted === 0) return "让平";
  return "让负";
}

function scorePoolHandicapLean(prediction) {
  const sporttery = prediction?.sporttery || {};
  const handicap = sporttery.handicap;
  if (handicap === null || handicap === undefined || Number.isNaN(Number(handicap))) return null;
  const scenario = marketScenario(prediction);
  const grid = sporttery.score_reference?.length
    ? sporttery.score_reference
    : scenario?.score_grid?.length
      ? scenario.score_grid
      : prediction?.value_model?.top_scores || scenario?.top_scores || [];
  const buckets = { "让胜": 0, "让平": 0, "让负": 0 };
  let total = 0;
  grid.forEach((row, index) => {
    const selection = handicapSelectionForScore(row.score, handicap);
    if (!selection) return;
    const weight = Number(row.probability ?? row.model_prob ?? 0) || (1 / (index + 1));
    buckets[selection] += weight;
    total += weight;
  });
  if (!total) return null;
  const selection = Object.entries(buckets).sort((a, b) => b[1] - a[1])[0][0];
  return { selection, probability: buckets[selection] / total, buckets };
}

function handicapPickConflict(row, prediction) {
  if (!row || row.play_type !== "让球胜平负" || !prediction) return { conflict: false };
  const lean = scorePoolHandicapLean(prediction);
  if (!lean) return { conflict: false };
  const conflict = row.selection !== lean.selection && lean.probability >= 0.42;
  return { conflict, lean };
}

function readablePickWithContext(row, prediction) {
  const base = readablePick(row);
  const check = handicapPickConflict(row, prediction);
  if (!check.conflict) return base;
  return `${base}（反比分主线，防穿盘观察）`;
}

function pickContextNote(row, prediction) {
  const check = handicapPickConflict(row, prediction);
  if (!check.conflict) return "";
  return `注意：比分主线更像${check.lean.selection}（${topScoreText(prediction)}），这项是反主线的防穿盘/赔率价值观察，不适合作为主要投入方向，也不要和大胜比分当成同一方向去串。`;
}

function scoreContextText(prediction, picks = []) {
  const scoreText = topScoreText(prediction);
  const conflicted = picks.find((row) => handicapPickConflict(row, prediction).conflict);
  if (!conflicted) return `比分主线：${scoreText}`;
  const check = handicapPickConflict(conflicted, prediction);
  return `比分主线：${scoreText}，让球主线更像${check.lean.selection}；${readablePick(conflicted)}属于防穿盘价值观察，不是比分主线`;
}

function riskText(prediction) {
  const summary = prediction.summary;
  const gap = summary.gap_level || "无市场数据";
  const upset = summary.upset_level || "-";
  if (gap === "高分歧" || upset === "高") return "风险高，少串或只观察";
  if (gap === "明显分歧" || upset === "中高") return "有分歧，控制金额";
  return "风险正常，仍需看临场SP";
}

function renderPickCard(row, matchLabel = "", prediction = null) {
  if (!row) {
    return `<div class="pick-card watch"><div class="pick-title">暂无正向候选</div><div class="pick-reason">当前没有同时满足官方SP、模型价值和风险约束的选项。</div></div>`;
  }
  const conflict = handicapPickConflict(row, prediction).conflict;
  const tone = conflict ? "watch" : decisionTone(row);
  const action = row.sp == null ? "等SP" : row.decision;
  const note = pickContextNote(row, prediction);
  return `
    <div class="pick-card ${tone}">
      <div class="pick-title">
        <span>${matchLabel ? `${esc(matchLabel)}｜` : ""}${esc(readablePick(row))}</span>
        ${badge(conflict ? "防穿盘观察" : action, tone === "primary" ? "green" : tone === "risky" ? "red" : "amber")}
      </div>
      <div class="pick-meta">
        <span>模型 ${pct(row.model_prob)}</span>
        <span>EV ${row.ev == null ? "-" : pct(row.ev)}</span>
        <span>风险 ${row.risk_score ?? "-"}</span>
      </div>
      <div class="pick-reason">${esc((row.rule_notes || []).join("；") || row.reason || row.score_note || "按官方玩法和模型价值筛选")}</div>
      ${note ? `<div class="pick-warning">${esc(note)}</div>` : ""}
    </div>
  `;
}

function overviewFinishedRows(limit = 4) {
  return scheduleRows()
    .filter((row) => isPrimaryScheduleRow(row) && fixtureStatus(row.fixture) === "finished")
    .sort((a, b) => String(b.fixture.kickoff || "").localeCompare(String(a.fixture.kickoff || "")))
    .slice(0, limit);
}

function overviewUpcomingRows(limit = 6) {
  return scheduleRows()
    .filter((row) => isPrimaryScheduleRow(row) && fixtureStatus(row.fixture) !== "finished")
    .sort((a, b) => String(a.fixture.kickoff || "").localeCompare(String(b.fixture.kickoff || "")))
    .slice(0, limit);
}

function renderOverviewV2() {
  const content = document.getElementById("content");
  const matches = state.data?.matches ?? [];
  const fixtures = state.data?.fixtures || { scheduled: [], finished: [] };
  const summary = state.data?.backtest_summary || {};
  const comboCount = state.data?.sporttery_combos?.length || 0;
  const latestFinished = overviewFinishedRows(4);
  const upcomingRows = overviewUpcomingRows(6);
  content.innerHTML = `
    <section class="schedule-head">
      <div>
        <h2>今天先看赛果，再看下一场</h2>
        <p>首页只放最关键的两件事：刚结束的比赛有没有偏差，马上开始的比赛能不能加入预测并生成下注测算。</p>
      </div>
      <div class="actions">
        <button data-post="/api/schedule/query" data-message="赛程查询完成">刷新赛程</button>
        <button class="secondary" data-tab="calendar">全部赛程</button>
        <button class="secondary" data-tab="schedule">完整复盘</button>
      </div>
    </section>

    <section class="grid cols-4">
      <div class="metric"><div class="label">当前预测</div><div class="value">${matches.length}</div><div class="sub">可查看详情和测算</div></div>
      <div class="metric"><div class="label">待开比赛</div><div class="value">${fixtures.scheduled?.length || 0}</div><div class="sub">首页展示最近 ${upcomingRows.length} 场</div></div>
      <div class="metric"><div class="label">最新完赛</div><div class="value">${fixtures.finished?.length || 0}</div><div class="sub">首页展示最近 ${latestFinished.length} 场</div></div>
      <div class="metric"><div class="label">过关组合</div><div class="value">${comboCount}</div><div class="sub">只纳入有SP候选</div></div>
    </section>

    <section class="grid cols-2">
      <div class="section">
        <div class="section-heading-row">
          <div>
            <h2>最新完赛复盘</h2>
            <p class="muted">先看结果和偏差，避免继续用已经暴露问题的判断方式。</p>
          </div>
          <button class="secondary" data-tab="schedule">看全部</button>
        </div>
        <div class="overview-feed">
          ${latestFinished.length ? latestFinished.map(renderOverviewFinishedCard).join("") : `<div class="empty-state">暂无完赛结果。刷新赛程后会自动出现在这里。</div>`}
        </div>
      </div>

      <div class="section">
        <div class="section-heading-row">
          <div>
            <h2>待开比赛</h2>
            <p class="muted">最近要开的比赛直接在这里加入预测，不用翻日期。</p>
          </div>
          <button class="secondary" data-tab="calendar">打开挂历</button>
        </div>
        <div class="overview-feed">
          ${upcomingRows.length ? upcomingRows.map(renderOverviewUpcomingCard).join("") : `<div class="empty-state">暂无待开比赛。点击“刷新赛程”重新获取。</div>`}
        </div>
      </div>
    </section>

    <section class="section">
      <h2>当前已加入预测</h2>
      <div class="overview-grid">
        ${matches.length ? matches.map(renderOverviewCard).join("") : `<div class="empty-state">暂无已加入预测的比赛。先在“待开比赛”里加入单场或未来4场。</div>`}
      </div>
    </section>

    <section class="section">
      <h3>回测给下一轮的提醒</h3>
      ${tuningSuggestionList(summary.tuning_suggestions || [])}
    </section>

    <section class="section">
      <h3>混合过关候选</h3>
      <p class="muted">只从有体彩SP且价值为正的跨场主玩法生成；缺少SP的比赛不会硬串。</p>
      ${globalComboTable(state.data?.sporttery_combos ?? [])}
    </section>
  `;
}

function renderOverviewFinishedCard(row) {
  const fixture = row.fixture;
  const test = latestBacktest(row.backtests);
  const result = actualResult(fixture);
  const hit = test ? Boolean(test.top1_hit) : null;
  const label = hit === null ? "未回测" : hit ? "方向命中" : "方向偏差";
  const tone = hit === null ? "pending" : hit ? "hit" : "miss";
  return `
    <article class="overview-list-card finished ${tone}">
      <div class="overview-list-main">
        <div>
          <div class="overview-list-time">${esc(fullKickoff(fixture.kickoff))}</div>
          <strong>${esc(fixture.home_team)} vs ${esc(fixture.away_team)}</strong>
        </div>
        <div class="overview-score">${fixture.home_score ?? "-"} - ${fixture.away_score ?? "-"}</div>
      </div>
      <div class="overview-list-meta">
        ${badge(label, hit === null ? "amber" : hit ? "green" : "red")}
        ${badge(`赛果 ${resultName(result)}`, "blue")}
        ${fixture.stage ? badge(fixture.stage, "amber") : ""}
      </div>
      <p>${esc(test ? deviationText(test) : "没有赛前预测归档，不能做正式偏差分析。")}</p>
      ${row.prediction ? `<div class="card-actions"><button class="secondary" data-open-match="${esc(row.prediction.match_id)}">查看赛前预测</button></div>` : ""}
    </article>
  `;
}

function renderOverviewUpcomingCard(row) {
  const fixture = row.fixture;
  const prediction = row.prediction?.prediction;
  const matchId = row.prediction?.match_id;
  const key = matchKey(fixture.home_team, fixture.away_team, fixture.kickoff);
  const market = prediction?.scenarios?.find((s) => s.scenario === "market");
  const picks = prediction ? topPicks(prediction.sporttery, 2, prediction) : [];
  return `
    <article class="overview-list-card upcoming ${prediction ? "has-prediction" : ""}">
      <div class="overview-list-main">
        <div>
          <div class="overview-list-time">${esc(fullKickoff(fixture.kickoff))}</div>
          <strong>${esc(fixture.home_team)} vs ${esc(fixture.away_team)}</strong>
        </div>
        <div class="overview-source">${esc(fixture.stage || "赛程")}</div>
      </div>
      ${prediction ? `
        <div class="mini-probs">
          <div><span>主胜</span><strong>${pct(market?.probabilities?.home)}</strong></div>
          <div><span>平局</span><strong>${pct(market?.probabilities?.draw)}</strong></div>
          <div><span>客胜</span><strong>${pct(market?.probabilities?.away)}</strong></div>
        </div>
        <div class="basis-brief">${esc(shortBasisText(row.prediction, prediction))}</div>
        <div class="overview-list-meta">
          ${picks.length ? picks.map((pick) => badge(readablePick(pick), pick.decision === "可小注" ? "green" : "amber")).join("") : badge("暂无正向候选", "amber")}
        </div>
        <div class="card-actions">
          <button data-open-match="${esc(matchId)}">看预测详情</button>
          <button class="secondary" data-open-betting="${esc(matchId)}">下注测算</button>
          <button class="secondary" data-refresh="${esc(matchId)}">刷新</button>
        </div>
      ` : `
        ${renderOddsQuickView(fixture, null)}
        <div class="empty-mini">还没加入预测。加入后会自动生成概率、比分池和下注测算。</div>
        <div class="card-actions">
          <button data-select-fixture="${esc(key)}" data-select-mode="single">加入此场预测</button>
          <button class="secondary" data-select-fixture="${esc(key)}" data-select-mode="next4">从这场起预测4场</button>
        </div>
      `}
    </article>
  `;
}

function renderSharePanel(item, prediction, marketScenario) {
  const picks = topPicks(prediction.sporttery, 2, prediction);
  const prob = marketScenario?.probabilities || prediction.value_model?.probabilities || {};
  return `
    <div class="share-panel">
      <div class="share-line">
        <div class="share-label">主方向</div>
        <div class="share-value">${esc(conclusionText(item, prediction))}</div>
      </div>
      <div class="share-line">
        <div class="share-label">胜平负概率</div>
        <div class="share-value">主 ${pct(prob.home)} ｜ 平 ${pct(prob.draw)} ｜ 客 ${pct(prob.away)}</div>
      </div>
      <div class="share-line">
        <div class="share-label">比分主线</div>
        <div class="share-value">${esc(scoreContextText(prediction, picks))}</div>
      </div>
      <div class="share-line">
        <div class="share-label">价值/观察项</div>
        <div class="share-value">${esc(picks.map((row) => readablePickWithContext(row, prediction)).join("；") || "暂无正向候选")}</div>
      </div>
      <div class="share-line">
        <div class="share-label">风险提示</div>
        <div class="share-value">${esc(riskText(prediction))}</div>
      </div>
    </div>
  `;
}

function renderOverview() {
  const content = document.getElementById("content");
  const matches = state.data?.matches ?? [];
  const fixtures = state.data?.fixtures || { scheduled: [], finished: [] };
  const summary = state.data?.backtest_summary || {};
  const comboCount = state.data?.sporttery_combos?.length || 0;
  content.innerHTML = `
    <section class="schedule-head">
      <div>
        <h2>今天先做哪一步</h2>
        <p>按实战流程使用：刷新赛程和赔率，加入要看的比赛，进入预测详情和下注测算；完赛后再看回测复盘。</p>
      </div>
      <div class="actions">
        <button data-post="/api/schedule/query" data-message="赛程查询完成">刷新赛程</button>
        <button class="secondary" data-tab="calendar">打开赛程挂历</button>
        <button class="secondary" data-tab="schedule">看回测复盘</button>
      </div>
    </section>
    <section class="grid cols-4">
      <div class="metric"><div class="label">当前预测</div><div class="value">${matches.length}</div><div class="sub">可查看详情和测算</div></div>
      <div class="metric"><div class="label">未开赛程</div><div class="value">${fixtures.scheduled?.length || 0}</div><div class="sub">从挂历加入预测</div></div>
      <div class="metric"><div class="label">已完赛果</div><div class="value">${fixtures.finished?.length || 0}</div><div class="sub">用于赛后复盘</div></div>
      <div class="metric"><div class="label">过关组合</div><div class="value">${comboCount}</div><div class="sub">只纳入有SP候选</div></div>
    </section>
    <section class="section">
      <h2>今日比赛推荐总览</h2>
      <div class="overview-grid">
        ${matches.map(renderOverviewCard).join("")}
      </div>
    </section>
    <section class="section">
      <h3>数据源健康</h3>
      ${sourceHealthTable(state.data?.sources ?? [], state.data?.source_health ?? {})}
    </section>
    <section class="section">
      <h3>混合过关池</h3>
      <p class="muted">对齐体彩计算器“混合过关”：只从有体彩SP且价值为正的跨场主玩法生成；缺少SP的场次不会硬串。</p>
      ${globalComboTable(state.data?.sporttery_combos ?? [])}
    </section>
  `;
}

function renderOverviewCard(item) {
  const prediction = item.prediction;
  const summary = prediction.summary;
  const market = prediction.scenarios.find((s) => s.scenario === "market");
  const picks = topPicks(prediction.sporttery, 2, prediction);
  return `
    <div class="match-card">
      <div class="match-card-top">
        <div>
          <div class="match-title">${esc(item.home_team)} vs ${esc(item.away_team)}</div>
          <div class="kickoff">${esc(formatKickoff(item.kickoff))}</div>
          <div class="rank-line">${esc(fifaRankText(item))}</div>
        </div>
        <button data-refresh="${esc(item.match_id)}">刷新</button>
      </div>
      <div class="headline">${esc(conclusionText(item, prediction))}</div>
      <div class="tag-row">
        ${badge(`置信 ${summary.confidence}/100`, summary.confidence >= 70 ? "green" : summary.confidence >= 55 ? "amber" : "red")}
        ${badge(`爆冷 ${summary.upset_level}`, summary.upset_level === "低" ? "green" : summary.upset_level === "高" ? "red" : "amber")}
        ${badge(`分歧 ${summary.gap_level}`, summary.gap_level === "一致" ? "green" : summary.gap_level === "高分歧" ? "red" : "amber")}
      </div>
      <div class="prob-strip" style="margin-top: 12px;">
        <div class="prob-pill home"><span>主胜</span><strong>${pct(market?.probabilities.home)}</strong></div>
        <div class="prob-pill draw"><span>平局</span><strong>${pct(market?.probabilities.draw)}</strong></div>
        <div class="prob-pill away"><span>客胜</span><strong>${pct(market?.probabilities.away)}</strong></div>
      </div>
      ${renderOddsQuickView(item, prediction)}
      <div class="card-picks" style="margin-top: 12px;">
        ${picks.length ? picks.map((row) => renderPickCard(row, "", prediction)).join("") : renderPickCard(null)}
      </div>
      <div class="basis-brief">${esc(shortBasisText(item, prediction))}</div>
      <div class="pick-reason">${esc(scoreContextText(prediction, picks))}。${esc(riskText(prediction))}。</div>
      <div class="card-actions">
        <button data-open-match="${esc(item.match_id)}">查看预测详情</button>
        <button class="secondary" data-open-betting="${esc(item.match_id)}">下注建议测算</button>
      </div>
    </div>
  `;
}

function renderCalendar() {
  const content = document.getElementById("content");
  const groups = calendarGroups();
  const total = groups.reduce((sum, group) => sum + group.items.length, 0);
  const predicted = groups.reduce((sum, group) => sum + group.items.filter((row) => row.prediction).length, 0);
  const sportteryCount = groups.reduce((sum, group) => sum + group.items.filter((row) => String(row.fixture.source || "").includes("中国体彩")).length, 0);
  content.innerHTML = `
    <section class="schedule-head">
      <div>
        <h2>世界杯赛程挂历</h2>
        <p>按中国北京时间分组展示未开赛赛程。体彩官方可售场次会显示编号；公开赛程源若只有日期，会标注“当日时间待核对”。</p>
      </div>
      <div class="actions">
        <button data-post="/api/schedule/query" data-message="赛程查询完成">刷新赛程</button>
      </div>
    </section>
    <section class="grid cols-3">
      <div class="metric"><div class="label">未开赛场次</div><div class="value">${total}</div><div class="sub">公开赛程 + 体彩可售</div></div>
      <div class="metric"><div class="label">已有预测</div><div class="value">${predicted}</div><div class="sub">可查看预测详情</div></div>
      <div class="metric"><div class="label">体彩可售</div><div class="value">${sportteryCount}</div><div class="sub">可对齐竞彩下单</div></div>
    </section>
    <section class="calendar-board">
      ${groups.length ? groups.slice(0, 40).map(renderCalendarDay).join("") : `<div class="empty-state">暂无未开赛赛程。</div>`}
    </section>
  `;
}

function renderCalendarDay(group) {
  return `
    <div class="calendar-day">
      <div class="calendar-day-head">
        <h3>${esc(dayLabel(group.dateKey))}</h3>
        <span>${group.items.length}场</span>
      </div>
      <div class="calendar-fixtures">
        ${group.items.map(renderCalendarFixture).join("")}
      </div>
    </div>
  `;
}

function renderCalendarFixture(row) {
  const fixture = row.fixture;
  const prediction = row.prediction?.prediction;
  const source = String(fixture.source || "");
  const isSporttery = source.includes("中国体彩");
  const key = matchKey(fixture.home_team, fixture.away_team, fixture.kickoff);
  return `
    <article class="calendar-fixture ${prediction ? "has-prediction clickable" : ""}" ${prediction ? `data-open-card="${esc(row.prediction.match_id)}"` : ""}>
      <div class="calendar-time">${esc(calendarKickoff(fixture))}</div>
      <div class="calendar-match">
        <strong>${esc(fixture.home_team)} vs ${esc(fixture.away_team)}</strong>
        <div class="schedule-meta">
          ${fixture.stage ? badge(fixture.stage, isSporttery ? "blue" : "amber") : ""}
          ${isSporttery ? badge("体彩可售", "green") : badge("公开赛程", "amber")}
          ${fixture.venue ? `<span>${esc(fixture.venue)}</span>` : ""}
        </div>
      </div>
      ${renderOddsQuickView(fixture, prediction)}
      ${prediction ? `
        <div class="basis-brief">${esc(shortBasisText(row.prediction, prediction))}</div>
        <div class="card-actions">
          <button data-open-match="${esc(row.prediction.match_id)}">查看预测详情</button>
          <button class="secondary" data-open-betting="${esc(row.prediction.match_id)}">下注建议测算</button>
          <button class="secondary" data-refresh="${esc(row.prediction.match_id)}">刷新预测</button>
        </div>
      ` : `
        <div class="empty-mini">仅赛程信息，暂未建立预测模型。</div>
        <div class="card-actions">
          <button data-select-fixture="${esc(key)}" data-select-mode="single">加入此场预测</button>
          <button class="secondary" data-select-fixture="${esc(key)}" data-select-mode="next4">从这场起预测4场</button>
        </div>
      `}
    </article>
  `;
}

function renderScheduleDay(tabId) {
  const [, dateKey, wantedStatus] = tabId.split(":");
  const rows = scheduleRows().filter((row) => {
    const rowStatus = fixtureStatus(row.fixture) === "finished" ? "finished" : "scheduled";
    return isPrimaryScheduleRow(row) && bjtDateKey(row.fixture.kickoff) === dateKey && rowStatus === wantedStatus;
  });
  const content = document.getElementById("content");
  const finished = wantedStatus === "finished";
  const withPrediction = rows.filter((row) => row.prediction).length;
  const withBacktest = rows.filter((row) => latestBacktest(row.backtests)).length;
  content.innerHTML = `
    <section class="schedule-head">
      <div>
        <h2>${esc(dayLabel(dateKey))} ${finished ? "完赛复盘" : "赛前预测"}</h2>
        <p>${finished ? "完赛场次会展示赛果、赛前预测命中情况和偏差原因。" : "未开赛场次按北京时间排序，优先展示中国体彩可售信息和本地模型推荐。"}</p>
      </div>
      <div class="actions">
        <button data-post="/api/schedule/query" data-message="赛程查询完成">一键查询赛程</button>
        <button data-post="/api/predictions/archive" data-message="当前预测已归档" class="secondary">归档当前预测</button>
        <button data-post="/api/backtest/run" data-message="回测已完成" class="secondary">运行回测</button>
      </div>
    </section>
    <section class="grid cols-3">
      <div class="metric"><div class="label">本页比赛</div><div class="value">${rows.length}</div><div class="sub">${finished ? "已完赛/待复盘" : "未开赛/待跟踪"}</div></div>
      <div class="metric"><div class="label">有预测模型</div><div class="value">${withPrediction}</div><div class="sub">可展示推荐与概率</div></div>
      <div class="metric"><div class="label">有正式回测</div><div class="value">${withBacktest}</div><div class="sub">需赛前归档 + 完场比分</div></div>
    </section>
    <section class="schedule-grid">
      ${rows.length ? rows.map(renderScheduleCard).join("") : `<div class="empty-state">暂无该日期比赛。点击“一键查询赛程”刷新。</div>`}
    </section>
  `;
}

function renderScheduleCard(row) {
  const fixture = row.fixture;
  const prediction = row.prediction?.prediction;
  const status = fixtureStatus(fixture);
  const finished = status === "finished";
  const market = prediction?.scenarios?.find((s) => s.scenario === "market");
  const picks = prediction ? topPicks(prediction.sporttery, 3, prediction) : [];
  return `
    <article class="schedule-card ${finished ? "finished" : ""} ${row.prediction ? "clickable" : ""}" ${row.prediction ? `data-open-card="${esc(row.prediction.match_id)}"` : ""}>
      <div class="schedule-card-top">
        <div>
          <div class="schedule-time">${esc(fullKickoff(fixture.kickoff))}</div>
          <h3>${esc(fixture.home_team)} vs ${esc(fixture.away_team)}</h3>
          <div class="schedule-meta">
            ${fixture.stage ? badge(fixture.stage, "blue") : ""}
            ${fixture.source ? badge(shortSource(fixture.source), finished ? "green" : "amber") : ""}
            ${fixture.venue ? `<span>${esc(fixture.venue)}</span>` : ""}
          </div>
        </div>
        <div class="status-chip ${finished ? "done" : status === "pending_result" ? "pending" : ""}">
          ${finished ? "完赛" : status === "pending_result" ? "待补赛果" : "未开赛"}
        </div>
      </div>
      ${finished ? renderFinishedBlock(row) : renderUpcomingBlock(row, market, picks)}
    </article>
  `;
}

function renderUpcomingBlock(row, market, picks) {
  const prediction = row.prediction?.prediction;
  const key = matchKey(row.fixture.home_team, row.fixture.away_team, row.fixture.kickoff);
  if (!prediction) {
    return `
      ${renderOddsQuickView(row.fixture, null)}
      <div class="empty-mini">
        这场已经进入赛程，但还没有加入本地预测配置。可以直接生成预测并刷新赔率。
      </div>
      <div class="card-actions">
        <button data-select-fixture="${esc(key)}" data-select-mode="single">加入此场预测</button>
        <button class="secondary" data-select-fixture="${esc(key)}" data-select-mode="next4">从这场起预测4场</button>
      </div>
    `;
  }
  return `
    <div class="mini-probs">
      <div><span>主胜</span><strong>${pct(market?.probabilities?.home)}</strong></div>
      <div><span>平局</span><strong>${pct(market?.probabilities?.draw)}</strong></div>
      <div><span>客胜</span><strong>${pct(market?.probabilities?.away)}</strong></div>
    </div>
    ${renderOddsQuickView(row.fixture, prediction)}
    <div class="schedule-conclusion">${esc(conclusionText(row.prediction, prediction))}</div>
    <div class="schedule-picks">
      ${picks.length ? picks.map((pick) => renderPickCard(pick, "", prediction)).join("") : renderPickCard(null)}
    </div>
    <div class="basis-brief">${esc(shortBasisText(row.prediction, prediction))}</div>
    <div class="plain-note">${esc(scoreContextText(prediction, picks))}。${esc(riskText(prediction))}。</div>
    <div class="card-actions">
      <button data-open-match="${esc(row.prediction.match_id)}">查看预测详情</button>
      <button class="secondary" data-open-betting="${esc(row.prediction.match_id)}">下注建议测算</button>
      <button class="secondary" data-refresh="${esc(row.prediction.match_id)}">刷新预测</button>
    </div>
  `;
}

function renderFinishedBlock(row) {
  const fixture = row.fixture;
  const test = latestBacktest(row.backtests);
  const actual = actualResult(fixture);
  return `
    <div class="final-score">
      <span>${esc(fixture.home_team)}</span>
      <strong>${fixture.home_score ?? "-"} - ${fixture.away_score ?? "-"}</strong>
      <span>${esc(fixture.away_team)}</span>
    </div>
    ${test ? renderDeviation(test, actual) : renderMissingBacktest(row)}
    ${row.prediction ? `<div class="card-actions"><button data-open-match="${esc(row.prediction.match_id)}">查看赛前预测详情</button></div>` : ""}
  `;
}

function renderDeviation(test, actual) {
  const hit = Boolean(test.top1_hit);
  return `
    <div class="review-panel ${hit ? "hit" : "miss"}">
      <div class="review-title">
        <strong>${hit ? "预测方向命中" : "预测方向偏差"}</strong>
        ${badge(test.scenario || "market", hit ? "green" : "red")}
      </div>
      <div class="review-grid">
        <div><span>赛前预测</span><strong>${esc(resultName(test.predicted_result))}</strong></div>
        <div><span>实际结果</span><strong>${esc(resultName(actual || test.actual_result))}</strong></div>
        <div><span>Brier</span><strong>${Number(test.brier_score).toFixed(3)}</strong></div>
        <div><span>Log Loss</span><strong>${Number(test.log_loss).toFixed(3)}</strong></div>
        <div><span>ROI</span><strong>${test.roi == null ? "-" : pct(test.roi)}</strong></div>
      </div>
      <p>${esc(deviationText(test))}</p>
    </div>
  `;
}

function renderMissingBacktest(row) {
  const prediction = row.prediction?.prediction;
  if (!prediction) {
    return `<div class="empty-mini">没有赛前预测归档，不能做正式偏差分析。</div>`;
  }
  return `
    <div class="review-panel pending">
      <div class="review-title"><strong>待运行正式回测</strong>${badge("需归档", "amber")}</div>
      <p>这场有模型信息，但没有找到赛前预测快照。正式复盘需要先在赛前点击“归档当前预测”，完赛后再运行回测。</p>
    </div>
  `;
}

function deviationText(test) {
  if (test.top1_hit) {
    return "主方向判断正确，后续重点看比分池和让球/总进球是否也覆盖到实际走势。";
  }
  if (test.actual_result === "draw") {
    return "实际打成平局，说明模型可能低估了弱队防守、强队轮换或比赛节奏下降带来的平局概率。";
  }
  if (test.predicted_result === "home" || test.predicted_result === "away") {
    return "强弱方向判断偏差，复盘时优先检查阵容轮换、赛前新闻、官方SP临场变化和早段进球/红黄牌影响。";
  }
  return "偏差主要来自平局保护不足或胜负方向被临场因素打破，需要结合技术统计和收盘SP继续校准。";
}

function renderScheduleBacktest() {
  const content = document.getElementById("content");
  const fixtures = state.data?.fixtures || { scheduled: [], finished: [] };
  const standings = state.data?.standings || { groups: [] };
  const summary = state.data?.backtest_summary || {};
  const snapshots = state.data?.prediction_snapshots || [];
  content.innerHTML = `
    <section class="section">
      <h2>赛程与回测</h2>
      <div class="actions" style="justify-content: flex-start;">
        <button id="querySchedule">一键查询赛程</button>
        <button id="archivePredictions" class="secondary">归档当前预测</button>
        <button id="runBacktest" class="secondary">运行赛后回测</button>
      </div>
      <p class="muted">赛程查询使用公开无 key 来源，成功后写入本地 fixtures 表；回测只评估已有预测归档且已有完场比分的比赛。</p>
    </section>

    <section class="grid cols-4">
      <div class="metric">
        <div class="label">未开赛</div>
        <div class="value">${fixtures.scheduled.length}</div>
        <div class="sub">公开赛程源</div>
      </div>
      <div class="metric">
        <div class="label">已完结</div>
        <div class="value">${fixtures.finished.length}</div>
        <div class="sub">可用于回测</div>
      </div>
      <div class="metric">
        <div class="label">预测归档</div>
        <div class="value">${snapshots.length}</div>
        <div class="sub">每场每情景一条</div>
      </div>
      <div class="metric">
        <div class="label">回测样本</div>
        <div class="value">${summary.count || 0}</div>
        <div class="sub">Top1 ${summary.top1_accuracy == null ? "-" : pct(summary.top1_accuracy)}</div>
      </div>
    </section>
    <section class="section">
      <h3>Bing小组积分榜</h3>
      <p class="muted">用于小组形势、赛果验证和动机修正，不作为赔率来源。最新抓取：${esc(standings.captured_at || "未抓取")}</p>
      ${standingsTable(standings)}
    </section>

    <section class="grid cols-2">
      <div class="section">
        <h3>未开赛赛程</h3>
        ${fixtureTable(fixtures.scheduled, false)}
      </div>
      <div class="section">
        <h3>已完结赛程</h3>
        ${fixtureTable(fixtures.finished, true)}
      </div>
    </section>

    <section class="grid cols-2">
      <div class="section">
        <h3>回测总览</h3>
        ${backtestSummaryTable(summary)}
      </div>
      <div class="section">
        <h3>按情景模型</h3>
        ${scenarioBacktestTable(summary.by_scenario || [])}
      </div>
    </section>
    <section class="grid cols-2">
      <div class="section">
        <h3>校准分桶</h3>
        ${calibrationTable(summary.calibration_buckets || [])}
      </div>
      <div class="section">
        <h3>自动调参建议</h3>
        ${tuningSuggestionList(summary.tuning_suggestions || [])}
      </div>
    </section>
  `;
  document.getElementById("querySchedule").addEventListener("click", () => postAction("/api/schedule/query", "赛程查询完成"));
  document.getElementById("archivePredictions").addEventListener("click", () => postAction("/api/predictions/archive", "当前预测已归档"));
  document.getElementById("runBacktest").addEventListener("click", () => postAction("/api/backtest/run", "回测已完成"));
}

function standingsTable(standings) {
  const groups = standings?.groups || [];
  if (!groups.length) return `<p class="muted">暂无积分榜。点击“一键查询赛程”会同时刷新 Bing 积分榜。</p>`;
  return `
    <div class="standings-grid">
      ${groups.slice(0, 12).map((group) => `
        <div class="mini-table">
          <h4>${esc(group.group || "-")}</h4>
          <table>
            <thead>
              <tr>
                <th>队伍</th><th>赛</th><th>胜平负</th><th>进失</th><th>净</th><th>分</th>
              </tr>
            </thead>
            <tbody>
              ${(group.teams || []).map((team) => `
                <tr>
                  <td>${team.rank}. ${esc(team.team)}</td>
                  <td>${team.played}</td>
                  <td>${team.wins}/${team.draws}/${team.losses}</td>
                  <td>${team.goals_for}:${team.goals_against}</td>
                  <td>${team.goal_diff}</td>
                  <td><strong>${team.points}</strong></td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      `).join("")}
    </div>
  `;
}

function fixtureTable(fixtures, finished) {
  if (!fixtures.length) return `<p class="muted">暂无数据。点击“一键查询赛程”。</p>`;
  return `
    <table>
      <thead>
        <tr>
          <th>比赛</th>
          <th>时间</th>
          <th>阶段</th>
          ${finished ? "<th>比分</th>" : ""}
          <th>来源</th>
        </tr>
      </thead>
      <tbody>
        ${fixtures.slice(0, 80).map((fixture) => `
          <tr>
            <td><strong>${esc(fixture.home_team)} vs ${esc(fixture.away_team)}</strong><br><span class="muted">${esc(fixture.match_id)}</span></td>
            <td>${esc(fixture.kickoff || "-")}</td>
            <td>${esc(fixture.stage || "-")}</td>
            ${finished ? `<td>${fixture.home_score ?? "-"} - ${fixture.away_score ?? "-"}</td>` : ""}
            <td>${esc(shortSource(fixture.source))}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function shortSource(source) {
  if (!source) return "-";
  return source.length > 48 ? `${source.slice(0, 45)}...` : source;
}

function backtestSummaryTable(summary) {
  if (!summary || !summary.count) return `<p class="muted">暂无回测结果。先归档预测，再查询已完结赛程并运行回测。</p>`;
  return `
    <table>
      <tbody>
        <tr><th>样本数</th><td>${summary.count}</td></tr>
        ${summary.raw_count && summary.raw_count !== summary.count ? `<tr><th>原始快照</th><td>${summary.raw_count}</td></tr>` : ""}
        <tr><th>Top1 命中率</th><td>${pct(summary.top1_accuracy)}</td></tr>
        <tr><th>Top2 命中率</th><td>${pct(summary.top2_accuracy)}</td></tr>
        <tr><th>比分 Top1 命中率</th><td>${pct(summary.score_accuracy)}</td></tr>
        <tr><th>平均 Brier</th><td>${summary.avg_brier.toFixed(3)}</td></tr>
        <tr><th>平均 Log Loss</th><td>${summary.avg_log_loss.toFixed(3)}</td></tr>
        <tr><th>单注平均 ROI</th><td>${summary.avg_roi == null ? "-" : pct(summary.avg_roi)}</td></tr>
      </tbody>
    </table>
  `;
}

function scenarioBacktestTable(rows) {
  if (!rows.length) return `<p class="muted">暂无情景模型回测。</p>`;
  return `
    <table>
      <thead><tr><th>情景</th><th>样本</th><th>Top1</th><th>Top2</th><th>Brier</th><th>Log Loss</th><th>ROI</th></tr></thead>
      <tbody>
        ${rows.map((row) => `
          <tr>
            <td>${esc(row.scenario)}</td>
            <td>${row.count}</td>
            <td>${pct(row.top1_accuracy)}</td>
            <td>${pct(row.top2_accuracy)}</td>
            <td>${row.avg_brier.toFixed(3)}</td>
            <td>${row.avg_log_loss.toFixed(3)}</td>
            <td>${row.avg_roi == null ? "-" : pct(row.avg_roi)}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function calibrationTable(rows) {
  if (!rows.length) return `<p class="muted">暂无校准分桶。</p>`;
  return `
    <table>
      <thead><tr><th>置信区间</th><th>样本</th><th>实际命中率</th><th>平均 Brier</th></tr></thead>
      <tbody>
        ${rows.map((row) => `
          <tr>
            <td>${esc(row.bucket)}</td>
            <td>${row.count}</td>
            <td>${row.accuracy == null ? "-" : pct(row.accuracy)}</td>
            <td>${row.avg_brier == null ? "-" : row.avg_brier.toFixed(3)}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function tuningSuggestionList(rows) {
  if (!rows.length) return `<p class="muted">暂无建议。</p>`;
  return `<ul>${rows.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>`;
}

function renderOverviewRow(item) {
  const summary = item.prediction.summary;
  return `
    <tr>
      <td><strong>${esc(item.home_team)} vs ${esc(item.away_team)}</strong><br><span class="muted">${esc(item.stage)}</span></td>
      <td>${esc(item.kickoff || "-")}</td>
      <td>${esc(conclusionText(item, item.prediction))}</td>
      <td>${summary.score_group.map(esc).join(" / ")}</td>
      <td>${esc(summary.market_direction)}</td>
      <td>${badge(summary.gap_level)}</td>
      <td>${badge(summary.upset_level)}</td>
      <td>${summary.confidence}/100</td>
      <td>${summary.data_score}/100</td>
      <td>
        <button data-refresh="${esc(item.match_id)}">刷新</button>
      </td>
    </tr>
  `;
}

function renderMatch(item) {
  const content = document.getElementById("content");
  const prediction = item.prediction;
  const summary = prediction.summary;
  const baseline = prediction.scenarios.find((s) => s.scenario === "baseline");
  const market = prediction.scenarios.find((s) => s.scenario === "market");
  const picks = topPicks(prediction.sporttery, 4, prediction);
  content.innerHTML = `
    <section class="decision-board">
      <div class="match-hero">
        <div class="hero-head">
          <div>
            <div class="team-line">${esc(item.home_team)} vs ${esc(item.away_team)}</div>
            <div class="kickoff">${esc(formatKickoff(item.kickoff))} · ${esc(item.stage || "世界杯")}</div>
            <div class="rank-line">${esc(fifaRankText(item))}</div>
          </div>
          <div class="headline">${esc(conclusionText(item, prediction))}</div>
        </div>
        <div class="prob-strip">
          <div class="prob-pill home"><span>主胜</span><strong>${pct(market.probabilities.home)}</strong></div>
          <div class="prob-pill draw"><span>平局</span><strong>${pct(market.probabilities.draw)}</strong></div>
          <div class="prob-pill away"><span>客胜</span><strong>${pct(market.probabilities.away)}</strong></div>
        </div>
        <div class="tag-row">
          ${badge(`比分 ${topScoreText(prediction)}`, "blue")}
          ${badge(`置信 ${summary.confidence}/100`, summary.confidence >= 70 ? "green" : summary.confidence >= 55 ? "amber" : "red")}
          ${badge(`爆冷 ${summary.upset_level}`, summary.upset_level === "低" ? "green" : summary.upset_level === "高" ? "red" : "amber")}
          ${badge(`分歧 ${summary.gap_level}`, summary.gap_level === "一致" ? "green" : summary.gap_level === "高分歧" ? "red" : "amber")}
        </div>
        <div class="actions" style="margin-top: 14px; justify-content: flex-start;">
          <button class="secondary" data-tab="overview">返回总览</button>
          <button data-refresh="${esc(item.match_id)}">刷新当前比赛</button>
        </div>
      </div>
      ${renderSharePanel(item, prediction, market)}
    </section>

    <section class="section">
      <h3>预测依据</h3>
      ${renderPredictionBasis(item, prediction)}
    </section>

    <section class="section">
      <h3>非体彩市场参考</h3>
      ${renderMarketContext(prediction)}
    </section>

    <section class="section">
      <h3>官方可买优先项</h3>
      <div class="grid cols-2">
        ${picks.length ? picks.map((row) => renderPickCard(row, `${item.home_team} vs ${item.away_team}`, prediction)).join("") : renderPickCard(null)}
      </div>
      <div class="pick-reason">原则：先看官方体彩是否开售，再看模型概率是否高过官方SP隐含概率。让球玩法必须和比分主线分开解释；反主线选项只作为防穿盘观察。</div>
    </section>

    <section class="section" id="bettingPlanner">
      <h3>下注建议测算</h3>
      ${renderBettingPlanner(item, prediction)}
    </section>

    <section class="grid cols-2">
      <div class="section">
        <h3>胜平负概率</h3>
        <div class="chart">${probabilityBars(baseline, item)}</div>
      </div>
      <div class="section">
        <h3>体彩计算器下单视图</h3>
        ${sportteryCalculatorView(prediction.sporttery)}
      </div>
    </section>

    <section class="section">
      <h3>体彩单项建议池</h3>
      ${sportteryCandidateTable(prediction.sporttery, prediction)}
    </section>

    <section class="grid cols-2">
      <div class="section">
        <h3>比分组合池</h3>
        ${scoreComboPoolTable(prediction.sporttery)}
      </div>
      <div class="section">
        <h3>仓位硬约束</h3>
        ${stakingPolicyTable(prediction.sporttery)}
      </div>
    </section>

    <section class="grid cols-2">
      <div class="section">
        <h3>比分热力图</h3>
        <div class="chart">${scoreHeatmap(baseline)}</div>
      </div>
      <div class="section">
        <h3>进球数分布</h3>
        <div class="chart">${goalDistributionChart(baseline)}</div>
      </div>
    </section>

    <section class="grid cols-2">
      <div class="section">
        <h3>总进球数</h3>
        ${totalGoalsTable(baseline.total_goals)}
      </div>
      <div class="section">
        <h3>总进球区间参考</h3>
        ${overUnderTable(baseline.over_under_lines)}
      </div>
    </section>

    <section class="grid cols-2">
      <div class="section">
        <h3>复选包</h3>
        ${compoundPackageTable(prediction.sporttery)}
      </div>
      <div class="section">
        <h3>放弃清单</h3>
        ${abandonTable(prediction.sporttery)}
      </div>
    </section>

    <section class="grid cols-2">
      <div class="section">
        <h3>9维评分雷达</h3>
        <div class="chart">${radarChart(prediction.dimension_scores, "score")}</div>
      </div>
      <div class="section">
        <h3>爆冷雷达</h3>
        <div class="chart">${upsetRadar(prediction.upset)}</div>
      </div>
    </section>

    <section class="section">
      <h3>六情景预测</h3>
      <div class="scenario-list">
        ${prediction.scenarios.map((scenario) => renderScenario(scenario, item)).join("")}
      </div>
    </section>

    <section class="grid cols-2">
      <div class="section">
        <h3>数据健康</h3>
        ${dataHealthTable(prediction.data_completeness.items)}
      </div>
      <div class="section">
        <h3>中文分析摘要</h3>
        <div class="report">${esc(buildReport(item, prediction, market))}</div>
      </div>
    </section>
  `;
  content.querySelectorAll("button[data-refresh]").forEach((button) => {
    button.addEventListener("click", () => refresh(button.dataset.refresh));
  });
}

function renderBettingPlanner(item, prediction) {
  const modes = [
    { id: "conservative", label: "保守", desc: "少项、方向优先，回报低但波动较小" },
    { id: "standard", label: "推荐", desc: "方向为主，少量比分/总进球增强收益" },
    { id: "aggressive", label: "激进高回报", desc: "加入比分和高赔尾部，只适合小仓位" },
    { id: "longshot", label: "以小博大", desc: "小金额覆盖比分和半全场，不作为主仓" },
  ];
  const amount = Math.max(2, Math.floor(Number(state.stakeAmount || 100) / 2) * 2);
  const mode = modes.find((row) => row.id === state.bettingMode) || modes[1];
  const packageRows = buildBettingPackage(prediction, mode.id, amount);
  const totalStake = packageRows.reduce((sum, row) => sum + row.stake, 0);
  const bestReturn = packageRows.reduce((max, row) => Math.max(max, row.returnAmount), 0);
  const weightedReturn = packageRows.reduce((sum, row) => sum + row.returnAmount * Math.max(row.model_prob || 0, 0), 0);
  return `
    <div class="planner-shell">
      <div class="planner-controls">
        <label>
          预估投入金额
          <input type="number" min="2" step="2" value="${amount}" data-stake-amount />
        </label>
        <div class="planner-tabs">
          ${modes.map((row) => `
            <button class="${row.id === mode.id ? "active" : ""}" data-stake-mode="${row.id}">
              ${esc(row.label)}
            </button>
          `).join("")}
        </div>
      </div>
      <div class="planner-note">
        <strong>${esc(mode.label)}方案：</strong>${esc(mode.desc)}。金额按体彩 2 元一注取整；同场互斥选项不做“全中”假设，返还按命中单项展示。
      </div>
      <div class="grid cols-3">
        <div class="metric"><div class="label">实际拆分投入</div><div class="value">${money(totalStake)}</div><div class="sub">按 2 元取整</div></div>
        <div class="metric"><div class="label">单项最高返还</div><div class="value">${money(bestReturn)}</div><div class="sub">命中其中一项时</div></div>
        <div class="metric"><div class="label">期望返还</div><div class="value">${money(weightedReturn)}</div><div class="sub">单项概率加权合计</div></div>
      </div>
      ${packageRows.length ? bettingPackageTable(packageRows, totalStake) : `<div class="empty-mini">当前缺少可用于测算的官方SP，先刷新或等体彩开售对应玩法。</div>`}
      <p class="muted">提示：让球胜平负很多场不支持单关，页面会标注“至少2串1”。实际下单前以体彩计算器最终可选项为准。</p>
    </div>
  `;
}

function money(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return `${Number(value).toFixed(2)}元`;
}

function bettingPackageTable(rows, totalStake) {
  return `
    <table>
      <thead>
        <tr>
          <th>仓位</th><th>玩法</th><th>选项</th><th>投入</th><th>SP/倍率</th><th>模型概率</th><th>命中返还</th><th>命中盈利</th><th>期望返还</th><th>说明</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map((row) => `
          <tr>
            <td>${esc(row.bucket)}</td>
            <td>${esc(row.play_type)}</td>
            <td><strong>${esc(row.selection)}</strong></td>
            <td>${money(row.stake)}</td>
            <td>${row.sp == null ? "-" : row.sp.toFixed(2)}</td>
            <td>${pct(row.model_prob)}</td>
            <td>${money(row.returnAmount)}</td>
            <td>${money(row.returnAmount - totalStake)}</td>
            <td>${money(row.expectedReturn)}</td>
            <td>${esc(row.note)}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function buildBettingPackage(prediction, mode, amount) {
  const rows = suggestedBetRows(prediction, mode);
  if (!rows.length) return [];
  const usableCount = Math.min(rows.length, Math.floor(amount / 2));
  const selected = rows.slice(0, Math.max(1, usableCount));
  const stakes = splitStake(amount, selected.map((row) => row.weight || 1));
  return selected.map((row, index) => {
    const stake = stakes[index] || 0;
    return {
      ...row,
      stake,
      returnAmount: row.sp ? stake * row.sp : 0,
      expectedReturn: row.sp ? stake * row.sp * Math.max(row.model_prob || 0, 0) : 0,
    };
  }).filter((row) => row.stake > 0);
}

function suggestedBetRows(prediction, mode) {
  const sporttery = prediction.sporttery || {};
  const allRows = uniqueBetRows([...(sporttery.candidate_pool || []), ...(sporttery.options || [])])
    .filter((row) => row.sp && row.sp > 1 && isOfficialSportteryBet(row))
    .map((row) => ({
      ...row,
      note: betRowNote(row),
      weight: baseBetWeight(row),
    }));
  const direction = allRows
    .filter((row) => !["比分", "半全场"].includes(row.play_type))
    .sort((a, b) => betSortScore(b) - betSortScore(a));
  const scores = allRows
    .filter((row) => row.play_type === "比分")
    .sort((a, b) => scoreOptionSort(a, b));
  const totals = allRows
    .filter((row) => row.play_type === "总进球")
    .sort((a, b) => betSortScore(b) - betSortScore(a));

  if (mode === "conservative") {
    return direction.slice(0, 3).map((row, index) => ({
      ...row,
      bucket: index === 0 ? "主仓" : "保护",
      weight: index === 0 ? 7 : 3,
    }));
  }
  if (mode === "aggressive") {
    return [
      ...direction.slice(0, 2).map((row, index) => ({ ...row, bucket: index === 0 ? "方向" : "保护", weight: index === 0 ? 4 : 2 })),
      ...scores.slice(0, 4).map((row) => ({ ...row, bucket: "比分高回报", weight: 1 })),
      ...totals.slice(0, 1).map((row) => ({ ...row, bucket: "总进球", weight: 1 })),
    ];
  }
  if (mode === "longshot") {
    const halfFull = allRows
      .filter((row) => row.play_type === "半全场")
      .sort((a, b) => betSortScore(b) - betSortScore(a));
    return [
      ...direction.slice(0, 1).map((row) => ({ ...row, bucket: "方向底仓", weight: 3 })),
      ...scores.slice(0, 5).map((row) => ({ ...row, bucket: "比分小博", weight: 1 })),
      ...halfFull.slice(0, 2).map((row) => ({ ...row, bucket: "半全场小博", weight: 1 })),
      ...totals.slice(0, 1).map((row) => ({ ...row, bucket: "总进球", weight: 1 })),
    ];
  }
  return [
    ...direction.slice(0, 2).map((row, index) => ({ ...row, bucket: index === 0 ? "主仓" : "保护", weight: index === 0 ? 6 : 3 })),
    ...scores.slice(0, 2).map((row) => ({ ...row, bucket: "比分小仓", weight: 1 })),
    ...totals.slice(0, 1).map((row) => ({ ...row, bucket: "总进球", weight: 1 })),
  ];
}

function uniqueBetRows(rows) {
  const seen = new Set();
  return rows.filter((row) => {
    const key = `${row.play_type}|${row.selection}|${row.sp ?? ""}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function isOfficialSportteryBet(row) {
  const source = String(row.sp_source || row.source || "");
  return source.includes("sporttery_official");
}

function betSortScore(row) {
  const ev = row.ev == null ? -0.2 : row.ev;
  const risk = row.risk_score == null ? 50 : row.risk_score;
  const prob = row.model_prob || 0;
  const priority = row.mapping_priority || 0;
  return priority * 2 + prob * 5 + ev * 3 - risk / 100;
}

function baseBetWeight(row) {
  if (row.play_type === "胜平负") return 5;
  if (row.play_type === "让球胜平负") return 4;
  if (row.play_type === "总进球") return 2;
  if (row.play_type === "比分") return 1;
  return 1;
}

function betRowNote(row) {
  const single = row.single_allowed === false ? `至少${row.min_legs || 2}串1` : "可单关";
  const rule = (row.rule_notes || []).join("；") || row.reason || row.score_note || "按模型概率和官方SP筛选";
  return `${single}；${rule}`;
}

function splitStake(amount, weights) {
  const total = Math.max(0, Math.floor(Number(amount || 0) / 2) * 2);
  if (!weights.length || total < 2) return [];
  const sumWeights = weights.reduce((sum, item) => sum + Math.max(item, 0), 0) || weights.length;
  const stakes = weights.map((weight) => Math.floor((total * Math.max(weight, 0) / sumWeights) / 2) * 2);
  let used = stakes.reduce((sum, item) => sum + item, 0);
  for (let i = 0; i < stakes.length && used + 2 <= total; i += 1) {
    stakes[i] += 2;
    used += 2;
  }
  return stakes;
}

function renderScenario(scenario, item) {
  const top = scenario.top_scores.slice(0, 3).map((row) => `${row.score}(${pct(row.probability, 1)})`).join(" / ");
  return `
    <div class="scenario">
      <h4>${esc(scenario.label)}</h4>
      ${probRows(scenario.probabilities)}
      <div class="muted">比分：${esc(top)}</div>
      <div class="muted">xG：${scenario.expected_goals.home.toFixed(2)} - ${scenario.expected_goals.away.toFixed(2)}</div>
      <div class="muted">大2.5：${pct(scenario.over_25)} · BTTS：${pct(scenario.btts)}</div>
      ${scenario.notes.length ? `<div class="muted">注：${esc(scenario.notes.join("；"))}</div>` : ""}
    </div>
  `;
}

function valueModelTable(valueModel) {
  if (!valueModel) return `<p class="muted">暂无官方SP价值模型。</p>`;
  const rows = ["home", "draw", "away"].map((key) => `
    <tr>
      <td>${labels[key]}</td>
      <td>${pct(valueModel.market_probs[key])}</td>
      <td>${Number(valueModel.deltas[key] || 0).toFixed(3)}</td>
      <td><strong>${pct(valueModel.probabilities[key])}</strong></td>
      <td>${valueModel.probabilities[key] ? (1 / valueModel.probabilities[key]).toFixed(2) : "-"}</td>
    </tr>
  `).join("");
  const scores = (valueModel.top_scores || []).slice(0, 3).map((row) => `${row.score} ${pct(row.probability)}`).join(" / ");
  return `
    <table>
      <thead><tr><th>结果</th><th>市场去水</th><th>Δ修正</th><th>模型概率</th><th>公允SP</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <p class="muted">价值层比分：${esc(scores)}；模型口径：市场去水概率 + 小幅基本面修正 + softmax。</p>
  `;
}

function sportteryCandidateTable(sporttery, prediction = null) {
  const rows = sporttery?.candidate_pool || [];
  if (!rows.length) {
    return `<p class="muted">暂无正向候选。若缺少体彩SP，请先录入对应玩法SP；只有胜平负可能使用市场赔率代理。</p>`;
  }
  return `
    <p class="muted">${esc(sporttery.settlement)}；让球数 H=${sporttery.handicap ?? 0}</p>
    <table>
      <thead><tr><th>玩法</th><th>选项</th><th>SP</th><th>模型</th><th>公允</th><th>EV</th><th>风险</th><th>动作</th></tr></thead>
      <tbody>
        ${rows.slice(0, 10).map((row) => `
          <tr>
            <td>${esc(row.play_type)}</td>
            <td><strong>${esc(row.selection)}</strong></td>
            <td>${row.sp == null ? "-" : row.sp.toFixed(2)}<br><span class="muted">${esc(row.sp_source || "")}</span></td>
            <td>${pct(row.model_prob)}</td>
            <td>${row.fair_sp == null ? "-" : row.fair_sp.toFixed(2)}</td>
            <td>${row.ev == null ? "-" : pct(row.ev)}</td>
            <td>${row.risk_score}<br>${badge(row.risk_level)}</td>
            <td>${esc(row.decision)}<br><span class="muted">${esc([row.reason, pickContextNote(row, prediction)].filter(Boolean).join("；"))}</span></td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function sportteryCalculatorView(sporttery) {
  const options = sporttery?.options || [];
  const hText = sporttery?.handicap == null ? "未抓到/未配置" : sporttery.handicap > 0 ? `受让${sporttery.handicap}球` : `让${Math.abs(sporttery.handicap)}球`;
  const tabs = [
    { label: "胜平负/让球胜平负", plays: ["胜平负", "让球胜平负"] },
    { label: "比分", plays: ["比分"] },
    { label: "总进球数", plays: ["总进球"] },
    { label: "半全场", plays: ["半全场"] },
  ];
  return `
    <p class="muted">对齐 体彩足球计算器：${esc(sporttery?.settlement || "90分钟含伤停补时")}；本场让球：${esc(hText)}。</p>
    <div class="calculator-tabs">
      ${tabs.map((tab) => {
        const rows = options
          .filter((row) => tab.plays.includes(row.play_type))
          .sort(calculatorOptionSort)
          .slice(0, 6);
        return `
          <div class="calculator-tab-card">
            <h4>${esc(tab.label)}</h4>
            ${calculatorOptionTable(rows)}
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function calculatorOptionSort(a, b) {
  if (a.play_type === "比分" && b.play_type === "比分") {
    return scoreOptionSort(a, b);
  }
  const mappingDiff = (b.mapping_priority || 0) - (a.mapping_priority || 0);
  if (mappingDiff) return mappingDiff;
  const decisionRank = { "可小注": 5, "观察": 4, "高风险观察": 3, "不可用": 2, "放弃": 1 };
  const aRank = decisionRank[a.decision] || 0;
  const bRank = decisionRank[b.decision] || 0;
  if (aRank !== bRank) return bRank - aRank;
  const aScore = a.risk_adjusted_score ?? -999;
  const bScore = b.risk_adjusted_score ?? -999;
  if (aScore !== bScore) return bScore - aScore;
  return (b.model_prob || 0) - (a.model_prob || 0);
}

function scoreOptionSort(a, b) {
  const priorityDiff = (b.score_priority || 0) - (a.score_priority || 0);
  if (priorityDiff) return priorityDiff;
  const probabilityDiff = (b.model_prob || 0) - (a.model_prob || 0);
  if (Math.abs(probabilityDiff) > 0.002) return probabilityDiff;
  const evDiff = (b.ev ?? -9) - (a.ev ?? -9);
  if (Math.abs(evDiff) > 0.05) return evDiff;
  return 0;
}

function minBuySp(row) {
  if (!row?.fair_sp) return "-";
  const threshold = row.play_type === "比分" || row.play_type === "半全场" ? 1.10 : row.play_type === "总进球" ? 1.06 : 1.05;
  return (row.fair_sp * threshold).toFixed(2);
}

function calculatorAction(row) {
  if (!row) return "-";
  if (row.sp == null) return `等奖金 >= ${minBuySp(row)}`;
  if (row.ev != null && row.ev > 0 && ["可小注", "观察", "高风险观察"].includes(row.decision)) return row.decision;
  return `低于线，>= ${minBuySp(row)}再看`;
}

function calculatorOptionTable(rows) {
  if (!rows.length) return `<p class="muted">暂无该玩法选项。</p>`;
  return `
    <table class="compact-table">
      <thead><tr><th>玩法</th><th>选择</th><th>方式</th><th>SP/倍率</th><th>概率</th><th>合理线</th><th>动作</th></tr></thead>
      <tbody>
        ${rows.map((row) => `
          <tr>
            <td>${esc(row.play_type)}</td>
            <td><strong>${esc(row.selection)}</strong></td>
            <td>${row.single_allowed === false ? `至少${row.min_legs || 2}串1` : "可单关"}</td>
            <td>${row.sp == null ? "未抓到" : row.sp.toFixed(2)}</td>
            <td>${pct(row.model_prob)}</td>
            <td>${row.fair_sp == null ? "-" : row.fair_sp.toFixed(2)}</td>
            <td>${esc(calculatorAction(row))}<br><span class="muted">${esc((row.rule_notes || []).join("；") || row.score_note || row.reason || "")}</span></td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function compoundPackageTable(sporttery) {
  const rows = sporttery?.compound_packages || [];
  if (!rows.length) return `<p class="muted">暂无复选包。</p>`;
  return `
    <table>
      <thead><tr><th>复选包</th><th>选项</th><th>命中率</th><th>注数</th><th>EV</th><th>动作</th></tr></thead>
      <tbody>
        ${rows.map((row) => `
          <tr>
            <td>${esc(row.name)}</td>
            <td>${esc((row.options || []).join(" + ") || row.reason || "-")}</td>
            <td>${row.hit_prob == null ? "-" : pct(row.hit_prob)}</td>
            <td>${row.num_bets ?? "-"}</td>
            <td>${row.ev == null ? "-" : pct(row.ev)}</td>
            <td>${esc(row.decision)}<br><span class="muted">${esc(row.reason || "")}</span></td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function scoreComboPoolTable(sporttery) {
  const rows = sporttery?.score_combo_pools || [];
  if (!rows.length) return `<p class="muted">暂无比分组合池。通常是缺少比分SP，或该场不适合比分玩法。</p>`;
  return `
    <table>
      <thead><tr><th>组合池</th><th>比分</th><th>覆盖概率</th><th>EV均值</th><th>动作</th></tr></thead>
      <tbody>
        ${rows.map((row) => `
          <tr>
            <td><strong>${esc(row.name)}</strong><br><span class="muted">${esc(row.reason || "")}</span></td>
            <td>${esc((row.selections || []).join(" / "))}</td>
            <td>${pct(row.hit_prob)}</td>
            <td>${row.avg_ev == null ? "-" : pct(row.avg_ev)}</td>
            <td>${esc(row.action)}<br><span class="muted">最高风险 ${row.max_risk ?? "-"}</span></td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function stakingPolicyTable(sporttery) {
  const policy = sporttery?.staking_policy;
  if (!policy) return `<p class="muted">暂无仓位策略。</p>`;
  return `
    <table>
      <tbody>
        <tr><th>方向主仓下限</th><td>${pct(policy.direction_min)}</td></tr>
        <tr><th>比分总仓上限</th><td>${pct(policy.score_cap)}</td></tr>
        <tr><th>单比分上限</th><td>${pct(policy.single_score_cap)}</td></tr>
        <tr><th>比分串上限</th><td>${pct(policy.score_combo_cap)}</td></tr>
        <tr><th>深盘尾部保护上限</th><td>${pct(policy.deep_tail_cap)}</td></tr>
      </tbody>
    </table>
    <ul>${(policy.hard_rules || []).map((rule) => `<li>${esc(rule)}</li>`).join("")}</ul>
  `;
}

function abandonTable(sporttery) {
  const rows = sporttery?.abandon_list || [];
  if (!rows.length) return `<p class="muted">暂无放弃项。</p>`;
  return `
    <table>
      <thead><tr><th>玩法</th><th>选项</th><th>模型</th><th>SP</th><th>EV</th><th>原因</th></tr></thead>
      <tbody>
        ${rows.slice(0, 12).map((row) => `
          <tr>
            <td>${esc(row.play_type)}</td>
            <td>${esc(row.selection)}</td>
            <td>${pct(row.model_prob)}</td>
            <td>${row.sp == null ? "-" : row.sp.toFixed(2)}</td>
            <td>${row.ev == null ? "-" : pct(row.ev)}</td>
            <td>${esc(row.reason)}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function probRows(probs) {
  return ["home", "draw", "away"].map((key) => `
    <div class="prob-row">
      <span>${labels[key]}</span>
      <div class="bar"><span style="width:${Math.max(0, Math.min(100, probs[key] * 100))}%; background:${colors[key]}"></span></div>
      <strong>${pct(probs[key], 0)}</strong>
    </div>
  `).join("");
}

function probabilityBars(scenario) {
  const entries = ["home", "draw", "away"];
  const width = 680;
  const height = 240;
  const max = Math.max(...entries.map((k) => scenario.probabilities[k]), 0.01);
  const bars = entries.map((key, i) => {
    const x = 120;
    const y = 42 + i * 58;
    const w = (scenario.probabilities[key] / max) * 480;
    return `
      <text x="24" y="${y + 18}" font-size="14" fill="#334155">${labels[key]}</text>
      <rect x="${x}" y="${y}" width="480" height="28" rx="5" fill="#e2e8f0"></rect>
      <rect x="${x}" y="${y}" width="${w}" height="28" rx="5" fill="${colors[key]}"></rect>
      <text x="${x + w + 12}" y="${y + 19}" font-size="13" fill="#172033">${pct(scenario.probabilities[key])}</text>
    `;
  }).join("");
  return `<svg viewBox="0 0 ${width} ${height}" role="img">${bars}</svg>`;
}

function oddsLineChart(history) {
  const rows = history.filter((row) => row.market === "h2h");
  if (!rows.length) return emptyChart("暂无赔率快照，点击刷新写入第一组数据");
  const times = [...new Set(rows.map((row) => row.captured_at))].sort();
  const points = { home: [], draw: [], away: [] };
  times.forEach((ts) => {
    const odds = {};
    rows.filter((row) => row.captured_at === ts).forEach((row) => {
      odds[row.selection] = odds[row.selection] || [];
      odds[row.selection].push(row.odds_decimal);
    });
    ["home", "draw", "away"].forEach((key) => {
      if (odds[key]) {
        const avgOdd = odds[key].reduce((a, b) => a + b, 0) / odds[key].length;
        points[key].push({ ts, value: 1 / avgOdd });
      }
    });
  });
  const allValues = Object.values(points).flat().map((p) => p.value);
  const min = Math.min(...allValues) * 0.94;
  const max = Math.max(...allValues) * 1.06;
  const width = 720;
  const height = 260;
  const plot = { x: 52, y: 24, w: 620, h: 185 };
  const toX = (idx) => plot.x + (times.length <= 1 ? plot.w / 2 : idx * plot.w / (times.length - 1));
  const toY = (v) => plot.y + plot.h - ((v - min) / (max - min || 1)) * plot.h;
  const paths = ["home", "draw", "away"].map((key) => {
    const d = points[key].map((point, idx) => `${idx === 0 ? "M" : "L"} ${toX(times.indexOf(point.ts))} ${toY(point.value)}`).join(" ");
    const circles = points[key].map((point) => `<circle cx="${toX(times.indexOf(point.ts))}" cy="${toY(point.value)}" r="3" fill="${colors[key]}"></circle>`).join("");
    return `<path d="${d}" fill="none" stroke="${colors[key]}" stroke-width="3"></path>${circles}`;
  }).join("");
  const legend = ["home", "draw", "away"].map((key, i) => `
    <rect x="${plot.x + i * 92}" y="224" width="12" height="12" fill="${colors[key]}"></rect>
    <text x="${plot.x + 18 + i * 92}" y="235" font-size="12" fill="#334155">${labels[key]}</text>
  `).join("");
  return `<svg viewBox="0 0 ${width} ${height}">
    <rect x="${plot.x}" y="${plot.y}" width="${plot.w}" height="${plot.h}" fill="#f8fafc" stroke="#d8dee8"></rect>
    <text x="10" y="28" font-size="12" fill="#667085">隐含概率</text>
    ${paths}
    ${legend}
  </svg>`;
}

function scoreHeatmap(scenario) {
  const grid = scenario.score_grid?.length ? scenario.score_grid : scenario.top_scores;
  const map = new Map(grid.map((row) => [row.score, row.probability]));
  const max = Math.max(...grid.map((row) => row.probability), 0.01);
  const cells = [];
  for (let h = 0; h <= 4; h += 1) {
    for (let a = 0; a <= 4; a += 1) {
      const score = `${h}-${a}`;
      const p = map.get(score) || 0;
      const intensity = Math.round(245 - (p / max) * 105);
      const fill = `rgb(${intensity}, ${Math.min(248, intensity + 10)}, 255)`;
      cells.push(`
        <rect x="${86 + a * 92}" y="${34 + h * 40}" width="82" height="32" rx="5" fill="${fill}" stroke="#d8dee8"></rect>
        <text x="${127 + a * 92}" y="${55 + h * 40}" text-anchor="middle" font-size="12" fill="#172033">${score} ${p ? pct(p, 1) : ""}</text>
      `);
    }
  }
  return `<svg viewBox="0 0 610 250">
    <text x="18" y="24" font-size="12" fill="#667085">主队进球 ↓ / 客队进球 →</text>
    ${cells.join("")}
  </svg>`;
}

function goalDistributionChart(scenario) {
  const width = 640;
  const height = 250;
  const max = Math.max(...scenario.goal_distribution.map((row) => row.probability), 0.01);
  const bars = scenario.goal_distribution.map((row, i) => {
    const barH = row.probability / max * 155;
    const x = 58 + i * 92;
    const y = 198 - barH;
    return `
      <rect x="${x}" y="${y}" width="44" height="${barH}" rx="5" fill="#0f766e"></rect>
      <text x="${x + 22}" y="222" text-anchor="middle" font-size="12" fill="#334155">${esc(row.goals)}</text>
      <text x="${x + 22}" y="${y - 8}" text-anchor="middle" font-size="12" fill="#172033">${pct(row.probability, 0)}</text>
    `;
  }).join("");
  return `<svg viewBox="0 0 ${width} ${height}">
    <text x="20" y="26" font-size="12" fill="#667085">总进球数概率</text>
    ${bars}
  </svg>`;
}

function totalGoalsTable(totalGoals) {
  if (!totalGoals) return `<p class="muted">暂无总进球数据。</p>`;
  return `
    <table>
      <tbody>
        <tr><th>最可能总进球</th><td>${esc(totalGoals.most_likely)}球</td></tr>
        <tr><th>推荐区间</th><td>${esc(totalGoals.best_range)}球</td></tr>
        <tr><th>低比分风险</th><td>${esc(totalGoals.low_score_risk)}</td></tr>
        <tr><th>大比分风险</th><td>${esc(totalGoals.high_score_risk)}</td></tr>
      </tbody>
    </table>
    <table style="margin-top: 10px;">
      <thead><tr><th>总进球</th><th>概率</th></tr></thead>
      <tbody>
        ${totalGoals.exact.map((row) => `<tr><td>${esc(row.goals)}球</td><td>${pct(row.probability)}</td></tr>`).join("")}
      </tbody>
    </table>
  `;
}

function overUnderTable(lines) {
  if (!lines?.length) return `<p class="muted">暂无大小球数据。</p>`;
  return `
    <table>
      <thead><tr><th>总进球线</th><th>大球概率</th><th>小球概率</th><th>倾向</th></tr></thead>
      <tbody>
        ${lines.map((row) => `
          <tr>
            <td>${row.line}</td>
            <td>${pct(row.over)}</td>
            <td>${pct(row.under)}</td>
            <td>${esc(row.lean)}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function radarChart(rows) {
  const labels = rows.map((row) => row.label.split(" / ")[0]);
  const values = rows.map((row) => (row.score + 3) / 6);
  return radarSvg(labels, values, "#2563eb");
}

function upsetRadar(upset) {
  const active = new Map(upset.active.map((item) => [item.key, item.weight]));
  const keys = [
    ["underdog_low_block", "低位"],
    ["underdog_counter_speed", "反击"],
    ["underdog_set_piece", "定位球"],
    ["underdog_goalkeeper", "门将"],
    ["strong_low_block_problem", "破密防"],
    ["strong_fatigue", "体能"],
    ["weather_pitch_against_technical", "环境"],
  ];
  const values = keys.map(([key]) => Math.min(1, active.get(key) || 0));
  return radarSvg(keys.map(([, label]) => label), values, "#dc2626");
}

function radarSvg(labels, values, stroke) {
  const width = 520;
  const height = 260;
  const cx = 260;
  const cy = 130;
  const r = 88;
  const n = labels.length;
  const point = (i, scale = 1) => {
    const angle = -Math.PI / 2 + i * 2 * Math.PI / n;
    return [cx + Math.cos(angle) * r * scale, cy + Math.sin(angle) * r * scale];
  };
  const rings = [0.33, 0.66, 1].map((scale) => {
    const d = labels.map((_, i) => point(i, scale)).map((p, i) => `${i === 0 ? "M" : "L"} ${p[0]} ${p[1]}`).join(" ") + " Z";
    return `<path d="${d}" fill="none" stroke="#d8dee8"></path>`;
  }).join("");
  const axes = labels.map((label, i) => {
    const [x, y] = point(i, 1);
    const [tx, ty] = point(i, 1.22);
    return `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="#e2e8f0"></line>
      <text x="${tx}" y="${ty}" text-anchor="middle" dominant-baseline="middle" font-size="11" fill="#334155">${esc(label)}</text>`;
  }).join("");
  const d = values.map((value, i) => point(i, value)).map((p, i) => `${i === 0 ? "M" : "L"} ${p[0]} ${p[1]}`).join(" ") + " Z";
  return `<svg viewBox="0 0 ${width} ${height}">
    ${rings}${axes}
    <path d="${d}" fill="${stroke}22" stroke="${stroke}" stroke-width="3"></path>
  </svg>`;
}

function divergenceChart(matches) {
  if (!matches.length) return emptyChart("暂无比赛");
  const rows = matches.map((item, i) => {
    const gap = item.prediction.model_market_gap.max_gap || 0;
    const w = Math.min(1, gap / 0.15) * 360;
    const y = 42 + i * 46;
    return `
      <text x="20" y="${y + 16}" font-size="12" fill="#334155">${esc(item.home_team)} vs ${esc(item.away_team)}</text>
      <rect x="190" y="${y}" width="360" height="24" rx="5" fill="#e2e8f0"></rect>
      <rect x="190" y="${y}" width="${w}" height="24" rx="5" fill="#7c3aed"></rect>
      <text x="${560}" y="${y + 17}" font-size="12" fill="#172033">${pct(gap)}</text>
    `;
  }).join("");
  return `<svg viewBox="0 0 650 250">${rows}</svg>`;
}

function dataScoreChart(matches) {
  if (!matches.length) return emptyChart("暂无比赛");
  const rows = matches.map((item, i) => {
    const score = item.prediction.data_completeness.score;
    const w = score / 100 * 360;
    const y = 42 + i * 46;
    const color = score >= 75 ? "#16a34a" : score >= 55 ? "#b45309" : "#dc2626";
    return `
      <text x="20" y="${y + 16}" font-size="12" fill="#334155">${esc(item.home_team)} vs ${esc(item.away_team)}</text>
      <rect x="190" y="${y}" width="360" height="24" rx="5" fill="#e2e8f0"></rect>
      <rect x="190" y="${y}" width="${w}" height="24" rx="5" fill="${color}"></rect>
      <text x="560" y="${y + 17}" font-size="12" fill="#172033">${score}/100</text>
    `;
  }).join("");
  return `<svg viewBox="0 0 650 250">${rows}</svg>`;
}

function dataHealthTable(items) {
  return `
    <table>
      <thead><tr><th>数据项</th><th>状态</th><th>权重</th></tr></thead>
      <tbody>
        ${items.map((item) => `<tr><td>${esc(item.name)}</td><td>${item.ok ? badge("已确认", "green") : badge("缺失/待确认", "amber")}</td><td>${item.weight}</td></tr>`).join("")}
      </tbody>
    </table>
  `;
}

function sourceHealthTable(sources, health) {
  if (!sources.length) return `<p class="muted">暂无数据源配置。</p>`;
  return `
    <table>
      <thead>
        <tr>
          <th>数据源</th>
          <th>类型</th>
          <th>状态</th>
          <th>可靠性</th>
          <th>成功/失败</th>
          <th>最近成功</th>
          <th>最近错误</th>
        </tr>
      </thead>
      <tbody>
        ${sources.map((source) => {
          const item = health[source.source_id] || {};
          const enabled = source.enabled ? badge("启用", "green") : badge("停用", "amber");
          return `
            <tr>
              <td><strong>${esc(source.name || source.source_id)}</strong><br><span class="muted">${esc(source.source_id)}</span></td>
              <td>${esc(source.type)}</td>
              <td>${enabled}</td>
              <td>${esc(source.reliability || "-")}</td>
              <td>${item.success_count || 0} / ${item.failure_count || 0}</td>
              <td>${esc(item.last_success_at || "-")}</td>
              <td>${esc(item.last_error || "-")}</td>
            </tr>
          `;
        }).join("")}
      </tbody>
    </table>
  `;
}

function globalComboTable(rows) {
  if (!rows.length) return `<p class="muted">暂无可串候选。串关只从正EV且有SP的候选项生成；缺少体彩SP时不会硬串。</p>`;
  return `
    <table>
      <thead><tr><th>组合</th><th>腿</th><th>概率</th><th>组合SP</th><th>EV</th><th>风险</th><th>动作</th></tr></thead>
      <tbody>
        ${rows.slice(0, 12).map((row) => `
          <tr>
            <td>${esc(row.combo_id)}<br>${esc(row.type)}</td>
            <td>${row.legs.map((leg) => `${esc(leg.match)}｜${esc(leg.play_type)} ${esc(leg.selection)} @${Number(leg.sp).toFixed(2)}`).join("<br>")}</td>
            <td>${pct(row.probability)}</td>
            <td>${Number(row.sp).toFixed(2)}</td>
            <td>${pct(row.ev)}</td>
            <td>${row.risk_score}</td>
            <td>${esc(row.decision)}<br><span class="muted">${esc(row.reason)}</span></td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function buildReport(item, prediction, marketScenario) {
  const s = prediction.summary;
  const active = prediction.upset.active.map((x) => x.label).join("、") || "暂无明显触发器";
  const scores = marketScenario.top_scores.slice(0, 4).map((x) => x.score).join(" / ");
  return [
    `比赛：${item.home_team} vs ${item.away_team}`,
    ``,
    `主结论：${conclusionText(item, prediction)}`,
    `基准比分组：${s.score_group.join(" / ")}`,
    `市场方向：${s.market_direction}`,
    `模型/市场分歧：${s.gap_level}`,
    `爆冷等级：${s.upset_level}`,
    `数据完整度：${s.data_score}/100`,
    ``,
    `市场修正版概率：主胜 ${pct(marketScenario.probabilities.home)}，平局 ${pct(marketScenario.probabilities.draw)}，客胜 ${pct(marketScenario.probabilities.away)}。`,
    `市场修正版比分：${scores}`,
    `爆冷路径：${active}`,
    ``,
    `风险提示：首发、伤停、天气、裁判和临场赔率如果未确认，最终置信度需要下调。`,
  ].join("\n");
}

function emptyChart(text) {
  return `<svg viewBox="0 0 520 250">
    <text x="260" y="128" text-anchor="middle" fill="#667085">${esc(text)}</text>
  </svg>`;
}

document.getElementById("refreshAll").addEventListener("click", () => refresh());
document.getElementById("reloadState").addEventListener("click", () => loadState());
document.addEventListener("click", (event) => {
  const target = event.target.closest("button[data-refresh]");
  if (target) {
    event.stopPropagation();
    refresh(target.dataset.refresh);
    return;
  }
  const postTarget = event.target.closest("button[data-post]");
  if (postTarget) {
    event.stopPropagation();
    postAction(postTarget.dataset.post, postTarget.dataset.message || "操作完成");
    return;
  }
  const selectTarget = event.target.closest("button[data-select-fixture]");
  if (selectTarget) {
    event.stopPropagation();
    selectFixture(selectTarget.dataset.selectFixture, selectTarget.dataset.selectMode || "single");
    return;
  }
  const tabTarget = event.target.closest("button[data-tab]");
  if (tabTarget && !tabTarget.closest("#tabs")) {
    state.active = tabTarget.dataset.tab;
    render();
    return;
  }
  const openMatch = event.target.closest("button[data-open-match]");
  if (openMatch) {
    event.stopPropagation();
    state.active = openMatch.dataset.openMatch;
    render();
    return;
  }
  const openBetting = event.target.closest("button[data-open-betting]");
  if (openBetting) {
    event.stopPropagation();
    state.active = openBetting.dataset.openBetting;
    render();
    requestAnimationFrame(() => document.getElementById("bettingPlanner")?.scrollIntoView({ behavior: "smooth", block: "start" }));
    return;
  }
  const stakeMode = event.target.closest("button[data-stake-mode]");
  if (stakeMode) {
    event.stopPropagation();
    state.bettingMode = stakeMode.dataset.stakeMode;
    render();
    requestAnimationFrame(() => document.getElementById("bettingPlanner")?.scrollIntoView({ block: "start" }));
    return;
  }
  const cardTarget = event.target.closest("[data-open-card]");
  if (cardTarget) {
    state.active = cardTarget.dataset.openCard;
    render();
  }
});

document.addEventListener("change", (event) => {
  const input = event.target.closest("input[data-stake-amount]");
  if (!input) return;
  state.stakeAmount = Math.max(2, Number(input.value || 2));
  render();
  requestAnimationFrame(() => document.getElementById("bettingPlanner")?.scrollIntoView({ block: "start" }));
});

document.addEventListener("input", (event) => {
  const input = event.target.closest("input[data-stake-amount]");
  if (!input) return;
  state.stakeAmount = Math.max(2, Number(input.value || 2));
});

loadState().catch((error) => {
  document.getElementById("content").innerHTML = `<section class="section"><h2>加载失败</h2><p>${esc(error.message)}</p></section>`;
});
