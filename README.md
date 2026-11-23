# IELTS Spelling Coach

A static website for practising the spelling of 2,300+ high-frequency IELTS words.
Hear a word, type it, and see its meaning, synonyms and antonyms. Works on phone and laptop.
No backend or database: word data is a static file, and progress is stored in the browser (`localStorage`).

## Features

- The ⚙ Settings button holds words at a time (20, 30, 50 or 100), mistakes allowed, voice and speed; **Show more** adds the next batch, and **New random set** reshuffles in Random order. Each row has a clue card (IPA, part of speech, synonyms, antonyms, meaning) and a typing card
- Text-to-speech pronunciation with a British voice where available. Voice and speed can be changed
- Live letter checking: a wrong letter is rejected as you type and counts as a mistake. After the allowed number of mistakes (1–10 or unlimited, default 5) the word is shown and the next one starts. A correct word moves on automatically. Only the word itself is ever spoken
- The word is blanked out of its definition until you answer
- Filters: 18 topics (the full Academic Word List, Writing Task 1 and 2 language, IELTS topic vocabulary, commonly misspelled words, advanced academic words), CEFR level (A1–C2), new words, mistakes, not mastered
- Order by frequency, at random, or A to Z
- Progress and settings are saved in the browser (localStorage). A word counts as mastered after 3 mistake-free answers in a row. **Export progress** downloads a PDF report (summary, progress per CEFR level, words to review with meanings, mastered words); **Reset all** clears everything
- British and American spellings are both accepted (organise/organize, colour/color)
- One soft light (neumorphic) theme, works on phone and laptop, autocorrect is turned off in the answer box

### Keyboard shortcuts

| Key | Action |
| --- | --- |
| `Esc` | Hear the word (`Shift`+`Esc` plays it slowly) |
| `Enter` | Hear the word again, or go to the next word once it's done |
| `↑` `↓` / `←` `→` | Previous / next word |

## Run locally

Any static file server works:

```bash
python3 -m http.server 8000
```

Then open http://localhost:8000.

## Deploy to Vercel

The site is plain HTML, CSS and JS, so there is no build step.

1. Push this folder to a GitHub repository and import it in Vercel. Set the framework preset to **Other** and leave the build command empty.
2. Or deploy it from the CLI: `npx vercel` (and `npx vercel --prod` for production).

`.vercelignore` keeps the Python tooling out of the deployment. The page loads the Nunito font from Google Fonts, and the PDF libraries (jsPDF, pinned with integrity hashes) from cdnjs only when you export.

## Project structure

```
index.html              page markup: filters, word rows, footer
css/styles.css          neumorphic light theme
js/app.js               app logic: filters, show more, speech, live checking, progress, PDF export
data/words.js           generated word data (window.IELTS_WORDS), committed
favicon.svg
vercel.json             Vercel headers (cache revalidation, security headers)
tools/wordlist.txt      curated word list, grouped by topic (edit this to add words)
tools/build_data.py     regenerates data/words.js
tools/overrides.json    hand-written entries for words the dictionaries miss
tools/cefr/             CEFR-J (A1–B2) and Octanove (C1–C2) vocabulary profiles
.claude/agents/         code-reviewer agent for Claude Code
```

## Code review

The project includes a Claude Code agent at `.claude/agents/code-reviewer.md`. It checks for bugs, data integrity, accessibility, security and maintainability. In Claude Code, ask: "use the code-reviewer agent to review the site".

## Regenerating the word data

`build_data.py` combines several sources:

- the [Free Dictionary API](https://dictionaryapi.dev) (Wiktionary) for definitions, examples and IPA
- WordNet (via NLTK) for meaning ranking, extra examples, synonyms and antonyms
- the [Datamuse API](https://www.datamuse.com/api/) for synonyms and antonyms ranked by usage
- [`wordfreq`](https://github.com/rspeer/wordfreq) for word frequency (ordering) and for filtering out obscure synonyms
- CEFR levels from the open [CEFR-J Vocabulary Profile](https://github.com/openlanguageprofiles/olp-en-cefrj) (A1–B2) and the Octanove Vocabulary Profile (C1–C2, CC BY-SA 4.0), stored in `tools/cefr/`. Words missing from both lists get the level of their base word (consistently → consistent), or an estimate from frequency

```bash
python3 -m venv .venv
.venv/bin/pip install nltk wordfreq
.venv/bin/python -c "import nltk; nltk.download('wordnet', download_dir='.venv/nltk_data')"
NLTK_DATA=.venv/nltk_data .venv/bin/python tools/build_data.py
```

Add `--offline` to rebuild from the cache without any network requests.

API responses are cached in `tools/.cache.json`, so re-runs after editing `wordlist.txt` only fetch the new words.

### Data entry format

```js
{ w: "accommodation", t: "Urban Life, Housing & Transport", f: 4.1, c: "B2", ipa: "/əˌkɒməˈdeɪʃən/",
  alt: [], m: [{ pos: "noun", def: "…", ex: "…" }], syn: ["lodging", "housing"], ant: [] }
```
