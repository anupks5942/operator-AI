# Environment Configuration

All configuration is loaded from `.env` at the repo root via [src/config.py](../src/config.py).

Copy [`.env.example`](../.env.example) to `.env` and fill in values. **Never commit `.env`** — it is gitignored.

---

## Quick start (minimum)

```env
OPENAI_API_KEY=sk-...
```

Required for router, tool-calling, and RAG (all use OpenAI models by default).

`OPENAI_API_KEY` is **not** declared in [config.py](../src/config.py) — LangChain reads it from the process environment after `load_dotenv()` runs in [server.py](../src/api/server.py) and [app.py](../app.py).

---

## LLM and models

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENAI_API_KEY` | (none) | **Required** — OpenAI API access |
| `OPENAI_MODEL` | `gpt-4o-mini` | Default model for all nodes |
| `ROUTER_OPENAI_MODEL` | same as `OPENAI_MODEL` | Semantic router |
| `TOOL_OPENAI_MODEL` | same as `OPENAI_MODEL` | Tool-calling ReAct loop |
| `RAG_OPENAI_MODEL` | same as `OPENAI_MODEL` | RAG answer generation |

Example override:

```env
OPENAI_MODEL=gpt-4o-mini
ROUTER_OPENAI_MODEL=gpt-4o-mini
```

---

## Setomatic API URLs

| Variable | Default | Purpose |
|----------|---------|---------|
| `SETOMATIC_BASE_URL` | `https://betasetomaticposwebapplication.spyderwash.com` | Live loyalty, transactions, refunds (when mock off) |
| `MOCK_BASE_URL` | `http://localhost:8001` | Local mock server |
| `USE_MOCK_REFUNDS` | `true` | `true` = refund tools use mock; `false` = live Setomatic |

Local refund development:

```env
USE_MOCK_REFUNDS=true
MOCK_BASE_URL=http://localhost:8001
```

UAT/production refunds:

```env
USE_MOCK_REFUNDS=false
SETOMATIC_BASE_URL=https://betasetomaticposwebapplication.spyderwash.com
```

---

## Escalation notifications

| Variable | Default | Purpose |
|----------|---------|---------|
| `USE_LIVE_NOTIFICATIONS` | `false` | `true` = send real email/SMS; `false` = log only |
| `ESCALATION_EMAIL` | `support@setomaticsystems.com` | Recipient for escalation HTML email |
| `ESCALATION_SMS_TO` | (empty) | Twilio destination for on-call SMS |

### Twilio (SMS)

| Variable | Purpose |
|----------|---------|
| `TWILIO_ACCOUNT_SID` | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Twilio auth token |
| `TWILIO_FROM_NUMBER` | Sender phone number (E.164) |

### Mandrill / SMTP (email)

| Variable | Default | Purpose |
|----------|---------|---------|
| `SMTP_HOST` | `smtp.mandrillapp.com` | SMTP server |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USERNAME` | (empty) | Mandrill SMTP username |
| `SMTP_PASSWORD` | (empty) | Mandrill SMTP password / API key |
| `FROM_EMAIL` | `support@spyderwash.com` | From address on escalation emails |

### Local dev (mock notifications)

```env
USE_LIVE_NOTIFICATIONS=false
```

Escalation still runs in the graph; output appears in console logs.

### Live test (personal recipients)

```env
USE_LIVE_NOTIFICATIONS=true
ESCALATION_EMAIL=you@example.com
ESCALATION_SMS_TO=+15551234567
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_FROM_NUMBER=+1...
SMTP_USERNAME=...
SMTP_PASSWORD=...
```

Revert to client addresses before client demo — see [RUNBOOK.md](RUNBOOK.md).

---

## Boolean parsing

These accept `true`/`1`/`yes` vs `false`/`0`/`no` (case insensitive):

- `USE_MOCK_REFUNDS`
- `USE_LIVE_NOTIFICATIONS`

---

## Production secrets

In production (Phase 3):

- Store secrets in a managed vault (Azure Key Vault, etc.)
- Inject via environment at deploy time
- Do not copy production `.env` into the repo

---

## Related documents

- [`.env.example`](../.env.example) — copy-paste template
- [RUNBOOK.md](RUNBOOK.md) — operational procedures
- [TECH_STACK.md](TECH_STACK.md) — stack overview
