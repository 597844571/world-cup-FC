import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "C:/Users/59784/Documents/Codex/2026-06-13/import-pandas-as-pd-from-openpyxl/outputs";
const outputFile = path.join(outputDir, "世界杯未开赛4场预测报告_多组赔率.xlsx");

const matches = [
  {
    id: "QAT_SUI",
    match: "卡塔尔 vs 瑞士",
    stage: "Group B",
    venue: "Santa Clara / Levi's Stadium",
    kickoff: "2026-06-13 中国时间约凌晨3点",
    confidence: "中",
    upset: "低",
    rhythm: "瑞士控节奏，卡塔尔低位防守",
    goals: "1-3球，偏小比分",
    finalLean: "瑞士胜",
    risk: "卡塔尔低位防守、定位球和门将发挥；首发/临场天气仍需确认",
    tactical: "瑞士中轴稳定、经验和整体压制更强；卡塔尔需要压缩空间并等待定位球。",
    probs: { home: 0.12, draw: 0.22, away: 0.66 },
    scores: ["0-2", "0-1", "1-2", "1-1"],
    oddsGroups: [
      { source: "基准模型", home: 6.13, draw: 3.93, away: 1.72, note: "Elo/实力底盘" },
      { source: "市场参考", home: 10.50, draw: 5.30, away: 1.25, note: "公开赔率参考，瑞士明显热门" },
      { source: "保守节奏", home: 7.90, draw: 3.45, away: 1.84, note: "低节奏上调平局" },
      { source: "开放节奏", home: 5.60, draw: 4.80, away: 1.66, note: "早进球后胜负分出" },
      { source: "爆冷情景", home: 5.95, draw: 3.85, away: 1.75, note: "卡塔尔低防+定位球" },
    ],
    dimensions: [
      ["基础实力 / Elo / 市场概率", "瑞士", "瑞士强优势，市场也支持瑞士"],
      ["xG / xGA / 射门质量", "瑞士", "瑞士进攻质量和防守稳定性更好"],
      ["阵容伤停与首发", "待确认", "首发未公布，置信度不能拉满"],
      ["战术相克与比赛形态", "瑞士", "瑞士更容易把比赛压进半场控制"],
      ["赛程 / 体能 / 气候", "均衡", "温暖天气可能降低压迫强度"],
      ["定位球与门将", "卡塔尔小点", "卡塔尔爆冷主要靠定位球"],
      ["爆冷触发器", "低", "触发器不足，不宜高估爆冷"],
      ["积分形势 / 动机", "瑞士", "首战抢分动机强"],
      ["裁判变量", "待确认", "临场裁判尺度未知"],
    ],
  },
  {
    id: "BRA_MAR",
    match: "巴西 vs 摩洛哥",
    stage: "Group C",
    venue: "New Jersey / MetLife",
    kickoff: "2026-06-13 中国时间约6点",
    confidence: "中高",
    upset: "中高",
    rhythm: "巴西主动，摩洛哥低防+反击",
    goals: "2-3球，BTTS有空间",
    finalLean: "巴西小优，防平",
    risk: "摩洛哥低位防守、身体对抗、反击和定位球；巴西若久攻不下容易被拖入低比分",
    tactical: "巴西个人能力和边路爆点占优；摩洛哥有明确的不败路径。",
    probs: { home: 0.53, draw: 0.27, away: 0.20 },
    scores: ["2-1", "1-1", "1-0", "2-0"],
    oddsGroups: [
      { source: "基准模型", home: 1.89, draw: 3.79, away: 4.85, note: "模型显示巴西小优" },
      { source: "市场参考", home: 1.63, draw: 4.10, away: 6.00, note: "市场更偏巴西" },
      { source: "保守节奏", home: 2.12, draw: 3.24, away: 4.15, note: "低节奏/破密防困难" },
      { source: "开放节奏", home: 1.75, draw: 4.65, away: 4.05, note: "早进球后巴西空间更大" },
      { source: "爆冷情景", home: 2.22, draw: 3.24, away: 4.15, note: "摩洛哥低防成功，平局上调" },
    ],
    dimensions: [
      ["基础实力 / Elo / 市场概率", "巴西", "巴西整体天赋和市场支持更强"],
      ["xG / xGA / 射门质量", "巴西小优", "巴西创造力更好，但摩洛哥防守质量不能低估"],
      ["阵容伤停与首发", "待确认", "内马尔缺席/核心状态需要二次确认"],
      ["战术相克与比赛形态", "分歧", "巴西主动，摩洛哥能用低防和反击制造不适"],
      ["赛程 / 体能 / 气候", "均衡", "临场天气湿度需确认"],
      ["定位球与门将", "摩洛哥小点", "摩洛哥定位球和门将发挥是爆冷路径"],
      ["爆冷触发器", "中高", "低防、反击、身体、定位球触发器较多"],
      ["积分形势 / 动机", "巴西", "首战争胜，但不能过热"],
      ["裁判变量", "待确认", "尺度宽松会利于摩洛哥身体对抗"],
    ],
  },
  {
    id: "HAI_SCO",
    match: "海地 vs 苏格兰",
    stage: "Group C",
    venue: "Foxborough / Gillette",
    kickoff: "2026-06-13 中国时间约9点",
    confidence: "中",
    upset: "低到中低",
    rhythm: "苏格兰身体和中场优势，海地速度反击",
    goals: "1-3球，偏苏格兰小胜",
    finalLean: "苏格兰胜",
    risk: "苏格兰若久攻不下，海地速度反击可能把比赛拖成1-1",
    tactical: "苏格兰经验、身体和中轴更稳；海地需要利用速度和转换。",
    probs: { home: 0.15, draw: 0.24, away: 0.61 },
    scores: ["0-2", "0-1", "1-1", "1-2"],
    oddsGroups: [
      { source: "基准模型", home: 6.90, draw: 4.00, away: 1.65, note: "Elo/实力差支持苏格兰" },
      { source: "市场参考", home: 6.40, draw: 4.30, away: 1.52, note: "公开赔率显示苏格兰明显热门" },
      { source: "保守节奏", home: 6.67, draw: 3.92, away: 1.68, note: "海地低位和苏格兰谨慎" },
      { source: "开放节奏", home: 5.75, draw: 4.85, away: 1.63, note: "海地必须争取机会后空间增大" },
      { source: "爆冷情景", home: 6.67, draw: 3.92, away: 1.68, note: "海地反击速度制造平局空间" },
    ],
    dimensions: [
      ["基础实力 / Elo / 市场概率", "苏格兰", "苏格兰明显占优"],
      ["xG / xGA / 射门质量", "苏格兰", "预计苏格兰机会质量更稳定"],
      ["阵容伤停与首发", "待确认", "首发和伤停未完全确认"],
      ["战术相克与比赛形态", "苏格兰", "身体和中场对抗占优"],
      ["赛程 / 体能 / 气候", "均衡", "旅行和天气需临场确认"],
      ["定位球与门将", "苏格兰", "定位球和高点优势可能明显"],
      ["爆冷触发器", "低到中低", "海地速度是主要不确定性"],
      ["积分形势 / 动机", "苏格兰", "首战抢分需求强"],
      ["裁判变量", "待确认", "高对抗尺度可能影响节奏"],
    ],
  },
  {
    id: "AUS_TUR",
    match: "澳大利亚 vs 土耳其",
    stage: "Group D",
    venue: "Vancouver / BC Place",
    kickoff: "2026-06-13 中国时间约午夜",
    confidence: "中",
    upset: "中低",
    rhythm: "土耳其控球创造，澳大利亚低防+定位球",
    goals: "1-2球，偏小比分",
    finalLean: "土耳其小优，不败更稳",
    risk: "澳大利亚身体、定位球和防守结构可能把比赛拖成1-1",
    tactical: "土耳其技术和创造力更强；澳大利亚能用身体、纪律和定位球压低比分。",
    probs: { home: 0.23, draw: 0.28, away: 0.49 },
    scores: ["0-1", "1-1", "0-2", "1-2"],
    oddsGroups: [
      { source: "基准模型", home: 4.32, draw: 3.72, away: 2.00, note: "土耳其小优" },
      { source: "市场参考", home: 4.60, draw: 3.55, away: 1.78, note: "市场略更看好土耳其" },
      { source: "保守节奏", home: 4.06, draw: 3.40, away: 2.17, note: "平局和低比分上调" },
      { source: "开放节奏", home: 3.95, draw: 4.35, away: 1.92, note: "早进球后胜负分出" },
      { source: "爆冷情景", home: 4.06, draw: 3.41, away: 2.17, note: "澳大利亚定位球/低防成功" },
    ],
    dimensions: [
      ["基础实力 / Elo / 市场概率", "土耳其", "土耳其技术和市场倾向小优"],
      ["xG / xGA / 射门质量", "土耳其小优", "创造力更好，但优势不是碾压"],
      ["阵容伤停与首发", "待确认", "核心中场和锋线首发需确认"],
      ["战术相克与比赛形态", "分歧", "土耳其怕被澳洲拖慢和消耗"],
      ["赛程 / 体能 / 气候", "均衡", "BC Place环境变量较低"],
      ["定位球与门将", "澳大利亚", "澳大利亚定位球和身体对抗是主要武器"],
      ["爆冷触发器", "中低", "平局路径比澳洲胜更现实"],
      ["积分形势 / 动机", "土耳其", "首战争胜，但避免失误也重要"],
      ["裁判变量", "待确认", "宽松尺度利于澳大利亚身体对抗"],
    ],
  },
];

function implied(odds) {
  const raw = { home: 1 / odds.home, draw: 1 / odds.draw, away: 1 / odds.away };
  const total = raw.home + raw.draw + raw.away;
  return { home: raw.home / total, draw: raw.draw / total, away: raw.away / total, overround: total - 1 };
}

function pct(v) {
  return `${(v * 100).toFixed(1)}%`;
}

await fs.mkdir(outputDir, { recursive: true });
const workbook = Workbook.create();

const overview = workbook.worksheets.add("总览");
overview.showGridLines = false;
overview.getRange("A1:K1").values = [[
  "比赛", "阶段", "地点", "开赛时间", "主胜", "平局", "客胜", "主比分", "备选比分", "爆冷等级", "最终倾向"
]];
overview.getRange("A2:K5").values = matches.map((m) => [
  m.match,
  m.stage,
  m.venue,
  m.kickoff,
  pct(m.probs.home),
  pct(m.probs.draw),
  pct(m.probs.away),
  m.scores[0],
  m.scores.slice(1).join(" / "),
  m.upset,
  m.finalLean,
]);

for (const sheet of [overview]) {
  sheet.getRange("A1:K1").format = {
    fill: "#111827",
    font: { bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "middle",
  };
  sheet.getRange("A1:K5").format.borders = { preset: "all", style: "thin", color: "#CBD5E1" };
  sheet.getRange("A:K").format.wrapText = true;
  sheet.getRange("A:A").format.columnWidthPx = 170;
  sheet.getRange("B:B").format.columnWidthPx = 90;
  sheet.getRange("C:D").format.columnWidthPx = 180;
  sheet.getRange("E:G").format.columnWidthPx = 80;
  sheet.getRange("H:J").format.columnWidthPx = 120;
  sheet.getRange("K:K").format.columnWidthPx = 180;
  sheet.freezePanes.freezeRows(1);
}
overview.tables.add("A1:K5", true, "OverviewTable").style = "TableStyleMedium2";

for (const m of matches) {
  const sheetName = m.match.replace(" vs ", "-").slice(0, 31);
  const ws = workbook.worksheets.add(sheetName);
  ws.showGridLines = false;

  ws.getRange("A1:F1").merge();
  ws.getRange("A1").values = [[`比赛预测：${m.match}`]];
  ws.getRange("A1").format = {
    fill: "#0F766E",
    font: { bold: true, color: "#FFFFFF", size: 14 },
    horizontalAlignment: "center",
  };

  ws.getRange("A3:F10").values = [
    ["字段", "内容", "", "胜平负概率", "概率", "备注"],
    ["阶段", m.stage, "", "主胜", pct(m.probs.home), m.match.split(" vs ")[0]],
    ["地点", m.venue, "", "平局", pct(m.probs.draw), "90分钟"],
    ["开赛", m.kickoff, "", "客胜", pct(m.probs.away), m.match.split(" vs ")[1]],
    ["比赛节奏", m.rhythm, "", "主比分", m.scores[0], ""],
    ["进球倾向", m.goals, "", "备选比分", m.scores.slice(1).join(" / "), ""],
    ["爆冷等级", m.upset, "", "置信度", m.confidence, ""],
    ["最终倾向", m.finalLean, "", "最大风险", m.risk, ""],
  ];

  ws.getRange("A12:F12").values = [["赔率组", "主胜赔率", "平局赔率", "客胜赔率", "去水主胜", "说明"]];
  ws.getRange("A13:F17").values = m.oddsGroups.map((row) => {
    const p = implied(row);
    return [row.source, row.home, row.draw, row.away, pct(p.home), row.note];
  });

  ws.getRange("H12:L12").values = [["赔率组", "去水平局", "去水客胜", "庄家水位", "市场解释"]];
  ws.getRange("H13:L17").values = m.oddsGroups.map((row) => {
    const p = implied(row);
    return [row.source, pct(p.draw), pct(p.away), pct(p.overround), row.note];
  });

  ws.getRange("A20:C20").values = [["维度", "优势方", "判断"]];
  ws.getRange(`A21:C${20 + m.dimensions.length}`).values = m.dimensions;

  ws.getRange("E20:F20").values = [["关键判断", "内容"]];
  ws.getRange("E21:F25").values = [
    ["支持主队", m.match.includes("巴西") ? "个人能力、市场支持、进攻深度" : "主要依靠低位防守、定位球或身体对抗"],
    ["支持客队", m.finalLean],
    ["支持平局", m.upset.includes("中") ? "爆冷触发器存在，低比分和平局空间需要保留" : "若强队久攻不下，平局作为风险比分"],
    ["战术关键", m.tactical],
    ["风险提示", "首发、伤停、天气、裁判和临场赔率需二次确认"],
  ];

  for (const range of ["A3:F10", "A12:F17", "H12:L17", "A20:C29", "E20:F25"]) {
    ws.getRange(range).format.borders = { preset: "all", style: "thin", color: "#CBD5E1" };
    ws.getRange(range).format.wrapText = true;
    ws.getRange(range).format.verticalAlignment = "top";
  }
  for (const header of ["A3:F3", "A12:F12", "H12:L12", "A20:C20", "E20:F20"]) {
    ws.getRange(header).format = {
      fill: "#1F2937",
      font: { bold: true, color: "#FFFFFF" },
      horizontalAlignment: "center",
      verticalAlignment: "middle",
    };
  }
  ws.getRange("A:A").format.columnWidthPx = 130;
  ws.getRange("B:B").format.columnWidthPx = 260;
  ws.getRange("C:C").format.columnWidthPx = 40;
  ws.getRange("D:F").format.columnWidthPx = 130;
  ws.getRange("H:L").format.columnWidthPx = 130;
  ws.getRange("A1:L29").format.font = { size: 10 };
  ws.freezePanes.freezeRows(2);
}

const note = workbook.worksheets.add("说明");
note.showGridLines = false;
note.getRange("A1:D1").values = [["说明项", "内容", "限制", "后续动作"]];
note.getRange("A2:D6").values = [
  ["赔率组", "每场包含基准、市场、保守、开放、爆冷五组赔率", "赔率为公开信息+模型换算参考，不是官方实时盘口", "接入公开源后可刷新快照"],
  ["预测口径", "均为90分钟常规时间倾向", "不含加时/点球晋级概率", "淘汰赛另行建模"],
  ["置信度", "根据数据完整度、赔率分歧、临场信息确认度综合判断", "首发未公布时不应给满", "开赛前二次确认"],
  ["风险", "红牌、点球、首发轮换、天气、裁判尺度会显著改变结果", "足球单场随机性高", "临场刷新"],
  ["用途", "用于赛前分析和多情景参考", "不构成投注建议", "赛后归档回测优化规则"],
];
note.getRange("A1:D6").format.borders = { preset: "all", style: "thin", color: "#CBD5E1" };
note.getRange("A1:D1").format = { fill: "#111827", font: { bold: true, color: "#FFFFFF" } };
note.getRange("A:D").format.columnWidthPx = 220;
note.getRange("A1:D6").format.wrapText = true;

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  summary: "formula error scan",
});
console.log(errors.ndjson);

const preview = await workbook.render({
  sheetName: "总览",
  range: "A1:K5",
  scale: 1,
  format: "png",
});
await fs.writeFile(path.join(outputDir, "世界杯未开赛4场预测报告_总览预览.png"), new Uint8Array(await preview.arrayBuffer()));

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputFile);
console.log(`SAVED:${outputFile}`);
