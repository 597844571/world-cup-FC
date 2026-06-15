import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "C:/Users/59784/Documents/Codex/2026-06-13/import-pandas-as-pd-from-openpyxl/outputs";
const outputFile = path.join(outputDir, "近期开赛4场_极简参考报告.xlsx");
const stateUrl = "http://127.0.0.1:8765/api/state";

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

function fmtPct(value) {
  return value == null ? "-" : `${(Number(value) * 100).toFixed(1)}%`;
}

function setup(ws) {
  ws.showGridLines = false;
  ws.freezePanes.freezeRows(1);
}

function style(ws, range) {
  ws.getRange(range).format.borders = { preset: "all", style: "thin", color: "#D8DEE8" };
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

function title(ws, range, value, fill = "#111827") {
  ws.getRange(range).merge();
  ws.getRange(range).values = [[value]];
  ws.getRange(range).format = {
    fill,
    font: { bold: true, color: "#FFFFFF", size: 14 },
    horizontalAlignment: "left",
    verticalAlignment: "middle",
  };
}

function handicapText(value) {
  if (value == null || value === "") return "未抓到";
  const n = Number(value);
  if (n === 0) return "不让球";
  return `主队${n > 0 ? "受让" : "让"}${Math.abs(n)}球`;
}

function sourceText(source) {
  if (!source) return "";
  if (source === "sporttery_mobile_calculator") return "体彩官方";
  if (source === "market_h2h_proxy") return "市场参考";
  if (source === "manual") return "手动兜底";
  return source;
}

function valueText(row) {
  if (!row || row.ev == null) return "无法判断";
  if (row.ev <= 0) return "不划算";
  if (row.ev < 0.03) return "略有优势";
  if (row.ev < 0.06) return "有小优势";
  if (row.ev < 0.10) return "优势较明显";
  return "优势高，需复核";
}

function adviceText(row) {
  if (!row) return "无";
  if (!row.sp) return "没奖金，不参考";
  if (row.ev == null) return "无法判断";
  if (row.ev <= 0) return "方向参考，不建议下";
  if ((row.risk_score ?? 100) > 75) return "风险偏高，只观察";
  return "可小额参考";
}

function bestDirection(match) {
  const options = match.prediction?.sporttery?.options || [];
  const main = options
    .filter((row) => row.sp && ["胜平负", "让球胜平负", "总进球"].includes(row.play_type))
    .sort((a, b) => {
      const official = (isOfficial(b) ? 1 : 0) - (isOfficial(a) ? 1 : 0);
      if (official) return official;
      const value = ((b.ev ?? -9) > 0 ? 1 : 0) - ((a.ev ?? -9) > 0 ? 1 : 0);
      if (value) return value;
      return (b.model_prob ?? 0) - (a.model_prob ?? 0);
    });
  return main[0] || null;
}

function isOfficial(row) {
  return row?.sp_source === "sporttery_mobile_calculator";
}

function topScores(match) {
  return (match.prediction?.value_model?.top_scores || []).slice(0, 3).map((row) => row.score).join(" / ");
}

const state = await (await fetch(stateUrl)).json();
await fs.mkdir(outputDir, { recursive: true });
const wb = Workbook.create();
const health = state.source_health?.sporttery_mobile_calculator || {};
const lastRefresh = (state.matches || []).map((m) => m.latest_snapshot).filter(Boolean).sort().at(-1);

const summary = wb.worksheets.add("01_先看这页");
setup(summary);
title(summary, "A1:H1", "近期开赛4场｜极简参考（中国-北京时间）");
summary.getRange("A2:H2").values = [["比赛", "北京时间", "本场让球", "一句话判断", "优先参考", "是否适合现在下", "主要风险", "数据说明"]];
const summaryRows = state.matches.map((match) => {
  const vm = match.prediction.value_model;
  const direction = bestDirection(match);
  const leader = ["home", "draw", "away"].sort((a, b) => vm.probabilities[b] - vm.probabilities[a])[0];
  const lean = leader === "home" ? match.home_team : leader === "away" ? match.away_team : "平局";
  return [
    `${match.home_team} vs ${match.away_team}`,
    fmtTime(match.kickoff),
    handicapText(match.prediction.sporttery.handicap),
    `${lean}方向更强，常见比分 ${topScores(match)}`,
    direction ? `${direction.play_type}-${direction.selection}，奖金${direction.sp}` : "无",
    adviceText(direction),
    match.prediction.sporttery.handicap == null ? "让球数没抓到；首发和伤停要再确认" : "首发、伤停、临场奖金变化要再确认",
    direction ? sourceText(direction.sp_source) : "无奖金",
  ];
});
summary.getRange(`A3:H${summaryRows.length + 2}`).values = summaryRows;
style(summary, `A2:H${summaryRows.length + 2}`);
header(summary, "A2:H2");
summary.getRange("A:H").format.columnWidthPx = 150;
summary.getRange("D:F").format.columnWidthPx = 240;
summary.getRange("G:H").format.columnWidthPx = 220;

const singles = wb.worksheets.add("02_单关参考");
setup(singles);
title(singles, "A1:J1", "单关参考｜每场只给1个最容易理解的方向");
singles.getRange("A2:J2").values = [["比赛", "北京时间", "玩法", "选择", "体彩奖金", "来源", "模型命中率", "是否划算", "建议", "说明"]];
const singleRows = state.matches.map((match) => {
  const row = bestDirection(match);
  return [
    `${match.home_team} vs ${match.away_team}`,
    fmtTime(match.kickoff),
    row?.play_type || "无",
    row?.selection || "无",
    row?.sp ?? "",
    sourceText(row?.sp_source),
    row ? fmtPct(row.model_prob) : "",
    valueText(row),
    adviceText(row),
    row?.ev > 0 ? "奖金和模型概率匹配，仍需临场复核" : "方向可以看，但当前奖金不够好，不建议直接下",
  ];
});
singles.getRange(`A3:J${singleRows.length + 2}`).values = singleRows;
style(singles, `A2:J${singleRows.length + 2}`);
header(singles, "A2:J2", "#064E3B");
singles.getRange("A:J").format.columnWidthPx = 140;
singles.getRange("J:J").format.columnWidthPx = 320;

const parlay = wb.worksheets.add("03_串关参考");
setup(parlay);
title(parlay, "A1:H1", "串关参考｜只做方向参考，单关优先");
parlay.getRange("A2:H2").values = [["组合", "包含哪些", "整体命中率", "组合奖金", "是否划算", "建议", "风险", "说明"]];
const picks = state.matches.map((m) => ({ match: m, row: bestDirection(m) })).filter((x) => x.row);
const combos = [];
for (let i = 0; i < picks.length; i += 1) {
  for (let j = i + 1; j < picks.length; j += 1) {
    const a = picks[i], b = picks[j];
    const p = a.row.model_prob * b.row.model_prob;
    const sp = a.row.sp * b.row.sp;
    const ev = p * sp - 1;
    combos.push([
      `2串1-${combos.length + 1}`,
      `${a.match.home_team}vs${a.match.away_team} ${a.row.play_type}-${a.row.selection} + ${b.match.home_team}vs${b.match.away_team} ${b.row.play_type}-${b.row.selection}`,
      fmtPct(p),
      Number(sp.toFixed(2)),
      ev > 0 ? "组合有优势" : "不划算",
      ev > 0 ? "可小额参考" : "方向参考，先不下",
      Math.max(a.row.risk_score ?? 80, b.row.risk_score ?? 80),
      ev > 0 ? "任一场临场变不划算就取消" : "组合里至少一腿当前不划算",
    ]);
  }
}
const parlayRows = combos.slice(0, 6);
if (parlayRows.length) parlay.getRange(`A3:H${parlayRows.length + 2}`).values = parlayRows;
style(parlay, `A2:H${Math.max(3, parlayRows.length + 2)}`);
header(parlay, "A2:H2", "#14532D");
parlay.getRange("A:H").format.columnWidthPx = 145;
parlay.getRange("B:B").format.columnWidthPx = 520;
parlay.getRange("H:H").format.columnWidthPx = 260;

const data = wb.worksheets.add("04_数据状态");
setup(data);
title(data, "A1:F1", "数据状态｜确认这份报告是不是最新");
data.getRange("A2:F2").values = [["项目", "状态", "北京时间/说明", "影响", "建议", "备注"]];
data.getRange("A3:F8").values = [
  ["本地刷新", "已刷新", lastRefresh ? fmtTime(lastRefresh) : "未知", "胜平负市场参考已更新", "可以看，但仍要临场复核", "本地刷新不等于官方SP一定更新"],
  ["体彩官方SP", health.last_error ? "本次未更新" : "正常", health.last_error || "接口正常", health.last_error ? "部分官方奖金可能是最近成功快照" : "官方奖金可用", "下单前再看体彩页面", ""],
  ["巴西 vs 摩洛哥", state.matches[0]?.prediction?.sporttery?.handicap == null ? "让球未知" : "有让球", handicapText(state.matches[0]?.prediction?.sporttery?.handicap), "可判断让球玩法", "仍需确认停售前奖金", ""],
  ["卡塔尔 vs 瑞士", state.matches[1]?.prediction?.sporttery?.handicap == null ? "让球未知" : "有让球", handicapText(state.matches[1]?.prediction?.sporttery?.handicap), "可判断让球玩法", "仍需确认停售前奖金", ""],
  ["海地 vs 苏格兰", state.matches[2]?.prediction?.sporttery?.handicap == null ? "让球未知" : "有让球", handicapText(state.matches[2]?.prediction?.sporttery?.handicap), "让球玩法暂不判断", "等官方SP刷新", ""],
  ["澳大利亚 vs 土耳其", state.matches[3]?.prediction?.sporttery?.handicap == null ? "让球未知" : "有让球", handicapText(state.matches[3]?.prediction?.sporttery?.handicap), "让球玩法暂不判断", "等官方SP刷新", ""],
];
style(data, "A2:F8");
header(data, "A2:F2", "#334155");
data.getRange("A:F").format.columnWidthPx = 180;
data.getRange("C:F").format.columnWidthPx = 260;

const errors = await wb.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  summary: "formula error scan",
});
console.log(errors.ndjson);
await wb.render({ sheetName: "01_先看这页", range: "A1:H8", scale: 1, format: "png" });
const xlsx = await SpreadsheetFile.exportXlsx(wb);
await xlsx.save(outputFile);
console.log(`SAVED:${outputFile}`);
