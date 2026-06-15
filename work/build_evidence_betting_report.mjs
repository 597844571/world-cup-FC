import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "C:/Users/59784/Documents/Codex/2026-06-13/import-pandas-as-pd-from-openpyxl/outputs";
const outputFile = path.join(outputDir, "世界杯4场预测_公开数据依据与下注场景报告.xlsx");

const sources = [
  ["卡塔尔 vs 瑞士", "ESPN Odds", "https://www.espn.com/soccer/odds/_/gameId/760420", "赔率/赛程确认"],
  ["卡塔尔 vs 瑞士", "JuveFC Preview", "https://www.juvefc.com/qatar-v-switzerland-predictions/", "瑞士热门和比分倾向参考"],
  ["巴西 vs 摩洛哥", "FOX Sports", "https://www.foxsports.com/stories/soccer/2026-world-cup-brazil-morocco-odds-prediction-picks", "赔率/预测参考"],
  ["巴西 vs 摩洛哥", "Covers", "https://www.covers.com/world-cup/brazil-vs-morocco-prediction-picks-odds-saturday-6-13-2026", "摩洛哥防守韧性和市场参考"],
  ["巴西 vs 摩洛哥", "Oddschecker", "https://www.oddschecker.com/us/soccer/world-cup/brazil-v-morocco", "公开赔率对比"],
  ["巴西 vs 摩洛哥", "The Sun", "https://www.the-sun.com/sport/16491227/brazil-vs-morocco-world-cup-2026/", "阵容/伤停新闻参考"],
  ["海地 vs 苏格兰", "Guardian", "https://www.theguardian.com/football/2026/jun/12/scotland-world-cup-football-haiti-steve-clarke", "苏格兰赛前阵容和动机"],
  ["海地 vs 苏格兰", "FOX Sports", "https://www.foxsports.com/stories/soccer/2026-world-cup-scotland-haiti-odds-predictions-picks", "赔率/预测参考"],
  ["海地 vs 苏格兰", "Covers", "https://www.covers.com/world-cup/haiti-vs-scotland-prediction-picks-odds-saturday-6-13-2026", "赔率/大小球参考"],
  ["澳大利亚 vs 土耳其", "Oddschecker", "https://www.oddschecker.com/us/soccer/world-cup/australia-v-turkey", "公开赔率对比"],
  ["澳大利亚 vs 土耳其", "Covers", "https://www.covers.com/world-cup/turkey-vs-australia-prediction-picks-odds-sunday-6-14-2026", "土耳其小优、比分参考"],
  ["澳大利亚 vs 土耳其", "Guardian", "https://www.theguardian.com/football/2026/jun/13/socceroos-world-cup-australia-football-team-preview", "澳大利亚球队状态/预期"],
];

const matches = [
  {
    code: "M1",
    match: "卡塔尔 vs 瑞士",
    market: "瑞士明显热门",
    model: "卡塔尔 14% / 平 23% / 瑞士 63%",
    final: "瑞士胜",
    handicap: "瑞士 -1：让平优先，防让胜",
    totals: "小3.5 / 2-3球",
    btts: "否略优",
    scores: "0-2 / 0-1 / 1-2",
    risk: "中低",
    confidence: "中",
    evidence: [
      "公开赔率和预测页均把瑞士列为明显热门。",
      "瑞士长期实力、中轴稳定性和欧洲大赛经验明显优于卡塔尔。",
      "卡塔尔爆冷路径集中在低位防守、定位球和门将发挥。",
    ],
    dimensions: [
      ["基础实力/市场", "瑞士强优势", "瑞士胜率底盘高"],
      ["过程质量", "瑞士", "预期控球和机会质量更稳定"],
      ["阵容首发", "待确认", "首发未公布，置信度不能拉满"],
      ["战术相克", "瑞士", "瑞士能持续压迫卡塔尔防线"],
      ["体能环境", "均衡", "温暖天气可能略降节奏"],
      ["定位球门将", "卡塔尔小点", "卡塔尔最现实爆冷路径"],
      ["爆冷触发器", "中低", "触发器强度不足"],
      ["动机", "瑞士", "首战抢分需求强"],
      ["裁判变量", "待确认", "临场尺度未知"],
    ],
    picks: ["稳健：瑞士不败", "均衡：瑞士胜", "进阶：瑞士-1让平", "激进：瑞士胜+小3.5"],
  },
  {
    code: "M2",
    match: "巴西 vs 摩洛哥",
    market: "巴西热门但非碾压",
    model: "巴西 55% / 平 25% / 摩洛哥 20%",
    final: "巴西小优，防平",
    handicap: "巴西 -1：让负优先，防让平",
    totals: "小3.5 / 2-3球",
    btts: "是略优",
    scores: "2-1 / 1-1 / 1-0 / 2-0",
    risk: "高",
    confidence: "中",
    evidence: [
      "Oddschecker/Covers 等公开赔率显示巴西热门，但赔率并非碾压。",
      "摩洛哥有世界杯四强经验，低位防守、反击、身体对抗和定位球路径完整。",
      "公开报道提到巴西存在核心伤情/缺阵变量，临场首发需要二次确认。",
    ],
    dimensions: [
      ["基础实力/市场", "巴西", "巴西天赋和市场支持更强"],
      ["过程质量", "巴西小优", "进攻创造力更高，但摩洛哥防守不可低估"],
      ["阵容首发", "待确认", "核心伤停和首发会改变结论"],
      ["战术相克", "分歧", "摩洛哥低位和反击能限制巴西"],
      ["体能环境", "均衡", "天气湿度需临场确认"],
      ["定位球门将", "摩洛哥小点", "定位球和门将是爆冷路径"],
      ["爆冷触发器", "高", "低防、反击、身体、定位球触发器多"],
      ["动机", "巴西", "首战仍有争胜需求"],
      ["裁判变量", "待确认", "尺度宽松利于摩洛哥身体对抗"],
    ],
    picks: ["稳健：巴西不败", "均衡：巴西胜小注", "进阶：巴西胜+小3.5", "防冷：1-1"],
  },
  {
    code: "M3",
    match: "海地 vs 苏格兰",
    market: "苏格兰明显热门",
    model: "海地 15% / 平 24% / 苏格兰 61%",
    final: "苏格兰胜",
    handicap: "苏格兰 -1：让平优先，防让胜",
    totals: "小3.5 / 1-3球",
    btts: "否略优",
    scores: "0-2 / 0-1 / 1-1 / 1-2",
    risk: "中低",
    confidence: "中",
    evidence: [
      "FOX/Covers/Oddschecker 类公开赔率均显示苏格兰明显热门。",
      "Guardian 赛前报道强调苏格兰核心和回归世界杯后的动机。",
      "海地速度和转换有威胁，但整体经验、中场质量和深度弱于苏格兰。",
    ],
    dimensions: [
      ["基础实力/市场", "苏格兰", "市场和实力都支持苏格兰"],
      ["过程质量", "苏格兰", "预期机会质量更稳定"],
      ["阵容首发", "待确认", "首发和伤停仍需临场确认"],
      ["战术相克", "苏格兰", "身体和中场对抗占优"],
      ["体能环境", "均衡", "旅行和天气待确认"],
      ["定位球门将", "苏格兰", "高点和定位球可能有优势"],
      ["爆冷触发器", "中低", "海地速度是主要风险"],
      ["动机", "苏格兰", "首战抢分动机强"],
      ["裁判变量", "待确认", "高对抗尺度可能影响节奏"],
    ],
    picks: ["稳健：苏格兰不败", "均衡：苏格兰胜", "进阶：苏格兰-1让平", "防冷：1-1"],
  },
  {
    code: "M4",
    match: "澳大利亚 vs 土耳其",
    market: "土耳其小热门",
    model: "澳大利亚 22% / 平 27% / 土耳其 51%",
    final: "土耳其不败，小胜倾向",
    handicap: "土耳其 -1：让负优先",
    totals: "小2.5 / 小3.5",
    btts: "否略优，防1-1",
    scores: "0-1 / 1-1 / 0-2 / 1-2",
    risk: "中高",
    confidence: "中",
    evidence: [
      "Oddschecker/Covers 等公开赔率给土耳其小热门，不是大热门。",
      "澳大利亚公开报道显示球队年轻化且有稳定世界杯经验。",
      "澳大利亚身体、定位球和防守纪律会压低土耳其穿盘概率。",
    ],
    dimensions: [
      ["基础实力/市场", "土耳其", "技术和市场小优"],
      ["过程质量", "土耳其小优", "创造力更强但不是碾压"],
      ["阵容首发", "待确认", "核心中场和锋线首发需确认"],
      ["战术相克", "分歧", "澳大利亚能拖慢节奏"],
      ["体能环境", "均衡", "BC Place环境变量相对低"],
      ["定位球门将", "澳大利亚", "定位球和身体对抗是武器"],
      ["爆冷触发器", "中高", "平局路径强于澳洲胜路径"],
      ["动机", "土耳其", "首战争胜但需避免失误"],
      ["裁判变量", "待确认", "宽松尺度利于澳大利亚"],
    ],
    picks: ["稳健：土耳其不败", "均衡：土耳其胜小注", "进阶：土耳其胜+小3.5", "防冷：1-1"],
  },
];

const parlays = [
  ["稳健2串1核心", "瑞士胜 + 苏格兰胜", "中低", "四场里最清晰的核心组合"],
  ["稳健3串1", "瑞士胜 + 苏格兰胜 + 巴西不败", "中", "用巴西不败规避摩洛哥逼平风险"],
  ["稳健3串1", "瑞士胜 + 苏格兰胜 + 土耳其不败", "中", "用土耳其不败规避1-1风险"],
  ["均衡4串1", "瑞士胜 + 巴西不败 + 苏格兰胜 + 土耳其不败", "中", "主线参考，不追四场全胜"],
  ["激进4串1", "瑞士胜 + 巴西胜 + 苏格兰胜 + 土耳其胜", "高", "断点集中在巴西和土耳其"],
  ["让1组合", "瑞士-1让平 + 巴西-1让负 + 苏格兰-1让平 + 土耳其-1让负", "中高", "更符合小比分和穿盘风险"],
  ["4串4组1", "瑞士胜 + 苏格兰胜 + 巴西不败", "中", "去掉土耳其单胜风险"],
  ["4串4组2", "瑞士胜 + 苏格兰胜 + 土耳其不败", "中", "去掉巴西单胜风险"],
  ["4串4组3", "瑞士胜 + 巴西不败 + 土耳其不败", "中", "双不败降低冷门风险"],
  ["4串4组4", "苏格兰胜 + 巴西不败 + 土耳其不败", "中", "瑞士不放入时收益降低但风险分散"],
];

await fs.mkdir(outputDir, { recursive: true });
const workbook = Workbook.create();

function styleRange(ws, range) {
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
function setup(ws) {
  ws.showGridLines = false;
  ws.freezePanes.freezeRows(1);
}

const overview = workbook.worksheets.add("总览");
setup(overview);
overview.getRange("A1:M1").values = [[
  "编号", "比赛", "市场判断", "模型概率", "最终倾向", "让1建议", "大小球", "BTTS", "比分参考", "风险", "置信度", "稳健选择", "防冷点"
]];
overview.getRange("A2:M5").values = matches.map((m) => [
  m.code, m.match, m.market, m.model, m.final, m.handicap, m.totals, m.btts, m.scores, m.risk, m.confidence, m.picks[0], m.picks.at(-1),
]);
styleRange(overview, "A1:M5");
header(overview, "A1:M1");
overview.getRange("A:A").format.columnWidthPx = 60;
overview.getRange("B:B").format.columnWidthPx = 170;
overview.getRange("C:M").format.columnWidthPx = 150;
overview.tables.add("A1:M5", true, "EvidenceOverview").style = "TableStyleMedium2";

const evidence = workbook.worksheets.add("公开数据依据");
setup(evidence);
evidence.getRange("A1:D1").values = [["比赛", "公开依据", "来源类型", "对测算的影响"]];
const evidenceRows = [];
for (const m of matches) {
  for (const item of m.evidence) {
    evidenceRows.push([m.match, item, "公开赔率/新闻/赛程", "用于修正胜平负、让1和风险等级"]);
  }
}
evidence.getRange(`A2:D${evidenceRows.length + 1}`).values = evidenceRows;
styleRange(evidence, `A1:D${evidenceRows.length + 1}`);
header(evidence, "A1:D1");
evidence.getRange("A:A").format.columnWidthPx = 170;
evidence.getRange("B:B").format.columnWidthPx = 430;
evidence.getRange("C:D").format.columnWidthPx = 180;

const deep = workbook.worksheets.add("逐场深度分析");
setup(deep);
deep.getRange("A1:E1").values = [["比赛", "维度", "优势方/等级", "判断依据", "下注影响"]];
const deepRows = [];
for (const m of matches) {
  for (const d of m.dimensions) {
    const impact = d[0].includes("爆冷") ? "影响防平、防让负和串关风险" : d[0].includes("基础") ? "决定胜平负底盘" : "修正比分/大小球/让球方向";
    deepRows.push([m.match, d[0], d[1], d[2], impact]);
  }
}
deep.getRange(`A2:E${deepRows.length + 1}`).values = deepRows;
styleRange(deep, `A1:E${deepRows.length + 1}`);
header(deep, "A1:E1");
deep.getRange("A:A").format.columnWidthPx = 170;
deep.getRange("B:B").format.columnWidthPx = 170;
deep.getRange("C:C").format.columnWidthPx = 120;
deep.getRange("D:E").format.columnWidthPx = 260;

const betting = workbook.worksheets.add("下注场景");
setup(betting);
betting.getRange("A1:K1").values = [["比赛", "胜平负", "让1", "双重机会", "大小球", "BTTS", "比分", "稳健", "均衡", "激进", "避开"]];
betting.getRange("A2:K5").values = matches.map((m) => [
  m.match, m.final, m.handicap, m.picks[0].replace("稳健：", ""), m.totals, m.btts, m.scores,
  m.picks[0], m.picks[1], m.picks[2], m.risk === "高" ? "让胜重仓/大胜逻辑" : "弱队胜或重注比分",
]);
styleRange(betting, "A1:K5");
header(betting, "A1:K1");
betting.getRange("A:A").format.columnWidthPx = 170;
betting.getRange("B:K").format.columnWidthPx = 155;

const parlay = workbook.worksheets.add("串关与组合");
setup(parlay);
parlay.getRange("A1:D1").values = [["类型", "组合", "风险", "说明"]];
parlay.getRange(`A2:D${parlays.length + 1}`).values = parlays;
styleRange(parlay, `A1:D${parlays.length + 1}`);
header(parlay, "A1:D1");
parlay.getRange("A:A").format.columnWidthPx = 150;
parlay.getRange("B:B").format.columnWidthPx = 420;
parlay.getRange("C:C").format.columnWidthPx = 90;
parlay.getRange("D:D").format.columnWidthPx = 310;

const sourceSheet = workbook.worksheets.add("来源清单");
setup(sourceSheet);
sourceSheet.getRange("A1:D1").values = [["比赛", "来源", "URL", "用途"]];
sourceSheet.getRange(`A2:D${sources.length + 1}`).values = sources;
styleRange(sourceSheet, `A1:D${sources.length + 1}`);
header(sourceSheet, "A1:D1");
sourceSheet.getRange("A:A").format.columnWidthPx = 170;
sourceSheet.getRange("B:B").format.columnWidthPx = 160;
sourceSheet.getRange("C:C").format.columnWidthPx = 500;
sourceSheet.getRange("D:D").format.columnWidthPx = 220;

const notes = workbook.worksheets.add("说明");
setup(notes);
notes.getRange("A1:D1").values = [["项目", "说明", "限制", "建议动作"]];
notes.getRange("A2:D10").values = [
  ["预测口径", "全部为90分钟常规时间", "不含加时和点球", "淘汰赛需单独建晋级模型"],
  ["价格价值", "看好方向不等于可以买", "EV≤0不进入候选池", "按公允SP、EV、风险分判断"],
  ["公开数据", "使用公开赔率、公开新闻、公开赛程作为依据", "不是实时官方盘口", "临场刷新赔率和首发"],
  ["让球", "G_home + H - G_away；大于0让胜，等于0让平，小于0让负", "不同平台可能有不同显示", "下注前核对盘口规则"],
  ["复选包", "按 SUM(p_i×SP_i)/注数 - 1 计算包EV", "不能只看命中率", "SP缺失则不计算"],
  ["串关", "串关只从正EV候选池生成", "负EV腿不硬串，组合越多波动越高", "组合EV需≥5%"],
  ["最高风险", "巴西 vs 摩洛哥、澳大利亚 vs 土耳其", "均存在平局路径", "避免两场同时硬胜重串"],
  ["回测", "后续应用完场结果回测 CLV、ROI、Brier、Log Loss", "样本少时不可过度调参", "赛前归档预测"],
  ["免责声明", "仅供分析参考，不构成投注建议", "足球单场随机性高", "控制风险"],
];
styleRange(notes, "A1:D10");
header(notes, "A1:D1");
notes.getRange("A:D").format.columnWidthPx = 230;

const rules = workbook.worksheets.add("v5报告规则");
setup(rules);
rules.getRange("A1:E1").values = [["模块", "必须输出", "核心公式", "红线", "说明"]];
rules.getRange("A2:E9").values = [
  ["赔率快照", "时间、来源、盘口、赔率、隐含概率、去水概率、变化", "隐含概率=1/赔率；去水=隐含/合计", "无时间戳不做严肃判断", "同一场不同时间点价格可能对应完全不同结论"],
  ["胜平负模型", "市场去水、Δ修正、模型概率、公允SP、EV", "softmax(ln(市场概率)+Δ)", "模型/市场差异>15%必须复核", "市场做底盘，基本面只做小幅修正"],
  ["进球模型", "λ_home、λ_away、比分、总进球、大小球、BTTS", "Poisson比分矩阵", "不能混淆总进球和大小球", "总进球输出0/1/2/3/4/5/6/7+"],
  ["体彩建议池", "玩法、选项、SP、模型概率、公允SP、EV、风险、Kelly、动作、原因", "EV=p×SP-1；Kelly=(SP×p-1)/(SP-1)", "EV≤0放弃", "没有体彩SP时只显示等待SP"],
  ["复选包", "选项集合、注数、命中率、包EV、建议倍数", "包EV=SUM(p_i×SP_i)/注数-1", "SP缺失不计算", "不败、防平、比分组、进球数组都按复选包处理"],
  ["串关组合", "单腿EV、组合概率、组合SP、组合EV、相关性风险", "组合EV=PRODUCT(p_i)×PRODUCT(SP_i)-1", "负EV腿禁止硬串", "同场不同玩法不得混入同一串"],
  ["放弃清单", "放弃项、放弃原因、价格差、风险分", "按EV、风险、SP缺失、相关性判断", "低赔无价值不追", "放弃清单是报告必备项"],
  ["赛后复盘", "投注时SP、收盘价、结果、CLV、ROI、Brier、Log Loss", "CLV=下注赔率/收盘赔率-1", "不能用赛后信息倒填赛前预测", "用于长期校准，不按单场成败过度调参"],
];
styleRange(rules, "A1:E9");
header(rules, "A1:E1");
rules.getRange("A:A").format.columnWidthPx = 130;
rules.getRange("B:E").format.columnWidthPx = 260;

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  summary: "formula error scan",
});
console.log(errors.ndjson);

const preview = await workbook.render({ sheetName: "总览", range: "A1:M5", scale: 1, format: "png" });
await fs.writeFile(path.join(outputDir, "世界杯4场公开数据依据报告_总览预览.png"), new Uint8Array(await preview.arrayBuffer()));

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputFile);
console.log(`SAVED:${outputFile}`);
