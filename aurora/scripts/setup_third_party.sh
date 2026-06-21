#!/usr/bin/env bash
# Setup third-party dependencies for Aurora
# Reads third_party/MANIFEST.txt and clones/builds each dependency.
set -euo pipefail

AURORA_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
THIRD_PARTY_DIR="$AURORA_ROOT/third_party"
MANIFEST="$THIRD_PARTY_DIR/MANIFEST.txt"

if [[ ! -f "$MANIFEST" ]]; then
    echo "ERROR: Manifest not found at $MANIFEST"
    exit 1
fi

echo "=== Aurora third-party setup ==="
echo "Manifest: $MANIFEST"
echo

# Skip comment lines and empty lines
while IFS='|' read -r name repo ref license purpose; do
    # Trim whitespace
    name=$(echo "$name" | xargs)
    repo=$(echo "$repo" | xargs)
    ref=$(echo "$ref" | xargs)
    license=$(echo "$license" | xargs)
    purpose=$(echo "$purpose" | xargs)

    [[ -z "$name" || "$name" == \#* ]] && continue

    dest="$THIRD_PARTY_DIR/$name"
    echo "[$name] $purpose"
    echo "  repo: $repo"
    echo "  ref:  $ref"
    echo "  license: $license"

    if [[ -d "$dest" ]]; then
        echo "  -> already cloned at $dest, skipping clone"
    else
        echo "  -> cloning to $dest ..."
        git clone --depth 1 "$repo" "$dest"
        if [[ "$ref" != "master" && "$ref" != "main" ]]; then
            cd "$dest"
            git fetch --depth 1 origin "$ref"
            git checkout "$ref"
            cd -
        fi
    fi
    echo
done < "$MANIFEST"

# Build basis_universal
if [[ -d "$THIRD_PARTY_DIR/basis_universal" ]]; then
    echo "[basis_universal] Building..."
    cd "$THIRD_PARTY_DIR/basis_universal"
    if [[ ! -d build ]]; then
        mkdir -p build
    fi
    cd build
    cmake .. -DCMAKE_BUILD_TYPE=Release
    make -j"$(nproc)"
    echo "  -> basisu binary at: $THIRD_PARTY_DIR/basis_universal/bin/basisu"
    cd "$AURORA_ROOT"
fi

echo
echo "=== Setup complete ==="
