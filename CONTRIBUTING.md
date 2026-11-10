# Working rules

This is a solo project for now, but it is run the way a team would run it, so the history stays
clean and someone else could join later.

1. **One branch per task.** Start each piece of work on a new branch from `main`, with a short
   descriptive name such as `feat/clean-data` or `docs/methodology`.
2. **Pull request before merging.** Open a pull request into `main` and read through your own changes
   before merging. If a teammate joins, one teammate must review each pull request.
3. **One person edits the Power BI project at a time.** Power BI files do not merge well, so never
   change the `powerbi/` project on two branches at once. Finish and merge one change before starting
   the next.
4. **Never edit the raw data.** Files in `data/raw/` stay exactly as they were downloaded. Every change
   to the data happens in the cleaning code, and its results go into `data/processed/`.
5. **Save the report as a Power BI Project.** In Power BI Desktop, use File, then Save as, and choose
   the Power BI Project (.pbip) format rather than .pbix. If that option is missing, turn it on under
   File, Options and settings, Options, Preview features.
6. **Keep secrets out of the repository.** The Census API key belongs in the `CENSUS_API_KEY`
   environment variable, never in a file.

---

Prepared by Pride Mudondo.
