"""学习者熟词表，给 wordseg 的 ★ 判定用。
general：初中 + 高中词汇（大部分中国学习者认识）；cet4：四级在此之上新增的词（raelon 画像额外认识）。
来源：KyleBing/english-vocabulary（BSD-3-Clause）。只保留纯字母单词。
"""
import json, os
from common import DATA, HERE
def lex(f):
    return {l.split('\t')[0].strip().lower() for l in open(os.path.join(DATA, f), encoding='utf-8')
            if l.split('\t')[0].strip().isalpha() and l.split('\t')[0].strip().isascii()}
gen = lex('juniorhigh.txt') | lex('highschool.txt')
out = {'source': 'KyleBing/english-vocabulary (BSD-3-Clause): 初中, 高中, 四级',
       'general': sorted(gen), 'cet4': sorted(lex('cet4.txt') - gen)}
path = os.path.join(HERE, '..', 'scripts', 'known_en.json')
json.dump(out, open(path, 'w'), ensure_ascii=False, separators=(',', ':'))
print(len(out['general']), len(out['cet4']), os.path.getsize(path), 'bytes')
