#!/bin/bash
set -e

# update_all_packages.sh - Update Poetry dependencies to latest compatible versions

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$SCRIPT_DIR}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_skip() {
    echo -e "${BLUE}[SKIP]${NC} $1"
}

update_module() {
    local module_path=$1
    local module_name=$(basename "$module_path")
    
    log_info "Processing module: $module_name"
    
    cd "$module_path"
    
    # Check if pyproject.toml exists
    if [ ! -f "pyproject.toml" ]; then
        log_warn "No pyproject.toml found in $module_path, skipping"
        return 0
    fi
    
    # First try: safe update within existing constraints
    log_info "Running poetry update (within existing constraints)..."
    if poetry update 2>&1 | tee /tmp/poetry_update.log; then
        log_info "Successfully updated packages within constraints in $module_name"
    else
        log_warn "Some packages failed to update within constraints in $module_name"
    fi
    
    # Check for outdated packages after update
    log_info "Checking for remaining outdated packages..."
    local outdated=$(poetry show --outdated 2>/dev/null || echo "")
    
    if [ -z "$outdated" ]; then
        log_info "All packages up to date in $module_name"
        cd "$PROJECT_ROOT"
        return 0
    fi
    
    log_info "Attempting to update remaining outdated packages to @latest..."
    echo "$outdated"
    
    # Extract package names
    local packages=$(echo "$outdated" | awk '{print $1}')
    
    local updated=()
    local failed=()
    
    # Try to update each package individually
    for package in $packages; do
        log_info "Attempting to update $package to latest..."
        
        # Try updating this package to @latest
        if poetry add "${package}@latest" 2>&1 | tee /tmp/poetry_add_${package}.log; then
            log_info "✓ Successfully updated $package to latest"
            updated+=("$package")
        else
            log_skip "✗ Could not update $package to latest (constraint conflict or dependency issue)"
            failed+=("$package")
        fi
    done
    
    # Report results for this module
    echo ""
    log_info "Update summary for $module_name:"
    if [ ${#updated[@]} -gt 0 ]; then
        echo -e "${GREEN}  Updated to @latest: ${updated[*]}${NC}"
    fi
    if [ ${#failed[@]} -gt 0 ]; then
        echo -e "${YELLOW}  Skipped (manual review needed): ${failed[*]}${NC}"
    fi
    
    cd "$PROJECT_ROOT"
    
    # Return success even if some packages failed
    return 0
}

main() {
    log_info "Starting package updates across all modules..."
    log_info "Project root: $PROJECT_ROOT"
    echo ""
    
    # Find all directories with pyproject.toml
    local modules=()
    while IFS= read -r -d '' file; do
        module_dir=$(dirname "$file")
        modules+=("$module_dir")
    done < <(find "$PROJECT_ROOT" -name "pyproject.toml" -type f -print0)
    
    if [ ${#modules[@]} -eq 0 ]; then
        log_error "No modules with pyproject.toml found in $PROJECT_ROOT"
        exit 1
    fi
    
    log_info "Found ${#modules[@]} module(s) to process"
    echo ""
    
    local all_updated=()
    local all_failed=()
    
    for module in "${modules[@]}"; do
        update_module "$module"
        echo "================================"
        echo ""
    done
    
    # Global summary
    log_info "=== FINAL SUMMARY ==="
    log_info "Processed ${#modules[@]} module(s)"
    log_info "Strategy: Update within constraints, then attempt @latest for remaining outdated packages"
    log_warn "Packages that couldn't be updated may require manual review for:"
    echo "  - Major version bumps with breaking changes"
    echo "  - Conflicting transitive dependencies"
    echo "  - Incompatible Python version requirements"
    echo ""
    log_info "Next steps:"
    echo "  1. Run tests: pytest (or your test command)"
    echo "  2. Review skipped packages: poetry show --outdated"
    echo "  3. Manually update problematic packages if needed"
}

# Parse arguments
DRY_RUN=false
while getopts "dh" opt; do
    case $opt in
        d)
            DRY_RUN=true
            log_info "=== DRY RUN MODE - No changes will be made ==="
            echo ""
            ;;
        h)
            echo "Usage: $0 [-d] [-h]"
            echo ""
            echo "Update all Poetry dependencies across modules"
            echo ""
            echo "Options:"
            echo "  -d    Dry run (show outdated packages without updating)"
            echo "  -h    Show this help message"
            echo ""
            echo "Environment variables:"
            echo "  PROJECT_ROOT    Root directory to search for modules (default: script directory)"
            exit 0
            ;;
        \?)
            log_error "Invalid option. Use -h for help."
            exit 1
            ;;
    esac
done

if [ "$DRY_RUN" = true ]; then
    # Just show what would be updated
    while IFS= read -r -d '' file; do
        module_dir=$(dirname "$file")
        module_name=$(basename "$module_dir")
        echo ""
        log_info "Module: $module_name ($module_dir)"
        cd "$module_dir"
        
        local outdated=$(poetry show --outdated 2>/dev/null || echo "")
        if [ -z "$outdated" ]; then
            log_info "  No outdated packages"
        else
            echo "$outdated"
        fi
        
        cd "$PROJECT_ROOT"
    done < <(find "$PROJECT_ROOT" -name "pyproject.toml" -type f -print0)
else
    main
fi