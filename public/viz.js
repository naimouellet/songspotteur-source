// Visualiseur affiché à la place de la pochette : une matrice de points carrée,
// comme la pochette qu'elle remplace. Chaque colonne est une bande de fréquence
// (graves à gauche, aigus à droite) qui s'allume du centre vers les bords.
// Chaque colonne est un petit ressort amorti : le mouvement reste souple.
window.Viz = (() => {
  const canvas = document.getElementById("viz");
  const g = canvas.getContext("2d");

  const COLS = 16, ROWS = 16;
  const F_LO = 60, F_HI = 9000;   // plage utile, en Hz
  const MARGIN = 0.16;            // marge autour de la grille, en fraction du côté

  const pos = new Float32Array(COLS);
  const vel = new Float32Array(COLS);
  let analyser = null, freq = null, ranges = null;
  let w = 0, h = 0, dpr = 1, raf = 0, last = 0;

  function resize() {
    dpr = Math.min(2, window.devicePixelRatio || 1);
    // Taille de mise en page, pas getBoundingClientRect : la pochette est réduite à 94 %
    // au repos (transform), et le canvas serait alors dessiné trop petit puis étiré.
    w = Math.max(1, Math.round(canvas.clientWidth * dpr));
    h = Math.max(1, Math.round(canvas.clientHeight * dpr));
    canvas.width = w;
    canvas.height = h;
  }
  new ResizeObserver(resize).observe(canvas);

  // Branche une source audio : elle passe par l'analyseur avant les haut-parleurs.
  function connect(ac, node) {
    if (!analyser) {
      analyser = ac.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.6;
      // Plage resserrée : avec celle par défaut, une chanson masterisée remplit tout.
      analyser.minDecibels = -80;
      analyser.maxDecibels = -18;
      freq = new Uint8Array(analyser.frequencyBinCount);
      const binHz = ac.sampleRate / analyser.fftSize;
      // Bandes espacées en log : autant de place aux graves qu'aux aigus perçus.
      ranges = [];
      for (let i = 0; i < COLS; i++) {
        const f0 = F_LO * Math.pow(F_HI / F_LO, i / COLS);
        const f1 = F_LO * Math.pow(F_HI / F_LO, (i + 1) / COLS);
        const b0 = Math.max(1, Math.floor(f0 / binHz));
        ranges.push([b0, Math.max(b0 + 1, Math.ceil(f1 / binHz))]);
      }
      analyser.connect(ac.destination);
    }
    node.connect(analyser);
  }

  function update(t, dt) {
    if (analyser) analyser.getByteFrequencyData(freq);
    const k = Math.min(3, dt * 60); // normalise pour 60 i/s
    for (let i = 0; i < COLS; i++) {
      let a = 0;
      if (freq) {
        const [b0, b1] = ranges[i];
        for (let b = b0; b < b1; b++) a += freq[b];
        a /= (b1 - b0) * 255;
        // Les aigus ont naturellement moins d'énergie : on les remonte un peu.
        a = Math.min(1, 0.9 * Math.pow(a * (1 + i * 0.04), 1.8));
      }
      // Au repos : une vague lente traverse le centre de la grille.
      const idle = 0.1 + 0.07 * Math.sin(t * 0.8 - i * 0.45);
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
    const side = Math.min(w, h) * (1 - MARGIN * 2);
    const x0 = (w - side) / 2, y0 = (h - side) / 2;
    const step = side / (COLS - 1);
    const dot = Math.max(1, step * 0.11);
    const mid = (ROWS - 1) / 2;

    for (let c = 0; c < COLS; c++) {
      const level = Math.max(0, Math.min(1, pos[c]));
      for (let r = 0; r < ROWS; r++) {
        // Distance au centre, de 0 (milieu) à 1 (bords) : la colonne s'allume du centre.
        const d = Math.abs(r - mid) / mid;
        const lit = Math.max(0, Math.min(1, (level - d) * 4 + 0.5));
        g.fillStyle = `rgba(255, 255, 255, ${0.07 + lit * (0.9 - d * 0.45)})`; // plus doux vers les bords
        g.beginPath();
        g.arc(x0 + c * step, y0 + r * step, dot * (1 + lit * 0.45), 0, Math.PI * 2);
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
