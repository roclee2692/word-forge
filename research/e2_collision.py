"""E2：碰撞检测（D）能不能列出学习者真实混淆的那个词？

真值：FCE 里“把一个真词错写成另一个真词”的编辑（lose ↔ loose，quite ↔ quiet）。
过滤：两个词都在 CMUdict、长度 ≥ 4、编辑距离 ≤ 2；去掉屈折变化（+s/+ed/+ing…）和英美拼法差异；
      只保留实词层面的类型（R:OTHER / R:NOUN / R:VERB / R:ADJ / R:ADV / R:SPELL）；
      写成的词 zipf ≥ 3（否则是错拼，归 E0）；形近 = 只差一个字母，或读音几乎相同（音素距离 ≤ 1）。
      这两条是看过 dev 的噪声（wich、have←make）后加的，之后不再改。
指标：召回率 = 学习词 c 的碰撞栏里，列出了学习者实际写成的 o 的比例（按词对去重）。
"""
import sys, argparse
from collections import Counter
from common import *
import wordseg as WS

KEEP = {'R:OTHER', 'R:NOUN', 'R:VERB', 'R:ADJ', 'R:ADV', 'R:SPELL'}
UKUS = [('our', 'or'), ('re', 'er'), ('ise', 'ize'), ('ll', 'l'), ('yse', 'yze'), ('ence', 'ense'), ('ogue', 'og')]

def inflection(a, b):
    for x, y in ((a, b), (b, a)):
        for suf in ('s', 'es', 'd', 'ed', 'ing', 'er', 'ly', 'r', 'n'):
            if y == x + suf or (x.endswith('e') and y == x[:-1] + suf) or (x.endswith('y') and y == x[:-1] + 'i' + suf): return True
    return False

def ukus(a, b):
    for x, y in UKUS:
        if a.replace(x, y) == b or b.replace(x, y) == a: return True
    return False

def ph_close(a, b, cmu):   # 读音几乎相同：任一读音组合的音素编辑距离 ≤ 1
    return min(WS.ph_dist(x, y) for x in cmu[a] for y in cmu[b]) <= 1

def load_pairs(cmu, zipf):
    pairs = Counter()
    for part in ('train', 'dev', 'test'):
        src = None
        for line in open(os.path.join(DATA, 'fce', 'm2', f'fce.{part}.gold.bea19.m2'), encoding='utf-8'):
            if line.startswith('S '): src = line[2:].split()
            elif line.startswith('A '):
                span, typ, cor = line[2:].split('|||')[:3]; a, b = map(int, span.split())
                if typ not in KEEP or b - a != 1 or ' ' in cor or not cor: continue
                o, c = src[a].lower(), cor.lower()
                if o == c or not (o.isalpha() and c.isalpha()) or o not in cmu or c not in cmu: continue
                if min(len(o), len(c)) < 4 or damerau(c, o)[len(c)][len(o)] > 2: continue
                if inflection(o, c) or ukus(o, c): continue
                if zipf(o) < 3.0: continue                                   # 写成的必须是常见真词，否则是 E0 的错拼
                if damerau(c, o)[len(c)][len(o)] != 1 and not ph_close(c, o, cmu): continue   # 形近：差一个字母，或读音几乎相同
                pairs[(c, o)] += 1
    return pairs

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--split', default='dev'); ap.add_argument('--show', type=int, default=0)
    a = ap.parse_args(); allowed(a.split)
    import cmudict; cmu = cmudict.dict()
    import wordfreq
    pairs = {p: n for p, n in load_pairs(cmu, lambda w: wordfreq.zipf_frequency(w, 'en')).items() if split_of(p[0]) == a.split}
    words, cmu2, foreign = WS.load()
    ac = WS.AC(sorted(set(words) | set(WS.MORPH) | set(foreign)))
    hit = miss = 0; misses = []; sizes = []
    cache = {}
    for (c, o), n in sorted(pairs.items(), key=lambda x: -x[1]):
        if c not in cache:
            r = WS.analyze(c, words, cmu2, ac, 3, foreign)
            cache[c] = r['collide']; sizes.append(len(r['collide']))
        if any(f' {o}（' in s or f'↔ {o}' in s or f' {o} ' in s for s in cache[c]): hit += 1
        else: miss += 1; misses.append((c, o, n, words.get(o, 0)))
    print(f'split={a.split}  词对={len(pairs)}  召回 {hit}/{hit + miss} = {hit / max(1, hit + miss):.2f}  平均每词列出 {sum(sizes) / max(1, len(sizes)):.1f} 个')
    for c, o, n, z in misses[:a.show]: print(f'  漏：{c} ← {o}（{n} 次，{o} zipf {z:.1f}）')
