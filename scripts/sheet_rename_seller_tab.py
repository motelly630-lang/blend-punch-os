"""시트 '셀러마스터' → '인플루언서마스터' 이름 정리.

이유: 이 탭은 OS `influencers` 테이블과 1:1이다. OS의 `sellers` 테이블은 사람이
아니라 판매링크 코드(`?seller=xxx`)라서 완전히 다른 것인데, 이름이 같아서
"인플루언서 탭도 따로 만들어야 하나?" 하는 혼동이 생겼다.

바꾸는 것: 탭 이름 · 1행 제목 · 4행 한글 라벨 · 데이터사전(시트명·라벨)
안 바꾸는 것: 영문 필드명(`seller_id`/`seller_name`/`seller_status`)
  → 공구일정의 FK와 코드값 ENUM 그룹명이 이 이름을 참조하므로 건드리면 파급이 크다.
    사장님이 보는 건 4행 한글 라벨이라 실사용엔 차이가 없다.

    .venv/bin/python scripts/sheet_rename_seller_tab.py [--dry-run] [--revert]

재실행 안전. --revert 로 되돌릴 수 있다.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.integrations import sheets_bridge as sb

OLD, NEW = "셀러마스터", "인플루언서마스터"
TITLE_OLD, TITLE_NEW = "셀러마스터 (sellers)", "인플루언서마스터 (influencers)"
# 4행 한글 라벨 교체 (영문 필드명은 그대로)
LABELS = {"셀러ID": "인플루언서ID", "셀러명": "인플루언서명", "셀러상태": "인플루언서상태"}

DICT_TAB = "데이터사전"


def main(dry_run: bool, revert: bool) -> int:
    if not sb.is_configured():
        print("!! 미설정 (.env)")
        return 1
    old, new = (NEW, OLD) if revert else (OLD, NEW)
    t_old, t_new = (TITLE_NEW, TITLE_OLD) if revert else (TITLE_OLD, TITLE_NEW)
    labels = {v: k for k, v in LABELS.items()} if revert else LABELS

    sh = sb._open()
    titles = [w.title for w in sh.worksheets()]
    if new in titles:
        print(f"이미 '{new}' 로 되어 있음 — 탭 이름 변경 건너뜀")
        ws = sh.worksheet(new)
    elif old in titles:
        print(f"탭 이름: '{old}' → '{new}'")
        ws = sh.worksheet(old)
        if not dry_run:
            ws.update_title(new)
    else:
        print(f"!! '{old}' / '{new}' 둘 다 없음")
        return 1

    # 1행 제목
    cur_title = ws.acell("A1").value or ""
    if cur_title.strip() == t_old:
        print(f"1행 제목: '{t_old}' → '{t_new}'")
        if not dry_run:
            ws.update([[t_new]], "A1", value_input_option="USER_ENTERED")
    else:
        print(f"1행 제목 그대로 ('{cur_title[:30]}')")

    # 4행 한글 라벨
    row4 = ws.row_values(sb.LABEL_ROW)
    changed = [(i, labels[v.strip()]) for i, v in enumerate(row4) if v.strip() in labels]
    if changed:
        print(f"4행 라벨 {len(changed)}개 교체: "
              + ", ".join(f"{row4[i]}→{v}" for i, v in changed))
        if not dry_run:
            new_row = list(row4)
            for i, v in changed:
                new_row[i] = v
            ws.update([new_row], f"A{sb.LABEL_ROW}", value_input_option="USER_ENTERED")
    else:
        print("4행 라벨 이미 정리됨")

    # 데이터사전: sheet_name + korean_label
    dic = sh.worksheet(DICT_TAB)
    rows = dic.get_all_values()
    updates = []
    for idx, r in enumerate(rows, start=1):
        if idx < sb.FIRST_DATA_ROW or not r:
            continue
        # 이 탭 소속 행만 건드린다. 공구일정에도 셀러ID/셀러명 필드가 있어서
        # 라벨을 무조건 바꾸면 사전과 그 탭 4행이 서로 안 맞게 된다.
        if (r[0] or "").strip() != old:
            continue
        updates.append({"range": f"'{DICT_TAB}'!A{idx}", "values": [[new]]})
        if len(r) > 3 and (r[3] or "").strip() in labels:
            updates.append({"range": f"'{DICT_TAB}'!D{idx}",
                            "values": [[labels[r[3].strip()]]]})
    if updates:
        print(f"데이터사전 {len(updates)}셀 수정")
        if not dry_run:
            sh.values_batch_update({"valueInputOption": "USER_ENTERED", "data": updates})
    else:
        print("데이터사전 이미 정리됨")

    print("\n" + ("[dry-run] 변경 없음" if dry_run else "완료."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--dry-run" in sys.argv, "--revert" in sys.argv))
