# Trieste Meteo Monitor

Static GitHub Pages dashboard with scheduled collection from the **Protezione Civile FVG** monitoring API. Independent of Ecowitt. No credentials or server required.

## Publish on GitHub

1. Create a **public** repository (for example `trieste-meteo-monitor`).
2. Upload **all files and folders** in this ZIP to the repository root, including the hidden `.github` folder. Alternatively clone the repository and copy the files, then `git add . && git commit -m 'Initial site' && git push`.
3. Open **Settings → Actions → General** and ensure workflows can run. Under **Workflow permissions**, select **Read and write permissions** if the scheduled workflow cannot push its data updates. Repository/org policy may also need to allow GitHub Actions to create and approve pull requests; that option is not required here.
4. Open **Settings → Pages → Build and deployment → Source** and choose **GitHub Actions**.
5. Open **Actions → Collect weather and deploy Pages → Run workflow**. After it succeeds, open the URL displayed in the Pages deployment or under Settings → Pages.
6. The workflow runs at approximately minute 07 and 37 of every hour (UTC). GitHub can delay scheduled jobs, and schedules on inactive public repos can be disabled after a period of inactivity.

## What it does

- Discovers stations with municipality ISTAT code `32006` and their sensors; starts with the five Trieste station IDs supplied by the project owner.
- Downloads measurements using `/api/stations/{station}/sensors/{sensor}/measures?from=...&to=...&last=10000&offset=...`.
- Incrementally backfills from **2023-01-01** in 7-day windows, retaining a cursor for each station/sensor. Data may be unavailable for older periods.
- Refreshes a rotating subset of sensors over the previous two days each run. The latest values of all sensors are **not** guaranteed to be updated simultaneously.
- Stores values in `site/data/history/{station}/{sensor}/{year}.json`. Re-runs merge readings without duplication.
- Displays any sensor, hourly raw readings, daily or monthly values, station Google Maps links, and CSV export.
- **Only `P_1h` is summed** as hourly rainfall. Other sensors use averages when aggregated; rolling rainfall sensors (`Prec_24_ore`, etc.) are *not* summed.

## Important accuracy notes

The API returns naive timestamps. The dashboard **does not assume UTC** or shift timestamps: it groups values by the calendar date returned by the API. Confirm the API timezone and whether `P_1h` is labeled at the start or end of its hour before using calendar-day rainfall for official reporting. The dashboard does not fill gaps with zero. Sensor `B` may represent station-level pressure rather than sea-level-corrected pressure.

## Operational limits

- The initial 2023–present archive for *all* stations and sensors can take many scheduled runs. `FVG_BACKFILL_REQUESTS` (default 28 windows/run) and `FVG_RECENT_REQUESTS` (default 12 sensors/run) tune API load. The first runs can show sparse or no historical data.
- The collector stores historical raw data as JSON files in git. A large multi-year archive may grow substantially; if this becomes too large, migrate to compressed yearly files or a separate data repository.
- GitHub Actions requires permission to commit back to the repository. Branch protection may block direct pushes.
- Charting uses Plotly's CDN and requires internet access.
- This project is independent of, and does not modify, the Ecowitt dashboard.

Data source: https://monitor.protezionecivile.fvg.it/api/apidocs/index.html
