# QA adapter — example (`<your-repo>/.claude/qa.md`)

Read by the `qa` skill and parsed by `qa_preflight.py`. The format of `forbidden_env`
items (one line, double quotes, in this key order) and the `allowed:` line right after
`local:` are what the parser expects — keep them. Full schema:
`skills/qa/references/bootstrap.md`.

```yaml
project: my-app
extends: .claude/orchestrator.md
environments:
  local:
    allowed: false
    why: ".env points at the production database"
  staging:
    url: https://staging.example.com
    credentials: "password manager, item 'my-app staging'"
    rate_limits: "the payments sandbox allows 10 req/s; 429 above that is environment"
    mutation_allowed: "only records whose name starts with qa-"
  production: read_zero
forbidden_env:
  - {file: ".env", grep_pattern: "prod-db\\.example\\.com|sslmode=require", why: "production database"}
probe:
  allowed: true
  safe_env: ".env.qa"
  import_rule_grep: "createApp\\(|AppModule"
  teardown: "rm .qa/probes/* and drop every qa_* database"
filtered_output: "npm test -- --run --reporter=dot"
regression_suite_allowed: false
external_oracles: ["../my-app-mobile (API consumer)", "docs/openapi.yaml"]
risk_profile: ["time zones in scheduling", "double charge on retry", "permissions per role"]
data: {seed: "npm run seed:qa", reset: "npm run reset:qa"}
browser: {route: inline, base_url: "http://localhost:5173", login_as: "qa user from the password manager", flags: "VITE_ENABLE_MSW=true"}
```
