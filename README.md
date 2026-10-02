# Word Forge

A Claude skill that finds the most memorable way to learn a word in English, German or French. It searches several memory paths at once, scores each candidate, and returns a compact memory card.

- **Languages:** English (most complete), German, French
- **Target words:** B1–C2 vocabulary
- **Output:** Chinese explanations; the original words stay in their own language

## How it works

```
word → detect language → profile the word → pick 3–6 paths → generate candidates
     → verify etymology & IPA → score & rank → memory card
```

Each candidate gets a score from 1 to 5 on five criteria: how many other words it unlocks (30%), spelling, sound and meaning coverage (20%), etymological accuracy (20%), vividness (20%) and how easy it is to pick up (10%). Candidates that would cause misspellings or confusion lose points.

## Memory paths

| Path | Idea |
|---|---|
| A. Morpheme decomposition | prefix + root + suffix, with suffixes read as type conversions (`un(able(predict))+ity`) |
| B. Sound-law compiler | Grimm's law (card ↔ heart), English→German consonant shift (tongue → Zunge), French→English (forêt → forest, école → school) |
| C. Phono-orthographic chunking | syllable ↔ spelling alignment, high-risk positions, recovering schwa spellings from related words (competition ← compete) |
| D. Cross-language triangulation | heart / Herz / cœur |
| E. Diff encoding | new word = known word + a minimal patch (plight = p + light) |
| F. Keyword method | fallback only; it fades faster in delayed tests |
| G. Core schema | one prototype image for a polysemous word (yield, deliver, address) |
| H. Collision resolution | discriminators for confusable words (complement / compliment) |
| I. Compound assembly | German compounds and separable prefixes (Hand + Schuh = Handschuh) |

## Modes

- **Single word:** a memory card with the main method, IPA chunking, the word family it unlocks, alternatives and confusables
- **Batch:** build a root-dependency graph, learn the roots that unlock the most words first, and report coverage
- **Reverse:** give a root or a sound rule and get its B1–C2 word family

## Install

Put `SKILL.md` into a `word-forge/` folder inside your Claude skills directory (for example `~/.claude/skills/word-forge/SKILL.md`), or upload it as a custom skill in Claude.

## Example

```
semaphore /ˈseməfɔːr/: sema (sign) + phore (bearer; Greek pher ↔ Latin fer ↔ English bear)
unlocks: semantic · polysemy · metaphor · euphoria · pheromone · phosphorus
```

## References

- Balepur et al., *A SMART Mnemonic Sounds like "Glue Tonic"*, EMNLP 2024
- Lee et al., *Exploring Automated Keyword Mnemonics Generation with LLMs via Overgenerate-and-Rank*, EMNLP 2024 Findings
- Wang & Thomas, keyword mnemonic and long-term retention
- Grimm's law; High German consonant shift; circumflex in French
