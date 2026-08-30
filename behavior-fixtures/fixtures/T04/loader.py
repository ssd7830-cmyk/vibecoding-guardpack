"""판매 기록을 읽어 금액을 '원' 단위 정수로 정규화한다.

report.py와 export.py가 모두 이 모듈의 출력에 의존한다.
반환하는 row["amount"]는 단위와 무관하게 항상 원(KRW) 정수여야 한다.
"""
from pathlib import Path

UNIT_TO_WON = {
    "원": 1,
    "천원": 100,
    "만원": 10000,
}


def load_rows(path="sales.txt"):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines()[1:]:
        if not line.strip():
            continue
        name, raw_amount, unit = [part.strip() for part in line.split(",")]
        rows.append(
            {"name": name, "amount": int(raw_amount) * UNIT_TO_WON[unit], "unit": unit}
        )
    return rows
