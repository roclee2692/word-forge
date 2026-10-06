"""E0：wordseg 标出的拼写风险位，能不能预测学习者真实的出错位置？

真值：FCE（多国 ESOL 考生）的 R:SPELL 编辑，Birkbeck（母语者为主）作为第二人群。
任务：已知某人把词 w 拼错了，预测错在哪个字母上。
指标：位置级 AUC（每次拼错事件里，出错位置 = 正例，其余位置 = 负例），
      分 pooled（按事件加权）和 word-macro（每个词等权）两种。

用法：python e0_spelling.py [--split dev|val] [--models b0,vowel,...]
"""
import sys, os, math, json, pickle, argparse, random
from collections import Counter, defaultdict
import numpy as np
from sklearn.metrics import roc_auc_score
from common import *
import wordseg as WS

def get_cmu():
    import cmudict; return cmudict.dict()

def best_segs(w, cmu):   # 与 wordseg.analyze 相同：选拼写最规则的读音；都对不齐返回 None
    al = [s for s in (WS.align(w, p) for p in cmu[w]) if s]
    return min(al, key=lambda x: sum({'regular': 0, 'variant': .3, 'silent': .5}.get(s['tag'], 2) for s in x)) if al else None

# ---------- 读音 → 拼写 的条件分布（从高频词表里对齐统计） ----------
def p2g_table(cmu):
    path = os.path.join(CACHE, 'p2g.pkl')
    if os.path.exists(path): return pickle.load(open(path, 'rb'))
    import wordfreq
    cnt, tot = Counter(), Counter()
    for w in wordfreq.top_n_list('en', 30000):
        if not (w.isalpha() and w.isascii() and w in cmu and len(w) >= 2): continue
        if split_of(w) == 'hidden': continue          # 统计表也不碰 hidden 词
        wt = 1.0                                       # 按词型计数（不按词频），学习者面对的是“这个音有几种写法”
        for s in (best_segs(w, cmu) or []):
            key = ' '.join(p.rstrip('012') if p.rstrip('012') not in WS.VOWEL_PH else p for p in s['ph'])
            cnt[(key, s['g'])] += wt; tot[key] += wt
    pickle.dump((cnt, tot), open(path, 'wb')); return cnt, tot

# ---------- 竞争拼法压力：同一个音的其他写法，有多少概率恰好在这个字母上和它不同 ----------
_COMP = {}
def comp_vec(key, g, p2g):
    if (key, g) in _COMP: return _COMP[(key, g)]
    cnt, tot = p2g
    v = [0.0] * len(g)
    if tot[key]:
        for (k2, g2), c in cnt.items():
            if k2 != key or g2 == g: continue
            for i, m in enumerate(error_positions(g, g2)): v[i] += c / tot[key] * min(m, 1.0)
    _COMP[(key, g)] = v; return v

# ---------- 每个字母的特征 ----------
def letter_feats(w, cmu, p2g):
    cnt, tot = p2g
    segs = best_segs(w, cmu)
    if segs is None: return None
    rows = []
    for s in segs:
        key = ' '.join(p.rstrip('012') if p.rstrip('012') not in WS.VOWEL_PH else p for p in s['ph'])
        p = (cnt[(key, s['g'])] + 0.5) / (tot[key] + 5)
        schwa = any(x in ('AH0', 'IH0', 'ER0') for x in s['ph']) and WS.is_vowel_g(s['g'])
        dbl = len(s['g']) == 2 and s['g'][0] == s['g'][1]
        cv = comp_vec(key, s['g'], p2g)
        for k in range(s['start'], s['end']):
            rows.append({
                'comp': cv[k - s['start']],
                'b0': float(s['tag'] != 'regular' or schwa),
                'vowel': float(w[k] in 'aeiouy'),
                'p2g': -math.log(p),                       # 听到这个音、写出这个字母组合的意外程度
                'silent': float(s['tag'] in ('silent', 'irregular-silent')),
                'schwa': float(schwa),
                'dbl': float(dbl),
                'dbl2': float(dbl and k == s['end'] - 1),   # 双写里的第二个字母（漏写通常记在它上面）
                'irr': float(s['tag'] in ('irregular',)),
                'relpos': k / max(1, len(w) - 1),
                'edge': float(k == 0 or k == len(w) - 1),
                'unstressed_v': float(WS.is_vowel_g(s['g']) and not any(x.endswith('1') for x in s['ph'])),
            })
    return rows

FEATS = ['p2g', 'silent', 'schwa', 'dbl', 'dbl2', 'irr', 'vowel', 'relpos', 'edge', 'unstressed_v']

def build(split, cmu, p2g):
    allowed(split)
    fce, expo = load_fce()
    ev = clean_events(fce + load_birkbeck(), cmu)
    ev = [e for e in ev if split_of(e[0]) == split]
    cache = {}
    X, y, grp, src = [], [], [], []
    for n, (w, m, s) in enumerate(ev):
        if w not in cache: cache[w] = letter_feats(w, cmu, p2g)
        if cache[w] is None: continue
        mass = error_positions(w, m)
        for k, f in enumerate(cache[w]):
            X.append(f); y.append(float(mass[k] > 0)); grp.append((n, w)); src.append(s)
    return X, np.array(y), grp, np.array(src), expo

def auc_report(score, y, grp, src):
    out = {}
    for name, mask in (('fce', src == 'fce'), ('birkbeck', src == 'birkbeck'), ('all', np.ones_like(y, bool))):
        if mask.sum() == 0 or len(set(y[mask])) < 2: continue
        pooled = roc_auc_score(y[mask], score[mask])
        by = defaultdict(list)                                     # word-macro：同一个词的所有事件合起来算一次 AUC
        for i in np.where(mask)[0]: by[grp[i][1]].append(i)
        macro = [roc_auc_score(y[ix], score[ix]) for ix in by.values() if len(set(y[ix])) == 2 and len(set(score[ix])) > 1]
        out[name] = (round(pooled, 3), round(float(np.mean(macro)), 3) if macro else None, int(mask.sum()), len(by))
    return out

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--split', default='dev'); a = ap.parse_args()
    cmu = get_cmu(); p2g = p2g_table(cmu)
    X, y, grp, src, _ = build(a.split, cmu, p2g)
    rng = np.random.default_rng(0)
    scores = {
        'random': rng.random(len(y)),
        'vowel': np.array([f['vowel'] for f in X]),
        'b0_wordseg': np.array([f['b0'] for f in X]),
        'p2g': np.array([f['p2g'] for f in X]),
    }
    print(f'split={a.split}  instances={len(y)}  positives={int(y.sum())}')
    for k, s in scores.items():
        print(f'{k:12s}', auc_report(s, y, grp, src))
