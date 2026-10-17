#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
git clone --quiet --depth 1 https://github.com/nanaism/yomiyasu.git "$tmp/source"
test -f "$tmp/source/skills/yomiyasu/SKILL.md"
rm -rf .agents/skills/yomiyasu
mkdir -p .agents/skills/yomiyasu
cp -R "$tmp/source/skills/yomiyasu/." .agents/skills/yomiyasu/
echo "Updated yomiyasu to $(git -C "$tmp/source" rev-parse HEAD)"
echo "Review the diff and update docs/yomiyasu.md before committing."
