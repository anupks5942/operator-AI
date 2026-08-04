# KT Guide — Teammate ko kaise samjhao (Hinglish)

Yeh file **tumhare liye speaker notes** hai.  
Teammate ko yeh padhne ko mat do pehle — **tum bolo, demo dikhao**, phir `PROJECT_OVERVIEW_HINGLISH.md` de dena handout ke liye.

**Suggested time:** 60–75 min  
**Audience:** naya backend / AI teammate  
**Goal:** wo khud flow follow kar sake — kahan change karna hai, kahan nahi

---

## KT se pehle (5 min prep)

1. Repo clone + `uv sync` already done ho
2. `.env` ready (LLM key, Setomatic URL agar tools dikhane hain)
3. Terminal ready:
   ```bash
   uv run streamlit run app.py
   ```
4. Sidebar mein routing diagnostics ON / visible (Streamlit pe)
5. Ye 4 demo prompts ready rakho (neeche Section D)

**Handouts after KT:**
- `docs/PROJECT_OVERVIEW_HINGLISH.md` — detail
- `docs/ARCHITECTURE.md` — English deep dive
- `AGENTS.md` — coding rules (must read)

---

## KT agenda (bolo exactly ye order)

| # | Block | Time | Kya cover |
|---|--------|------|-----------|
| 0 | Context | 5 min | Product kya hai, kiske liye hai |
| 1 | Big picture | 10 min | UI → API → LangGraph → RAG/Tools/Escalate |
| 2 | Live demo | 20 min | 4 real chats + routing sidebar |
| 3 | Code walk | 20 min | Sirf 5 files open karke |
| 4 | Rules / gotchas | 10 min | Mat todna wali cheezein |
| 5 | Q&A + next tasks | 10 min | Unka first PR area |

**Galat order:** pehle tools.py / router prompts kholna. Pehle picture, phir demo, phir code.

---

## Block 0 — Opening pitch (exact words style)

Bolo:

> SpyderWash operators laundromat chaláte hain. Unko support chahiye — machine down, card balance, kiosk, refund kaise karein.  
> Yeh AI agent unka first-line support hai.  
> Teen kaam karta hai:  
> 1) Manuals se answer (RAG)  
> 2) Live Setomatic data (tools)  
> 3) Fix na ho to Email/SMS escalate  
> Refund **execute** nahi karta — sirf portal guide karta hai.  
> Production UI .NET hai, chat backend yeh Python LangGraph service hai.

Phir ek line:

> Sab conversation **LangGraph** se hoti hai. Router decide karta hai kaunsa lane — RAG, tools, ya outage workflow.

---

## Block 1 — Whiteboard / diagram (10 min)

Board pe yeh draw karo (ya screen pe):

```
Operator
   │
   ▼
UI (.NET / React / Streamlit)
   │
   ▼
FastAPI  :8000   POST /api/v1/agent/chat
   │
   ▼
┌──────────── LangGraph ────────────┐
│  router  →  sahi node             │
│     │                             │
│     ├─ RAG        (manuals)       │
│     ├─ tools      (Setomatic API) │
│     └─ outage     (troubleshoot → escalate) │
└───────────────────────────────────┘
         │            │            │
         ▼            ▼            ▼
     Qdrant      Setomatic     Mandrill/Twilio
```

**3 sentences jo zaroor bolni hain:**

1. **Router = traffic police** — intent classify + entities (card, blast radius, dates).
2. **Graph = road map** — `route_after_classifier` decide karta hai next node.
3. **State = memory** — session ke tickets, blast_radius, entities yahi rehte hain (`MemorySaver`).

**Mat ghumao abhi:** FlashRank, MMR numbers, ADR numbers — baad mein.

---

## Block 2 — Live demo (sabse important)

Streamlit chalao. Har demo ke baad sidebar / routing diagnostics dikhao: **intent + flags**.

### Demo 1 — RAG (2 min)

**Type:** `Printer paper jam kaise clear karu?`

**Samjhao:**
- Intent ~ `technical_support` / `general_query`
- `api_action_required = false`
- Answer KB se aaya — koi Setomatic API nahi

### Demo 2 — Tools (3 min)

**Type:** `Card <valid-test-card> ka balance batao`  
(ya jo bhi test card tumhare env mein chalta hai)

**Samjhao:**
- Intent `loyalty_balance_query`
- `api_action_required = true`
- `tool_node` → live API
- Agar “show more” flow hai transactions pe, ek baar dikha do

### Demo 3 — Outage single machine (5 min)

**Type:** `Washer 2 start nahi ho rahi`

**Expect flow:**
1. Blast radius poochhega (one vs entire)
2. Bolo: `just one machine`
3. Troubleshooting steps dega + “Did this resolve?”
4. Bolo: `no`
5. Escalation confirm poochhega
6. Bolo: `yes` → ticket path (mock notifications agar live off hai)

**Samjhao:**
> Poora store down pe seedha escalate. Ek machine pe pehle troubleshoot, phir permission, phir ticket. Alert fatigue kam karne ke liye.

### Demo 4 — Guardrail / refund (3 min)

**Refund:** `Customer ko refund kaise dun?`  
→ RAG portal guidance, **no refund API execute**

**Optional PCI:** mat real CVV daalna — bas bolo:
> CVV/track data aaye to LLM pe jaane se pehle block.

**Optional OOD:** `Aaj ka cricket score?` → static refuse

---

## Block 3 — Code walk (sirf 5 files)

IDE mein **is order** se kholo. Har file pe 2–3 min.

### 1) `src/agent/state.py` (2 min)

Bolo:
> Yeh conversation ka shape hai — messages, intent flags, tickets, entities.  
> `merge_dicts` isliye hai taaki turn-2 pe card number wipe na ho.

### 2) `src/agent/router.py` (5 min)

Dikhao:
- `IntentClassification` model (intent list)
- `semantic_router` function
- Safety nets: domain keywords, show-more heuristic

Bolo:
> Naya intent add karna ho to yahan + graph edge map — dono jagah.

### 3) `src/agent/graph.py` (7 min)

Dikhao:
- `_ESCALATION_WORKFLOW_INTENTS`
- `route_after_classifier` (priority order samjhao upar se neeche)
- `tool_node` / `escalation_node` names

Bolo:
> Yeh file master flowchart hai. Bug “galat node pe chala gaya” → pehle yahan dekho.

### 4) `src/agent/nodes.py` + `tools.py` (5 min)

- `nodes.py` = RAG + greeting + PCI + OOD
- `tools.py` = Setomatic `@tool` functions

Bolo:
> RAG intents tools pe mat bhejo. Refund tools exist nahi karte by design.

### 5) `src/api/server.py` (3 min)

Bolo:
> Production entry: `POST /api/v1/agent/chat` (`server.py`).  
> Streamlit demo `app.py` se in-process graph call karta hai.

**Bonus agar time ho:** `src/services/rag_service.py` — “KB ingest yahan, uv run python -m data_injection se reingest”.

---

## Block 4 — Rules / gotchas (KT ka asli value)

Teammate ko **clear list** do — screenshot / copy:

### Always

1. Flow LangGraph se hi — bypass mat karo
2. Naya intent = `router.py` + `graph.py` edge map
3. Tool node ReAct loop — tool_calls ke baad ToolMessage zaroori
4. User text pehle sanitize; outbound escalation pe bhi sanitize
5. Config sirf `src/config.py` / `.env` se

### Never / careful

1. `refund_request` / `technical_support` / `kiosk_not_responding` pe `api_action_required=true` mat set karo
2. `escalation_request` ko outage SMS blast jaisa treat mat karo (pehle clarify)
3. Entire location pe troubleshoot skip — by design
4. `routes.py` `/query` extend mat karo
5. PCI responses LLM se mat generate karo — static
6. Secrets `.env` commit mat karna

### Common bugs teammate hit karega

| Symptom | Pehle kahan dekho |
|---------|-------------------|
| Galat lane (RAG vs tools) | `router.py` intent + flags |
| Outage mid-flow toot gaya | `graph.py` sticky gates + state flags |
| Card turn-2 pe gayab | `extracted_entities` / `merge_dicts` |
| KB purana answer | Run: `uv run python -m data_injection` |
| Escalation nahi gaya | `USE_LIVE_NOTIFICATIONS` + notifications.py |

---

## Block 5 — Closing — unko kya karna hai next

Bolo:

> Pehle `AGENTS.md` + `PROJECT_OVERVIEW_HINGLISH.md` padh.  
> Phir Streamlit pe 4 demos khud repeat kar.  
> Pehla safe task: docs typo / test case / chhota RAG prompt tweak — graph rewrite se mat shuru kar.

**Suggested first tasks (pick one):**
- Ek failing / missing unittest padh ke samjho
- Intent matrix row → router intent mapping verify (`docs/INTENT_MATRIX.md`)
- Streamlit sidebar mein ek routing field samajh ke explain karo wapas tumhe

**Docs map unke liye:**

| Agar yeh karna hai | Yeh padho |
|--------------------|-----------|
| Overall system | `ARCHITECTURE.md` |
| Outage tickets | `ESCALATION_WORKFLOW.md` |
| Intent business mapping | `INTENT_MATRIX.md` |
| APIs | `SETOMATIC_BACKEND_APIS.md` |
| Env vars | `ENVIRONMENT.md` |
| Coding rules | `AGENTS.md` |
| Hinglish recap | `PROJECT_OVERVIEW_HINGLISH.md` |

---

## Tumhare liye — short “cheat script” (agar time kam ho, 25 min version)

1. **2 min:** Product + 3 lanes (RAG / tools / escalate)  
2. **5 min:** Diagram draw  
3. **10 min:** Demo 1 + 3 only (RAG + outage)  
4. **5 min:** `router.py` → `graph.py` → `server.py`  
5. **3 min:** Never-do list + handout files  

---

## KT ke baad checklist (teammate se poochho)

Agar yeh 5 jawab de sake — KT successful:

1. Message pehle kaunse node se guzarta hai? → **router**
2. Balance query kahan jaati hai? → **tool_node / Setomatic**
3. Poora store down pe pehle troubleshoot? → **Nahi, seedha escalate**
4. Refund agent execute karta hai? → **Nahi, portal guide**
5. Naya intent kahan add hota hai? → **router + graph edges**

---

## Extra tips (tumhari delivery)

- Teammate ko beech mein **khud type** karne do ek prompt — passive listening se KT fail hota hai.
- Jargon pehle Hindi/Hinglish, phir English term: “traffic police = router”.
- ADR / Phase-2 roadmap pe mat atakna pehli KT mein.
- Agar wo frontend hai: API contract (`docs/API.md`) zyada, `tools.py` kam.
- Agar wo backend/AI hai: `graph.py` + outage sticky state zyada.

**Handout combo after call:**
1. Yeh file (tumhari notes — optional unko)
2. `PROJECT_OVERVIEW_HINGLISH.md` (unka padhne wala)
3. `AGENTS.md` (roz ka rulebook)
