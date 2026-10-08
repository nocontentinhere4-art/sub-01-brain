"""The image must contain every local module the server imports (the #49 incident: mind.py was missing and the image
crashed at start). Parses the Dockerfile's COPY lines and walks the imports with ast; no docker needed."""
import ast
import re
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY_POINTS = ("live_server.py", "browse_service.py")          # the CMD, and the browser child / separate service


def copied_paths(dockerfile=ROOT / "Dockerfile"):
    """Repo paths the Dockerfile copies from the build context (sources of COPY/ADD, not --from=stage copies)."""
    text = re.sub(r"\\\n", " ", dockerfile.read_text())          # join continued lines
    out = set()
    for line in text.splitlines():
        words = shlex.split(line.strip(), comments=True) if line.strip() else []
        if not words or words[0].upper() not in ("COPY", "ADD"):
            continue
        args = words[1:]
        if any(a.startswith("--from") for a in args):
            continue
        srcs = [a for a in args if not a.startswith("--")][:-1]  # last one is the destination
        out.update(Path(s).as_posix().rstrip("/") for s in srcs)
    return out


def _resolve(name, importer, level):
    """The repo file a (possibly relative) import refers to, or None for third-party / stdlib."""
    if level:
        base = (ROOT / importer).parent
        for _ in range(level - 1):
            base = base.parent
        parts = name.split(".") if name else []
    else:
        base, parts = ROOT, name.split(".")
    found = []
    for i in range(1, len(parts) + 1):
        p = base.joinpath(*parts[:i])
        if (p / "__init__.py").exists():
            found.append(p / "__init__.py")
        elif p.with_suffix(".py").exists():
            found.append(p.with_suffix(".py"))
            break
        else:
            break
    if level and not parts and (base / "__init__.py").exists():
        found.append(base / "__init__.py")
    return [f.relative_to(ROOT).as_posix() for f in found]


def local_imports(entry_points=ENTRY_POINTS):
    """Every repo .py file reachable from the entry points through import statements (any depth, any scope)."""
    seen, todo = set(), list(entry_points)
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        for node in ast.walk(ast.parse((ROOT / f).read_text(), f)):
            if isinstance(node, ast.Import):
                todo += [r for a in node.names for r in _resolve(a.name, f, 0)]
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                todo += _resolve(mod, f, node.level)
                for a in node.names:                              # `from pkg import submodule`
                    todo += _resolve(f"{mod}.{a.name}" if mod else a.name, f, node.level)
    return seen


def covered(path, copied):
    return any(path == c or path.startswith(c + "/") for c in copied)


def test_dockerfile_copies_every_imported_module():
    copied = copied_paths()
    missing = sorted(f for f in local_imports() if not covered(f, copied))
    assert not missing, f"Dockerfile does not COPY {missing} (imported by {', '.join(ENTRY_POINTS)})"


def test_dockerfile_copy_sources_exist():
    copied = copied_paths()
    assert "live_server.py" in copied and "entrypoint.sh" in copied
    assert not [c for c in copied if not (ROOT / c).exists()]


def test_catches_a_missing_module(tmp_path):
    """The #49 regression: the same Dockerfile without mind.py must fail the check."""
    df = tmp_path / "Dockerfile"
    df.write_text((ROOT / "Dockerfile").read_text().replace(" mind.py", ""))
    copied = copied_paths(df)
    assert "mind.py" not in copied
    assert "mind.py" in local_imports() and not covered("mind.py", copied)
