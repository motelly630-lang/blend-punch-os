"""수수료율·할인율 입력 단위 규칙 — 모든 입력 경로의 단일 기준.

DB 저장 단위는 **비율(0~1)** 이다. 예: 12.5% → 0.125

입력 경로는 두 종류로 나뉜다.

1) 화면 입력 (`parse_percent_input`)
   입력칸 라벨에 "(%)" 가 붙어 있어 단위가 명시돼 있다. 숫자는 항상 퍼센트로 읽는다.
   "12.5" → 0.125, "0.5" → 0.005 (0.5%), "12.5%" → 0.125

2) 외부 입력 — 엑셀·CSV·통합시트 (`parse_external_rate`)
   작성자가 퍼센트로 적었는지 비율로 적었는지 알 수 없다.
   - "15%" 처럼 % 가 붙어 있으면 퍼센트                     → 0.15
   - 1 보다 크면 비율일 수 없으므로 퍼센트                  → "15" → 0.15
   - 0 은 0
   - 0 초과 1 이하(예: "1", "0.5", "0.15")는 1%/100% · 0.5%/50% 처럼
     **두 해석이 모두 가능**하므로 추측하지 않고 AmbiguousRate 를 던진다.
     호출측은 그 값을 저장하지 않고 사용자에게 "15%" 처럼 다시 적도록 안내한다.

   통합시트는 비율 셀이 퍼센트 서식이라 읽으면 "15.00%" 처럼 % 가 붙어 온다
   (sheets_export._same_cell 주석 참고). 그래서 시트 호환성은 유지된다.
"""
from __future__ import annotations

import math

MAX_PERCENT = 100.0


class RateError(ValueError):
    """비율 값이 잘못됨 (숫자 아님·범위 밖)."""


class AmbiguousRate(RateError):
    """퍼센트인지 비율인지 판단할 수 없는 외부 입력."""


def _clean(raw) -> tuple[str, bool]:
    s = str(raw).replace(",", "").replace("％", "%").strip()
    has_pct = s.endswith("%")
    return s.rstrip("%").strip(), has_pct


def _to_float(s: str, raw) -> float:
    try:
        v = float(s)
    except ValueError:
        raise RateError(f"숫자가 아닙니다: {raw!r}")
    if math.isnan(v) or math.isinf(v):
        raise RateError(f"숫자가 아닙니다: {raw!r}")
    return v


def _ratio(percent: float, raw) -> float:
    if percent < 0 or percent > MAX_PERCENT:
        raise RateError(f"0~100% 범위를 벗어났습니다: {raw!r}")
    # 부동소수점 잡음 제거 (12.5/100 → 0.125). 6자리면 0.0001% 단위까지 보존된다.
    return round(percent / 100.0, 6)


def parse_percent_input(raw) -> float | None:
    """화면 입력(단위 = %) → 비율. 빈 값은 None."""
    if raw is None:
        return None
    s, _ = _clean(raw)
    if s == "":
        return None
    return _ratio(_to_float(s, raw), raw)


def parse_external_rate(raw) -> float | None:
    """엑셀·시트 입력 → 비율. 빈 값은 None. 모호하면 AmbiguousRate."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        s, has_pct = str(raw), False
    else:
        s, has_pct = _clean(raw)
    if s == "" or s.lower() in ("none", "null", "-", "n/a", "#ref!", "#n/a"):
        return None
    v = _to_float(s, raw)
    if has_pct or v > 1:
        return _ratio(v, raw)
    if v == 0:
        return 0.0
    if v < 0:
        raise RateError(f"음수입니다: {raw!r}")
    raise AmbiguousRate(
        f"{raw!r} 은(는) {v:g}% 인지 {v * 100:g}% 인지 알 수 없습니다 — '{v * 100:g}%' 처럼 % 를 붙여 입력하세요"
    )


def ratio_to_percent_text(ratio) -> str:
    """비율 → 입력칸 표시용 퍼센트 문자열. 0.125 → '12.5', None → ''."""
    if ratio is None or ratio == "":
        return ""
    try:
        v = round(float(ratio) * 100, 4)
    except (TypeError, ValueError):
        return ""
    return f"{v:g}"
