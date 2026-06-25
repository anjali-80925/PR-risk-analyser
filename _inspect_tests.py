import json
from pathlib import Path

ti = json.loads(Path('pr-analysis/DTB-17595/test_index.json').read_text(encoding='utf-8'))
tests = ti.get('tests', [])

files = sorted(set(t.get('file','') for t in tests))
print('ALL TEST FILES:')
for f in files:
    print(' ', f)
print()

print('SAMPLE TESTS (deduped tags):')
for t in tests[:5]:
    tags = list(dict.fromkeys(t.get('tags',[])))
    meaningful = [tg for tg in tags if tg not in ('fixtures','test','pages')]
    print('  FILE:', t['file'].split('\\')[-1])
    print('  CASE:', t['testCase'])
    print('  TAGS:', meaningful)
    print()
