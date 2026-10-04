"""Guards the numbers the documentation quotes against the code that defines them.

README claims drift silently: this repo advertised 20 DRC rules while `drc.py`
shipped 26, 23 NL parameters while `nl_adjust.py` accepted 28, and a 212-test
badge while the suite ran 222. None of that breaks a build, so nothing caught it.

Every assertion here re-derives the number from the source of truth and compares
it to the literal in the docs. When you add a rule, a parameter or a test, these
fail until the docs are updated — which is the entire point.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Docs that quote feature counts. All of them must stay consistent.
COUNT_DOCS = ["README.md", "README.en.md", "llms.txt"]

# How each material preset is named in prose — one or more accepted aliases,
# since the Chinese and English docs phrase them differently. Keep the keys in
# lockstep with `materials.MATERIALS`; the test asserts that, so adding a preset
# without documenting it fails the build.
PRESET_PROSE = {
    "durostone": ("Durostone",),
    "ricocel": ("Ricocel",),
    "fr4_high_tg": ("FR-4",),
    "aluminum": ("铝", "aluminum"),
}


def _read(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Sources of truth, derived from the code — never hard-coded
# --------------------------------------------------------------------------- #


def drc_rule_codes() -> set[str]:
    """Every distinct rule code emitted by `run_drc`."""
    return set(re.findall(r'_issue\(\s*\n?\s*"([A-Z][A-Z0-9_]+)"', _read("drc.py")))


def nl_param_names() -> set[str]:
    """Every canonical parameter the NL adjuster understands."""
    src = _read("nl_adjust.py")
    seg = src[src.index("PARAM_ALIASES") : src.index("def parse_adjust_command")]
    return set(re.findall(r'"([a-z_0-9]+)"\s*:', seg))


def material_keys() -> set[str]:
    src = _read("materials.py")
    seg = src[src.index("MATERIALS: dict") :]
    return set(re.findall(r'^\s{4}"([a-z0-9_]+)"\s*:', seg, re.MULTILINE))


def rule_count_claims(text: str) -> set[int]:
    """Numbers used to claim a DRC rule count, in either language.

    Chinese phrasing varies ('26 规则', '26 条规则', '26 条设计规则'), so allow a
    few non-digit characters between the number and the noun.
    """
    zh = re.findall(r"(\d+)\s*条?[^0-9\s]{0,4}规则", text)
    en = re.findall(r"(\d+)\s*rules?\b", text, re.IGNORECASE)
    return {int(c) for c in zh + en}


def param_count_claims(text: str) -> set[int]:
    """Numbers used to claim an NL parameter count, in either language."""
    zh = re.findall(r"(\d+)\s*个?参数", text)
    en = re.findall(r"(\d+)\s*parameters?\b", text, re.IGNORECASE)
    return {int(c) for c in zh + en}


def automation_rows() -> list[str]:
    """The numbered automation table in README.md."""
    seg = re.search(r"## ✨ \d+ 项自动化(.*?)\n## ", _read("README.md"), re.DOTALL)
    assert seg, "README.md lost its automation table"
    return re.findall(r"^\| (\d+) \|", seg.group(1), re.MULTILINE)


# --------------------------------------------------------------------------- #
# Counts quoted in the docs
# --------------------------------------------------------------------------- #


def test_drc_rule_count_matches_every_doc():
    """Every 'N rules' claim in every doc must equal the number of rule codes.

    Strict on purpose: a doc that says both 20 and 26 passes a membership check
    while still being wrong, so the whole set of claimed counts must match.
    """
    n = len(drc_rule_codes())
    assert n >= 20, f"only {n} DRC rules found — extraction may have broken"
    for doc in COUNT_DOCS:
        text = _read(doc)
        claims = rule_count_claims(text)
        assert claims, f"{doc} never states a DRC rule count"
        assert claims == {n}, f"{doc} claims DRC rule counts {sorted(claims)}, code ships {n}"


def test_nl_param_count_matches_every_doc():
    n = len(nl_param_names())
    assert n >= 20, f"only {n} NL params found — extraction may have broken"
    for doc in COUNT_DOCS:
        text = _read(doc)
        claims = param_count_claims(text)
        assert claims, f"{doc} never states an NL parameter count"
        assert claims == {n}, f"{doc} claims NL parameter counts {sorted(claims)}, code ships {n}"


def test_material_count_matches_every_doc():
    """Every material preset must be named in the docs.

    Matching raw keys against prose is fragile (the docs say "FR-4" and "铝",
    not `fr4_high_tg` and `aluminum`), so the prose name is declared explicitly.
    Asserting the mapping's keys equal the real preset keys means adding a
    material fails this test until it is documented.
    """
    keys = material_keys()
    assert PRESET_PROSE.keys() == keys, (
        f"material presets changed. Code ships {sorted(keys)}, "
        f"PRESET_PROSE documents {sorted(PRESET_PROSE)} — update both the docs and this map"
    )
    for doc in COUNT_DOCS:
        text = _read(doc)
        missing = [k for k, aliases in PRESET_PROSE.items() if not any(a in text for a in aliases)]
        assert not missing, f"{doc} does not name material presets: {missing}"


def test_automation_table_matches_its_own_heading():
    """The 'N 项自动化' heading must equal the number of rows in the table."""
    rows = automation_rows()
    heading = int(re.search(r"## ✨ (\d+) 项自动化", _read("README.md")).group(1))
    assert len(rows) == heading, f"heading claims {heading} automations, table has {len(rows)}"
    # And the numbers must be a contiguous 1..N run.
    assert [int(r) for r in rows] == list(range(1, len(rows) + 1)), "automation numbering has gaps"


def test_english_readme_lists_the_same_automations():
    """The two READMEs must not drift apart in feature count."""
    zh = int(re.search(r"## ✨ (\d+) 项自动化", _read("README.md")).group(1))
    en_seg = re.search(r"## The (\d+) automations", _read("README.en.md"))
    assert en_seg, "README.en.md lost its automation section"
    assert int(en_seg.group(1)) == zh, f"README.en.md says {en_seg.group(1)}, README.md says {zh}"


# --------------------------------------------------------------------------- #
# Test-count badge
# --------------------------------------------------------------------------- #


def test_test_count_badge_is_not_stale():
    """The badge must quote the number of tests the suite actually collects.

    Deriving this from pytest itself means the badge can never quietly rot.
    """
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", str(REPO_ROOT / "tests")],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    m = re.search(r"(\d+)\s+tests? collected", proc.stdout)
    assert m, f"could not determine collected test count:\n{proc.stdout[-800:]}"
    actual = int(m.group(1))

    for doc in ("README.md", "README.en.md"):
        text = _read(doc)
        badges = [int(c) for c in re.findall(r"badge/tests-(\d+)", text)]
        assert badges, f"{doc} has no test badge"
        for b in badges:
            assert b == actual, f"{doc} test badge says {b}, suite collects {actual}"


# --------------------------------------------------------------------------- #
# Version consistency
# --------------------------------------------------------------------------- #


def test_version_has_no_pending_bump():
    """`pyproject.toml` must not lag behind a commit that claims a version."""
    import subprocess

    declared = re.search(r'^version\s*=\s*"([^"]+)"', _read("pyproject.toml"), re.MULTILINE)
    assert declared, "pyproject.toml has no version"
    version = declared.group(1)

    log_res = subprocess.run(
        ["git", "log", "-20", "--pretty=%s"],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        cwd=REPO_ROOT,
        check=False,
    )
    log = log_res.stdout or ""
    # A commit message that names a project version bump must not exceed the current one.
    def to_tuple(v_str: str) -> tuple[int, ...]:
        return tuple(int(x) for x in v_str.split("."))

    # Filter out dependency/action bumps like 'chore(deps): bump X from A to B' or 'ci: bump action'
    bump_lines = [
        line for line in log.splitlines()
        if re.search(r"bump version|release", line, re.IGNORECASE) and "deps" not in line.lower()
    ]
    named = set(re.findall(r"\bv?(\d+\.\d+\.\d+)\b", "\n".join(bump_lines)))
    future_named = {v for v in named if to_tuple(v) > to_tuple(version)}
    assert not future_named, (
        f"recent commits claim version(s) {sorted(future_named)} but pyproject says {version} — bump it"
    )


def test_published_tags_do_not_exceed_declared_version():
    """The declared version must be >= the newest release tag."""
    import subprocess

    declared = re.search(r'^version\s*=\s*"([^"]+)"', _read("pyproject.toml"), re.MULTILINE).group(1)
    tags = subprocess.run(
        ["git", "tag"], capture_output=True, text=True, cwd=REPO_ROOT, check=False
    ).stdout.split()

    def key(v: str) -> tuple:
        return tuple(int(x) for x in v.lstrip("v").split("."))

    released = [t for t in tags if re.fullmatch(r"v\d+\.\d+\.\d+", t)]
    if not released:
        pytest.skip("no release tags yet")
    newest = max(released, key=key)
    assert key(declared) >= key(newest), (
        f"pyproject version {declared} is behind the newest tag {newest}"
    )


# --------------------------------------------------------------------------- #
# Web frontend must have a real backend
# --------------------------------------------------------------------------- #


def test_web_frontend_endpoints_exist_in_the_server():
    """Every /api/ endpoint the UI calls must be implemented in web_server.py.

    An orphaned frontend (a UI calling endpoints that do not exist) is exactly
    the kind of thing that ships unnoticed and then 404s in front of a customer.
    """
    html = _read("web/index.html")
    called = set(re.findall(r"fetch\(\s*['\"`](/api/[a-z0-9_]+)", html))
    assert called, "web/index.html calls no /api/ endpoints — extraction may have broken"

    server = _read("web_server.py")
    missing = [ep for ep in sorted(called) if ep not in server]
    assert not missing, f"web/index.html calls endpoints absent from web_server.py: {missing}"


# --------------------------------------------------------------------------- #
# Packaging hygiene
# --------------------------------------------------------------------------- #


def test_every_top_level_module_is_packaged():
    """No module may be silently excluded from the wheel.

    This repo ships as a flat set of top-level modules; a new module that is not
    listed in `py-modules` installs fine from source and then ImportErrors for
    every user who pip-installs it.
    """
    pyproject = _read("pyproject.toml")
    m = re.search(r"py-modules\s*=\s*\[(.*?)\]", pyproject, re.DOTALL)
    assert m, "pyproject.toml has no py-modules list"
    packaged = set(re.findall(r'"([a-z0-9_]+)"', m.group(1)))

    on_disk = {
        p.stem
        for p in REPO_ROOT.glob("*.py")
        if not p.stem.startswith(("_", "test_", "batch_run", "process"))
    }
    missing = on_disk - packaged
    assert not missing, f"modules on disk but not in py-modules: {sorted(missing)}"
