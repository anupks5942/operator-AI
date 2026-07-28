# Operator AI — Simple Overview (Hinglish)

Yeh project **SpyderWash / Setomatic Operator AI** hai — laundromat operators ke liye technical support chatbot. Operator machine/kiosk/card/refund ke baare mein poochta hai, agent answer deta hai: manuals se (RAG), live APIs se (balance/transactions), ya escalate karta hai support team ko (email/SMS).

---

## Architecture (kaise flow hota hai)

```
Operator UI → Agent API / Streamlit → LangGraph → (RAG / Tools / Escalation)
                                      ↓
                         ChromaDB (KB) + Setomatic APIs + Twilio/Mandrill
```

| Layer | Kaam |
|--------|------|
| **UI** | Streamlit (`app.py` demo), React (QA), .NET (prod) |
| **API** | FastAPI `:8000` — `POST /api/v1/agent/chat` |
| **Brain** | LangGraph — har message pehle **router** se jaata hai |
| **Memory** | `MemorySaver` — session/thread ke hisaab se (restart pe wipe) |
| **KB** | ChromaDB + FlashRank (manuals / Bible) |
| **Live data** | Setomatic APIs (loyalty, txn, kiosk, POS, remote reboot) |
| **Escalation** | Mandrill email + Twilio SMS (`USE_LIVE_NOTIFICATIONS`) |

**Rule:** LangGraph orchestrator hai — flow bypass mat karo.

---

## Routing (intent → node)

Har turn:

1. User message sanitize (PCI)
2. **`router`** → intent + entities extract
3. **`route_after_classifier()`** → sahi node pe bhejo
4. Node reply → **END**

**Priority (short):**

1. PCI / CVV block
2. Conversation summary
3. Outage mid-workflow (yes/no, blast radius)
4. Greeting / out-of-domain
5. Post-escalation follow-ups
6. Critical store-down → seedha escalate
7. Outage intents → blast-radius → troubleshoot → escalate
8. API intents → tools
9. Baaki → RAG

**3 main paths:**

| Path | Kab | Example |
|------|-----|---------|
| **RAG** | How-to, refund guide, technical support | “Printer kaise fix karu?” |
| **Tools** | Live data chahiye | “Card balance batao” |
| **Outage workflow** | Machine/store down | “Sab machines offline hain” |

Outage flow (Gregg style):

```
Blast radius? → One machine: troubleshoot first → fail? confirm → escalate
              → Entire location: seedha escalate (no troubleshoot)
```

**Important:** Refunds agent execute nahi karta — sirf portal guidance (Bible/RAG).

---

## Functions / Capabilities

- **KB Q&A** — manuals se troubleshooting
- **Loyalty / transactions** — balance, history, pagination (“show more”)
- **Kiosk / POS** — purchases, recharges, POS txns
- **Remote device** — reboot / dispense (confirmation ke saath)
- **System status** — Setomatic status page
- **Escalation** — ticket email/SMS, resolve, notes
- **Guardrails** — PCI block, out-of-domain refuse, hardware live-status refuse

---

## Important Files

```
src/
  agent/
    graph.py      → LangGraph: nodes, edges, outage + tools + escalate
    router.py     → Intent classifier + entity extraction
    nodes.py      → RAG, greeting, summary, PCI, out-of-domain
    tools.py      → Setomatic API tools (@tool)
    state.py      → AgentState (messages, flags, tickets, entities)
  api/
    server.py     → Production FastAPI (/api/v1/agent/chat)
    routes.py     → Legacy /query (extend mat karo)
  services/
    rag_service.py     → Chroma + FlashRank + KB ingest
    notifications.py   → Email/SMS escalation
  utils/security.py    → PCI mask / sanitize
  config.py            → .env settings
  llm.py               → OpenAI / Groq chat model

app.py                 → Streamlit demo UI
KB/                    → Manuals (v2.2 + Bible)
chroma_db/             → Vector store (local)
docs/ARCHITECTURE.md   → Full architecture detail (English)
```

---

## Ek line mein

Operator message aata hai → **router classify** karta hai → ya to **RAG** (docs), ya **tools** (live API), ya **outage workflow** (troubleshoot → escalate). Sab kuch LangGraph se controlled hai.
