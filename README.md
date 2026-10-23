# MusiQuiz QC

Un jeu où il faut reconnaître une chanson québécoise à partir d'un extrait d'une demi-seconde.

**Jouer : https://musiquizqc.com**

Inspiré de [songspot](https://songspot.co), mais uniquement avec de la musique d'ici, en français : des classiques de Beau Dommage, Harmonium et Jean Leloup jusqu'au rap et à l'indie d'aujourd'hui (Les Louanges, Ariane Roy, Thierry Larose, FouKi, Souldia…).

## Comment jouer

1. Appuie sur lecture : tu entends les **0,5 premières secondes** de la chanson.
2. Tape le titre dans le champ de recherche et choisis-le dans les suggestions.
3. Pas sûr ? **Extrait plus long** débloque le prochain extrait : 0,5 s → 2 s → 4 s → 8 s → 16 s.
4. Un mauvais essai débloque aussi l'extrait suivant.
5. Après le dernier extrait, **Je ne sais pas** révèle la réponse.

Le jeu compte tes bonnes réponses d'affilée : ta **série**. Une chanson ratée la remet à zéro ; ton **record** (ta meilleure série) reste gardé dans ton navigateur. Une fois la réponse révélée, la chanson joue pendant 15 secondes et le bouton **Ouvrir dans…** l'ouvre dans ton app de musique, tout comme les cartes de l'historique. Au premier clic, tu choisis l'app (Apple Music, Spotify, Deezer ou YouTube Music) ; le jeu s'en souvient, et la flèche à côté du bouton permet d'en changer. Quand l'artiste a une page Bandcamp, un lien y mène, sous son nom.

Raccourcis : **Entrée** dans un champ vide réécoute l'extrait, **Espace** joue ou met en pause.

## Le catalogue

Environ 1 500 chansons de près de 200 artistes. Elles viennent de deux sources :

- la playlist Apple Music [TOP QUEB](https://music.apple.com/ca/playlist/top-queb/pl.u-11zBvGYC8MG8vqP) de Samuel Belley, dont toutes les chansons sont ajoutées ;
- une sélection faite à la main, choisie pour être :
  - **québécoise** : l'artiste principal doit être d'ici (les collaborations avec des artistes de France sont exclues) ;
  - **en français** : les chansons en anglais ou dans d'autres langues sont retirées ;
  - **variée** : un nombre maximal de chansons par artiste évite que la pop radio prenne toute la place.

Le catalogue couvre toutes les époques ; environ la moitié des chansons datent des années 2020.

## Comment ça marche

C'est un site statique : du HTML, du CSS et du JavaScript, sans serveur ni compte.

- **Extraits** : les aperçus de 30 secondes d'[Apple Music](https://music.apple.com) (AAC, environ 256 kb/s), trouvés par le code ISRC de chaque enregistrement. Pour les quelques chansons qu'Apple n'a pas, le jeu se rabat sur l'aperçu [Deezer](https://www.deezer.com).
- **Découpage précis** : l'aperçu est décodé avec la Web Audio API, ce qui permet de jouer exactement 0,5 s. Le jeu saute aussi le fondu du début des aperçus pour que le premier extrait soit bien audible.
- **Sons du jeu** : les petits sons de bonne et de mauvaise réponse sont synthétisés dans le navigateur ; il n'y a aucun fichier audio.
- **Fluidité** : la chanson suivante se télécharge pendant que tu joues, pour enchaîner sans attente.
- **Pas de répétition** : le jeu retient dans ton navigateur les chansons déjà jouées et n'en repropose aucune avant d'avoir fait le tour du catalogue.

## Code source

```
public/              le jeu (ce qui est publié)
  index.html         la page
  style.css          l'apparence
  app.js             la logique du jeu
  viz.js             le visualiseur affiché à la place de la pochette
  songs.js           le catalogue généré (ne pas éditer à la main)
  bandcamp.js        les pages Bandcamp des artistes, générées
scripts/
  catalog.tsv        la liste des chansons : titre, artiste, année, genre
  artist_limits.tsv  le nombre maximal de chansons par artiste
  blocklist.txt      les titres exclus (anglais, versions live, doublons)
  bandcamp.tsv       la page Bandcamp de chaque artiste (- = aucune page utilisable)
  build_catalog.py   génère songs.js (Apple Music, avec Deezer en secours)
  apple_music.py     jeton et requêtes de l'API Apple Music
  apple_migrate.py   ajoute l'extrait Apple aux chansons qui n'en ont pas (par ISRC)
  playlist_import.py ajoute les chansons de la playlist TOP QUEB qui manquent
  weekly_update.sh   mise à jour hebdomadaire : playlist, catalogue, Bandcamp, publication
  discover.py        liste les chansons populaires d'une liste d'artistes
  expand.py          propose de nouvelles chansons à ajouter au catalogue
  bandcamp.py        trouve les pages Bandcamp (Wikidata, MusicBrainz, vérification de la page)
  build_dist.py      prépare dist/ pour l'hébergement statique
  deploy.sh          publie dist/ sur GitHub Pages (domaine musiquizqc.com)
server.py            serveur local
```

Jouer en local, sur http://localhost:5173 :

```bash
python3 server.py
```

Le serveur local désactive le cache du navigateur : chaque modification est visible au rafraîchissement.

Après une modification de `scripts/catalog.tsv`, régénérer le catalogue :

```bash
python3 scripts/build_catalog.py
```

Publier (nécessite `gh` connecté) : le site est hébergé sur GitHub Pages, à l'adresse musiquizqc.com.

```bash
scripts/deploy.sh
```

Ajouter les nouvelles chansons de la playlist, chercher les pages Bandcamp des nouveaux artistes et publier, en une commande (c'est ce que fait la tâche planifiée chaque semaine) :

```bash
scripts/weekly_update.sh
```

Les scripts Apple Music ont besoin d'une clé MusicKit (`AuthKey_<KEY_ID>.p8`). Elle n'est jamais dans le dépôt : ils la lisent dans `~/.songspotteur/` ou dans la variable d'environnement `APPLE_MUSIC_KEY`.

Les scripts de catalogue gardent des caches des réponses de Deezer (`scripts/.*-cache.json`). Ils ne sont pas versionnés : un clone neuf interroge Deezer de nouveau.

## Crédits

Les extraits audio et les pochettes proviennent d'Apple Music et de Deezer et appartiennent à leurs ayants droit. Merci à Samuel Belley pour la playlist TOP QUEB. Ce projet n'est affilié ni à Apple, ni à Deezer, ni à songspot.
