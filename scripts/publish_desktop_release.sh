#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: publish_desktop_release.sh <tag> <release-dir>" >&2
  exit 2
fi

tag="$1"
release_dir="$2"
if [[ ! "$tag" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then
  echo "Unsafe desktop release tag: $tag" >&2
  exit 2
fi
if [[ ! -d "$release_dir" ]]; then
  echo "Desktop release artifact directory is missing: $release_dir" >&2
  exit 2
fi

version="${tag#v}"
expected_names=(
  "ModWatcherAgent-$version-win-x64-portable.zip"
  "ModWatcherAgent-$version-win-x64-portable.zip.sha256"
)
assets=()
for name in "${expected_names[@]}"; do
  asset="$release_dir/$name"
  if [[ ! -f "$asset" ]]; then
    echo "Desktop release asset is missing: $asset" >&2
    exit 2
  fi
  assets+=("$asset")
done
mapfile -t actual_names < <(find "$release_dir" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort)
mapfile -t expected_names_sorted < <(printf '%s\n' "${expected_names[@]}" | sort)
if ! diff -u \
  <(printf '%s\n' "${expected_names_sorted[@]}") \
  <(printf '%s\n' "${actual_names[@]}"); then
  echo "Desktop release directory must contain exactly the two expected portable assets." >&2
  exit 2
fi

if ! gh release view "$tag" >/dev/null 2>&1; then
  gh release create "$tag" "${assets[@]}" \
    --verify-tag \
    --generate-notes \
    --title "Mod Watcher Agent $tag"
  exit 0
fi

if ! remote_inventory="$(
  gh release view "$tag" --json assets --jq '.assets[].name'
)"; then
  echo "Unable to query remote release assets for immutable verification." >&2
  exit 1
fi
remote_names=()
while IFS= read -r remote_name; do
  if [[ -n "$remote_name" ]]; then
    remote_names+=("$remote_name")
  fi
done <<< "$remote_inventory"
mapfile -t remote_names_sorted < <(printf '%s\n' "${remote_names[@]}" | sort)
if ! diff -u \
  <(printf '%s\n' "${expected_names_sorted[@]}") \
  <(printf '%s\n' "${remote_names_sorted[@]}"); then
  echo "Existing release assets do not match the exact immutable asset set." >&2
  exit 1
fi

download_root="$(mktemp -d)"
trap 'rm -rf -- "$download_root"' EXIT
for name in "${expected_names[@]}"; do
  if ! gh release download "$tag" \
    --pattern "$name" \
    --dir "$download_root" >/dev/null 2>&1; then
    echo "Unable to download existing release asset for verification: $name" >&2
    exit 1
  fi
done

remote_artifact="$download_root/${expected_names[0]}"
remote_checksum="$download_root/${expected_names[1]}"
if [[ ! -f "$remote_artifact" || ! -f "$remote_checksum" ]]; then
  echo "Existing release asset download is incomplete." >&2
  exit 1
fi

hash_line="$(tr -d '\r' < "$remote_checksum")"
digest="${hash_line%%  *}"
referenced_name="${hash_line#*  }"
if [[ "$digest" == "$hash_line" ||
      ! "$digest" =~ ^[0-9a-f]{64}$ ||
      "$referenced_name" != "${expected_names[0]}" ]]; then
  echo "Existing release checksum metadata is invalid." >&2
  exit 1
fi
if ! (
  cd "$download_root"
  printf '%s  %s\n' "$digest" "$referenced_name" |
    sha256sum --check --strict - >/dev/null
); then
  echo "Existing release checksum verification failed." >&2
  exit 1
fi

echo "Existing immutable release assets verified: $tag"
