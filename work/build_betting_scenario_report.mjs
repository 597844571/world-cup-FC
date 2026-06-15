import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "C:/Users/59784/Documents/Codex/2026-06-13/import-pandas-as-pd-from-openpyxl/outputs";
const outputFile = path.join(outputDir, "世界杯未开赛4场_完整下注场景分析报告.xlsx");

const matches = [
  {
    code: "M1",
    match: "卡塔尔 vs 瑞士",
    favorite: "瑞士",
    regular: "瑞士胜",
    regularProb: "63%-66%",
    handicapLine: "瑞士 -1",
    handicapLean: "让平 / 让胜",
    handicapRisk: "瑞士赢1球概率不低，0-1比0-3更顺",
    doubleChance: "瑞士不败",
    totals: "小3.5优先；2-3球",
    btts: "否略优",
    scores: "0-2 / 0-1 / 1-2 / 1-1",
    riskLevel: "中低",
    confidence: "中",
    safePick: "瑞士不败",
    mediumPick: "瑞士胜",
    aggressivePick: "瑞士-1让平/让胜",
    avoid: "卡塔尔胜",
    note: "瑞士实力和市场明显占优；卡塔尔爆冷路径主要是低位防守+定位球。",
  },
  {
    code: "M2",
    match: "巴西 vs 摩洛哥",
    favorite: "巴西",
    regular: "巴西胜，防平",
    regularProb: "53%-56%",
    handicapLine: "巴西 -1",
    handicapLean: "让负优先，次选让平",
    handicapRisk: "摩洛哥低防强，巴西大胜不稳",
    doubleChance: "巴西不败",
    totals: "2-3球；小3.5优先",
    btts: "是/否接近，偏是",
    scores: "2-1 / 1-1 / 1-0 / 2-0",
    riskLevel: "高",
    confidence: "中",
    safePick: "巴西不败",
    mediumPick: "巴西胜 或 平局保护",
    aggressivePick: "巴西胜+双方进球 / 2-1",
    avoid: "巴西-1让胜重注",
    note: "巴西小优，但摩洛哥具备低防、反击、身体和定位球完整爆冷路径。",
  },
  {
    code: "M3",
    match: "海地 vs 苏格兰",
    favorite: "苏格兰",
    regular: "苏格兰胜",
    regularProb: "60%-62%",
    handicapLine: "苏格兰 -1",
    handicapLean: "让平优先，防让胜",
    handicapRisk: "苏格兰赢1球或2球都合理，0-1/0-2分布接近",
    doubleChance: "苏格兰不败",
    totals: "小3.5；1-3球",
    btts: "否略优",
    scores: "0-2 / 0-1 / 1-1 / 1-2",
    riskLevel: "中低",
    confidence: "中",
    safePick: "苏格兰不败",
    mediumPick: "苏格兰胜",
    aggressivePick: "苏格兰-1让平 / 0-2",
    avoid: "海地胜",
    note: "苏格兰身体、中场和大赛经验更稳；海地主要靠速度转换制造冷门。",
  },
  {
    code: "M4",
    match: "澳大利亚 vs 土耳其",
    favorite: "土耳其",
    regular: "土耳其小优，防平",
    regularProb: "49%-51%",
    handicapLine: "土耳其 -1",
    handicapLean: "让负优先",
    handicapRisk: "澳大利亚低防和定位球会压低比分，土耳其穿盘难",
    doubleChance: "土耳其不败",
    totals: "小2.5/小3.5；1-2球",
    btts: "否略优，防1-1",
    scores: "0-1 / 1-1 / 0-2 / 1-2",
    riskLevel: "中高",
    confidence: "中",
    safePick: "土耳其不败",
    mediumPick: "土耳其胜小注 / 平局保护",
    aggressivePick: "0-1 / 土耳其胜且小3.5",
    avoid: "土耳其-1让胜",
    note: "土耳其技术更好，但澳大利亚身体、定位球和防守纪律会显著提高平局概率。",
  },
];

const parlays = [
  ["稳健2串1核心", "M1 瑞士胜 + M3 苏格兰胜", "中", "两场强弱差距较清晰，是组合核心。"],
  ["稳健2串1防线", "M1 瑞士胜 + M2 巴西不败", "中低", "降低巴西被摩洛哥逼平的损失。"],
  ["稳健2串1防线", "M3 苏格兰胜 + M4 土耳其不败", "中", "M4用不败替代土耳其胜。"],
  ["稳健3串1", "M1 瑞士胜 + M3 苏格兰胜 + M2 巴西不败", "中", "三场里最大风险仍是巴西被逼平。"],
  ["稳健3串1", "M1 瑞士胜 + M3 苏格兰胜 + M4 土耳其不败", "中", "比加入土耳其胜更稳。"],
  ["均衡3串1", "M1 瑞士胜 + M2 巴西不败 + M4 土耳其不败", "中", "适合降低M2/M4冷门损伤。"],
  ["激进3串1", "M1 瑞士胜 + M2 巴西胜 + M3 苏格兰胜", "中高", "收益更高，但M2风险明显。"],
  ["激进4串1", "M1 瑞士胜 + M2 巴西胜 + M3 苏格兰胜 + M4 土耳其胜", "高", "四场全胜方向，M2/M4是断点。"],
  ["稳健4串1", "M1 瑞士胜 + M2 巴西不败 + M3 苏格兰胜 + M4 土耳其不败", "中", "更适合做主线参考。"],
  ["4串4三串一组1", "M1 瑞士胜 + M2 巴西不败 + M3 苏格兰胜", "中", "去掉M4单胜风险。"],
  ["4串4三串一组2", "M1 瑞士胜 + M3 苏格兰胜 + M4 土耳其不败", "中", "去掉M2胜负风险。"],
  ["4串4三串一组3", "M1 瑞士胜 + M2 巴西不败 + M4 土耳其不败", "中", "两场不败降低穿透要求。"],
  ["4串4三串一组4", "M2 巴西不败 + M3 苏格兰胜 + M4 土耳其不败", "中", "去掉瑞士胜后收益降低但风险更分散。"],
];

const workbook = Workbook.create();
await fs.mkdir(outputDir, { recursive: true });

function styleSheet(ws, range) {
  ws.showGridLines = false;
  ws.getRange(range).format.borders = { preset: "all", style: "thin", color: "#CBD5E1" };
  ws.getRange(range).format.wrapText = true;
  ws.getRange(range).format.verticalAlignment = "top";
}

function header(ws, range) {
  ws.getRange(range).format = {
    fill: "#111827",
    font: { bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "middle",
  };
}

const overview = workbook.worksheets.add("总览");
overview.getRange("A1:N1").values = [[
  "编号", "比赛", "常规时间倾向", "胜率区间", "让1盘口", "让1建议", "双重机会", "大小球", "BTTS", "比分组", "风险", "稳健", "均衡", "激进"
]];
overview.getRange("A2:N5").values = matches.map((m) => [
  m.code, m.match, m.regular, m.regularProb, m.handicapLine, m.handicapLean, m.doubleChance,
  m.totals, m.btts, m.scores, m.riskLevel, m.safePick, m.mediumPick, m.aggressivePick,
]);
styleSheet(overview, "A1:N5");
header(overview, "A1:N1");
overview.getRange("A:A").format.columnWidthPx = 70;
overview.getRange("B:B").format.columnWidthPx = 170;
overview.getRange("C:N").format.columnWidthPx = 145;
overview.freezePanes.freezeRows(1);
overview.tables.add("A1:N5", true, "BettingOverview").style = "TableStyleMedium2";

const single = workbook.worksheets.add("单场场景");
single.getRange("A1:K1").values = [[
  "比赛", "场景", "推荐", "风险", "适合类型", "说明", "比分参考", "大小球", "BTTS", "让球解释", "避开项"
]];
const singleRows = [];
for (const m of matches) {
  singleRows.push([m.match, "常规时间胜平负", m.regular, m.riskLevel, "主线", m.note, m.scores, m.totals, m.btts, "90分钟，不含加时点球", m.avoid]);
  singleRows.push([m.match, "让1胜平负", m.handicapLean, m.riskLevel, "进阶", m.handicapRisk, m.scores, m.totals, m.btts, `${m.handicapLine}: 赢2+为让胜，赢1为让平，否则让负`, m.avoid]);
  singleRows.push([m.match, "双重机会", m.doubleChance, "较低", "稳健", "降低单场冷门波动", m.scores, m.totals, m.btts, "适合串关降低风险", "低赔过多会压收益"]);
  singleRows.push([m.match, "比分/进球", m.scores.split(" / ")[0], "中高", "激进", "比分只做小注参考", m.scores, m.totals, m.btts, "比分与大小球联动", "大额压比分"]);
}
single.getRange(`A2:K${singleRows.length + 1}`).values = singleRows;
styleSheet(single, `A1:K${singleRows.length + 1}`);
header(single, "A1:K1");
single.getRange("A:A").format.columnWidthPx = 170;
single.getRange("B:K").format.columnWidthPx = 150;
single.freezePanes.freezeRows(1);

const handicap = workbook.worksheets.add("让1盘口");
handicap.getRange("A1:J1").values = [[
  "比赛", "让球队", "让胜条件", "让平条件", "让负条件", "首选", "次选", "不推荐", "关键比分", "理由"
]];
handicap.getRange("A2:J5").values = matches.map((m) => [
  m.match,
  m.favorite,
  `${m.favorite}赢2球或以上`,
  `${m.favorite}赢1球`,
  `${m.favorite}不胜或只打平/输球`,
  m.handicapLean.split("，")[0],
  m.handicapLean.includes("次选") ? m.handicapLean.split("次选")[1] : "按比分防线选择",
  m.avoid,
  m.scores,
  m.handicapRisk,
]);
styleSheet(handicap, "A1:J5");
header(handicap, "A1:J1");
handicap.getRange("A:A").format.columnWidthPx = 170;
handicap.getRange("B:J").format.columnWidthPx = 150;

const parlay = workbook.worksheets.add("串关组合");
parlay.getRange("A1:D1").values = [["组合类型", "组合内容", "风险", "说明"]];
parlay.getRange(`A2:D${parlays.length + 1}`).values = parlays;
styleSheet(parlay, `A1:D${parlays.length + 1}`);
header(parlay, "A1:D1");
parlay.getRange("A:A").format.columnWidthPx = 150;
parlay.getRange("B:B").format.columnWidthPx = 420;
parlay.getRange("C:C").format.columnWidthPx = 90;
parlay.getRange("D:D").format.columnWidthPx = 300;
parlay.freezePanes.freezeRows(1);

const matrix = workbook.worksheets.add("投注矩阵");
matrix.getRange("A1:F1").values = [["风险等级", "适合组合", "优先选择", "防线", "不建议", "说明"]];
matrix.getRange("A2:F6").values = [
  ["低", "单关/2串1", "瑞士胜、苏格兰胜", "瑞士不败、苏格兰不败", "弱队胜", "作为核心场次"],
  ["中", "2串1/3串1", "巴西不败、土耳其不败", "巴西防平、土耳其防平", "巴西-1让胜、土耳其-1让胜", "用不败比硬胜更合理"],
  ["中高", "比分/让球小注", "巴西2-1、土耳其0-1", "巴西1-1、土耳其1-1", "重注比分", "情景参考，不适合重仓"],
  ["高", "激进串关", "四场常规胜", "把M2/M4替换为不败", "全让胜串关", "收益高但断点集中"],
  ["防冷", "4串4/分散", "瑞士胜+苏格兰胜核心", "巴西不败+土耳其不败", "M2/M4同时硬胜", "分散巴西和土耳其的平局风险"],
];
styleSheet(matrix, "A1:F6");
header(matrix, "A1:F1");
matrix.getRange("A:F").format.columnWidthPx = 170;

const notes = workbook.worksheets.add("说明");
notes.getRange("A1:D1").values = [["项目", "说明", "限制", "动作"]];
notes.getRange("A2:D8").values = [
  ["口径", "全部为90分钟常规时间分析", "不含加时和点球", "淘汰赛需另建晋级模型"],
  ["让1", "强队让一球：赢2+为让胜，赢1为让平，不胜为让负", "不同平台规则可能不同", "下注前核对盘口"],
  ["串关", "2串1/3串1/4串1/4串4均为组合思路", "组合越多波动越高", "用核心场+防线场分散"],
  ["最高风险", "巴西 vs 摩洛哥、澳大利亚 vs 土耳其", "均存在平局/爆冷路径", "不建议两场同时硬胜重串"],
  ["核心场", "瑞士胜、苏格兰胜", "仍需首发确认", "赛前刷新"],
  ["赔率", "本报告未接入实时盘口，仅为模型和公开信息推演", "盘口变化会改变价值", "临场二次确认"],
  ["免责声明", "仅供分析参考，不构成投注建议", "足球单场随机性高", "控制风险"],
];
styleSheet(notes, "A1:D8");
header(notes, "A1:D1");
notes.getRange("A:D").format.columnWidthPx = 220;

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  summary: "formula error scan",
});
console.log(errors.ndjson);

const preview = await workbook.render({ sheetName: "总览", range: "A1:N5", scale: 1, format: "png" });
await fs.writeFile(path.join(outputDir, "世界杯4场完整下注场景_总览预览.png"), new Uint8Array(await preview.arrayBuffer()));

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputFile);
console.log(`SAVED:${outputFile}`);
