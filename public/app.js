(() => {
  const SONGS = window.SONGS || [];
  const $ = (id) => document.getElementById(id);

  // Durées d'extrait, de la plus courte à la plus longue.
  const STAGES = [0.5, 2, 4, 8, 16];

  const store = {
    get(k, d) { try { const v = localStorage.getItem("songspotteur:" + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("songspotteur:" + k, JSON.stringify(v)); } catch {} },
  };

  const state = {
    streak: store.get("streak", 0),
    best: Math.max(store.get("best", 0), store.get("streak", 0)), // meilleure série, gardée dans le navigateur
    round: 0,
    results: [],
    history: [],
    song: null,
    buffer: null,
    offset: 0,
    stage: 0,
    over: false,
    source: null,
    raf: 0,
  };

  let ctx = null;
  const audio = () => (ctx ||= new (window.AudioContext || window.webkitAudioContext)());

  const norm = (s) => s.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/œ/g, "oe").replace(/[^a-z0-9]+/g, " ").trim();
  const fmt = (s) => `${String(s).replace(".", ",")} s`;

  // ---------- Extraits ----------
  // Durées offertes pour la chanson en cours : on retire celles que l'aperçu ne couvre pas.
  const stages = () => state.stages || STAGES;
  const REVEAL_LEN = 15;
  const QUESTION = "Quelle est cette chanson\u202f?"; // espace fine insécable : le « ? » ne passe jamais seul à la ligne
  const HINT = "Écoute l'extrait, puis devine le titre.";

  // Une capsule par durée d'extrait, colorée selon ce qui s'est passé.
  function renderTimeline() {
    $("stages").innerHTML = "";
    stages().forEach((t, i) => {
      const li = document.createElement("li");
      const result = state.results[i];
      if (result) li.className = result;
      else if (i === state.stage && !state.over) li.className = "current";
      li.innerHTML = `<span class="track"><i class="bar"></i></span><span class="dur">${fmt(t)}</span>`;
      if (i <= state.stage && !state.over) {
        li.classList.add("replay");
        li.title = `Réécouter ${fmt(t)}`;
        li.onclick = () => play(t, i);
      }
      $("stages").append(li);
    });
    const last = state.stage >= stages().length - 1;
    $("skip").hidden = state.over;
    $("skip").textContent = last ? "Je ne sais pas" : `Extrait plus long · ${fmt(stages()[state.stage + 1])}`;
    $("skip").classList.toggle("give-up", last);
  }

  // Le catalogue garde des pochettes de 250–300 px, assez pour l'historique et le
  // fond flou. La grande pochette demande 1000 px au même serveur (WebP chez Apple :
  // trois fois plus léger que leur JPEG, pour la même image).
  const bigArt = (url) => (url || "")
    .replace(/\/250x250-(?=000000-)/, "/1000x1000-")
    .replace(/\/300x300bb\.jpg$/, "/1000x1000bb.webp");

  // Arrière-plan flou : la pochette de la dernière chanson révélée, en fondu.
  let bgFront = "bgA";
  function setBackdrop(url) {
    if (!url) return;
    const next = bgFront === "bgA" ? "bgB" : "bgA";
    $(next).style.backgroundImage = `url("${url}")`;
    $(next).classList.add("on");
    $(bgFront).classList.remove("on");
    bgFront = next;
  }

  // ---------- Audio ----------
  function stop() {
    if (state.source) { try { state.source.stop(); } catch {} state.source = null; }
    cancelAnimationFrame(state.raf);
    document.querySelectorAll("#stages .bar").forEach((b) => (b.style.width = "0"));
    $("artwork").classList.remove("playing");
    $("play").classList.remove("is-playing");
  }

  // Petits sons de jeu, synthétisés : pas de fichiers à charger.
  function tone(freq, start, dur, { type = "sine", gain = 0.18, to } = {}) {
    const ac = audio();
    const osc = ac.createOscillator();
    const g = ac.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, start);
    if (to) osc.frequency.exponentialRampToValueAtTime(to, start + dur);
    g.gain.setValueAtTime(0, start);
    g.gain.linearRampToValueAtTime(gain, start + 0.008);
    g.gain.exponentialRampToValueAtTime(0.0001, start + dur);
    osc.connect(g).connect(ac.destination);
    osc.start(start);
    osc.stop(start + dur + 0.02);
  }

  const sfx = {
    // Arpège majeur ascendant ; plus long et plus brillant quand c'est trouvé du premier coup.
    right(stage) {
      const t = audio().currentTime + 0.03;
      const notes = stage === 0 ? [523.25, 659.25, 783.99, 1046.5, 1318.5] : [587.33, 739.99, 880, 1174.66];
      notes.forEach((f, i) => {
        tone(f, t + i * 0.075, 0.5, { type: "triangle", gain: 0.16 });
        tone(f * 2, t + i * 0.075, 0.25, { gain: 0.04 });
      });
      tone(notes.at(-1), t + notes.length * 0.075, 0.9, { gain: 0.08 });
    },
    wrong() {
      const t = audio().currentTime + 0.02;
      tone(196, t, 0.22, { type: "triangle", gain: 0.2, to: 110 });
      tone(98, t, 0.25, { gain: 0.15 });
    },
    skip() {
      tone(1400, audio().currentTime + 0.01, 0.05, { type: "square", gain: 0.03, to: 900 });
    },
    lose() {
      const t = audio().currentTime + 0.05;
      [392, 349.23, 293.66].forEach((f, i) => tone(f, t + i * 0.16, 0.35, { type: "triangle", gain: 0.12 }));
    },
  };

  // L'API Deezer n'envoie pas d'en-têtes CORS : on passe par JSONP pour
  // obtenir un lien d'aperçu frais (ils expirent après ~15 min).
  let jsonpId = 0;
  function previewUrl(id) {
    return new Promise((resolve, reject) => {
      const cb = `__dz${++jsonpId}`;
      const script = document.createElement("script");
      const done = () => { delete window[cb]; script.remove(); clearTimeout(timer); };
      const timer = setTimeout(() => { done(); reject(new Error("timeout")); }, 8000);
      window[cb] = (data) => { done(); data?.preview ? resolve(data.preview) : reject(new Error("no preview")); };
      script.onerror = () => { done(); reject(new Error("jsonp")); };
      script.src = `https://api.deezer.com/track/${id}?output=jsonp&callback=${cb}`;
      document.head.append(script);
    });
  }

  // Identifiant Deezer d'une chanson (les plus anciennes entrées n'ont que `id`).
  const deezerId = (song) => song.deezer ?? (typeof song.id === "number" ? song.id : null);

  async function fetchAudio(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return audio().decodeAudioData(await res.arrayBuffer());
  }

  // Extrait Apple Music (AAC ~256 kb/s, lien stable) en priorité ; Deezer en secours
  // si la chanson n'a pas d'extrait Apple ou si celui-ci ne charge pas.
  async function load(song) {
    if (song.preview) {
      try { return await fetchAudio(song.preview); }
      catch (e) { if (!deezerId(song)) throw e; console.warn("Extrait Apple indisponible, secours Deezer", song.title, e); }
    }
    return fetchAudio(await previewUrl(deezerId(song)));
  }

  // Les aperçus Deezer commencent souvent par un fondu : on saute au premier
  // moment où le son atteint la moitié du niveau typique de l'extrait.
  function loudStart(buf) {
    const data = buf.getChannelData(0);
    const win = Math.floor(buf.sampleRate * 0.05);
    const rms = [];
    for (let i = 0; i + win <= data.length; i += win) {
      let sum = 0;
      for (let j = i; j < i + win; j++) sum += data[j] * data[j];
      rms.push(Math.sqrt(sum / win));
    }
    const typical = [...rms].sort((a, b) => a - b)[Math.floor(rms.length * 0.6)] || 0;
    const first = rms.findIndex((v) => v >= typical * 0.5);
    // On garde de quoi jouer l'extrait le plus long après le point de départ.
    return Math.min(Math.max(0, first) * 0.05, Math.max(0, buf.duration - STAGES.at(-1) - 0.5));
  }

  function play(seconds, barIndex = state.stage) {
    if (!state.buffer) return;
    stop();
    const ac = audio();
    if (ac.state === "suspended") ac.resume();
    const src = ac.createBufferSource();
    const gain = ac.createGain();
    src.buffer = state.buffer;
    src.connect(gain);
    window.Viz ? Viz.connect(ac, gain) : gain.connect(ac.destination);
    // Micro-fondu pour éviter les clics sur les extraits ultra-courts.
    const t0 = ac.currentTime + 0.02;
    const fade = Math.min(0.008, seconds / 4);
    gain.gain.setValueAtTime(0, t0);
    gain.gain.linearRampToValueAtTime(1, t0 + fade);
    gain.gain.setValueAtTime(1, t0 + seconds - fade);
    gain.gain.linearRampToValueAtTime(0, t0 + seconds);
    src.start(t0, state.offset, seconds);
    state.source = src;
    src.onended = () => { if (state.source === src) stop(); };

    $("artwork").classList.add("playing");
    $("play").classList.add("is-playing");
    // La barre avance dans la case de l'extrait en cours.
    const bar = state.over ? null : $("stages").children[barIndex]?.querySelector(".bar");
    const tick = () => {
      const t = Math.max(0, ac.currentTime - t0);
      if (bar) bar.style.width = `${Math.min(1, t / seconds) * 100}%`;
      if (t < seconds) state.raf = requestAnimationFrame(tick);
    };
    tick();
  }

  // ---------- Partie ----------
  // Chansons déjà tirées, gardées dans le navigateur : aucune répétition avant d'avoir
  // fait le tour du catalogue, même d'une visite à l'autre. Les chansons ajoutées plus
  // tard comptent comme pas encore jouées ; celles retirées du catalogue sont oubliées.
  const catalogIds = new Set(SONGS.map((s) => s.id));
  const played = new Set(store.get("played", []).filter((id) => catalogIds.has(id)));

  function pickSong() {
    if (!SONGS.length) return null;
    // On évite aussi la chanson en cours, qui n'est marquée jouée qu'au début de sa manche.
    let fresh = SONGS.filter((s) => !played.has(s.id) && s.id !== state.song?.id);
    if (!fresh.length) {
      // Tour complet : on recommence, sans reprendre tout de suite les dernières entendues.
      const last = new Set([...played].slice(-20));
      played.clear();
      fresh = SONGS.filter((s) => !last.has(s.id) && s.id !== state.song?.id);
    }
    return fresh[Math.floor(Math.random() * fresh.length)];
  }

  // Une chanson compte comme jouée quand sa manche commence (pas quand elle est préchargée).
  function markPlayed(song) {
    played.add(song.id);
    store.set("played", [...played]);
  }

  // La prochaine chanson se télécharge pendant qu'on joue la courante.
  let preload = null;
  function preloadNext() {
    const song = pickSong();
    if (!song) return;
    preload = { song, buf: load(song).catch(() => null) };
  }

  // Les navigateurs bloquent le son avant un premier geste ; après, on enchaîne tout seul.
  let interacted = false;
  for (const ev of ["pointerdown", "keydown"]) addEventListener(ev, () => (interacted = true), { once: true, capture: true });

  let loadToken = 0;
  async function newRound() {
    stop();
    state.stage = 0;
    state.over = false;
    state.buffer = null;
    state.results = [];
    state.stages = null;
    state.guessed = new Set();
    const pre = preload;
    preload = null;
    state.song = pre && !played.has(pre.song.id) ? pre.song : pickSong();
    if (state.song) markPlayed(state.song);
    state.round += 1;
    $("round").textContent = `Chanson ${state.round}`;
    $("attempts").innerHTML = "";
    $("reveal").hidden = true;
    $("searchBox").hidden = false;
    $("searchBox").classList.remove("shake");
    $("verdict").hidden = true;
    $("songMeta").hidden = true;
    $("songShows").hidden = true;
    $("songTitle").textContent = QUESTION;
    $("songArtist").textContent = HINT;
    document.querySelector(".heading").classList.remove("revealed");
    $("artwork").classList.remove("revealed");
    $("artwork").classList.add("idle");
    window.Viz?.setActive(true);
    $("guess").value = "";
    $("clear").hidden = true;
    $("guess").disabled = $("skip").disabled = !state.song;
    closeSuggest();
    renderTimeline();
    if (!state.song) { setStatus(""); $("play").disabled = true; return; }

    const token = ++loadToken;
    const song = state.song;
    $("play").classList.add("loading");
    setStatus("Chargement…");
    try {
      const buf = (pre && pre.song === song && (await pre.buf)) || (await load(song));
      if (token !== loadToken) return;
      state.buffer = buf;
      state.offset = loudStart(buf);
      const room = buf.duration - state.offset;
      state.stages = STAGES.filter((t, i) => i === 0 || t <= room);
      renderTimeline();
      setStatus("Prêt");
      $("play").classList.remove("loading");
      if (interacted) play(stages()[0]);
      preloadNext();
      // La grande pochette se charge pendant la manche : prête à la révélation.
      new Image().src = bigArt(song.art);
    } catch (e) {
      if (token !== loadToken) return;
      console.warn("Extrait introuvable, on passe à la suivante", song, e);
      return newRound();
    } finally {
      if (token === loadToken) $("play").classList.remove("loading");
      $("play").disabled = false;
    }
  }

  function setStatus(t) { $("status").textContent = t; }

  function addAttempt(kind, text) {
    state.results[state.stage] = kind;
    // Les extraits allongés se voient déjà dans les capsules ; la liste ne garde que les essais ratés.
    if (kind !== "wrong") return;
    const li = document.createElement("li");
    li.className = kind;
    const mark = '<svg viewBox="0 0 12 12"><path d="m3 3 6 6m0-6-6 6"/></svg>';
    li.innerHTML = `<span class="t">${fmt(stages()[state.stage])}</span><span class="mark">${mark}</span><span class="txt"></span>`;
    li.querySelector(".txt").textContent = text;
    $("attempts").append(li);
  }

  function advance(delay = 0) {
    if (state.stage >= stages().length - 1) return finish(false);
    state.stage++;
    renderTimeline();
    const stage = state.stage;
    setTimeout(() => { if (!state.over && state.stage === stage) play(stages()[stage]); }, delay);
  }

  function guess(song) {
    if (state.over || !state.song) return;
    if (song.id === state.song.id || (norm(song.title) === norm(state.song.title) && song.artist === state.song.artist)) {
      addAttempt("right", `${song.title} — ${song.artist}`);
      finish(true);
    } else {
      addAttempt("wrong", `${song.title} — ${song.artist}`);
      state.guessed.add(song.id);
      sfx.wrong();
      stop();
      const box = $("searchBox");
      box.classList.remove("shake"); void box.offsetWidth; box.classList.add("shake");
      // Laisse le son du mauvais essai finir avant l'extrait plus long.
      advance(450);
    }
  }

  // Prochains spectacles de l'artiste (scripts/shows.py, mis à jour chaque semaine) :
  // seulement ceux à venir et dans les six prochains mois, au plus deux.
  const localDate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  function renderShows(artist) {
    const now = new Date(), until = new Date(now);
    until.setMonth(until.getMonth() + 6);
    const from = localDate(now), to = localDate(until);
    const shows = ((window.SHOWS || {})[artist] || []).filter((s) => s.date >= from && s.date <= to).slice(0, 2);
    const p = $("songShows");
    p.replaceChildren();
    shows.forEach((show, i) => {
      const [y, m, d] = show.date.split("-").map(Number);
      const a = document.createElement("a");
      a.href = show.url;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = new Date(y, m - 1, d).toLocaleDateString("fr-CA", { day: "numeric", month: "short" })
        + (show.city ? ` à ${show.city}` : "");
      a.title = [show.venue, show.city].filter(Boolean).join(", ");
      p.append(i ? " · " : "En spectacle : ", a);
    });
    p.hidden = !shows.length;
  }

  function finish(won) {
    const stage = state.stage;
    state.over = true;
    stop();
    const s = state.song;
    let msg;
    if (won) {
      state.streak += 1;
      const record = state.streak > state.best;
      if (record) state.best = state.streak;
      msg = stage === 0 ? "Du premier coup" : `Trouvée en ${fmt(stages()[stage])}`;
      if (record && state.streak >= 2) msg += " · Nouveau record";
      sfx.right(stage);
      renderScore(true, record);
    } else {
      state.streak = 0;
      msg = "Pas cette fois";
      sfx.lose();
      renderScore();
    }
    store.set("streak", state.streak);
    store.set("best", state.best);
    renderTimeline();
    $("verdict").textContent = msg;
    $("verdict").className = "verdict " + (won ? "win" : "lose");
    $("verdict").hidden = false;
    $("songTitle").textContent = s.title;
    $("songArtist").textContent = s.artist;
    $("songMeta").textContent = `${s.year} · ${s.genre}`;
    // Lien vers la page Bandcamp de l'artiste, quand il en a une.
    const bandcamp = (window.BANDCAMP || {})[s.artist];
    if (bandcamp) {
      const a = document.createElement("a");
      a.className = "bandcamp";
      a.href = bandcamp;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = "Bandcamp";
      a.title = `${s.artist} sur Bandcamp`;
      $("songMeta").append(" · ", a);
    }
    $("songMeta").hidden = false;
    renderShows(s.artist);
    document.querySelector(".heading").classList.add("revealed");
    $("art").src = bigArt(s.art);
    $("art").alt = `Pochette — ${s.title}`;
    $("artwork").classList.remove("idle");
    $("artwork").classList.add("revealed");
    // Le visualiseur s'arrête une fois la pochette affichée (après le fondu).
    setTimeout(() => { if (state.over) window.Viz?.setActive(false); }, 700);
    setBackdrop(s.art);
    addToHistory({ song: s, won, label: won ? fmt(stages()[stage]) : "Ratée" });
    setLink($("apple"), s);
    $("searchBox").hidden = true;
    $("attempts").innerHTML = ""; // la réponse est affichée : plus besoin des essais
    $("reveal").hidden = false;
    $("guess").disabled = $("skip").disabled = true;
    closeSuggest();
    setStatus(`${s.title}, ${s.artist}`);
    // Le focus passe au bouton suivant, sans contour : on n'y est pas allé au clavier.
    // Le contour revient si on quitte le bouton puis qu'on y revient avec Tab.
    $("next").classList.add("auto-focus");
    $("next").addEventListener("blur", () => $("next").classList.remove("auto-focus"), { once: true });
    $("next").focus();
    // La récompense : la chanson joue, après le carillon.
    setTimeout(() => { if (state.over && state.song === s) play(Math.min(REVEAL_LEN, state.buffer?.duration ?? REVEAL_LEN)); }, won ? 650 : 900);
  }

  // ---------- Ouvrir la chanson dans une app de musique ----------
  // Un navigateur ne peut pas connaître l'app de musique par défaut : on la demande
  // une fois, puis on retient le choix. Chaque lien est un vrai lien que le navigateur
  // passe directement à l'app, sans détour réseau au moment du clic.
  const query = (song) => encodeURIComponent(`${song.artist} ${song.title}`);
  const APPS = {
    apple: { name: "Apple Music", link: (song, exact) => song.apple ? `music://music.apple.com/ca/song/${song.apple}` : exact ? exact.replace(/^https:/, "music:") : `music://music.apple.com/ca/search?term=${query(song)}` },
    spotify: { name: "Spotify", link: (song) => `spotify:search:${query(song)}` },
    deezer: { name: "Deezer", link: (song) => deezerId(song) ? `deezer://www.deezer.com/track/${deezerId(song)}` : `deezer://www.deezer.com/search/${query(song)}` },
    youtube: { name: "YouTube Music", web: true, link: (song) => `https://music.youtube.com/search?q=${query(song)}` },
  };
  let app = APPS[store.get("app", "")] ? store.get("app", "") : null;

  // Lien exact vers la piste Apple Music (via la recherche iTunes), une fois par chanson.
  const appleTracks = new Map();
  function lookupApple(song) {
    if (appleTracks.has(song.id)) return appleTracks.get(song.id);
    const found = new Promise((resolve) => {
      const cb = `__it${song.id}`;
      const script = document.createElement("script");
      const done = (url) => { delete window[cb]; script.remove(); clearTimeout(timer); resolve(url); };
      const timer = setTimeout(() => done(null), 5000);
      window[cb] = (data) => {
        const want = norm(song.title);
        const artist = norm(song.artist).replace(/ /g, "");
        const hit = (data.results || []).find((r) =>
          norm(r.artistName || "").replace(/ /g, "").includes(artist) &&
          norm(r.trackName || "").startsWith(want));
        done(hit ? hit.trackViewUrl.replace(/[?&]uo=\d+/, "") : null);
      };
      script.onerror = () => done(null);
      script.src = `https://itunes.apple.com/search?${new URLSearchParams({ term: `${song.artist} ${song.title}`, country: "CA", entity: "song", limit: "10", callback: cb })}`;
      document.head.append(script);
    });
    appleTracks.set(song.id, found);
    return found;
  }

  // Les liens « ouvrir » de la page (bouton et cartes) et leur chanson.
  const linkSongs = new WeakMap();
  function setLink(a, song) {
    linkSongs.set(a, song);
    a.classList.add("music-link");
    if (!app) { a.href = "#"; a.removeAttribute("target"); return; }
    const def = APPS[app];
    a.href = def.link(song);
    if (def.web) { a.target = "_blank"; a.rel = "noopener"; } else a.removeAttribute("target");
    if (app === "apple" && !song.apple) lookupApple(song).then((exact) => { if (exact && app === "apple" && linkSongs.get(a) === song) a.href = def.link(song, exact); });
  }

  function renderOpenButton() {
    $("apple").textContent = app ? `Ouvrir dans ${APPS[app].name}` : "Ouvrir dans une app de musique";
  }

  function setApp(key) {
    app = key;
    store.set("app", key);
    renderOpenButton();
    document.querySelectorAll("a.music-link").forEach((a) => linkSongs.has(a) && setLink(a, linkSongs.get(a)));
  }

  // Menu de choix de l'app, placé près du lien qui l'a ouvert.
  let pending = null;
  function openChooser(anchor, follow) {
    pending = follow ? anchor : null;
    const menu = $("appChooser");
    menu.innerHTML = `<li class="chooser-title">Ouvrir avec</li>`;
    for (const [key, def] of Object.entries(APPS)) {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.type = "button";
      b.setAttribute("role", "menuitemradio");
      b.setAttribute("aria-checked", String(key === app));
      b.innerHTML = `<span></span><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3.5 8.5 3 3 6-7"/></svg>`;
      b.firstChild.textContent = def.name;
      b.onclick = () => pickApp(key);
      li.append(b);
      menu.append(li);
    }
    menu.hidden = false;
    const r = anchor.getBoundingClientRect(), m = menu.getBoundingClientRect();
    const top = r.top - m.height - 8 >= 8 ? r.top - m.height - 8 : r.bottom + 8;
    menu.style.top = `${top}px`;
    menu.style.left = `${Math.max(8, Math.min(r.right - m.width, innerWidth - m.width - 8))}px`;
    (menu.querySelector('[aria-checked="true"]') || menu.querySelector("button")).focus();
  }
  function closeChooser() { $("appChooser").hidden = true; pending = null; }
  function pickApp(key) {
    const target = pending;
    closeChooser();
    setApp(key);
    if (!target) return;
    // Le clic dans le menu compte comme geste de l'utilisateur : on suit le lien tout de suite.
    if (APPS[key].web) window.open(target.href, "_blank", "noopener");
    else location.href = target.href;
  }

  // Sans app choisie, un lien « ouvrir » demande d'abord laquelle utiliser.
  document.addEventListener("click", (e) => {
    const a = e.target.closest?.("a.music-link");
    if (a && !app) { e.preventDefault(); openChooser(a, true); }
  });
  $("appMenu").onclick = (e) => { e.stopPropagation(); $("appChooser").hidden ? openChooser($("appMenu"), false) : closeChooser(); };
  document.addEventListener("pointerdown", (e) => {
    if (!$("appChooser").hidden && !e.target.closest("#appChooser, #appMenu, a.music-link")) closeChooser();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("appChooser").hidden) closeChooser(); });
  addEventListener("resize", closeChooser);


  // Les chansons de la partie, la plus récente en premier (à gauche) ;
  // la bande revient doucement au début pour la montrer.
  const HISTORY_MAX = 24;
  function addToHistory(entry) {
    state.history.unshift(entry);
    const list = $("history");
    list.prepend(historyCard(entry));
    while (list.children.length > HISTORY_MAX) list.lastElementChild.remove();
    requestAnimationFrame(() => list.scrollTo({ left: 0, behavior: "smooth" }));
  }

  // Bande d'historique à la souris : la molette fait défiler à l'horizontale, et on
  // peut glisser la bande. Un glissement n'ouvre pas la carte sous le curseur.
  const strip = $("history");
  strip.addEventListener("wheel", (e) => {
    if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return; // le trackpad défile déjà à l'horizontale
    const max = strip.scrollWidth - strip.clientWidth;
    if (max <= 0) return;
    // Aux extrémités, on rend la molette à la page.
    if ((e.deltaY < 0 && strip.scrollLeft <= 0) || (e.deltaY > 0 && strip.scrollLeft >= max - 1)) return;
    e.preventDefault();
    strip.scrollBy({ left: e.deltaY * (e.deltaMode === 1 ? 32 : 1) });
  }, { passive: false });

  let drag = null;
  strip.addEventListener("pointerdown", (e) => {
    if (e.pointerType !== "mouse" || e.button !== 0) return;
    drag = { x: e.clientX, left: strip.scrollLeft, moved: false };
  });
  addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x;
    if (!drag.moved && Math.abs(dx) > 5) { drag.moved = true; strip.classList.add("dragging"); }
    if (drag.moved) strip.scrollLeft = drag.left - dx;
  });
  addEventListener("pointerup", () => {
    if (drag?.moved) {
      // Avale le clic qui suit un glissement.
      strip.addEventListener("click", (e) => { e.stopPropagation(); e.preventDefault(); }, { capture: true, once: true });
      setTimeout(() => strip.classList.remove("dragging"), 0);
    }
    drag = null;
  });

  function historyCard({ song, won, label }) {
    const li = document.createElement("li");
    li.className = won ? "won" : "lost";
    // Chaque carte ouvre la chanson dans l'app de musique choisie.
    const a = document.createElement("a");
    a.draggable = false; // sinon glisser la bande traînerait le lien
    a.title = `${song.title} — ${song.artist}`;
    a.setAttribute("aria-label", `Ouvrir ${song.title} de ${song.artist}`);
    a.innerHTML = `<img alt="" loading="lazy" draggable="false"><span class="info"><b></b><span></span></span><span class="chip"></span>`;
    a.querySelector("img").src = song.art;
    a.querySelector("b").textContent = song.title;
    a.querySelector(".info span").textContent = song.artist;
    a.querySelector(".chip").textContent = label;
    setLink(a, song);
    li.append(a);
    return li;
  }

  // Série en cours et record ; une bonne réponse fait battre la série (et le record s'il tombe).
  function renderScore(won = false, record = false) {
    $("streak").textContent = state.streak;
    $("best").textContent = state.best;
    if (!won) return;
    for (const b of record ? [$("streak"), $("best")] : [$("streak")]) {
      b.classList.remove("bump"); void b.offsetWidth; b.classList.add("bump");
      b.addEventListener("animationend", () => b.classList.remove("bump"), { once: true });
    }
  }



  // ---------- Autocomplétion ----------
  const choices = [...new Map(SONGS.map((s) => [norm(s.title) + "|" + s.artist, s])).values()]
    .map((s) => ({ song: s, key: norm(s.title + " " + s.artist), title: norm(s.title) }));
  let active = -1;
  let shown = [];

  function closeSuggest() { $("suggest").hidden = true; active = -1; shown = []; $("guess").removeAttribute("aria-activedescendant"); }

  function renderSuggest() {
    const q = norm($("guess").value);
    if (!q) return closeSuggest();
    const words = q.split(" ");
    shown = choices
      .filter((c) => words.every((w) => c.key.includes(w)) && !state.guessed?.has(c.song.id))
      .sort((a, b) => (b.title.startsWith(q) - a.title.startsWith(q)) || a.title.localeCompare(b.title))
      .slice(0, 8);
    const ul = $("suggest");
    ul.innerHTML = "";
    if (!shown.length) return closeSuggest();
    active = 0;
    shown.forEach((c, i) => {
      const li = document.createElement("li");
      li.id = "opt-" + i;
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", String(i === active));
      li.textContent = c.song.title;
      const small = document.createElement("small");
      small.textContent = c.song.artist;
      li.append(small);
      li.onmousedown = (e) => { e.preventDefault(); choose(i); };
      // La sélection suit la souris, comme au clavier.
      li.onmousemove = () => { if (active !== i) highlight(i); };
      ul.append(li);
    });
    ul.hidden = false;
    placeSuggest();
    $("guess").setAttribute("aria-activedescendant", "opt-0");
  }

  // Ouvre la liste là où elle tient : en dessous du champ si la place suffit
  // (ou s'il y a de quoi montrer ~5 suggestions, pour ne pas cacher les commandes),
  // sinon au-dessus, et jamais plus haute que l'espace disponible.
  function placeSuggest() {
    const ul = $("suggest");
    if (ul.hidden) return;
    const field = $("searchBox").getBoundingClientRect();
    const margin = 12, gap = 8;
    const below = innerHeight - field.bottom - gap - margin;
    const above = field.top - gap - margin;
    ul.style.maxHeight = "";
    const wanted = Math.min(ul.scrollHeight, 330);
    const up = below < Math.min(wanted, 220) && above > below;
    ul.classList.toggle("up", up);
    ul.style.maxHeight = `${Math.max(120, Math.min(330, up ? above : below))}px`;
  }
  addEventListener("resize", placeSuggest);
  addEventListener("scroll", placeSuggest, { passive: true });

  function highlight(i) {
    active = (i + shown.length) % shown.length;
    [...$("suggest").children].forEach((li, j) => li.setAttribute("aria-selected", String(j === active)));
    $("suggest").children[active]?.scrollIntoView({ block: "nearest" });
    $("guess").setAttribute("aria-activedescendant", "opt-" + active);
  }

  function choose(i) {
    const c = shown[i];
    if (!c) return;
    $("guess").value = "";
    $("clear").hidden = true;
    closeSuggest();
    guess(c.song);
  }

  // Bouton d'effacement maison : visible seulement quand il y a du texte.
  const syncClear = () => { $("clear").hidden = !$("guess").value; };
  // Le contour rouge d'un mauvais essai s'efface dès qu'on revient dans le champ.
  const clearWrong = () => $("searchBox").classList.remove("shake");
  $("searchBox").addEventListener("pointerdown", clearWrong);
  $("guess").addEventListener("focus", clearWrong);
  // Revenir dans le champ rouvre les suggestions pour le texte déjà tapé.
  const reopenSuggest = () => { if ($("guess").value.trim() && $("suggest").hidden && !state.over) renderSuggest(); };
  $("guess").addEventListener("focus", reopenSuggest);
  $("guess").addEventListener("click", reopenSuggest);
  $("guess").addEventListener("input", () => { clearWrong(); syncClear(); renderSuggest(); });
  $("clear").addEventListener("pointerdown", (e) => e.preventDefault()); // garde le focus dans le champ
  $("clear").onclick = () => { $("guess").value = ""; syncClear(); closeSuggest(); $("guess").focus(); };
  $("guess").addEventListener("blur", () => setTimeout(closeSuggest, 100));
  $("guess").addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" && shown.length) { e.preventDefault(); highlight(active + 1); }
    else if (e.key === "ArrowUp" && shown.length) { e.preventDefault(); highlight(active - 1); }
    else if (e.key === "Enter" && shown.length) { e.preventDefault(); choose(active); }
    else if (e.key === "Enter" && !$("guess").value.trim()) { e.preventDefault(); $("play").click(); }
    // Échap ferme d'abord la liste sans effacer le texte (le champ de recherche l'effacerait).
    else if (e.key === "Escape" && !$("suggest").hidden) { e.preventDefault(); closeSuggest(); }
  });

  // ---------- Contrôles ----------
  $("play").onclick = () => {
    if (state.source) return stop();
    if (state.over) return play(Math.min(REVEAL_LEN, state.buffer?.duration ?? REVEAL_LEN));
    play(stages()[state.stage]);
  };
  $("skip").onclick = () => {
    if (state.over || !state.song) return;
    if (state.stage >= stages().length - 1) {
      state.results[state.stage] = "skipped";
      return finish(false);
    }
    addAttempt("skipped", "Extrait plus long");
    sfx.skip();
    advance();
  };
  $("next").onclick = newRound;

  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT") return;
    if (e.code === "Space") { e.preventDefault(); $("play").click(); }
    else if (e.key === "Enter" && state.over) { e.preventDefault(); newRound(); }
  });

  renderScore();
  renderOpenButton();
  newRound();
})();
