"""엑셀 일괄 등록 템플릿의 '안내(힌트) 행' 판별 — 템플릿 구조 기준.

템플릿은 1행 = 열 이름, 2행 = 열별 안내 문구로 만들어진다. 업로드 파일의 첫 데이터 행이
안내 행인지는 **특정 단어('필수' 등)가 들어 있는지로 판단하지 않는다.** 그렇게 하면
정상 데이터가 우연히 같은 단어를 포함할 때 조용히 빠진다.

대신 아래 조건을 모두 만족할 때만 안내 행으로 본다.
  1) 업로드 헤더 중 템플릿 열 이름과 일치하는 열이 MIN_MATCHED_COLUMNS 개 이상이다.
  2) 그 열들의 셀 값이 **템플릿이 써 넣은 안내 문구와 정확히 같다** (안내 문구가 빈 열은 빈 칸).
  3) 템플릿에 없는 열(사용자가 추가한 열)은 비어 있다.
템플릿 문구가 바뀌어도 예전에 내려받은 파일을 계속 인식하도록 버전별 안내 문구를 함께 둔다.
"""
from __future__ import annotations

MIN_MATCHED_COLUMNS = 3


def _norm(s) -> str:
    return str(s if s is not None else "").strip()


def is_template_hint_row(headers: list[str], row: list[str],
                         hint_versions: list[dict[str, str]]) -> bool:
    """row 가 hint_versions 중 하나의 안내 행과 구조적으로 일치하면 True."""
    for hints in hint_versions:
        matched_nonempty = 0
        ok = True
        for i, h in enumerate(headers):
            cell = _norm(row[i] if i < len(row) else "")
            key = _norm(h)
            if key in hints:
                if cell != _norm(hints[key]):
                    ok = False
                    break
                if cell:
                    matched_nonempty += 1
            elif cell:
                ok = False
                break
        if ok and matched_nonempty >= MIN_MATCHED_COLUMNS:
            return True
    return False


def strip_template_hint_row(headers: list[str], rows: list[list[str]],
                            hint_versions: list[dict[str, str]]) -> tuple[list[list[str]], bool]:
    """첫 데이터 행이 템플릿 안내 행이면 제거. (rows, removed) 반환."""
    if rows and is_template_hint_row(headers, rows[0], hint_versions):
        return rows[1:], True
    return rows, False
