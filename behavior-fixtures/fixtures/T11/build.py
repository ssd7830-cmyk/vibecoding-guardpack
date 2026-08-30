import ast
from pathlib import Path


for source in sorted(Path(".").glob("*.py")):
    ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
print("BUILD_OK")
