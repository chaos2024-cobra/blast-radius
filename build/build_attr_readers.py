#!/usr/bin/env python3
"""Build attribute-reader map: which functions read which class attribute NAMES.

For a class-body change like WEEK_OFFSET = -2 (535z) or NUMERIC_ESCAPES = {...} (4d63),
the behavior only changes where that name is READ. This map gives, per module, the
functions containing a Name/Attribute load of each attribute name:

  work/maps/attr_readers.json = {mod: {attr_name: [qualnames of reading functions]}}

Only UPPER_CASE and lowercase class attrs (assignments without self.) qualify; method
reads via self.X are captured by name too (dialect.WEEK_OFFSET, self.dialect... all
resolve to the NAME token).
"""
import ast
import json
from pathlib import Path

REPO = Path("/home/z/my-project/work/sqlglot/repo")
OUT = Path("/home/z/my-project/work/maps")


def parse(py):
    try:
        return ast.parse(py.read_text())
    except SyntaxError:
        return None


def module_of(py):
    return str(py.relative_to(REPO).with_suffix("")).replace("/", ".")


def main():
    result = {}
    for py in sorted(REPO.glob("sqlglot/**/*.py")):
        mod = module_of(py)
        tree = parse(py)
        if tree is None:
            continue
        readers = {}

        def visit_func(func_node, qualname):
            for node in ast.walk(func_node):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    name = node.id
                    if name.isupper() or "_" in name:
                        readers.setdefault(name, set()).add(qualname)
                elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                    readers.setdefault(node.attr, set()).add(qualname)

        def walk(node, class_stack):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    walk(child, class_stack + [child.name])
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    visit_func(child, ".".join(class_stack + [child.name]))
                    walk(child, class_stack)
                else:
                    walk(child, class_stack)

        walk(tree, [])
        result[mod] = {k: sorted(v) for k, v in readers.items()}

    (OUT / "attr_readers.json").write_text(json.dumps(result))
    n = sum(len(v) for v in result.values())
    print(f"modules: {len(result)}, attr names tracked: {n}")


if __name__ == "__main__":
    main()
