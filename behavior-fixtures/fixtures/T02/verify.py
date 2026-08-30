from pathlib import Path


actual = Path("message.txt").read_text(encoding="utf-8")
expected = "환영합니다.\n"
if actual != expected:
    raise SystemExit(f"VERIFY_FAIL: {actual!r}")
print("VERIFY_OK")
