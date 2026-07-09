#!/bin/bash
# File manipulation utilities
# Used across multiple ETL scripts
# TODO: this has grown over the years, should be refactored (or replaced
#       outright when we port the pipeline to Python on GCP)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/logging.sh"

# Check if file exists and is not empty
check_file() {
    local filepath="$1"
    if [[ ! -f "$filepath" ]]; then
        log_error "File not found: $filepath"
        return 1
    fi
    if [[ ! -s "$filepath" ]]; then
        log_warn "File is empty: $filepath"
        return 2
    fi
    return 0
}

# Count lines in a file (excluding header)
count_data_rows() {
    local filepath="$1"
    local has_header="${2:-true}"

    if [[ "$has_header" == "true" ]]; then
        echo $(( $(wc -l < "$filepath") - 1 ))
    else
        wc -l < "$filepath"
    fi
}

# Create dated archive copy
archive_file() {
    local filepath="$1"
    local archive_dir="${2:-${DATA_ARCHIVE_DIR:-/opt/albertsons/etl/data/archive}}"
    local datestamp=$(date +%Y%m%d_%H%M%S)
    local filename=$(basename "$filepath")
    local archive_path="${archive_dir}/${filename%.*}_${datestamp}.${filename##*.}"

    mkdir -p "$archive_dir"
    cp "$filepath" "$archive_path"

    if [[ $? -eq 0 ]]; then
        log_info "Archived: $filepath -> $archive_path"
        echo "$archive_path"
    else
        log_error "Failed to archive: $filepath"
        return 1
    fi
}

# Move file with retry
move_file() {
    local src="$1"
    local dest="$2"
    local retries="${3:-3}"

    local attempt=0
    while [[ $attempt -lt $retries ]]; do
        mv "$src" "$dest" 2>/dev/null
        if [[ $? -eq 0 ]]; then
            log_info "Moved: $src -> $dest"
            return 0
        fi
        attempt=$((attempt + 1))
        log_warn "Move failed (attempt ${attempt}/${retries}): $src -> $dest"
        sleep 2
    done

    log_error "Failed to move file after ${retries} attempts: $src"
    return 1
}

# Validate CSV structure
validate_csv() {
    local filepath="$1"
    local expected_cols="$2"
    local delimiter="${3:-,}"

    check_file "$filepath" || return 1

    local header_cols=$(head -1 "$filepath" | awk -F"$delimiter" '{print NF}')

    if [[ -n "$expected_cols" ]] && [[ "$header_cols" -ne "$expected_cols" ]]; then
        log_error "CSV column mismatch: expected ${expected_cols}, got ${header_cols} in $filepath"
        return 1
    fi

    # Check for consistent column count (sample first 100 rows)
    local inconsistent=$(head -100 "$filepath" | awk -F"$delimiter" -v cols="$header_cols" 'NF != cols {print NR}')
    if [[ -n "$inconsistent" ]]; then
        log_warn "Inconsistent column counts at lines: $inconsistent"
        return 2
    fi

    log_info "CSV validation passed: $filepath (${header_cols} columns)"
    return 0
}

# Compress a file with gzip in place (keeps original by default)
gzip_file() {
    local filepath="$1"
    local keep="${2:-true}"

    check_file "$filepath" || return 1

    if [[ "$keep" == "true" ]]; then
        gzip -c "$filepath" > "${filepath}.gz"
    else
        gzip -f "$filepath"
    fi

    if [[ $? -eq 0 ]]; then
        log_info "Compressed: ${filepath} -> ${filepath}.gz"
    else
        log_error "gzip failed for: ${filepath}"
        return 1
    fi
}

# Get file size in human readable format
file_size_hr() {
    local filepath="$1"
    if [[ -f "$filepath" ]]; then
        ls -lh "$filepath" | awk '{print $5}'
    else
        echo "0"
    fi
}
