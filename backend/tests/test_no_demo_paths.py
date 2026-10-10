"""AT-14: the application package contains no demo/canned/scripted verification path.

Static checks over backend/app:
  - no demo/mock/fake/canned/scripted/sample-response identifiers;
  - verdict values are only *assigned* inside pipeline/verdicts.py (other modules only read/label them);
  - the provider registry has no offline/fallback provider;
  - test fixtures are not importable from the app package.
"""
import ast
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
SOURCES = {p: p.read_text(encoding="utf-8") for p in APP.rglob("*.py")}


def _identifiers(src: str) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.alias):
            names.add(node.asname or node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names


def test_no_demo_identifiers():
    rx = re.compile(r"(demo|mock|fake|canned|scripted|sample_(messages|responses)|offline)", re.I)
    hits = [(p.name, n) for p, s in SOURCES.items() for n in _identifiers(s) if rx.search(n)]
    assert hits == []


def test_verdicts_only_decided_by_rules():
    rx = re.compile(r"ClaimDecision\(\s*\"(verified|false|partly_true|misleading|outdated|conflicting)\"")
    offenders = [p.name for p, s in SOURCES.items() if rx.search(s) and p.name != "verdicts.py"]
    assert offenders == []
    # overall_verdict is only ever set from decide_overall()
    for p, s in SOURCES.items():
        for m in re.finditer(r"overall_verdict\s*=\s*([^\n]+)", s):
            assert "overall" in m.group(1) or "None" in m.group(1), (p.name, m.group(0))


def test_registry_has_no_substitute_provider():
    reg = SOURCES[APP / "providers" / "registry.py"]
    assert "GeminiProvider(" in reg and "TavilySearch(" in reg
    assert "except ProviderNotConfigured" in reg and reg.count("except ProviderNotConfigured") == 1  # only optional fact-check


def test_app_does_not_import_tests():
    assert not any("tests" in line for s in SOURCES.values() for line in s.splitlines() if line.startswith(("import", "from")))
