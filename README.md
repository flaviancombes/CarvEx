# CarvEx

CarvEx est une application PySide6 de post-traitement des résultats PhotoRec,
conçue pour organiser des projets d'investigation DFIR. Elle ne remplace pas
les procédures d'acquisition, de conservation des originaux ni la validation
humaine des résultats.

## Installation

CarvEx requiert Python 3.11 ou 3.12 et un environnement graphique compatible
avec PySide6. Depuis une copie propre du dépôt :

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install .
```

Pour contribuer ou lancer la suite qualité :

```powershell
python -m pip install -e ".[dev]"
```

## Lancement

Après installation, lancez :

```powershell
carvex
```

Ou directement depuis le dépôt :

```powershell
python main.py
python main.py C:\chemin\vers\dossier\PhotoRec
```

## Développement et validation

```powershell
python -m ruff check .
python -m black --check --diff .
python -m mypy
python -m pytest --cov --cov-report=term-missing --cov-report=xml
python -m build
```

Les tests Qt sont exécutés sans affichage dans la CI avec
`QT_QPA_PLATFORM=offscreen`; `PYTHONUTF8=1` y garantit un environnement UTF-8.
La couverture impose un seuil minimal de 75 %. MyPy contrôle le noyau de
publication typé ; l'extension progressive de ce périmètre est documentée dans
les travaux de maintenance.

## Publication

Une version est produite avec `python -m build` dans `dist/`. Avant publication,
vérifiez le changelog, exécutez la chaîne qualité ci-dessus et testez le wheel
dans un environnement vierge avec `python -m pip install dist/*.whl`.

Le workflow GitHub Actions `Release` construit puis publie les artefacts lors
de la publication d'une GitHub Release. Il requiert la configuration préalable
du Trusted Publishing PyPI pour l'environnement GitHub `pypi` ; aucun jeton
PyPI n'est stocké dans le dépôt.

## Gouvernance et documentation

- [Contribuer](CONTRIBUTING.md)
- [Sécurité](SECURITY.md)
- [Changelog](CHANGELOG.md)
- [Licence MIT](LICENSE)
- [Documentation d'architecture](docs/)
