# UR Vacancy Watcher

A tiny Python/Playwright watcher for UR rental vacancies. It checks the configured Kanagawa / Tokyu Toyoko Line search every 15 minutes, stores the latest snapshot in `data/vacancies.txt`, and emails only when new entries appear.

## Why Playwright?

UR renders parts of the vacancy list with JavaScript. Playwright loads the page like a browser, while the parser avoids depending on one fragile CSS class.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env
python -m src.watcher
```

The initial run records the current inventory but does **not** email it. Set `SEND_INITIAL=true` to receive the initial snapshot too.

## Free 24/7 hosting with GitHub Actions

1. Create a GitHub repository and push these files. A **public repository** is best if you want to avoid private-repository Actions-minute limits. Do not commit `.env`.
2. Open **Settings → Secrets and variables → Actions → Variables** and create:
   - `SEARCH_URL`: paste the full UR results URL. The supplied default is the Kanagawa Tokyu Toyoko Line URL.
3. Under **Repository secrets**, create:
   - `SMTP_USERNAME`: the Gmail address that will send alerts.
   - `SMTP_PASSWORD`: a Google App Password for that sending account, not its normal password.
4. Open the **Actions** tab, select **Watch UR vacancies**, and click **Run workflow** once.
5. Check the first run. It should commit the initial `data/vacancies.txt` snapshot without sending an email.

Alerts go to `kyuhur2@gmail.com`. Change `NOTIFY_EMAIL` in `.github/workflows/watch.yml` to use another address.

## Changing the search

No code change is needed. Generate a new UR results URL in the browser and replace the `SEARCH_URL` repository variable. This can represent another prefecture, line, station set, rent range, or floor-space range.

## Important behavior

- It sends on **additions only**, not removals.
- A parse failure does not overwrite the last good state, preventing a false flood on the next run.
- On failure, the workflow uploads the rendered page as a short-lived debug artifact.
- GitHub scheduled jobs are best-effort and can run late. The workflow is configured at minutes 7, 22, 37, and 52 to avoid the busiest top-of-hour period.
- Keep the polling interval polite. Fifteen minutes is reasonable; do not aggressively hammer the site.

## Run tests

```bash
pip install pytest
pytest -q
```

## Gmail App Password

Google generally requires 2-Step Verification before an App Password can be created. Put that generated 16-character password into the GitHub secret `SMTP_PASSWORD`. Never place it in source code or `vacancies.txt`.
