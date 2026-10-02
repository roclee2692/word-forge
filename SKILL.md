---
name: "word-forge"
description: "给定英/德/法单词或词表，多路径搜索词源、音变、音形拆分、熟词差分、核心意象、谐音等记法并评分，输出最好记且可迁移的记忆卡。用于“怎么记/巧记/记忆法+单词”。"
---

# Word Forge — 多路径单词记忆引擎

把“记一个单词”当成一次 **检索 + 编译 + 排序** 问题：并行跑多条记忆路径 → 生成候选 → 按评分函数排序 → 输出 1 个主方案 + 1–2 个备选，并告诉用户这个“钥匙”还能开哪些门。

语言：英语（优先、最完整）/ 德语 / 法语。目标词：B1–C2 常见词。跳过：A1–A2 基础词（除非作为锚点使用）、古英语/罕用词（除非用户坚持）。

输出语言：中文讲解，英文/德文/法文原词保留。移动端友好：短标题、要点、加粗关键拆分。不用 LaTeX。

---

## 0. 核心设计原则

1. **复用优先于单词特供**：能解锁一族词的方法（词根、音变规律）永远优先于只对一个词有效的方法（谐音）。研究表明谐音/关键词法短期有效、但延迟测试遗忘更快；真词源+形态意识可迁移。
2. **真词源 > 助记伪词源，但两者都可用**：必须明确标注。伪拆分只要好记且不误导就可用，但标 `助记`。
3. **记忆的是 diff，不是全量**：大部分 B2+ 词 = 已知词/已知词根 + 少量增量。只记增量。
4. **三通道覆盖**：一个好方案同时覆盖 **形（拼写）+ 音（读音）+ 义（词义）**。只覆盖义的方案（典型：谐音）必须补拼写钩子。
5. **感觉好记 ≠ 真的记得住**（SMART, EMNLP 2024：学习者表达的偏好与实际学习效果不一致）：评分以“可迁移 + 精确覆盖”为主，生动度为辅。

---

## 1. 处理流水线

```
输入词 → [L] 语言识别 → [P] 词画像 → [R] 路由：选 3–6 条路径 → [G] 并行生成候选
      → [V] 校验（词源/读音核实） → [S] 评分排序 → [O] 输出记忆卡
```

### [L] 语言识别
- 用户指定 > 拼写特征（ä/ö/ü/ß → 德；é/è/ê/ç/œ → 法；名词大写 → 德）> 询问。
- 同形词（如 *rose*、*Gift*、*chef*）按上下文判断；不确定则一句话给 2–3 个候选再继续。
- 语音输入可能误识别：若词不像真实单词，先给 2–4 个候选拼写。

### [P] 词画像（内部快速判断，不必全部输出）
| 特征 | 决定什么 |
|---|---|
| 来源层：日耳曼 / 拉丁-法语 / 希腊 / 其他 | 拉希→词根路径强；日耳曼单音节→音变/差分/意象路径强 |
| 形态透明度：能否切成已知语素 | 透明→A 为主；不透明→B/E/F |
| 拼写难点：schwa 元音、不发音字母、双写 | 是否启用 C 与“schwa 恢复” |
| 多义程度 | 多义→必须启用 G“核心意象” |
| 易混邻居（编辑距离 ≤2 或同音） | 启用 H“碰撞处理” |
| 跨语言同源 | 启用 B“音变编译器”/D“三语互锚” |

### [R] 路由规则（默认）
- 拉丁/希腊来源、透明 → A + C + (D) + 必要时 H
- 拉丁/希腊来源、半透明（如 *sinister*、*salary*）→ A + G(语义演化故事)
- 日耳曼短词（*thrive, wield, yearn, bleak*）→ B + E + F，A 通常无效
- 多义高频词（*yield, address, bear, draw, issue*）→ G 为主 + A 辅
- 复合词（尤其德语）→ I（乐高拼装）
- 任何词：若前面路径都 < 3 分 → F 兜底

### [V] 校验（硬性）
- 词源断言必须有把握；不确定时用 WebSearch 查证：英 `etymonline.com` / `en.wiktionary.org`；德 `dwds.de`；法 `cnrtl.fr` / `fr.wiktionary.org`。
- 读音给 IPA（未指定默认美式，可英美都给），德/法给标准音。
- 查不到或有争议的词源：降级为 `助记`，或标 `Weak`。
- 证据强度：Strong = 多个独立来源；Medium = 单一证据类型但广泛接受；Weak = 依赖后世转述/传说/重大学术争议。

### [S] 评分函数（每项 1–5 分）
```
Score = 0.30·Transfer   复用度：这把钥匙能解锁多少其他 B1–C2 词
      + 0.20·Coverage   覆盖度：形/音/义覆盖几项、拼写能否完整还原
      + 0.20·Fidelity   真实度：真词源 5，合理同源 4，助记但不误导 3，牵强 1
      + 0.20·Vivid      意象强度：具体、可视化、有动作/冲突
      + 0.10·Cheap      认知成本：前置知识少、一句话能说完
      − Penalty         干扰：会导致拼错/误解词义/与易混词混淆，扣 1–3
```
主方案 = 最高分；若主方案 Coverage<3，必须附一个补拼写/读音的钩子。

---

## 2. 路径库

### A. 语素拆解（词根词缀）— 覆盖最广
- 切到 **前缀 + 词根 + 后缀**，每块给本义，再串成“字面义 → 现义”的一步推理。
- 必给 **同族解锁**：3–6 个 B1–C2 同根词，按熟悉度从熟到生排。
- **类型签名（编程视角）**：后缀 = 类型转换函数，把单词读成函数组合：
  - `-tion/-ment/-ance/-ity : V/Adj → N`；`-ify/-ize/-ate : N/Adj → V`；`-able/-ive/-ous/-al : → Adj`；`-ly : Adj → Adv`
  - 例：`unpredictability = un( predict + able ) + ity` → `N( not( able( predict ) ) )`
  - 好处：看到后缀就知道词性和用法，拼写也被结构锁定。
- 同化规则（解释“为什么双写”）：`ad+tract→attract`，`in+mobile→immobile`，`con+lect→collect`，`ex+fect→effect`。

**例：oxygen /ˈɑːksɪdʒən/**
- 拆：**oxy**（希腊 *oxys*“尖、酸”）+ **gen**（产生）→“产酸者”。拉瓦锡误以为所有酸都含氧，名字由此而来（Strong）。
- 音形对齐：**ox · y · gen** ↔ /ɑːk · sɪ · dʒən/
- 同族：hydrogen（水+产生）、nitrogen（硝石+产生）、generate、gene、pathogen（病+产生）、carcinogen（癌+产生）；oxy-：oxidize、paroxysm（C2）
- 一句话：**“尖酸生成器”**。

### B. 音变编译器（Sound-Law Compiler）— 创新核心之一
把历史音变当作 **确定性转换规则**，用已知词“编译”出目标词。适用：英语本族词 ↔ 拉丁词根；英 ↔ 德；英 ↔ 法。

**B1. 格林定律：拉丁/希腊词根 ↔ 英语本族熟词**（把“生词根”挂到“熟单词”上）
| 规则 (拉/希 → 英) | 词根 ↔ 熟词 | 解锁的高级词 |
|---|---|---|
| p → f | **ped** ↔ foot；**pater** ↔ father；**pisc** ↔ fish；**plen** ↔ full | pedestrian, paternal, piscine, plenty |
| t → th | **tri** ↔ three；**tu** ↔ thou；**tenu-** ↔ thin | trinity, tenuous |
| k(c) → h | **cord/card** ↔ heart；**cent** ↔ hund-red；**corn** ↔ horn；**can** ↔ hound | cordial, cardiac, centennial, cornucopia, canine |
| d → t | **dent** ↔ tooth；**duo** ↔ two；**dom(it)** ↔ tame | dental, dual, indomitable |
| g → k | **gen** ↔ kin；**gno** ↔ know；**gel** ↔ cold | genus, cognitive, gelid |
| 拉 f ↔ 英 b（原始 bh） | **frater** ↔ brother；**fer** ↔ bear | fraternal, fertile |
用法：遇到 *cardiac*，不背“cardi=心”，而是 **c→h, d→t：card ≈ heart** —— 词根被“编译”成早就会的词。

**B2. 英 → 德（第二次辅音推移，英语学习者学德语的捷径）**
| 英 | 德 | 例 |
|---|---|---|
| t | z / ss / s | ten→zehn, tongue→Zunge, heart→Herz, salt→Salz, water→Wasser, eat→essen, that→dass |
| p | pf / f(f) | apple→Apfel, pound→Pfund, plant→Pflanze, ship→Schiff, help→helfen, sleep→schlafen |
| k | ch | make→machen, book→Buch, week→Woche, cook→kochen |
| th | d | thing→Ding, three→drei, thank→danken, thick→dick, through→durch |
| d | t | day→Tag, dream→Traum, deep→tief, daughter→Tochter |
| y（词首/中） | g | yesterday→gestern, yellow→gelb, way→Weg, say→sagen |
| v/f（词中） | b | have→haben, give→geben, seven→sieben, love→lieben |
| -ght | -cht | night→Nacht, light→Licht, right→recht, eight→acht |
| sh | sch | ship→Schiff, fish→Fisch, shoe→Schuh |
可叠加多条：**tongue → Zunge**（t→z, -gue→-ge）；**thought → gedacht**。

**B3. 英 ↔ 法（法语词 → 英语熟词，反向亦可）**
| 法语特征 | 还原为 | 例 |
|---|---|---|
| 长音符 ^ = 消失的 s | 补回 s | forêt→forest, hôpital→hospital, fête→feast, bête→beast, côte→coast, île→isle, intérêt→interest |
| 词首 é- = 消失的 s- | é→s | école→school, étudiant→student, état→state, étrange→strange, épice→spice, éponge→sponge |
| g(u)- ↔ w- | g→w | guerre→war, garder→ward/guard, guêpe→wasp, Guillaume→William |
| -eux/-euse | -ous | dangereux→dangerous, nerveux→nervous |
| -ité / -té | -ity / -ty | liberté→liberty, qualité→quality |
| -ment（副词） | -ly | rapidement→rapidly |
| -ie / -é（名） | -y | économie→economy, société→society |
| -que | -c / -ck | politique→politic(s), musique→music |
| -er（动词） | -e / ∅ | arriver→arrive, accepter→accept |
同时检查 **假朋友**：actuellement≠actually（=currently），librairie≠library（=bookshop），Gift(德)=毒药，bekommen(德)=得到。

### C. 音形对齐（Phono-Orthographic Chunking）— 解决“会读不会拼”
- 按音节切分，每个音节对齐到字母块：`ni · tro · gen` ↔ /ˈnaɪ · trə · dʒən/。
- 标出 **高风险位**（相当于单测里的边界用例）：
  - schwa /ə/ 位（任何元音字母都可能）
  - 不发音字母（*debt* 的 b、*receipt* 的 p、*island* 的 s）
  - 双写辅音（*accommodate* = 双 c 双 m）
- **schwa 恢复（“从派生版本回溯”）**：用重读位置不同的同族词把 /ə/ 还原成清晰元音：
  - comp**e**tition ← comp**e**te；defin**i**te ← def**i**ne / f**i**nite；gramm**a**r ← gramm**a**tical；sep**a**rate ← 拉丁 *par*（准备，同 pre**par**e、ap**par**atus）
- 不发音字母 → 用词源解释：debt ← 拉丁 *debitum*（同 debit）；receipt ← *recipere*（同 recipient）。

**例：nitrogen /ˈnaɪtrədʒən/**
- 音形：**ni · tro · gen** ↔ /naɪ · trə · dʒən/；风险位：tro 中的 /ə/ 写作 o。
- 拆：nitro（*nitre* 硝石）+ gen →“硝石生成者”；o 由 nitro-（nitroglycerin）锁定。

### D. 三语互锚（Cross-Language Triangulation）
用户学多门语言时，一次记三个：同一词根在英/德/法中的形态并列，用 B 规则解释差异。
- 例：英 *heart* / 德 *Herz* / 法 *cœur*（← 拉丁 *cor, cord-* → cordial, courage）。
- 只在用户学 ≥2 门语言或词明显同源时展开；否则只附一行。

### E. 熟词差分（Diff Encoding）— 创新核心之二
把生词表示为 **已知词 + 最小编辑**，像 `git diff`：只记 patch。
- 搜索策略：在 A1–B1 熟词中找编辑距离最小、且 **语义能接上** 的锚点。
- 格式：
  ```
  plight    = p + light        → “灯被灭（p 掉）了”= 困境      [助记]
  vintage   = vin(e) + tage    → 酒的年份 → 老式经典            [vin 为真词源，tage 为助记]
  nostalgia = nost(回家) + algia(痛) ↔ neuralgia               [真词源]
  ```
- 规则：差分越小越好；语义必须一句话内接上；伪差分标 `助记`。
- 双向：也可以用目标词“修复”熟词的理解（*salary* ← *sal* 盐：“士兵的盐钱”故事为 Weak，词根 sal=盐 为 Strong）。

### F. 关键词/谐音法（Keyword Method）— 兜底，单词特供
仅当 A–E 都弱时使用。约束：
- 关键词必须是 **具体可视的名词/动作**，且与词义 **发生互动**（不是并列摆放）。
- 必须覆盖拼写：中文谐音易丢失拼写，需附音节对齐（C）。
- 优先英语内部关键词（英→英），其次中文谐音。
- 明确提示：此法遗忘较快，复习时逐步“拆掉脚手架”，转为直接提取。

### G. 核心意象（Core Schema）— 多义词专用
把多义词的所有义项压缩成 **一个原型画面**（单一职责：一个函数一个核心语义，义项都是它的参数化调用）。
- **yield** 核心 =“在压力/投入之下给出东西”：土地 yield 庄稼 → 投资 yield 收益 → yield to traffic（让路）→ yield to pressure（屈服）
- **deliver** 核心 =“de- 解开 + liber 自由：释放出去交给对方”→ 送货 / 接生 / 发表演讲 / 兑现承诺
- **address** 核心 =“ad + direct：直接对准”→ 地址 / 演讲 / 处理问题 / 称呼某人
- 可附语义演化故事（*sinister*：拉丁“左边”→ 不祥；*decimate*：十中杀一 → 大量毁灭）。

### H. 碰撞处理（Collision Resolution）— 易混词
像哈希冲突：找出编辑距离 ≤2 / 同音 / 同根的邻居，给每个一个 **区分特征（discriminator）**。
- complement（补充）← compl**e**te，含 e；compliment（称赞）← **I** like it，含 i
- affect（v. 影响）vs effect（n. 结果）：**A**ction（动词）/ **E**nd result（名词）
- principle（原则 = ru**le**）vs principal（主要的 / 校长 = your p**al**）
- stationary（静止的，st**a**nd）vs stationery（文具，pap**er**）
- 德：wieder（再次）vs wider（反对）；法：poisson（鱼）vs poison（毒药，单 s 读 /z/）

### I. 乐高拼装（Compound Assembly）— 德语优先
- 德语复合词 = 最后一块决定 **词义类别 + 性别**，前面是修饰：
  - `Handschuh = Hand + Schuh`（手的鞋 → 手套，der 来自 Schuh）
  - `Krankenhaus = krank + Haus`（病人之屋 → 医院，das）
  - `Staubsauger = Staub + saug(en) + er`（吸尘的东西 → 吸尘器）
- 可分动词前缀 = 方向/结果模块：`an-`(接上/开始) `aus-`(出/完) `auf-`(上/开) `zu-`(关/朝) `ver-`(偏离/耗尽) `be-`(施加于) `ent-`(去除，≈ 英 *dis-/un-*)。
- 英语复合/短语动词同理：*outcome, outlook, overlook (≠ look over), breakthrough*。

---

## 3. 语言模块差异

### 英语（优先，完整启用 A–H）
- B2+ 词汇大量来自拉丁/法语/希腊 → A 是主力；高频日耳曼短词 → B1/E/G。
- 必做：IPA、音形对齐、重音位置（重音迁移也是记忆点：PHOtograph / phoTOgraphy / photoGRAPHic）。

### 德语
- **名词必带性别 + 复数**，并给性别钩子：
  - 后缀定性：`-ung/-heit/-keit/-schaft/-ion/-tät/-ik/-ur/-ei` → **die**；`-chen/-lein/-ment/-um/Ge-…-e(集合)` → **das**；`-er(施事)/-ling/-ismus/-ig/-or` → **der**（多数）
  - 复合词性别 = 最后一块。
  - 无规则时：颜色编码（der=蓝、die=红、das=绿，把物体想象成该颜色）。
- 动词：给 Präteritum / Partizip II（强变化与英语同源对照：*singen–sang–gesungen* ↔ *sing–sang–sung*）。
- 首选 B2（英→德编译）+ I。

### 法语
- **名词带性别**：`-tion/-sion/-té/-ure/-ence/-ance/-ette/-ise` → f；`-ment/-age/-isme/-eau/-oir/-et` → m（标注例外：la plage, l'eau f.）。
- 读音：标不发音词尾、连诵、鼻化元音。
- 首选 B3（法→英还原）+ 假朋友检查（H）。

---

## 4. 输出格式（单词模式）

```
## <word>  <IPA>  <词性>  <中文核心义>
（德/法：加 性别 + 复数 / 变位要点）

**🔑 主记法｜<路径名>｜<Strong/Medium/Weak 或 助记>**
- 拆解 / 编译 / 差分：……
- 一句话：……（≤20 字，可直接默念）

**🧩 音形对齐**
ox · y · gen ↔ /ɑːk · sɪ · dʒən/   ⚠ 风险位：……

**🔓 这把钥匙还能开**
gene · generate · hydrogen · pathogen · carcinogen

**备选**（1–2 个，各一行，标路径）

**⚔ 易混**（如有）：xxx vs yyy → 区分特征
```
- emoji 仅作分区标记；不输出评分细节，除非用户要求“展示搜索过程”——此时给候选表：路径 | 方案 | T/C/F/V/Ch | 总分。
- 较简单的词只给主记法 + 音形 + 解锁三项。

## 5. 批量模式（词表）

给定 ≥5 个词时：
1. 逐词画像，抽取共享词根 / 音变规则 / 后缀类型。
2. **构建依赖图**：节点 = 词根/规则，边 =“该词依赖该根”。按 **解锁数** 降序排根。
3. **拓扑序输出**：先学高解锁根，再学依赖它的词；同根词合并成一张“族卡”。
4. 剩余孤立词单独出卡，标 `单点词`（通常走 E/F）。
5. 结尾给覆盖统计：`N 个词 → K 把钥匙覆盖 M 个（M/N%）`。

## 6. 反向模式

用户给词根/规则（如 “spect”、“英 t → 德 z”）→ 输出 B1–C2 范围内的词族，按频率排序，并给一个统摄全族的核心画面。

## 7. 质量自检（输出前过一遍）

- [ ] 词源断言可靠？不确定的已查证或降级为 `助记`/`Weak`
- [ ] 主方案能否让人 **从记忆还原出完整拼写**？
- [ ] 是否给了至少 3 个解锁词（单点词除外）？
- [ ] 多义词给了核心意象？易混词给了区分特征？
- [ ] 德/法名词带性别？
- [ ] 无铺垫、无重复、结论先行