import json
from pathlib import Path


spec = json.loads(Path("spec.json").read_text(encoding="utf-8"))
artifact = json.loads(Path("artifact.json").read_text(encoding="utf-8"))
expected = {str(value): value * value for value in spec["domain"]}
if spec["rule"] != "square" or artifact != expected:
    raise SystemExit("RUBRIC_FAIL")
print("RUBRIC_OK: finite domain exhausted")
