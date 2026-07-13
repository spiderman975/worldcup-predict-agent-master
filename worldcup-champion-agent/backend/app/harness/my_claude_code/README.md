# My Claude Code

This folder contains a local coding-agent harness copied from the feature/cc branch and adapted for this project.

It is the project-level agent runtime. The World Cup prediction domain is registered into this runtime as explicit `worldcup_*` business tools, while the original local coding tools remain available for command-line developer use.

The FastAPI chat API uses this runtime with a restricted tool allowlist: only World Cup business tools are exposed to web chat. Shell and file mutation tools are not exposed through the browser.

## Project Adaptations

- `WORKDIR` defaults to the `worldcup-champion-agent` project root instead of the current shell directory.
- LLM settings are loaded from `backend/.env` first, then environment variables:
  - `LLM_API_KEY`, `QWEN_API_KEY`, `DASHSCOPE_API_KEY`, `OPENAI_API_KEY`
  - `LLM_BASE_URL`, `DASHSCOPE_BASE_URL`, `OPENAI_BASE_URL`
  - `LLM_MODEL`, `QWEN_MODEL`
- Runtime data is written to `.agent_data/`, which is ignored by git.
- File tools and shell working directories are restricted to the project root.
- World Cup business workflows are registered by `worldcup_workflows.py`.
- Web chat bridges through `backend/app/harness/runtime.py`; `backend/app/services/my_claude_runtime_service.py` remains as a compatibility facade.

## World Cup Tools

- `worldcup_list_teams`: list teams, groups, FIFA ranks, and project ratings.
- `worldcup_list_matches`: list match IDs and fixtures.
- `worldcup_predict_match_workflow`: run the single-match six-agent workflow:
  `PlannerAgent -> DataScoutAgent -> FootballAnalystAgent -> SimulationAgent -> NarratorAgent -> CriticAgent`.
- `worldcup_run_full_prediction`: local CLI-only full prediction workflow. The browser uses the FastAPI prediction task API for long-running live updates.

## Run

From the project root:

```powershell
backend\.venv\Scripts\python.exe backend\app\harness\my_claude_code\main.py
```

Or from inside `backend`:

```powershell
.venv\Scripts\python.exe -m app.harness.my_claude_code.main
```

If no API key is configured, the program exits with a configuration message instead of starting an unusable session.

For web chat, set `MY_CLAUDE_RUNTIME_ENABLED=false` in `backend/.env` to temporarily fall back to the older lightweight chat responder.
