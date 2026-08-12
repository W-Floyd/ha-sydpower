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

# SSH target for the Home Assistant OS box, for the deploy recipes.
# Override per invocation (`just haos_host=ha.local deploy`) or in the
# environment (`export HAOS_HOST=root@ha.local`). Requires the "Advanced SSH &
# Web Terminal" add-on; the official SSH add-on cannot reach the core container,
# which `deploy-lib` needs.
haos_host := env("HAOS_HOST", "root@homeassistant.local")
haos_config := "/config"
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

# ── Deploying to Home Assistant OS ────────────────────────────────────────────
#
# Python modules are cached once imported, so editing a file and reloading the
# config entry does NOT pick up code changes — the core has to restart. That is
# why every deploy recipe here restarts it.

# Refuse to deploy a manifest whose pinned wheel is not downloadable yet.
[private]
_check_pin_resolves:
    #!/usr/bin/env bash
    set -euo pipefail
    url=$({{python}} -c "
    import json
    m = json.load(open('{{justfile_directory()}}/{{manifest}}'))
    print(next(r.split(' @ ')[1] for r in m['requirements'] if r.startswith('sydpower @')))
    ")
    code=$(curl -sILo /dev/null -w '%{http_code}' "$url" || echo 000)
    if [ "$code" != "200" ]; then
        echo "the manifest pins a wheel that is not downloadable (HTTP $code):" >&2
        echo "  $url" >&2
        echo "" >&2
        echo "Home Assistant installs this at startup, so deploying now would leave" >&2
        echo "the integration failing with 'Requirements not found'. If a release was" >&2
        echo "just tagged, CI may still be uploading the asset — wait and retry:" >&2
        echo "  gh run watch --repo {{repo}}" >&2
        exit 1
    fi
    echo "manifest pin resolves (HTTP 200)"

# Copy the integration to HAOS and restart the core. For integration-only edits.
deploy: _check_pin_resolves
    #!/usr/bin/env bash
    set -euo pipefail
    src="{{justfile_directory()}}/custom_components/sydpower/"
    echo "deploying to {{haos_host}}:{{haos_config}}/custom_components/sydpower/"
    # --delete so files removed locally do not linger and shadow new code.
    rsync -av --delete \
        --exclude '__pycache__' --exclude '*.pyc' \
        "$src" "{{haos_host}}:{{haos_config}}/custom_components/sydpower/"
    ssh "{{haos_host}}" 'ha core restart'
    echo "restarted; follow with: just logs"

# Build the library, install it into the core container, and restart.
deploy-lib: build
    #!/usr/bin/env bash
    set -euo pipefail
    # Use this while iterating on sydpower/ without cutting a release: the
    # manifest pin is version-based, so HA skips reinstalling a version it
    # already has, and edits would otherwise never reach the box.
    wheel=$(ls "{{justfile_directory()}}/sydpower/dist/"*.whl | head -1)
    name=$(basename "$wheel")
    echo "installing $name into the core container on {{haos_host}}"

    # Staged through /config rather than /tmp: the SSH shell runs in its own
    # container, so its /tmp is not a path the docker daemon can resolve and
    # `docker cp` appears to succeed while copying nothing. /config is the same
    # volume the core container mounts, so both sides see this file.
    remote="{{haos_config}}/.sydpower-dev-wheel"
    ssh "{{haos_host}}" "mkdir -p '$remote'"
    scp "$wheel" "{{haos_host}}:$remote/$name"

    # Needs the Advanced SSH add-on with protection mode off, so docker is
    # reachable. --force-reinstall because the version may not have changed;
    # --no-deps because the dependencies are already satisfied.
    ssh "{{haos_host}}" "docker exec homeassistant pip install \
        --force-reinstall --no-deps '/config/.sydpower-dev-wheel/$name'"
    ssh "{{haos_host}}" "rm -rf '$remote'"

    ssh "{{haos_host}}" 'ha core restart'
    echo "restarted; confirm with: just deployed"

# Deploy both the library and the integration.
deploy-all: deploy-lib deploy

# Follow the Home Assistant log, filtered to this integration and the library.
logs:
    ssh "{{haos_host}}" 'tail -f {{haos_config}}/home-assistant.log' \
        | grep --line-buffered -iE 'sydpower|bleak|bluetooth' || true

# Print recent errors and warnings mentioning this integration.
logs-errors:
    ssh "{{haos_host}}" 'grep -iE "sydpower" {{haos_config}}/home-assistant.log' \
        | grep -iE "error|warning|traceback|Failed" | tail -40 || true

# Report which version is installed on the box, for both halves.
deployed:
    #!/usr/bin/env bash
    set -uo pipefail
    echo "integration manifest on device:"
    ssh "{{haos_host}}" "grep -E '\"version\"' {{haos_config}}/custom_components/sydpower/manifest.json" || true
    echo "library in the core container:"
    ssh "{{haos_host}}" "docker exec homeassistant pip show sydpower 2>/dev/null | grep -iE '^version'" || true
    echo "local: $(just version)"

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
