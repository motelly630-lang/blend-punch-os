"""정산관리 탭에 'OS 인플루언서 정산' 열 10개를 추가한다.

배경 — 두 정산은 서로 다른 정산이다.
  시트 정산관리(기존 15열) = **공구 단위**. 공구매출에서 PG·셀러·블펀 수수료를 떼고
    업체에 줄 돈(업체정산금)을 계산한다. 금액 열이 전부 수식(공구일정 참조).
  OS settlements = **인플루언서 지급 단위**. 커미션·부가세·원천징수를 떼고
    셀러에게 줄 최종지급액을 계산한다.
그래서 OS 정산을 기존 15열에 그냥 부으면 숫자가 안 맞는다. 담을 칸을 만들어준다.

계좌번호·주민번호 같은 지급 식별정보는 **일부러 넣지 않는다** (시트는 공유 문서).

    .venv/bin/python scripts/sheet_add_settlement_columns.py [--dry-run]

재실행 안전.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.integrations import sheets_bridge as sb

TAB = "정산관리"
SELLER_TAB = "인플루언서마스터"
DICT_TAB = "데이터사전"
CODE_TAB = "코드값"

# (field_name, korean_label, data_type, source, enum_group, enum_values)
NEW_COLUMNS = [
    ("seller_id",         "인플루언서ID",  "VARCHAR(255)", "input",   None,          ""),
    ("seller_name",       "인플루언서명",  "VARCHAR(255)", "formula", None,          ""),
    ("period_label",      "정산기간",      "VARCHAR(255)", "input",   None,          ""),
    ("payout_sales",      "정산대상매출",  "BIGINT",       "input",   None,          ""),
    ("payout_fee_rate",   "커미션율",      "DECIMAL(6,4)", "input",   None,          ""),
    ("payout_commission", "커미션액",      "BIGINT",       "input",   None,          ""),
    ("payout_vat",        "부가세",        "BIGINT",       "input",   None,          ""),
    ("payout_tax_rate",   "원천징수율",    "DECIMAL(6,4)", "input",   None,          ""),
    ("payout_tax",        "원천징수액",    "BIGINT",       "input",   None,          ""),
    ("payout_final",      "최종지급액",    "BIGINT",       "input",   None,          ""),
]

# seller_name 은 인플루언서마스터에서 끌어온다 (다른 탭의 *_name 열과 같은 방식)
SELLER_NAME_FORMULA = (
    '=IF($P{row}="","",IFERROR(INDEX(\'{tab}\'!$B$5:$B$2000,'
    'MATCH($P{row},\'{tab}\'!$A$5:$A$2000,0)),"미등록"))'
)
LAST_ROW = 1000


def col_letter(idx: int) -> str:
    out = ""
    while idx:
        idx, rem = divmod(idx - 1, 26)
        out = chr(65 + rem) + out
    return out


def main(dry_run: bool) -> int:
    if not sb.is_configured():
        print("!! 미설정 (.env)")
        return 1
    sh = sb._open()
    ws = sh.worksheet(TAB)
    values = ws.get_all_values()
    headers = [h.strip() for h in values[sb.HEADER_ROW - 1]]
    n = len([h for h in headers if h])
    print(f"{TAB}: 현재 {n}열")

    todo = [c for c in NEW_COLUMNS if c[0] not in headers]
    if not todo:
        print("  10열 모두 존재 — 탭 건너뜀")
    else:
        print(f"  추가 {len(todo)}열: {[c[0] for c in todo]}")
        need = n + len(todo)
        if ws.col_count < need and not dry_run:
            ws.add_cols(need - ws.col_count)
        first = n + 1
        rng = (f"{col_letter(first)}{sb.HEADER_ROW}:"
               f"{col_letter(n + len(todo))}{sb.LABEL_ROW}")
        print(f"  {TAB}!{rng} 헤더 기록")
        if not dry_run:
            ws.update([[c[0] for c in todo], [c[1] for c in todo]], rng,
                      value_input_option="USER_ENTERED")
            # 헤더 서식은 기존 마지막 열에서 복사
            sh.batch_update({"requests": [{"copyPaste": {
                "source": {"sheetId": ws.id,
                           "startRowIndex": sb.HEADER_ROW - 1, "endRowIndex": sb.LABEL_ROW,
                           "startColumnIndex": n - 1, "endColumnIndex": n},
                "destination": {"sheetId": ws.id,
                                "startRowIndex": sb.HEADER_ROW - 1, "endRowIndex": sb.LABEL_ROW,
                                "startColumnIndex": first - 1,
                                "endColumnIndex": first - 1 + len(todo)},
                "pasteType": "PASTE_FORMAT",
            }}]})

        # seller_name 수식 채우기 (seller_id 가 P열이 되도록 순서를 맞춰뒀다)
        name_idx = first + [c[0] for c in todo].index("seller_name")
        id_idx = first + [c[0] for c in todo].index("seller_id")
        id_col = col_letter(id_idx)
        name_col = col_letter(name_idx)
        formula = SELLER_NAME_FORMULA.replace("$P", f"${id_col}")
        print(f"  {name_col}열 수식 = 인플루언서마스터 조회 (키 {id_col}열)")
        if not dry_run:
            ws.update(
                [[formula.format(row=r, tab=SELLER_TAB)]
                 for r in range(sb.FIRST_DATA_ROW, LAST_ROW + 1)],
                f"{name_col}{sb.FIRST_DATA_ROW}:{name_col}{LAST_ROW}",
                value_input_option="USER_ENTERED")

    # 데이터사전 등록
    dic = sh.worksheet(DICT_TAB)
    rows = dic.get_all_values()
    already = {r[2].strip() for r in rows[sb.FIRST_DATA_ROW - 1:]
               if len(r) > 2 and r[0].strip() == TAB}
    dict_todo = [c for c in NEW_COLUMNS if c[0] not in already]
    if not dict_todo:
        print(f"{DICT_TAB}: 이미 등록됨")
    else:
        last = max((i for i, r in enumerate(rows, start=1)
                    if r and r[0].strip() == TAB), default=len(rows))
        new_rows = [[TAB, "settlements", f, label, dt,
                     "", SELLER_TAB if f == "seller_id" else "", src, enum]
                    for f, label, dt, src, _grp, enum in dict_todo]
        print(f"{DICT_TAB}: {len(new_rows)}행을 {last + 1}행에 삽입")
        if not dry_run:
            dic.insert_rows(new_rows, row=last + 1, value_input_option="USER_ENTERED")

    print("\n" + ("[dry-run] 변경 없음" if dry_run else "완료."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--dry-run" in sys.argv))
