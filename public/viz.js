// Visualiseur affiché à la place de la pochette : une matrice de points carrée,
// comme la pochette qu'elle remplace. Chaque colonne est une bande de fréquence
// (graves à gauche, aigus à droite) qui s'allume du centre vers les bords.
// Chaque colonne est un petit ressort amorti : le mouvement reste souple.
window.Viz = (() => {
  const canvas = document.getElementById("viz");
  const g = canvas.getContext("2d");

  const COLS = 32, ROWS = 32;
  const F_LO = 50, F_HI = 4000;   // plage utile, en Hz
  const EDGE = [91, 149, 255];    // bleu du « QC » : teinte les points vers les bords

  const pos = new Float32Array(COLS);
  const vel = new Float32Array(COLS);
  const raw = new Float32Array(COLS);
  let analyser = null, freq = null, bands = null;
  let w = 0, h = 0, dpr = 1, raf = 0, last = 0;
  let grid = null, x0 = 0, y0 = 0, step = 0, dot = 0;

  // Couleur de chaque rangée : blanc au centre, bleu vers les bords.
  const mid = (ROWS - 1) / 2;
  const tint = Array.from({ length: ROWS }, (_, r) => {
    const d = Math.abs(r - mid) / mid;
    const [R, G, B] = EDGE.map((c) => Math.round(255 + (c - 255) * d));
    return `rgb(${R}, ${G}, ${B})`;
  });

  function resize() {
    dpr = Math.min(2, window.devicePixelRatio || 1);
    // Taille de mise en page, pas getBoundingClientRect : la pochette est réduite à 94 %
    // au repos (transform), et le canvas serait alors dessiné trop petit puis étiré.
    w = Math.max(1, Math.round(canvas.clientWidth * dpr));
    h = Math.max(1, Math.round(canvas.clientHeight * dpr));
    canvas.width = w;
    canvas.height = h;

    // La grille couvre toute la pochette : chaque point au centre de sa case,
    // donc une demi-case aux bords, comme entre deux points.
    const side = Math.min(w, h);
    step = side / COLS;
    x0 = (w - side) / 2 + step / 2;
    y0 = (h - side) / 2 + step / 2;
    dot = Math.max(0.75, step * 0.13);

    // La grille éteinte ne bouge pas : dessinée une fois, puis recopiée à chaque image.
    grid = document.createElement("canvas");
    grid.width = w;
    grid.height = h;
    const gg = grid.getContext("2d");
    gg.fillStyle = "rgba(255, 255, 255, 0.06)";
    gg.beginPath();
    for (let c = 0; c < COLS; c++) {
      for (let r = 0; r < ROWS; r++) {
        gg.moveTo(x0 + c * step + dot, y0 + r * step);
        gg.arc(x0 + c * step, y0 + r * step, dot, 0, Math.PI * 2);
      }
    }
    gg.fill();
  }
  new ResizeObserver(resize).observe(canvas);

  // Branche une source audio : elle passe par l'analyseur avant les haut-parleurs.
  function connect(ac, node) {
    if (!analyser) {
      analyser = ac.createAnalyser();
      analyser.fftSize = 4096;
      analyser.smoothingTimeConstant = 0.55;
      // Plage resserrée : avec celle par défaut, une chanson masterisée remplit tout.
      analyser.minDecibels = -80;
      analyser.maxDecibels = -18;
      freq = new Uint8Array(analyser.frequencyBinCount);
      const binHz = ac.sampleRate / analyser.fftSize;
      // Bandes espacées en log : autant de place aux graves qu'aux aigus perçus.
      // Les plus graves sont plus étroites qu'une case de la FFT : on y interpole.
      bands = [];
      for (let i = 0; i < COLS; i++) {
        const f0 = F_LO * Math.pow(F_HI / F_LO, i / COLS);
        const f1 = F_LO * Math.pow(F_HI / F_LO, (i + 1) / COLS);
        // Les aigus ont naturellement moins d'énergie : on les remonte un peu, et on
        // soulève la zone des voix (bosse autour de 1,5 kHz, ~1 octave de large) pour
        // qu'elles fassent réagir la grille autant que la basse et la batterie.
        const oct = Math.log2(Math.sqrt(f0 * f1) / 1500);
        const gain = (1 + i * 0.02) * (1 + 0.5 * Math.exp(-oct * oct / 2));
        bands.push([f0 / binHz, f1 / binHz, gain]);
      }
      analyser.connect(ac.destination);
    }
    node.connect(analyser);
  }

  // Énergie moyenne entre deux positions (fractionnaires) du spectre, de 0 à 1.
  function energy(b0, b1) {
    if (b1 - b0 < 1) {
      const c = (b0 + b1) / 2, i = Math.floor(c), f = c - i;
      return (freq[i] * (1 - f) + freq[i + 1] * f) / 255;
    }
    let a = 0, n = 0;
    for (let b = Math.ceil(b0); b < b1; b++) { a += freq[b]; n++; }
    return a / (n * 255);
  }

  function update(t, dt) {
    if (analyser) analyser.getByteFrequencyData(freq);
    const k = Math.min(3, dt * 60); // normalise pour 60 i/s
    for (let i = 0; i < COLS; i++) {
      let a = 0;
      if (freq) {
        const [b0, b1, gain] = bands[i];
        a = Math.min(1, 0.9 * Math.pow(Math.min(1, energy(b0, b1) * gain), 2.4));
      }
      raw[i] = a;
    }
    for (let i = 0; i < COLS; i++) {
      // Léger lissage entre voisines : un contour continu plutôt qu'en dents de scie.
      const a = 0.25 * raw[Math.max(0, i - 1)] + 0.5 * raw[i] + 0.25 * raw[Math.min(COLS - 1, i + 1)];
      // Au repos : une vague lente traverse le centre de la grille.
      const idle = 0.1 + 0.07 * Math.sin(t * 0.8 - i * 0.225);
      const target = Math.max(idle, a);
      vel[i] += (target - pos[i]) * 0.16 * k;
      vel[i] *= Math.pow(0.72, k);
      pos[i] += vel[i] * k;
    }
  }

  function frame(now) {
    raf = requestAnimationFrame(frame);
    if (document.hidden || !w) { last = now; return; }
    const dt = last ? Math.min(0.05, (now - last) / 1000) : 1 / 60;
    last = now;
    update(now / 1000, dt);

    g.clearRect(0, 0, w, h);
    g.globalAlpha = 1;
    g.drawImage(grid, 0, 0);

    for (let r = 0; r < ROWS; r++) {
      g.fillStyle = tint[r];
      // Distance au centre, de 0 (milieu) à 1 (bords) : la colonne s'allume du centre.
      const d = Math.abs(r - mid) / mid;
      for (let c = 0; c < COLS; c++) {
        const level = Math.max(0, Math.min(1, pos[c]));
        const lit = Math.max(0, Math.min(1, (level - d) * 5 + 0.5));
        if (lit < 0.02) continue;
        g.globalAlpha = lit * (0.92 - d * 0.4); // plus doux vers les bords
        g.beginPath();
        g.arc(x0 + c * step, y0 + r * step, dot * (1 + lit * 0.5), 0, Math.PI * 2);
        g.fill();
      }
    }
  }

  // Tourne seulement tant que la pochette est cachée.
  function setActive(on) {
    cancelAnimationFrame(raf);
    last = 0;
    if (on) raf = requestAnimationFrame(frame);
  }

  setActive(true);
  return { connect, setActive };
})();
