"""最终评测：hidden 集只跑一次。研究前的 wordseg（bc85bcb）对比当前版本。
置信区间：按词整簇重抽样（bootstrap）1000 次，取 2.5% 和 97.5% 分位。
用法：FINAL=1 python final_eval.py
"""
import os, sys, subprocess, importlib.util, json, pickle
import numpy as np
from common import *
assert os.environ.get('FINAL') == '1', '最终评测须设置 FINAL=1'
rng = np.random.default_rng(0)

def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

old_src = subprocess.run(['git', 'show', 'bc85bcb:scripts/wordseg.py'], cwd=os.path.join(HERE, '..'), capture_output=True, text=True).stdout
open(os.path.join(CACHE, 'wordseg_v0.py'), 'w').write(old_src)
V0 = load_mod('wordseg_v0', os.path.join(CACHE, 'wordseg_v0.py'))
import wordseg as V1

def boot(stat, groups, n=1000):
    keys = list(groups); vals = []
    for _ in range(n):
        pick = rng.choice(len(keys), len(keys))
        vals.append(stat([groups[keys[i]] for i in pick]))
    return np.percentile(vals, [2.5, 97.5])

report = {}

# ---------- E0：拼写风险位 AUC ----------
from sklearn.metrics import roc_auc_score
from e0_spelling import build, get_cmu, p2g_table
cmu = get_cmu(); p2g = p2g_table(cmu)
X, y, grp, src, _ = build('hidden', cmu, p2g)
for corpus in ('fce', 'birkbeck'):
    m = src == corpus
    by = {}
    for i in np.where(m)[0]: by.setdefault(grp[i][1], []).append(i)
    for feat in ('b0', 'comp'):
        s = np.array([f[feat] for f in X])
        auc = roc_auc_score(y[m], s[m])
        ci = boot(lambda gs: roc_auc_score(y[np.concatenate(gs)], s[np.concatenate(gs)]) if len(set(y[np.concatenate(gs)])) == 2 else 0.5, by, 500)
        report[f'E0 {corpus} {feat}'] = (round(auc, 3), np.round(ci, 3).tolist(), int(m.sum()), len(by))
    diff = lambda gs: (lambda ix: roc_auc_score(y[ix], np.array([X[i]['comp'] for i in ix])) - roc_auc_score(y[ix], np.array([X[i]['b0'] for i in ix])))(np.concatenate(gs))
    report[f'E0 {corpus} comp-b0 差值 CI'] = np.round(boot(diff, by, 500), 3).tolist()

# ---------- 两个版本的运行器（旧版崩溃按“没有输出”计） ----------
def runner(M):
    words, cmu2, foreign = M.load()
    ac = M.AC(sorted(set(words) | set(M.MORPH) | set(foreign)))
    crashes = []
    def run(w):
        try: return M.analyze(w, words, cmu2, ac, 3, foreign)
        except Exception as e: crashes.append(w); return None
    return run, crashes, words

R = {'v0': runner(V0), 'v1': runner(V1)}

# ---------- E2：碰撞召回 ----------
import wordfreq
from e2_collision import load_pairs
pairs = {p: n for p, n in load_pairs(cmu, lambda w: wordfreq.zipf_frequency(w, 'en')).items() if split_of(p[0]) == 'hidden'}
for ver, (run, crashes, _) in R.items():
    hits = {}
    for (c, o) in pairs:
        r = run(c); col = r['collide'] if r else []
        hits[(c, o)] = float(any(f' {o}（' in s or f'↔ {o}' in s or f' {o} ' in s for s in col))
    groups = {}
    for (c, o), h in hits.items(): groups.setdefault(c, []).append(h)
    rec = np.mean(list(hits.values()))
    report[f'E2 召回 {ver}'] = (round(rec, 3), np.round(boot(lambda gs: np.mean(np.concatenate(gs)), {k: np.array(v) for k, v in groups.items()}), 3).tolist(), len(pairs))

# ---------- E3a：词根词缀说法 ----------
from e3_morph import load_eval
items = load_eval('hidden')
for ver, (run, crashes, _) in R.items():
    per = {}
    for w, g in items:
        r = run(w)
        if not g: continue
        path = r['top'][0][1] if r and r['top'] else []
        E = g | {0, len(w)}; near = lambda x: any(abs(x - e) <= 1 for e in E)
        ok = bad = 0
        for i, j, ch, k, _ in path:
            if k in ('前缀', '词根', '后缀'):
                if near(i) and near(j): ok += 1
                else: bad += 1
        per[w] = np.array([ok, bad])
    tot = sum(per.values())
    report[f'E3a {ver} 正确/错误/目标'] = (int(tot[0]), int(tot[1]), int(tot[0] - 2 * tot[1]),
        '错误数 CI', np.round(boot(lambda gs: sum(gs)[1], per), 1).tolist(),
        '容差准确率', round(tot[0] / max(1, tot.sum()), 3))

# ---------- 稳定性：崩溃次数 ----------
W1000 = [x['word'] for x in json.load(open(os.path.join(DATA, 'ielts1000.json')))]
top20k = [w for w in wordfreq.top_n_list('en', 20000) if w.isalpha() and w.isascii() and len(w) >= 4]
for ver, (run, crashes, _) in R.items():
    crashes.clear()
    for w in W1000 + top20k: run(w)
    report[f'崩溃 {ver}'] = (len(crashes), len(W1000) + len(top20k), crashes[:8])

for k, v in report.items(): print(f'{k:28s} {v}')
json.dump({k: str(v) for k, v in report.items()}, open(os.path.join(HERE, 'final_report.json'), 'w'), ensure_ascii=False, indent=1)
