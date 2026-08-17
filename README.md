# Application de devis SBBM

Application FastAPI permettant d'importer un ou plusieurs fichiers CSV du
progiciel, de consolider leurs quantités et de générer un devis HTML/PDF.

## Ouvrir et lancer avec VS Code

1. Ouvrir le dossier `devis_app-main` dans VS Code.
2. Installer les extensions Python recommandées si VS Code le propose.
3. Vérifier que l'interpréteur affiché est `venv/bin/python` (Python 3.14).
4. Ouvrir **Exécuter et déboguer** et choisir **Devis SBBM - FastAPI**.
5. Appuyer sur `F5`, puis ouvrir <http://127.0.0.1:8000>.

Compte local de démonstration :

- utilisateur : `ga`
- mot de passe : `1234`

Ces identifiants sont uniquement adaptés aux tests locaux.

## Commandes dans le terminal

```bash
source venv/bin/activate
uvicorn app.main:app --reload
```

Tests automatiques :

```bash
venv/bin/python -m unittest discover -s tests -v
```

Les mêmes commandes sont disponibles dans **Terminal > Exécuter la tâche**.

## Tester l'import multiple

1. Se connecter et ouvrir **Nouveau devis**.
2. Choisir le mode **À partir d'un ou plusieurs fichiers progiciel**.
3. Dans le sélecteur, sélectionner plusieurs `.CSV` avec `Cmd`/`Ctrl` ou `Shift`.
4. Compléter le client et le chantier.
5. Cliquer sur **Générer le devis**.

Les poutrelles et hourdis sont réunis, les surfaces CT/TS sont additionnées,
puis un seul devis et un seul PDF sont générés.

Le formulaire propose deux présentations :

- **Devis regroupé** : les articles identiques de tous les CSV sont fusionnés.
- **Détail par niveau** : chaque CSV produit une section nommée d'après son
  fichier, avec ses articles regroupés et son sous-total HT. Le total général
  reste identique au mode regroupé.

## Fichiers principaux

- `app/main.py` : routes FastAPI, formulaire, import multiple et PDF.
- `app/services/parser_progiciel.py` : lecture du format CSV progiciel.
- `app/services/engine.py` : tarification et calcul du transport.
- `templates/` : pages HTML Jinja2.
- `data/` : fichiers de données et exemples.

La base `devis.db` et les PDF générés sont créés localement et ignorés par Git.

## Déploiement Render

Le fichier `render.yaml` configure un service web Python en région Frankfurt,
avec un disque persistant de 1 Go monté sur `/var/data`. Le disque conserve la
base SQLite et les PDF après un redéploiement ou un redémarrage.

La commande de production est :

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Render vérifie l'application avec la route `/health`. Le disque persistant
nécessite un service Render payant ; sans disque, SQLite et les PDF seraient
réinitialisés lors des redéploiements.
