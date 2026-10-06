"""E3a：wordseg 说“这一块是前缀/词根/后缀”时，说得对不对？（真实度 Fidelity，不误导）

真值：MorphoLex-en 的人工语素切分（susceptible = <sus<(cept)>able>）。语素是规范形式，
      用编辑距离对齐把语素边界投影到实际拼写上（able ↔ ible）。
指标：
  claim_prec  第 1 名路径里，被标成语素的块，两端都落在真实语素边界上的比例
              只在 MorphoLex 切成 ≥2 个语素的词上算（MorphoLex 把 antidote 这类词当单语素，无法判对错）
  prec_tol    同上，但边界允许 ±1（audac|ious 与 audaci|ous 都算对）
  claims/word 平均每个词有几块被标成语素（防止靠少标刷准确率）
  morph_rec   真实的词内语素边界，被第 1 名路径切到的比例（参考，不作目标：熟词画面优先于语素）
"""
import re, json, pickle, argparse, os
from common import *
import wordseg as WS

TOK = re.compile(r'<([a-z]+)<|\(([a-z]+)\)|>([a-z]+)>')

def gold_morphs(seg):
    return [(a or b or c, 'p' if a else 'r' if b else 's') for a, b, c in TOK.findall(seg.lower())]

def project(morphs, word):
    """把规范语素串对齐到实际拼写，返回词内语素边界位置集合。"""
    canon = ''.join(m for m, _ in morphs); cuts = []; o = 0
    for m, _ in morphs[:-1]: o += len(m); cuts.append(o)
    n, k = len(canon), len(word)
    d = [[0] * (k + 1) for _ in range(n + 1)]
    for i in range(n + 1): d[i][0] = i
    for j in range(k + 1): d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, k + 1):
            d[i][j] = min(d[i-1][j] + 1, d[i][j-1] + 1, d[i-1][j-1] + (canon[i-1] != word[j-1]))
    mp = {n: k}; i, j = n, k                       # mp[规范串位置] = 拼写位置
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i-1][j-1] + (canon[i-1] != word[j-1]): i -= 1; j -= 1
        elif i > 0 and d[i][j] == d[i-1][j] + 1: i -= 1
        else: j -= 1
        mp.setdefault(i, j)
    return {mp[c] for c in cuts if 0 < mp[c] < k}

def load_eval(split):
    allowed(split)
    ml = pickle.load(open(os.path.join(CACHE, 'morpholex.pkl'), 'rb'))
    W = json.load(open(os.path.join(DATA, 'ielts1000.json')))
    return [(x['word'], project(gold_morphs(ml[x['word']]), x['word'])) for x in W if x['split'] == split and x['word'] in ml]

def score(items, run):
    claims = good = tol = rec_hit = rec_tot = claims_all = 0; bad = []; multi = 0
    for w, gold in items:
        path = run(w)
        cuts = {j for _, j, *_ in path[:-1]}
        rec_tot += len(gold); rec_hit += len(gold & cuts)
        edges = gold | {0, len(w)}
        near = lambda x: any(abs(x - e) <= 1 for e in edges)
        if gold: multi += 1
        for i, j, ch, kind, info in path:
            if kind in ('前缀', '词根', '后缀'):
                claims_all += 1
                if not gold: continue
                claims += 1
                if i in edges and j in edges: good += 1
                else: bad.append((w, ch, kind, info, sorted(gold)))
                if near(i) and near(j): tol += 1
    return {'words': len(items), 'multi': multi, 'claims/word': round(claims_all / len(items), 2),
            'claim_prec': round(good / max(1, claims), 3), 'prec_tol': round(tol / max(1, claims), 3),
            'morph_rec': round(rec_hit / max(1, rec_tot), 3)}, bad

def wordseg_runner():
    words, cmu, foreign = WS.load()
    ac = WS.AC(sorted(set(words) | set(WS.MORPH) | set(foreign)))
    def run(w):
        r = WS.analyze(w, words, cmu, ac, 1, foreign)
        return r['top'][0][1] if r['top'] else []
    return run

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--split', default='dev'); ap.add_argument('--show', type=int, default=0)
    a = ap.parse_args()
    items = load_eval(a.split)
    m, bad = score(items, wordseg_runner())
    print(a.split, m)
    from collections import Counter
    print('错得最多的语素说法：', Counter(f'{ch}={k}' for _, ch, k, _, _ in bad).most_common(25))
    for x in bad[:a.show]: print('  ', x)
