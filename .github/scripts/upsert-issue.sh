#!/usr/bin/env bash
# Open the one issue carrying LABEL, or replace its body if it is already open.
#
#   upsert-issue.sh LABEL TITLE BODY_FILE
#
# Needs GH_TOKEN with issues: write, and actions: write to start the repair.
#
# A new issue starts repair.yml. An issue that is already open does not: the
# check runs again every day, and one proposed fix per issue is enough. To ask
# for another, run the Repair workflow by hand with the issue number.
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
  # Issues and labels created with GITHUB_TOKEN do not trigger workflows, so
  # the repair has to be started explicitly.
  gh workflow run repair.yml -f issue="$number" \
    || echo "::warning::could not start repair.yml for #$number; run it by hand"
fi
