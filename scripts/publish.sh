#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# publish.sh — AnimaWorks リリーススクリプト
#
# Usage:
#   scripts/publish.sh --release              # patch bump + GitHub Release
#   scripts/publish.sh --release minor        # minor bump
#   scripts/publish.sh --release 0.6.0        # explicit version
#   scripts/publish.sh --dry-run --release     # preview (no changes)
#   scripts/publish.sh --pii-check --release   # PII check 付きリリース
#
# Workflow:
#   1. Validate (clean tree, on main, synced)
#   2. Version bump + CHANGELOG update (generate_changelog.py)
#   3. Release notes generation (generate_release_notes.py — EN+JA)
#   4. Commit + Tag
#   5. Push
#   6. GitHub Release (gh release create)

set -euo pipefail

# ── Config ──────────────────────────────────────────
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS_DIR="$REPO_ROOT/scripts"
RELEASE_NOTES_FILE="/tmp/animaworks_release_notes.md"

# ── Parse args ──────────────────────────────────────
DRY_RUN=false
DO_RELEASE=false
RELEASE_BUMP="patch"
PII_CHECK=false
ALL_LOGS=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)     DRY_RUN=true ;;
        --pii-check)   PII_CHECK=true ;;
        --all-logs)    ALL_LOGS=true ;;
        --release)
            DO_RELEASE=true
            if [[ "${2:-}" =~ ^(patch|minor|major)$ ]] || [[ "${2:-}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
                RELEASE_BUMP="$2"
                shift
            fi
            ;;
        --help|-h)
            echo "Usage: $0 --release [patch|minor|major|X.Y.Z] [--dry-run] [--pii-check] [--all-logs]"
            echo ""
            echo "Options:"
            echo "  --release [BUMP]   Release with version bump (default: patch)"
            echo "  --dry-run          Preview only, no changes"
            echo "  --pii-check        Run PII scan before commit"
            echo "  --all-logs         Use all work logs (ignore previous tag date)"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
    shift
done

if ! $DO_RELEASE; then
    echo "ERROR: --release is required."
    echo "Run: $0 --release [patch|minor|major|X.Y.Z]"
    exit 1
fi

# ── Helpers ─────────────────────────────────────────
get_version() {
    python3 -c "import re; print(re.search(r'version\s*=\s*\"([^\"]+)\"', open('$REPO_ROOT/pyproject.toml').read()).group(1))"
}

get_prev_tag() {
    git -C "$REPO_ROOT" describe --tags --abbrev=0 2>/dev/null || echo ""
}

calc_next_version() {
    local current="$1" bump="$2"
    if [[ "$bump" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo "$bump"
    else
        python3 -c "
v = '$current'.split('.')
b = '$bump'
if b == 'major': v = [str(int(v[0])+1), '0', '0']
elif b == 'minor': v = [v[0], str(int(v[1])+1), '0']
else: v = [v[0], v[1], str(int(v[2])+1)]
print('.'.join(v))
"
    fi
}

# ── PII check (optional) ───────────────────────────
run_pii_check() {
    local diff_content="$1"
    echo "Running PII scan via cursor-agent..."

    if ! command -v cursor-agent &>/dev/null; then
        echo "WARNING: cursor-agent not found. Skipping PII check."
        return 0
    fi

    local prompt='You are a PII auditor. Check the following file list for real person names, internal hostnames, credential files, or private paths. Respond with "PII_CHECK_RESULT: PASS" if clean, or "PII_CHECK_RESULT: FAIL" with details.

'"$diff_content"

    local result
    result=$(cursor-agent -p --model composer-1.5 "$prompt" 2>&1) || {
        echo "WARNING: PII check failed. Continue? [y/N]"
        read -r confirm
        [[ "$confirm" == [yY] ]] || exit 1
        return 0
    }

    echo "$result"
    if echo "$result" | grep -q "PII_CHECK_RESULT: PASS"; then
        echo "PII check: PASSED"
    elif echo "$result" | grep -q "PII_CHECK_RESULT: FAIL"; then
        echo "PII check: FAILED"
        exit 1
    fi
}

# ── Execute ─────────────────────────────────────────
echo "=== AnimaWorks Release ==="
echo "Mode: $(if $DRY_RUN; then echo 'DRY-RUN'; else echo 'EXECUTE'; fi)"
echo ""

PREV_TAG=$(get_prev_tag)
CURRENT_VERSION=$(get_version)
echo "Current version: $CURRENT_VERSION"
echo "Previous tag:    ${PREV_TAG:-"(none)"}"
echo ""

# ── Step 1: Validate ────────────────────────────────
echo "--- Step 1: Validate ---"

if ! git -C "$REPO_ROOT" diff --quiet || ! git -C "$REPO_ROOT" diff --cached --quiet; then
    echo "ERROR: Working tree is not clean. Commit or stash changes first."
    git -C "$REPO_ROOT" status --short
    exit 1
fi

BRANCH=$(git -C "$REPO_ROOT" branch --show-current)
if [[ "$BRANCH" != "main" ]]; then
    echo "ERROR: Not on main branch (current: $BRANCH)."
    exit 1
fi

if ! $DRY_RUN; then
    echo "Pulling latest..."
    git -C "$REPO_ROOT" pull --rebase origin main || true
fi
echo "Validation passed."
echo ""

# ── Step 2: Version bump + CHANGELOG ────────────────
echo "--- Step 2: Version bump + CHANGELOG ---"

CHANGELOG_ARGS=(--release "$RELEASE_BUMP")
if $DRY_RUN; then
    python3 "$SCRIPTS_DIR/generate_changelog.py" "${CHANGELOG_ARGS[@]}" --dry-run
    RELEASE_VERSION=$(calc_next_version "$CURRENT_VERSION" "$RELEASE_BUMP")
else
    python3 "$SCRIPTS_DIR/generate_changelog.py" "${CHANGELOG_ARGS[@]}"
    RELEASE_VERSION=$(get_version)
fi
echo "Release version: $RELEASE_VERSION"
echo ""

# ── Step 3: Release notes (EN + JA) ────────────────
echo "--- Step 3: Generate release notes (EN + JA) ---"

NOTES_ARGS=(--version "$RELEASE_VERSION")
if ! $ALL_LOGS && [[ -n "$PREV_TAG" ]]; then
    NOTES_ARGS+=(--since-tag "$PREV_TAG")
    echo "Using work logs since tag $PREV_TAG"
else
    echo "Using ALL work logs (initial release or --all-logs)"
fi
if $DRY_RUN; then
    NOTES_ARGS+=(--dry-run)
fi

python3 "$SCRIPTS_DIR/generate_release_notes.py" "${NOTES_ARGS[@]}"
echo ""

if $DRY_RUN; then
    echo ""
    echo "=== Dry-run complete ==="
    echo "Would release v${RELEASE_VERSION}"
    exit 0
fi

# ── Step 4: PII check (optional) ───────────────────
if $PII_CHECK; then
    echo "--- Step 4: PII check ---"
    DIFF_FILES=$(git -C "$REPO_ROOT" diff HEAD --name-status)
    run_pii_check "$DIFF_FILES"
    echo ""
fi

# ── Step 5: Commit + Tag ───────────────────────────
echo "--- Step 5: Commit + Tag ---"

git -C "$REPO_ROOT" add CHANGELOG.md pyproject.toml
git -C "$REPO_ROOT" commit -m "release: v${RELEASE_VERSION}" --no-verify

git -C "$REPO_ROOT" tag "v${RELEASE_VERSION}" 2>/dev/null || {
    echo "WARNING: Tag v${RELEASE_VERSION} already exists."
}

echo "Committed and tagged v${RELEASE_VERSION}"
echo ""

# ── Step 6: Push ───────────────────────────────────
echo "--- Step 6: Push ---"

git -C "$REPO_ROOT" push origin main --follow-tags
echo "Pushed to origin/main with tags."
echo ""

# ── Step 7: GitHub Release ─────────────────────────
echo "--- Step 7: GitHub Release ---"

if ! command -v gh &>/dev/null; then
    echo "WARNING: gh CLI not found. Skipping GitHub Release."
    echo "Create manually: gh release create v${RELEASE_VERSION} --notes-file $RELEASE_NOTES_FILE"
else
    if [[ -f "$RELEASE_NOTES_FILE" ]]; then
        gh release create "v${RELEASE_VERSION}" \
            --title "v${RELEASE_VERSION}" \
            --notes-file "$RELEASE_NOTES_FILE"
        echo "GitHub Release v${RELEASE_VERSION} created!"
    else
        echo "WARNING: Release notes file not found at $RELEASE_NOTES_FILE"
        echo "Creating release with auto-generated notes..."
        gh release create "v${RELEASE_VERSION}" \
            --title "v${RELEASE_VERSION}" \
            --generate-notes
    fi
fi

# ── Summary ─────────────────────────────────────────
echo ""
echo "=== Release Complete ==="
echo "Version:  v${RELEASE_VERSION}"
echo "Tag:      v${RELEASE_VERSION}"
echo "Commit:   $(git -C "$REPO_ROOT" log --oneline -1)"
echo "Release:  https://github.com/xuiltul/animaworks/releases/tag/v${RELEASE_VERSION}"
