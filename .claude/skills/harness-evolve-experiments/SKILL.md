---
name: harness-evolve-experiments
description: Set up and run harness-evolve experiments (sudoku / arc_agi / text_classification / terminal_bench) with dual .env files, then diagnose and work around the infra gotchas that bite in bandwidth-restricted labs.
---

# Harness-Evolve Experiments

Use this when the user wants to run any of the four task families under
`harness_evolve/` end-to-end, or when an experiment is stuck on credentials,
models, or container networking. You drive the pipeline; this doc captures
what I (Claude Opus 4.7) learned the hard way so the next run is faster.

## TL;DR decision tree

- **New smoke run?** Always `bash scripts/e2e_<family>.sh`, never poke Python
  directly from a REPL. Override with env vars (below).
- **Model fails to respond?** Check `MODEL_NAME` in the env file matches what
  the endpoint actually serves. `gpt-5.3-codex` is a real alias in this lab,
  not a typo; `gpt-4.1-mini` and `gpt-5-mini` coexist.
- **Docker-backed family (terminal_bench) stalling?** It's almost always
  container-side network, not your code. Set `TB_FORCE_BUILD=1` and tag a
  local `ubuntu:24.04`. See §5.
- **Tests pass locally but e2e hangs?** The verifier inside the TB task
  container downloads `uv` at runtime. That can hit SSL errors or 10 KB/s
  throttling. Score becomes 0.0 for reasons unrelated to the harness.

## 1. Env file layout (dual-env pattern)

The repo ships three dotenvs at its root. They share `OPENAI_API_KEY` and
`OPENAI_BASE_URL`; the only practical difference is `MODEL_NAME`:

```
.env.openai           MODEL_NAME=gpt-5-mini
.env.openai.proposer  MODEL_NAME=gpt-5.3-codex  # drafts harnesses
.env.openai.eval      MODEL_NAME=gpt-4.1-mini   # solves puzzles
```

Every `scripts/e2e_<family>.sh` reads two envs (`ENV_PROPOSER` and
`ENV_EVAL`), parses `MODEL_NAME` out of each without polluting shell state,
then sources both (eval last so `OPENAI_API_KEY` in-process matches the
eval path). Override with:

```bash
ENV_PROPOSER=.env.openai.proposer ENV_EVAL=.env.openai \
  bash scripts/e2e_<family>.sh
```

If a user asks you to "run with env X for proposer and env Y for eval",
that's the pattern — do not try to edit the env files themselves, override.

## 2. Running each family

All four use the same `harness_evolve.cli run` entry point under the hood.
Defaults are deliberately tiny so a smoke takes minutes, not hours.

| Family | Script | Default iter | Default tasks | Wall time (iter=2, n=1) |
|---|---|---|---|---|
| sudoku | `scripts/e2e_sudoku.sh` | 4 | 1 puzzle | ~5 min |
| arc_agi | `scripts/e2e_arc_agi.sh` | 2 | 1 task, no-aug | ~3 min |
| text_classification | `scripts/e2e_text_classification.sh` | 2 | built-in smoke JSON | ~2 min |
| terminal_bench | `scripts/e2e_terminal_bench.sh` | 1 | `extract-elf` | ~7–25 min |

Scale up via env overrides:

```bash
NUM_ITERATIONS=4 PROPOSALS_PER_ITER=2 bash scripts/e2e_sudoku.sh
NUM_TASKS=5 NUM_ITERATIONS=3 bash scripts/e2e_arc_agi.sh
TB_FORCE_BUILD=1 NUM_ITERATIONS=2 bash scripts/e2e_terminal_bench.sh
```

**Log everything.** Each script writes to `runs/e2e_logs/<family>_<ts>.log`
and the run-dir is `runs/<family>_<provider>_<model>_iter<x>_n<y>_<ts>/`.
Never redirect logs to stdout — piping through `tail -F | grep` in a
`Monitor` is the right pattern for long runs.

## 3. Run-dir shape

All four families produce an identical layout (because they all go through
`cli run`):

```
runs/<family>_<slug>_iter<x>_n<y>_<ts>/
  meta.json                       # config used
  iteration_log.json              # append-only per-candidate record
  leaderboard.json                # ranked by score_primary
  llm_calls/NNN_<stage>_<id>.md   # every proposer LLM call, full prompts
  candidates/
    H001/                         # seed
      harness.py scores.json summary.md traces/
    H002/                         # iter 1, parent=H001
      harness.py scores.json summary.md traces/ proposer_log.md
    ...
  harbor_jobs/                    # terminal_bench only — raw Harbor output
```

If you need to quote a concrete score or delta, read from
`iteration_log.json` — that's the canonical record. Candidate dirs can get
cleaned between runs; `iteration_log.json` is append-only.

## 4. Terminal-Bench specifics (read before any TB work)

TB is the odd one. Its "harness" is a Python module that exports an
`AgentHarness` class; Harbor loads it out of a Python 3.12 venv inside
`meta-harness/reference_examples/terminal_bench_2/` and runs each task
inside a Docker container. Three preconditions:

1. **Harbor workdir bootstrap** (one-time):
   ```bash
   git submodule update --init --recursive
   bash scripts/setup_terminal_bench_env.sh   # installs Python 3.12 + uv sync
   ```
   Check `meta-harness/reference_examples/terminal_bench_2/.venv/bin/harbor`
   exists after.

2. **Docker daemon reachable** (`docker ps` works, user is in the docker
   group or sudoer for docker commands).

3. **Image path** — either Docker Hub reachable (prebuilt image pull) or
   `TB_FORCE_BUILD=1` + a local `ubuntu:24.04` image (see §5).

When `cli run` evaluates a TB candidate it writes the candidate's source to
`<tb_workdir>/agents/candidate_<hid>.py`, derives the import path
`agents.candidate_<hid>:AgentHarness`, calls Harbor, then cleans the file
up. The canonical source stays in `<run_dir>/candidates/HNNN/harness.py`.

Seed = `harness_evolve/seeds/terminal_bench_baseline.py` — a 3-line module
that re-exports `agents.baseline_kira:AgentHarness`. Don't "improve" it by
copying KIRA source in; the proposer will generate subclasses on top.

## 5. The Docker Hub workaround (you will need this)

Symptom: first TB run hangs with `docker compose up --wait` for minutes,
then dies with:

```
Error Get "https://registry-1.docker.io/v2/": net/http: request canceled
  while waiting for connection (Client.Timeout exceeded while awaiting
  headers)
```

Root cause: the lab blocks Docker Hub outbound. Harbor is trying to pull
`alexgshaw/extract-elf:20251031` (or whichever prebuilt task image).

Fix:

```bash
# 1) Create a local ubuntu:24.04 from whatever mirror you do have.
#    In this lab, dockerhub.zjusct.io/library/ubuntu:22.04 is pre-pulled.
docker tag dockerhub.zjusct.io/library/ubuntu:22.04 ubuntu:24.04

# 2) Force Harbor to build the task Dockerfile locally instead of pulling
#    its prebuilt image. The task Dockerfile only needs apt to work
#    (nodejs, npm, gcc for extract-elf) — not Docker Hub.
TB_FORCE_BUILD=1 bash scripts/e2e_terminal_bench.sh
```

If apt inside the container is also blocked, you're stuck — there's no
fallback short of pre-baking a custom image. Report and stop; do not
silently return score=0.0 and claim success.

## 6. The `uv` download trap (will bite you silently)

TB's per-task `tests/test.sh` runs inside the container as the verifier.
Its first step is:

```bash
curl -LsSf https://astral.sh/uv/0.9.5/install.sh | sh
```

This can fail in three ways, all of which produce `reward=0.0`:

- **Fast SSL error** (~2 min): `curl: (56) OpenSSL SSL_read: unexpected eof`.
  The whole run completes in ~3 min with `n_errors: 0`, `reward: 0.0`. This
  looks like "the agent failed the task" — it is NOT. The verifier never
  ran pytest.
- **Slow throttled download** (~20 min): curl stays alive downloading the
  25 MB uv tarball at 10–100 KB/s. Then the 15-min verifier timeout kills
  it.
- **Successful install → pytest ran** (rare): only then is `reward` a
  signal about the agent.

**Never trust reward=0.0 on TB without checking** `<harbor_jobs>/<job>/
extract-elf__*/verifier/test-stdout.txt`. If the tail shows `downloading
uv 0.9.5` or `OpenSSL SSL_read: unexpected eof`, the reward is noise, not
signal. State this in your report to the user; do not report "evolution
didn't find an improvement".

## 7. Workflow

For any experiment request:

1. **Clarify** — which env pair, which iter count, which task family. Don't
   guess: a missed `TB_FORCE_BUILD=1` wastes 20 min.
2. **Smoke-verify credentials first** — one sync `llm_call` with
   `max_tokens=32` against each model before the long run. Takes 5 s,
   saves 20 min when the model name is wrong.
3. **Kick off via script, always in background**, log to
   `runs/e2e_logs/`:
   ```bash
   LOG=runs/e2e_logs/<family>_$(date +%Y%m%d_%H%M%S).log
   bash scripts/e2e_<family>.sh >"$LOG" 2>&1 &
   ```
4. **Monitor with `Monitor`, not polling** — grep for
   `Seed H|Candidate H|Iteration|e2e:|Traceback|ERROR|failed` so both
   progress and failure modes fire events.
5. **Don't stop a running container to "hurry things up"** — it looks like
   a shortcut, but it masks the true failure mode and destroys the
   evidence trail. Let timeouts fire naturally.
6. **Atomic commits, one concern per commit** — e.g. "task-family-aware
   validator" separate from "max_tokens bump" separate from "E2E scripts".
   Use PRs for multi-commit feature work.

## 8. Writing the result back to the user

When reporting:

- Quote concrete numbers from `iteration_log.json` / `leaderboard.json`,
  not from the terminal tail.
- Make clear whether `reward=0.0` is a *signal* or an *infra artifact*.
- Name the run dir so the user can `ls` it.
- Link the PR URL after `git push` + `gh pr create` (or the curl API
  call — see below).

## 9. Handy one-liners

```bash
# Kill a stuck harbor run cleanly (asks the user first)
docker ps --filter name=extract-elf --format '{{.Names}}' | xargs -r docker stop

# Delete transient candidate files after a crashed run (cleanup pollution)
rm -f meta-harness/reference_examples/terminal_bench_2/agents/candidate_h*.py

# Create a PR when `gh` isn't installed but a token is in ~/.git-credentials
TOKEN=$(awk -F'[:@]' '/github.com/ {print $3}' ~/.git-credentials | head -1)
curl -sH "Authorization: token $TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -X POST https://api.github.com/repos/<owner>/<repo>/pulls \
  -d @pr_payload.json
```

## 10. What NOT to do

- Do not run `harness_evolve.cli` directly in a REPL for "just a quick
  test" — the env-file layer won't be applied, so the model you think
  you're hitting isn't the one you're hitting.
- Do not edit `meta-harness/reference_examples/terminal_bench_2/` source.
  It's a git submodule; the repo contracts expect baseline_kira.py to be
  pristine. All evolution happens through proposer-generated files.
- Do not commit files under `runs/` (covered by `.gitignore`), the
  submodule's transient `agents/candidate_*.py`, or env files.
- Do not paper over a verifier-side infra failure by retrying with
  different seeds or models. Diagnose first.
