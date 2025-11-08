#!/usr/bin/env bash
# config/alsa/preflight.sh — ALSA device pre-flight check and cleanup
#
# This script ensures ALSA devices are available before starting audio applications.
# It follows the security policy from docs/CONFIG_POLICY.md:
# - Logs all actions clearly
# - Uses safe termination (SIGTERM before SIGKILL)
# - Only kills specific known-safe processes (arecord, aplay, voice apps)
# - Requires --force flag to actually kill processes
#
# Usage:
#   config/alsa/preflight.sh [--force] [--capture DEVICE] [--playback DEVICE]
#
# Examples:
#   # Check without killing
#   config/alsa/preflight.sh --capture wm8960_in --playback wm8960_out
#   
#   # Check and kill blocking processes
#   config/alsa/preflight.sh --force --capture wm8960_in
#
# Exit codes:
#   0 - devices are free
#   1 - devices blocked (and --force not specified or kill failed)
#   2 - usage error

set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────
FORCE=0
CAPTURE_DEV=""
PLAYBACK_DEV=""
SCRIPT_NAME="[alsa-preflight]"
LIMIT_PIDS=()

# Skip lsof in test/CI environments
SKIP_LSOF="${ALSA_SKIP_LSOF:-0}"
if [[ -n "${PYTEST_CURRENT_TEST:-}" ]] || [[ -n "${CI:-}" ]]; then
    SKIP_LSOF=1
fi

# ─────────────────────────────────────────────────────────────────────────────
# Logging helpers
# ─────────────────────────────────────────────────────────────────────────────
log_info() {
    echo "$SCRIPT_NAME $*" >&2
}

log_warn() {
    echo "$SCRIPT_NAME WARNING: $*" >&2
}

log_error() {
    echo "$SCRIPT_NAME ERROR: $*" >&2
}

# ─────────────────────────────────────────────────────────────────────────────
# Parse arguments
# ─────────────────────────────────────────────────────────────────────────────
usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

ALSA device pre-flight check and cleanup.

Options:
    --force                Kill blocking processes if devices are busy
    --capture DEVICE       Specify capture device to check (e.g., wm8960_in)
    --playback DEVICE      Specify playback device to check (e.g., wm8960_out)
    --limit-pid PID        Limit cleanup to specific PID (can be repeated)
    --help                 Show this help

Exit codes:
    0 - Devices are free and accessible
    1 - Devices blocked (--force not specified or kill failed)
    2 - Usage error or missing tools

Examples:
    # Check devices without killing
    $0 --capture wm8960_in --playback wm8960_out

    # Force cleanup
    $0 --force --capture wm8960_in --playback wm8960_out

See docs/CONFIG_POLICY.md for security policy.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --force)
            FORCE=1
            shift
            ;;
        --capture)
            CAPTURE_DEV="$2"
            shift 2
            ;;
        --playback)
            PLAYBACK_DEV="$2"
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        --limit-pid)
            LIMIT_PIDS+=("$2")
            shift 2
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            exit 2
            ;;
    esac
done

# ─────────────────────────────────────────────────────────────────────────────
# Check prerequisites
# ─────────────────────────────────────────────────────────────────────────────
if ! command -v arecord >/dev/null 2>&1; then
    log_warn "arecord not found - ALSA tools not installed"
    exit 1
fi

if [[ "$SKIP_LSOF" != "1" ]] && ! command -v lsof >/dev/null 2>&1; then
    log_warn "lsof not found - cannot detect blocking processes"
fi

# ─────────────────────────────────────────────────────────────────────────────
# Device resolution (simple alias mapping)
# ─────────────────────────────────────────────────────────────────────────────
resolve_device() {
    local dev="$1"
    case "$dev" in
        wm8960_in|wm8960_out|wm8960soundcard)
            echo "hw:wm8960soundcard,0"
            ;;
        *)
            echo "$dev"
            ;;
    esac
}

# ─────────────────────────────────────────────────────────────────────────────
# Test device accessibility
# ─────────────────────────────────────────────────────────────────────────────
test_capture_device() {
    local dev="$1"
    log_info "Testing capture device: $dev"
    
    # Try to open device for 0.1 seconds
    timeout 2 arecord -D "$dev" -f S16_LE -r 16000 -c 1 -t raw -d 0.1 /dev/null >/dev/null 2>&1
    return $?
}

test_playback_device() {
    local dev="$1"
    log_info "Testing playback device: $dev"
    
    # Try to open device (play silence)
    timeout 2 aplay -D "$dev" -f S16_LE -r 16000 -c 2 /dev/null >/dev/null 2>&1
    return $?
}

# ─────────────────────────────────────────────────────────────────────────────
# Find and kill blocking processes
# ─────────────────────────────────────────────────────────────────────────────
kill_blocking_processes() {
    if [[ "$SKIP_LSOF" == "1" ]]; then
        log_info "Skipping lsof (test/CI environment)"
        return 0
    fi

    log_info "Searching for processes using /dev/snd/*"

    local output
    output="$(lsof /dev/snd/* 2>/dev/null || true)"

    if [[ -z "$output" ]]; then
        log_info "No processes found using audio devices"
        return 0
    fi

    local killed=0
    local line cmd pid rest allowed limit
    while read -r line; do
        [[ -n "$line" ]] || continue
        read -r cmd pid rest <<< "$line"
        if [[ ! "$cmd" =~ ^(arecord|aplay|python.*voice) ]]; then
            continue
        fi

        if [[ ${#LIMIT_PIDS[@]} -gt 0 ]]; then
            allowed=0
            for limit in "${LIMIT_PIDS[@]}"; do
                if [[ "$limit" == "$pid" ]]; then
                    allowed=1
                    break
                fi
            done
            [[ $allowed -eq 1 ]] || continue
        fi

        log_warn "Found blocking process: PID=$pid CMD=$cmd"

        if [[ "$FORCE" != "1" ]]; then
            log_warn "Device busy (use --force to kill blocking processes)"
            continue
        fi

        log_info "Sending SIGTERM to PID=$pid ($cmd)"
        kill -TERM "$pid" 2>/dev/null || {
            log_warn "Failed to send SIGTERM to PID=$pid"
            continue
        }
        for _ in {1..10}; do
            if ! kill -0 "$pid" 2>/dev/null; then
                log_info "PID=$pid terminated gracefully"
                killed=$((killed + 1))
                break
            fi
            sleep 0.1
        done
        if kill -0 "$pid" 2>/dev/null; then
            log_warn "PID=$pid did not terminate, sending SIGKILL"
            kill -KILL "$pid" 2>/dev/null || {
                log_error "Failed to SIGKILL PID=$pid"
                continue
            }
            sleep 0.2
            if ! kill -0 "$pid" 2>/dev/null; then
                log_info "PID=$pid force-killed"
                killed=$((killed + 1))
            else
                log_error "PID=$pid could not be killed"
            fi
        fi
    done < <(printf '%s\n' "$output" | tail -n +2)

    if [[ $killed -gt 0 ]]; then
        log_info "Killed $killed blocking process(es)"
        sleep 0.3  # Give system time to clean up
    fi

    return 0
}

# ─────────────────────────────────────────────────────────────────────────────
# Main logic
# ─────────────────────────────────────────────────────────────────────────────
main() {
    local capture_ok=1
    local playback_ok=1
    local had_errors=0
    
    # Resolve device names
    local capture_resolved=""
    local playback_resolved=""
    
    if [[ -n "$CAPTURE_DEV" ]]; then
        capture_resolved="$(resolve_device "$CAPTURE_DEV")"
        log_info "Checking capture device: $CAPTURE_DEV -> $capture_resolved"
    fi
    
    if [[ -n "$PLAYBACK_DEV" ]]; then
        playback_resolved="$(resolve_device "$PLAYBACK_DEV")"
        log_info "Checking playback device: $PLAYBACK_DEV -> $playback_resolved"
    fi
    
    # Initial device tests
    if [[ -n "$capture_resolved" ]]; then
        if test_capture_device "$capture_resolved"; then
            log_info "✓ Capture device is accessible"
            capture_ok=0
        else
            log_warn "✗ Capture device is NOT accessible"
            capture_ok=1
        fi
    fi
    
    if [[ -n "$playback_resolved" ]]; then
        if test_playback_device "$playback_resolved"; then
            log_info "✓ Playback device is accessible"
            playback_ok=0
        else
            log_warn "✗ Playback device is NOT accessible"
            playback_ok=1
        fi
    fi
    
    # If devices are blocked, try to clean up
    if [[ $capture_ok -ne 0 ]] || [[ $playback_ok -ne 0 ]]; then
        log_info "Devices blocked, searching for blocking processes..."
        kill_blocking_processes
        
        # Retest after cleanup
        if [[ -n "$capture_resolved" ]] && [[ $capture_ok -ne 0 ]]; then
            if test_capture_device "$capture_resolved"; then
                log_info "✓ Capture device now accessible after cleanup"
                capture_ok=0
            else
                log_error "✗ Capture device still NOT accessible"
                had_errors=1
            fi
        fi
        
        if [[ -n "$playback_resolved" ]] && [[ $playback_ok -ne 0 ]]; then
            if test_playback_device "$playback_resolved"; then
                log_info "✓ Playback device now accessible after cleanup"
                playback_ok=0
            else
                log_error "✗ Playback device still NOT accessible"
                had_errors=1
            fi
        fi
    fi
    
    # Summary
    if [[ $had_errors -eq 0 ]] && [[ $capture_ok -eq 0 ]] && [[ $playback_ok -eq 0 ]]; then
        log_info "✓ All devices ready"
        return 0
    else
        log_error "Devices not ready (try --force or check ALSA configuration)"
        return 1
    fi
}

# Run main and exit with its status
main
exit $?
