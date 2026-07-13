# Data Layer Usage

The documented data layer uses SQLite at `data/worldcup.db`. The database is generated from seed or ingest scripts and should not be treated as the only source of truth.

## Initialize Database

```powershell
python -B -m data.seed --reset
```

Without `--reset`, existing `data/worldcup.db` is preserved.

## Import Static CSV Data

```powershell
python -B scripts\ingest_worldcup_static.py `
  --teams datasets\teams_2026.csv `
  --squads datasets\squads_2026.csv `
  --schedule datasets\schedule_2026.csv `
  --rankings datasets\fifa_rankings.csv
```

## Update Live Data

```powershell
python -B scripts\update_worldcup_live_data.py --injuries --injuries-csv datasets\injuries_2026.csv
python -B scripts\update_worldcup_live_data.py --lineups --lineups-csv datasets\lineups_2026.csv
python -B scripts\update_worldcup_live_data.py --rankings --rankings-csv datasets\fifa_rankings.csv
python -B scripts\update_worldcup_live_data.py --scores --year 2026
```

`--scores` reads `FOOTBALL_DATA_API_KEY` from `.env`.

## Validate Database

```powershell
python -B scripts\validate_worldcup_data.py
```

## Run Tests

```powershell
python -B -m pytest
```

