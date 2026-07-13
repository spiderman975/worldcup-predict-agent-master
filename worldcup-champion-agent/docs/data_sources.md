# World Cup Seed Data Sources

This repository's formal CSV seed files are designed to make the documented SQLite data layer reproducible without committing `data/worldcup.db`.

## Data Acquisition Checklist

| File | Fields | Current source | Target formal source | Acquisition method | Done | Validation |
| --- | --- | --- | --- | --- | --- | --- |
| `teams_2026.csv` | `name`, `group`, `attack_team`, `defensive_team`, `streak`, `starting_lineup`, `fifa_ranking` | official/API source via saved football-data.org raw JSON; dependent lineup fields are scaffolded | official/API source: football-data.org World Cup teams plus official/FIFA draw groups | raw-file mode reads `datasets/raw/football_data_teams_2026.json` and `datasets/raw/football_data_matches_2026.json`; metadata is saved to `datasets/raw/football_data_build_2026_metadata.json` | Yes for team universe | `scripts/validate_dataset_csv.py`, then `scripts/validate_worldcup_data.py` |
| `schedule_2026.csv` | `match_id`, `stage`, `home_team`, `away_team`, `home_score`, `away_score`, `is_real`, `played_at` | official/API source via saved football-data.org raw JSON | official/API source: football-data.org World Cup matches or FIFA official fixtures | raw-file mode records the manually downloaded raw path in metadata; matches without known teams are skipped until raw data is complete | Yes for matches with known teams | unique `match_id`, teams exist, stage in `1~8`, unplayed score `-1/-1` |
| `fifa_rankings.csv` | `team_name`, `fifa_ranking`, `ranking_date` | manually extracted and canonicalized FIFA ranking-related data | official source: FIFA men's world ranking page/download, with manual extraction fallback when dynamic HTML is incomplete | current P0 file is preserved as `datasets/raw/fifa_rankings_2026_manual_canonical.csv`; it is manually canonicalized, not auto-parsed from full HTML | Yes for P0 manual canonical CSV | positive integer rankings, `ranking_date`, and teams exist in `teams_2026.csv` |
| `squads_2026.csv` | `team_name`, `name`, `attack`, `defensive`, `injured`, `injury_description` | manual curated candidate squad with ranking-adjusted position fallback abilities | official squad lists plus a documented ability mapping when announced/available | raw input `datasets/raw/squads_2026_manual.csv` is built through `scripts/build_squads_from_raw.py --rating-mode ranking_position_fallback`; non-scaffold source notes are tracked in `datasets/raw/squad_sources_2026.csv` | P1-F manual candidates + deterministic fallback abilities | team exists, at least 11 players, ability values in `0~100` |
| `lineups_2026.csv` | `team_name`, `player_name` | aligned rule-generated scaffold from the first 11 squad rows per team | manually curated or official match lineups when available | rebuilt only with explicit `--rebuild-dependent-scaffolds` | Scaffold only | every player exists in `squads_2026.csv` |
| `injuries_2026.csv` | `team_name`, `player_name`, `injured`, `injury_description` | aligned healthy baseline scaffold, not an official injury report | manually curated source from reliable injury reports | rebuilt only with explicit `--rebuild-dependent-scaffolds` | Scaffold only | every player exists in `squads_2026.csv`; `injured` is `0/1` |

Source type legend:

- `official/API source`: official provider or API output preserved under `datasets/raw/`.
- `manually curated source`: human-maintained rows with source notes.
- `rule-generated source`: deterministic seed rows generated from documented rules.

Current P0 status: completed with traceable football-data.org raw files, aligned rule-generated scaffolds, and a manually canonicalized ranking CSV.

- `teams_2026.csv` and `schedule_2026.csv` were generated from saved football-data.org raw files in raw-file mode. This must be described as saved raw-file generation, not as a live API fetch.
- `datasets/team_aliases.csv` defines the canonical team-name mapping used by the official builders and CSV validator.
- `squads_2026.csv`, `lineups_2026.csv`, and `injuries_2026.csv` were rebuilt with the explicit `--rebuild-dependent-scaffolds` flag. They are aligned scaffolds and are not official squad, lineup, or injury data.
- `fifa_rankings.csv` contains 48 canonical teams with `ranking_date=2026-04-01`. The available FIFA dynamic HTML still exposes only 10 parseable rows, so P0 uses a manually extracted and manually canonicalized CSV preserved at `datasets/raw/fifa_rankings_2026_manual_canonical.csv`.

Current P1-F squad status: `datasets/squads_2026.csv` is built from `datasets/raw/squads_2026_manual.csv` and all 48 teams now use manual curated candidate squads with `ranking_position_fallback` ability values.

- Rating and source rules are documented in `docs/player_rating_mapping.md`.
- Raw manual squad input format is documented by `datasets/raw/squads_2026_manual.csv.example`.
- `scripts/build_squads_from_raw.py` converts a traceable raw squad CSV into the data-layer-compatible `datasets/squads_2026.csv`.
- `datasets/raw/squad_sources_2026.csv` records source notes and source URLs for non-scaffold rows.
- The current manual rows are not official FIFA final squads. They are manual curated candidate lists cross-checked against public national team pages.
- Current attack/defensive values are not official player ratings and are not random values. They are deterministic position base values adjusted by FIFA ranking tier.
- First batch `manual_curated_candidate` teams: Argentina, Brazil, England, France, Germany, Netherlands, Portugal, Spain.
- Second batch `manual_curated_candidate` teams: Algeria, Australia, Austria, Belgium, Colombia, Croatia, Ecuador, Japan, Mexico, Morocco, Senegal, South Korea, Switzerland, Turkey, United States, Uruguay.
- P1-E `manual_curated_candidate` teams: Bosnia and Herzegovina, Canada, Cape Verde, Curacao, Czechia, DR Congo, Egypt, Ghana, Haiti, Iran, Iraq, Ivory Coast, Jordan, New Zealand, Norway, Panama, Paraguay, Qatar, Saudi Arabia, Scotland, South Africa, Sweden, Tunisia, Uzbekistan.
- Current `scaffold_fallback` teams: none.

Latest P0 attempt metadata:

- football-data teams raw: `datasets/raw/football_data_teams_2026.json`
- football-data matches raw: `datasets/raw/football_data_matches_2026.json`
- football-data build metadata: `datasets/raw/football_data_build_2026_metadata.json`
- FIFA ranking raw HTML checked first: `datasets/raw/fifa_rankings_2026_20260401_full.html`
- FIFA ranking fallback HTML: `datasets/raw/fifa_rankings_2026_20260401.html`
- FIFA manual canonical ranking raw: `datasets/raw/fifa_rankings_2026_manual_canonical.csv`
- FIFA ranking date requested: `2026-04-01`

## `datasets/teams_2026.csv`

The file now uses the 48-team universe returned by football-data.org raw data. Team names are canonicalized through `datasets/team_aliases.csv`; for example `Bosnia-Herzegovina` becomes `Bosnia and Herzegovina`, `Cape Verde Islands` becomes `Cape Verde`, `Congo DR` becomes `DR Congo`, and `Curaçao` becomes `Curacao`.

Official replacement status: completed for the team universe via raw-file mode. The `starting_lineup` values are still scaffolded from `squads_2026.csv`; they are not official lineups.

Formal replacement paths:

```powershell
python -B scripts\build_official_teams_schedule.py --year 2026 --rebuild-dependent-scaffolds
```

The API mode reads `FOOTBALL_DATA_API_KEY` from `.env` or the environment and saves raw responses to:

- `datasets/raw/football_data_teams_2026.json`
- `datasets/raw/football_data_matches_2026.json`
- `datasets/raw/football_data_build_2026_metadata.json`

Raw-file fallback mode does not require an API key:

```powershell
python -B scripts\build_official_teams_schedule.py `
  --teams-raw datasets\raw\football_data_teams_2026.json `
  --matches-raw datasets\raw\football_data_matches_2026.json `
  --rebuild-dependent-scaffolds
```

When raw-file mode is used, the raw files are treated as manually downloaded football-data.org responses. The metadata file records the raw paths, UTC generation time, and whether CSV files were written. This must not be described as a live API fetch.

## `datasets/schedule_2026.csv`

The schedule is generated from football-data.org raw matches. The current raw file contains 104 matches; 101 rows are written because 3 later knockout matches do not yet include concrete home/away teams. Those skipped rows are recorded as `skipped_matches_missing_teams` in `datasets/raw/football_data_build_2026_metadata.json`.

Official replacement status: completed for matches with known teams.

Field mapping from football-data.org matches:

- canonical `stage`, `home_team`, and `away_team` -> stable `match_id` such as `s1_mexico_south_africa`; duplicate pairings receive the API id as a suffix
- `stage` -> numeric `stage` (`GROUP_STAGE` = `1`, `LAST_16` = `2`, quarter-finals = `3`, semi-finals = `4`, third-place = `5`, final = `6`)
- `homeTeam.name` -> `home_team`
- `awayTeam.name` -> `away_team`
- `score.fullTime.home/away` -> score fields only when status is finished
- non-finished matches -> `home_score=-1`, `away_score=-1`, `is_real=false`
- `utcDate` -> `played_at`

## `datasets/fifa_rankings.csv`

The rankings are a manually extracted and manually canonicalized P0 CSV aligned with the official 48-team universe. The file includes `team_name`, `fifa_ranking`, and `ranking_date`, with `ranking_date=2026-04-01`.

Official replacement status: completed for P0 with manual canonical CSV. This is not a full automatic parse of FIFA HTML. The saved FIFA HTML files only expose 10 parseable teams, so they remain evidence of the blocked automatic path rather than the source used to generate the completed P0 ranking CSV.

Traceability path: `datasets/fifa_rankings.csv` is mirrored to `datasets/raw/fifa_rankings_2026_manual_canonical.csv` and must be described as manually extracted / manually canonicalized FIFA ranking-related data. If a complete official downloadable CSV becomes available later, replace this manual canonical CSV through `scripts/build_official_rankings.py` and keep the raw official file.

## `datasets/squads_2026.csv`

Squad rows are currently built from `datasets/raw/squads_2026_manual.csv` by `scripts/build_squads_from_raw.py`. The raw file uses `source_note=manual_curated_candidate` for all 48 teams. The current project does not claim these are official FIFA final squads.

For the P1-C, P1-D, and P1-E batches, `teams_2026.csv` `starting_lineup` values are aligned to each team's 11 manual curated candidate players so the SQLite validator can confirm starters belong to team members. These are provisional/manual starting lineups, not official starting lineups.

P1 replacement path:

```powershell
python -B scripts\build_squads_from_raw.py `
  --teams datasets\teams_2026.csv `
  --raw-squads datasets\raw\squads_2026_manual.csv `
  --output datasets\squads_2026.csv `
  --rankings datasets\fifa_rankings.csv `
  --rating-mode ranking_position_fallback
```

If a team has fewer than 11 raw players, the script stops by default. Use `--allow-scaffold-fill` only when the remaining placeholder players are explicitly acceptable and documented as scaffold fallback.

Later P1 passes can replace manual curated candidates with official squad rows or richer rating-source rows when reliable sources become available.

## Attack / Defensive Mapping

Player ability values are deterministic, not random. The detailed P1 mapping policy is in `docs/player_rating_mapping.md`.

For the current P1-F dataset:

- Player names are manual curated candidates, not FIFA official final squads.
- `attack` / `defensive` are generated by `ranking_position_fallback`, not official player ratings.
- `ranking_position_fallback` uses position base values plus a FIFA ranking tier modifier from `datasets/fifa_rankings.csv`.
- Values are clamped to `0~100`.
- No random values are used.

This gives stronger teams slightly higher baseline values while keeping role differences visible and reproducible.

## `datasets/injuries_2026.csv`

The current injury file is an aligned healthy baseline with all listed scaffold players marked healthy (`injured=0`). It is a temporary P0/P1 baseline and is not an official injury report.

## `datasets/lineups_2026.csv`

The current lineup file uses each team's first 11 scaffold squad players as the starting lineup. It is a temporary P0/P1 scaffold and is not an official lineup source.
