# IELTS Spelling Coach

A static website for practising the spelling of about 2,450 IELTS words.
Hear a word, type it, and see its meaning, an example, its IPA, synonyms and antonyms. Works on phone and laptop.
No backend, no database, no accounts, no cookies, no analytics: word data is a static file, and progress is stored only in the visitor's own browser (`localStorage`).

## Features

- The ⚙ Settings button holds words at a time (20, 30, 50 or 100), mistakes allowed, how long a wrong letter stays visible, voice, speed, PDF export and the reset buttons; **Show more** adds the next batch, and **New random set** reshuffles in Random order. Each row has a clue card (British IPA, part of speech, up to 3 synonyms and 2 antonyms, one learner-friendly meaning with an example) and a typing card
- Text-to-speech pronunciation with a British voice where available. Voice and speed can be changed
- Live letter checking: a wrong letter shows in red for a moment (0.3–2 s, or not at all), is then removed, and counts as a mistake. After the allowed number of mistakes (1–10 or unlimited, default 5) the word is shown and the next one starts. A finished word moves straight on to the next one, which scrolls into view (on phones the keyboard stays open). Only the word itself is ever spoken
- The word is blanked out of its definition, example, synonyms and antonyms until you answer (including inside longer words, such as un___ for unhappy)
- Filters: 18 topics (the full Academic Word List, Writing Task 1 and 2 language, IELTS topic vocabulary, commonly misspelled words, advanced academic words), CEFR level (A1–C2), new words, mistakes, not mastered
- **Top 100 / 300 / 500 / 1,000 / 1,500 / All**: the most useful words for IELTS spelling, taken from the official IELTS sources. Every Top list is filled in fixed shares: 33% [Academic Word List](https://www.wgtn.ac.nz/lals/resources/academicwordlist) (Reading and Writing), 30% [IDP's common IELTS Listening vocabulary](https://ielts.idp.com/prepare/article-common-vocabulary-ielts-listening) (a misspelled Listening answer scores zero), 15% commonly misspelled words, 12% Writing Task 1 and 2 language and 10% IELTS topic vocabulary. Within each source the most important words come first: AWL sublist 1 before sublist 10, the words IDP says candidates misspell, the classic spelling traps (accommodation, necessary, separate, definitely…), frequent words, words that are hard to spell, and B1–C1 words (IELTS bands 5.5–8) before very easy ones. Top 300 has 90 of IDP's Listening words, 87 words from the AWL's first two sublists and 45 commonly misspelled words; Top 1,000 has every IDP word family. Each Top list has one word per family (development, not also develop; relevant, not also irrelevant). To practise harder words, combine a Top list with the C1 or C2 level filter
- Order: Top first, at random, or A to Z
- Progress and settings are saved in the browser (localStorage). A word counts as mastered after 3 mistake-free answers in a row. **Export progress** downloads a PDF report (summary, progress per CEFR level, words to review with meanings, mastered words); **Reset all** clears everything
- British and American spellings are both accepted (organise/organize, colour/color)
- One soft light (neumorphic) theme using system fonts, works on phone and laptop, autocorrect is turned off in the answer box
- A short privacy notice on first visit (dismissed once, remembered in `localStorage`), a [privacy page](privacy.html) and a custom 404 page

### Keyboard shortcuts

| Key | Action |
| --- | --- |
| `Esc` | Hear the word (`Shift`+`Esc` plays it slowly) |
| `Enter` | Hear the word again, or go to the next word once it's done |
| `↑` `↓` / `←` `→` | Previous / next word |

## Run locally

Use the preview server, which sends the same headers as Vercel (Content-Security-Policy and the rest) and supports clean URLs such as `/privacy`:

```bash
python3 tools/serve.py
```

Then open http://127.0.0.1:8765 (pass a port number to use another one). Any static file server also works, but it won't apply the security headers.

## Deploy to Vercel

The site is plain HTML, CSS and JS, so there is no build step.

1. Push this folder to a GitHub repository and import it in Vercel. Set the framework preset to **Other** and leave the build command empty.
2. Or deploy it from the CLI: `npx vercel` (and `npx vercel --prod` for production).

`.vercelignore` keeps the Python tooling out of the deployment.

## Privacy and security

- The site collects no personal data: no cookies, no analytics, no tracking, no third-party fonts. Progress and settings stay in the visitor's browser under the keys `isp.progress.v1`, `isp.prefs.v1` and `isp.notice.v1`, and **Reset all** removes them.
- The only third-party request is jsPDF (pinned version with an integrity hash) from cdnjs, loaded only when someone clicks **Export progress**.
- `vercel.json` sets a strict Content-Security-Policy (`default-src 'none'`, scripts only from the site and cdnjs, no inline scripts or styles, no framing), HSTS, `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, COOP/CORP and a Permissions-Policy that turns off camera, microphone, location and similar features.
- `privacy.html` explains this in plain language. It is a starting point, not legal advice: if you add analytics, ads or accounts later, update the page and the notice.

## Project structure

```
index.html              page markup: filters, word rows, footer, privacy notice
privacy.html            privacy page
404.html                page shown for unknown URLs
css/styles.css          neumorphic light theme (system fonts)
js/app.js               app logic: filters, show more, speech, live checking, progress, PDF export
data/words.js           generated word data (window.IELTS_WORDS), committed
favicon.svg
vercel.json             Vercel headers (clean URLs, cache revalidation, security headers)
tools/serve.py          local preview server with the vercel.json headers
tools/wordlist.txt      curated word list, grouped by topic (edit this to add words)
tools/build_data.py     regenerates data/words.js
tools/curated.json      hand-checked definitions, examples, IPA, synonyms and antonyms
tools/cefr/             CEFR-J (A1–B2) and Octanove (C1–C2) vocabulary profiles
tools/ielts/            Academic Word List sublists and IDP IELTS Listening vocabulary
```

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

### How each entry is chosen

- **One meaning per word.** The build keeps only the most useful sense, tidies the definition (removes labels, brackets and dictionary jargon) and picks an example that uses the word.
- **IPA** is British (Received Pronunciation style) and written the same way for every word: `r` (not `ɹ`), `e` (not `ɛ`), `ɡ`, `aɪ`/`aʊ`, final `-i` as in /ˈhæpi/, no syllable dots. `clean_ipa()` in `build_data.py` converts dictionary transcriptions to this style and rejects anything that looks American (`ɚ`, `oʊ`, `ɑ` without length, a pronounced `r` before a consonant) or contains unexpected symbols, so it is better to have no generated IPA than a wrong one.
- **Synonyms and antonyms** must not give the answer away: no spelling variants (organization for organisation) and no words that contain the answer.

### curated.json

`tools/curated.json` holds hand-checked fixes, keyed by headword. Every field is optional, and any field present replaces the generated value:

```json
{
  "found": {
    "pos": "verb",
    "def": "To start an organisation, company or city.",
    "ex": "The university was founded in 1850.",
    "ipa": "/faʊnd/",
    "syn": ["establish", "set up", "create"],
    "ant": ["abolish", "close"]
  }
}
```

An empty list (`"ant": []`) removes the generated clues. `"f"` overrides the word frequency where wordfreq is misleading ("found" is counted as the past tense of "find"). An entry with `pos`, `def` and `ex` also covers a word the dictionaries don't have (eco-friendly, whilst). A definition must not contain the word itself, and the example should match the sense of the definition.

### Data entry format

```js
{ w: "accommodation", t: "Urban Life, Housing & Transport", f: 4.1, c: "B2", r: 41, ipa: "/əˌkɒməˈdeɪʃən/",
  alt: [], m: [{ pos: "noun", def: "…", ex: "…" }], syn: ["lodging", "housing"], ant: [] }
```

`m` always has exactly one meaning. The app shows at most 3 synonyms and 2 antonyms.
