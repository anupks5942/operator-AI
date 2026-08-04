# Operator AI — Detailed Overview (Hinglish)

Yeh project **SpyderWash / Setomatic Operator AI** hai — laundromat operators ke liye LangGraph-based technical support agent.

Operator chat mein problem batata hai. Agent teen tarike se help karta hai:

1. **RAG** — manuals / Bible se step-by-step answer
2. **Live tools** — Setomatic APIs se balance, transactions, kiosk/POS data
3. **Escalation** — agar fix nahi hua to Email + SMS se support team ko ticket

**Refunds:** agent khud refund nahi karta. Sirf portal pe kaise karna hai, woh guide karta hai (Bible/RAG).

**Consumers:** Streamlit (dev demo), React (QA), .NET Super Admin (production). Sab production path mein FastAPI `:8000` use karte hain.

---

## 1. Architecture — poora system kaise juda hai

```
┌─────────────┐  ┌──────────┐  ┌─────────────────┐
│ Streamlit   │  │ React QA │  │ .NET Super Admin│
│ app.py      │  │          │  │ (production)    │
└──────┬──────┘  └────┬─────┘  └────────┬────────┘
       │ in-process   │                 │
       │              └────────┬────────┘
       │                       │ HTTP
       ▼                       ▼
┌──────────────────────────────────────────┐
│ FastAPI  src/api/server.py  :8000        │
│ POST /api/v1/agent/chat                  │
│ GET  /health                             │
└──────────────────┬───────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│ LangGraph agent_app  (src/agent/graph.py)│
│ Entry: router → conditional edge → node  │
│ Memory: MemorySaver (session_id/thread)  │
└─────┬──────────────┬──────────────┬──────┘
      │              │              │
      ▼              ▼              ▼
 Qdrant+FlashRank   Setomatic APIs  Mandrill+Twilio
 (KB manuals)        (live data)     (escalation)
```

| Layer | File / component | Simple meaning |
|--------|------------------|----------------|
| Demo UI | `app.py` | Local Streamlit chat + routing diagnostics sidebar |
| Prod API | `src/api/server.py` | Real chat endpoint; session → LangGraph thread |
| Orchestrator | `src/agent/graph.py` | Har turn ka master flowchart |
| Intent brain | `src/agent/router.py` | Message padh ke intent + entities nikalta hai |
| Answers / static replies | `src/agent/nodes.py` | RAG, greeting, summary, PCI, out-of-domain |
| Live API tools | `src/agent/tools.py` | Balance, txn, kiosk, POS, remote command |
| Conversation memory shape | `src/agent/state.py` | Messages, flags, tickets, entities |
| Knowledge base | `src/services/rag_service.py` | Docs ingest + retrieve + rerank |
| Notifications | `src/services/notifications.py` | Escalation email/SMS |
| Security | `src/utils/security.py` | Card mask, sanitize in/out |
| Config | `src/config.py` | Saari env vars yahi se |
| LLM factory | `src/llm.py` | Groq (default) ya OpenAI |

**Hard rule:** LangGraph orchestrator hai. Chat flow ko graph se bahar mat le jao.

**Memory catch:** `MemorySaver` process ke andar hai. Server restart / multiple replicas pe memory share nahi hoti. Production durable memory baad ka phase hai.

---

## 2. Ek turn ka life-cycle (step by step)

```
1. User message aata hai (API ya Streamlit)
2. sanitize_user_text()  → card numbers mask, dirty text clean
3. CVV/track data check  → mil gaya to seedha PCI guardrail (LLM tak nahi jaata)
4. semantic_router()     → intent + flags + entities
5. route_after_classifier() → kaunsa node chalega
6. Node reply generate   → RAG / tools / outage / static
7. END                   → response UI ko wapas
```

Har turn mein usually: **router → ek downstream node → END**.  
Outage mid-flow mein multi-turn sticky state rehti hai (`blast_radius`, `troubleshooting_failed`, tickets, etc.).

---

## 3. Routing — intents, flags, priority

### 3.1 Router kya return karta hai

`IntentClassification` (`router.py`) roughly ye fields deta hai:

| Field | Matlab |
|--------|--------|
| `intent` | Message ka type (greeting, machine_down, loyalty_balance_query, …) |
| `api_action_required` | True → tool_node (live API) |
| `escalation_required` | Critical / human escalate signal |
| `hardware_lookup_attempted` | Live machine status maanga → guardrail |
| `extracted_entities` | card_number, blast_radius, dates, device_id, … |

Entities `merge_dicts` se merge hoti hain — turn-2 pe card number wipe nahi hota.

### 3.2 Intent list (router ke allowed values)

| Intent | Typically kahan jaata hai | Example |
|--------|---------------------------|---------|
| `greeting` | greeting_node | “Hi”, “Thanks” |
| `conversation_summary` | summarize_node | “Recap de do” |
| `general_query` | RAG | “Portal login kaise?” |
| `technical_support` | RAG | “Printer jam ho gaya” |
| `refund_request` | RAG (portal guide only) | “Customer refund kaise?” |
| `kiosk_not_responding` | RAG | “Kiosk dead hai” |
| `loyalty_balance_query` | tools | “Card balance?” |
| `transaction_lookup` | tools | “Last 5 transactions” |
| `system_status_check` | tools | “Setomatic down hai kya?” |
| `kiosk_purchase_lookup` | tools | “Kiosk purchases dikhao” |
| `kiosk_recharge_lookup` | tools | “Reload history” |
| `pos_transaction_lookup` | tools | “POS sales” |
| `remote_device_action` | tools | “Kiosk reboot karo” |
| `report_lookup` | tools | Reports |
| `machine_down` | Outage workflow | “Washer 3 down” |
| `machines_not_starting` | Outage workflow | “Machines start nahi ho rahi” |
| `multiple_machines_offline` | Outage workflow | “Kai readers offline” |
| `emergency_store_down` | Outage / escalate | “Poora store down” |
| `critical_outage` | Immediate escalate | Store-level critical |
| `escalation_request` | Clarify first (ADR-031) | “Human se baat karni hai” — seedha SMS blast nahi |
| `hardware_status` | guardrail | “Abhi machine online hai?” (live status refuse) |
| `out_of_domain` | static refuse | Cricket score, jailbreak, etc. |

### 3.3 `route_after_classifier` priority (order matter karta hai)

Priority roughly yeh hai (upar wala pehle jeetta hai):

1. **PCI** → `pci_guardrail_node`
2. **conversation_summary** → summary (outage state reset nahi)
3. Escalation confirmation gate (operator ne escalate yes/no bola)
4. Ticket resolve disambiguation
5. Mid-workflow gibberish → `workflow_reminder_node` (Yes/No dubara poochho)
6. Greeting / out-of-domain
7. Hardware live lookup → guardrail
8. Post-escalation follow-ups (resolve / new issue / ticket notes / RAG how-to)
9. Critical outage → immediate escalate
10. Outage workflow intents → blast → troubleshoot → confirm → escalate
11. `api_action_required` → `tool_node`
12. Default → `rag_agent`

### 3.4 Teen main paths detail mein

#### A) RAG path

- Intents: `general_query`, `technical_support`, `refund_request`, `kiosk_not_responding`, …
- `api_action_required` **hamesha false** in intents pe (refund/kiosk/technical ko tools pe mat bhejo)
- Flow: query → Qdrant retrieve → FlashRank rerank → LLM answer
- Kabhi “Did this resolve?” add hota hai (sirf jab troubleshooting markers hon)

#### B) Tools path (ReAct loop)

- Intents: loyalty, transactions, kiosk/POS, remote device, system status, reports
- `tool_node` max ~6 iterations
- Har `AIMessage` with `tool_calls` ke baad `ToolMessage` zaroori
- “Show more” → router regex se pehle se API intent pe stick → `page_no++`

#### C) Outage / escalation path (Gregg workflow)

Outage intents set:

- `emergency_store_down`
- `machine_down`
- `machines_not_starting`
- `multiple_machines_offline`

Flow:

```
Operator: "Machines down"
    → blast_radius_check
         ├─ entire_location  → seedha escalate (troubleshoot skip)
         └─ single_machine
              → (optional) clarify_issue agar bahut vague
              → troubleshoot_first  (KB steps + Did this resolve?)
                   ├─ yes → troubleshoot_success
                   └─ no  → confirm_escalation
                              ├─ yes → escalation_node (email/SMS)
                              └─ no  → escalation_declined (direct contact)
```

`escalation_request` is set mein **nahi** hai — pehle clarify, phir escalate. Alert fatigue kam karne ke liye single-machine pe permission maangte hain.

---

## 4. Graph nodes — kaun kya karta hai

| Node | File | Kaam |
|------|------|------|
| `router` | router.py | Intent + entities |
| `greeting_node` | nodes.py | Hi / thanks / bye — no RAG |
| `summarize_node` | nodes.py | Chat recap + tickets list |
| `workflow_reminder_node` | nodes.py | Mid-outage pe Yes/No reminder |
| `guardrail_node` | nodes.py | Live hardware status refuse |
| `pci_guardrail_node` | nodes.py | CVV/track data static block |
| `out_of_domain_node` | nodes.py | Off-topic static refuse |
| `blast_radius_check` | graph.py | One machine vs entire store |
| `clarify_issue` | graph.py | Vague outage pe details maango |
| `troubleshoot_first` | graph.py | KB steps + resolve check |
| `troubleshoot_success` | graph.py | Fix ho gaya — ack |
| `confirm_escalation` | graph.py | Single-machine pe permission |
| `escalation_declined` | graph.py | Decline pe direct contact info |
| `escalation_node` | graph.py | Ticket + email/SMS dispatch |
| `escalation_resolved` | graph.py | Ticket resolve + threaded email |
| `post_escalation_ack` | graph.py | Ticket ke baad short ack |
| `new_issue_after_escalation` | graph.py | Nayi problem → naya blast cycle |
| `tool_node` | graph.py | ReAct + Setomatic tools |
| `rag_agent` | nodes.py | Normal KB Q&A |

---

## 5. Functions / capabilities (operator view)

### Knowledge (RAG)

- KB sources: **v2.2 articles** + **Setomatic Bible** (selective sections)
- Retrieve: MMR → FlashRank top 6 → co-retrieval companion articles
- Short follow-ups (“haan”, “uska”) pehle wale article context se expand hote hain

### Live Setomatic tools

| Tool | Kya karta hai |
|------|----------------|
| `get_loyalty_balance` | Card balance |
| `get_transaction_history` | History; count, refunds filter, date range; default ~6 months |
| `get_kiosk_purchases` | Kiosk purchase list (date range) |
| `get_kiosk_recharges` | Reload/recharge history |
| `get_pos_transactions` | POS txns (filters + card last-4 safety) |
| `send_remote_device_command` | Reboot / Dispense (2-step confirm) |
| `check_global_system_status` | Setomatic status page scrape |

Pagination: default **5 records/page**. Footer mein “show more”. Transaction IDs operator screen pe hide, andar refund flow ke liye rakhe ja sakte hain.

### Escalation / tickets

- Ticket ID jaise `TKT-…`
- Mandrill email + Twilio SMS jab `USE_LIVE_NOTIFICATIONS=true` (warna mock/log)
- Open tickets, session history, resolve emails, ticket notes, callback number — sab state mein

### Guardrails

- PCI: CVV/CVC/track data pehle block
- Out-of-domain: hardcoded refuse (LLM pe mat chhodna)
- Domain keyword safety net: printer/portal/network jaise terms pe false `out_of_domain` override
- Live hardware status: intentionally refuse

---

## 6. State — session mein kya yaad rehta hai

`AgentState` (`state.py`) ke important pieces:

| Field | Role |
|--------|------|
| `messages` | Poori chat (append) |
| `current_intent` | Last classified intent |
| `api_action_required` / `escalation_required` | Routing flags |
| `blast_radius` | `single_machine` / `entire_location` |
| `troubleshooting_failed` | Outage resolve check ka result |
| `extracted_entities` | Card, dates, device_id, … (merge across turns) |
| `escalation_dispatched` | Ticket already gaya? |
| `dispatched_tickets` | Open tickets |
| `all_session_tickets` | Session history (summary ke liye) |
| `ticket_email_ids` | Threaded resolve replies |
| `last_ticket_summary` / `last_ticket_blast_radius` | Dedup |
| `ticket_notes` / `callback_number` | Post-ticket operator updates |
| `operator_*` | Frontend se aaya contact info |

---

## 7. Important files — folder map

```
operator-AI/
├── app.py                 # Streamlit demo UI
├── KB/                    # Active manuals (v2.2 + Bible)
├── spyderwash_qdrant/     # Local vector DB (gitignore; first run pe banta hai)
├── tests/
│   ├── test_outage_workflow.py
│   └── test_security.py
├── docs/
│   ├── ARCHITECTURE.md            # English system design
│   ├── ESCALATION_WORKFLOW.md     # Outage detail
│   ├── INTENT_MATRIX.md           # Business intents mapping
│   ├── SETOMATIC_BACKEND_APIS.md  # API scope
│   ├── DECISIONS.md               # ADRs
│   └── PROJECT_OVERVIEW_HINGLISH.md  # Yeh file
└── src/
    ├── config.py
    ├── llm.py
    ├── agent/
    │   ├── graph.py       # Nodes + edges + escalate/tools orchestration
    │   ├── router.py      # Intent classifier
    │   ├── nodes.py       # RAG + static nodes
    │   ├── tools.py       # Live API @tools
    │   └── state.py       # AgentState TypedDict
    ├── api/
    │   ├── server.py      # Production FastAPI  ★ use this
    │   ├── routes.py      # Legacy /query       ✗ don't extend
    │   └── schemas.py
    ├── services/
    │   ├── rag_service.py
    │   └── notifications.py
    └── utils/
        └── security.py
```

### Commands (quick)

```bash
uv sync
uv run uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload
uv run streamlit run app.py
uv run python -m unittest tests.test_outage_workflow tests.test_security -v
```

---

## 8. Example conversations (flow samajhne ke liye)

**RAG**

```
User: Printer paper jam kaise clear karu?
→ router: technical_support / general_query
→ rag_agent → KB steps
→ (kabhi) "Did this resolve?"
```

**Tools**

```
User: Card LC-1234 ka balance?
→ router: loyalty_balance_query, api_action_required=true
→ tool_node → get_loyalty_balance → reply

User: show more
→ router sticky on same API intent → next page
```

**Outage**

```
User: Sab machines offline hain
→ blast_radius = entire_location
→ escalation_node (troubleshoot skip)

User: Washer 2 start nahi ho rahi
→ blast → single_machine
→ KB troubleshoot
→ User: no
→ "Escalate karun?"
→ yes → ticket email/SMS
```

**Refund**

```
User: Customer ko refund kaise dun?
→ refund_request → RAG portal guidance
→ koi refund API execute nahi
```

---

## 9. Ek line mein

Operator message → **sanitize + router** → sahi lane:

- **RAG** = docs se sikhao  
- **Tools** = live Setomatic data lao  
- **Outage workflow** = pehle troubleshoot, phir escalate  

Sab control **LangGraph** (`graph.py`) ke haath mein hai.

Aur detail chahiye ho to English sources: `docs/ARCHITECTURE.md`, `docs/ESCALATION_WORKFLOW.md`, `docs/INTENT_MATRIX.md`.
