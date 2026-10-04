#!/bin/bash
# Debug helper — run extract_enhanced.py on a single service for a given JIRA ID.
# Replace the variables below with your own values.
cd /path/to/workspace
REPO=.service-repos/my-service
DIFF=/tmp/debug.diff
JIRA_ID=PROJ-1234
rm -f $DIFF
git -C $REPO log --all --extended-regexp --grep="$JIRA_ID" --pretty=%H 2>/dev/null | while read c; do
  git -C $REPO show $c >> $DIFF 2>/dev/null
done
echo "Diff lines: $(wc -l < $DIFF)"
python3 scripts/lib/extract_enhanced.py \
  --service my-service \
  --jira $JIRA_ID \
  --diff $DIFF \
  --out /tmp/debug_out 2>&1
echo "Exit: $?"
ls /tmp/debug_out/
