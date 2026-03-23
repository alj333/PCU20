# PCU20 Network Manager

Modern, cross-platform file server for Siemens Sinumerik PCU20 CNC controllers.

Replaces the original Windows-only PCU20 Network Manager with a Python-based solution featuring a web dashboard.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m pcu20
```

Open http://localhost:8020 for the web dashboard.

## Configuration

Copy `pcu20.toml.example` to `pcu20.toml` and edit to match your setup.
