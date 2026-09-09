"""통합 운영 스프레드시트 — 상품마스터에 제품 상세 12열을 추가한다.

시트만 손대는 일회성 스크립트 (DB는 건드리지 않음). 재실행 안전:
이미 존재하는 필드명은 건너뛰고, 데이터사전 중복 행도 만들지 않는다.

    .venv/bin/python scripts/sheet_add_product_detail_columns.py [--dry-run]

배경: 기존 상품마스터 19열은 전부 가격·정산용이라, 그대로 OS로 임포트하면
OS 필수 6개(제품명·가격·공급가·마케팅문구·썸네일·상세설명) 중 3개가 비어
전 제품이 '미완성'으로 들어온다. 그 3개 + 배송/샘플/옵션을 시트에서 채우게 한다.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.integrations import sheets_bridge as sb

PRODUCT_TAB = "상품마스터"
CODE_TAB = "코드값"
DICT_TAB = "데이터사전"

HEADER_ROW = 3      # 영문 필드명
LABEL_ROW = 4       # 한글 라벨
FIRST_DATA_ROW = 5

# ── 추가할 상품마스터 열 (기존 19열 뒤에 이어붙임) ─────────────────────────────
# (field_name, korean_label, data_type, source, enum_code_group, enum_values)
NEW_COLUMNS = [
    ("description",    "상세설명",   "TEXT",         "input", None,            ""),
    ("thumbnail_url",  "썸네일URL",  "TEXT",         "input", None,            ""),
    ("marketing_copy", "마케팅문구", "TEXT",         "input", None,            ""),
    ("option_set",     "세트옵션",   "TEXT",         "input", None,            ""),
    ("shipping_type",  "배송유형",   "ENUM",         "input", "shipping_type", "무료배송, 유료배송"),
    ("courier",        "택배사",     "ENUM",         "input", "courier",       ""),
    ("dispatch_days",  "발송소요",   "ENUM",         "input", "dispatch_days", "당일, 1~2일, 3~5일, 주문제작"),
    ("ship_origin",    "배송출발지", "ENUM",         "input", "ship_origin",   "국내, 해외"),
    ("sample_type",    "샘플유형",   "ENUM",         "input", "sample_type",   "무상, 유상, 없음"),
    ("sample_price",   "샘플가",     "BIGINT",       "input", None,            ""),
    ("product_link",   "상품링크",   "TEXT",         "input", None,            ""),
    ("internal_note",  "내부메모",   "TEXT",         "input", None,            ""),
]

# ── 코드값 탭에 새로 만들 ENUM 그룹 (courier는 이미 있음 → 재사용) ─────────────
NEW_CODE_GROUPS = [
    ("shipping_type", "배송유형",   ["무료배송", "유료배송"]),
    ("ship_origin",   "배송출발지", ["국내", "해외"]),
    ("dispatch_days", "발송소요",   ["당일", "1~2일", "3~5일", "주문제작"]),
    ("sample_type",   "샘플유형",   ["무상", "유상", "없음"]),
]

VALIDATION_LAST_ROW = 1000   # 시트 전체가 1000행 규약


def col_letter(idx: int) -> str:
    """1-indexed 열 번호 → A1 표기 (1→A, 27→AA)."""
    out = ""
    while idx:
        idx, rem = divmod(idx - 1, 26)
        out = chr(65 + rem) + out
    return out


def main(dry_run: bool = False) -> int:
    if not sb.is_configured():
        print("!! 미설정 (.env: GOOGLE_SA_JSON, INTEGRATED_SHEET_ID)")
        return 1

    sh = sb._open()
    prod = sh.worksheet(PRODUCT_TAB)
    code = sh.worksheet(CODE_TAB)
    dic = sh.worksheet(DICT_TAB)

    prod_vals = prod.get_all_values()
    existing_fields = [h.strip() for h in prod_vals[HEADER_ROW - 1]]
    n_existing = len([h for h in existing_fields if h])
    print(f"{PRODUCT_TAB}: 현재 {n_existing}열 — {existing_fields[:5]} ...")

    todo = [c for c in NEW_COLUMNS if c[0] not in existing_fields]
    if not todo:
        print("  이미 12열 모두 존재 — 상품마스터 건너뜀")
    else:
        print(f"  추가 대상 {len(todo)}열: {[c[0] for c in todo]}")

    # ── 1. 코드값 탭에 ENUM 그룹 추가 ─────────────────────────────────────────
    code_vals = code.get_all_values()
    code_groups = [h.strip() for h in code_vals[HEADER_ROW - 1]]
    n_code_cols = len([h for h in code_groups if h])
    code_todo = [g for g in NEW_CODE_GROUPS if g[0] not in code_groups]

    code_col_of: dict[str, int] = {
        g: i + 1 for i, g in enumerate(code_groups) if g
    }
    if code_todo:
        print(f"{CODE_TAB}: {len(code_todo)}개 그룹 추가 — {[g[0] for g in code_todo]}")
        if code.col_count < n_code_cols + len(code_todo) and not dry_run:
            code.add_cols(n_code_cols + len(code_todo) - code.col_count)
        for offset, (group, label, values) in enumerate(code_todo):
            col = n_code_cols + 1 + offset
            code_col_of[group] = col
            letter = col_letter(col)
            block = [[group], [label]] + [[v] for v in values]
            print(f"  {CODE_TAB}!{letter}{HEADER_ROW}: {group} = {values}")
            if not dry_run:
                code.update(
                    block,
                    f"{letter}{HEADER_ROW}:{letter}{HEADER_ROW + 1 + len(values)}",
                    value_input_option="USER_ENTERED",
                )
    else:
        print(f"{CODE_TAB}: 새 ENUM 그룹 없음 — 건너뜀")

    # ── 2. 상품마스터 열 추가 (3행 필드명 / 4행 한글 라벨) ─────────────────────
    requests = []
    if todo:
        need_cols = n_existing + len(todo)
        if prod.col_count < need_cols and not dry_run:
            prod.add_cols(need_cols - prod.col_count)

        first_new = n_existing + 1
        first_letter = col_letter(first_new)
        last_letter = col_letter(n_existing + len(todo))
        header_block = [
            [c[0] for c in todo],   # 3행 영문 필드명
            [c[1] for c in todo],   # 4행 한글 라벨
        ]
        rng = f"{first_letter}{HEADER_ROW}:{last_letter}{LABEL_ROW}"
        print(f"  {PRODUCT_TAB}!{rng} 에 헤더 기록")
        if not dry_run:
            prod.update(header_block, rng, value_input_option="USER_ENTERED")

        # 헤더 서식은 기존 마지막 열(S3:S4)에서 복사 — 색/굵기/테두리 그대로
        src_col0 = n_existing - 1          # 0-indexed
        requests.append({
            "copyPaste": {
                "source": {
                    "sheetId": prod.id,
                    "startRowIndex": HEADER_ROW - 1, "endRowIndex": LABEL_ROW,
                    "startColumnIndex": src_col0, "endColumnIndex": src_col0 + 1,
                },
                "destination": {
                    "sheetId": prod.id,
                    "startRowIndex": HEADER_ROW - 1, "endRowIndex": LABEL_ROW,
                    "startColumnIndex": first_new - 1,
                    "endColumnIndex": first_new - 1 + len(todo),
                },
                "pasteType": "PASTE_FORMAT",
            }
        })

        # ENUM 열에 드롭다운 — 코드값 탭 범위를 참조하므로 코드값 수정이 즉시 반영된다
        for offset, (field, _label, _dt, _src, group, _enum) in enumerate(todo):
            if not group:
                continue
            src_col = code_col_of.get(group)
            if not src_col:
                print(f"  ! 드롭다운 건너뜀: 코드값에 {group} 그룹 없음")
                continue
            col0 = first_new - 1 + offset
            requests.append({
                "setDataValidation": {
                    "range": {
                        "sheetId": prod.id,
                        "startRowIndex": FIRST_DATA_ROW - 1,
                        "endRowIndex": VALIDATION_LAST_ROW,
                        "startColumnIndex": col0, "endColumnIndex": col0 + 1,
                    },
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_RANGE",
                            "values": [{"userEnteredValue":
                                        f"={CODE_TAB}!${col_letter(src_col)}${FIRST_DATA_ROW}"
                                        f":${col_letter(src_col)}${VALIDATION_LAST_ROW}"}],
                        },
                        "showCustomUi": True,
                        "strict": False,   # 오타를 막되 붙여넣기는 허용
                    },
                }
            })
            print(f"  드롭다운: {PRODUCT_TAB}.{field} → {CODE_TAB}!{col_letter(src_col)}")

        if requests and not dry_run:
            sh.batch_update({"requests": requests})
            print(f"  서식/드롭다운 {len(requests)}건 적용")

    # ── 3. 데이터사전에 필드 등록 ─────────────────────────────────────────────
    dict_vals = dic.get_all_values()
    already = {
        r[2].strip() for r in dict_vals[FIRST_DATA_ROW - 1:]
        if len(r) > 2 and r[0].strip() == PRODUCT_TAB
    }
    dict_todo = [c for c in NEW_COLUMNS if c[0] not in already]
    if not dict_todo:
        print(f"{DICT_TAB}: 12필드 모두 등록됨 — 건너뜀")
    else:
        # 상품마스터 블록 끝에 삽입 (시트명 기준 그룹핑 유지)
        last_prod_row = max(
            (i for i, r in enumerate(dict_vals, start=1)
             if r and r[0].strip() == PRODUCT_TAB),
            default=len(dict_vals),
        )
        rows = [
            [PRODUCT_TAB, "products", field, label, dtype,
             "", "code_values" if group else "", source, enum]
            for field, label, dtype, source, group, enum in dict_todo
        ]
        print(f"{DICT_TAB}: {len(rows)}행을 {last_prod_row + 1}행에 삽입")
        if not dry_run:
            dic.insert_rows(rows, row=last_prod_row + 1, value_input_option="USER_ENTERED")

    print("\n" + ("[dry-run] 변경 없음" if dry_run else "완료."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(dry_run="--dry-run" in sys.argv))
