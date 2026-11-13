# Le Relevé : spécification V1

Date : 2026-11-13 · Statut : implémentée

## Objectif

Un site d'actualité privé (usage personnel et proches) qui publie deux fois par jour au plus 10 sujets importants, résumés de façon factuelle à partir de plusieurs sources indépendantes. Sans publicité, sans recherche de clic, sans traceur.

## Décisions

| Sujet | Décision |
|---|---|
| Public | Privé ; thèmes et régions fixés au build dans `config.toml` |
| Collecte | Recherche web ouverte via Firecrawl (`/v2/search` + extraction Markdown) |
| Fiabilité | Notée par le LLM (0–1 + justification), seuil configurable ; opinion écartée |
| Objectivité | ≥ 2 sources indépendantes ; divergences signalées, jamais tranchées |
| Langue | Résumés en français, sources toutes langues |
| LLM | DeepSeek (`deepseek-chat`, API compatible OpenAI) derrière un protocole `LLMClient` |
| Exécution | GitHub Actions (cron), pipeline Python (uv) |
| Hébergement | Vercel, site statique, accès par HTTP Basic (Routing Middleware) |
| Limite | 10 sujets au total, toutes catégories confondues |
| Hors V1 | Mini-analyse (mise de côté) |

## Pipeline

1. **collect** : une requête par (requête du thème + termes de la région). Doublons d'URL ignorés. Une requête en échec devient un incident, le run continue.
2. **assess** : lots de 10 articles. Le LLM renvoie la fiabilité, la justification, le média, la langue, le pays, l'agence de presse éventuelle et l'indicateur d'opinion. Les articles non évalués sont écartés.
3. **cluster** : un appel LLM groupe les articles retenus par événement. Il donne un impact (0–1 + justification) et signale les redites de l'édition précédente sans fait nouveau. Les identifiants inconnus ou en double sont filtrés.
4. **independence** : une union-find par événement rassemble le même domaine, la même agence de presse (déclarée ou détectée dans la signature) et les textes quasi identiques (Jaccard sur des 5-grammes ≥ 0,5). Chaque groupe compte pour une seule source. Le plus fiable est retenu, les autres sont « fusionnés ».
5. **rank** : `score = (0,6 × couverture/couverture_max + 0,4 × impact) / (somme des poids)`, multiplié par `repeat_penalty` en cas de redite. Les événements sous `min_sources` sont coupés.
6. **summarize** : les événements sont traités dans l'ordre jusqu'à 10 sujets valides, un rejet passant la main au suivant. Le LLM produit un JSON strict (titre, essentiel, faits, contexte, divergences avec identifiants de sources). Les contrôles :
   - schéma, longueur (≤ `max_read_minutes × words_per_minute` mots), titre ≤ 12 mots, termes sensationnalistes → un nouvel essai avec les erreurs, puis rejet ;
   - chaque nombre de 2 chiffres ou plus doit figurer dans les sources (séparateurs normalisés). Sinon la phrase est retirée ; un nombre non sourcé dans le titre, ou un essentiel de moins de 2 phrases, entraîne le rejet.
7. **render** : Jinja (autoescape, `StrictUndefined`) → `site/`. On y trouve la une, une page par sujet, l'audit, les archives, une CSS sans police externe et le mode sombre automatique.

## Données

`data/editions/<AAAA-MM-JJ>-<am|pm>.json` : l'édition complète. Elle comprend les sujets, les sujets coupés (rang, score, motif), l'audit de chaque source (score, statut, justification), les incidents et les statistiques de coût. Les textes intégraux des articles ne sont jamais persistés.

## Gestion des erreurs

- Retry avec backoff exponentiel : Firecrawl (3 essais, codes 408/429/5xx) et SDK OpenAI (`max_retries=3`).
- Plafonds par run : `max_llm_calls` et `max_search_requests`. Le dépassement arrête l'étape en cours ; les sujets restants sont coupés avec le motif « Budget épuisé ».
- Moins de `min_stories` sujets, ou regroupement impossible : code de sortie 3, rien n'est versionné ni déployé, l'édition précédente reste en ligne et GitHub envoie un e-mail d'échec.
- Configuration invalide ou secret manquant : code de sortie 2.
- Middleware : sans `SITE_PASSWORD`, réponse 503 (fermé par défaut). Comparaison des identifiants en temps constant.

## Déploiement

- `edition.yml` : un cron à 05:00 et 17:00 UTC exécute `ai-news run`, versionne le JSON sur `main` puis lance `vercel deploy site --prod`. Un push de code sur `main` ne fait que `ai-news render`, suivi du déploiement.
- `deploy/` (middleware, `vercel.json` avec en-têtes de sécurité et CSP stricte, `package.json`) est copié dans `site/`.
- Le `vercel.json` racine désactive les déploiements Git : seul le workflow déploie.

## Tests

pytest avec API simulées (`httpx.MockTransport`, `FakeLLM`). Ils couvrent la configuration, les contrôles mécaniques, l'indépendance, le classement, le client Firecrawl (formes de réponse, retry, budget), chaque étape LLM et un test de bout en bout jusqu'au HTML (échappement, archives, budget épuisé, sujets insuffisants, codes de sortie de la CLI). La CI exécute ruff, mypy `--strict`, pytest et `node --check` sur le middleware.
