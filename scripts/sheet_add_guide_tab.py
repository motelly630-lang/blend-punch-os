"""통합 운영시트 맨 앞에 '사용법' 탭을 만든다.

사장님이 시트만 열어도 쓰는 법을 알 수 있게 하는 안내 탭. 데이터 탭이 아니므로
데이터사전에는 등록하지 않고, sheets_bridge/import/export 도 이 탭을 건드리지 않는다.

'다음 번호' 항목은 고정값이 아니라 **수식**이다. 각 마스터 탭의 ID에서 뒤 4자리를
읽어 최대값+1 을 보여주므로, 시트가 늘어나도 안내가 낡지 않는다.

    .venv/bin/python scripts/sheet_add_guide_tab.py [--dry-run]

재실행 안전 (이미 있으면 내용을 새로 씀).
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.integrations import sheets_bridge as sb

TAB = "사용법"
WIDTHS = [110, 210, 640, 120]      # A~D

# 각 마스터 탭의 '다음 발급 번호'를 스스로 계산하는 수식
NEXT_ID = ('=ARRAYFORMULA("{prefix}-2026-"&TEXT(MAX(IFERROR(VALUE('
           "RIGHT('{tab}'!$A$5:$A$2000,4)),0))+1,\"0000\"))")


def _next(prefix: str, tab: str) -> str:
    return NEXT_ID.format(prefix=prefix, tab=tab)


# (종류, A, B, C, D)
#   title / sub / section / head(표 머리) / row / warn / blank
CONTENT: list[tuple] = [
    ("title", "BLEND PUNCH 통합 운영시트 — 사용법", "", "", ""),
    ("sub", "이 시트에 적으면 OS(os.blendpunch.com)에 들어가고, OS에서 진행된 공구·정산은 이 시트로 내려옵니다.", "", "", ""),
    ("blank",),

    ("section", "1. 어디서 누르나", "", "", ""),
    ("row", "들어가는 곳", "os.blendpunch.com", "로그인 → 왼쪽 아래 ⚙️설정 → 통합시트 연동", ""),
    ("row", "버튼 ①", "미리보기 → 이대로 반영", "시트 → OS. 시트에 적은 브랜드·업체·상품·인플루언서를 OS로 보냅니다.", "시트→OS"),
    ("row", "버튼 ②", "내려받기 미리보기 → 시트에 기록", "OS → 시트. OS에서 진행된 공구·정산을 시트로 가져옵니다.", "OS→시트"),
    ("warn", "먼저 미리보기", "아무것도 바뀌지 않습니다", "미리보기는 몇 건이 새로 생기고 어떤 값이 어떻게 바뀌는지만 보여줍니다. 확인하고 나서 반영 버튼을 누르세요.", ""),
    ("blank",),

    ("section", "2. 어느 탭을 내가 적고, 어느 탭이 자동인가", "", "", ""),
    ("head", "탭", "방향", "내가 할 일", "구분"),
    ("row", "브랜드마스터", "시트 → OS", "브랜드명·설명·로고주소를 적습니다", "내가 적음"),
    ("row", "업체마스터", "시트 → OS", "협력사(공급사) 정보를 적습니다", "내가 적음"),
    ("row", "상품마스터", "시트 → OS", "제품과 가격·상세를 적습니다 (아래 4번 참고)", "내가 적음"),
    ("row", "인플루언서마스터", "시트 → OS", "셀러(인플루언서) 정보를 적습니다", "내가 적음"),
    ("row", "공구일정", "OS → 시트", "적지 마세요. OS에서 공구가 진행되면 버튼②로 내려받습니다.", "내려받기 전용"),
    ("row", "정산관리", "OS → 시트", "적지 마세요. P~Y열은 OS 인플루언서 지급정산이 내려옵니다.", "내려받기 전용"),
    ("row", "대시보드 · 성과관리", "자동", "공구일정에서 수식으로 자동 계산됩니다", "자동"),
    ("row", "샘플일정 · 콘텐츠일정", "미사용", "아직 OS에 연결되지 않았습니다 (준비 중)", "준비 중"),
    ("row", "CS관리", "미사용", "CS는 이 탭 대신 OS의 CS 메뉴를 쓰세요", "OS에서"),
    ("row", "코드값 · 데이터사전 · 입력값", "설정", "드롭다운 목록과 항목 정의표입니다. 건드리지 마세요.", "건드리지 마세요"),
    ("blank",),

    ("section", "3. 새 제품 넣는 순서", "", "", ""),
    ("row", "1단계", "브랜드마스터", "그 브랜드가 있는지 확인. 없으면 먼저 한 줄 추가 (로고 주소까지)", ""),
    ("row", "2단계", "업체마스터", "그 업체가 있는지 확인. 없으면 먼저 한 줄 추가", ""),
    ("row", "3단계", "상품마스터", "맨 아래 빈 줄에 제품을 적습니다", ""),
    ("row", "4단계", "OS에서 버튼 ①", "미리보기로 확인 → 이대로 반영", ""),
    ("blank",),

    ("section", "4. 상품마스터 — 어느 칸에 뭘 적나", "", "", ""),
    ("head", "칸", "항목", "적는 법", "구분"),
    ("row", "A", "상품ID", "PRD-2026-#### 형식. 다음 번호는 아래 7번에 나옵니다. 비우지 마세요.", "필수"),
    ("row", "B", "상품명", "", "필수"),
    ("row", "C", "브랜드", "브랜드마스터 B열과 글자가 똑같아야 같은 브랜드로 묶입니다", "필수"),
    ("row", "D", "카테고리", "예: 식품/음료, 생활/주방", "필수"),
    ("row", "E", "업체ID", "업체마스터 A열의 VND-… 코드", "필수"),
    ("row", "F", "업체명", "업체ID를 넣으면 저절로 채워집니다", "⛔ 자동"),
    ("row", "G · H · I", "공급가 · 정상가 · 판매가", "숫자만 (쉼표 없이 12000)", "필수"),
    ("row", "J", "배송비", "무료면 0", ""),
    ("row", "K", "PG수수료율", "OS에 대응 칸이 없어 시트에만 남습니다", "시트에만"),
    ("row", "L · M", "셀러수수료율 · 블펀수수료율", "15% 처럼 적으세요", "필수"),
    ("row", "N · O · P · Q", "업체정산율 · 업체정산금 · 블펀수수료금액 · 검증", "위 수수료율을 넣으면 저절로 계산됩니다", "⛔ 자동"),
    ("row", "R", "담당자", "OS에 대응 칸이 없어 시트에만 남습니다", "시트에만"),
    ("row", "S", "상품상태", "드롭다운에서 고르세요", "필수"),
    ("row", "T", "상세설명", "제품 상세 문구", "권장"),
    ("row", "U", "썸네일URL", "http로 시작하는 이미지 주소. 비우면 OS에서 '미완성'으로 뜹니다.", "권장"),
    ("row", "V", "마케팅문구", "한 줄 카피", "권장"),
    ("row", "W", "세트옵션", "1박스(30팩):18000; 2박스(60팩):34000 — 옵션 사이는 세미콜론(;)", ""),
    ("row", "X ~ AB", "배송유형 · 택배사 · 발송소요 · 배송출발지 · 샘플유형", "드롭다운에서 고르세요", ""),
    ("row", "AC · AD · AE", "샘플가 · 상품링크 · 내부메모", "", ""),
    ("blank",),

    ("section", "5. 이 세 가지만 지켜주세요", "", "", ""),
    ("warn", "①", "ID 칸(A열)을 비우지 마세요", "비워도 제품은 들어가지만, 나중에 내려받기할 때 같은 제품이 시트에 한 줄 더 생깁니다. 비운 채로 미리보기하면 경고가 뜹니다.", ""),
    ("warn", "②", "이미지는 셀에 붙여넣지 마세요", "셀에 삽입한 그림이나 =IMAGE() 는 읽어올 수 없습니다. http로 시작하는 주소를 글자로 넣어야 OS가 받아서 저장합니다.", ""),
    ("warn", "③", "자동 계산 칸을 손으로 덮지 마세요", "상품마스터 F·N·O·P·Q, 공구일정·정산관리의 회색 칸들. 손으로 쓰면 계산식이 지워집니다.", ""),
    ("blank",),

    ("section", "6. 안심하셔도 되는 것", "", "", ""),
    ("row", "빈 칸", "지우라는 뜻이 아닙니다", "시트에서 비워둔 칸은 OS 값을 지우지 않습니다. OS에서 채운 내용이 날아가지 않습니다.", ""),
    ("row", "중복", "생기지 않습니다", "같은 시트를 여러 번 올려도 ID로 기존 행을 찾아 덮어씁니다.", ""),
    ("row", "실패", "전체를 되돌립니다", "중간에 문제가 생기면 절반만 들어가는 일 없이 전부 취소됩니다.", ""),
    ("row", "브랜드 없는 제품", "자동으로 만듭니다", "상품마스터 C열 이름이 브랜드마스터에 없으면 그 이름으로 브랜드를 새로 만듭니다. 다만 로고·설명은 비어 있으니 브랜드마스터에 먼저 적는 편이 좋습니다.", ""),
    ("blank",),

    ("section", "7. 다음에 쓸 ID (자동 계산)", "", "", ""),
    ("head", "탭", "다음 번호", "", ""),
    ("row", "상품마스터", _next("PRD", "상품마스터"), "A열에 이 번호를 적고 시작하세요", ""),
    ("row", "브랜드마스터", _next("BRD", "브랜드마스터"), "", ""),
    ("row", "업체마스터", _next("VND", "업체마스터"), "", ""),
    ("row", "인플루언서마스터", _next("SEL", "인플루언서마스터"), "", ""),
]

# ── 색 ────────────────────────────────────────────────────────────────────────
NAVY = {"red": 0.10, "green": 0.14, "blue": 0.20}
SECTION_BG = {"red": 0.93, "green": 0.95, "blue": 0.98}
HEAD_BG = {"red": 0.96, "green": 0.96, "blue": 0.96}
WARN_BG = {"red": 1.0, "green": 0.97, "blue": 0.90}
WHITE = {"red": 1, "green": 1, "blue": 1}
GRAY = {"red": 0.45, "green": 0.45, "blue": 0.45}


def _fmt(row0: int, n_cols: int, sheet_id: int, **cell):
    return {"repeatCell": {
        "range": {"sheetId": sheet_id, "startRowIndex": row0, "endRowIndex": row0 + 1,
                  "startColumnIndex": 0, "endColumnIndex": n_cols},
        "cell": {"userEnteredFormat": cell},
        "fields": "userEnteredFormat(" + ",".join(cell) + ")",
    }}


def main(dry_run: bool) -> int:
    if not sb.is_configured():
        print("!! 미설정 (.env)")
        return 1
    sh = sb._open()
    titles = [w.title for w in sh.worksheets()]

    n_rows = len(CONTENT) + 4
    if TAB in titles:
        print(f"'{TAB}' 탭 이미 있음 — 내용을 새로 씁니다")
        ws = sh.worksheet(TAB)
        if not dry_run:
            ws.clear()
            if ws.row_count < n_rows:
                ws.add_rows(n_rows - ws.row_count)
    else:
        print(f"'{TAB}' 탭 신설 (맨 앞)")
        if dry_run:
            print(f"[dry-run] {len(CONTENT)}행 · 폭 {WIDTHS} · 서식 적용 예정")
            return 0
        ws = sh.add_worksheet(title=TAB, rows=n_rows, cols=4, index=0)

    values, requests = [], []
    for i, item in enumerate(CONTENT):
        kind = item[0]
        cells = list(item[1:5]) if len(item) > 1 else ["", "", "", ""]
        cells = (cells + ["", "", "", ""])[:4]
        values.append(cells)
        if kind == "title":
            requests.append(_fmt(i, 4, ws.id,
                                 backgroundColor=NAVY,
                                 textFormat={"bold": True, "fontSize": 15,
                                             "foregroundColor": WHITE}))
        elif kind == "sub":
            requests.append(_fmt(i, 4, ws.id,
                                 textFormat={"fontSize": 10, "foregroundColor": GRAY}))
        elif kind == "section":
            requests.append(_fmt(i, 4, ws.id, backgroundColor=SECTION_BG,
                                 textFormat={"bold": True, "fontSize": 12}))
        elif kind == "head":
            requests.append(_fmt(i, 4, ws.id, backgroundColor=HEAD_BG,
                                 textFormat={"bold": True, "fontSize": 10}))
        elif kind == "warn":
            requests.append(_fmt(i, 4, ws.id, backgroundColor=WARN_BG))

    print(f"  {len(values)}행 기록 + 서식 {len(requests)}건")
    ws.update(values, f"A1:D{len(values)}", value_input_option="USER_ENTERED")

    # 열 폭 · 줄바꿈 · 세로 정렬 · 첫 행 고정
    for idx, w in enumerate(WIDTHS):
        requests.append({"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                      "startIndex": idx, "endIndex": idx + 1},
            "properties": {"pixelSize": w}, "fields": "pixelSize"}})
    requests.append({"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": len(values),
                  "startColumnIndex": 0, "endColumnIndex": 4},
        "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP",
                                       "verticalAlignment": "TOP"}},
        "fields": "userEnteredFormat(wrapStrategy,verticalAlignment)"}})
    requests.append({"updateSheetProperties": {
        "properties": {"sheetId": ws.id,
                       "gridProperties": {"frozenRowCount": 2}},
        "fields": "gridProperties.frozenRowCount"}})
    # 탭 위치를 맨 앞으로 (기존 탭을 새로 쓴 경우에도)
    requests.append({"updateSheetProperties": {
        "properties": {"sheetId": ws.id, "index": 0}, "fields": "index"}})

    sh.batch_update({"requests": requests})
    print("완료.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--dry-run" in sys.argv))
