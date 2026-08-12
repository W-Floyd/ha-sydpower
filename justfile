# Release automation for ha-sydpower.
#
# The Python library and the Home Assistant integration share one version and
# one `v*` tag. Four places must agree, and a mismatch produces a release that
# installs but whose requirement URL 404s:
#
#   sydpower/pyproject.toml     version
#   sydpower/setup.py           __version__
#   manifest.json               version
#   manifest.json               requirements pin -> .../download/vX.Y.Z/sydpower-X.Y.Z-...whl
#
# Typical use:
#   just bump patch     # rewrite all four, add a changelog stub
#   just release        # test, verify, commit, tag, push (CI attaches the wheel)

set shell := ["bash", "-uc"]

repo := "W-Floyd/ha-sydpower"
pyproject := "sydpower/pyproject.toml"
setup := "sydpower/setup.py"
manifest := "custom_components/sydpower/manifest.json"
changes := "sydpower/CHANGES.md"
python := "python3"

# Show available recipes.
default:
    @just --list

# Print the current version, taken from pyproject.toml.
version:
    @{{python}} -c "import re;print(re.search(r'^version = \"(.+?)\"', open('{{pyproject}}').read(), re.M).group(1))"

# Verify all four version locations agree. Run before tagging.
check:
    #!/usr/bin/env bash
    set -euo pipefail
    {{python}} - <<'PY'
    import json, re, sys

    pyproject = open("{{pyproject}}").read()
    version = re.search(r'^version = "(.+?)"', pyproject, re.M).group(1)
    errors = []

    setup_version = re.search(r'^__version__ = "(.+?)"', open("{{setup}}").read(), re.M)
    if setup_version is None:
        errors.append("setup.py has no __version__")
    elif setup_version.group(1) != version:
        errors.append(f"setup.py is {setup_version.group(1)}, expected {version}")

    m = json.load(open("{{manifest}}"))
    if m["version"] != version:
        errors.append(f"manifest version is {m['version']}, expected {version}")

    pin = next((r for r in m["requirements"] if r.startswith("sydpower @")), None)
    if pin is None:
        errors.append("manifest has no sydpower requirement pin")
    else:
        expected = f"/releases/download/v{version}/sydpower-{version}-py3-none-any.whl"
        if not pin.endswith(expected):
            errors.append("pin does not reference " + expected + "\n    pin: " + pin)

    for e in errors:
        print("  " + e, file=sys.stderr)
    if errors:
        sys.exit(1)
    print(f"all version references agree: {version}")
    PY

# Bump the version. LEVEL is patch, minor or major.
bump level="patch":
    #!/usr/bin/env bash
    set -euo pipefail
    {{python}} - "{{level}}" <<'PY'
    import json, re, sys, datetime, pathlib

    level = sys.argv[1]
    if level not in ("patch", "minor", "major"):
        sys.exit(f"level must be patch, minor or major, not {level!r}")

    pyproject_path = pathlib.Path("{{pyproject}}")
    text = pyproject_path.read_text()
    current = re.search(r'^version = "(.+?)"', text, re.M).group(1)
    major, minor, patch = (int(p) for p in current.split("."))

    if level == "major":
        major, minor, patch = major + 1, 0, 0
    elif level == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    new = f"{major}.{minor}.{patch}"

    pyproject_path.write_text(
        re.sub(r'^version = ".+?"', f'version = "{new}"', text, count=1, flags=re.M)
    )

    setup_path = pathlib.Path("{{setup}}")
    setup_path.write_text(
        re.sub(
            r'^__version__ = ".+?"',
            f'__version__ = "{new}"',
            setup_path.read_text(),
            count=1,
            flags=re.M,
        )
    )

    # The manifest is rewritten via json so the pin and version cannot drift.
    manifest_path = pathlib.Path("{{manifest}}")
    m = json.loads(manifest_path.read_text())
    m["version"] = new
    wheel = f"https://github.com/{{repo}}/releases/download/v{new}/sydpower-{new}-py3-none-any.whl"
    m["requirements"] = [
        "sydpower @ " + wheel if r.startswith("sydpower @") else r
        for r in m["requirements"]
    ]
    manifest_path.write_text(json.dumps(m, indent=2) + "\n")

    # Prepend a changelog stub above the newest existing entry, for editing.
    changes_path = pathlib.Path("{{changes}}")
    body = changes_path.read_text()
    today = datetime.date.today().isoformat()
    stub = f"## [{new}] - {today}\n\n### Changed\n- TODO: describe this release.\n\n"
    index = body.find("## [")
    changes_path.write_text(body[:index] + stub + body[index:] if index != -1 else body + "\n" + stub)

    print(f"{current} -> {new}")
    print(f"  edit {{changes}} to describe the release, then: just release")
    PY

# Create sydpower/.venv with the library and its dev dependencies installed.
dev-setup:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{justfile_directory()}}/sydpower"
    {{python}} -m venv .venv
    .venv/bin/pip install --quiet --upgrade pip
    .venv/bin/pip install --quiet -e ".[dev]" build
    echo "ready: sydpower/.venv"

# Resolve an interpreter that has the test dependencies, or explain how to get one.
[private]
_python:
    #!/usr/bin/env bash
    set -euo pipefail
    py="{{justfile_directory()}}/sydpower/.venv/bin/python"
    [ -x "$py" ] || py="{{python}}"
    if ! "$py" -c "import pytest, bleak" 2>/dev/null; then
        echo "missing test dependencies. Run: just dev-setup" >&2
        exit 1
    fi
    echo "$py"

# Run the library test suite.
test:
    #!/usr/bin/env bash
    set -euo pipefail
    py=$(just _python)
    cd "{{justfile_directory()}}/sydpower" && "$py" -m pytest tests/ -q

# Build the wheel locally, to check packaging without tagging.
build: test
    #!/usr/bin/env bash
    set -euo pipefail
    py=$(just _python)
    cd "{{justfile_directory()}}/sydpower"
    rm -rf dist build ./*.egg-info
    "$py" -m build --wheel
    ls -1 dist

# Commit, tag and push the current version. CI builds and attaches the wheel.
release: check test
    #!/usr/bin/env bash
    set -euo pipefail
    version=$(just version)
    tag="v${version}"

    if git rev-parse "$tag" >/dev/null 2>&1; then
        echo "tag $tag already exists; bump first" >&2
        exit 1
    fi
    if grep -q "TODO: describe this release" {{changes}}; then
        echo "{{changes}} still has a TODO stub; describe the release first" >&2
        exit 1
    fi

    # Only the release files may be dirty, so an unrelated work-in-progress is
    # never swept into a release commit.
    unexpected=$(git status --porcelain -- . \
        ':!{{pyproject}}' ':!{{setup}}' ':!{{manifest}}' ':!{{changes}}' || true)
    if [ -n "$unexpected" ]; then
        echo "unrelated changes present; commit or stash them first:" >&2
        echo "$unexpected" >&2
        exit 1
    fi

    git add {{pyproject}} {{setup}} {{manifest}} {{changes}}
    git commit -m "chore(release): $tag"
    git tag -a "$tag" -m "sydpower $version"
    git push origin HEAD
    git push origin "$tag"
    echo "pushed $tag; CI will build and attach the wheel"
    echo "watch: gh run watch --repo {{repo}}"

# Bump and release in one step. Skips the changelog stub check.
release-now level="patch":
    just bump {{level}}
    {{python}} -c "import pathlib;p=pathlib.Path('{{changes}}');p.write_text(p.read_text().replace('TODO: describe this release.','Version bump.',1))"
    just release

# Show the state of the most recent release and whether its wheel resolves.
status:
    #!/usr/bin/env bash
    set -uo pipefail
    echo "local version: $(just version)"
    gh release list --repo {{repo}} --limit 3 || true
    version=$(just version)
    url="https://github.com/{{repo}}/releases/download/v${version}/sydpower-${version}-py3-none-any.whl"
    code=$(curl -sILo /dev/null -w '%{http_code}' "$url" || echo "000")
    echo "wheel for v${version}: HTTP ${code} ${url}"
