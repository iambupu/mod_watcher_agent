#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "Usage: publish_desktop_release.sh <tag> <notes-file> <release-dir>" >&2
  exit 2
fi

tag="$1"
notes_file="$2"
release_dir="$3"
if [[ ! "$tag" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then
  echo "Unsafe desktop release tag: $tag" >&2
  exit 2
fi
if [[ ! -f "$notes_file" ]]; then
  echo "Desktop release notes file is missing: $notes_file" >&2
  exit 2
fi
if [[ ! -d "$release_dir" ]]; then
  echo "Desktop release artifact directory is missing: $release_dir" >&2
  exit 2
fi

required_notes=(
  "WebView2"
  '%LOCALAPPDATA%\ModWatcherAgent'
  "卸载"
  "保留"
  "备份"
  "NotSigned"
  "已知限制"
)
for required in "${required_notes[@]}"; do
  if ! grep -Fq -- "$required" "$notes_file"; then
    echo "Desktop release notes are missing required guidance: $required" >&2
    exit 2
  fi
done

version="${tag#v}"
expected_names=(
  "ModWatcherAgent-$version-win-x64-portable.zip"
  "ModWatcherAgent-$version-win-x64-portable.zip.sha256"
  "ModWatcherAgent-Setup-$version-win-x64.exe"
  "ModWatcherAgent-Setup-$version-win-x64.exe.sha256"
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
  echo "Desktop release directory must contain exactly the expected four assets." >&2
  exit 2
fi

if ! gh release view "$tag" >/dev/null 2>&1; then
  gh release create "$tag" "${assets[@]}" \
    --verify-tag \
    --notes-file "$notes_file" \
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
for remote_name in "${remote_names[@]}"; do
  expected=false
  for expected_name in "${expected_names[@]}"; do
    if [[ "$remote_name" == "$expected_name" ]]; then
      expected=true
      break
    fi
  done
  if [[ "$expected" != true ]]; then
    echo "Unexpected remote release assets: $remote_name" >&2
    exit 1
  fi
done

download_root="$(mktemp -d)"
trap 'rm -rf -- "$download_root"' EXIT
missing_assets=()
for asset in "${assets[@]}"; do
  name="$(basename "$asset")"
  remote_exists=false
  for remote_name in "${remote_names[@]}"; do
    if [[ "$remote_name" == "$name" ]]; then
      remote_exists=true
      break
    fi
  done
  if [[ "$remote_exists" != true ]]; then
    missing_assets+=("$asset")
    continue
  fi
  asset_download_dir="$download_root/$name"
  mkdir -p "$asset_download_dir"
  if ! gh release download "$tag" \
    --pattern "$name" \
    --dir "$asset_download_dir" >/dev/null 2>&1; then
    echo "Unable to download existing release asset for verification: $name" >&2
    exit 1
  fi
  remote_asset="$asset_download_dir/$name"
  if [[ ! -f "$remote_asset" ]] || ! cmp -s -- "$asset" "$remote_asset"; then
    echo "Immutable release asset mismatch: $name" >&2
    exit 1
  fi
done

for asset in "${missing_assets[@]}"; do
  gh release upload "$tag" "$asset"
done

gh release edit "$tag" --notes-file "$notes_file"
