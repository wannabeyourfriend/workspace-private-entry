# Security Scanning Tools

## check_exposed_keys.py

Scans the workspace for exposed API keys and credentials that are **not** already defined in `.env` files.

### Features

- **Multi-pattern detection**: OpenAI, Anthropic, AWS, GitHub, Stripe, Google, private keys, and generic API keys
- **Smart filtering**: Automatically excludes values found in `.env`, `.env.local`, `.env.llmapi`, `.env.openai`
- **Binary file skipping**: Avoids scanning images, PDFs, and compiled files
- **Git-aware**: Skips `.git/`, `node_modules/`, `__pycache__/`, etc.
- **Masked output**: Sensitive values are masked in reports for security

### Usage

```bash
# Scan current directory
python3 scripts/check_exposed_keys.py

# Scan specific directory with verbose output
python3 scripts/check_exposed_keys.py --dir /path/to/scan -v

# Output as JSON for integration with other tools
python3 scripts/check_exposed_keys.py --json
```

### Exit Codes

- `0`: No exposed keys found
- `1`: Exposed keys detected (requires action)

### Patterns Detected

| Type | Pattern |
|------|---------|
| OpenAI API Key | `sk-*` (20+ chars) |
| OpenAI Org ID | `org-*` (20+ chars) |
| Anthropic API Key | `claude-*` (32+ chars) |
| AWS Access Key | `AKIA*` (16 chars) |
| AWS Secret Key | Full secret patterns |
| GitHub Token | `ghp_*` (36+ chars) |
| GitHub PAT | `github_pat_*` (22+ chars) |
| Stripe SK | `sk_live_*` |
| Stripe PK | `pk_live_*` |
| Google API Key | `AIza*` (39+ chars) |
| Private Keys | RSA/DSA/EC private key headers |
| Generic API Keys | `api_key`, `apiKey`, etc. |

### What Gets Excluded

1. **Values in .env files** — Legitimate env variables won't trigger alerts
2. **Binary files** — `.png`, `.jpg`, `.pdf`, `.zip`, etc.
3. **Common directories** — `.git/`, `node_modules/`, `__pycache__/`, `.venv/`, etc.
4. **Short values** — Keys less than 10 characters (too short to be real)

### Example Output

```
[*] Scanning /home/user/workspace
[*] Loaded 8 values from .env files to exclude
[*] Using 12 pattern detectors

[*] Scanned 1,234 files
[!] Found 2 files with potential exposed keys

======================================================================
SECURITY REPORT: EXPOSED API KEYS DETECTED
======================================================================

FILE: src/config.py
----------------------------------------------------------------------
  Line 42: [openai_api_key]
    Value: sk-proj-***********************ZXn (length: 48)
  Line 51: [generic_api_key]
    Value: Bearer *****************************2a8 (length: 64)

======================================================================
RECOMMENDATIONS:
  1. Move exposed keys to .env files
  2. Regenerate keys if committed to git
  3. Add patterns to .gitignore to prevent future leaks
======================================================================
```

### Remediation Steps

If exposed keys are found:

1. **Move to .env**:
   ```bash
   # Add to .env
   EXPOSED_KEY="value"
   
   # Remove from code and use: os.getenv('EXPOSED_KEY')
   ```

2. **Regenerate the key** on the provider (OpenAI, AWS, etc.) if it was committed to git

3. **Force-push** to remove from git history (⚠️ use carefully):
   ```bash
   git filter-branch --tree-filter 'rm -f exposed_file.py' HEAD
   git push origin --force
   ```

4. **Add to .gitignore**:
   ```
   # Env files
   .env*
   !.env.example
   
   # Secrets
   secrets/
   *.pem
   *.key
   ```

### Scheduled Scanning

Add to CI/CD or cron to run automatically:

```bash
# GitHub Actions example
name: Security Scan
on: [push, pull_request]
jobs:
  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - run: python3 scripts/check_exposed_keys.py
```

### Limitations

- Regex-based detection can have false positives/negatives
- Very long keys may be truncated during reading
- Some custom key formats may not be detected
- Performance degrades on very large directories (>50k files)

### Contributing

To add new patterns:

1. Edit the `PATTERNS` dict in `check_exposed_keys.py`
2. Use specific, tested regex patterns
3. Test against real examples (anonymized)
4. Update this README with the new pattern
