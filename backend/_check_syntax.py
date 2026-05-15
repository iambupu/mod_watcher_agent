import ast
import glob
import os

root = r"D:\bupuy\Documents\mod_watcher_agent\backend"
pyfiles = glob.glob(os.path.join(root, "**", "*.py"), recursive=True)
errors = []

for f in pyfiles:
    try:
        with open(f, encoding="utf-8") as fh:
            ast.parse(fh.read())
    except SyntaxError as e:
        errors.append(f"{f}: {e}")

print(f"{len(pyfiles)} files checked, {len(errors)} errors")
for err in errors:
    print(f"  ERROR: {err}")
