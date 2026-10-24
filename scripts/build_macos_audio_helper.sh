#!/bin/bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
app_dir="$repo_root/.build/TalkTrackAudioCapture.app"
contents_dir="$app_dir/Contents"
binary="$contents_dir/MacOS/TalkTrackAudioCapture"
source_file="$repo_root/app/platform/macos/system_audio_tap.swift"
plist_template="$repo_root/app/platform/macos/Info.plist"

mkdir -p "$contents_dir/MacOS"
if ! cmp -s "$plist_template" "$contents_dir/Info.plist"; then
    cp "$plist_template" "$contents_dir/Info.plist"
fi

if [ -x "$binary" ] && [ "$binary" -nt "$source_file" ] \
        && [ "$binary" -nt "$contents_dir/Info.plist" ]; then
    printf 'Native system-audio helper is up to date.\n'
    exit 0
fi

host_arch="$(uname -m)"
temporary_binary="$binary.tmp"
swiftc -O -target "$host_arch-apple-macosx14.4" \
    -framework CoreAudio -framework Foundation \
    "$source_file" -o "$temporary_binary"
mv "$temporary_binary" "$binary"
chmod +x "$binary"
codesign --force --deep --sign - "$app_dir" >/dev/null
printf 'Built native system-audio helper: %s\n' "$binary"
