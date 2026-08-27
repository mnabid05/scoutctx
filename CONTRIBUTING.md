# Contributing to ScoutCTX

Thanks for helping make coding-agent context smaller, safer, and more useful.

## Before you start

For a significant feature, open an issue first so the approach can be discussed. Bug fixes and documentation improvements are welcome as direct pull requests.

ScoutCTX has three product constraints:

1. Repository content stays local.
2. Ranking and selection remain explainable and deterministic.
3. The CLI keeps zero runtime dependencies.

## Local setup

```bash
git clone https://github.com/mnabid05/scoutctx.git
cd scoutctx
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
```

On Windows PowerShell, activate the environment with `.venv\Scripts\Activate.ps1`.

## Pull requests

- Keep each pull request focused on one behavior or concern.
- Add tests that fail before the change and pass afterward.
- Update the README and changelog when behavior visible to users changes.
- Include a CLI example when introducing a new option.
- Confirm that generated briefs contain no timestamps or absolute paths.

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

