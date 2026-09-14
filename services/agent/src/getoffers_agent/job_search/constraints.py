"""Bounded, deterministic city intent parsing before any candidate retrieval.

City names come from visible facts and a small Chinese city vocabulary. This is
not general geographic NER: only supported location phrases become hard filters.
"""

import re
from collections import defaultdict
from collections.abc import Iterable

from getoffers_agent.job_search.contracts import HardConstraints, SearchRequest, text

CITY_PARSER_VERSION = "city-intent-v1"
CITY_CONNECTOR = re.compile(r"\s*(?:或(?:者)?|和|及|、|/|,|or|and)\s*", re.I)
CHINESE_CITIES = (
    "北京 上海 广州 深圳 杭州 南京 苏州 成都 重庆 武汉 西安 长沙 合肥 天津 "
    "郑州 济南 青岛 厦门 福州 珠海 东莞 佛山 无锡 宁波 大连 沈阳 香港 澳门"
).split()
US_STATES = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO "
    "MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()
)


def _aliases(city: str) -> set[str]:
    value = text(city).casefold()
    aliases = {value}
    if re.fullmatch(r"[\u4e00-\u9fff]+市?", value):
        aliases.update({value.removesuffix("市"), value.removesuffix("市") + "市"})
    # Keep the complete value as the actual filter (e.g. Fontana, CA).
    if "," in value:
        aliases.add(value.split(",", 1)[0].strip())
    return aliases


def resolve_city_constraints(
    request: SearchRequest, cities: Iterable[str]
) -> tuple[HardConstraints, tuple[str, ...]]:
    """Intersect explicit and textual city scopes; never broaden explicit filters.

    Positive lists are alternatives. Exclusions are cumulative. Contradictory
    positive scopes are rejected, since an empty cities tuple means unrestricted.
    Returns the effective constraints and the query spans used to derive them.
    """
    available = tuple(sorted(set(cities)))
    names: dict[str, set[str]] = defaultdict(set)
    for city in available:
        for alias in _aliases(city):
            names[alias].add(city)
    for city in (*request.hard_constraints.cities, *request.hard_constraints.excluded_cities):
        if text(city).casefold() not in names:
            for alias in _aliases(city):
                names[alias].add(city)
    for city in CHINESE_CITIES:
        if city not in names:
            names[city].add(city)
            names[city + "市"].add(city)

    query = text(request.query)
    # A full City, ST location remains restrictive even without matching jobs.
    for match in re.finditer(r"\b[A-Z][a-z]+(?: [A-Z][a-z]+){0,2}, [A-Z]{2}\b", query):
        city = match.group()
        # Avoid treating titles such as "Research Engineer, AI" as places.
        location_context = re.search(
            r"\b(?:in|location\s*:)\s*$|[—–]\s*$|(?:在|地点[:：]?)\s*$",
            query[: match.start()],
            re.I,
        )
        if city[-2:] in US_STATES and location_context and city.casefold() not in names:
            for alias in _aliases(city):
                names[alias].add(city)
    if not names:
        return request.hard_constraints, ()
    alternatives = "|".join(re.escape(s) for s in sorted(names, key=lambda s: (-len(s), s)))
    # ASCII boundaries allow Chinese sentences without allowing Reno inside Grenoble.
    pattern = re.compile(r"(?<![a-z])(?:" + alternatives + r")(?![a-z])", re.I)
    matches = list(pattern.finditer(query))
    included, excluded, spans = set(), set(), []
    previous_end, previous_intent = 0, None
    for position, match in enumerate(matches):
        prefix = query[previous_end : match.start()]
        suffix = query[match.end() :]
        group_end = match.end()
        for following in matches[position + 1 :]:
            if not CITY_CONNECTOR.fullmatch(query[group_end : following.start()]):
                break
            group_end = following.end()
        group_suffix = query[group_end:]
        # Bound intent to this clause rather than applying an earlier preference
        # or negation to all subsequent cities.
        clause = re.split(r"[，,;；。.!！?？]|\bbut\b|但是|但", prefix, flags=re.I)[-1]
        intent = None
        if re.search(r"不限|不限制|无所谓|anywhere|no (?:city|location) preference", clause, re.I):
            intent = "neutral"
        elif re.search(
            r"不要|不考虑|排除|不在|不去|避开|\b(?:not|exclude|excluding|outside|avoid)\b",
            clause,
            re.I,
        ):
            intent = "exclude"
        elif re.search(r"优先|最好|偏好|倾向|prefer(?:red|ably)?|ideally", clause, re.I):
            intent = "neutral"
        elif re.match(r"(?:市)?\s*(?:优先|最好|不限|也可以|preferred)", group_suffix, re.I):
            intent = "neutral"
        elif CITY_CONNECTOR.fullmatch(prefix):
            intent = previous_intent
        elif re.search(
            r"(?:在|位于|地点[:：]?|城市[:：]?|只看|只要|限于|找|搜索)\s*$|"
            r"\b(?:in|based in|located in|location\s*:)\s*$|[—–]\s*$",
            clause,
            re.I,
        ):
            intent = "include"
        elif not prefix.strip() or re.match(r"\s*(?:的)?(?:岗位|工作|职位)", suffix):
            intent = "include"
        elif "," in match.group() and re.match(r"\s*(?:\(Customer Site\))?\s*$", suffix, re.I):
            intent = "include"
        # Mentions of employers, universities or travel are not job locations.
        if re.match(r"\s*(?:大学|公司|客户|University|Inc\b|Ltd\b)", suffix, re.I) or re.search(
            r"出差|拜访|对接|曾在|住在|travel(?:ling)? to|customers? in|worked in|live in",
            clause,
            re.I,
        ):
            intent = "neutral"
        if intent in {"include", "exclude"}:
            targets = names[match.group().casefold()]
            (included if intent == "include" else excluded).update(targets)
            spans.append(match.group())
        previous_end, previous_intent = match.end(), intent

    def canonical(values: tuple[str, ...]) -> set[str]:
        result = set()
        for value in values:
            # Resolve spelling aliases to actual indexed values when possible.
            targets = names.get(text(value).casefold(), {value})
            result.update(set(targets).intersection(available) or targets)
        return result

    explicit = canonical(request.hard_constraints.cities)
    if explicit and included:
        included.intersection_update(explicit)
        if not included:
            raise ValueError("conflicting_city_constraints")
    else:
        included.update(explicit)
    excluded.update(canonical(request.hard_constraints.excluded_cities))
    if included and not included.difference(excluded):
        raise ValueError("conflicting_city_constraints")
    return request.hard_constraints.model_copy(
        update={
            "cities": tuple(sorted(included)),
            "excluded_cities": tuple(sorted(excluded)),
        }
    ), tuple(spans)
