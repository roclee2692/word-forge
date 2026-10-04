# word-forge

A Claude skill that builds memory cards for English / German / French words (B1–C2), plus a segmentation algorithm that computes the cheapest-to-remember way to split a word.

- `SKILL.md` — the skill itself (Chinese). The live copy is saved in the user's Claude account; this file mirrors it. Keep them in sync.
- `scripts/wordseg.py` — segmentation algorithm (English only).
- `README.md` — public overview.

The user is Raelon. Reply in Chinese, conclusion first, high information density, no filler. The repo is public at github.com/roclee2692/word-forge.

## Run

```
pip install wordfreq cmudict
python3 scripts/wordseg.py redundant strawberry --k 3   # add --json for machine output
```

## How wordseg.py works

1. Grapheme–phoneme alignment DP against CMUdict: tags each letter group as regular / variant / silent / irregular and flags schwa positions.
2. Aho–Corasick automaton over ~30k frequent English words, the German/French top-3000 lists and a morpheme table (`MORPHS`) finds every known chunk in one pass.
3. k-best segmentation DP (shortest path over positions 0…n). Edge costs: frequent words are cheap (cheaper again when their pronunciation matches that span), morphemes ~0.9, pronounceable syllable chunks 1.3, single letters most expensive, plus a fixed cost per chunk. Greedy longest-match is printed only as a baseline.
4. Collision detection: frequent words one edit away, chunks that become a frequent word by swapping adjacent letters (entre ↔ enter), look-alike chunks (prise ↔ price).

Output marks paths made entirely of known words with ★ and lists every identity of each chunk ("一块多义"), e.g. ant = English word (蚂蚁) / suffix, und = German word.

## Selection rules (where past mistakes happened)

The algorithm only covers spelling and sound; choosing the main mnemonic is a separate step, and that step is where things went wrong before.

- A ★ path (all known words) is the default main mnemonic: turn the chunks into one picture tied to the meaning. redundant = red + und (German "and") + ant → "红色和蚂蚁，多余". Do not drop it because it is not the real etymology; label it 助记.
- Only use a root as the main mnemonic when the root itself is common (spec, port, vers). Rare roots (luct, und = wave) go to the 📎 原理 line only.
- Look at every identity of a chunk before choosing.
- When there is no ★ path, fall back to phonics + word family (reluctant: re·luc·tant, reluctance, reluctantly).
- Words that share a start and end (reluctant / redundant) get one comparison card that only covers the middle.
- Main hook: at most one inference step, concrete; confusable words go first on the card.

## Known issues / ideas

- No concreteness or imageability data yet: ★ marks "all known words", not "easy to picture". A concreteness lexicon (e.g. Brysbaert ratings) would let the cost function prefer nouns you can see.
- Foreign-word list adds some noise for short chunks (re, en); chunks under 3 letters are excluded from ★.
- Morpheme table is hand-written and small; month-suffix entries (`ber`, `uary`) are ad hoc.
- English only; German/French cards still rely on the rules in SKILL.md.

## TODO

- Push the local commits to GitHub.
- In SKILL.md §7, make the public raw URL the first way to fetch the script:
  `https://raw.githubusercontent.com/roclee2692/word-forge/main/scripts/wordseg.py`
  (then update the saved skill in the Claude account too).

## Git notes

Commit as `Developer <roclee2692@gmail.com>` to match the existing history.
