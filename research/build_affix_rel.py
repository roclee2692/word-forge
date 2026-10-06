"""词缀/词根可信度：在 MorphoLex 里，某个串出现在某个位置时，它真是语素的比例。

前缀 p：以 p 开头的词里，p 后面真有语素边界的比例。
后缀 s：以 s 结尾的词里，s 前面真有语素边界的比例。
词根 r：词中出现 r 的词里，r 两端都是语素边界（或词首尾）的比例。
边界允许 ±1（ious/ous）。ielts1000 的全部 1000 个词都排除，不参与统计。
来源：Sánchez-Gutiérrez et al. (2017) MorphoLex-en, Behavior Research Methods。导出的只是每个串一个比例。
"""
import pickle, json, os
from common import CACHE, DATA, HERE
from e3_morph import gold_morphs, project
import wordseg as WS

ml = pickle.load(open(os.path.join(CACHE, 'morpholex.pkl'), 'rb'))
excl = {x['word'] for x in json.load(open(os.path.join(DATA, 'ielts1000.json')))}
items = []
for w, seg in ml.items():
    if w in excl or not w.isalpha(): continue
    items.append((w, project(gold_morphs(seg), w)))
near = lambda x, E: any(abs(x - e) <= 1 for e in E)
rel = {}
for m, senses in WS.MORPH.items():
    for kind, _ in senses:
        hit = tot = 0
        for w, gold in items:
            if len(w) < len(m) + 3: continue
            E = gold | {0, len(w)}
            if kind == 'p' and w.startswith(m):
                tot += 1; hit += near(len(m), gold)
            elif kind == 's' and w.endswith(m):
                tot += 1; hit += near(len(w) - len(m), gold)
            elif kind == 'r':
                k = w.find(m)
                if k >= 0: tot += 1; hit += near(k, E) and near(k + len(m), E)
        if tot >= 5: rel[f'{kind}:{m}'] = [round(hit / tot, 3), tot]
out = os.path.join(HERE, '..', 'scripts', 'affix_rel.json')
json.dump(rel, open(out, 'w'), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
print(len(rel), 'entries →', out)
for k in ['s:ance', 'p:ac', 'r:dent', 's:ment', 's:ity', 'p:sus', 'r:cept', 's:ous', 'p:re', 'p:em', 'r:secu', 's:ant', 'p:anti']:
    print(' ', k, rel.get(k))
