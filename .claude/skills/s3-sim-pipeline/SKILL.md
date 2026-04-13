---
name: s3-sim-pipeline
description: Operate the S³-Sim data generation pipeline — rollouts, ablations, oracle design, resume logic. Use when running data generation, adding ablations, debugging rollouts, or assembling SFT datasets.
---

# S³-Sim data generation pipeline

Stateful conversational data generation for personalized LLM alignment. Pairs a stateful user simulator with a privileged oracle assistant; student model is trained via SFT on assistant turns only.

## Entry points (project root)

| Script | Seeds from | When to use |
|---|---|---|
| `run_rollout.py` | `data/rewritten_prompts/original_rewritten_selected_prompts_us.jsonl` (1240 real-query rewrites) | Reproducible dataset rollouts |
| `run_deep_scenario_rollout.py` | Per-persona scenarios constructed on-the-fly via `simulator_lifelong_scenario_constructor.yaml` | Deeply-personal scenarios anchored in Erikson stages / life phases |
| `main.py` → `pipeline.py` | Legacy | **Do not extend** |

All entry points call `user_simulator.simulator.rollout_conversation` under an `AblationConfig`.

## Ablations (`user_simulator/ablation.py`)

Factorize along two axes: user simulator (state+behavior vs vanilla) × oracle access (full profile+state, profile-only, none).

| Name | User simulator | Assistant |
|---|---|---|
| `full` | state + behavior | oracle (profile + state) |
| `no_privilege` | state + behavior | vanilla (no profile) |
| `no_behavior` | state only | oracle |
| `no_state` | vanilla | oracle |
| `oracle_profile_only` | state + behavior | oracle (profile only, no user_state) |

`oracle_profile_only` isolates the contribution of user_state to the oracle — everything else matches `full`, including `sft_include_profile=True`. Assistant prompt routes through `assistant_vanilla_with_profile.yaml` via the `_TMPL_ASST_ORACLE_PROFILE_ONLY` branch in `simulator.py`.

Adding a new ablation: (1) factory classmethod + `from_name` entry in `ablation.py`, (2) new branch in `simulator.py:rollout_conversation`, (3) argparse choice in both rollout scripts.

## Resumability rules

- **Conversation JSONs**: dedup by `conv_path.exists()`. Safe to re-run — no overwrite, no duplicates.
- **SFT jsonl**:
  - `run_rollout.py` opens in `"w"` mode — **truncates on every run**. If you restart mid-run, the partial SFT jsonl from before is wiped. Rebuild it post-hoc from the conversation JSONs using `assemble_sft`.
  - `run_deep_scenario_rollout.py` opens in `"a"` mode — appends, safe across restarts.
- **Scenario cache** (`data/deep_scenarios/{persona_id}.json`): reused unless `--force-reconstruct`.

## Rebuilding SFT from conversation JSONs

```bash
uv run python -m user_simulator.oracle \
  output/conversations/<ablation_name> \
  -o output/sft/train_<ablation_name>.jsonl
```

`assemble_sft` in `user_simulator/oracle.py` reads all conv JSONs under a directory (flat or nested by persona), builds the SFT system prompt (profile + behavior_metadata if `include_profile=True`), and emits one JSONL line per conversation. Deterministic — use it whenever the SFT jsonl diverged from the conv dir.

## Detached long-running rollouts

Background tasks started with the `run_in_background` flag are tied to the Claude Code session — if the session ends they get SIGTERM'd. For 1240-scale rollouts (~90 min), launch with `nohup` + `disown` to survive:

```bash
nohup uv run python run_rollout.py --ablation <name> --concurrency 80 \
  >> logs/rollout_<name>.log 2>&1 </dev/null &
disown
```

Chaining follow-up work (e.g., rebuild SFT once rollout exits): start a second `nohup` bash that polls `kill -0 <pid>` in a loop, then runs the follow-up command.

## Environment

- `uv sync` to install, `uv run python ...` to execute.
- `.env` at root: `MODEL_NAME=gpt-4o-mini`, `OPENAI_BASE_URL=https://api.openai.com/v1`. Alternate presets: `.env.llmapi` (Qwen3), `.env.openai`.
- Per-role overrides: `SIM_MODEL`, `ORACLE_MODEL`.
- `output/` is gitignored except for a whitelisted historical dir; commit samples under `samples/` instead.

## Concurrency + cost

- 1240 rollouts at `--concurrency 80` against gpt-4o-mini took ~90 min end-to-end. Each rollout averages ~4 min at concurrency 1 (multi-turn, up to 12 turns × 2 sides × ~1s/call).
- The `LLM` class in `user_simulator/data.py` handles retry (3x with exponential backoff) and optional JSONL call logging via `log_calls=True`.

## Conventions

- Core logic → `user_simulator/`. Rollout scripts → project root. No I/O or CLI in `user_simulator/`.
- Type-annotate new code; prefer `dataclasses`/`pydantic` over raw dicts.
- Don't extend `main.py`/`pipeline.py`.
- Sync `S3-Sim-Simulating-Humans-for-Personalized-Language-Modeling/` (release submodule, JSONL format) only when data format or rollout output shape changes.
- Samples for new data versions: add one conversation JSON (ideally same persona+prompt as existing samples for apples-to-apples) under `samples/` and commit.

## Smoke-testing new pipelines

Before launching a 1240-scale run, smoke-test on one persona + one prompt/scenario:

```bash
uv run python run_rollout.py --persona-ids profile_259 --max-prompts 1 --concurrency 1 \
  --output-dir output/smoke
# or for deep scenarios:
uv run python run_deep_scenario_rollout.py --persona-ids profile_259 --max-scenarios 1 \
  --concurrency 1 --output-dir output/deep_scenario_smoke
```
