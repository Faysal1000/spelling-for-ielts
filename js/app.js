/* IELTS Spelling Practice
 * Word data: data/words.js (window.IELTS_WORDS). Progress: localStorage, per browser.
 */
(() => {
  "use strict";

  const POS_SHORT = { n: "n.", v: "v.", adj: "adj.", adv: "adv.", noun: "n.", verb: "v.", adjective: "adj.", adverb: "adv.", conjunction: "conj.", preposition: "prep.", pronoun: "pron.", interjection: "interj." };
  const CEFR = ["A1", "A2", "B1", "B2", "C1", "C2"];
  const MASTERED_STREAK = 3;    // mistake-free answers in a row to master a word
  const WEAK_STREAK = 2;        // a word with mistakes stays "weak" until this streak
  const SLOW_RATE = 0.55;       // Shift+Esc / Shift+Enter speech rate
  const NEXT_AFTER_OK_MS = 700; // pause before moving on after a correct word
  const NEXT_AFTER_FAIL_MS = 2000;
  const SHOW_SYN = 3, SHOW_ANT = 2;
  const SAMPLE_WORD = "necessary"; // spoken when the voice or speed changes

  const WORDS = (window.IELTS_WORDS || []).map((w, i) => ({ ...w, i, key: w.w.toLowerCase() }));
  const TOPICS = [...new Set(WORDS.map(w => w.t))];

  const $ = sel => document.querySelector(sel);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = n => n.toLocaleString("en-GB");

  const ICONS = {
    speaker: '<svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><path fill="currentColor" d="M3 9v6h4l5 5V4L7 9H3Zm13.5 3A4.5 4.5 0 0 0 14 8v8a4.5 4.5 0 0 0 2.5-4ZM14 3.2v2.1a7 7 0 0 1 0 13.4v2.1a9 9 0 0 0 0-17.6Z"/></svg>',
    check: '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="m9.5 16.2-4.2-4.2-1.4 1.4 5.6 5.6 11-11-1.4-1.4-9.6 9.6Z"/></svg>',
    cross: '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="m6.4 5 5.6 5.6L17.6 5 19 6.4 13.4 12l5.6 5.6-1.4 1.4-5.6-5.6L6.4 19 5 17.6l5.6-5.6L5 6.4 6.4 5Z"/></svg>',
  };

  /* ---------- Storage ---------- */
  const storage = {
    get(key, fallback) {
      try {
        const v = JSON.parse(localStorage.getItem(key));
        return v && typeof v === "object" && !Array.isArray(v) ? v : fallback;
      } catch { return fallback; }
    },
    set(key, value) {
      try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ }
    },
  };
  const KEY_PROGRESS = "isp.progress.v1";
  const KEY_PREFS = "isp.prefs.v1";

  // Keep only well-formed progress entries, so old or edited storage can't break the page
  const num = v => (Number.isFinite(v) && v >= 0 ? v : 0);
  function loadProgress() {
    const out = {};
    for (const [k, p] of Object.entries(storage.get(KEY_PROGRESS, {}))) {
      if (p && typeof p === "object") out[k] = { c: num(p.c), x: num(p.x), s: num(p.s), t: num(p.t) };
    }
    return out;
  }
  let progress = loadProgress();
  const DEFAULT_PREFS = { top: "all", topic: "all", level: "all", status: "all", order: "rank", count: "50", maxMistakes: "5", wrongMs: "500", voice: "", rate: "0.85" };
  const prefs = { ...DEFAULT_PREFS };
  for (const [k, v] of Object.entries(storage.get(KEY_PREFS, {}))) if (k in prefs && typeof v === "string") prefs[k] = v;
  const savePrefs = () => storage.set(KEY_PREFS, prefs);
  const saveProgress = () => storage.set(KEY_PROGRESS, progress);

  function statusOf(word) {
    const p = progress[word.key];
    if (!p) return "new";
    if (p.s >= MASTERED_STREAK) return "mastered";
    if (p.x > 0 && p.s < WEAK_STREAK) return "weak";
    return "practising";
  }

  function record(word, correct) {
    const p = progress[word.key] || { c: 0, x: 0, s: 0, t: 0 };
    if (correct) { p.c += 1; p.s += 1; } else { p.x += 1; p.s = 0; }
    p.t = Date.now();
    progress[word.key] = p;
    saveProgress();
  }

  /* ---------- Speech ---------- */
  const synth = window.speechSynthesis;
  let voices = [];
  let speakTimer = 0;

  function loadVoices() {
    if (!synth) return;
    const score = v => {
      let s = 0;
      if (/en[-_]GB/i.test(v.lang)) s += 50;
      else if (/en[-_](AU|IE|NZ)/i.test(v.lang)) s += 30;
      else if (/en[-_]US/i.test(v.lang)) s += 20;
      if (/google|natural|neural|premium|enhanced/i.test(v.name)) s += 15;
      if (/daniel|serena|kate|arthur|martha|libby|sonia|ryan/i.test(v.name)) s += 10;
      if (/albert|bad news|bahh|bells|boing|bubbles|cellos|fred|jester|junior|organ|ralph|superstar|trinoids|whisper|wobble|zarvox/i.test(v.name)) s -= 100;
      return s;
    };
    voices = synth.getVoices().filter(v => /^en([-_]|$)/i.test(v.lang)).sort((a, b) => score(b) - score(a));
    const select = $("#voice");
    select.innerHTML = voices.length
      ? voices.map(v => `<option value="${esc(v.voiceURI)}">${esc(v.name.replace(/\s*\(.*\)$/, ""))} (${esc(v.lang)})</option>`).join("")
      : '<option value="">Default</option>';
    if (!voices.some(v => v.voiceURI === prefs.voice) && voices[0]) prefs.voice = voices[0].voiceURI;
    select.value = prefs.voice;
  }

  function speak(text, rate = Number(prefs.rate)) {
    if (!synth || !text) return;
    clearTimeout(speakTimer);
    synth.cancel();
    document.querySelectorAll(".speak.playing").forEach(b => b.classList.remove("playing"));
    const u = new SpeechSynthesisUtterance(text);
    const voice = voices.find(v => v.voiceURI === prefs.voice);
    if (voice) { u.voice = voice; u.lang = voice.lang; } else { u.lang = "en-GB"; }
    u.rate = rate;
    const btn = document.querySelector(".row.active .speak");
    u.onstart = () => btn && btn.classList.add("playing");
    u.onend = u.onerror = () => btn && btn.classList.remove("playing");
    speakTimer = setTimeout(() => synth.speak(u), 30); // Chrome needs a tick after cancel()
  }

  /* ---------- Filtering ---------- */
  function stopSpeech() {
    clearTimeout(speakTimer);
    if (synth) synth.cancel();
  }

  function filteredWords() {
    const list = WORDS.filter(w =>
      (prefs.top === "all" || w.r <= Number(prefs.top)) &&
      (prefs.topic === "all" || w.t === prefs.topic) &&
      (prefs.level === "all" || w.c === prefs.level) &&
      (prefs.status === "all" ||
        (prefs.status === "notmastered" ? statusOf(w) !== "mastered" : statusOf(w) === prefs.status)));
    if (prefs.order === "alpha") return list.sort((a, b) => a.key.localeCompare(b.key));
    if (prefs.order === "random") return shuffleStable(list);
    return list.sort((a, b) => a.r - b.r); // "Top first": most useful words first
  }

  // Seeded shuffle: the random order only changes when asked to (so "Show more" continues the same set)
  const newSeed = () => Math.floor(Math.random() * 1e9);
  let shuffleSeed = newSeed();
  function shuffleStable(list) {
    let seed = shuffleSeed;
    const rand = () => ((seed = (seed * 1664525 + 1013904223) % 4294967296) / 4294967296);
    for (let i = list.length - 1; i > 0; i--) {
      const j = Math.floor(rand() * (i + 1));
      [list[i], list[j]] = [list[j], list[i]];
    }
    return list;
  }

  /* ---------- Visible list state ---------- */
  let list = [];           // all words matching the filters, in order
  let shown = 0;           // how many rows are on the page
  let active = 0;          // index of the active row
  let results = new Map(); // word index -> { done, mistakes, typed } once a word is finished
  const newLive = (n = -1) => ({ n, valid: "", mistakes: 0 });
  let live = newLive(); // typing state of the active word: row, correct prefix, mistakes
  let autoNextTimer = 0;

  let wrong = { input: null, value: "", timer: 0 }; // a rejected letter shown briefly in red
  const batchSize = () => Number(prefs.count) || 50;
  const maxMistakes = () => Number(prefs.maxMistakes) || 0; // 0 = unlimited

  function refresh() {
    savePrefs();
    list = filteredWords();
    results = new Map();
    active = 0;
    shown = 0;
    clearWrong(false);
    live = newLive();
    clearTimeout(autoNextTimer);
    stopSpeech();
    $("#rows").innerHTML = list.length
      ? ""
      : '<p class="empty">No words match these filters. Try another topic or “All words”.</p>';
    showMore();
    renderStats();
  }

  function showMore() {
    const from = shown;
    shown = Math.min(list.length, shown + batchSize());
    $("#rows").insertAdjacentHTML("beforeend", list.slice(from, shown).map((w, k) => rowHtml(w, from + k)).join(""));
    updateFooter();
    markActive();
  }

  function updateFooter() {
    const left = list.length - shown;
    $("#listInfo").textContent = list.length ? `Showing ${fmt(shown)} of ${fmt(list.length)} words` : "";
    $("#moreBtn").hidden = left <= 0;
    $("#moreBtn").textContent = `Show ${fmt(Math.min(left, batchSize()))} more`;
    $("#shuffleBtn").hidden = prefs.order !== "random" || !list.length;
  }

  function totals() {
    let practised = 0, mastered = 0, right = 0, wrong = 0;
    for (const w of WORDS) {
      const p = progress[w.key];
      if (!p) continue;
      practised += 1; right += p.c; wrong += p.x;
      if (p.s >= MASTERED_STREAK) mastered += 1;
    }
    const accuracy = right + wrong ? `${Math.round((right / (right + wrong)) * 100)}%` : "–";
    return { practised, mastered, accuracy };
  }

  function renderStats() {
    const { practised, mastered, accuracy } = totals();
    $("#stats").innerHTML = `<b>${fmt(WORDS.length)}</b> words · <b>${fmt(practised)}</b> practised · <b>${fmt(mastered)}</b> mastered · <b>${accuracy}</b> accuracy`;
  }

  /* ---------- Rendering rows ---------- */
  // Hides the word and its relatives in the clue (chemical -> "chemi..." also hides "chemistry").
  // wholeWord=false also hides it inside longer words, e.g. "un___" for the antonym "unavailable".
  function stemOf(form) {
    const cut = form.length >= 9 ? 4 : form.length >= 7 ? 3 : form.length > 5 ? 2 : form.endsWith("e") ? 1 : 0;
    return form.slice(0, form.length - cut);
  }
  function blankRegex(word, wholeWord = true) {
    const stems = [word.key, ...(word.alt || [])].map(form => stemOf(form.toLowerCase()).replace(/[-\s]/g, "[-\\s]?"));
    return new RegExp(`${wholeWord ? "\\b" : ""}(${stems.join("|")})[a-z]*`, "gi");
  }

  function clueHtml(word, revealed) {
    const BLANK = '<span class="blank" role="img" aria-label="blank"></span>';
    const mask = re => text => (revealed ? esc(text) : esc(text).replace(re, BLANK));
    const hide = mask(blankRegex(word));
    const hideInside = mask(blankRegex(word, false));
    const m = word.m[0] || { pos: "", def: "" };
    const syn = word.syn.slice(0, SHOW_SYN);
    const ant = word.ant.slice(0, SHOW_ANT);
    const related = [
      syn.length ? `<span class="syn">Syn. ${hideInside(syn.join("; "))}</span>` : "",
      ant.length ? `<span class="ant">Ant. ${hideInside(ant.join("; "))}</span>` : "",
    ].filter(Boolean).join(" · ");
    const meta = [
      word.ipa ? `<span class="ipa">${esc(word.ipa)}</span>` : "",
      m.pos ? `<span class="pos">${esc(POS_SHORT[m.pos] || m.pos)}</span>` : "",
      related,
    ].join("");
    const example = revealed && m.ex ? `<p class="ex">“${esc(m.ex)}”</p>` : "";
    return `<p class="meta">${meta}</p><p class="def">${hide(m.def)}</p>${example}`;
  }

  /* ---------- Answer card ---------- */
  function triesHtml(mistakes, lastWrong) {
    const max = maxMistakes();
    if (!mistakes) return "";
    const dots = max
      ? `<span class="dots" aria-hidden="true">${Array.from({ length: max }, (_, k) => `<i class="${k < mistakes ? "used" : ""}"></i>`).join("")}</span>`
      : "";
    const count = max ? `${mistakes} of ${max} mistakes` : `${mistakes} mistake${mistakes > 1 ? "s" : ""}`;
    return `<div class="tries">${dots}<span>${count}${lastWrong ? ` · “${esc(lastWrong)}” is wrong` : ""}</span></div>`;
  }

  function answerHtml(word, result) {
    if (!result) return "";
    if (result.done) {
      const note = result.mistakes ? ` · ${result.mistakes} mistake${result.mistakes > 1 ? "s" : ""}` : "";
      // The word is already in the input, so only the verdict is shown
      return `<div class="result ${result.mistakes ? "warn" : "ok"}"><span class="verdict">${ICONS.check}Correct${note}</span></div>`;
    }
    // Out of tries: show the full word, the part they got right in green
    const got = result.typed.length;
    return `<div class="result bad"><span class="verdict">${ICONS.cross}Out of tries</span>
      <span class="word" aria-label="Correct spelling ${esc(word.w)}"><span class="good">${esc(word.w.slice(0, got))}</span><span class="miss">${esc(word.w.slice(got))}</span></span></div>`;
  }

  const rowState = result => (result ? (result.done ? (result.mistakes ? " warn" : " ok") : " bad") : "");
  const answerValue = (word, result) => (result ? (result.done ? word.w : result.typed) : "");
  function markHtml(word) {
    const st = statusOf(word);
    if (st !== "mastered" && st !== "weak") return '<span class="mark" aria-hidden="true"></span>';
    const label = st === "mastered" ? "Mastered" : "In your mistakes";
    return `<span class="mark ${st}" role="img" aria-label="${label}" title="${label}"></span>`;
  }

  function rowHtml(word, n) {
    const result = results.get(word.i);
    return `<article class="row${rowState(result)}" data-row="${n}">
      <div class="card info-card">
        <div class="info-head">
          <button class="speak" type="button" data-speak="${n}" aria-label="Hear word ${n + 1}">${ICONS.speaker}</button>
          <span class="esc">[Esc]</span>
          <span class="num">(${n + 1})</span>
          ${markHtml(word)}
          ${word.c ? `<span class="cefr cefr-${word.c[0]}" title="CEFR level ${word.c}">${word.c}</span>` : ""}
        </div>
        <div class="clue">${clueHtml(word, !!result)}</div>
      </div>
      <div class="card answer-card">
        <input class="answer" type="text" data-input="${n}" value="${esc(answerValue(word, result))}" ${result ? "readonly" : ""}
          autocomplete="off" autocorrect="off" autocapitalize="none" spellcheck="false" enterkeyhint="next"
          placeholder="Type the word you hear" aria-label="Spelling for word ${n + 1}">
        <div class="feedback" aria-live="polite">${answerHtml(word, result)}</div>
      </div>
    </article>`;
  }

  // Update a row in place (not by re-rendering it), so a focused input and the phone keyboard survive
  function updateRow(n) {
    const row = document.querySelector(`[data-row="${n}"]`);
    if (!row) return;
    const word = list[n], result = results.get(word.i);
    row.className = `row${rowState(result)}${n === active ? " active" : ""}`;
    row.querySelector(".mark").outerHTML = markHtml(word);
    row.querySelector(".clue").innerHTML = clueHtml(word, !!result);
    const input = row.querySelector(".answer");
    input.value = answerValue(word, result);
    input.readOnly = !!result;
    row.querySelector(".feedback").innerHTML = answerHtml(word, result);
  }

  // Phones: put the row near the top so the keyboard can't cover it. Laptops: centre it.
  const narrow = window.matchMedia("(max-width: 640px)");
  function scrollToRow(n) {
    const row = document.querySelector(`[data-row="${n}"]`);
    if (row) row.scrollIntoView({ behavior: "smooth", block: narrow.matches ? "start" : "center" });
  }

  function markActive() {
    document.querySelectorAll(".row.active").forEach(r => r.classList.remove("active"));
    const row = document.querySelector(`[data-row="${active}"]`);
    if (row) row.classList.add("active");
  }

  /* ---------- Practice actions ---------- */
  function setActive(n, { play = true, scroll = true } = {}) {
    if (n < 0 || n >= shown) return;
    clearTimeout(autoNextTimer);
    clearWrong();
    if (live.n !== n) live = newLive(n);
    // An unfinished word you leave starts fresh when you come back
    const prevInput = document.querySelector(`[data-input="${active}"]`);
    if (active !== n && prevInput && !results.has(list[active].i)) {
      prevInput.value = "";
      prevInput.closest(".answer-card").querySelector(".feedback").innerHTML = "";
    }
    active = n;
    markActive();
    const input = document.querySelector(`[data-input="${n}"]`);
    if (input && document.activeElement !== input) input.focus({ preventScroll: true });
    if (scroll) scrollToRow(n);
    if (play && !results.has(list[n].i)) speak(list[n].w);
  }

  // Accepted spellings (main + British/American variants); a hyphen also accepts a space
  function forms(word) {
    return [word.key, ...(word.alt || [])].map(f => f.toLowerCase());
  }
  const sameChar = (typed, expected) => typed === expected || (expected === "-" && typed === " ") || (expected === " " && typed === "-");
  const isPrefix = (typed, form) => typed.length <= form.length && [...typed].every((c, k) => sameChar(c, form[k]));

  // Ends the red "wrong letter" display; with revert, puts the input back to the correct part
  function clearWrong(revert = true) {
    if (!wrong.input) return;
    clearTimeout(wrong.timer);
    wrong.input.classList.remove("wrong");
    if (revert && wrong.input.value.toLowerCase() === wrong.value) wrong.input.value = live.valid;
    wrong = { input: null, value: "", timer: 0 };
  }

  function onType(input) {
    const n = Number(input.dataset.input);
    const word = list[n];
    if (results.has(word.i)) return;
    if (live.n !== n) live = newLive(n);
    let typed = input.value.toLowerCase();

    // Typing on while a wrong letter is still shown: drop it and keep only what is new
    if (wrong.input === input) {
      const extra = typed.startsWith(wrong.value) ? typed.slice(wrong.value.length) : "";
      clearWrong(false);
      typed = live.valid + extra;
      input.value = typed;
    }

    const candidates = forms(word);
    if (candidates.some(f => isPrefix(typed, f))) {
      live.valid = typed;
      if (input.value !== typed) input.value = typed;
      if (candidates.some(f => f.length === typed.length && isPrefix(typed, f))) finish(n, true);
      return;
    }

    // Wrong letter: count a mistake, show it in red for a moment, then remove it.
    // Several letters can arrive at once (paste, a phone's suggestion bar), so keep the
    // correct letters in front of the wrong one.
    const chars = [...typed];
    const bad = chars.findIndex((c, k) => !candidates.some(f => isPrefix(chars.slice(0, k + 1).join(""), f)));
    const wrongChar = bad >= 0 ? chars[bad] : "";
    if (bad > live.valid.length) live.valid = chars.slice(0, bad).join("");
    live.mistakes += 1;
    const card = input.closest(".answer-card");
    card.classList.remove("shake");
    void card.offsetWidth; // restart the animation
    card.classList.add("shake");
    const max = maxMistakes();
    if (max && live.mistakes >= max) { input.value = live.valid; finish(n, false); return; }
    card.querySelector(".feedback").innerHTML = triesHtml(live.mistakes, wrongChar.trim() ? wrongChar : "space");
    const showMs = Number(prefs.wrongMs) || 0;
    if (showMs > 0) {
      input.value = typed;
      input.classList.add("wrong");
      wrong = { input, value: typed, timer: setTimeout(() => clearWrong(), showMs) };
    } else {
      input.value = live.valid;
    }
  }

  // Record the answer and move to the next word straight away. Focus moves while the
  // keystroke is still being handled, so phones keep the keyboard open; the next
  // word is spoken after a short pause so the result can be read.
  function finish(n, done) {
    const word = list[n];
    results.set(word.i, { done, mistakes: live.mistakes, typed: live.valid });
    record(word, done && live.mistakes === 0);
    renderStats();
    if (n >= shown - 1 && shown < list.length) showMore();
    const next = n + 1 < shown ? n + 1 : n;
    if (next !== n) setActive(next, { play: false });
    updateRow(n);
    clearTimeout(autoNextTimer);
    if (next !== n) {
      autoNextTimer = setTimeout(() => {
        if (active === next && !results.has(list[next].i)) speak(list[next].w);
      }, done ? NEXT_AFTER_OK_MS : NEXT_AFTER_FAIL_MS);
    }
  }

  function goNext() {
    if (active >= shown - 1 && shown < list.length) showMore();
    if (active < shown - 1) setActive(active + 1);
  }
  function goPrev() {
    if (active > 0) setActive(active - 1);
  }

  /* ---------- Events ---------- */
  $("#rows").addEventListener("click", e => {
    const speakBtn = e.target.closest("[data-speak]");
    if (speakBtn) {
      const n = Number(speakBtn.dataset.speak);
      setActive(n, { play: false, scroll: false });
      speak(list[n].w);
      return;
    }
    const row = e.target.closest("[data-row]");
    if (row && !e.target.closest("input")) setActive(Number(row.dataset.row), { play: false, scroll: false });
  });

  $("#rows").addEventListener("focusin", e => {
    const input = e.target.closest("[data-input]");
    if (!input) return;
    const n = Number(input.dataset.input);
    if (n !== active) setActive(n, { scroll: false });
  });

  $("#rows").addEventListener("input", e => {
    const input = e.target.closest("[data-input]");
    if (input) onType(input);
  });

  $("#rows").addEventListener("keydown", e => {
    const input = e.target.closest("[data-input]");
    if (!input || e.key !== "Enter") return;
    e.preventDefault();
    const n = Number(input.dataset.input);
    if (e.shiftKey) { speak(list[n].w, SLOW_RATE); return; }
    if (results.has(list[n].i)) goNext(); else speak(list[n].w);
  });

  document.addEventListener("keydown", e => {
    if (!list.length || e.target.tagName === "SELECT") return;
    const plain = !e.altKey && !e.ctrlKey && !e.metaKey;
    if (e.key === "Escape") {
      e.preventDefault();
      speak(list[active].w, e.shiftKey ? SLOW_RATE : undefined);
    } else if (plain && !e.shiftKey && (e.key === "ArrowRight" || e.key === "ArrowDown")) {
      e.preventDefault(); goNext();
    } else if (plain && !e.shiftKey && (e.key === "ArrowLeft" || e.key === "ArrowUp")) {
      e.preventDefault(); goPrev();
    }
  });

  $("#moreBtn").addEventListener("click", () => {
    const next = shown;
    showMore();
    setActive(next);
  });
  $("#shuffleBtn").addEventListener("click", () => {
    shuffleSeed = newSeed();
    refresh();
    window.scrollTo({ top: $("#listInfo").offsetTop - 16, behavior: "smooth" });
  });

  for (const id of ["top", "topic", "level", "status", "order", "count"]) {
    $("#" + id).addEventListener("change", e => {
      prefs[id] = e.target.value;
      if (id === "order") shuffleSeed = newSeed();
      refresh();
    });
  }
  $("#voice").addEventListener("change", e => { prefs.voice = e.target.value; savePrefs(); speak(SAMPLE_WORD); });
  $("#rate").addEventListener("change", e => { prefs.rate = e.target.value; savePrefs(); speak(SAMPLE_WORD); });
  $("#maxMistakes").addEventListener("change", e => { prefs.maxMistakes = e.target.value; savePrefs(); });
  $("#wrongMs").addEventListener("change", e => { prefs.wrongMs = e.target.value; savePrefs(); });
  $("#settingsBtn").addEventListener("click", e => {
    const open = e.currentTarget.getAttribute("aria-expanded") !== "true";
    e.currentTarget.setAttribute("aria-expanded", String(open));
    $("#settings").hidden = !open;
  });

  /* ---------- PDF export ---------- */
  // Loaded only when exporting. Integrity hashes pin the exact files served by cdnjs.
  const PDF_LIBS = [
    { src: "https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js", sri: "sha512-qZvrmS2ekKPF2mSznTQsxqPgnpkI4DNTlrdUmTzrDgektczlKNRRhy5X5AAOnx5S09ydFYWWNSfcEqDTTHgtNA==" },
    { src: "https://cdnjs.cloudflare.com/ajax/libs/jspdf-autotable/3.8.2/jspdf.plugin.autotable.min.js", sri: "sha512-2/YdOMV+YNpanLCF5MdQwaoFRVbTmrJ4u4EpqS/USXAQNUDgI5uwYi6J98WVtJKcfe1AbgerygzDFToxAlOGEQ==" },
  ];
  const scriptLoads = new Map();
  function loadScript({ src, sri }) {
    if (!scriptLoads.has(src)) {
      scriptLoads.set(src, new Promise((resolve, reject) => {
        const el = document.createElement("script");
        el.src = src;
        el.integrity = sri;
        el.crossOrigin = "anonymous";
        el.onload = resolve;
        el.onerror = () => {
          el.remove();
          scriptLoads.delete(src); // allow a retry, e.g. once back online
          reject(new Error("Could not load " + src));
        };
        document.head.appendChild(el);
      }));
    }
    return scriptLoads.get(src);
  }
  // The PDF's built-in font only covers Latin-1, so keep text to that range
  const pdfText = s => String(s ?? "").replace(/[‘’]/g, "'").replace(/[“”]/g, '"').replace(/[–—]/g, "-").replace(/[^\x20-\xFF]/g, "");

  async function exportPdf() {
    const btn = $("#exportBtn");
    btn.disabled = true;
    btn.textContent = "Preparing PDF…";
    try {
      for (const lib of PDF_LIBS) await loadScript(lib);
      const { jsPDF } = window.jspdf;
      const doc = new jsPDF({ unit: "pt", format: "a4" });
      const accent = [47, 127, 181];
      const pageW = doc.internal.pageSize.getWidth();

      const practised = WORDS.filter(w => progress[w.key]);
      const mastered = practised.filter(w => statusOf(w) === "mastered");
      const weak = practised.filter(w => statusOf(w) === "weak").sort((a, b) => progress[b.key].x - progress[a.key].x);
      const accuracy = pdfText(totals().accuracy);

      doc.setFont("helvetica", "bold").setFontSize(20).setTextColor(43, 52, 69);
      doc.text("IELTS Spelling Progress", 40, 56);
      doc.setFont("helvetica", "normal").setFontSize(10).setTextColor(88, 98, 116);
      doc.text(new Date().toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }), 40, 74);

      const table = (title, head, body, opts = {}) => {
        let y = (doc.lastAutoTable ? doc.lastAutoTable.finalY : 84) + 30;
        if (y > doc.internal.pageSize.getHeight() - 80) { doc.addPage(); y = 50; }
        doc.setFont("helvetica", "bold").setFontSize(13).setTextColor(43, 52, 69);
        doc.text(title, 40, y);
        doc.autoTable({
          startY: y + 8, head: [head], body: body.length ? body : [[{ content: "None yet", colSpan: head.length }]],
          margin: { left: 40, right: 40 }, styles: { fontSize: 9.5, cellPadding: 5, textColor: [43, 52, 69] },
          headStyles: { fillColor: accent, textColor: 255 }, alternateRowStyles: { fillColor: [244, 246, 249] }, ...opts,
        });
      };

      table("Summary", ["Words in course", "Practised", "Mastered", "To review", "Accuracy"],
        [[fmt(WORDS.length), fmt(practised.length), fmt(mastered.length), fmt(weak.length), accuracy]]);

      table("By CEFR level", ["Level", "Words", "Practised", "Mastered"], CEFR.map(c => {
        const ws = WORDS.filter(w => w.c === c);
        return [c, fmt(ws.length), fmt(ws.filter(w => progress[w.key]).length), fmt(ws.filter(w => statusOf(w) === "mastered").length)];
      }));

      table("Words to review", ["Word", "Level", "Meaning", "Right", "Wrong"],
        weak.map(w => [pdfText(w.w), w.c || "", pdfText(w.m[0] ? w.m[0].def : ""), progress[w.key].c, progress[w.key].x]),
        { columnStyles: { 0: { fontStyle: "bold", cellWidth: 95 }, 1: { cellWidth: 38 }, 3: { cellWidth: 38 }, 4: { cellWidth: 42 } } });

      table("Mastered words", ["Word", "Level", "Meaning"],
        mastered.sort((a, b) => a.key.localeCompare(b.key)).map(w => [pdfText(w.w), w.c || "", pdfText(w.m[0] ? w.m[0].def : "")]),
        { columnStyles: { 0: { fontStyle: "bold", cellWidth: 95 }, 1: { cellWidth: 38 } } });

      const pages = doc.getNumberOfPages();
      for (let i = 1; i <= pages; i++) {
        doc.setPage(i);
        doc.setFontSize(8.5).setTextColor(138, 147, 163);
        doc.text(`Page ${i} of ${pages}`, pageW - 40, doc.internal.pageSize.getHeight() - 24, { align: "right" });
      }
      doc.save(`ielts-spelling-progress-${new Date().toISOString().slice(0, 10)}.pdf`);
    } catch (err) {
      alert("Could not create the PDF. Check your internet connection and try again.");
    } finally {
      btn.disabled = false;
      btn.textContent = "Export PDF";
    }
  }
  $("#exportBtn").addEventListener("click", exportPdf);

  $("#resetAllBtn").addEventListener("click", () => {
    if (!confirm("Reset everything? This deletes your progress and your settings (topic, voice, mistakes allowed…) from this browser.")) return;
    try { localStorage.removeItem(KEY_PROGRESS); localStorage.removeItem(KEY_PREFS); } catch { /* storage unavailable */ }
    location.reload();
  });
  $("#resetBtn").addEventListener("click", () => {
    if (!confirm("Delete all your saved progress? This cannot be undone.")) return;
    progress = {};
    saveProgress();
    refresh();
  });

  /* ---------- Privacy notice (shown once; nothing to consent to, since nothing is collected) ---------- */
  const KEY_NOTICE = "isp.notice.v1";
  if (!storage.get(KEY_NOTICE, null)) {
    const notice = $("#notice");
    notice.hidden = false;
    $("#noticeOk").addEventListener("click", () => {
      notice.hidden = true;
      storage.set(KEY_NOTICE, { seen: 1 });
    });
  }

  /* ---------- Start ---------- */
  if (!WORDS.length) {
    $("#rows").innerHTML = '<p class="empty">Word data is missing. Run tools/build_data.py to create data/words.js.</p>';
    return;
  }
  $('#top option[value="all"]').textContent = `All ${fmt(WORDS.length)} words`;
  $("#topic").innerHTML = '<option value="all">All topics</option>' +
    TOPICS.map(t => `<option value="${esc(t)}">${esc(t)} (${WORDS.filter(w => w.t === t).length})</option>`).join("");
  // A saved value that is no longer an option (renamed topic, old version) falls back to the default
  for (const id of ["top", "topic", "level", "status", "order", "count", "maxMistakes", "wrongMs", "rate"]) {
    const select = $("#" + id);
    select.value = prefs[id];
    if (select.value !== prefs[id]) select.value = prefs[id] = DEFAULT_PREFS[id];
  }
  if (synth) {
    loadVoices();
    synth.addEventListener?.("voiceschanged", loadVoices);
  } else {
    $("#voice").innerHTML = "<option>Speech not supported</option>";
  }
  refresh();
})();
