#!/usr/bin/env python3
"""wordseg.py: word-forge 的配套算法，用来找一个英语单词“最省记忆”的拼写切分。

流程：
  1. 字母-音素对齐（动态规划）：把拼写对齐到 CMUdict 读音，
     给每个字母块打标签：规则 / 变体 / 不发音 / 不规则，并标出弱读位（风险位）。
  2. AC 自动机：一次扫描找出词里出现的所有“熟块”（高频词、词根词缀）。
  3. 切分（k-best 动态规划，即带成本的最短路）：在所有切分路径里，
     找总记忆成本最低的几条。贪心最长匹配只作为对照输出。
  4. 碰撞检测：找相邻字母互换、编辑距离为 1 的高频词
     （entre ↔ enter，scarce ↔ scare，prise ↔ price）。

用法：  python3 wordseg.py entrepreneur wednesday [--k 3] [--json]
依赖：  pip install wordfreq cmudict
范围：  只支持英语（读音来自 CMUdict）。语义联想由调用它的 Claude 判断，
        算法只负责拼写和读音这两条通道。
"""
import sys, os, json, math
from collections import deque

# ---------- 成本参数（数值越小越好记） ----------
LAMBDA = 0.4            # 每多一个块的固定开销（块越少越好）
MORPH_COST = 0.9        # 词根词缀（自带意义，略便宜于纯拼读块）
SYL_COST = 1.3          # 拼读块（按拼写就能读出来的音节）
SYL_IRREG = 0.3         # 拼读块里每含一个不规则或静音字母，加这么多
GRAPH_COST = 1.8        # 单个字母组合（规则）
GRAPH_IRREG = 2.4       # 单个字母组合（不规则或静音，需要硬记）
SPLIT_PEN = 0.8         # 切断一个多字母组合（如把 ph、ur 拆开）
SOUND_BONUS = (0.5, 0.25)  # 熟词的读音和目标片段完全一致 / 差一个音素
ZIPF_MIN = 3.0          # 熟词门槛（wordfreq 的 zipf 频率）

def word_cost(z):       # 越常见越便宜：zipf 5.5 及以上 1.0，zipf 3.0 为 2.0
    return 1.0 + 0.4 * max(0.0, 5.5 - z)

# ---------- 词根词缀表：串 类型 含义（p=前缀 r=词根 s=后缀） ----------
MORPHS = """
un p 不|in p 不/进入|im p 不/进入|il p 不|ir p 不|dis p 分开/否定|re p 再/回|pre p 之前|pro p 向前
con p 共同|com p 共同|col p 共同|cor p 共同|co p 共同|de p 向下/去除|ex p 出|sub p 在下|sus p 在下
sup p 在下|super p 超|trans p 穿过|inter p 之间|intra p 内|anti p 反|ante p 前|auto p 自己|bi p 二
tri p 三|mono p 单|multi p 多|poly p 多|micro p 小|macro p 大|mis p 错|non p 非|ob p 对着|op p 对着
per p 贯穿|post p 后|semi p 半|under p 下|over p 过度|out p 出|en p 使|em p 使|ab p 离开|ad p 朝向|se p 分开
ac p 朝向|af p 朝向|ap p 朝向|as p 朝向|at p 朝向|bene p 好|mal p 坏|circum p 环绕|contra p 反
counter p 反|extra p 外|hyper p 超|hypo p 下|para p 旁|peri p 周围|syn p 共同|sym p 共同|tele p 远
ultra p 超|uni p 一|omni p 全|equi p 相等|entre p 之间(法语)|enter p 之间|octo p 八|dec p 十
spect r 看|spec r 看|vers r 转|vert r 转|cap r 抓|capt r 抓|cept r 拿|ceiv r 拿|dict r 说|duc r 引导
duct r 引导|fer r 带|port r 拿/运|mit r 送|miss r 送|mov r 动|mot r 动|pend r 挂|pens r 挂/称|pon r 放
pos r 放|scrib r 写|script r 写|struct r 建|tract r 拉|ven r 来|vent r 来|vid r 看|vis r 看|voc r 声音
cred r 相信|fac r 做|fact r 做|fect r 做|fic r 做|gen r 产生|grad r 步|gress r 走|ject r 扔|jud r 判断
lect r 选/读|leg r 法/读|log r 言/学|loqu r 说|manu r 手|nov r 新|path r 感受/病|ped r 脚|pel r 推
puls r 推|phon r 声音|photo r 光|graph r 写|gram r 写|rupt r 断|sci r 知|sent r 感觉|sens r 感觉
sist r 站|stat r 站|stit r 站|solv r 松开|son r 声音|tain r 握|ten r 握|tin r 握|tend r 伸|tens r 伸
terr r 土地|therm r 热|tort r 扭|vac r 空|val r 价值|vit r 生命|viv r 活|vol r 意愿/飞|noct r 夜
nox r 夜/害|noc r 害|carn r 肉|vor r 吞吃|herb r 草|sect r 切|tom r 切|sema r 信号|phor r 携带
phore r 携带|pren r 拿|prehend r 抓住|pris r 拿|prise r 拿/撬|carp r 摘|cede r 走|ceed r 走|cess r 走
chron r 时间|cycl r 圈|demo r 人民|derm r 皮|hydr r 水|oxy r 尖/酸|bio r 生命|geo r 地|aqua r 水
mar r 海|mort r 死|nat r 生|nom r 名|nym r 名|plic r 折|ply r 折|prim r 第一|quest r 寻求|quir r 寻求
rect r 直|reg r 统治|rog r 问|sequ r 跟随|secu r 跟随|sign r 标记|simil r 相似|soci r 同伴|spir r 呼吸
tact r 触|tang r 触|temp r 时间|urb r 城|verb r 词|via r 路|vinc r 征服|vict r 征服|cord r 心|card r 心
dent r 牙|corp r 身体|cid r 切/杀|mod r 尺度|par r 准备/相等|meter r 测量|metr r 测量|scope r 看|cracy r 统治|crat r 统治|cide r 杀|nounce r 宣告|sume r 拿|sumpt r 拿|lumin r 光|loc r 地方
able s 能…的|ible s 能…的|al s …的|ial s …的|ance s 名词|ence s 名词|ant s …的/人|ent s …的/人
ary s …的/物|ery s 场所/行为|ory s …的/场所|ate s 使/…的|ation s 名词|tion s 名词|sion s 名词|cian s 人
dom s 状态|ed s 过去|er s 人/物|or s 人/物|eur s 人(法语)|ess s 女性|ful s 充满|fy s 使|ify s 使
hood s 身份|ic s …的|ical s …的|ing s 进行|ise s 使|ize s 使|ism s 主义|ist s 人|ity s 性质|ty s 性质
ive s …的|ative s …的|less s 无|ly s 地|ment s 名词|ness s 名词|ous s …的|ious s …的|eous s …的
ship s 身份|ure s 名词|ward s 向|atile s 易…的|ile s 能…的|ar s …的|ette s 小|esque s 风格|ology s 学科
logy s 学科|ian s 人|ine s …的|oid s 像|osis s 病/过程|urnal s …的|imen s 名词|ber s 月份词尾|uary s 月份词尾
"""
_REL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'affix_rel.json')
AFFIX_REL = json.load(open(_REL_PATH)) if os.path.exists(_REL_PATH) else {}
def morph_rel(kind, p, i, j, n):   # 这个串在这个位置真是语素的比例（来自 MorphoLex 统计；前缀不在词首、后缀不在词尾时打五折）
    r = AFFIX_REL.get(f'{kind}:{p}', [0.5])[0]
    if (kind == 'p' and i > 0) or (kind == 's' and j < n): r *= 0.5
    return r
# 低于这个可信度的词根词缀说法不标（research/E3a：对照 MorphoLex 人工切分，val 上错误说法 25 → 5，正确说法 97 → 87）
REL_T = 0.4
MORPH = {}
for item in MORPHS.replace("\n", "|").split("|"):
    item = item.strip()
    if item:
        s, k, m = item.split(" ", 2)
        MORPH.setdefault(s, []).append((k, m))

# ---------- 自然拼读：字母组合 → 常见读音（ARPAbet，第一个是默认读法，'' 表示不发音） ----------
G = {
 'b':['B'],'bb':['B'],'c':['K','S'],'cc':['K','K S'],'ch':['CH','K','SH'],'ck':['K'],'d':['D'],'dd':['D'],
 'dg':['JH'],'f':['F'],'ff':['F'],'g':['G','JH'],'gg':['G'],'gh':['','F','G'],'gn':['N'],'h':['HH',''],
 'j':['JH'],'k':['K'],'kn':['N'],'l':['L'],'ll':['L'],'m':['M'],'mm':['M'],'mb':['M'],'n':['N'],'nn':['N'],
 'ng':['NG'],'nk':['NG K'],'p':['P'],'pp':['P'],'ph':['F'],'qu':['K W','K'],'r':['R'],'rr':['R'],
 's':['S','Z','SH','ZH'],'ss':['S'],'sh':['SH'],'sc':['S','S K'],'t':['T','SH','CH'],'tt':['T'],'th':['TH','DH'],
 'tch':['CH'],'tion':['SH AH N'],'sion':['ZH AH N','SH AH N'],'ture':['CH ER'],'v':['V'],'w':['W'],'wh':['W'],
 'wr':['R'],'x':['K S','G Z','Z'],'z':['Z','ZH'],'zz':['Z'],
 'a':['AE','EY','AH','AA','AO','EH','IH'],'e':['EH','IY','AH','IH',''],'i':['IH','AY','AH','IY'],
 'o':['AA','OW','AH','AO','UW'],'u':['AH','UW','Y UW','UH','Y AH',''],'y':['IY','AY','IH','Y'],
 'ai':['EY'],'ay':['EY','IY'],'au':['AO','AA'],'aw':['AO'],'ea':['IY','EH','EY'],'ee':['IY'],'ei':['EY','IY','AY'],
 'ey':['EY','IY'],'ie':['IY','AY'],'igh':['AY'],'oa':['OW'],'oe':['OW'],'oi':['OY'],'oy':['OY'],'oo':['UW','UH'],
 'ou':['AW','UW','AH','OW'],'ow':['OW','AW'],'ue':['UW','Y UW'],'ui':['UW','IH'],'ew':['UW','Y UW'],
 'eu':['UW','Y UW'],'eau':['OW'],'ar':['AA R','ER'],'er':['ER'],'ir':['ER'],'or':['AO R','ER'],'ur':['ER'],
 'ear':['ER','IH R'],'our':['AW R','ER','AO R'],'are':['EH R'],'ure':['Y UH R','ER'],'eur':['ER','UH R'],
 'air':['EH R'],'ere':['IH R','EH R'],'le':['AH L'],'ci':['SH'],'ti':['SH'],'xi':['K SH'],
}
G = {k: [tuple(o.split()) for o in v] for k, v in G.items()}
VOWEL_PH = {'AA','AE','AH','AO','AW','AY','EH','ER','EY','IH','IY','OW','OY','UH','UW'}
IPA = {'AA':'ɑ','AE':'æ','AH':'ʌ','AO':'ɔ','AW':'aʊ','AY':'aɪ','B':'b','CH':'tʃ','D':'d','DH':'ð','EH':'ɛ',
       'ER':'ɝ','EY':'eɪ','F':'f','G':'ɡ','HH':'h','IH':'ɪ','IY':'i','JH':'dʒ','K':'k','L':'l','M':'m','N':'n',
       'NG':'ŋ','OW':'oʊ','OY':'ɔɪ','P':'p','R':'r','S':'s','SH':'ʃ','T':'t','TH':'θ','UH':'ʊ','UW':'u','V':'v',
       'W':'w','Y':'j','Z':'z','ZH':'ʒ'}

def ipa(ph):  # ph 是带重音数字的 ARPAbet
    b, s = ph.rstrip('012'), ph[-1]
    if b == 'AH' and s == '0': return 'ə'
    if b == 'ER' and s == '0': return 'ɚ'
    return ('ˈ' if s == '1' else '') + IPA.get(b, b.lower())

# ---------- 学习者画像：哪些词算“熟块”（决定 ★） ----------
# general：初中 + 高中词汇（大部分中国学习者）；raelon：再加四级词汇和德语、法语高频词（用户在学德法语）。
# research/E3b：旧判定只看 wordfreq 词频，dev 上 81% 的 ★ 路径含通用学习者不认识的块（ive、ent、comm、nes、fri）。
_KNOWN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'known_en.json')
_KNOWN = json.load(open(_KNOWN_PATH)) if os.path.exists(_KNOWN_PATH) else None
PROFILE = 'raelon'
def known_en():
    if not _KNOWN: return None
    return set(_KNOWN['general']) | (set(_KNOWN['cet4']) if PROFILE == 'raelon' else set())

# ---------- 词典加载 ----------
TWO_OK = {'an','at','in','on','to','up','us','we','me','he','it','is','of','or','by','so','no','go','do','be','my','as','if','am','ox','hi','oh'}
def load():
    import wordfreq, cmudict
    words = {}
    for w in wordfreq.top_n_list('en', 40000):
        if w.isalpha() and w.isascii() and len(w) >= 2:
            z = wordfreq.zipf_frequency(w, 'en')
            if z >= ZIPF_MIN and (len(w) > 2 or w in TWO_OK):
                words[w] = z
    foreign = {}   # 德语/法语高频词：用户在学这两门语言，它们也算“熟块”（und = and）
    for lang, name in (('de', '德语'), ('fr', '法语')):
        for w in wordfreq.top_n_list(lang, 3000):
            if w.isalpha() and w.isascii() and len(w) >= 2 and w not in foreign:
                foreign[w] = (name, wordfreq.zipf_frequency(w, lang))
    return words, cmudict.dict(), foreign

# ---------- AC 自动机：一次扫描找出所有熟块 ----------
class AC:
    def __init__(self, pats):
        self.go, self.fail, self.out, self.pats = [{}], [0], [[]], pats
        for pid, p in enumerate(pats):
            u = 0
            for ch in p:
                if ch not in self.go[u]:
                    self.go[u][ch] = len(self.go); self.go.append({}); self.fail.append(0); self.out.append([])
                u = self.go[u][ch]
            self.out[u].append(pid)
        q = deque(self.go[0].values())          # BFS 建失配指针，原理同 KMP 的 next 数组
        while q:
            u = q.popleft()
            for ch, v in self.go[u].items():
                q.append(v); f = self.fail[u]
                while f and ch not in self.go[f]: f = self.fail[f]
                nf = self.go[f].get(ch, 0)
                self.fail[v] = nf if nf != v else 0
                self.out[v] = self.out[v] + self.out[self.fail[v]]
    def find(self, text):                     # 返回所有匹配 (起点, 终点, 串)
        u, res = 0, []
        for i, ch in enumerate(text):
            while u and ch not in self.go[u]: u = self.fail[u]
            u = self.go[u].get(ch, 0)
            for pid in self.out[u]:
                p = self.pats[pid]; res.append((i + 1 - len(p), i + 1, p))
        return res

# ---------- 1. 字母-音素对齐 DP ----------
def align(word, phones):
    base = [p.rstrip('012') for p in phones]
    n, m, INF = len(word), len(base), float('inf')
    dp = [[INF] * (m + 1) for _ in range(n + 1)]; bt = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0
    def upd(i, j, c, info):
        if c < dp[i][j]: dp[i][j], bt[i][j] = c, info
    for i in range(n):
        for j in range(m + 1):
            if dp[i][j] == INF: continue
            c0 = dp[i][j]
            for L in (4, 3, 2, 1):
                g = word[i:i + L]
                if len(g) < L or g not in G: continue
                for k, opt in enumerate(G[g]):
                    if tuple(base[j:j + len(opt)]) != opt: continue
                    if not opt:   # 不发音
                        c = 0.1 if (g == 'e' and i + 1 == n) else 0.6
                        tag = 'silent'
                    else:
                        c, tag = (0.0, 'regular') if k == 0 else (0.3, 'variant')
                    upd(i + L, j + len(opt), c0 + c, (i, j, g, tag))
            if j < m: upd(i + 1, j + 1, c0 + 2.0, (i, j, word[i], 'irregular'))   # 不规则读法
            if j + 1 < m: upd(i + 1, j + 2, c0 + 2.5, (i, j, word[i], 'irregular'))   # 一个字母读两个音（security 的 u→/jʊ/、缩写词）
            upd(i + 1, j, c0 + 1.5, (i, j, word[i], 'irregular-silent'))           # 不规则静音
    if dp[n][m] == INF: return None    # 音素比字母还多、对不齐（如 w 读 /ˈdʌbəlju/）
    segs, i, j = [], n, m
    while i > 0:
        pi, pj, g, tag = bt[i][j]
        segs.append({'g': g, 'start': pi, 'end': i, 'ph': phones[pj:j], 'tag': tag}); i, j = pi, pj
    return segs[::-1]

def pseudo_align(word):   # 词典里查不到读音时：按最长字母组合切，读音未知
    segs, i = [], 0
    while i < len(word):
        for L in (4, 3, 2, 1):
            g = word[i:i + L]
            if len(g) == L and (g in G or L == 1):
                segs.append({'g': g, 'start': i, 'end': i + L, 'ph': [], 'tag': 'unknown'}); i += L; break
    return segs

ONSET2 = {'bl','br','cl','cr','dr','fl','fr','gl','gr','pl','pr','sc','sk','sl','sm','sn','sp','st','sw','tr','tw',
          'thr','shr','chr','phr','sch','scr','spl','spr','str','squ','qu','dw','gw','ph','th','sh','ch','wh','wr','kn','gn'}

def legal_onset(segs, lo, a):      # 音节开头的辅音组合必须是英语里合法的（排除 dn、sd 这类）
    c = ''.join(segs[x]['g'] for x in range(lo, a))
    return a - lo <= 1 or c in ONSET2

def is_vowel_g(g):
    return g[0] in 'aeiou' or (g[0] == 'y' and len(g) == 1)

def ph_dist(a, b):        # 音素序列编辑距离（忽略重音）
    a = [x.rstrip('012') for x in a]; b = [x.rstrip('012') for x in b]
    d = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(b) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (a[i - 1] != b[j - 1])); prev, d[j] = d[j], cur
    return d[len(b)]

# ---------- 2+3. 建切分图并做 k-best DP ----------
def senses(p, words, foreign):   # 一个块的全部身份：英语词 / 德法词 / 词根词缀，交给调用者挑最好编故事的
    out = []
    if p in words: out.append(f'英语词 zipf {words[p]:.1f}')
    if p in foreign and len(p) >= 3: out.append(f'{foreign[p][0]}词')
    KIND = {'p': '前缀', 'r': '词根', 's': '后缀'}
    out += [KIND[k] + '·' + m for k, m in MORPH.get(p, [])]
    return out

def analyze(word, words, cmu, ac, k=3, foreign=None):
    foreign = foreign or {}
    w = word.lower(); n = len(w)
    al = [(p, align(w, p)) for p in cmu.get(w, [])]
    al = [(p, s) for p, s in al if s]            # 对不齐的读音丢掉
    if al:      # 多个读音时，选拼写最“规则”的那个来对齐
        pron, segs = min(al, key=lambda x: sum({'regular': 0, 'variant': .3, 'silent': .5}.get(s['tag'], 2) for s in x[1]))
    else:
        pron = None; segs = pseudo_align(w)
    bounds = {s['start'] for s in segs} | {n}
    SOFT = {'xi', 'ci', 'ti', 'le', 'sc', 'cc', 'ss', 'mm', 'll', 'tt', 'pp', 'ff', 'rr', 'nn', 'dd', 'gg', 'bb', 'zz'}
    soft = {s['start'] + 1 for s in segs if s['g'] in SOFT}   # 双写辅音中间常是词素边界，切开只轻罚
    span_ph = {}
    for a in range(len(segs)):
        ph = []
        for b in range(a, len(segs)):
            ph = ph + list(segs[b]['ph']); span_ph[(segs[a]['start'], segs[b]['end'])] = ph
    edges = [[] for _ in range(n + 1)]
    def add(i, j, cost, kind, info=''):
        for x in (i, j):
            if x not in bounds: cost += 0.1 if x in soft else SPLIT_PEN / 2
        edges[i].append((j, cost, kind, info))
    found = ac.find(w)
    ok_claim = {(i, j, kd) for i, j, p in found if p != w for kd, _ in MORPH.get(p, []) if morph_rel(kd, p, i, j, n) >= REL_T}
    for i, j, p in found:                      # 熟词和词根词缀
        if p == w: continue
        if p in words:
            c = word_cost(words[p])
            if (i, j) in span_ph and p in cmu and span_ph[(i, j)]:
                dd = min(ph_dist(span_ph[(i, j)], pr) for pr in cmu[p])
                c -= SOUND_BONUS[0] if dd == 0 else SOUND_BONUS[1] if dd == 1 else 0
            add(i, j, c, 'word', f'zipf {words[p]:.1f}')
        elif p in foreign and len(p) >= 3:
            add(i, j, word_cost(foreign[p][1]) + 0.3, 'word', f'{foreign[p][0]}词')
        for kind, mean in MORPH.get(p, []):
            if (i, j, kind) not in ok_claim: continue      # 不可信的词缀说法会误导（ancestor 的 ance、acrobat 的 ac）
            c = MORPH_COST
            if kind == 'p' and i > 0: c += 0.3
            if kind == 's' and j < n: c += 0.5
            if len(p) <= 2: c += 0.2
            add(i, j, c, {'p': '前缀', 'r': '词根', 's': '后缀'}[kind], mean)
            if kind == 'r' and i > 1 and w[i - 1] in 'io':   # 拉丁/希腊连接元音：insect-i-vor、therm-o-meter
                add(i - 1, j, c + 0.1, '词根', f'连接元音 {w[i-1]} + {p}={mean}')
    for a, s in enumerate(segs):               # 单个字母组合
        hard = s['tag'] in ('irregular', 'irregular-silent', 'silent')
        edges[s['start']].append((s['end'], GRAPH_IRREG if hard else GRAPH_COST, '字母', s['tag']))
        # 拼读块：0-2 个辅音 + 1 个元音组合 + 0-2 个辅音，按字母顺序就能读出来
        if not is_vowel_g(s['g']): continue
        for lo in range(max(0, a - 2), a + 1):
            if any(is_vowel_g(segs[x]['g']) for x in range(lo, a)) or not legal_onset(segs, lo, a): continue
            for hi in range(a, min(len(segs), a + 3)):
                if any(is_vowel_g(segs[x]['g']) for x in range(a + 1, hi + 1)): break
                i, j = segs[lo]['start'], segs[hi]['end']
                if j - i < 2 or j - i > 5: continue
                irr = sum(segs[x]['tag'] not in ('regular', 'variant', 'unknown') for x in range(lo, hi + 1))
                edges[i].append((j, SYL_COST + SYL_IRREG * irr, '拼读块', '含静音字母，按拼写读' if irr else ''))
    best = [dict() for _ in range(n + 1)]; best[0][()] = (0.0, [])
    for i in range(n):
        cand = sorted(best[i].values(), key=lambda x: x[0])[:k * 4]
        for c, path in cand:
            for j, ec, kind, info in edges[i]:
                key = tuple(x[1] for x in path) + (j,)
                nc = c + ec + LAMBDA
                if key not in best[j] or nc < best[j][key][0]:
                    best[j][key] = (nc, path + [(i, j, w[i:j], kind, info)])
    top = sorted(best[n].values(), key=lambda x: x[0])[:k]
    # 贪心最长匹配（对照组）：每步取最长的熟块
    greedy, i = [], 0
    while i < n:
        j, kind = max(((e[0], e[2]) for e in edges[i] if e[2] not in ('字母', '拼读块')), default=(None, None))
        if j is None:   # 前一块停在字母组合中间时，从这里开始的组合不存在，就退一个字母
            s = next((s for s in segs if s['start'] == i), None); j, kind = (s['end'] if s else i + 1), '字母'
        greedy.append(w[i:j]); i = j
    sense = {ch: senses(ch, words, foreign) for _, path in top for _, _, ch, _, _ in path}
    kn = known_en()
    def known(ch):   # 能直接当画面用的块：学习者认识的英语词（≥3 字母或常见两字母词）；raelon 画像另加 ≥3 字母的德法高频词
        en = (ch in kn) if kn is not None else (ch in words)
        return (en and (len(ch) >= 3 or ch in TWO_OK)) or (PROFILE == 'raelon' and ch in foreign and len(ch) >= 3)
    story = [len(path) > 1 and all(known(ch) for _, _, ch, _, _ in path) for _, path in top]   # 看块的全部身份：ant 标成后缀也算熟词
    risk = []
    for s in segs:
        if not s['ph']: continue
        v, alts = spell_risk(s)
        hit = ''.join(ch for ch, x in zip(s['g'], v) if x >= RISK_T)
        if hit and alts: risk.append({'g': s['g'], 'letters': hit, 'start': s['start'], 'alts': alts,
                                     'sound': ''.join(ipa(p) for p in s['ph']).lstrip('ˈ')})
    return {'word': w, 'segs': segs, 'top': top, 'risk': risk, 'greedy': greedy, 'senses': sense, 'story': story,
            'collide': collisions(w, words, top[0][1] if top else [], cmu), 'pron': pron}

# ---------- 4. 碰撞检测 ----------
def edits1(w):
    sp = [(w[:i], w[i:]) for i in range(len(w) + 1)]; al = 'abcdefghijklmnopqrstuvwxyz'
    out = {}
    for a, b in sp:
        if b: out.setdefault(a + b[1:], '少一个字母')
        if len(b) > 1: out.setdefault(a + b[1] + b[0] + b[2:], '相邻互换')
        for c in al:
            if b: out.setdefault(a + c + b[1:], '换一个字母')
            out.setdefault(a + c + b, '多一个字母')
    out.pop(w, None); return out

_PHIDX = None
def phone_index(words, cmu):   # 读音（去重音）→ 熟词
    global _PHIDX
    if _PHIDX is None:
        _PHIDX = {}
        for x in words:
            for p in cmu.get(x, []): _PHIDX.setdefault(tuple(q.rstrip('012') for q in p), set()).add(x)
    return _PHIDX

PHONES = sorted(IPA)
def near_homophones(w, words, cmu):   # 同音词 → 0；只差一个元音的熟词 → 'v'；只差一个辅音或增删一个音素 → 1
    idx, out = phone_index(words, cmu), {}
    for p in cmu.get(w, []):
        b = [q.rstrip('012') for q in p]; cands = {tuple(b): 0}
        for i in range(len(b) + 1):
            if i < len(b): cands.setdefault(tuple(b[:i] + b[i + 1:]), 1)
            for ph in PHONES:
                if i < len(b) and ph != b[i]:
                    cands.setdefault(tuple(b[:i] + [ph] + b[i + 1:]), 'v' if ph in VOWEL_PH and b[i] in VOWEL_PH else 1)
                cands.setdefault(tuple(b[:i] + [ph] + b[i:]), 1)
        for c, dist in cands.items():
            for x in idx.get(c, ()):
                if x != w and (x not in out or out[x] != 0): out[x] = dist
    return out

def lev(a, b):
    d = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(b) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (a[i - 1] != b[j - 1])); prev, d[j] = d[j], cur
    return d[len(b)]

def is_infl(a, b):   # 同一个词的屈折形式（不算碰撞）
    for x, y in ((a, b), (b, a)):
        for suf in ('s', 'es', 'd', 'ed', 'ing', 'er', 'r', 'ly'):
            if y == x + suf or (x.endswith('e') and y == x[:-1] + suf) or (x.endswith('y') and y == x[:-1] + 'i' + suf): return True
    return False

def collisions(w, words, best_path, cmu=None):
    res = []
    infl = {w + 's', w + 'es', w + 'd', w + 'ed', w + 'r', w[:-1]}
    e1 = edits1(w)
    for cand, how in e1.items():                 # 整词近邻（排除复数、过去式等词形变化）
        if words.get(cand, 0) >= 3.5 and cand not in infl:
            res.append((words[cand] + 0.5, f'{w} ↔ {cand}（{how}）'))
    # 同音、或只差一个元音、拼写差 ≤2 的熟词（break ↔ brake，accept ↔ except）。
    # research/E2：对照 FCE 学习者真实混淆的词对，召回 val 0.47 → 0.58。只差一个辅音的（wait/waste）不收，收了反而更差。
    if cmu:
        for cand, dist in near_homophones(w, words, cmu).items():
            if cand in e1 or words.get(cand, 0) < 3.0 or is_infl(w, cand) or lev(w, cand) > 2: continue
            if dist == 1: continue
            bonus = 1.5 if dist == 0 else 0.8
            res.append((words[cand] + bonus, f'{w} ↔ {cand}（{"同音" if dist == 0 else "只差一个元音" if dist == "v" else "读音几乎相同"}）'))
    seen = set()
    spans = {(i, j) for i, j, *_ in best_path} | {(0, L) for L in range(4, 8)}
    for i, j in sorted(spans):                          # 词首或最优切分的块被拼反
        s = w[i:j]; L = len(s)
        if L >= 4:
            for p in range(L - 1):
                t = s[:p] + s[p + 1] + s[p] + s[p + 2:]
                if t != s and words.get(t, 0) >= 4.0 and words.get(s, 0) < 3.5 and t not in seen:
                    seen.add(t); res.append((words[t] + 1, f'片段 {s} ↔ 熟词 {t}（相邻互换，别拼反）'))
    for _, _, chunk, kind, _ in best_path:              # 最优切分里的块：长得像哪个熟词
        if len(chunk) >= 5 and words.get(chunk, 0) < 4.0:
            near = sorted(((words[c], c) for c, h in edits1(chunk).items()
                           if h == '换一个字母' and words.get(c, 0) >= 4.5), reverse=True)[:2]
            if near: res.append((near[0][0], f'块 {chunk} 形近熟词：' + ' / '.join(c for _, c in near) + '（可类比，别写混）'))
    return [s for _, s in sorted(res, reverse=True)[:4]]

# ---------- 拼写易错位 ----------
# 同一个音的其他常见写法里，有多少概率恰好在这个字母上和它不同（竞争拼法压力）。
# research/E0 用 FCE 学习者真实拼错的位置验证过：val 集 AUC 0.559（旧的“弱读/不规则”标记）→ 0.638；
# 阈值 0.5 时标出约 23% 的字母，这些位置的实际错误率是平均的 1.58 倍（旧标记标 32%，1.30 倍）。
_P2G_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'p2g.json')
P2G = json.load(open(_P2G_PATH)) if os.path.exists(_P2G_PATH) else {}
RISK_T = 0.5

def letter_mass(word, miss):   # 把另一种写法对齐到 word 上，返回每个字母上的差异量（与 research/common.error_positions 相同）
    n, m = len(word), len(miss)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1): d[i][0] = i
    for j in range(m + 1): d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(d[i-1][j] + 1, d[i][j-1] + 1, d[i-1][j-1] + (word[i-1] != miss[j-1]))
            if i > 1 and j > 1 and word[i-1] == miss[j-2] and word[i-2] == miss[j-1]: d[i][j] = min(d[i][j], d[i-2][j-2] + 1)
    mass, i, j = [0.0] * n, n, m
    while i > 0 or j > 0:
        if i > 1 and j > 1 and word[i-1] == miss[j-2] and word[i-2] == miss[j-1] and d[i][j] == d[i-2][j-2] + 1 and word[i-1] != word[i-2]:
            mass[i-1] += 1; mass[i-2] += 1; i -= 2; j -= 2
        elif i > 0 and j > 0 and d[i][j] == d[i-1][j-1] + (word[i-1] != miss[j-1]):
            if word[i-1] != miss[j-1]: mass[i-1] += 1
            i -= 1; j -= 1
        elif i > 0 and d[i][j] == d[i-1][j] + 1:
            mass[i-1] += 1; i -= 1
        else:
            if i > 0: mass[i-1] += 0.5
            if i < n: mass[i] += 0.5
            j -= 1
    return mass

def alt_name(g, a):   # 竞争写法的说法：双写 ↔ 单写要点明，否则“mm 也常写成 m”像废话
    if len(g) == 2 and g[0] == g[1] and a == g[0]: return f'单写 {a}'
    if len(a) == 2 and a[0] == a[1] and g == a[0]: return f'双写 {a}'
    return a

def spell_risk(seg):   # 返回 (每个字母的风险, [(竞争写法, 概率)…])
    key = ' '.join(p.rstrip('012') if p.rstrip('012') not in VOWEL_PH else p for p in seg['ph'])
    alts = P2G.get(key, {}); tot = sum(alts.values()); g = seg['g']
    v = [0.0] * len(g)
    if not tot: return v, []
    for g2, c in alts.items():
        if g2 != g:
            for i, x in enumerate(letter_mass(g, g2)): v[i] += c / tot * min(x, 1.0)
    comp = sorted(((c / tot, g2) for g2, c in alts.items() if g2 != g), reverse=True)
    return v, [(g2, round(p, 2)) for p, g2 in comp if p >= 0.1][:2]

# ---------- 输出 ----------
TAG = {'regular': '', 'variant': '变体', 'silent': '不发音', 'irregular': '不规则', 'irregular-silent': '不规则静音', 'unknown': ''}

def legal_ph_onset(c):   # 英语合法的音节首辅音丛（音素层面）：str、pl、kw、sp……
    if len(c) == 1: return c[0] != 'NG'
    if len(c) == 2:
        a, b = c
        return (a == 'S' and b in ('P', 'T', 'K', 'M', 'N', 'L', 'W', 'F')) or \
               (a in ('P', 'B', 'T', 'D', 'K', 'G', 'F', 'TH', 'SH') and b in ('R', 'L', 'W', 'Y')) or \
               (a in ('M', 'N', 'V', 'HH') and b == 'Y')
    return len(c) == 3 and c[0] == 'S' and c[1] in ('P', 'T', 'K') and c[2] in ('R', 'L', 'W', 'Y')

def ipa_word(pron):   # 重音符号放到重读音节的整个起首辅音丛前（strawberry → /ˈstrɔ…/）
    sy = [ipa(p).lstrip('ˈ') for p in pron]
    base = [p.rstrip('012') for p in pron]
    for i, p in enumerate(pron):
        if p.endswith('1'):
            k = i
            while k > 0 and base[k - 1] not in VOWEL_PH and legal_ph_onset(base[k - 1:i]): k -= 1
            sy[k] = 'ˈ' + sy[k]; break
    return ''.join(sy)

def render(r):
    out = [f"■ {r['word']}  /{ipa_word(r['pron'])}/" if r['pron'] else f"■ {r['word']}（CMUdict 无读音）"]
    al = []
    for s in r['segs']:
        ph = ''.join(ipa(p) for p in s['ph']) or '∅'
        risk = '弱读' if any(p in ('AH0', 'IH0', 'ER0') for p in s['ph']) and is_vowel_g(s['g']) else ''
        tag = '·'.join(x for x in (TAG[s['tag']], risk) if x)
        al.append(f"{s['g']}→{ph}" + (f"[{tag}]" if tag else ''))
    out.append('  对齐：' + '  '.join(al))
    if r.get('risk'): out.append('  易错位：' + '；'.join(
        f"{x['g']}" + (f" 的 {x['letters']}" if x['letters'] != x['g'] else '') + f"（/{x['sound']}/ 也常写成 {' / '.join(alt_name(x['g'], a) for a, _ in x['alts'])}）"
        for x in r['risk']))
    for rank, (c, path) in enumerate(r['top'], 1):
        parts = [f"{ch}" for _, _, ch, _, _ in path]
        notes = [f"{ch}={kind}{('·' + info) if info else ''}" for _, _, ch, kind, info in path]
        star = '  ★全是熟词，可直接编画面' if r['story'][rank - 1] else ''
        out.append(f"  {rank}. {' | '.join(parts)}   成本 {c:.2f}   ({'; '.join(notes)}){star}")
    multi = [f"{ch}={' / '.join(v)}" for ch, v in r['senses'].items() if len(v) > 1]
    if multi: out.append('  一块多义（挑最好编画面的那个）：' + '；'.join(multi))
    out.append('  贪心对照：' + ' | '.join(r['greedy']))
    if r['collide']: out.append('  碰撞：' + '；'.join(r['collide']))
    return '\n'.join(out)

if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    k = int(sys.argv[sys.argv.index('--k') + 1]) if '--k' in sys.argv else 3
    if '--k' in sys.argv: args.remove(str(k))
    if '--profile' in sys.argv:   # general：大部分中国学习者；raelon（默认）：加四级和德法语
        PROFILE = sys.argv[sys.argv.index('--profile') + 1]; args.remove(PROFILE)
    words, cmu, foreign = load()
    ac = AC(sorted(set(words) | set(MORPH) | set(foreign)))
    res = [analyze(a, words, cmu, ac, k, foreign) for a in args]
    if '--json' in sys.argv: print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    else: print('\n\n'.join(render(r) for r in res))
