#!/usr/bin/env bash
# Rider-Pi systemd services smoke test
# Tests that all systemd service files can be loaded and have valid paths

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SYSTEMD_DIR="$REPO_ROOT/systemd"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_ok() {
    echo -e "${GREEN}✓${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}!${NC} $*"
}

log_error() {
    echo -e "${RED}✗${NC} $*"
}

# Check if systemd directory exists
if [[ ! -d "$SYSTEMD_DIR" ]]; then
    log_error "systemd directory not found at $SYSTEMD_DIR"
    exit 1
fi

echo "Rider-Pi Systemd Services Smoke Test"
echo "====================================="
echo "Repository root: $REPO_ROOT"
echo "Systemd directory: $SYSTEMD_DIR"
echo ""

# Find all service files
mapfile -t SERVICE_FILES < <(find "$SYSTEMD_DIR" -name "*.service" -type f | sort)

if [[ ${#SERVICE_FILES[@]} -eq 0 ]]; then
    log_error "No service files found in $SYSTEMD_DIR"
    exit 1
fi

echo "Found ${#SERVICE_FILES[@]} service files"
echo ""

# Test 1: Validate with systemd-analyze verify
echo "Test 1: systemd-analyze verify"
echo "-------------------------------"

VERIFY_FAILED=0
for service in "${SERVICE_FILES[@]}"; do
    service_name=$(basename "$service")
    
    # Run systemd-analyze verify
    if output=$(systemd-analyze verify "$service" 2>&1); then
        log_ok "$service_name: syntax valid"
    else
        # Check if errors are only about missing files (expected in CI)
        if echo "$output" | grep -q "No such file or directory\|not executable"; then
            log_warn "$service_name: syntax valid (warnings about missing files are expected)"
        else
            log_error "$service_name: validation failed"
            echo "$output" | sed 's/^/  /'
            VERIFY_FAILED=$((VERIFY_FAILED + 1))
        fi
    fi
done

echo ""

# Test 2: Check for correct paths
echo "Test 2: Path validation"
echo "-----------------------"

PATH_FAILED=0

# Run our custom path validator
if python3 "$REPO_ROOT/scripts/diag_validate-systemd-paths.py"; then
    log_ok "All service file paths validated"
else
    log_error "Path validation failed"
    PATH_FAILED=1
fi

echo ""

# Test 3: Check for deprecated patterns
echo "Test 3: Check for deprecated patterns"
echo "--------------------------------------"

DEPRECATED_FAILED=0

for service in "${SERVICE_FILES[@]}"; do
    service_name=$(basename "$service")
    
    # Check for /workspaces/ paths (should not exist)
    if grep -q "/workspaces/" "$service" 2>/dev/null; then
        log_error "$service_name: contains /workspaces/ path (should use /home/pi/robot)"
        DEPRECATED_FAILED=$((DEPRECATED_FAILED + 1))
        continue
    fi
    
    # Check for ops/ paths (should not exist, migrated to scripts/)
    if grep -E "^ExecStart.*\bops/" "$service" 2>/dev/null; then
        log_error "$service_name: contains ops/ path (should use scripts/)"
        DEPRECATED_FAILED=$((DEPRECATED_FAILED + 1))
        continue
    fi
    
    # Check for tools/ paths (should not exist, migrated to scripts/)
    if grep -E "^ExecStart.*\btools/" "$service" 2>/dev/null; then
        log_error "$service_name: contains tools/ path (should use scripts/)"
        DEPRECATED_FAILED=$((DEPRECATED_FAILED + 1))
        continue
    fi
    
    log_ok "$service_name: no deprecated patterns found"
done

echo ""

# Test 4: Check for consistency
echo "Test 4: Check for consistency"
echo "------------------------------"

CONSISTENCY_ISSUES=0

for service in "${SERVICE_FILES[@]}"; do
    service_name=$(basename "$service")
    
    # Check if services that use Python scripts have WorkingDirectory set
    if grep -q "python3.*apps/" "$service" || grep -q "python3.*services/" "$service"; then
        if ! grep -q "^WorkingDirectory=" "$service"; then
            log_warn "$service_name: Python app/service without WorkingDirectory"
            CONSISTENCY_ISSUES=$((CONSISTENCY_ISSUES + 1))
        else
            log_ok "$service_name: has WorkingDirectory"
        fi
    else
        log_ok "$service_name: no Python app/service paths"
    fi
done

echo ""

# Summary
echo "Test Summary"
echo "============"
echo "Total service files: ${#SERVICE_FILES[@]}"
echo "Verify failures: $VERIFY_FAILED"
echo "Path validation failures: $PATH_FAILED"
echo "Deprecated pattern failures: $DEPRECATED_FAILED"
echo "Consistency issues (warnings): $CONSISTENCY_ISSUES"
echo ""

TOTAL_FAILURES=$((VERIFY_FAILED + PATH_FAILED + DEPRECATED_FAILED))

if [[ $TOTAL_FAILURES -eq 0 ]]; then
    log_ok "All tests passed!"
    if [[ $CONSISTENCY_ISSUES -gt 0 ]]; then
        log_warn "Note: $CONSISTENCY_ISSUES consistency warnings found (not failures)"
    fi
    exit 0
else
    log_error "Tests failed with $TOTAL_FAILURES error(s)"
    exit 1
fi
