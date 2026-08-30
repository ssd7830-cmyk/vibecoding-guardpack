from loader import load_rows
from report import total_amount

EXPECTED = 46500  # 4,500원 + 12천원 + 3만원

actual = total_amount(load_rows("sales.txt"))
if actual != EXPECTED:
    raise SystemExit(
        f"TOTAL_FAIL: report.total_amount(load_rows('sales.txt')) returned {actual}, expected {EXPECTED}"
    )
print("TOTAL_OK")
