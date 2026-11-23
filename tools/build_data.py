"""Build data/words.js from tools/wordlist.txt.

Meanings, examples, synonyms and antonyms come from WordNet (offline, via nltk).
Synonyms/antonyms are supplemented, and word frequency is fetched, from the
Datamuse API (https://www.datamuse.com/api/). Results are cached in
tools/.cache.json so re-runs are fast.

Run:  NLTK_DATA=.venv/nltk_data .venv/bin/python tools/build_data.py
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
            if not w or key in seen or key in SKIP:
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

    overrides = {}
    op = os.path.join(ROOT, "tools", "overrides.json")
    if os.path.exists(op):
        overrides = json.load(open(op, encoding="utf-8"))

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
            phon = phon or entry.get("phonetic") or next(
                (p["text"] for p in entry.get("phonetics", []) if p.get("text")), "")
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
            m["def"] = m["def"][0].upper() + m["def"][1:]
            if not m["def"].endswith((".", "?", "!")):
                m["def"] += "."
            if not m["ex"]:
                for wm in wn_meanings:
                    if wm["pos"] == m["pos"] and wm["ex"] and has_word(wm["ex"]):
                        m["ex"] = wm["ex"]
        if base in overrides:
            o = overrides[base]
            meanings = o.get("m", meanings)
            fd_syn = o.get("syn", []) + fd_syn
            fd_ant = o.get("ant", []) + fd_ant
        if not meanings:
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
            return min(zipf_frequency(t, "en") for t in xl.split()) >= minz

        def pick(cands, minz, limit):
            res = []
            for c in cands:
                c = c.strip()
                if ok(c, minz) and c.lower() not in [r.lower() for r in res]:
                    res.append(c)
                if len(res) == limit:
                    break
            return res

        dm_syn = [d["word"] for d in (dm.get("syn") or [])]
        dm_ant = [d["word"] for d in (dm.get("ant") or [])]
        o = overrides.get(base, {})
        syn = pick(o.get("syn", []) + dm_syn[:5] + wn_syn + fd_syn, 2.9, 6)
        ant = pick(o.get("ant", []) + wn_ant + dm_ant + fd_ant, 2.6, 4)

        freq = max([zipf_frequency(base.replace("-", " "), "en")] +
                   [zipf_frequency(a, "en") for a in alts])
        out.append({
            "w": w,
            "t": topic,
            "f": round(freq, 2),
            "ipa": phon,
            "alt": alts,
            "m": meanings,
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
    too_easy = [e["w"] for e in out if e["c"] == "A1" and e["_src"] == "list" and len(e["w"]) < 7
                and not e["t"].startswith("Commonly")]
    out = [e for e in out if e["w"] not in too_easy]
    for e in out:
        del e["_src"]
    print(f"Dropped {len(too_easy)} basic A1 words: {' '.join(too_easy)}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("// Generated by tools/build_data.py — do not edit by hand.\n")
        fh.write("window.IELTS_WORDS = ")
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write(";\n")
    print(f"Wrote {len(out)} words to {OUT}")
    print(f"No dictionary data for {len(missing)}: {missing}")
    print("CEFR:", {c: sum(1 for e in out if e["c"] == c) for c in CEFR_ORDER}, "| source:", sources)
    print("with antonyms:", sum(1 for e in out if e["ant"]))
    print("no synonyms:", sum(1 for e in out if not e["syn"]), "| no example:", sum(1 for e in out if not e["m"][0]["ex"]), "| no ipa:", sum(1 for e in out if not e["ipa"]))


if __name__ == "__main__":
    sys.exit(main())
