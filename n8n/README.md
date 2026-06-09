# n8n Orchestration Workflows

Declarative workflow exports for the orchestration layer. These are committed as
JSON artifacts — **no n8n instance is bundled** (the project's non-goals exclude
Docker / hosted deployment). Import them into any self-hosted n8n to wire
scheduled re-crawls, engagement alerts, and failure recovery on top of the
LangGraph agent.

## Workflows

| File | Trigger | Action |
|---|---|---|
| `scheduled_recrawl.json` | Cron (`N8N_RECRAWL_CRON`, default every 6h) | `POST {AGENT_API_BASE_URL}/api/agent/run` |
| `engagement_alert.json` | Webhook `POST /webhook/engagement_alert` (fired by the LangGraph `alert` node) | Slack notification with item id + score |
| `failure_recovery.json` | Webhook `POST /webhook/failure_recovery` (fired when `retry_count >= MAX_RETRIES`) | Append to dead-letter store + notify on-call |

## Import (fresh instance)

1. Open n8n → **Workflows → Import from File**.
2. Import each JSON in this directory. They are named with an `[orchestration]`
   prefix for easy filtering.
3. Workflows ship `active: false` — review, then toggle Active per workflow.

## Credentials & secrets

Secrets are **never** stored in these JSONs. Each Slack node references a
credential by name (`Slack account`) with a placeholder id
(`REPLACE_WITH_CREDENTIAL_ID`). Before activating:

1. Create the **Slack API** credential in n8n (Settings → Credentials).
2. Re-select it on each Slack node so n8n binds the real credential id.

## Environment variables (set on the n8n instance)

| Var | Used by | Notes |
|---|---|---|
| `N8N_RECRAWL_CRON` | scheduled_recrawl | cron expression, e.g. `0 */6 * * *` |
| `AGENT_API_BASE_URL` | scheduled_recrawl | base URL of the Flask agent API |
| `RECRAWL_TOPIC` | scheduled_recrawl | topic to re-crawl |
| `RECRAWL_SOURCES` | scheduled_recrawl | comma list, e.g. `reddit,hn` |
| `SLACK_ALERT_CHANNEL` | engagement_alert | channel id for engagement alerts |
| `SLACK_ONCALL_CHANNEL` | failure_recovery | channel id for on-call |
| `DEAD_LETTER_URL` | failure_recovery | endpoint that records failed runs |

## Local Docker note

If running n8n in Docker locally, the agent API on the host is reachable from the
n8n container at `http://host.docker.internal:<port>`, not `localhost`. Set
`AGENT_API_BASE_URL` accordingly.
