#!/usr/bin/env bash
# scripts/config-init.sh
# Initialize configuration files from templates
# Copies *.toml.example to *.toml only if the target file doesn't exist

set -euo pipefail

# Determine the repository root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_DIR="${REPO_ROOT}/config"

# Color output helpers
if [[ -t 1 ]]; then
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m' # No Color
else
    GREEN=''
    YELLOW=''
    BLUE=''
    NC=''
fi

log_info() {
    echo -e "${BLUE}[config-init]${NC} $*"
}

log_success() {
    echo -e "${GREEN}[config-init]${NC} $*"
}

log_skip() {
    echo -e "${YELLOW}[config-init]${NC} $*"
}

# Check if config directory exists
if [[ ! -d "${CONFIG_DIR}" ]]; then
    echo "Error: Config directory not found: ${CONFIG_DIR}" >&2
    exit 1
fi

log_info "Scanning for *.toml.example files in ${CONFIG_DIR}..."

# Counter for statistics
TOTAL=0
CREATED=0
SKIPPED=0

# Find all .toml.example files and process them
while IFS= read -r -d '' example_file; do
    TOTAL=$((TOTAL + 1))
    
    # Get the base filename without .example extension
    target_file="${example_file%.example}"
    
    # Get relative path for display
    rel_example="${example_file#${CONFIG_DIR}/}"
    rel_target="${target_file#${CONFIG_DIR}/}"
    
    if [[ -f "${target_file}" ]]; then
        log_skip "${rel_target} already exists, skipping."
        SKIPPED=$((SKIPPED + 1))
    else
        cp "${example_file}" "${target_file}"
        log_success "Created ${rel_target} from ${rel_example}"
        CREATED=$((CREATED + 1))
    fi
done < <(find "${CONFIG_DIR}" -maxdepth 1 -name "*.toml.example" -type f -print0 | sort -z)

# Summary
echo ""
log_info "Summary:"
log_info "  Total templates found: ${TOTAL}"
log_success "  Files created: ${CREATED}"
log_skip "  Files skipped (already exist): ${SKIPPED}"

if [[ ${CREATED} -gt 0 ]]; then
    echo ""
    log_info "Don't forget to review and customize the newly created config files!"
fi

exit 0
