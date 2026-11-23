"""Build data/words.js from tools/wordlist.txt.

Definitions, examples and IPA come from the Free Dictionary API (Wiktionary), with WordNet
(via nltk) for meaning ranking and extra synonyms/antonyms. Synonyms/antonyms also come from
the Datamuse API, word frequency from wordfreq, and CEFR levels from the CEFR-J/Octanove
profiles in tools/cefr/. Hand-checked fixes in tools/curated.json win over all of these.
Each word also gets a usefulness rank for the Top N lists, from the official IELTS sources in
tools/ielts/ (Academic Word List, IDP Listening vocabulary).
API responses are cached in tools/.cache.json; --offline rebuilds from the cache only.

Run:  NLTK_DATA=.venv/nltk_data .venv/bin/python tools/build_data.py [--offline]
"""
import csv
import json
import os
import re
import sys
import threading
import urllib.parse
import urllib.request
import urllib.error
import time
from concurrent.futures import ThreadPoolExecutor

from nltk.corpus import wordnet as wn
from wordfreq import zipf_frequency

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIST = os.path.join(ROOT, "tools", "wordlist.txt")
CURATED = os.path.join(ROOT, "tools", "curated.json")
CACHE = os.path.join(ROOT, "tools", ".cache.json")
OUT = os.path.join(ROOT, "data", "words.js")

SKIP = {"sex", "pros", "cons", "bar", "pie", "jam", "rush", "gap", "gas", "fast",
        "junk", "death", "life", "heart", "blood", "job-satisfaction", "sea-level",
        "acid", "rain", "global", "warming", "human", "mass", "print", "role", "model",
        "prime", "zone", "which", "coming", "plus", "odd", "tape", "file", "bus", "taxi", "state", "private", "public", "distance", "space", "social"}

BAD_LABEL = re.compile(r"\((obsolete|archaic|dated|rare|slang|vulgar|nautical|heraldry|dialect|uncommon|historical)", re.I)

POS_NAME = {"n": "noun", "v": "verb", "a": "adjective", "s": "adjective", "r": "adverb"}

# British -> American spellings, used for dictionary lookup and accepted answers.
OUR_WORDS = ["colour", "behaviour", "labour", "favour", "honour", "neighbour", "humour",
             "rumour", "vapour", "harbour", "flavour", "endeavour", "saviour", "vigour",
             "tumour", "favourable", "neighbourhood", "humorous"]


def american_variants(w):
    out = set()
    v = w
    for a, b in [("isation", "ization"), ("ise", "ize"), ("ising", "izing"), ("ised", "ized"),
                 ("yse", "yze"), ("yser", "yzer")]:
        if a in v and not w.startswith(("advertis", "compromis", "exercis", "supervis", "surpris",
                                        "televis", "revis", "promis", "rais", "advis", "wise",
                                        "precis", "concis", "premis", "expertis", "franchis",
                                        "merchandis", "otherwis", "devis", "despis", "chastis",
                                        "disguis", "enterpris", "excis", "incis", "improvis")):
            v = v.replace(a, b)
    if v != w:
        out.add(v)
    for base in OUR_WORDS:
        if base in w and base != "humorous":
            out.add(w.replace("our", "or"))
    repl = {"centre": "center", "theatre": "theater", "fibre": "fiber", "litre": "liter",
            "metre": "meter", "tumour": "tumor", "programme": "program", "defence": "defense",
            "offence": "offense", "licence": "license", "practise": "practice",
            "catalogue": "catalog", "dialogue": "dialog", "ageing": "aging",
            "fertiliser": "fertilizer", "traveller": "traveler", "enrolment": "enrollment",
            "enrol": "enroll", "jewellery": "jewelry", "judgement": "judgment",
            "skeptical": "sceptical", "grey": "gray", "cheque": "check", "tyre": "tire",
            "aluminium": "aluminum", "mould": "mold", "plough": "plow", "analyse": "analyze",
            "paralyse": "paralyze", "civilisation": "civilization", "westernisation": "westernization"}
    for a, b in repl.items():
        if a in w:
            out.add(w.replace(a, b))
    if w.endswith("lled") or w.endswith("lling") or w.endswith("ller"):
        out.add(re.sub(r"ll(ed|ing|er)$", r"l\1", w))
    out.discard(w)
    return sorted(out)


CEFR_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]
CEFR_FILES = ["cefrj-vocabulary-profile-1.5.csv", "octanove-vocabulary-profile-c1c2-1.0.csv"]
SUFFIXES = [("ically", "ic"), ("ally", "al"), ("ily", "y"), ("ly", ""), ("ness", ""), ("ment", ""),
            ("ation", "e"), ("ation", ""), ("ition", "e"), ("ion", "e"), ("ion", ""), ("ity", "e"),
            ("ive", "e"), ("ed", "e"), ("ed", ""), ("ing", "e"), ("ing", ""), ("es", ""), ("s", ""),
            ("er", ""), ("est", ""), ("ist", ""), ("ism", "")]


def load_cefr():
    """Lowest CEFR level per headword from the CEFR-J (A1-B2) and Octanove (C1-C2) profiles."""
    levels = {}
    for name in CEFR_FILES:
        with open(os.path.join(ROOT, "tools", "cefr", name), encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row["CEFR"] not in CEFR_ORDER:
                    continue
                for head in row["headword"].split("/"):
                    head = head.strip().lower()
                    if head and (head not in levels or CEFR_ORDER.index(row["CEFR"]) < CEFR_ORDER.index(levels[head])):
                        levels[head] = row["CEFR"]
    return levels


def phrase_zipf(text):
    """Zipf frequency; wordfreq scores "part-time" almost like "part", so lower it per extra part."""
    parts = re.split(r"[-\s]+", text)
    return zipf_frequency(" ".join(parts), "en") - min(1.8, 1.0 * (len(parts) - 1))


# ---- ranking: "Top 100 / 300 / 500 / ..." = the most useful words for IELTS spelling ----
# Every Top list is filled from the official IELTS sources in fixed shares, so even Top 100 covers
# all of them, and each source's most important words come first:
#   academic    Academic Word List (Coxhead), the core vocabulary of Reading and Writing
#   listening   IDP's common IELTS Listening vocabulary (IDP co-owns IELTS). A misspelled answer
#               scores zero in Listening, so spelling these matters most
#   writing     Writing Task 1 (charts, trends) and Task 2 (argument, linking) language
#   misspelled  words that IELTS candidates commonly misspell
#   topic       vocabulary for the common IELTS topics (environment, health, work, ...)
# A word belongs to the first of these that lists it, in the order: listening, misspelled,
# academic, writing, topic.
SOURCE_SHARE = {"academic": 0.33, "listening": 0.30, "misspelled": 0.15, "writing": 0.12, "topic": 0.10}

# The classic spelling traps found on practically every "commonly misspelled words" list; they
# come first among the misspelled words (+1.0)
CLASSIC_TRAPS = {
    "accommodation", "necessary", "separate", "definitely", "embarrass", "occurrence", "receive",
    "recommend", "beginning", "committee", "rhythm", "conscious", "government", "environment",
    "until", "tomorrow", "address", "believe", "achieve", "privilege", "possession", "occasionally",
    "foreign", "weird", "calendar", "february", "wednesday", "independent", "existence",
    "successful", "immediately", "parliament", "restaurant", "acquaintance", "maintenance",
}

# Within a source, a word's usefulness is the sum of:
#   frequency      Zipf frequency in general English (wordfreq)
#   listening      on IDP's list (+1.0), and +0.5 more if IDP says test takers often misspell it
#   academic       Academic Word List sublist: +3.4 for sublist 1 (most frequent) down to +0.25 for 10
#   topic          IELTS topic and Writing vocabulary, or the commonly misspelled list
#   classic trap   +1.0 for the words in CLASSIC_TRAPS
#   difficulty     how hard the word is to spell (double letters, silent letters, tricky endings,
#                  length), so easy-to-spell words like "merit" don't crowd out "accommodation"
#   level          CEFR: IELTS bands 5.5-8 match B2-C1, and A1/A2 words are rarely misspelled, so
#                  B1-C1 come first (not applied to words on a misspelled list, which stay high)
LEVEL_ADJUST = {"A1": -1.5, "A2": -0.8, "B1": 0.0, "B2": 0.3, "C1": 0.3, "C2": -0.2}
TOPIC_BONUS = {
    "Commonly Misspelled Words": 1.0,
    "Writing Task 1: Charts & Trends": 0.5,
    "Writing Task 2: Argument & Linking": 0.5,
    "Common Verbs & Adjectives for IELTS": 0.2,
    "Academic Core": 0.0,  # scored by AWL sublist instead
    "Advanced Academic Words": 0.0,
}
OTHER_TOPIC_BONUS = 0.3  # IELTS topic vocabulary (Environment, Education, IELTS Listening, ...)
LISTENING_BONUS, LISTENING_MISSPELLED_BONUS = 1.0, 0.5
DIFFICULTY_WEIGHT = 0.8

IELTS_DIR = os.path.join(ROOT, "tools", "ielts")


def _read_lists(name):
    """Lines "<key>: a, b, c" in tools/ielts/<name> -> {key: set of lowercase words}."""
    out = {}
    for line in open(os.path.join(IELTS_DIR, name), encoding="utf-8"):
        if ":" in line and not line.startswith("#"):
            key, words = line.split(":", 1)
            out[key.strip()] = {w.strip().lower() for w in words.split(",") if w.strip()}
    return out


_idp = _read_lists("idp_listening.txt")
IDP_MISSPELLED = _idp.pop("misspelled")
IDP_LISTENING = set().union(*_idp.values()) | IDP_MISSPELLED
AWL_SUBLIST = {}
for _n, _forms in sorted(_read_lists("awl_sublists.txt").items(), key=lambda kv: -int(kv[0])):
    AWL_SUBLIST.update({f: int(_n) for f in _forms})  # a form in two sublists keeps the lower number

# Patterns that make English words hard to spell; each match adds to the difficulty.
TRICKY_SPELLING = [
    r"([a-z])\1",                       # double letters: accommodation, committee
    r"ough|augh|eigh",                  # thought, height
    r"^ps|^pn|^kn|^wr|mn$|mb$|gn",      # silent letters: psychology, autumn, foreign
    r"dnes|rnm|bt|stl|[aeiou]lk|[aeiou]lm",  # Wednesday, government, debt, castle, talk, calm
    r"rh|ph",                           # rhythm, phenomenon
    r"sc[eiy]",                         # science, conscious
    r"ei|ie",                           # receive, believe
    r"[iu]ous$|eous$",                  # various, courageous
    r"[ae]nce$|[ae]nt$|[ai]ble$",       # existence, independent, responsible
    r"que$|cq|ch[aeiour]",              # technique, acquire, character
    r"ae|oe|ai(?!n)",                   # aesthetic, Wednesday
    r"y[^aeiou]",                       # rhythm, analysis
]


def spelling_difficulty(word):
    w = word.lower()
    score = 0.2 * sum(len(re.findall(p, w)) for p in TRICKY_SPELLING)
    score += min(0.4, max(0, len(w) - 7) * 0.06)
    return min(score, 1.2)


def usefulness(e):
    forms = {e["w"].lower(), *e["alt"]}
    topics = LISTED_IN.get(e["w"].lower(), {e["t"]})
    score = e["f"] + max(TOPIC_BONUS.get(t, OTHER_TOPIC_BONUS) for t in topics)
    if forms & IDP_LISTENING:
        score += LISTENING_BONUS
    if forms & IDP_MISSPELLED:
        score += LISTENING_MISSPELLED_BONUS
    sublists = [AWL_SUBLIST[f] for f in forms if f in AWL_SUBLIST]
    if sublists:
        score += 3.75 - 0.35 * min(sublists)
    if not (forms & IDP_MISSPELLED or "Commonly Misspelled Words" in topics):
        score += LEVEL_ADJUST[e["c"]]
    if forms & CLASSIC_TRAPS:
        score += 1.0
    score += DIFFICULTY_WEIGHT * spelling_difficulty(e["w"])
    if len(e["w"]) <= 4:
        score -= 0.4  # short words are rarely hard to spell
    return score


FAMILY_SUFFIXES = ("ibility", "ability", "ically", "ical", "ation", "ition", "ment", "ness", "ance", "ence",
                   "ancy", "ency", "able", "ible", "ity", "ism", "ist", "ive", "ion", "ant", "ent", "ing",
                   "ic", "al", "ed", "ly", "s", "e", "y")
# Negative and other prefixes that keep the word family: legal/illegal, migrant/immigrant,
# population/overpopulation. Words that only look prefixed are listed in NOT_FAMILY.
FAMILY_PREFIXES = ("non-", "non", "dis", "mis", "un", "in", "im", "il", "ir", "over", "under")
NOT_FAMILY = {frozenset(p) for p in (
    ("stance", "instance"), ("jury", "injury"), ("appoint", "disappoint"), ("corporate", "incorporate"),
    ("inform", "informal"), ("universe", "university"), ("position", "positive"), ("hospital", "hospitality"),
    ("execution", "executive"), ("author", "authority"), ("comment", "commence"), ("organic", "organise"),
    ("celebration", "celebrity"), ("competence", "competition"), ("competition", "competent"),
    ("considerable", "considering"), ("consist", "inconsistent"), ("discrimination", "criminal"),
    ("experiment", "experience"), ("format", "information"), ("identical", "identity"),
    ("integral", "integrity"), ("integrity", "integration"), ("mediate", "immediately"),
    ("steady", "instead"), ("vegetation", "vegetable"), ("misinformation", "informal"), ("exam", "example"), ("carbon", "carbohydrate"),
    ("define", "definitely"), ("define", "definite"),
)}


def family_stems(word):
    """sustainable / sustainability -> both include "sustain" (a light suffix strip, not a full stemmer)."""
    return {word} | {word[: -len(suf)] for suf in FAMILY_SUFFIXES if word.endswith(suf) and len(word) - len(suf) >= 5}


def similar(a, b):
    """Same word family or near-identical spelling: develop/development, sustainable/sustainability,
    relevant/irrelevant, migrant/immigrant."""
    short, long_ = sorted((a.lower(), b.lower()), key=len)
    if frozenset((short, long_)) in NOT_FAMILY:
        return False
    k = max(5, len(short) - 1) if len(short) >= 5 else len(short)
    if long_.startswith(short[:k]) or family_stems(short) & family_stems(long_):
        return True
    # Prefixed: the rest must be the other word or share its stem exactly (not just start the same)
    return any(long_.startswith(p) and len(long_) - len(p) >= 5
               and (long_[len(p):] == short or family_stems(long_[len(p):]) & family_stems(short))
               for p in FAMILY_PREFIXES)


def family_passes(entries):
    """Split words into passes: pass 1 has the most useful word of each family, pass 2 the next, ..."""
    rest, passes = sorted(entries, key=usefulness, reverse=True), []
    while rest:
        picked, deferred = [], []
        for e in rest:
            (deferred if any(similar(e["w"], p["w"]) for p in picked) else picked).append(e)
        passes.append(picked)
        rest = deferred
    return passes


def ielts_source(e):
    """The IELTS source a word is counted under (see SOURCE_SHARE)."""
    forms = {e["w"].lower(), *e["alt"]}
    topics = LISTED_IN.get(e["w"].lower(), {e["t"]})
    if forms & IDP_LISTENING:
        return "listening"
    if "Commonly Misspelled Words" in topics:
        return "misspelled"
    if any(f in AWL_SUBLIST for f in forms):
        return "academic"
    if any(t.startswith("Writing Task") for t in topics):
        return "writing"
    return "topic"


def interleave_sources(entries):
    """Order words so every prefix keeps SOURCE_SHARE (smooth weighted round-robin over sources).
    When a source runs out, the others share its place."""
    queues = {s: [e for e in entries if ielts_source(e) == s] for s in SOURCE_SHARE}  # by usefulness
    credit = {s: 0.0 for s in SOURCE_SHARE}
    out = []
    while any(queues.values()):
        active = [s for s in SOURCE_SHARE if queues[s]]
        for s in active:
            credit[s] += SOURCE_SHARE[s]
        source = max(active, key=lambda s: credit[s])
        credit[source] -= sum(SOURCE_SHARE[s] for s in active)
        out.append(queues[source].pop(0))
    return out


def rank_words(entries):
    """Set e["r"] (1 = most useful). Each Top N keeps the source mix of SOURCE_SHARE and has
    one word per family: the most useful member comes first, the rest only after every family."""
    ranked = [e for p in family_passes(entries) for e in interleave_sources(p)]
    for i, e in enumerate(ranked, 1):
        e["r"] = i


def cefr_level(word, alts, zipf, levels):
    """Return (level, source): listed level, the level of its base word, or an estimate from frequency."""
    for form in [word] + alts:
        if form in levels:
            return levels[form], "list"
    for form in [word] + alts:
        for suffix, repl in SUFFIXES:
            if form.endswith(suffix) and len(form) - len(suffix) >= 3:
                base = form[: -len(suffix)] + repl
                if base in levels:
                    return levels[base], "base"
    # Words missing from both profiles are mostly academic; frequency gives a fair estimate
    level = "B1" if zipf >= 5.0 else "B2" if zipf >= 4.4 else "C1" if zipf >= 3.6 else "C2"
    return level, "estimate"


LISTED_IN = {}  # word -> every topic it is listed under (a word is shown under the first one)


def fd_ipa(w, cache):
    """The first IPA text in the cached Free Dictionary entries for w ("" if none)."""
    for entry in (cache.get(w, {}).get("fd") or []):
        if isinstance(entry, dict):
            text = entry.get("phonetic") or next((p["text"] for p in entry.get("phonetics", []) if p.get("text")), "")
            if text:
                return text
    return ""


def wiktionary_ipa(w):
    """British (UK/RP) IPA from the word's English Wiktionary entry, else its first IPA.

    Returns "" when the entry has none, and None when the request failed (so it is retried next time).
    """
    url = ("https://en.wiktionary.org/w/api.php?action=parse&prop=wikitext&format=json&formatversion=2&page="
           + urllib.parse.quote(w))
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ielts-spelling-builder/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode())
            break
        except urllib.error.HTTPError as e:
            if e.code != 429:
                return "" if e.code == 404 else None
            time.sleep(10 * (attempt + 1))  # rate limited: back off
        except Exception:
            time.sleep(5)
    else:
        return None
    text = data.get("parse", {}).get("wikitext", "")
    english = re.split(r"\n==[^=]", text.split("==English==", 1)[1])[0] if "==English==" in text else ""
    # "*" lines are the main accents; "**" lines are regional sub-variants
    lines = [l for l in english.split("\n") if l.startswith("* ") and "{{IPA|en|" in l]
    british = [l for l in lines if re.search(r"(a=|\{\{a\|)[^}]*\b(UK|RP|GB|British)\b", l)]
    for line in british + lines:
        m = re.search(r"\{\{IPA\|en\|([/\[][^|}]+[/\]])", line)
        if m:
            return m.group(1)
    return ""


IPA_OK = set("abdefhijklmnprstuvwzæɑɒɔəɜɪʊʌθðʃʒŋɡːˈˌ()")
IPA_US = re.compile(r"[ɚɝɾ]|oʊ|ae|ɑ(?!ː)|ɔ(?![ːɪ])|ɜ(?!ː)|[aeiouæɑɒɔəɜɪʊʌː]r(?=[^aeiouæɑɒɔəɜɪʊʌj(]|$)")


def clean_ipa(text):
    """One consistent British IPA style, or "" if the transcription is unusable.

    Sources mix styles (syllable dots, tie bars, ɹ or r, ɛ or e) and sometimes give narrow phonetic
    [..] forms, American forms or fragments such as /-mɪnt/. Those are rejected so another source,
    or a hand-written one in curated.json, is used instead.
    """
    t = (text or "").strip()
    if not (t.startswith("/") and t.endswith("/") and len(t) > 2):
        return ""
    t = t[1:-1].split(",")[0].strip()
    t = re.sub(r"\((ɹ|r)\)$", "", t)  # optional linking r: /ˈpɹɛʃə(ɹ)/
    for a, b in (("t͡ʃ", "tʃ"), ("d͡ʒ", "dʒ"), ("͡", ""), ("̯", ""), ("̩", ""), (".", ""), ("'", "ˈ"),
                 ("ɹ", "r"), ("ɛ", "e"), ("ɐ", "ʌ"), ("ɨ", "ɪ"), ("g", "ɡ"), ("ɫ", "l"), ("ɝ", "ɜː"), ("ᵻ", "ɪ")):
        t = t.replace(a, b)
    t = re.sub(r"\(r\)", "", t)  # optional r
    t = re.sub(r"\(([^)]*)\)", r"\1", t)  # other optional sounds are kept: /əˈveɪləb(ə)l/
    for a, b in (("ʌɪ", "aɪ"), ("ʌʊ", "aʊ"), ("hw", "w"), ("əː", "ɜː"), ("ɪː", "iː"), ("ɜːː", "ɜː"), ("ˌˈ", "ˈ")):
        t = t.replace(a, b)
    t = re.sub(r"a(?![ɪʊː])", "æ", t)  # /ˈmanjʊəl/ (newer British style) -> /ˈmænjʊəl/
    t = re.sub(r"(?<![aeɔəʊ])ɪ$", "i", t)  # not the end of a diphthong such as /aɪ/  # /saɪˈkɒlədʒɪ/ -> /saɪˈkɒlədʒi/
    if not t or t[0] in "-‿" or t[-1] in "-" or any(c not in IPA_OK for c in t) or IPA_US.search(t):
        return ""
    return "/" + t + "/"


def tidy_definition(text):
    """Short, learner-friendly clue: the first sentence, without notes and usage examples."""
    text = re.sub(r"\s*\((see )?Wikipedia[^)]*\)", "", text)
    text = re.sub(r"\s*\[[^\]]*\]", "", text)           # ["to compare X with Y"]
    text = re.sub(r"[;,]\s*as,\s.*$", "", text)        # "...; as, the peak of a cap."
    text = re.sub(r"\s*\((e\.g\.|as in|i\.e\.)[^)]*\)", "", text)  # "(e.g. city council)"
    first = re.split(r"(?<!\be\.g)(?<!\bi\.e)(?<!\betc)(?<!\b[A-Z])\.\s+(?=[A-Z(])", text, maxsplit=1)[0]
    if len(first) > 110 and ";" in first and len(first.split(";")[0]) >= 20:
        first = first.split(";")[0]
    return first.strip().rstrip(",:")


def read_list():
    words, seen = [], set()
    topic = None
    for line in open(LIST, encoding="utf-8"):
        line = line.strip()
        if line.startswith("## "):
            topic = line[3:].strip()
            continue
        if not line or line.startswith("#"):
            continue
        for w in line.split(","):
            w = w.strip()
            key = w.lower()
            if not w or key in SKIP:
                continue
            LISTED_IN.setdefault(key, set()).add(topic)
            if key in seen:
                continue
            seen.add(key)
            words.append((w, topic))
    return words


def lemma_count(syn, word):
    return sum(l.count() for l in syn.lemmas() if l.name().lower() == word.lower())


def wn_lookup(word):
    """Return (meanings, synonyms, antonyms) from WordNet for word (or its variants)."""
    candidates = [word] + american_variants(word.lower())
    syns = []
    for c in candidates:
        syns = wn.synsets(c.replace("-", "_").replace(" ", "_"))
        if not syns:
            syns = wn.synsets(c.replace("-", ""))
        if syns:
            lookup = c
            break
    if not syns:
        return None
    lk = lookup.lower().replace("-", "_")

    # Only keep synsets whose own lemma is the word (not derived/inflected matches)
    exact = [s for s in syns if any(l.name().lower() == lk for l in s.lemmas())] or syns
    # Rank: WordNet order is already roughly frequency order; boost by tagged counts.
    ranked = sorted(enumerate(exact), key=lambda t: (-lemma_count(t[1], lk), t[0]))
    ranked = [s for _, s in ranked]

    meanings, used_pos = [], set()
    for s in ranked:
        pos = POS_NAME[s.pos()]
        if pos in used_pos:
            continue
        used_pos.add(pos)
        ex = ""
        for e in s.examples():
            if re.search(r"\b" + re.escape(lk.replace("_", " ")[:max(4, len(lk) - 3)]), e, re.I):
                ex = e
                break
        if not ex and s.examples():
            ex = s.examples()[0]
        meanings.append({"pos": pos, "def": s.definition(), "ex": ex})
        if len(meanings) == 2:
            break

    synonyms, antonyms = [], []
    for s in ranked[:4]:
        for l in s.lemmas():
            n = l.name().replace("_", " ")
            if n.lower() != lk.replace("_", " ") and n not in synonyms:
                synonyms.append(n)
            for a in l.antonyms():
                an = a.name().replace("_", " ")
                if an not in antonyms:
                    antonyms.append(an)
        if s.pos() in "as":
            for sim in s.similar_tos()[:2]:
                for l in sim.lemmas()[:1]:
                    n = l.name().replace("_", " ")
                    if n.lower() != lk and n not in synonyms:
                        synonyms.append(n)
    # Antonyms via derivationally related adjectives (e.g. for nouns) as a fallback
    if not antonyms:
        for s in ranked[:3]:
            for l in s.lemmas():
                for d in l.derivationally_related_forms():
                    for a in d.antonyms():
                        an = a.name().replace("_", " ")
                        if an not in antonyms:
                            antonyms.append(an)
    return meanings, synonyms, antonyms


def datamuse(word):
    q = urllib.parse.quote(word.replace("-", " "))
    res = {}
    for key, url in [
        ("syn", f"https://api.datamuse.com/words?rel_syn={q}&max=8"),
        ("ant", f"https://api.datamuse.com/words?rel_ant={q}&max=5"),
        ("freq", f"https://api.datamuse.com/words?sp={q}&md=fd&max=1"),
    ]:
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=20) as r:
                    res[key] = json.loads(r.read().decode())
                break
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    res[key] = []
                    break
                time.sleep(3 * (attempt + 1))
                if attempt == 2:
                    res[key] = None
            except Exception:
                if attempt == 2:
                    res[key] = None
    return word, res


def main():
    words = read_list()
    cache = {}
    for _ in range(5):  # the cache may be mid-write by another run
        try:
            cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
            break
        except json.JSONDecodeError:
            time.sleep(1)
    # --offline: build from the cache only (no network), e.g. while a fetch is still running
    offline = "--offline" in sys.argv
    todo = [] if offline else [w for w, _ in words if w not in cache or any(cache[w].get(k) is None for k in ("syn", "ant", "freq"))]
    print(f"{len(words)} words, fetching {len(todo)} from Datamuse...", flush=True)
    with ThreadPoolExecutor(5) as ex:
        for i, (w, res) in enumerate(ex.map(datamuse, todo)):
            cache[w] = res
            if i % 200 == 0:
                print(f"  {i}/{len(todo)}", flush=True)
                json.dump(cache, open(CACHE, "w"))
    if not offline:
        json.dump(cache, open(CACHE, "w"))

    # Free Dictionary API allows ~450 requests per 5 minutes: 3 workers sharing a 1.4 req/s limit.
    fd_todo = [] if offline else [w for w, _ in words if cache.get(w, {}).get("fd") is None]
    print(f"fetching {len(fd_todo)} entries from dictionaryapi.dev...", flush=True)
    lock, next_slot = threading.Lock(), [0.0]

    def throttle():
        with lock:
            now = time.time()
            slot = max(now, next_slot[0])
            next_slot[0] = slot + 1 / 1.4
        time.sleep(max(0, slot - now))

    def fetch_fd(w):
        req = urllib.request.Request(
            "https://api.dictionaryapi.dev/api/v2/entries/en/" + urllib.parse.quote(w.lower()),
            headers={"User-Agent": "ielts-spelling-builder/1.0"})
        for _ in range(6):
            throttle()
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    return w, json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return w, []
                print(f"  HTTP {e.code} for {w}, backing off", flush=True)
                time.sleep(60)
            except Exception:
                time.sleep(5)
        return w, None

    with ThreadPoolExecutor(3) as ex:
        for i, (w, data) in enumerate(ex.map(fetch_fd, fd_todo)):
            cache[w]["fd"] = data
            if i % 50 == 0:
                print(f"  {i}/{len(fd_todo)}", flush=True)
                json.dump(cache, open(CACHE, "w"))
    if not offline:
        json.dump(cache, open(CACHE, "w"))

    # IPA from Wiktionary for words the Free Dictionary API has no pronunciation for
    wk_todo = [] if offline else [w for w, _ in words if not fd_ipa(w, cache) and cache.get(w, {}).get("wk_ipa") is None]
    print(f"fetching {len(wk_todo)} pronunciations from Wiktionary...", flush=True)
    for i, w in enumerate(wk_todo):
        ipa = None
        # British spellings ("analyse") often have only a pointer to the US entry, so try that too
        for form in [w] + american_variants(w.lower()):
            ipa = wiktionary_ipa(form)
            time.sleep(1.5)  # be polite to Wiktionary
            if ipa:
                break
        cache.setdefault(w, {})["wk_ipa"] = ipa
        if i % 50 == 0:
            print(f"  {i}/{len(wk_todo)}", flush=True)
            json.dump(cache, open(CACHE, "w"))
    if not offline:
        json.dump(cache, open(CACHE, "w"))

    curated = json.load(open(CURATED, encoding="utf-8")) if os.path.exists(CURATED) else {}

    out, missing = [], []
    for w, topic in words:
        base = w.lower()
        alts = american_variants(base)
        stem = base[:max(4, len(base) - 3)]
        stems = [stem] + [a[:max(4, len(a) - 3)] for a in alts]
        dm = cache.get(w, {})
        wnres = wn_lookup(w)
        wn_meanings, wn_syn, wn_ant = wnres if wnres else ([], [], [])

        def has_word(text):
            t = (text or "").lower()
            return any(re.search(r"\b" + re.escape(st), t) for st in stems)

        # ---- meanings from Free Dictionary (Wiktionary) ----
        fd_pos, fd_syn, fd_ant, phon = {}, [], [], ""
        for entry in (dm.get("fd") or []):
            if not isinstance(entry, dict) or entry.get("word", "").lower() not in [base] + alts:
                continue
            if not phon:  # the first usable British transcription among this entry's phonetics
                texts = [entry.get("phonetic")] + [p.get("text") for p in entry.get("phonetics", [])]
                phon = next((c for c in map(clean_ipa, texts) if c), "")
            for m in entry.get("meanings", []):
                pos = m.get("partOfSpeech", "")
                fd_syn += m.get("synonyms", [])
                fd_ant += m.get("antonyms", [])
                for d in m.get("definitions", []):
                    fd_syn += d.get("synonyms", [])
                    fd_ant += d.get("antonyms", [])
                    text = d.get("definition", "")
                    if BAD_LABEL.search(text) or len(text) < 4:
                        continue
                    text = re.sub(r"^(\([^)]*\)\s*)+", "", text).strip()
                    if not text or text.lower().startswith(("alternative", "obsolete", "plural of",
                                                            "misspelling", "synonym of", "initialism")):
                        continue
                    slot = fd_pos.setdefault(pos, {"pos": pos, "def": "", "ex": ""})
                    if not slot["def"]:
                        slot["def"] = text
                    ex = d.get("example", "")
                    if not slot["ex"] and ex and has_word(ex) and len(ex) < 160:
                        slot["ex"] = ex.strip('"')

        # order parts of speech by WordNet usage, then dictionary order
        wn_order = [m["pos"] for m in wn_meanings]
        meanings = sorted(fd_pos.values(), key=lambda m: wn_order.index(m["pos"]) if m["pos"] in wn_order else 9)
        meanings = [m for m in meanings if m["def"]][:2]
        if not meanings:
            meanings = [dict(m) for m in wn_meanings]
        for m in meanings:
            m["def"] = tidy_definition(m["def"])
            m["def"] = m["def"][0].upper() + m["def"][1:]
            if not m["def"].endswith((".", "?", "!")):
                m["def"] += "."
            if not m["ex"]:
                for wm in wn_meanings:
                    if wm["pos"] == m["pos"] and wm["ex"] and has_word(wm["ex"]):
                        m["ex"] = wm["ex"]
        # ---- hand-checked fixes from curated.json (sense, definition, example, clues) ----
        # A complete curated entry (pos, def, ex) also covers words the dictionaries miss
        cur = curated.get(w) or curated.get(base) or {}
        if any(k in cur for k in ("pos", "def", "ex")):
            first = meanings[0] if meanings else {"pos": "", "def": "", "ex": ""}
            first = {**first, **{k: cur[k] for k in ("pos", "def", "ex") if k in cur}}
            meanings = [first] + [m for m in meanings[1:] if m["pos"] != first["pos"]]
        if not meanings or not meanings[0]["def"]:
            missing.append(w)
            continue

        def ok(x, minz):
            xl = x.lower().strip()
            if not xl or xl == base or xl in alts or any(xl.startswith(st) for st in stems):
                return False
            # Proper nouns and abbreviations ("Rudolf Diesel", "POTUS", "D/L") are not useful clues
            if x != xl or re.search(r"[\d./]", x):
                return False
            # Phrases that repeat the word or its stem ("linguistic context", "do drugs") give the answer away
            if any(tok.startswith(st) for tok in re.split(r"[ -]", xl) for st in stems):
                return False
            if len(xl.split()) > 2 or len(xl) > 22:
                return False
            # Abbreviations of the word itself ("feb", "sci", "gym") give the answer away
            if base.startswith(xl) or any(a.startswith(xl) for a in alts):
                return False
            return min(zipf_frequency(t, "en") for t in xl.split()) >= minz

        def pick(cands, minz, limit):
            res, seen = [], set()
            for c in cands:
                c = c.strip()
                forms = {c.lower(), *american_variants(c.lower()), c.lower().replace("judgement", "judgment")}
                # skip abbreviations ("ka") and spelling variants of a word already picked (judgment/judgement)
                if len(c) >= 3 and ok(c, minz) and not forms & seen:
                    res.append(c)
                    seen |= forms
                if len(res) == limit:
                    break
            return res

        dm_syn = [d["word"] for d in (dm.get("syn") or [])]
        dm_ant = [d["word"] for d in (dm.get("ant") or [])]
        syn = pick(dm_syn[:5] + wn_syn + fd_syn, 2.9, 3)
        ant = pick(wn_ant + dm_ant + fd_ant, 2.6, 2)
        # Hand-checked lists win: they match the meaning shown (the page shows 3 synonyms and 2 antonyms)
        syn = cur.get("syn", syn)
        ant = cur.get("ant", ant)

        freq = max([phrase_zipf(base)] + [phrase_zipf(a) for a in alts])
        if "f" in cur:  # e.g. "found" (to establish) is counted as the past tense of "find"
            freq = cur["f"]
        out.append({
            "w": w,
            "t": topic,
            "f": round(freq, 2),
            "ipa": cur.get("ipa") or phon or clean_ipa(dm.get("wk_ipa")) or "",
            "alt": alts,
            "m": meanings[:1],  # the page shows one meaning: the one that matches the example
            "syn": syn,
            "ant": ant,
        })

    # One entry per word: drop a headword that is another entry's accepted spelling (license -> licence)
    variants = {a for e in out for a in e["alt"]}
    merged = [e["w"] for e in out if e["w"].lower() in variants]
    out = [e for e in out if e["w"].lower() not in variants]
    print(f"Merged {len(merged)} spelling variants: {' '.join(merged)}")

    # CEFR level (A1-C2) from the open CEFR-J / Octanove profiles, else estimated
    cefr = load_cefr()
    sources = {"list": 0, "base": 0, "estimate": 0}
    for e in out:
        e["c"], how = cefr_level(e["w"].lower(), e["alt"], e["f"], cefr)
        e["_src"] = how
        sources[how] += 1

    # Too basic for IELTS spelling practice: short A1 words (keep the commonly misspelled ones)
    # IELTS Listening words stay: there a misspelled answer scores zero, however easy the word is
    too_easy = [e["w"] for e in out if e["c"] == "A1" and e["_src"] == "list" and len(e["w"]) < 7
                and not e["t"].startswith("Commonly") and e["w"].lower() not in IDP_LISTENING]
    out = [e for e in out if e["w"] not in too_easy]
    for e in out:
        del e["_src"]
    rank_words(out)
    print(f"Dropped {len(too_easy)} basic A1 words: {' '.join(too_easy)}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("// Generated by tools/build_data.py — do not edit by hand.\n")
        fh.write("window.IELTS_WORDS = ")
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write(";\n")
    print(f"Wrote {len(out)} words to {OUT}")
    print(f"No dictionary data for {len(missing)}: {missing}")
    print("Top 100:", " ".join(e["w"] for e in sorted(out, key=lambda e: e["r"])[:100]))
    print("CEFR:", {c: sum(1 for e in out if e["c"] == c) for c in CEFR_ORDER}, "| source:", sources)
    print("with antonyms:", sum(1 for e in out if e["ant"]))
    print("no synonyms:", sum(1 for e in out if not e["syn"]), "| no example:", sum(1 for e in out if not e["m"][0]["ex"]), "| no ipa:", sum(1 for e in out if not e["ipa"]))


if __name__ == "__main__":
    sys.exit(main())
