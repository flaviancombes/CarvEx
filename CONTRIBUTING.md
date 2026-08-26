# Contribuer à CarvEx

## Préparer l'environnement

Utilisez Python 3.11 ou 3.12, créez un environnement virtuel, puis installez
les dépendances de développement :

```powershell
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Avant toute proposition, exécutez :

```powershell
python -m ruff check .
python -m black --check --diff .
python -m mypy
python -m pytest --cov --cov-report=term-missing
python -m build
```

Les changements doivent préserver les identités canoniques, la chaîne de
conservation et les APIs publiques existantes. Ne versez jamais de données de
preuve, de projets `.carvex`, de rapports générés ou de fichiers récupérés dans
le dépôt.

Ajoutez des tests déterministes pour toute correction et mettez à jour la
documentation d'architecture lorsqu'une interface publique évolue.
