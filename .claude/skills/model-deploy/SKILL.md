---
name: model-deploy
description: Deploy a trained SFT LoRA checkpoint (or base model) via vLLM on a free GPU. Use when the user asks to serve/deploy/run-vllm on a checkpoint in outputs/ or a model in hf_models/.
user-invocable: true
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash(nvidia-smi*)
  - Bash(lsof*)
  - Bash(kill*)
  - Bash(nohup*)
  - Bash(tail*)
  - Bash(grep*)
  - Bash(chmod*)
  - Bash(ls*)
  - Bash(cat*)
  - Bash(until*)
  - Bash(sleep*)
  - Bash(mkdir*)
  - Bash(python3*)
---

# /model-deploy — vLLM deployment for SFT checkpoints

Deploy `outputs/<run>/checkpoint-N` (LoRA adapter) or `hf_models/<base>` on a free GPU, following the conventions already proven in `scripts/serve_qwen25_7b_*.sh`.

## Defaults (do not deviate without reason)

- **vLLM binary**: `/home/2025user/zhou/anaconda3/envs/persona/bin/vllm`
- **Required env**: `export LD_LIBRARY_PATH=/home/2025user/zhou/anaconda3/envs/persona/lib:${LD_LIBRARY_PATH:-}` (fixes `GLIBCXX_3.4.29` PIL import error)
- **Base model root**: `/home/2025user/zhou/hf_models/`
- **Port map already in use**: 8001=no-state-us, 8002=us-profile-mar31, 8003=oracle-profile-only, 8004=base. Next free port = 8005+.
- **Logs**: `outputs/logs/serve_<name>.log`
- **Launch**: `nohup bash scripts/serve_<name>.sh > outputs/logs/serve_<name>.log 2>&1 &`

## Model-specific caps (known)

- **Qwen2.5-7B-Instruct**: `max_position_embeddings=32768` → `--max-model-len` ≤ 32768. 40960 will fail validation.
- **LoRA rank from our SFT recipe = 32** → must set `--max-lora-rank 32` (default is 16).

## Steps

### 1. Identify the checkpoint

Ask user (or infer from request):
- Checkpoint path (e.g. `outputs/<run>/checkpoint-50`) — if LoRA.
- Base model (read `adapter_config.json` → `base_model_name_or_path`) — if LoRA.
- Or just a base model under `hf_models/` — no LoRA.

### 2. Pick GPU + port

Run `nvidia-smi --query-compute-apps=pid,used_memory,gpu_uuid --format=csv,noheader` and:
- A GPU is "free enough" if **≥ 40 GiB free** (Qwen2.5-7B model + KV cache needs headroom).
- Check `lsof -ti :<port>` for port availability. Default next free port = 8005.

### 3. Write the script

Create `scripts/serve_<short_name>.sh`. Template for **LoRA checkpoint**:

```bash
#!/usr/bin/env bash
set -euo pipefail
PORT="${PORT:-<PORT>}"
export LD_LIBRARY_PATH=/home/2025user/zhou/anaconda3/envs/persona/lib:${LD_LIBRARY_PATH:-}
CUDA_VISIBLE_DEVICES=<GPU> /home/2025user/zhou/anaconda3/envs/persona/bin/vllm serve \
  <BASE_MODEL_ABS_PATH> \
  --port "$PORT" \
  --enable-lora \
  --lora-modules <short_name>=<CHECKPOINT_ABS_PATH> \
  --max-model-len <= model cap (e.g. 16384 or 32768) \
  --max-lora-rank 32 \
  --gpu-memory-utilization 0.75 \
  --max-num-seqs 128 \
  "$@"
```

For **base model only**, drop `--enable-lora`, `--lora-modules`, and `--max-lora-rank`; use `--gpu-memory-utilization 0.5` if the GPU is crowded.

Then `chmod +x scripts/serve_<short_name>.sh`.

### 4. Launch and poll

```bash
nohup bash scripts/serve_<short_name>.sh > outputs/logs/serve_<short_name>.log 2>&1 &
until grep -qE "Application startup complete|RuntimeError|Exception|ValueError" outputs/logs/serve_<short_name>.log; do sleep 5; done
tail -4 outputs/logs/serve_<short_name>.log
```

### 5. Report

Table: `| Port | Model served (lora name or base) | GPU | Context len |`.

## Failure recipes (seen in practice)

| Symptom in log | Fix |
|---|---|
| `GLIBCXX_3.4.29 not found` | Set `LD_LIBRARY_PATH` as above. |
| `LoRA rank 32 is greater than max_lora_rank 16` | Add `--max-lora-rank 32`. |
| `User-specified max_model_len (X) is greater than derived max_model_len (Y)` | Lower `--max-model-len` to ≤ Y (model's `max_position_embeddings`). |
| `CUDA out of memory ... warming up sampler with 256 dummy requests` | Add `--max-num-seqs 128` (or 64). |
| `Free memory on device cuda:0 (X GiB) ... less than desired GPU memory utilization` | Lower `--gpu-memory-utilization` so `util * 80 GiB` < free. |
| Old EngineCore holds memory after main process died | `nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader` → `kill` the orphaned PID. |

## Never

- Do **not** re-download base models; always use absolute paths under `hf_models/`.
- Do **not** delete checkpoints or `outputs/` without explicit user approval.
- Do **not** skip committing the new `scripts/serve_*.sh` — tell the user to commit after verifying the server is healthy.
