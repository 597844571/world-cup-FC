from __future__ import annotations

from typing import Any

from .config import SOURCE_HEALTH_PATH, SOURCES_PATH, load_json, save_json


DEFAULT_SOURCES = [
    {
        "source_id": "manual_consensus",
        "name": "手动共识赔率",
        "type": "manual",
        "enabled": True,
        "priority": 100,
        "reliability": "high",
        "notes": "没有公开源或 API key 时使用 matches.json 里的 manual_odds。",
    },
    {
        "source_id": "sporttery_official_match_list",
        "name": "中国体彩竞彩足球赛程官方接口",
        "type": "sporttery_official_match_list",
        "enabled": True,
        "priority": 9,
        "url": "https://webapi.sporttery.cn/gateway/uniform/football/getMatchListV1.qry?clientCode=3001",
        "referer": "https://www.lottery.gov.cn/jc/zqszsc/",
        "bookmaker": "中国体育彩票",
        "requires_browser": False,
        "reliability": "official",
        "polite_delay_seconds": 0.4,
        "notes": "官方竞彩足球赛程页接口，作为第一优先级盘口/SP源，提供比赛编号、开售状态、单关/过关、让球数和部分SP。",
    },
    {
        "source_id": "sporttery_mobile_calculator",
        "name": "中国体彩竞彩足球移动端计算器",
        "type": "sporttery_official_calculator",
        "enabled": True,
        "priority": 12,
        "url": "https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry?channel=m&poolCode=had,hhad,crs,ttg,hafu",
        "referer": "https://m.sporttery.cn/mjc/jsq/zqspf/",
        "bookmaker": "中国体育彩票",
        "pool_codes": ["had", "hhad", "crs", "ttg", "hafu"],
        "requires_browser": False,
        "reliability": "official",
        "polite_delay_seconds": 0.8,
        "notes": "官方移动端足球计算器补充源，可提供更完整的比分、总进球、半全场SP；若触发WAF则自动降级。",
    },
    {
        "source_id": "candidate_public_html",
        "name": "公开 HTML 候选源模板",
        "type": "public_html_regex",
        "enabled": False,
        "priority": 20,
        "url": "",
        "requires_browser": False,
        "reliability": "unknown",
        "patterns": {
            "home": "",
            "draw": "",
            "away": "",
        },
        "notes": "由 AI 发现并确认公开页面后再启用。只解析无需登录、无需验证码、无需绕反爬的公开页面。",
    },
    {
        "source_id": "bing_worldcup_standings",
        "name": "Bing 世界杯积分榜",
        "type": "bing_worldcup_standings",
        "enabled": True,
        "priority": 15,
        "url": "https://cn.bing.com/sportsdetails?q=%E4%B8%96%E7%95%8C%E6%9D%AF%E6%8A%A5%E9%81%93%20%E7%BB%9F%E8%AE%A1%E4%BF%A1%E6%81%AF&sport=Soccer&scenario=League&TimezoneId=China%20Standard%20Time&IANATimezoneId=Asia/Shanghai&ISOTimezoneKey=CST&league=Soccer_InternationalWorldCup&intent=Standings&seasonyear=2026&segment=sports&isl2=true&form=ARENL1&",
        "requires_browser": False,
        "reliability": "public_aggregator",
        "polite_delay_seconds": 0.8,
        "notes": "公开积分榜来源，只用于小组积分、净胜球、已赛状态、赛后验证和动机修正；不作为赔率或下注价格来源。",
    },
    {
        "source_id": "aicai_worldcup_stats",
        "name": "新浪爱彩世界杯数据统计",
        "type": "aicai_worldcup_stats",
        "enabled": True,
        "priority": 16,
        "url": "https://live.aicai.com/league/index.htm?leagueId=1999&tab=4",
        "api_url": "https://sport.ttyingqiu.com/sportdata/f",
        "requires_browser": False,
        "reliability": "public_aggregator",
        "polite_delay_seconds": 0.8,
        "notes": "公开世界杯数据统计源，提供赛程赛果、欧赔初赔/即时赔、让球市场参考、总进球市场参考、半全场和常见比分统计；用于市场倍率变化、回测和算法修正，不作为中国体彩可下单选项。",
    },
    {
        "source_id": "msn_worldcup_process",
        "name": "MSN世界杯赛中/赛后过程统计",
        "type": "msn_match_process",
        "enabled": False,
        "priority": 18,
        "url": "https://www.msn.cn/zh-cn/sports/soccer/fifa_world_cup?uxmode=ruby&ocid=msedgntp&cvid=6a2f6074157e4350bf3f1f17e4019e31&pc=LCTS&ei=27",
        "requires_browser": False,
        "reliability": "public_aggregator",
        "polite_delay_seconds": 0.8,
        "notes": "备用过程数据源。MSN聚合页不稳定，默认停用；只有发现稳定JSON接口或手工配置正则后再启用。",
    },
    {
        "source_id": "candidate_public_json",
        "name": "公开 JSON 候选源模板",
        "type": "public_json_path",
        "enabled": False,
        "priority": 30,
        "url": "",
        "requires_browser": False,
        "reliability": "unknown",
        "paths": {
            "home": "",
            "draw": "",
            "away": "",
        },
        "notes": "由 AI 发现并确认公开 JSON 后再启用。paths 使用点路径，例如 odds.home。",
    },
]


def load_sources() -> list[dict[str, Any]]:
    sources = load_json(SOURCES_PATH, None)
    if sources is None:
        save_json(SOURCES_PATH, DEFAULT_SOURCES)
        sources = DEFAULT_SOURCES
    else:
        existing = {source.get("source_id") for source in sources}
        missing = [source for source in DEFAULT_SOURCES if source.get("source_id") not in existing]
        if missing:
            sources = [*sources, *missing]
            save_json(SOURCES_PATH, sources)
    return sources


def save_sources(sources: list[dict[str, Any]]) -> None:
    save_json(SOURCES_PATH, sources)


def load_source_health() -> dict[str, Any]:
    return load_json(SOURCE_HEALTH_PATH, {})


def save_source_health(health: dict[str, Any]) -> None:
    save_json(SOURCE_HEALTH_PATH, health)
