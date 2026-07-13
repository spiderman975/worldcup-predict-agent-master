# Player Squad and Rating Mapping

This document defines the P1 data rules for converting traceable squad inputs into `datasets/squads_2026.csv`.

## Output Schema

`datasets/squads_2026.csv` must keep the current data-layer-compatible fields:

| Field | Description |
| --- | --- |
| `team_name` | Canonical team name matching `datasets/teams_2026.csv`. |
| `name` | Player name used by `data.models.Member`. |
| `attack` | Final attack ability on a deterministic `0~100` scale. |
| `defensive` | Final defensive ability on a deterministic `0~100` scale. |
| `injured` | `0` or `1`. |
| `injury_description` | Empty string when no confirmed injury note exists. |

The current core schema does not include a `position` field. Position may be stored in raw input files and used to generate `attack` / `defensive`, but it must not be written to the final `squads_2026.csv` unless the data model is explicitly changed later.

## Squad Source Priority

Use the strongest available source for each team, and document the source in the raw input:

1. FIFA official squad page, if available.
2. National team official website squad announcement.
3. Trusted sports media or Wikipedia squad page for cross-checking.
4. Manually curated candidate squad when final official squads are not available.
5. Aligned rule-generated scaffold when no candidate squad is available.

Manual or scaffold rows must never be described as official squads.

## Rating Source Priority

Use the strongest available ability source for each player:

1. Public player rating or statistical data that can be traced.
2. Position-based mapping when no consistent rating source is available.
3. Neutral fallback `65/65` when position is missing or unknown.

All fallback values must be deterministic. Random values are not allowed.

## Position-Based Mapping

The raw input may use `position=GK`, `DF`, `MF`, `FW`, or `UNKNOWN`.

Recommended ranges:

| Position | Attack Range | Defensive Range | Deterministic Default |
| --- | --- | --- | --- |
| `GK` | `20~35` | `75~95` | `28/85` |
| `DF` | `35~60` | `70~90` | `48/80` |
| `MF` | `55~85` | `55~80` | `70/68` |
| `FW` | `70~95` | `25~60` | `84/42` |
| `UNKNOWN` | neutral | neutral | `65/65` |

If `attack_raw` or `defensive_raw` is present, the builder treats it as a numeric `0~100` value and clamps it to `0~100`. Empty raw values fall back to the position rule above.

## Ranking-Adjusted Position Fallback

`ranking_position_fallback` is the current P1-F ability mapping mode.

This is not an official player rating, not an EA/FC rating, and not OPTA or club-level performance data. It is a deterministic fallback that uses position base values plus a national-team FIFA ranking tier modifier so teams do not all have identical same-position ability values.

Base values:

| Position | Base Attack | Base Defensive |
| --- | ---: | ---: |
| `GK` | 28 | 85 |
| `DF` | 48 | 80 |
| `MF` | 70 | 68 |
| `FW` | 84 | 42 |
| `UNKNOWN` | 65 | 65 |

FIFA ranking tier modifier:

| FIFA Ranking | Modifier |
| --- | ---: |
| `1~10` | `+8` |
| `11~20` | `+5` |
| `21~30` | `+3` |
| `31~50` | `0` |
| `51~75` | `-3` |
| `76+` | `-6` |

Formula:

```text
attack = clamp(base_attack + modifier, 0, 100)
defensive = clamp(base_defensive + modifier, 0, 100)
```

The rule does not introduce random differences or name-hash differences within a team. If reliable `rating_source` or `manual_rule` data is later added to `attack_raw` / `defensive_raw`, those raw values can override this fallback.

## Injury Rules

- `0` means healthy, available, or no confirmed absence.
- `1` means confirmed injury, suspension, or unavailable status from a clear source.
- Suspected or rumored injury should not be marked as `injured=1` without a clear source.
- Empty `injured` values in raw input default to `0`.
- Empty `injury_description` values default to an empty string.

## Traceability

The preferred P1 raw input format is `datasets/raw/squads_2026_manual.csv`.

Each raw row should preserve:

- `source_note`: where the player-list row came from, such as `official`, `team_website`, `manual_curated`, or `scaffold`.
- `attack_source` / `defensive_source`: where each ability value came from, such as `rating`, `manual_rule`, `position_fallback`, or `neutral_fallback`.
- `attack_raw` / `defensive_raw`: source value when available.

The final `squads_2026.csv` intentionally keeps only fields consumed by the current data layer.

## Current P1-F Dataset

The current P1-F raw squad file is `datasets/raw/squads_2026_manual.csv`.

Current status:

- `source_note`: all 48 teams use `manual_curated_candidate`.
- `attack_source`: all rows use `ranking_position_fallback`.
- `defensive_source`: all rows use `ranking_position_fallback`.
- `attack_raw` / `defensive_raw`: empty for all rows.
- `injured`: `0` for all rows.
- `injury_description`: empty for all rows.
- `datasets/raw/squad_sources_2026.csv` tracks source URLs and comments for non-scaffold rows.

The current manual curated candidate set is not an official FIFA final squad. It covers all 48 canonical teams, including:

- Algeria
- Argentina
- Australia
- Austria
- Belgium
- Brazil
- Colombia
- Croatia
- Ecuador
- England
- France
- Germany
- Japan
- Mexico
- Morocco
- Netherlands
- Portugal
- Senegal
- South Korea
- Spain
- Switzerland
- Turkey
- United States
- Uruguay
- Uzbekistan

Position distribution:

| Position | Rows |
| --- | ---: |
| `GK` | 48 |
| `DF` | 192 |
| `MF` | 144 |
| `FW` | 144 |

For the current P1-F build, the output ability values are generated by `scripts/build_squads_from_raw.py --rating-mode ranking_position_fallback --rankings datasets/fifa_rankings.csv`.

No player uses `rating_source` in the current P1-F dataset. No team currently remains on `scaffold_fallback`. `neutral_fallback` is reserved for rows where `position=UNKNOWN` or for explicit scaffold fill rows created with `--allow-scaffold-fill`. The current raw file has 11 rows for every team, so the builder did not need to synthesize additional fill rows.
