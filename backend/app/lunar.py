"""农历换算封装（lunardate，支持 1900-2100）。

用途：纪念日存公历日期；生日场景下要"每年同时在公历与农历对应日标标签"：
  solar_to_lunar_md(date_str)        -> (农历月, 农历日) 由出生公历日反推农历生日
  occurrences_in_year(date_str, y)   -> 该公历年内的标注日列表
      [{date:'YYYY-MM-DD', kind:'solar'|'lunar'}]
"""
from __future__ import annotations

from lunardate import LunarDate

MONTHS = "正二三四五六七八九十冬腊"
DAYS = ("初一初二初三初四初五初六初七初八初九初十"
        "十一十二十三十四十五十六十七十八十九二十"
        "廿一廿二廿三廿四廿五廿六廿七廿八廿九三十")


def _split(date_str: str) -> tuple[int, int, int]:
    y, m, d = date_str.split("-")
    return int(y), int(m), int(d)


def _from_solar(y, m, d) -> LunarDate:
    f = getattr(LunarDate, "from_solar_date", None) or getattr(LunarDate, "fromSolarDate")
    return f(y, m, d)


def _to_solar(ld: LunarDate):
    f = getattr(ld, "to_solar_date", None) or getattr(ld, "toSolarDate")
    return f()


def solar_to_lunar_md(date_str: str) -> tuple[int, int]:
    y, m, d = _split(date_str)
    ld = _from_solar(y, m, d)
    return ld.month, ld.day


def lunar_text(month: int, day: int) -> str:
    if not (1 <= month <= 12 and 1 <= day <= 30):
        return ""
    # DAYS 是两字一组的拼接串，按 (day-1)*2 切片取两个字
    return f"{MONTHS[month - 1]}月{DAYS[(day - 1) * 2: day * 2]}"


def lunar_text_of(date_str: str) -> str:
    m, d = solar_to_lunar_md(date_str)
    return lunar_text(m, d)


def occurrences_in_year(date_str: str, year: int) -> list[dict]:
    """返回该公历年内应标注的日期（公历固定日 + 农历对应日，去重）。"""
    _, sm, sd = _split(date_str)
    out: dict[str, str] = {f"{year:04d}-{sm:02d}-{sd:02d}": "solar"}
    lm, ld = solar_to_lunar_md(date_str)
    seen = set()
    for ly in range(year - 1, year + 2):
        try:
            d = _to_solar(LunarDate(ly, lm, ld))
        except (ValueError, OverflowError):
            continue
        if d.year == year:
            key = f"{d.year:04d}-{d.month:02d}-{d.day:02d}"
            if key not in seen:
                seen.add(key)
                out[key] = "lunar"
    return [{"date": k, "kind": v} for k, v in sorted(out.items())]
