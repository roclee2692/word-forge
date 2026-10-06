"""E2b：碰撞检测能不能找出听力里的同音/近音词？真值：Raelon 的收集（listening_pairs.txt）。
三词组拆成两两一对；按词对（字母序较小的词）的 md5 切 dev/val/hidden。
命中：任一方向的碰撞栏列出了另一个词（学哪个词都会被提醒）。
同时报告 FCE（E2）的 dev/val 召回和平均列出数，作为不能退化的约束。
"""
import sys, os, itertools, argparse
from common import *
import wordseg as WS

def load_pairs():
    out = set()
    for line in open(os.path.join(HERE, 'listening_pairs.txt'), encoding='utf-8'):
        if line.startswith('#') or not line.strip(): continue
        for a, b in itertools.combinations(line.split(), 2): out.add(tuple(sorted((a, b))))
    return sorted(out)

def listed(col, b): return any(f'↔ {b}（' in s or f' {b}（' in s or f' {b} ' in s for s in col)

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--split', default='dev'); ap.add_argument('--show', action='store_true')
    a = ap.parse_args(); allowed(a.split)
    words, cmu, foreign = WS.load(); ac = WS.AC(sorted(set(words) | set(WS.MORPH) | set(foreign)))
    col = lambda w: WS.analyze(w, words, cmu, ac, 1, foreign)['collide']
    P = [p for p in load_pairs() if split_of(p[0]) == a.split]
    hit = [p for p in P if listed(col(p[0]), p[1]) or listed(col(p[1]), p[0])]
    print(f'听力 {a.split}: {len(hit)}/{len(P)} = {len(hit) / max(1, len(P)):.2f}')
    if a.show: print('  漏：', [p for p in P if p not in hit])
