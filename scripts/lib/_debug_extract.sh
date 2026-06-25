#!/bin/bash
cd /mnt/c/Users/anl/qa-workspace
REPO=.service-repos/dtb-iconography-service
DIFF=/tmp/ico.diff
rm -f $DIFF
git -C $REPO log --all --extended-regexp --grep="DTB-17595" --pretty=%H 2>/dev/null | while read c; do
  git -C $REPO show $c >> $DIFF 2>/dev/null
done
echo "Diff lines: $(wc -l < $DIFF)"
python3 scripts/lib/extract_enhanced.py \
  --service dtb-iconography-service \
  --jira DTB-17595 \
  --diff $DIFF \
  --out /tmp/ico_out 2>&1
echo "Exit: $?"
ls /tmp/ico_out/
