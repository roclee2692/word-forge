"""研究共用：数据切分、拼写错误事件、字母级对齐。

切分：按词的 md5 固定切分，dev 60% / val 20% / hidden 20%。
hidden 只在 FINAL=1 时可读，开发过程中任何脚本都不碰它。
"""
import os, sys, json, hashlib, re
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
CACHE = os.path.join(HERE, 'cache'); os.makedirs(CACHE, exist_ok=True)
sys.path.insert(0, os.path.join(HERE, '..', 'scripts'))

def split_of(word):
    b = int(hashlib.md5(word.encode()).hexdigest(), 16) % 10
    return 'dev' if b < 6 else 'val' if b < 8 else 'hidden'

def allowed(split):
    if split == 'hidden' and os.environ.get('FINAL') != '1':
        raise SystemExit('hidden 集只在最终评测时读取（FINAL=1）')
    return True

# ---------- 拼写错误事件 ----------
def damerau(a, b):
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1): d[i][0] = i
    for j in range(len(b) + 1): d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i][j] = min(d[i-1][j] + 1, d[i][j-1] + 1, d[i-1][j-1] + (a[i-1] != b[j-1]))
            if i > 1 and j > 1 and a[i-1] == b[j-2] and a[i-2] == b[j-1]:
                d[i][j] = min(d[i][j], d[i-2][j-2] + 1)
    return d

def error_positions(word, miss):
    """把错拼对齐到正确词上，返回每个字母位置上的错误量（插入错误一半记给左邻、一半记给右邻）。"""
    d = damerau(word, miss); i, j = len(word), len(miss)
    mass = [0.0] * len(word)
    while i > 0 or j > 0:
        if i > 1 and j > 1 and word[i-1] == miss[j-2] and word[i-2] == miss[j-1] and d[i][j] == d[i-2][j-2] + 1 and word[i-1] != word[i-2]:
            mass[i-1] += 1; mass[i-2] += 1; i -= 2; j -= 2
        elif i > 0 and j > 0 and d[i][j] == d[i-1][j-1] + (word[i-1] != miss[j-1]):
            if word[i-1] != miss[j-1]: mass[i-1] += 1
            i -= 1; j -= 1
        elif i > 0 and d[i][j] == d[i-1][j] + 1:
            mass[i-1] += 1; i -= 1                      # 漏写 word[i-1]
        else:
            if i > 0: mass[i-1] += 0.5                  # 多写：插在 word[i-1] 之后
            if i < len(word): mass[i] += 0.5
            j -= 1
    return mass

def load_fce():
    """FCE（剑桥 FCE 考生作文，多国学习者）：R:SPELL 编辑 → (正确词, 错拼)；同时统计每个词的出现次数。"""
    events, expo = [], Counter()
    for part in ('train', 'dev', 'test'):
        src = None; spell = {}
        for line in open(os.path.join(DATA, 'fce', 'm2', f'fce.{part}.gold.bea19.m2'), encoding='utf-8'):
            line = line.rstrip('\n')
            if line.startswith('S '):
                src = line[2:].split(' '); spell = {}
            elif line.startswith('A '):
                span, typ, cor = line[2:].split('|||')[:3]
                a, b = map(int, span.split())
                if typ == 'R:SPELL' and b - a == 1 and ' ' not in cor:
                    spell[a] = cor
            elif not line and src is not None:
                for k, t in enumerate(src):
                    if k in spell:
                        events.append((spell[k].lower(), t.lower(), 'fce')); expo[spell[k].lower()] += 1
                    else:
                        expo[t.lower()] += 1
                src = None
    return events, expo

def load_birkbeck():
    """Birkbeck 拼写错误语料（以英语母语者为主）：$正确词 后面跟若干错拼。"""
    events, cur = [], None
    for line in open(os.path.join(DATA, 'missp.dat'), encoding='latin-1'):
        line = line.strip()
        if line.startswith('$'): cur = line[1:].lower()
        elif cur and line: events.append((cur, line.lower(), 'birkbeck'))
    return events

def clean_events(events, cmu):
    out = []
    for w, m, src in events:
        if not (w.isalpha() and w.isascii() and m.isalpha() and m.isascii()): continue
        if len(w) < 4 or w == m or w not in cmu: continue
        if damerau(w, m)[len(w)][len(m)] > 2: continue      # 编辑距离 >2 多半是换词，不算拼写
        out.append((w, m, src))
    return out
