# Bot de veille logements CROUS

Surveille une recherche de logements sur [trouverunlogement.lescrous.fr](https://trouverunlogement.lescrous.fr)
et envoie une notification Discord dès qu'une nouvelle annonce apparaît.

## Comment ça marche

1. `main.py` charge la page de résultats de recherche (`SEARCH_URL`).
2. Il parse les cartes de logement (`div.fr-card`) avec BeautifulSoup pour en extraire
   adresse, loyer, surface, type et lien vers l'annonce.
3. Il compare les ID trouvés à ceux déjà connus dans `seen_listings.json`.
4. Chaque nouvelle annonce est envoyée sur un webhook Discord.
5. `seen_listings.json` est mis à jour puis re-commité par le workflow GitHub Actions.

## 1. Récupérer l'URL de recherche filtrée

1. Va sur https://trouverunlogement.lescrous.fr/ et lance une recherche (ville, prix max,
   surface min, type de cohabitation, etc.).
2. Une fois les filtres appliqués et les résultats affichés, copie l'URL complète dans la
   barre d'adresse de ton navigateur. Elle ressemble à :
   ```
   https://trouverunlogement.lescrous.fr/tools/47/search?bounds=...&locationName=Caen+%2814000%29
   ```
3. Colle cette URL :
   - soit directement dans `main.py`, en remplaçant la valeur de `DEFAULT_SEARCH_URL` ;
   - soit dans une variable de repository GitHub `CROUS_SEARCH_URL` (Settings → Secrets and
     variables → Actions → onglet **Variables**), ce qui évite de modifier le code.

Le `47` dans l'URL correspond à l'année universitaire ciblée (visible aussi dans le menu
« Je recherche un logement » du site) ; utilise l'ID correspondant à la période qui t'intéresse.

## 2. Créer un webhook Discord

1. Dans Discord, va dans les paramètres du salon où tu veux recevoir les alertes →
   **Intégrations** → **Webhooks** → **Nouveau webhook**.
2. Donne-lui un nom, choisis le salon, puis clique sur **Copier l'URL du webhook**.
3. Garde cette URL secrète : elle permet d'envoyer des messages dans ton salon.

## 3. Configurer le secret GitHub `DISCORD_WEBHOOK_URL`

Dans le repository GitHub :

1. **Settings** → **Secrets and variables** → **Actions** → onglet **Secrets** → **New
   repository secret**.
2. Nom : `DISCORD_WEBHOOK_URL`
3. Valeur : l'URL copiée à l'étape précédente.

Le workflow `.github/workflows/watch.yml` lit ce secret et le passe au script en variable
d'environnement.

## 4. Ajuster la fréquence de vérification

La fréquence est définie par l'expression cron dans `.github/workflows/watch.yml` :

```yaml
on:
  schedule:
    - cron: "*/5 * * * *"
```

Modifie cette ligne pour changer l'intervalle (ex. `*/15 * * * *` pour 15 minutes,
`0 * * * *` pour toutes les heures). GitHub Actions n'exécute pas les cron plus vite que
toutes les 5 minutes. Le tableau de bord Actions du repo affichera aussi un
bouton **Run workflow** pour le déclencher manuellement (`workflow_dispatch`).

À noter : GitHub peut retarder ou espacer les cron jobs en période de forte charge, et
désactive automatiquement les workflows planifiés après 60 jours sans activité sur le repo
(un `workflow_dispatch` manuel ou un commit suffit à les réactiver).

## Exécution locale

```bash
pip install -r requirements.txt
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
python main.py
```

## Fichiers

- `main.py` — script de veille
- `requirements.txt` — dépendances (`requests`, `beautifulsoup4`)
- `.github/workflows/watch.yml` — planification GitHub Actions + commit automatique de l'état
- `seen_listings.json` — état persistant des annonces déjà notifiées
