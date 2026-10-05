# Contributing

This is a portfolio project, but issues and suggestions are welcome.

## Set-up

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check .
```

## Conventions

- Tests take the ledger and return the flagged rows with every column kept, so the row ID
  survives. They never read the `Anomaly` column.
- New tests go in `rules.py` and `pipeline.run_python_tests`. If a test belongs to a correlated
  group (like the date tests), add its keyword to `scoring.DATE_KEYWORDS`.
- If you change the generator or the IDEA mock, rebuild the fixtures with
  `python scripts/make_fixtures.py` and re-run `notebooks/demo.ipynb`.
- Synthetic data only: no real ledgers, names or figures in issues, fixtures or examples.
- Plain language and British spelling in docs.
