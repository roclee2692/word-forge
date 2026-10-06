"""把“读音 → 拼写”统计表导出给 wordseg 用（只来自 CMUdict + wordfreq，不含任何学习者语料）。"""
import json, os
from e0_spelling import get_cmu, p2g_table
cnt, tot = p2g_table(get_cmu())
out = {}
for (key, g), c in cnt.items(): out.setdefault(key, {})[g] = int(c)
path = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'p2g.json')
json.dump(out, open(path, 'w'), ensure_ascii=False, separators=(',', ':'), sort_keys=True)
print(len(out), 'keys,', os.path.getsize(path), 'bytes')
