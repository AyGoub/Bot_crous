# Bot de veille — studios à Paris + petite couronne

Surveille les nouvelles annonces de **studios et T1** (logement individuel, pas de colocation)
à **Paris (75), Hauts-de-Seine (92), Seine-Saint-Denis (93) et Val-de-Marne (94)**, jusqu'à
**800 € charges comprises**, et envoie une notification Discord dès qu'une annonce apparaît.

## Sources

| Source | Ce qu'elle couvre |
|---|---|
| [CROUS](https://trouverunlogement.lescrous.fr) | Résidences étudiantes CROUS (mode « Individuel » uniquement) |
| [Bien'ici](https://www.bienici.com) | Annonces de la plupart des agences et réseaux (Century 21, Laforêt, Guy Hoquet, IAD…) |
| [ARPEJ](https://www.arpej.fr/fr/nos-residences/) | Résidences étudiantes et jeunes actifs : notification quand une résidence passe de « complet » à « N disponible(s) » |

Non couverts : Leboncoin, SeLoger, PAP, Studapart, ImmoJeune (protection anti-robots ou annonces
chargées en JavaScript), ALJT (le site liste ses résidences mais n'affiche aucune disponibilité :
on candidate depuis l'espace candidat) et CLJT (site injoignable lors des tests). Pour ceux-là, active directement leurs alertes, ou utilise une appli
qui les regroupe comme Jinka.

## Ce que fait le bot

1. Il récupère toutes les annonces de chaque source (toutes les pages).
2. Il applique les filtres communs :
   - loyer ≤ `MAX_RENT` (800 €) charges comprises ;
   - surface ≥ `MIN_SURFACE` (9 m², le minimum légal d'un logement décent) ;
   - code postal dans `DEPARTMENTS` (75, 92, 93, 94) ;
   - exclusion des colocations, colivings et chambres chez l'habitant (les chambres de bonne
     sont gardées).
3. Il compare avec `seen_listings.json` et notifie seulement les nouvelles annonces, les moins
   chères d'abord :
   - 🔥 **vert** : loyer ≤ `TARGET_RENT` (700 €) ;
   - **bleu** : entre 700 et 800 € ;
   - **orange** avec ⚠️ : indices d'arnaque (e-mail dans le titre, « Western Union », prix au m²
     anormalement bas…) ou bail code civil.
4. À la première vérification d'une source, il envoie **un seul message récapitulatif** (les
   15 moins chères) au lieu de centaines de notifications.
5. Une annonce retirée puis remise en ligne est notifiée à nouveau.
6. Si un site est indisponible ou limite le trafic, le bot passe son tour sans perdre l'état.

## Configuration

### Secret obligatoire : `DISCORD_WEBHOOK_URL`

1. Dans Discord : paramètres du salon → **Intégrations** → **Webhooks** → **Nouveau webhook** →
   **Copier l'URL du webhook**.
2. Dans GitHub : **Settings** → **Secrets and variables** → **Actions** → onglet **Secrets** →
   **New repository secret**, nom `DISCORD_WEBHOOK_URL`.

### Variables facultatives (onglet **Variables**)

| Variable | Défaut | Rôle |
|---|---|---|
| `MAX_RENT` | `800` | Loyer maximum charges comprises |
| `TARGET_RENT` | `700` | En dessous, l'annonce est marquée 🔥 |
| `MIN_SURFACE` | `9` | Surface minimale en m² |
| `DEPARTMENTS` | `75,92,93,94` | Départements acceptés (préfixes de code postal) |
| `CROUS_SEARCH_URL` | Paris + petite couronne, année 2026-2027 | URL de recherche CROUS |

⚠️ Si tu avais défini `CROUS_SEARCH_URL` pour Caen, **supprime-la** : elle remplacerait la
recherche Paris. L'ID dans l'URL CROUS (`/tools/48/`) correspond à l'année universitaire et
change chaque année (l'ancien `47` renvoie maintenant une erreur 404).

## Fréquence

Le workflow `.github/workflows/watch.yml` tourne **toutes les 15 minutes** (`*/15 * * * *`).
Le repo est public, donc les minutes GitHub Actions sont gratuites. GitHub peut retarder les
cron en période de forte charge, et désactive les workflows planifiés après 60 jours sans
activité sur le repo. Dans ce cas, réactive-le depuis l'onglet **Actions**.

## Exécution locale

```bash
pip install -r requirements.txt
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
python main.py
```

## Fichiers

- `main.py` : filtres, détection d'arnaques, notifications Discord, état.
- `sources/crous.py`, `sources/bienici.py`, `sources/arpej.py` : un module par site. Pour ajouter un site, il suffit
  de créer un module avec une fonction `fetch()` qui renvoie des annonces au même format (voir
  `sources/__init__.py`), puis de l'ajouter à `SOURCES` dans `main.py`.
- `seen_listings.json` : annonces déjà notifiées (mis à jour par le workflow).
