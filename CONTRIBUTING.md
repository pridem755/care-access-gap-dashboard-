# Working rules

Solo project for now, but run it the way a team would so the history stays clean
and anyone can join later.

1. **One branch per task.** Branch from `main`, e.g. `feat/clean-data`, `docs/methodology`.
2. **Pull request before merging.** Open a PR into `main` and review your own diff
   before merging (if a teammate joins, one teammate review is required).
3. **One editor of the `.pbip` at a time.** Power BI files merge badly. Never edit
   the `powerbi/` project on two branches at once; finish and merge one before starting the next.
4. **Never edit `data/raw/`.** Raw files stay exactly as downloaded; all changes happen in
   `scripts/clean_data.py` and land in `data/processed/`.
5. **Save as .pbip, not .pbix.** File -> Save as -> Power BI Project (.pbip). If the option
   is missing, enable it under File -> Options and settings -> Options -> Preview features.
