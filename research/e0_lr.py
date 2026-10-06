"""E0 第 1 轮起：把多个特征组合成逻辑回归。
dev 上按词分组 5 折交叉验证选特征；--val 时用全部 dev 训练、在 val 上报告一次。
"""
import sys, argparse
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from e0_spelling import *

def matrix(X, feats):
    return np.array([[f[k] for k in feats] for f in X])

def cv_scores(M, y, grp):
    words = np.array([g[1] for g in grp]); out = np.zeros(len(y))
    for tr, te in GroupKFold(5).split(M, y, words):
        out[te] = LogisticRegression(max_iter=2000).fit(M[tr], y[tr]).decision_function(M[te])
    return out

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--val', action='store_true')
    ap.add_argument('--sets', default='p2g|p2g,silent,schwa,dbl,dbl2,irr|p2g,silent,schwa,dbl,dbl2,irr,vowel,relpos,edge,unstressed_v')
    a = ap.parse_args()
    cmu = get_cmu(); p2g = p2g_table(cmu)
    X, y, grp, src, _ = build('dev', cmu, p2g)
    for feats in a.sets.split('|'):
        feats = feats.split(',')
        M = matrix(X, feats)
        print(f'[dev-cv] {",".join(feats):70s}', auc_report(cv_scores(M, y, grp), y, grp, src))
        if a.val:
            m = LogisticRegression(max_iter=2000).fit(M, y)
            Xv, yv, gv, sv, _ = build('val', cmu, p2g)
            print(f'[val]    {",".join(feats):70s}', auc_report(m.decision_function(matrix(Xv, feats)), yv, gv, sv))
            print('         coef', dict(zip(feats, np.round(m.coef_[0], 2))))
