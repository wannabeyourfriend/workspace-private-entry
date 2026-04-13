---
name: bench
description: Automate p13n-eval-harness benchmarking across locally served vLLM endpoints. Discover served models by probing ports, then run one or more benchmarks (bigtom / prefeval / sotopia / lamp / lampqa / personamem) for each model in parallel and print a per-model summary. Use when the user says "run benchmarks", "/bench", or asks to evaluate served models on specific benchmarks.
allowed-tools: Bash Read Edit Write Grep Glob
---

# bench — orchestrate benchmarks across served models

## Workflow

1. **Discover served models.** Loop ports 8000-8010 and probe `http://localhost:PORT/v1/models`. For each responsive port, record `(port, model_id)` pairs. Skip the plain base model (`/home/.../Qwen2.5-7B-Instruct`) unless the user asks to include it — it typically co-appears with a LoRA on the same port; use the LoRA.

2. **Parse the user's request.** Extract:
   - Target benchmarks: `bigtom | prefeval | sotopia | lamp | lampqa | personamem` (or `all` → everything).
   - Target models: if unspecified, run every discovered endpoint. User may name a subset.
   - Optional: `WORKERS` (default 32, drop to 16 for PersonaMem at 32k context).

3. **Launch.** For each `(model, port)` run the benchmark scripts in parallel (one backgrounded `bash scripts/run_<bench>.sh` per model). Always:
   - Set `MODEL` to a short friendly name (LoRA name or `qwen2.5-7b-instruct`).
   - Set `MODEL_ID` to whatever `/v1/models` returned (needed when it's a filesystem path).
   - Write each model's log to `results/_<model>_<bench>.log`.

4. **Shared Sotopia/LaMP-QA judge.** If the base Qwen endpoint is up, use it as `JUDGE_PORT` + `JUDGE_MODEL` for Sotopia and LaMP-QA. Otherwise fall back to self-judge.

5. **Report.** Once done, run `scripts/summarize.py --results-root results --models <list>` and show the output to the user.

## Port probe (reusable)

```bash
for p in 8000 8001 8002 8003 8004 8005 8006 8007 8008 8009 8010; do
  r=$(curl -sS -m 2 "http://localhost:$p/v1/models" 2>/dev/null) || continue
  python -c "import sys,json; d=json.loads(sys.stdin.read()); [print('$p', m['id']) for m in d['data']]" <<< "$r"
done
```

## Benchmark flag reference

| Benchmark | Script | Extra env |
|---|---|---|
| bigtom | `run_bigtom.sh` | — |
| prefeval | `run_prefeval.sh` | `INTER_TURNS=5` |
| sotopia | `run_sotopia.sh` | `JUDGE_PORT`, `JUDGE_MODEL` |
| lamp | `run_lamp.sh` | `TASKS` (default LaMP-1..7 ex-6) |
| lampqa | `run_lampqa.sh` | `JUDGE_PORT`, `JUDGE_MODEL`, `CATEGORIES` |
| personamem | `run_personamem.sh` | `SIZE` (32k/128k), `EVAL_MODE` (mcq/generative) |

All scripts share: `MODEL`, `MODEL_ID`, `PORT`, `WORKERS`, `OUT_ROOT`.

## Gotchas (don't repeat these)

- PersonaMem-v2 32k needs vLLM `max_model_len ≥ 32768`. If the served ctx is smaller, stop and tell the user to relaunch vLLM with `--max-model-len 40000` before running.
- LaMP runner imports `transformers`; its PIL chain needs `LD_PRELOAD=/home/2025user/zhou/anaconda3/envs/persona/lib/libstdc++.so.6` (already in `run_lamp.sh`).
- When a LoRA endpoint is down (connection refused), poll instead of failing fast — see `wait_for_port` in `scripts/eval_lamp_4models.sh`.
- Oracle-style LoRAs can produce empty outputs for Sotopia role-play; verify `avg_turns > 0` in the scenario results before trusting the judge score.

## Minimal launch skeleton

```bash
OUT_ROOT=$(pwd)/results
WORKERS=${WORKERS:-32}
cd /path/to/p13n-eval-harness
for spec in no-state-us:8001:no-state-us us-profile-mar31:8002:us-profile-mar31; do
  IFS=: read M P MID <<< "$spec"
  MODEL=$M PORT=$P MODEL_ID=$MID WORKERS=$WORKERS OUT_ROOT=$OUT_ROOT \
    bash scripts/run_<bench>.sh > "$OUT_ROOT/_${M}_<bench>.log" 2>&1 &
done
wait
python scripts/summarize.py --results-root "$OUT_ROOT" --models no-state-us us-profile-mar31
```
