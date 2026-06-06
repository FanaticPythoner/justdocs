# Project Setup

Project Setup installs Justdocs into an MkDocs project and writes a local
`Justfile` for deterministic build and serve commands.

## Generator

```bash
justdocs theme-dir
justdocs init --root docs-project --mkdocs-config mkdocs.yml --addr 127.0.0.1:8000
```

| Command | Contract |
| --- | --- |
| `justdocs theme-dir` | Validate required theme assets and print the absolute theme package path. |
| `justdocs init` | Write a project-local `Justfile`. |

| Option | Default | Contract |
| --- | --- | --- |
| `--root` | `.` | Directory receiving `Justfile`. |
| `--mkdocs-config` | `mkdocs.yml` | MkDocs config path used by generated recipes. |
| `--addr` | `127.0.0.1:8000` | MkDocs serve bind address. |
| `--package` | `justdocs` | Pip package spec installed by generated recipes. |
| `--force` | `false` | Existing `Justfile` overwrite gate. |

## Generated Recipes

| Recipe | Contract |
| --- | --- |
| `just install` | Create virtualenv, upgrade pip, install package spec, and install extra packages. |
| `just check` | Run strict MkDocs build with clean output. |
| `just build` | Alias for `check`. |
| `just serve` | Serve the configured MkDocs project. |
| `just serve-clean` | Free the configured port, then serve. |
| `just free-port` | Kill local processes bound to the configured port. |
| `just clean` | Remove MkDocs output and cache directories. |
| `just dist-clean` | Remove outputs, cache directories, and virtualenv. |

## Environment

| Variable | Default | Contract |
| --- | --- | --- |
| `JUSTDOCS_PYTHON` | `python3` | Python used to create virtualenv. |
| `JUSTDOCS_CONFIG` | generator config path | MkDocs config path. |
| `JUSTDOCS_ADDR` | generator address | MkDocs serve address. |
| `JUSTDOCS_PORT` | port from address | Port passed to `lsof -t -i`. |
| `JUSTDOCS_PACKAGE` | generator package spec | Pip package spec. |
| `JUSTDOCS_EXTRA_PACKAGES` | `pymdown-extensions==10.12` | Additional pip packages. |
| `JUSTDOCS_VENV` | `.venv` | Virtualenv directory. |
| `JUSTDOCS_VENV_PYTHON` | `.venv/bin/python` | Virtualenv Python executable. |
| `JUSTDOCS_VENV_MKDOCS` | `.venv/bin/mkdocs` | Virtualenv MkDocs executable. |

## Install Safety

| Guard | Contract |
| --- | --- |
| Existing file | `ProjectJustfileExistsError` preserves existing `Justfile` unless `--force` is present. |
| Package spec parsing | `ProjectJustfileInvalidPackageError` rejects invalid shell syntax and empty specs. |
| Editable install | `-e`, `--editable`, and `--editable=<path>` are rejected. |
| Local source install | `flock` serializes installs by canonical package root. |
| Missing template | `TemplateAssetError` reports absent project template assets. |

## Source Repository

| Recipe | Contract |
| --- | --- |
| `just install` | Install the local package into source `.venv`. |
| `just theme-dir` | Print the bundled theme package path. |
| `just example-justfile` | Regenerate this example `Justfile`. |
| `just test` | Run package tests. |
| `just example-build` | Build this example site through its generated recipe. |
| `just example-serve` | Serve this example site through its generated recipe. |
| `just check` | Run tests and strict example build. |
