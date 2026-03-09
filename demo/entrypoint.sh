#!/usr/bin/env bash
set -euo pipefail

# ── Config ────────────────────────────────────────────────
PRESET="${PRESET:-en-business}"
PRESET_DIR="/demo/presets/${PRESET}"
DATA_DIR="${ANIMAWORKS_DATA_DIR:-$HOME/.animaworks}"
CONFIG_JSON="${DATA_DIR}/config.json"

# ── Validation ────────────────────────────────────────────
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "WARNING: ANTHROPIC_API_KEY is not set. Animas will not be able to respond."
    echo "         Set it in demo/.env or pass via -e ANTHROPIC_API_KEY=sk-..."
fi

if [ ! -d "$PRESET_DIR" ]; then
    echo "ERROR: Preset directory not found: ${PRESET_DIR}"
    echo "       Available presets:"
    ls -1 /demo/presets/ 2>/dev/null || echo "       (none)"
    exit 1
fi

# ── First-run initialization ─────────────────────────────
if [ ! -f "$CONFIG_JSON" ]; then
    echo "=== First run detected — initializing AnimaWorks ==="
    echo "Preset: ${PRESET}"

    # 1. Initialize runtime (infrastructure only, no default anima)
    animaworks init --skip-anima
    echo "Runtime directory initialized."

    # 2. Copy company vision if present
    if [ -f "${PRESET_DIR}/vision.md" ]; then
        mkdir -p "${DATA_DIR}/company"
        cp "${PRESET_DIR}/vision.md" "${DATA_DIR}/company/vision.md"
        echo "Company vision installed."
    fi

    # 3. Apply config overlay BEFORE anima creation so locale is correct
    overlay="${PRESET_DIR}/config_overlay.json"
    if [ -f "$overlay" ]; then
        python3 -c "
import json, sys
def deep_merge(base, patch):
    for k, v in patch.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            deep_merge(base[k], v)
        else:
            base[k] = v
cfg_path, ovl_path = sys.argv[1], sys.argv[2]
with open(cfg_path) as f:
    cfg = json.load(f)
with open(ovl_path) as f:
    ovl = json.load(f)
deep_merge(cfg, ovl)
with open(cfg_path, 'w') as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
" "$CONFIG_JSON" "$overlay"
        echo "Config overlay applied."

        rm -rf "${DATA_DIR}/prompts" "${DATA_DIR}/common_knowledge" "${DATA_DIR}/common_skills"
        python3 -c "
from core.init import merge_templates
from pathlib import Path
merge_templates(Path('$DATA_DIR'))
"
        echo "Templates re-merged with locale from overlay."
    fi

    # 4. Create animas from character sheets (locale is now correct)
    for md_file in "${PRESET_DIR}/characters/"*.md; do
        [ -f "$md_file" ] || continue
        name="$(basename "$md_file" .md)"
        role_file="${PRESET_DIR}/roles/${name}.txt"

        create_args=(animaworks anima create --from-md "$md_file")

        if [ -f "$role_file" ]; then
            role="$(sed -n '1p' "$role_file")"
            supervisor="$(sed -n '2p' "$role_file")"

            if [ -n "$role" ]; then
                create_args+=(--role "$role")
            fi
            if [ -n "$supervisor" ]; then
                create_args+=(--supervisor "$supervisor")
            fi
        fi

        echo "Creating anima: ${name}"
        "${create_args[@]}"
    done

    # 4a. Override models for demo (cost optimization: sonnet/haiku instead of opus/sonnet)
    python3 -c "
import json, sys, glob
data_dir = sys.argv[1]
for status_path in glob.glob(f'{data_dir}/animas/*/status.json'):
    with open(status_path) as f:
        status = json.load(f)
    role = status.get('role', 'general')
    if role in ('manager', 'engineer', 'writer', 'researcher'):
        status['model'] = 'claude-sonnet-4-6'
        status['background_model'] = 'claude-haiku-4-5-20251001'
    else:
        status['model'] = 'claude-haiku-4-5-20251001'
        status['background_model'] = 'claude-haiku-4-5-20251001'
    with open(status_path, 'w') as f:
        json.dump(status, f, indent=2, ensure_ascii=False)
" "$DATA_DIR"
    echo "Demo model override applied (sonnet + haiku)."

    # 4b. Copy preset-specific heartbeat/cron files (override blank templates)
    for hb_file in "${PRESET_DIR}/heartbeat/"*.md; do
        [ -f "$hb_file" ] || continue
        name="$(basename "$hb_file" .md)"
        target="${DATA_DIR}/animas/${name}/heartbeat.md"
        if [ -d "${DATA_DIR}/animas/${name}" ]; then
            cp "$hb_file" "$target"
            echo "Custom heartbeat installed for: ${name}"
        fi
    done
    for cron_file in "${PRESET_DIR}/cron/"*.md; do
        [ -f "$cron_file" ] || continue
        name="$(basename "$cron_file" .md)"
        target="${DATA_DIR}/animas/${name}/cron.md"
        if [ -d "${DATA_DIR}/animas/${name}" ]; then
            cp "$cron_file" "$target"
            echo "Custom cron installed for: ${name}"
        fi
    done

    # 4c. Create auth.json (local_trust mode, no password)
    cat > "${DATA_DIR}/auth.json" <<AUTHEOF
{
  "auth_mode": "local_trust",
  "trust_localhost": true,
  "owner": {
    "username": "demo",
    "display_name": "Demo User",
    "role": "owner"
  },
  "users": [],
  "sessions": {},
  "token_version": 1
}
AUTHEOF
    echo "Auth config created (local_trust)."

    # 5. Copy pre-built character assets
    for char_dir in "${PRESET_DIR}/assets/"*/; do
        [ -d "$char_dir" ] || continue
        char_name="$(basename "$char_dir")"
        target_dir="${DATA_DIR}/animas/${char_name}/assets"
        if [ ! -d "$target_dir" ]; then
            mkdir -p "$target_dir"
        fi
        cp "$char_dir"/* "$target_dir/" 2>/dev/null || true
    done
    echo "Character assets installed."

    # 6. Copy example runtime data (activity logs, state, channels)
    LANG_KEY="${PRESET%%-*}"  # ja or en
    EXAMPLES_DIR="/demo/examples/${LANG_KEY}"
    if [ -d "$EXAMPLES_DIR" ]; then
        # Adjust timestamps to be relative to today (in-place, container is ephemeral)
        if [ -f /demo/adjust_dates.sh ]; then
            /demo/adjust_dates.sh "$EXAMPLES_DIR"
        fi

        for char_dir in "$EXAMPLES_DIR"/*/; do
            char_name="$(basename "$char_dir")"
            [ "$char_name" = "channels" ] && continue
            [ "$char_name" = "users" ] && continue
            target_dir="${DATA_DIR}/animas/${char_name}"
            if [ -d "$target_dir" ]; then
                cp -r "$char_dir"/* "$target_dir/" 2>/dev/null || true
            fi
        done
        if [ -d "$EXAMPLES_DIR/channels" ]; then
            mkdir -p "${DATA_DIR}/shared/channels"
            cp "$EXAMPLES_DIR/channels/"* "${DATA_DIR}/shared/channels/" 2>/dev/null || true
        fi
        if [ -d "$EXAMPLES_DIR/users" ]; then
            mkdir -p "${DATA_DIR}/shared/users"
            cp -r "$EXAMPLES_DIR/users/"* "${DATA_DIR}/shared/users/" 2>/dev/null || true
        fi
        echo "Example runtime data installed."
    fi

    echo "=== Initialization complete ==="
else
    echo "Existing configuration found — skipping initialization."
fi

# ── Inject API key & mode_s_auth into config ─────────────
if [ -n "${ANTHROPIC_API_KEY:-}" ] && [ -f "$CONFIG_JSON" ]; then
    python3 -c "
import json, os, sys
cfg_path = sys.argv[1]
api_key = os.environ['ANTHROPIC_API_KEY']
with open(cfg_path) as f:
    cfg = json.load(f)
creds = cfg.setdefault('credentials', {}).setdefault('anthropic', {})
creds['type'] = 'api_key'
creds['api_key'] = api_key
cfg.setdefault('anima_defaults', {})['mode_s_auth'] = 'api'
with open(cfg_path, 'w') as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
" "$CONFIG_JSON"
    echo "API key injected into config."
fi

# ── Clean stale PID file ──────────────────────────────────
# In Docker, PID 1 always exists (it's the entrypoint itself), so a
# leftover server.pid from a previous container run would trick the
# "already running" check.  Remove it unconditionally before starting.
rm -f "${DATA_DIR}/server.pid"

# ── Start server ──────────────────────────────────────────
echo "Starting AnimaWorks server on port 18501..."
exec animaworks start --host 0.0.0.0 --port 18501 --foreground
