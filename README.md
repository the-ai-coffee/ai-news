# Le Relevé

Site d'actualité statique et privé : **10 sujets maximum, résumés de façon factuelle à partir de plusieurs sources indépendantes**. Sans publicité, sans traceur, sans JavaScript côté lecteur. Deux éditions par jour.

## Fonctionnement

```
GitHub Actions (cron 05:00 et 17:00 UTC)
  └─ ai-news run
       1. collect   Firecrawl : recherche web + texte, pour chaque thème × région
       2. assess    DeepSeek : fiabilité 0–1 et justification ; opinion et score faible écartés
       3. cluster   DeepSeek : regroupement par événement, score d'impact, détection des redites
       4. independence  reprises de dépêche, même domaine, textes quasi identiques = 1 source
       5. rank      0,6 × couverture + 0,4 × impact (× pénalité si redite) ; ≥ 2 sources
       6. summarize DeepSeek : titre, essentiel, faits, contexte, divergences (JSON strict)
                    + contrôles mécaniques : chiffres présents dans les sources,
                      ≤ 3 min de lecture, pas de termes sensationnalistes
       7. render    Jinja → HTML statique (une, pages sujet, audit, archives)
  └─ commit data/editions/<id>.json   (trace d'audit versionnée)
  └─ vercel deploy site/ --prod       (accès protégé par mot de passe)
```

Une édition dégradée vaut mieux qu'aucune, mais jamais une édition fausse :

| Panne | Comportement |
|---|---|
| API indisponible | Retry avec backoff exponentiel (3 essais), puis incident journalisé |
| Une requête de recherche échoue | Le run continue, l'incident apparaît dans l'audit |
| Sortie LLM hors schéma ou non conforme | 1 nouvel essai avec les erreurs signalées, puis sujet rejeté |
| Chiffre absent des sources | Phrase retirée ; sujet rejeté si le texte devient incohérent |
| Moins de `min_stories` sujets | Rien n'est publié, le workflow échoue → e-mail de GitHub |
| Plafond de coût atteint | Arrêt propre de l'étape en cours |

## Mise en service

1. **Clés API** : créer une clé [DeepSeek](https://platform.deepseek.com) et une clé [Firecrawl](https://firecrawl.dev).
2. **Projet Vercel** : créer un projet vide (aucun dépôt Git connecté n'est nécessaire), puis :
   - variables d'environnement du projet : `SITE_PASSWORD` (obligatoire) et `SITE_USER` (facultatif, défaut `lecteur`) ;
   - un jeton dans *Account Settings → Tokens* ;
   - `VERCEL_ORG_ID` et `VERCEL_PROJECT_ID` dans *Project Settings → General*.
3. **Secrets GitHub** (*Settings → Secrets and variables → Actions*) :
   `DEEPSEEK_API_KEY`, `FIRECRAWL_API_KEY`, `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`.
4. **Premier run** : *Actions → Édition → Run workflow*.

Les alertes d'échec sont les e-mails standard de GitHub Actions, envoyés à la personne qui a modifié le cron en dernier.

## Configuration

Tout se règle dans [`config.toml`](config.toml) : thèmes et requêtes, régions, nombre de sujets, seuils de fiabilité et de sources, poids du classement, plafonds de coût, modèle LLM. La configuration est validée au démarrage.

Pour changer de fournisseur LLM, il suffit d'implémenter le protocole `LLMClient` (`src/ai_news/llm.py`). Tout fournisseur compatible OpenAI ne demande qu'un changement de `base_url` et `model`.

## Développement

```bash
uv sync
uv run pytest                       # tests (API simulées)
uv run ruff check . && uv run mypy  # qualité
export DEEPSEEK_API_KEY=… FIRECRAWL_API_KEY=…
uv run ai-news run --dry-run        # pipeline réel, rien n'est enregistré
uv run ai-news render               # site depuis data/editions/
python -m http.server -d site       # aperçu local
```

Spécification : [`docs/specs/2026-11-13-news-digest-design.md`](docs/specs/2026-11-13-news-digest-design.md).

## Limites connues

- Le contrôle des chiffres porte sur les nombres de deux chiffres ou plus ; les nombres écrits en lettres ne sont pas vérifiés.
- Les textes complets des articles ne sont jamais stockés : l'audit conserve URL, média, score et justification.
- DeepSeek est hébergé en Chine. Seuls des articles publics lui sont envoyés.
