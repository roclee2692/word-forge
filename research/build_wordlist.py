"""E3 词表：1000 个“较难”的雅思词（规则在看结果之前写死）。
来源：KyleBing/english-vocabulary 雅思词表（BSD-3）。
条件：纯字母单词、在 CMUdict 里、长度 ≥ 7、wordfreq zipf ≤ 3.8；满足条件的词用种子 42 随机抽 1000 个。
切分沿用 common.split_of（按词的 md5），所以 hidden 词在整个研究里一致。
"""
import json, random, os
import wordfreq, cmudict
from common import DATA, split_of
cmu = cmudict.dict()
rows = {}
for line in open(os.path.join(DATA, 'ielts_simple.txt'), encoding='utf-8'):
    p = line.rstrip('\n').split('\t')
    w = p[0].strip()
    if w.isalpha() and w.isascii() and w.islower() and len(w) >= 7 and w in cmu and wordfreq.zipf_frequency(w, 'en') <= 3.8:
        rows[w] = p[1] if len(p) > 1 else ''
pool = sorted(rows)
random.Random(42).shuffle(pool)
pick = sorted(pool[:1000])
json.dump([{'word': w, 'gloss': rows[w], 'split': split_of(w)} for w in pick],
          open(os.path.join(DATA, 'ielts1000.json'), 'w'), ensure_ascii=False, indent=0)
from collections import Counter
print('pool', len(pool), 'picked', len(pick), Counter(split_of(w) for w in pick))
