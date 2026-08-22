# 🐍 Hydra Cloud Shield

Ruche de détection de menaces distribuée, portée sur Google Cloud pour le
hackathon **All Things Agentic** (track **Taskmaster**).

5 agents spécialisés (Scout / Tank / Ghost / Oracle / Druid) surveillent
en autonomie les **Cloud Audit Logs** réels du projet GCP, se coordonnent
via **Pub/Sub**, partagent une mémoire persistante via **Firestore**, et
l'Oracle — piloté par **Gemini** — tranche un verdict de consensus avant
de proposer une action de remédiation réelle (révocation IAM / désactivation
de clé de service account). **L'humain confirme toujours avant exécution.**

> Version cloud de Hydra-Smart-Shield (prototype local sur process
> Windows). Voir la section [Différences vs la version locale](#différences-vs-la-version-locale)
> pour le détail du portage.

---

## Sommaire

- [Architecture des fichiers](#architecture-des-fichiers)
- [Comment ça marche](#comment-ça-marche)
- [Les 5 rôles](#les-5-rôles-en-détail)
- [Setup — de zéro à un projet GCP fonctionnel](#setup--de-zéro-à-un-projet-gcp-fonctionnel)
- [Configuration (variables d'environnement)](#configuration-variables-denvironnement)
- [Lancer le système en local](#lancer-le-système-en-local)
- [Tester chaque brique isolément](#tester-chaque-brique-isolément)
- [Déploiement sur Cloud Run](#déploiement-sur-cloud-run)
- [Différences vs la version locale](#différences-vs-la-version-locale)
- [État d'avancement](#état-davancement)
- [Dépannage](#dépannage)
- [Philosophie de sécurité](#philosophie-de-sécurité)

---

## Architecture des fichiers

```
hydra-cloud/
├── main.py                   # entrypoint unique — lit BOX_ROLE et lance le bon comportement
├── requirements.txt
├── Dockerfile
├── deploy.sh                  # déploiement Cloud Run (5 revisions, une par rôle)
├── .env.example
├── devpost_story_draft.md     # brouillon pour la page Devpost (section "Project Story")
│
├── config/
│   └── settings.py            # constantes : projet GCP, topics, seuils, modèle Gemini
│
├── boxes/                     # logique métier — un fichier = un rôle
│   ├── base_box.py            # classe abstraite commune (contrat _build_features/_score)
│   ├── scout.py                # BOX0 — détection rapide sur les logs bruts
│   ├── tank.py                  # BOX1 — confirmation via historique Firestore
│   ├── ghost.py                   # BOX2 — patterns temporels (horaires, rafales)
│   ├── oracle.py                   # BOX3 — consensus + appel Gemini
│   └── druid.py                     # BOX4 — santé de la ruche (heartbeats)
│
├── core/                      # infrastructure partagée, découplée de la logique de rôle
│   ├── audit_log_reader.py    # pull les Cloud Audit Logs (remplace psutil)
│   ├── pubsub_ring.py          # publish/subscribe signé HMAC (remplace le ring UDP)
│   ├── memory_store.py          # Firestore transactionnel (remplace memory.json)
│   ├── gemini_client.py          # wrapper google-genai, utilisé uniquement par Oracle
│   └── remediation.py             # construction de proposition + actions IAM (humain requis)
│
└── tests/
    └── test_pulse.py           # injection d'un événement de test dans le ring
```

---

## Comment ça marche

```
Cloud Audit Logs (réel, généré par l'activité normale du projet GCP)
        │
        ▼
   [SCOUT] ── scanne toutes les 30s, seuils bas, priorité au rappel
        │
        │  publie sur le topic Pub/Sub "hydra-ring" (signé HMAC)
        ▼
   [TANK] ── écoute le ring, confirme/infirme via l'historique Firestore
        │
        ▼
   [GHOST] ── scanne aussi les logs, détecte patterns temporels (indépendant)
        │
        └──────────────┬──────────────┘
                        ▼
                  [ORACLE] ── accumule les signaux 15s, appelle Gemini,
                              tranche un verdict JSON structuré
                        │
                        ▼
              Verdict critique ? ──oui──▶ propose une remédiation
                        │                  (JAMAIS exécutée automatiquement)
                        │
                        ▼
              Écrit le verdict dans Firestore (hydra_memory)
                        │
                        ▼
        Prochaine rencontre avec cette identité → décision immédiate,
        pas de recalcul (verdict "safe"/"sandbox" mémorisé)

   [DRUID] ── en parallèle, écoute le ring pour détecter les heartbeats
              implicites, alerte si une box est silencieuse >90s
```

Chaque publication d'une box sur le ring vaut heartbeat — pas besoin
d'un message dédié, Druid observe simplement l'activité normale.

---

## Les 5 rôles en détail

| Box | Fichier | Source de données | Ce qu'il fait |
|-----|---------|--------------------|-----------------|
| **Scout** | `boxes/scout.py` | Cloud Audit Logs (poll direct) | Première alerte, seuils bas (≥20/100), détecte méthodes IAM à risque et sévérités surveillées |
| **Tank** | `boxes/tank.py` | Ring (écoute Scout uniquement) | Confirme/infirme via l'historique Firestore de l'identité, court-circuite si verdict déjà connu |
| **Ghost** | `boxes/ghost.py` | Cloud Audit Logs (poll direct) | Patterns temporels : heures creuses (1h-5h UTC), rafales d'activité, identités jamais vues |
| **Oracle** | `boxes/oracle.py` | Ring (tous les signaux) | Agrège sur une fenêtre de 15s, appelle Gemini pour le verdict final, propose une remédiation si critique |
| **Druid** | `boxes/druid.py` | Ring (heartbeats implicites) | Surveille la santé de la ruche elle-même, alerte si une box devient silencieuse |

---

## Setup — de zéro à un projet GCP fonctionnel

### 1. Créer le projet GCP (si pas déjà fait)

```bash
# Dans la Console (console.cloud.google.com) ou via gcloud CLI :
gcloud projects create TON_PROJECT_ID
gcloud config set project TON_PROJECT_ID
```

### 2. Activer les APIs nécessaires

```bash
gcloud services enable \
  logging.googleapis.com \
  pubsub.googleapis.com \
  firestore.googleapis.com \
  aiplatform.googleapis.com \
  run.googleapis.com
```

### 3. Créer la base Firestore (mode natif, une seule fois par projet)

```bash
gcloud firestore databases create --location=eur3
```

### 4. S'authentifier en local

```bash
gcloud auth login
gcloud auth application-default login
```

### 5. Installer les dépendances Python

```bash
pip install -r requirements.txt --break-system-packages
```

### 6. Récupérer une clé API Gemini (si tu n'utilises pas Vertex AI directement)

Va sur [aistudio.google.com/apikey](https://aistudio.google.com/apikey),
génère une clé, mets-la dans `GEMINI_API_KEY` (voir section config).

---

## Configuration (variables d'environnement)

Copie `.env.example` en `.env` et remplis :

| Variable | Obligatoire | Description |
|----------|:---:|--------------|
| `GCP_PROJECT_ID` | ✅ | L'ID de ton projet GCP |
| `HYDRA_RING_HMAC_KEY` | ✅ | Clé secrète partagée pour signer les paquets ring — génère avec `openssl rand -hex 32` |
| `BOX_ROLE` | ✅ | `scout` / `tank` / `ghost` / `oracle` / `druid` |
| `GEMINI_API_KEY` | selon SDK | Clé API Gemini (si pas d'auth via Vertex AI/ADC) |
| `GEMINI_MODEL` | non | Défaut dans `config/settings.py` |

**Sans `GCP_PROJECT_ID` ou `HYDRA_RING_HMAC_KEY`, `main.py` refuse de démarrer**
et affiche clairement ce qui manque — c'est volontaire (voir `_check_env()`
dans `main.py`), pour éviter un crash silencieux une fois déployé.

---

## Lancer le système en local

Chaque box tourne dans son propre process. Ouvre 5 terminaux (ou utilise
`tmux`/`screen`), et dans chacun :

```bash
export GCP_PROJECT_ID=ton-project-id
export HYDRA_RING_HMAC_KEY=ta-clé-générée

# Terminal 1
BOX_ROLE=scout python main.py

# Terminal 2
BOX_ROLE=tank python main.py

# Terminal 3
BOX_ROLE=ghost python main.py

# Terminal 4
BOX_ROLE=oracle python main.py

# Terminal 5
BOX_ROLE=druid python main.py
```

Si tout est bien configuré, tu dois voir :
- Scout et Ghost scanner les logs toutes les 30s (`SCAN_INTERVAL_SECONDS`)
- Dès qu'un événement dépasse le seuil (≥20/100), Scout/Ghost publient sur le ring
- Tank réagit aux publications de Scout
- Oracle accumule pendant 15s puis appelle Gemini et affiche le verdict
- Druid affiche "Santé de la ruche : nominale" toutes les 30s

**Pour générer de l'activité de test rapidement** sans attendre un vrai
événement IAM : fais un changement IAM mineur sur ton projet (ex: ajoute
puis retire un rôle sur un compte de test) — ça génère un vrai Cloud Audit
Log immédiatement.

---

## Tester chaque brique isolément

### `audit_log_reader.py` — vérifier qu'on lit bien les logs

```bash
python -m core.audit_log_reader
```
Doit afficher les événements des 60 dernières minutes (fenêtre élargie
pour le test). Si rien ne s'affiche, c'est probablement normal si le
projet est peu actif — génère un événement (crée/supprime une ressource,
change un rôle IAM) et relance.

### `pubsub_ring.py` — vérifier que publish/listen fonctionnent

```bash
python3 -c "
from core.pubsub_ring import RingClient
r = RingClient('test')
r.publish({'proc_or_event_id': 'test-1', 'identity': 'test@example.com', 'score': 42})
print('publié avec succès')
"
```

### `memory_store.py` — vérifier Firestore

```bash
python3 -c "
from core.memory_store import MemoryStore
m = MemoryStore()
m.record_encounter('test@example.com', 42, 'test_box')
print(m.get('test@example.com'))
"
```

### `gemini_client.py` — vérifier l'appel Gemini isolément

```bash
python3 -c "
from core.gemini_client import get_consensus_verdict
verdict = get_consensus_verdict(
    {'identity': 'test@example.com'},
    [{'source_role': 'scout', 'score': 60, 'confidence': 0.6, 'raisons': ['test']}],
    None
)
print(verdict)
"
```

### Injection de test complète (`tests/test_pulse.py`)

Une fois `pubsub_ring.py` branché dedans (actuellement en `TODO` dans le
fichier), ça permet de simuler une alerte Scout sans attendre un vrai
événement IAM — utile pour tester Tank/Oracle/Druid indépendamment de
la disponibilité de vrais logs suspects.

---

## Déploiement sur Cloud Run

1. Remplis `PROJECT_ID` dans `deploy.sh`
2. Assure-toi que `HYDRA_RING_HMAC_KEY` et `GEMINI_API_KEY` sont dans
   Secret Manager plutôt qu'en clair dans le script (à faire avant la
   démo finale — voir section État d'avancement)
3. Lance :
   ```bash
   chmod +x deploy.sh
   ./deploy.sh
   ```
   Ça build l'image une fois et déploie 5 revisions Cloud Run (une par
   rôle), chacune avec `min-instances=1 max-instances=1` pour garantir
   qu'il y a toujours exactement une instance de chaque rôle qui tourne
   (pas de scaling horizontal ici — chaque rôle est un singleton logique).

---

## Différences vs la version locale

| Avant (Hydra-Smart-Shield, local) | Maintenant (Hydra Cloud Shield) |
|-------------------------------------|------------------------------------|
| `psutil` (scan de process Windows) | Cloud Audit Logs (API Cloud Logging) |
| Ring UDP (sockets locaux, ports 9990-9994) | Pub/Sub (topic `hydra-ring`) |
| `memory.json` (fichier + symlink + `threading.Lock`) | Firestore (collection `hydra_memory`, transactions natives) |
| Scoring heuristique maison uniquement | Scoring heuristique **+** verdict Gemini (Oracle) |
| Quarantaine = suspendre un PID + copier l'exe | Remédiation = révoquer un rôle IAM / désactiver une clé de SA |
| 5 process Python séparés (`BOX0.py`...`BOX4.py`) | 1 service Cloud Run, rôle choisi via `BOX_ROLE` |
| GUI Tkinter locale | (pas encore de GUI cloud — décision humaine via CLI pour l'instant) |

---

## État d'avancement

### ✅ Fait
- Les 5 boxes (Scout, Tank, Ghost, Oracle, Druid) — logique complète, testées **end-to-end en conditions réelles**
- `core/audit_log_reader.py`, `pubsub_ring.py`, `memory_store.py`, `gemini_client.py` — tous validés individuellement puis en intégration
- `core/remediation.py` — `propose()` fonctionnel (construction de proposition, zéro action IAM)
- `main.py` — dispatch réel vers chaque box selon `BOX_ROLE`
- **Projet GCP `hydra-cloud-shield` créé**, APIs activées (Logging, Pub/Sub, Firestore, Vertex AI)
- Firestore (région `eur3`) créée et fonctionnelle
- **Les 5 boxes tournent en parallèle pour de vrai**, communiquent via Pub/Sub, Oracle rend des verdicts cohérents via Gemini 3.6
- Fix heartbeat : chaque box (Scout, Tank, Ghost, Oracle) publie désormais un signal de vie périodique (`RingClient.start_heartbeat`), indépendant de ses alertes — Druid distingue maintenant correctement "silencieuse" de "rien à signaler ce cycle"

### ⏳ À faire avant soumission
- [ ] Point d'entrée humain pour valider/déclencher `execute_disable_service_account_key`
      et `execute_revoke_iam_role` (CLI avec confirmation `[y/N]`)
- [ ] Cloud Run — en attente de l'activation du billing (crédits hackathon, arrivée prévue lundi)
- [ ] Remplir `PROJECT_ID` dans `deploy.sh` et faire un vrai déploiement Cloud Run
- [ ] Passer `HYDRA_RING_HMAC_KEY` et `GEMINI_API_KEY` par Secret Manager plutôt qu'en env var en clair
- [ ] Diagramme d'architecture (schéma visuel pour la soumission Devpost)
- [ ] Vidéo démo ~4min (montrer Cloud Console, logs, verdict Gemini en action)
- [ ] Repo GitHub public (ou partagé à testing@devpost.com et cloudhackathons@google.com)
- [ ] Compléter `devpost_story_draft.md` avec les sections "How we built it" / "Challenges" / "What we learned"

---

## Dépannage

**`RuntimeError: GCP_PROJECT_ID non configuré`**
→ Variable d'env manquante. `export GCP_PROJECT_ID=ton-project-id` avant de lancer.

**`RuntimeError: HYDRA_RING_HMAC_KEY non configurée`**
→ Génère une clé : `export HYDRA_RING_HMAC_KEY=$(openssl rand -hex 32)`.
Doit être **la même clé sur toutes les boxes**, sinon elles rejettent
mutuellement leurs paquets (signature invalide).

**Aucun événement détecté par Scout/Ghost**
→ Normal si le projet est peu actif. Génère un événement IAM (ajoute/retire
un rôle sur un compte de test) et relance `python -m core.audit_log_reader`
pour vérifier que ça remonte.

**`[RING] ⚠️ Paquet rejeté — signature invalide`**
→ Vérifie que `HYDRA_RING_HMAC_KEY` est identique sur toutes les boxes en cours d'exécution.

**`[GEMINI_CLIENT] ⚠️ Appel Gemini échoué : 'ascii' codec can't encode character...`**
→ Problème de locale système (fréquent sur WSL/Debian fraîchement installé,
qui démarre parfois en ASCII plutôt qu'UTF-8). Corrige avec :
```bash
export LANG=C.UTF-8
export LC_ALL=C.UTF-8
export PYTHONUTF8=1
```
Pour rendre ça permanent : ajoute ces 3 lignes à `~/.bashrc`.

**Erreur de permission Firestore/Pub/Sub/Logging**
→ Vérifie que `gcloud auth application-default login` a bien été fait,
et que les APIs sont activées (`gcloud services list --enabled`).

**Gemini répond quelque chose d'imparfait**
→ `gemini_client.py` a un fallback automatique (`_parse_verdict`) qui
retourne un verdict "suspect/monitor" si le JSON est malformé — ça ne
devrait jamais planter la box, juste afficher un warning en console.

---

## Philosophie de sécurité

**REPAIR only, jamais d'action offensive.** Hérité directement de la
version locale (`sandbox_engine.py` disait déjà "l'humain décide
toujours") :

- `remediation.propose()` ne modifie **rien** côté IAM — il construit
  juste un dict décrivant l'action recommandée.
- `execute_disable_service_account_key()` et `execute_revoke_iam_role()`
  ne doivent **jamais** être appelées automatiquement par Oracle ou
  n'importe quelle box — uniquement depuis un point d'entrée déclenché
  par une confirmation humaine explicite.
- Les paquets ring sont signés HMAC-SHA256 pour empêcher l'injection de
  faux scores par un tiers.
- Toute erreur d'appel externe (API Cloud Logging, Pub/Sub, Firestore,
  Gemini) est catchée et loguée plutôt que de faire planter une box —
  le système est pensé pour tourner en autonome sans supervision constante.