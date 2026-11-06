# harvest — SoundCloud → Soulseek → bibliothèque DJ

Outil CLI pour extraire les likes d'un compte SoundCloud, retrouver les morceaux sur
Soulseek (via [slskd](https://github.com/slskd/slskd)) en FLAC (fallback MP3 ≥ 320),
puis les taguer et les ranger dans un dossier unique pour Rekordbox.

## Prérequis (déjà installés sur cette machine)

- Docker + daemon (`./start.sh` le démarre si besoin)
- Python 3.12 via `uv` (`.venv/` à la racine)
- `ffmpeg` / `ffprobe`

## Mise en route

```bash
./start.sh                 # daemon Docker + slskd (http://localhost:5030)
```

La config slskd est dans `data/slskd/app/slskd.yml` :
- identifiants Soulseek : `otherchoice_dj` (le compte est créé automatiquement à la
  première connexion ; si le pseudo est déjà pris, change-le dans le fichier ou l'UI)
- clé API pour ce script déjà générée (aussi dans `config.yaml`)

Interface web slskd : `http://localhost:5030` (utilisateur `harvest`).

## Commandes

```bash
.venv/bin/python -m harvest fetch          # liste les likes SoundCloud (--limit pour tester)
.venv/bin/python -m harvest search         # cherche chaque morceau sur Soulseek
.venv/bin/python -m harvest download       # télécharge les meilleurs candidats
.venv/bin/python -m harvest organize       # tags + rangement dans la bibliothèque
.venv/bin/python -m harvest status         # état d'avancement
.venv/bin/python -m harvest retry          # remet les échecs en file
.venv/bin/python -m harvest run            # tout enchaîner
```

## Fonctionnement

1. **fetch** : yt-dlp liste `soundcloud.com/other_choice/likes`, puis enrichit chaque
   morceau (uploader, durée, genre, tags, artwork), avec cache dans `data/cache/`.
2. **search** : requêtes `artiste titre` sur Soulseek, scoring des fichiers
   (FLAC > WAV > MP3 320, correspondance du nom, écart de durée, file d'attente).
3. **download** : enqueue des meilleurs candidats chez slskd, suivi des transferts,
   bascule sur le candidat suivant en cas d'échec, fichiers déplacés dans `data/staging/`.
4. **organize** : vérification ffprobe, tags + cover, rangement à plat dans
   `/mnt/e/Music/dj/Artiste - Titre [QUALITÉ].ext`, doublons mis de côté.

## Rappels

- Le partage Soulseek est actif (`/mnt/e/Music/dj` monté en `/music`), nécessaire pour
  éviter les restrictions du réseau.
- Après un redémarrage de WSL : relancer `./start.sh`.
- Les téléchargements restent dans `data/slskd/downloads` jusqu'à leur traitement.
