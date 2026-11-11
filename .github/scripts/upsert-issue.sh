#!/usr/bin/env bash
# Open the one issue carrying LABEL, or replace its body if it is already open.
#
#   upsert-issue.sh LABEL TITLE BODY_FILE
#
# Needs GH_TOKEN with issues: write.
set -euo pipefail

label=$1
title=$2
body_file=$3

# GitHub rejects issue bodies over 65536 characters.
if [ "$(wc -c < "$body_file")" -gt 60000 ]; then
  head -c 60000 "$body_file" > "$body_file.cut"
  printf '\n```\n\n_Report cut at 60000 bytes. The workflow run has the rest._\n' >> "$body_file.cut"
  mv "$body_file.cut" "$body_file"
fi

gh label create "$label" --color D93F0B --description "Opened by a scheduled check" 2> /dev/null || true

number=$(gh issue list --label "$label" --state open --limit 1 --json number --jq '.[0].number // empty')
if [ -n "$number" ]; then
  gh issue edit "$number" --body-file "$body_file" > /dev/null
  echo "Updated issue #$number"
else
  url=$(gh issue create --title "$title" --label "$label" --body-file "$body_file")
  number=${url##*/}
  echo "Opened issue #$number"
fi
