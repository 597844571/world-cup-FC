import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "C:/Users/59784/Documents/Codex/2026-06-13/import-pandas-as-pd-from-openpyxl/outputs";
const outputFile = path.join(outputDir, "体彩计算器对齐_预测与可选下注项报告.xlsx");
const stateUrl = "http://127.0.0.1:8765/api/state";

const playOrder = ["胜平负", "让球胜平负", "总进球", "比分", "半全场"];
const playSheetNames = {
  "胜平负": "体彩-胜平负",
  "让球胜平负": "体彩-让球胜平负",
  "总进球": "体彩-总进球",
  "比分": "体彩-比分",
  "半全场": "体彩-半全场",
};

function pct(value) {
  return value == null ? "" : value;
}

function text(value) {
  return value == null ? "" : String(value);
}

function percentFormat(ws, cols, startRow, endRow) {
  for (const col of cols) ws.getRange(`${col}${startRow}:${col}${endRow}`).format.numberFormat = "0.0%";
}

function setup(ws) {
  ws.showGridLines = false;
  ws.freezePanes.freezeRows(1);
}

function styleTable(ws, range) {
  ws.getRange(range).format.borders = { preset: "all", style: "thin", color: "#CBD5E1" };
  ws.getRange(range).format.wrapText = true;
  ws.getRange(range).format.verticalAlignment = "top";
}

function header(ws, range, fill = "#111827") {
  ws.getRange(range).format = {
    fill,
    font: { bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "middle",
    wrapText: true,
  };
}

function optionRows(state, playType) {
  const rows = [];
  for (const match of state.matches || []) {
    const sporttery = match.prediction?.sporttery || {};
    for (const option of sporttery.options || []) {
      if (option.play_type !== playType) continue;
      rows.push([
        match.match_id,
        `${match.home_team} vs ${match.away_team}`,
        match.kickoff || "",
        sporttery.handicap == null ? "未抓到/未配置" : sporttery.handicap,
        option.play_type,
        option.selection,
        option.sp ?? "",
        option.sp_source || "",
        pct(option.model_prob),
        option.fair_sp ?? "",
        pct(option.implied_prob),
        pct(option.value_gap),
        pct(option.ev),
        option.risk_score ?? "",
        option.risk_level || "",
        pct(option.kelly),
        pct(option.stake_pct),
        option.decision || "",
        option.reason || "",
      ]);
    }
  }
  return rows;
}

function candidateRows(state) {
  const rows = [];
  for (const match of state.matches || []) {
    const sporttery = match.prediction?.sporttery || {};
    for (const option of sporttery.candidate_pool || []) {
      rows.push([
        match.match_id,
        `${match.home_team} vs ${match.away_team}`,
        sporttery.handicap == null ? "未抓到/未配置" : sporttery.handicap,
        option.play_type,
        option.selection,
        option.sp ?? "",
        option.sp_source || "",
        pct(option.model_prob),
        option.fair_sp ?? "",
        pct(option.ev),
        option.risk_score ?? "",
        option.risk_level || "",
        pct(option.kelly),
        pct(option.stake_pct),
        option.decision || "",
        option.reason || "",
      ]);
    }
  }
  return rows.sort((a, b) => {
    const rank = { "可小注": 3, "观察": 2, "高风险观察": 1, "不可用": 0, "放弃": 0 };
    return (rank[b[14]] || 0) - (rank[a[14]] || 0) || (b[9] || -9) - (a[9] || -9);
  });
}

function abandonRows(state) {
  const rows = [];
  for (const match of state.matches || []) {
    const sporttery = match.prediction?.sporttery || {};
    for (const option of sporttery.abandon_list || []) {
      rows.push([
        match.match_id,
        `${match.home_team} vs ${match.away_team}`,
        sporttery.handicap == null ? "未抓到/未配置" : sporttery.handicap,
        option.play_type,
        option.selection,
        option.sp ?? "",
        option.sp_source || "",
        pct(option.model_prob),
        option.fair_sp ?? "",
        pct(option.ev),
        option.decision || "",
        option.reason || "",
      ]);
    }
  }
  return rows;
}

function snapshotRows(state) {
  const rows = [];
  for (const match of state.matches || []) {
    for (const row of match.odds_history || []) {
      if (!["胜平负", "让球胜平负", "总进球", "比分", "半全场", "h2h", "sporttery_handicap"].includes(row.market)) continue;
      rows.push([
        match.match_id,
        `${match.home_team} vs ${match.away_team}`,
        row.captured_at,
        row.source,
        row.bookmaker,
        row.market,
        row.selection,
        row.odds_decimal,
      ]);
    }
  }
  return rows;
}

function comboRows(state) {
  return (state.sporttery_combos || []).map((combo) => [
    combo.combo_id,
    combo.type,
    combo.legs.map((leg) => `${leg.match}｜${leg.play_type}-${leg.selection}@${leg.sp}`).join("\n"),
    pct(combo.probability),
    combo.sp,
    pct(combo.ev),
    combo.risk_score,
    combo.decision,
    combo.reason,
  ]);
}

await fs.mkdir(outputDir, { recursive: true });
const state = await (await fetch(stateUrl)).json();
const workbook = Workbook.create();

const summary = workbook.worksheets.add("总览");
setup(summary);
summary.getRange("A1:K1").values = [["比赛", "开赛时间", "官方让球H", "市场概率主/平/客", "模型概率主/平/客", "首选候选", "候选动作", "源状态", "最新快照", "风险提示", "结算口径"]];
const summaryRows = (state.matches || []).map((match) => {
  const vm = match.prediction.value_model;
  const sporttery = match.prediction.sporttery;
  const first = sporttery.candidate_pool?.[0] || {};
  const health = state.source_health?.sporttery_mobile_calculator || {};
  return [
    `${match.home_team} vs ${match.away_team}`,
    match.kickoff || "",
    sporttery.handicap == null ? "未抓到/未配置" : sporttery.handicap,
    `${(vm.market_probs.home * 100).toFixed(1)}% / ${(vm.market_probs.draw * 100).toFixed(1)}% / ${(vm.market_probs.away * 100).toFixed(1)}%`,
    `${(vm.probabilities.home * 100).toFixed(1)}% / ${(vm.probabilities.draw * 100).toFixed(1)}% / ${(vm.probabilities.away * 100).toFixed(1)}%`,
    first.play_type ? `${first.play_type}-${first.selection} @${first.sp ?? "-"}` : "无",
    first.decision || "",
    health.last_error ? `异常：${health.last_error}` : "正常/有最近成功快照",
    match.latest_snapshot || "",
    sporttery.handicap == null ? "让球玩法缺少H时不计算EV" : "按真实SP和H计算",
    sporttery.settlement,
  ];
});
summary.getRange(`A2:K${summaryRows.length + 1}`).values = summaryRows;
styleTable(summary, `A1:K${summaryRows.length + 1}`);
header(summary, "A1:K1");
summary.getRange("A:A").format.columnWidthPx = 170;
summary.getRange("B:K").format.columnWidthPx = 160;

const candidates = workbook.worksheets.add("候选池");
setup(candidates);
candidates.getRange("A1:P1").values = [["Match_ID", "比赛", "官方让球H", "玩法", "选项", "体彩SP", "SP来源", "模型概率", "公允SP", "EV", "风险分", "风险等级", "Kelly", "建议仓位", "动作", "原因"]];
const candRows = candidateRows(state);
if (candRows.length) candidates.getRange(`A2:P${candRows.length + 1}`).values = candRows;
styleTable(candidates, `A1:P${Math.max(2, candRows.length + 1)}`);
header(candidates, "A1:P1", "#064E3B");
percentFormat(candidates, ["H", "J", "M", "N"], 2, Math.max(2, candRows.length + 1));
candidates.getRange("A:P").format.columnWidthPx = 125;
candidates.getRange("B:B").format.columnWidthPx = 170;
candidates.getRange("P:P").format.columnWidthPx = 260;

for (const playType of playOrder) {
  const ws = workbook.worksheets.add(playSheetNames[playType]);
  setup(ws);
  ws.getRange("A1:S1").values = [["Match_ID", "比赛", "开赛时间", "官方让球H", "玩法", "选项", "体彩SP", "SP来源", "模型概率", "公允SP", "隐含概率", "价值差", "EV", "风险分", "风险等级", "Kelly", "建议仓位", "动作", "原因"]];
  const rows = optionRows(state, playType);
  if (rows.length) ws.getRange(`A2:S${rows.length + 1}`).values = rows;
  styleTable(ws, `A1:S${Math.max(2, rows.length + 1)}`);
  header(ws, "A1:S1", playType === "比分" ? "#7C2D12" : "#1E3A8A");
  percentFormat(ws, ["I", "K", "L", "M", "P", "Q"], 2, Math.max(2, rows.length + 1));
  ws.getRange("A:S").format.columnWidthPx = 118;
  ws.getRange("B:B").format.columnWidthPx = 170;
  ws.getRange("S:S").format.columnWidthPx = 270;
}

const combos = workbook.worksheets.add("串关池");
setup(combos);
combos.getRange("A1:I1").values = [["组合ID", "过关方式", "腿", "组合概率", "组合SP", "组合EV", "风险分", "动作", "原因"]];
const cRows = comboRows(state);
if (cRows.length) combos.getRange(`A2:I${cRows.length + 1}`).values = cRows;
styleTable(combos, `A1:I${Math.max(2, cRows.length + 1)}`);
header(combos, "A1:I1", "#581C87");
percentFormat(combos, ["D", "F"], 2, Math.max(2, cRows.length + 1));
combos.getRange("A:I").format.columnWidthPx = 140;
combos.getRange("C:C").format.columnWidthPx = 420;

const abandon = workbook.worksheets.add("放弃清单");
setup(abandon);
abandon.getRange("A1:L1").values = [["Match_ID", "比赛", "官方让球H", "玩法", "选项", "体彩SP", "SP来源", "模型概率", "公允SP", "EV", "动作", "原因"]];
const aRows = abandonRows(state);
if (aRows.length) abandon.getRange(`A2:L${aRows.length + 1}`).values = aRows;
styleTable(abandon, `A1:L${Math.max(2, aRows.length + 1)}`);
header(abandon, "A1:L1", "#991B1B");
percentFormat(abandon, ["H", "J"], 2, Math.max(2, aRows.length + 1));
abandon.getRange("A:L").format.columnWidthPx = 125;
abandon.getRange("B:B").format.columnWidthPx = 170;
abandon.getRange("L:L").format.columnWidthPx = 300;

const snapshots = workbook.worksheets.add("体彩SP快照");
setup(snapshots);
snapshots.getRange("A1:H1").values = [["Match_ID", "比赛", "抓取时间", "来源", "机构", "市场/玩法", "选项", "SP/赔率"]];
const sRows = snapshotRows(state);
if (sRows.length) snapshots.getRange(`A2:H${sRows.length + 1}`).values = sRows;
styleTable(snapshots, `A1:H${Math.max(2, sRows.length + 1)}`);
header(snapshots, "A1:H1", "#0F172A");
snapshots.getRange("A:H").format.columnWidthPx = 150;
snapshots.getRange("B:B").format.columnWidthPx = 170;

const rules = workbook.worksheets.add("规则说明");
setup(rules);
rules.getRange("A1:D1").values = [["规则", "执行方式", "为什么", "红线"]];
rules.getRange("A2:D11").values = [
  ["按计算器选项输出", "每个体彩玩法单独成 sheet", "避免预测方向和实际可下选项错位", "没有SP的选项不可推荐"],
  ["让球胜平负", "必须有官方让球H或手工配置H", "H不同，概率完全不同", "缺少H时不计算EV"],
  ["胜平负", "只对已开售SP计算EV", "部分场次可能不开售", "未开售不推荐"],
  ["比分", "31项全部列出", "单项方差极高", "高EV也只作高风险观察"],
  ["总进球", "0/1/2/3/4/5/6/7+全部列出", "对应体彩计算器选项", "不要和大小球混用"],
  ["半全场", "9项全部列出", "半场模型误差更大", "提高EV门槛"],
  ["复选包", "按注数重算包EV", "命中率高不等于有价值", "SP缺失不计算"],
  ["串关", "只从正EV候选池生成", "串关放大方差", "负EV腿禁止硬串"],
  ["官方源", "sporttery_mobile_calculator", "来自体彩移动端计算器公开接口", "WAF拦截时不绕过"],
  ["结算口径", "90分钟含伤停补时", "体彩竞彩足球口径", "不含加时和点球"],
];
styleTable(rules, "A1:D11");
header(rules, "A1:D1");
rules.getRange("A:D").format.columnWidthPx = 250;

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  summary: "formula error scan",
});
console.log(errors.ndjson);

await workbook.render({ sheetName: "总览", range: "A1:K6", scale: 1, format: "png" });
await workbook.render({ sheetName: "候选池", range: "A1:P12", scale: 1, format: "png" });

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputFile);
console.log(`SAVED:${outputFile}`);
