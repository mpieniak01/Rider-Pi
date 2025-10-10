#!/usr/bin/env bash
# scripts/util_load-config.sh — Helper for ops scripts to load configuration
# 
# Usage:
#   source scripts/util_load-config.sh
#   RIDER_ROOT=$(get_rider_root)
#   CONFIG_DIR=$(get_config_dir)
#   
# Or for one-liners:
#   source scripts/util_load-config.sh && exec_with_config python -m apps.voice.cli listen

set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# Detect project root
# ─────────────────────────────────────────────────────────────────────────────
get_rider_root() {
    # Try RIDER_ROOT env first
    if [[ -n "${RIDER_ROOT:-}" ]]; then
        echo "$RIDER_ROOT"
        return 0
    fi
    
    # Try to find from git root
    if command -v git >/dev/null 2>&1; then
        local git_root
        git_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
        if [[ -n "$git_root" ]]; then
            echo "$git_root"
            return 0
        fi
    fi
    
    # Fall back to script location (assume we're in scripts/)
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    echo "$(dirname "$script_dir")"
}

# ─────────────────────────────────────────────────────────────────────────────
# Get config directory
# ─────────────────────────────────────────────────────────────────────────────
get_config_dir() {
    # Try RIDER_CONFIG_DIR env first
    if [[ -n "${RIDER_CONFIG_DIR:-}" ]]; then
        echo "$RIDER_CONFIG_DIR"
        return 0
    fi
    
    # Default: $RIDER_ROOT/config
    local root
    root="$(get_rider_root)"
    echo "$root/config"
}

# ─────────────────────────────────────────────────────────────────────────────
# Load API key from profile if not already set
# ─────────────────────────────────────────────────────────────────────────────
load_api_key() {
    local var_name="${1:-OPENAI_API_KEY}"
    
    # If already set, don't override
    if [[ -n "${!var_name:-}" ]]; then
        return 0
    fi
    
    # Try to load from ~/.bash_profile
    if [[ -f "$HOME/.bash_profile" ]]; then
        local key_value
        key_value="$(
            bash -lc "source ~/.bash_profile >/dev/null 2>&1; printf '%s' \"\${${var_name}:-}\""
        )"
        
        if [[ -n "$key_value" ]]; then
            export "$var_name=$key_value"
            echo "[load_config] Loaded $var_name from ~/.bash_profile" >&2
            return 0
        fi
    fi
    
    # Try ~/.profile as fallback
    if [[ -f "$HOME/.profile" ]]; then
        local key_value
        key_value="$(
            bash -lc "source ~/.profile >/dev/null 2>&1; printf '%s' \"\${${var_name}:-}\""
        )"
        
        if [[ -n "$key_value" ]]; then
            export "$var_name=$key_value"
            echo "[load_config] Loaded $var_name from ~/.profile" >&2
            return 0
        fi
    fi
    
    echo "[load_config] WARNING: $var_name not found in environment or profile" >&2
    return 1
}

# ─────────────────────────────────────────────────────────────────────────────
# Setup common environment for voice applications
# ─────────────────────────────────────────────────────────────────────────────
setup_voice_env() {
    local config_dir
    config_dir="$(get_config_dir)"
    
    # Locale/encoding
    export PYTHONIOENCODING=UTF-8
    export LC_ALL=C.UTF-8
    export LANG=C.UTF-8
    
    # Python path
    local rider_root
    rider_root="$(get_rider_root)"
    export PYTHONPATH="${rider_root}:${PYTHONPATH:-}"
    
    # Unbuffered output for logging
    export PYTHONUNBUFFERED=1
    
    # Try to load API key
    load_api_key OPENAI_API_KEY || true
    
    # Export config dir for Python to discover
    export RIDER_CONFIG_DIR="$config_dir"
    
    echo "[load_config] Environment setup complete:" >&2
    echo "  RIDER_ROOT: $rider_root" >&2
    echo "  CONFIG_DIR: $config_dir" >&2
    echo "  PYTHONPATH: $PYTHONPATH" >&2
}

# ─────────────────────────────────────────────────────────────────────────────
# Convenience function: exec command with config loaded
# ─────────────────────────────────────────────────────────────────────────────
exec_with_config() {
    setup_voice_env
    exec "$@"
}

# ─────────────────────────────────────────────────────────────────────────────
# If sourced, export functions; if executed, show usage
# ─────────────────────────────────────────────────────────────────────────────
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    # Executed directly - show usage
    cat <<'USAGE'
load_config.sh — Configuration helper for Rider-Pi ops scripts

This script should be SOURCED, not executed:

    source scripts/util_load-config.sh
    setup_voice_env
    python -m apps.voice.cli listen

Functions available:
    get_rider_root      - Get project root directory
    get_config_dir      - Get config directory (respects RIDER_CONFIG_DIR)
    load_api_key [VAR]  - Load API key from profile (default: OPENAI_API_KEY)
    setup_voice_env     - Setup complete environment for voice apps
    exec_with_config    - Setup env and exec command

Example usage in script:
    #!/usr/bin/env bash
    set -euo pipefail
    
    # Load config utilities
    source "$(dirname "$0")/util_load-config.sh"
    
    # Setup environment
    setup_voice_env
    
    # Run application
    python -m apps.voice.cli listen

Environment variables:
    RIDER_ROOT        - Override project root detection
    RIDER_CONFIG_DIR  - Override config directory (default: $RIDER_ROOT/config)
    OPENAI_API_KEY    - Will be loaded from ~/.bash_profile if not set

See docs/CONFIG_POLICY.md for full configuration policy.
USAGE
    exit 0
fi

# Export functions when sourced
export -f get_rider_root
export -f get_config_dir
export -f load_api_key
export -f setup_voice_env
export -f exec_with_config
