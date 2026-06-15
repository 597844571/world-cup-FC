import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "C:/Users/59784/Documents/Codex/2026-06-13/import-pandas-as-pd-from-openpyxl/outputs";
const outputFile = path.join(outputDir, "下一组4场_体彩玩法对齐分析报告_德国荷兰科特迪瓦瑞典.xlsx");
const stateUrl = "http://127.0.0.1:8765/api/state";

const playOrder = {
  "胜平负": ["胜", "平", "负"],
  "让球胜平负": ["让胜", "让平", "让负"],
  "总进球": ["0", "1", "2", "3", "4", "5", "6", "7+"],
  "半全场": ["胜胜", "胜平", "胜负", "平胜", "平平", "平负", "负胜", "负平", "负负"],
  "比分": [
    "1:0", "2:0", "2:1", "3:0", "3:1", "3:2", "4:0", "4:1", "4:2", "5:0", "5:1", "5:2", "胜其它",
    "0:0", "1:1", "2:2", "3:3", "平其它",
    "0:1", "0:2", "1:2", "0:3", "1:3", "2:3", "0:4", "1:4", "2:4", "0:5", "1:5", "2:5", "负其它",
  ],
};

function setup(ws) {
  ws.showGridLines = false;
  ws.freezePanes.freezeRows(1);
}

function styleRange(ws, range) {
  ws.getRange(range).format.borders = { preset: "all", style: "thin", color: "#D8DEE8" };
  ws.getRange(range).format.wrapText = true;
  ws.getRange(range).format.verticalAlignment = "top";
}

function header(ws, range, fill = "#172033") {
  ws.getRange(range).format = {
    fill,
    font: { bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "middle",
    wrapText: true,
  };
}

function title(ws, range, text, fill = "#111827") {
  ws.getRange(range).merge();
  ws.getRange(range).values = [[text]];
  ws.getRange(range).format = {
    fill,
    font: { bold: true, color: "#FFFFFF", size: 14 },
    horizontalAlignment: "left",
    verticalAlignment: "middle",
  };
}

function pct(value) {
  return value == null || value === "" ? "" : Number(value);
}

function fmtPct(value) {
  return value == null ? "-" : `${(Number(value) * 100).toFixed(1)}%`;
}

function fmtTime(iso) {
  if (!iso) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso)).replace(/\//g, "-");
}

function byPlay(match, playType) {
  const rows = match.prediction?.sporttery?.options || [];
  const order = new Map((playOrder[playType] || []).map((item, idx) => [item, idx]));
  return rows
    .filter((row) => row.play_type === playType)
    .sort((a, b) => {
      if (playType === "比分") return scoreOptionSort(a, b, order);
      const decisionRank = { "可小注": 4, "观察": 3, "高风险观察": 2, "放弃": 1, "不可用": 0 };
      const aScore = (decisionRank[a.decision] || 0) * 10 + (a.ev ?? -9) - (a.risk_score ?? 80) * 0.002;
      const bScore = (decisionRank[b.decision] || 0) * 10 + (b.ev ?? -9) - (b.risk_score ?? 80) * 0.002;
      return bScore - aScore || (order.get(a.selection) ?? 999) - (order.get(b.selection) ?? 999);
    })
    .slice(0, 6);
}

function scoreOptionSort(a, b, order) {
  const priorityDiff = (b.score_priority ?? 0) - (a.score_priority ?? 0);
  if (priorityDiff) return priorityDiff;
  const probabilityDiff = (b.model_prob ?? 0) - (a.model_prob ?? 0);
  if (Math.abs(probabilityDiff) > 0.002) return probabilityDiff;
  const evDiff = (b.ev ?? -9) - (a.ev ?? -9);
  if (Math.abs(evDiff) > 0.05) return evDiff;
  return (order.get(a.selection) ?? 999) - (order.get(b.selection) ?? 999);
}

function isOfficial(option) {
  return option?.sp_source === "sporttery_mobile_calculator";
}

function compactMainCandidates(match) {
  const options = match.prediction?.sporttery?.options || [];
  const main = options
    .filter((row) => row.sp && row.ev != null && row.ev > 0 && ["胜平负", "让球胜平负", "总进球"].includes(row.play_type))
    .sort((a, b) => {
      const priority = { "胜平负": 3, "让球胜平负": 2, "总进球": 1 };
      return (b.mapping_priority || 0) - (a.mapping_priority || 0)
        || (priority[b.play_type] || 0) - (priority[a.play_type] || 0)
        || b.ev - a.ev;
    });
  const highRisk = options
    .filter((row) => row.sp && row.ev != null && row.ev > -0.08 && ["比分", "半全场"].includes(row.play_type))
    .sort((a, b) => {
      if (a.play_type === "比分" && b.play_type === "比分") return scoreOptionSort(a, b, new Map());
      return b.ev - a.ev;
    })
    .slice(0, 2);
  return { main: main.slice(0, 4), highRisk };
}

function lowRiskLegs(match) {
  const options = match.prediction?.sporttery?.options || [];
  return options
    .filter((row) => row.sp && ["胜平负", "让球胜平负", "总进球"].includes(row.play_type))
    .sort((a, b) => {
      const priority = { "胜平负": 4, "让球胜平负": 3, "总进球": 2 };
      const officialA = isOfficial(a) ? 1 : 0;
      const officialB = isOfficial(b) ? 1 : 0;
      const valueA = (a.ev ?? -9) > 0 ? 1 : 0;
      const valueB = (b.ev ?? -9) > 0 ? 1 : 0;
      return (b.mapping_priority || 0) - (a.mapping_priority || 0)
        || officialB - officialA
        || valueB - valueA
        || (priority[b.play_type] || 0) - (priority[a.play_type] || 0)
        || (b.model_prob ?? 0) - (a.model_prob ?? 0)
        || (a.risk_score ?? 100) - (b.risk_score ?? 100);
    });
}

function lowRiskStrategy(state) {
  const rows = [];
  for (const match of state.matches || []) {
    const legs = lowRiskLegs(match);
    const primary = legs[0];
    const backup = legs.find((row) => row.selection !== primary?.selection) || legs[1];
    rows.push({
      match,
      primary,
      backup,
    });
  }
  const core = rows.filter((row) => row.primary).slice(0, 4);
  const singles = core.map(({ match, primary }) => [
    `${match.home_team} vs ${match.away_team}`,
    fmtTime(match.kickoff),
    primary.play_type,
    primary.selection,
    primary.sp,
    sourceText(primary.sp_source),
    fmtPct(primary.model_prob),
    valueText(primary),
    `${primary.risk_score} ${primary.risk_level}`,
    friendlyDecision(primary),
    (primary.ev ?? -1) > 0
      ? "低风险单关优先；如果临场奖金下降到不划算，就放弃"
      : "这是低风险方向，不代表现在值得下；需要等奖金改善或只作参考",
  ]);

  const twoLegs = [];
  for (let i = 0; i < core.length; i += 1) {
    for (let j = i + 1; j < core.length; j += 1) {
      const a = core[i].primary;
      const b = core[j].primary;
      const p = a.model_prob * b.model_prob;
      const sp = a.sp * b.sp;
      const ev = p * sp - 1;
      const risk = Math.max(a.risk_score ?? 80, b.risk_score ?? 80) + 5;
      twoLegs.push({
        legs: `${core[i].match.home_team}vs${core[i].match.away_team} ${a.play_type}-${a.selection} + ${core[j].match.home_team}vs${core[j].match.away_team} ${b.play_type}-${b.selection}`,
        p,
        sp,
        ev,
        risk,
        allValue: (a.ev ?? -1) > 0 && (b.ev ?? -1) > 0,
      });
    }
  }
  twoLegs.sort((a, b) => (a.risk - b.risk) || b.ev - a.ev);

  return {
    singles,
    parlays: twoLegs.slice(0, 6).map((row, idx) => [
      `低风险2串1-${idx + 1}`,
      row.legs,
      row.p,
      row.sp,
      row.ev >= 0.10 ? "优势高，需复核" : row.ev >= 0.05 ? "组合有优势" : row.ev > 0 ? "略有优势" : "不划算",
      row.risk,
      row.allValue && row.ev >= 0.05 && row.risk <= 75 ? "可小额参考" : "方向参考，先不下",
      row.allValue ? "每一腿当前都划算；任一场临场变得不划算，整组取消" : "有腿当前不划算，所以只保留串关方向，不建议直接下",
    ]),
  };
}

function analysisLine(match) {
  const vm = match.prediction.value_model;
  const topScores = (vm.top_scores || []).slice(0, 3).map((row) => row.score).join(" / ");
  const total = vm.total_goals?.best_range || "-";
  const ou = (vm.over_under_lines || []).find((row) => row.line === 2.5);
  const favorite = ["home", "draw", "away"].sort((a, b) => vm.probabilities[b] - vm.probabilities[a])[0];
  const lean = favorite === "home" ? match.home_team : favorite === "away" ? match.away_team : "平局";
  return `模型主线：${lean}；比分集中 ${topScores}；总进球区间 ${total}；2.5球倾向 ${ou ? `${fmtPct(ou.over)}大 / ${fmtPct(ou.under)}小` : "-"}。`;
}

function spAvailability(match) {
  const options = match.prediction?.sporttery?.options || [];
  const official = options.filter(isOfficial).length;
  const available = options.filter((row) => row.sp).length;
  if (official > 0) return `官方SP ${official}项`;
  if (available > 0) return `代理/手工SP ${available}项`;
  return "未抓到SP";
}

function sourceText(source) {
  if (!source) return "";
  if (source === "sporttery_mobile_calculator") return "体彩官方";
  if (source === "market_h2h_proxy") return "市场参考";
  if (source === "sporttery_sp") return "手工录入体彩";
  if (source === "manual") return "手动兜底";
  return source;
}

function friendlyDecision(rowOrText) {
  const decision = typeof rowOrText === "string" ? rowOrText : rowOrText?.decision;
  if (decision === "可小注") return "可小额参考";
  if (decision === "观察") return "先观察";
  if (decision === "高风险观察") return "高风险，仅观察";
  if (decision === "放弃") return "不建议";
  if (decision === "不可用") return "暂不可用";
  return decision || "";
}

function friendlyReason(row) {
  const reason = row?.reason || "";
  if (reason.includes("EV≤0")) return "赔率给得不够高，按模型测算不划算";
  if (reason.includes("缺少体彩SP")) return "当前没有抓到体彩奖金指数，不能判断是否划算";
  if (reason.includes("缺少官方让球数") || reason.includes("缺H")) return "没有抓到本场官方让几球，不能判断让球胜平负";
  if (reason.includes("低赔无价值")) return "虽然方向看好，但奖金太低，不适合追";
  if (reason.includes("不足玩法门槛")) return "略微划算，但优势不明显，适合等临场再看";
  if (reason.includes("风险分超过")) return "比赛不确定性偏高，不适合下重";
  if (reason.includes("高EV小概率")) return "高赔率小概率选项，容易波动，只适合看看";
  if (reason.includes("EV达到门槛")) return "模型概率高于奖金对应概率，且风险可控";
  return reason;
}

function valueText(row) {
  if (!row || row.ev == null) return "无法判断";
  if (row.ev <= 0) return "不划算";
  if (row.ev < 0.03) return "略有优势";
  if (row.ev < 0.06) return "有小优势";
  if (row.ev < 0.10) return "优势较明显";
  return "优势高，需复核";
}

function handicapText(value) {
  if (value == null || value === "") return "未抓到";
  const n = Number(value);
  if (n === 0) return "不让球";
  return `主队${n > 0 ? "受让" : "让"}${Math.abs(n)}球`;
}

function applyPercent(ws, cols, start, end) {
  for (const col of cols) ws.getRange(`${col}${start}:${col}${end}`).format.numberFormat = "0.0%";
}

const state = await (await fetch(stateUrl)).json();
await fs.mkdir(outputDir, { recursive: true });
const workbook = Workbook.create();

const overview = workbook.worksheets.add("01_总览");
setup(overview);
title(overview, "A1:L1", "近期开赛4场｜体彩可选项分析（中国-北京时间）");
overview.getRange("A2:L2").values = [["比赛", "中国-北京时间", "本场让球", "奖金数据状态", "市场看法", "模型测算", "比赛判断", "常见比分", "总进球倾向", "优先查看", "风险提示", "结算口径"]];
const overviewRows = state.matches.map((match) => {
  const vm = match.prediction.value_model;
  const sporttery = match.prediction.sporttery;
  const topScores = (vm.top_scores || []).slice(0, 3).map((row) => row.score).join(" / ");
  const candidates = compactMainCandidates(match).main;
  const first = candidates[0];
  return [
    `${match.home_team} vs ${match.away_team}`,
    fmtTime(match.kickoff),
    handicapText(sporttery.handicap),
    spAvailability(match),
    `${fmtPct(vm.market_probs.home)} / ${fmtPct(vm.market_probs.draw)} / ${fmtPct(vm.market_probs.away)}`,
    `${fmtPct(vm.probabilities.home)} / ${fmtPct(vm.probabilities.draw)} / ${fmtPct(vm.probabilities.away)}`,
    analysisLine(match),
    topScores,
    vm.total_goals?.best_range || "",
    first ? `${first.play_type}-${first.selection} @${first.sp}` : "无主玩法候选",
    sporttery.handicap == null ? "让球玩法缺少让球数，暂不判断；首发/伤停未确认" : "首发、伤停、停售前奖金变化需要再确认",
    sporttery.settlement,
  ];
});
overview.getRange(`A3:L${overviewRows.length + 2}`).values = overviewRows;
styleRange(overview, `A2:L${overviewRows.length + 2}`);
header(overview, "A2:L2", "#0F172A");
overview.getRange("A:A").format.columnWidthPx = 170;
overview.getRange("B:B").format.columnWidthPx = 115;
overview.getRange("C:D").format.columnWidthPx = 105;
overview.getRange("E:F").format.columnWidthPx = 170;
overview.getRange("G:G").format.columnWidthPx = 420;
overview.getRange("H:J").format.columnWidthPx = 145;
overview.getRange("K:L").format.columnWidthPx = 260;

const lowRisk = workbook.worksheets.add("02_低风险策略");
setup(lowRisk);
title(lowRisk, "A1:K1", "风险最低的中国体彩参考方案｜先看方向，再看是否值得下");
lowRisk.getRange("A2:K2").values = [["比赛", "北京时间", "玩法", "选择", "体彩奖金", "奖金来源", "模型命中率", "是否划算", "风险", "建议", "怎么执行"]];
const strategy = lowRiskStrategy(state);
if (strategy.singles.length) lowRisk.getRange(`A3:K${strategy.singles.length + 2}`).values = strategy.singles;
styleRange(lowRisk, `A2:K${Math.max(3, strategy.singles.length + 2)}`);
header(lowRisk, "A2:K2", "#064E3B");
applyPercent(lowRisk, ["G"], 3, Math.max(3, strategy.singles.length + 2));
lowRisk.getRange("A:K").format.columnWidthPx = 130;
lowRisk.getRange("A:A").format.columnWidthPx = 170;
lowRisk.getRange("K:K").format.columnWidthPx = 380;

const lowRiskParlay = workbook.worksheets.add("03_低风险串关");
setup(lowRiskParlay);
title(lowRiskParlay, "A1:H1", "低风险串关参考｜只展示最多6组，单关优先");
lowRiskParlay.getRange("A2:H2").values = [["组合", "包含哪些选择", "整体命中率", "组合奖金", "是否划算", "风险", "建议", "怎么执行"]];
if (strategy.parlays.length) lowRiskParlay.getRange(`A3:H${strategy.parlays.length + 2}`).values = strategy.parlays;
styleRange(lowRiskParlay, `A2:H${Math.max(3, strategy.parlays.length + 2)}`);
header(lowRiskParlay, "A2:H2", "#14532D");
applyPercent(lowRiskParlay, ["C", "E"], 3, Math.max(3, strategy.parlays.length + 2));
lowRiskParlay.getRange("A:H").format.columnWidthPx = 135;
lowRiskParlay.getRange("B:B").format.columnWidthPx = 520;
lowRiskParlay.getRange("H:H").format.columnWidthPx = 340;

const recommend = workbook.worksheets.add("04_精选推荐");
setup(recommend);
title(recommend, "A1:N1", "精选参考｜每场每类最多精选，主玩法优先");
recommend.getRange("A2:N2").values = [["比赛", "北京时间", "玩法", "选择", "体彩奖金", "奖金来源", "模型命中率", "合理奖金线", "是否划算", "风险", "建议", "参考投入", "推荐级别", "说明"]];
const recRows = [];
for (const match of state.matches) {
  const { main, highRisk } = compactMainCandidates(match);
  for (const row of main) {
    recRows.push([
      `${match.home_team} vs ${match.away_team}`,
      fmtTime(match.kickoff),
      row.play_type,
      row.selection,
      row.sp,
      sourceText(row.sp_source),
      pct(row.model_prob),
      row.fair_sp,
      valueText(row),
      `${row.risk_score ?? ""} ${row.risk_level ?? ""}`,
      friendlyDecision(row),
      pct(row.stake_pct),
      row.play_type === "胜平负" || row.play_type === "让球胜平负" ? "主玩法候选" : "进球玩法候选",
      friendlyReason(row),
    ]);
  }
  for (const row of highRisk) {
    recRows.push([
      `${match.home_team} vs ${match.away_team}`,
      fmtTime(match.kickoff),
      row.play_type,
      row.selection,
      row.sp,
      sourceText(row.sp_source),
      pct(row.model_prob),
      row.fair_sp,
      valueText(row),
      `${row.risk_score ?? ""} ${row.risk_level ?? ""}`,
      row.score_bet_allowed ? "小额比分参考" : "高风险，仅观察",
      pct(row.stake_pct),
      row.score_bet_allowed ? "实力接近比分候选" : "小概率高赔观察",
      row.score_bet_allowed
        ? "实力接近或平局空间足，比分只可小额参考，不进核心串关"
        : "比分/半全场不作为核心推荐，需二次核查SP与首发",
    ]);
  }
}
if (recRows.length) recommend.getRange(`A3:N${recRows.length + 2}`).values = recRows;
styleRange(recommend, `A2:N${Math.max(3, recRows.length + 2)}`);
header(recommend, "A2:N2", "#064E3B");
applyPercent(recommend, ["G", "I", "L"], 3, Math.max(3, recRows.length + 2));
recommend.getRange("A:N").format.columnWidthPx = 120;
recommend.getRange("A:A").format.columnWidthPx = 170;
recommend.getRange("N:N").format.columnWidthPx = 310;

const analysis = workbook.worksheets.add("05_逐场分析");
setup(analysis);
title(analysis, "A1:H1", "逐场分析｜用普通话说明为什么这样判断");
analysis.getRange("A2:H2").values = [["比赛", "北京时间", "胜平负测算", "可能比分", "进球判断", "奖金数据", "分析结论", "执行边界"]];
const analysisRows = state.matches.map((match) => {
  const vm = match.prediction.value_model;
  const sporttery = match.prediction.sporttery;
  return [
    `${match.home_team} vs ${match.away_team}`,
    fmtTime(match.kickoff),
    `主 ${fmtPct(vm.probabilities.home)} / 平 ${fmtPct(vm.probabilities.draw)} / 客 ${fmtPct(vm.probabilities.away)}`,
    (vm.top_scores || []).slice(0, 5).map((row) => `${row.score}(${fmtPct(row.probability)})`).join(" / "),
    `总进球${vm.total_goals?.best_range || "-"}；${(vm.over_under_lines || []).map((x) => `${x.line}:${x.lean}`).join("，")}`,
    spAvailability(match),
    analysisLine(match),
    sporttery.handicap == null ? "让球玩法暂不判断；只参考已经抓到奖金的选项" : `让球按官方${sporttery.handicap > 0 ? "受让" : "让"}${Math.abs(sporttery.handicap)}球计算；奖金不划算的不进推荐`,
  ];
});
analysis.getRange(`A3:H${analysisRows.length + 2}`).values = analysisRows;
styleRange(analysis, `A2:H${analysisRows.length + 2}`);
header(analysis, "A2:H2", "#1E3A8A");
analysis.getRange("A:H").format.columnWidthPx = 180;
analysis.getRange("G:H").format.columnWidthPx = 360;

function buildPlaySheet(name, playType, fill) {
  const ws = workbook.worksheets.add(name);
  setup(ws);
  title(ws, "A1:P1", `${playType}｜对应体彩计算器真实选项，最多显示6个`);
  ws.getRange("A2:P2").values = [["比赛", "北京时间", "本场让球", "选择", "体彩奖金", "奖金来源", "模型命中率", "合理奖金线", "奖金要求概率", "模型优势", "是否划算", "风险", "建议", "原因", "数据状态", "备注"]];
  const rows = [];
  for (const match of state.matches) {
    const sporttery = match.prediction.sporttery;
    for (const row of byPlay(match, playType)) {
      rows.push([
        `${match.home_team} vs ${match.away_team}`,
        fmtTime(match.kickoff),
        handicapText(sporttery.handicap),
        row.selection,
        row.sp ?? "",
        sourceText(row.sp_source),
        pct(row.model_prob),
        row.fair_sp ?? "",
        pct(row.implied_prob),
        pct(row.value_gap),
        valueText(row),
        row.risk_score == null ? "" : `${row.risk_score} ${row.risk_level}`,
        friendlyDecision(row),
        friendlyReason(row),
        row.sp ? (isOfficial(row) ? "官方SP" : "代理/手工SP") : "未开售/未抓到SP",
        playType === "比分"
          ? `${row.score_group || "比分参考"}：${row.score_note || "比分玩法波动高，不作核心"}`
          : playType === "让球胜平负" && sporttery.handicap == null ? "缺少让球数，不判断" : "",
      ]);
    }
  }
  if (rows.length) ws.getRange(`A3:P${rows.length + 2}`).values = rows;
  styleRange(ws, `A2:P${Math.max(3, rows.length + 2)}`);
  header(ws, "A2:P2", fill);
  applyPercent(ws, ["G", "I", "J", "K"], 3, Math.max(3, rows.length + 2));
  ws.getRange("A:P").format.columnWidthPx = 110;
  ws.getRange("A:A").format.columnWidthPx = 170;
  ws.getRange("N:P").format.columnWidthPx = 220;
}

buildPlaySheet("06_胜平负", "胜平负", "#14532D");
buildPlaySheet("07_让球胜平负", "让球胜平负", "#7C2D12");
buildPlaySheet("08_总进球", "总进球", "#1D4ED8");
buildPlaySheet("09_比分", "比分", "#991B1B");
buildPlaySheet("10_半全场", "半全场", "#581C87");

const combos = workbook.worksheets.add("11_串关池");
setup(combos);
title(combos, "A1:I1", "串关池｜只从划算的主玩法候选生成");
combos.getRange("A2:I2").values = [["组合编号", "过关方式", "包含哪些选择", "整体命中率", "组合奖金", "是否划算", "风险", "建议", "原因"]];
const comboRows = (state.sporttery_combos || []).map((combo) => [
  combo.combo_id,
  combo.type,
  combo.legs.map((leg) => `${leg.match}｜${leg.play_type}-${leg.selection}@${leg.sp}`).join("\n"),
  pct(combo.probability),
  combo.sp,
  combo.ev >= 0.10 ? "优势高，需复核" : combo.ev >= 0.05 ? "组合有优势" : combo.ev > 0 ? "略有优势" : "不划算",
  combo.risk_score,
  combo.decision === "可小注" ? "可小额参考" : combo.decision,
  combo.reason === "单腿正EV且组合EV达标" ? "每一场单独看都划算，组合后也划算" : combo.reason,
]);
if (comboRows.length) combos.getRange(`A3:I${comboRows.length + 2}`).values = comboRows;
styleRange(combos, `A2:I${Math.max(3, comboRows.length + 2)}`);
header(combos, "A2:I2", "#4C1D95");
applyPercent(combos, ["D", "F"], 3, Math.max(3, comboRows.length + 2));
combos.getRange("A:I").format.columnWidthPx = 135;
combos.getRange("C:C").format.columnWidthPx = 430;

const source = workbook.worksheets.add("12_SP快照与状态");
setup(source);
title(source, "A1:J1", "体彩奖金快照与来源状态");
source.getRange("A2:J2").values = [["比赛", "北京时间", "抓取时间UTC", "来源", "市场/玩法", "选择", "奖金/赔率", "是否官方", "当前源状态", "说明"]];
const health = state.source_health?.sporttery_mobile_calculator || {};
const sourceRows = [];
for (const match of state.matches) {
  for (const row of match.odds_history || []) {
    if (!["胜平负", "让球胜平负", "总进球", "比分", "半全场", "h2h", "sporttery_handicap"].includes(row.market)) continue;
    sourceRows.push([
      `${match.home_team} vs ${match.away_team}`,
      fmtTime(match.kickoff),
      row.captured_at,
      sourceText(row.source),
      row.market,
      row.selection,
      row.odds_decimal,
      row.source === "sporttery_mobile_calculator" ? "是" : "否",
      health.last_error ? `最近异常：${health.last_error}` : "正常",
      row.source === "sporttery_mobile_calculator" ? "体彩计算器公开接口快照" : "兜底/代理数据",
    ]);
  }
}
if (sourceRows.length) source.getRange(`A3:J${sourceRows.length + 2}`).values = sourceRows;
styleRange(source, `A2:J${Math.max(3, sourceRows.length + 2)}`);
header(source, "A2:J2", "#334155");
source.getRange("A:J").format.columnWidthPx = 145;
source.getRange("A:A").format.columnWidthPx = 170;
source.getRange("I:J").format.columnWidthPx = 280;

const rules = workbook.worksheets.add("13_规则");
setup(rules);
title(rules, "A1:D1", "报告怎么看");
rules.getRange("A2:D2").values = [["你看到的词", "是什么意思", "为什么重要", "怎么用"]];
rules.getRange("A3:D12").values = [
  ["中国-北京时间", "所有比赛时间都按北京时间写", "避免看错开赛时间", "不要再用“凌晨/午夜”模糊判断"],
  ["体彩奖金", "就是体彩页面显示的SP", "奖金变化会改变是否值得参考", "没有奖金就不做推荐"],
  ["本场让球", "让球胜平负里的让几球", "让1球和让2球是完全不同的玩法", "没抓到让球数就不判断"],
  ["模型命中率", "程序估算这个选项打出的概率", "概率越高不代表越值得买，还要看奖金", "不能只看命中率"],
  ["合理奖金线", "低于这个奖金就不太划算", "用来判断体彩奖金给得够不够", "奖金低于合理线就别追"],
  ["是否划算", "模型概率和体彩奖金合起来测算", "看好不等于值得买", "不划算就不建议"],
  ["参考投入", "按模型给出的很小比例", "只是风控参考，不是要求下注", "连续亏损不加仓"],
  ["比分/半全场", "高奖金但命中率低", "波动很大", "只观察，不做核心"],
  ["串关", "多场一起中才算中", "风险比单关高很多", "任一场变不划算就整组取消"],
  ["官方源状态", "体彩接口有时会拦截脚本请求", "要知道数据是不是最新官方快照", "被拦截时不要强抓"],
];
styleRange(rules, "A2:D12");
header(rules, "A2:D2");
rules.getRange("A:D").format.columnWidthPx = 255;

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "formula error scan",
});
console.log(errors.ndjson);

await workbook.render({ sheetName: "01_总览", range: "A1:L8", scale: 1, format: "png" });
await workbook.render({ sheetName: "02_低风险策略", range: "A1:K12", scale: 1, format: "png" });
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputFile);
console.log(`SAVED:${outputFile}`);
