# Collecte pytest et imports internes

CarvEx conserve ses packages applicatifs à la racine du dépôt plutôt que sous
un répertoire `src/`. Les packages possèdent leurs `__init__.py` lorsque cela
est nécessaire ; `core` peut également être importé comme namespace package
tant que la racine du projet est dans `sys.path`.

La configuration `[tool.pytest.ini_options]` fixe donc deux garanties :

- `pythonpath = ["."]` ajoute explicitement la racine du dépôt aux imports ;
- `--import-mode=prepend` rend le comportement indépendant du mode
  `importlib`, qui n'ajoute pas systématiquement le répertoire racine.

Toujours lancer les tests avec l'interpréteur qui possède les dépendances du
projet :

```powershell
.\.venv\Scripts\python.exe -m pytest --collect-only -q
```

Un `pytest.exe` installé globalement peut viser un autre interpréteur ou un
répertoire de travail différent, ce qui explique un `ModuleNotFoundError` sur
un package pourtant importable avec `py -c`.
