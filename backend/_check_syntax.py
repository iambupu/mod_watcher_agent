# 中文注释：快速检查 Python 文件语法的本地维护脚本。

import ast
from pathlib import Path

root = Path(__file__).resolve().parent
pyfiles = list(root.rglob("*.py"))
errors = []

for path in pyfiles:
    try:
        with path.open(encoding="utf-8") as fh:
            ast.parse(fh.read())
    except SyntaxError as e:
        errors.append(f"{path}: {e}")

print(f"{len(pyfiles)} files checked, {len(errors)} errors")
for err in errors:
    print(f"  ERROR: {err}")
