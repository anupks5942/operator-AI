# Intent Matrix

Brandon's signed-off business intent matrix (June 2026), mapped to LangGraph router intents and escalation channels.

**Router:** [src/agent/router.py](../src/agent/router.py) — 17 intents  
**Routing:** [src/agent/graph.py](../src/agent/graph.py) — `route_after_classifier`  
**Notifications:** [src/services/notifications.py](../src/services/notifications.py)

---

## Legend

| Escalation type (Brandon) | Meaning |
|---------------------------|---------|
| **None** | No email/SMS dispatch |
| **Email** | Mandrill to `ESCALATION_EMAIL` only |
| **Email/SMS** | Both email and SMS |
| **SMS Alert** | Twilio to `ESCALATION_SMS_TO` only (no email) |
| **Conditional** | Escalate only when troubleshooting or API path fails |

| Code column | Meaning |
|-------------|---------|
| **Today** | Actual behavior in this repo |
| **Target** | Brandon matrix requirement |

**Gap (today):** Every escalation sends **Email+SMS** regardless of intent. Per-intent routing is **Phase 2** — [ROADMAP.md](ROADMAP.md).

**Related (different layer):** Brandon’s **KB chunks** (`sw_*` IDs, keywords) drive *retrieval*; this matrix drives *routing and escalation*. Full chunk → row mapping: [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md).

---

## Brandon matrix (29 rows)

Source: client Intent Matrix spreadsheet (Brandon), June 2026.

| # | Category | Subcategory | Priority | AI action | API | Escalation (target) | KB |
|---|----------|-------------|----------|-----------|-----|----------------------|-----|
| 1 | Hub Setup & Installation | Static IP | Low | Instructional | No | None | Yes |
| 2 | Account & Login | Operator Portal Login | Medium | Troubleshoot + escalate | Conditional | Email | Yes |
| 3 | Hub Setup & Installation | Wi-Fi Requirement | Low | Instructional | No | None | Yes |
| 4 | Attendant & Time Clock | POS Time Clock | Low | Instructional | No | None | Yes |
| 5 | Transactions & Card History | Specific Transaction Lookup | Medium | API + portal guidance | Yes | None | Yes |
| 6 | Account & Login | Customer Account Creation | Low | Instructional | No | None | Yes |
| 7 | Refunds & Payment Adjustments | Customer Refunds | Medium | Workflow / API | Yes | Email | Yes |
| 8 | Operator Portal Guidance | Machine Management | Medium | Portal guidance | No | None | Yes |
| 9 | Attendant & Time Clock | Attendant Access & Passcodes | Low | Portal guidance | No | None | Yes |
| 10 | Pricing & Program | Machine Pricing | Low | Portal navigation | Conditional | Email | Yes |
| 11 | Loyalty Card Support | Balance Lookup | Low | API lookup | Yes | None | Yes |
| 12 | Operator Portal Guidance | Machine Availability | Low | Portal guidance | No | None | Yes |
| 13 | Kiosk / Reload Center | Kiosk Cash Reconciliation | Low | Portal guidance | No | None | Yes |
| 14 | Loyalty Card Support | Loyalty Program Settings | Low | RAG + portal | No | None | Yes |
| 15 | Transactions & Card History | Card & Transaction History | Medium | API + portal | Yes | None | Yes |
| 16 | Loyalty Card Support | Customer Card Management | Low | Portal guidance | Conditional | None | Yes |
| 17 | Hub Setup & Installation | Reader Pairing | Low | Instructional | No | None | Yes |
| 18 | Hub Setup & Installation | Hub Reboot | Medium | Instructional | No | None | Yes |
| 19 | Loyalty Card Support | Card Registration | Low | Portal guidance | No | None | Yes |
| 20 | Pricing & Program | Free Wash Program | Low | RAG + portal | Conditional | None | Yes |
| 21 | Hub Setup & Installation | Reader Distance | Low | Instructional | No | None | Yes |
| 22 | Payments, Deposits & KYC | Activation Timing | Medium | Instructional | No | Email | Yes |
| 23 | Hub Setup & Installation | Hub Quantity Planning | Low | Instructional | No | None | Yes |
| 24 | Human Support Request | Human Escalation | Medium | Troubleshoot first → escalate | No | Email/SMS | Yes |
| 25 | Kiosk / Reload Center | Kiosk Not Responding | **High** | Outage workflow | No | Email/SMS | Yes |
| 26 | Machine Start / Vend | Machines Not Starting | **High** | Outage workflow | No | Email/SMS | Yes |
| 27 | Critical Outage | Entire Store Down | **Critical** | Outage workflow + escalate | No | **SMS Alert** | Yes |
| 28 | Kiosk / Reload Center | Receipt Printer Issue | Medium | Troubleshooting workflow | No | Email | Yes |
| 29 | Loyalty Card Support | Recharge Failure | Medium | Troubleshooting workflow | Conditional | Email | Yes |

---

## Business row → router intent mapping

| Brandon subcategory(s) | Router intent(s) | Graph route |
|------------------------|------------------|-------------|
| Simple greeting / salutation (hi, hello, hey) | `greeting` | greeting_node |
| Summarise / recap current chat | `conversation_summary` | summarize_node |
| Hub setup, portal how-to, time clock, card registration, free wash, etc. | `general_query` or `technical_support` | RAG |
| Machine Availability; live machine/port status questions | `hardware_status` | guardrail |
| Balance Lookup | `loyalty_balance_query` | tool_node |
| Transaction lookup / card history (normal or refunded) | `transaction_lookup` | tool_node (`isRefund` false/true) |
| Customer Refunds | `refund_request` | RAG (Bible/portal how-to) — **not** refund execute tools |
| Global/platform outage | `system_status_check` | tool_node |
| Portal login, pricing, activation, receipt printer, recharge failure | `technical_support` (no dedicated label) | RAG (unfiltered; ADR-033); conditional Email **not wired** |
| Human Escalation | `escalation_request` | clarify-first → escalate (ADR-031; **not** outage workflow) |
| Kiosk Not Responding | `kiosk_not_responding` | RAG direct (no outage workflow) |
| Machines Not Starting | `machines_not_starting` | outage workflow |
| Entire Store Down | `emergency_store_down`, `multiple_machines_offline`, or `critical_outage` | outage or immediate escalation |
| Single machine down | `machine_down` | outage workflow |
| Off-topic / injection | `out_of_domain` | refusal |

### Router gaps (Phase 2)

| Business need | Today | Action |
|---------------|-------|--------|
| Receipt Printer Issue | `technical_support` → RAG (domain keywords + no category filter) | Phase 2: dedicated intent + Email-only escalate |
| Recharge Failure | `technical_support` → RAG (phrase safety net prevents misroute to status/lookup) | Phase 2: dedicated intent + conditional Email |
| Operator Portal Login, Machine Pricing, Activation Timing | RAG only | Conditional Email after KB failure |
| Customer Refunds | RAG portal guidance (Bible) | Agent does not execute refunds (ADR-028) |

---

## Router intent table (17 intents)

| Router intent | Graph route | Outage workflow | Escalation today | Target (Brandon) |
|---------------|-------------|-----------------|------------------|------------------|
| `greeting` | greeting_node | No | None | None |
| `conversation_summary` | summarize_node | No (does not reset active workflow) | None | None |
| `general_query` | RAG | No | None | None |
| `technical_support` | RAG | No | None | None (Conditional Email rows — **not wired**) |
| `hardware_status` | guardrail | No | None | None |
| `out_of_domain` | refusal | No | None | None |
| `loyalty_balance_query` | tool_node | No | None | None |
| `transaction_lookup` | tool_node | No | None | None |
| `refund_request` | RAG (portal guidance) | No | None | None — Bible/portal steps (ADR-028) |
| `system_status_check` | tool_node | No | None | None |
| `kiosk_not_responding` | RAG direct | No (user must escalate manually) | None | Email/SMS |
| `machines_not_starting` | outage workflow | Yes | Email+SMS | Email/SMS |
| `machine_down` | outage workflow | Yes | Email+SMS | Email/SMS |
| `multiple_machines_offline` | outage workflow | Yes | Email+SMS | Email/SMS |
| `emergency_store_down` | outage workflow | Yes | Email+SMS | **SMS Alert only** |
| `escalation_request` | human_escalation_clarify → escalation | No (clarify-first) | Email+SMS | Email/SMS |
| `critical_outage` | immediate escalation | Skipped | Email+SMS | **SMS Alert only** |

---

## Phase 2 escalation routing spec

| Target channel | Router intents / triggers |
|----------------|---------------------------|
| **None** | Non-escalation paths; TC1 resolved |
| **Email only** | Refund/portal/pricing/activation/receipt/recharge failures (once wired) |
| **SMS only** | `emergency_store_down`, `critical_outage` after troubleshoot failure |
| **Email+SMS** | `kiosk_not_responding`, `machines_not_starting`, `machine_down`, `multiple_machines_offline`, `escalation_request` |

**Important:** Entire Store Down is **SMS Alert only** in Brandon's matrix. Current code sends both channels.

---

## Router flags

Set by [router.py](../src/agent/router.py) `semantic_router`:

| Flag | Set when | Effect |
|------|----------|--------|
| `hardware_lookup_attempted` | `hardware_status` | → guardrail_node |
| `api_action_required` | loyalty, transaction, system_status, kiosk/POS/remote | → tool_node (`refund_request` → RAG portal guidance) |
| `escalation_required` | `emergency_store_down`, `escalation_request` (initial classification) | Enters outage workflow |

Outage/hardware intents must keep all three flags **false** on first classification — graph handles escalation after `troubleshooting_done`.

**Graph-level escalation** (independent of initial `escalation_required`):

- `troubleshooting_failed` in entities or negative reply after "Did this resolve?" → `escalation_node`
- `critical_outage` intent → immediate `escalation_node` (skips troubleshoot)

Outage workflow intent set (`_ESCALATION_WORKFLOW_INTENTS` in graph.py):

```
emergency_store_down, machine_down, escalation_request,
machines_not_starting, multiple_machines_offline
```

RAG-only (no outage workflow): `kiosk_not_responding`, `technical_support`

---

## Context-continuation (multi-turn)

| Prior assistant prompt | Operator reply | Extracted entity |
|------------------------|----------------|------------------|
| Blast-radius question | "one machine", "entire laundromat offline" | `blast_radius` |
| Did this resolve? | "no", "still down" | `troubleshooting_failed: true` → confirm escalate (single) or escalate (entire) |
| Did this resolve? | "yes", "fixed" | `troubleshooting_failed: false` → `troubleshoot_success` (not ticket resolve) |
| Refund workflow | card number, "yes proceed" | `card_number`, `confirmation` |
| Ticket already dispatched | how-to / new-topic statement | RAG answer (ADR-037) — not ticket notes |
| Ticket already dispatched | "also…", "same problem…" | `post_escalation_ack` ticket notes |
| Ticket already dispatched | different blast-radius outage | `new_issue_after_escalation` (not Jaccard false-positive) |
| Ticket already dispatched | greeting | greeting node; clears escalation routing flags |
| RAG answer cites `KB-…` | "yes provide me" / short follow-up | expanded RAG query / article_id filter (ADR-036) |
| Summarise / recap request | "summarise this chat", "recap", "tl;dr" | `conversation_summary` — honored mid-workflow |

---

## Implementation backlog

| Task | Phase | Owner | File |
|------|-------|-------|------|
| Per-intent Email / SMS / both / none | 2 | dev1 | [notifications.py](../src/services/notifications.py) |
| SMS-only for store-down / critical | 2 | dev1 | [notifications.py](../src/services/notifications.py) |
| Escalation type lookup table | 2 | dev1 | [router.py](../src/agent/router.py) or config |
| Receipt printer + recharge failure intents | 2 | dev1 | [router.py](../src/agent/router.py) |
| Conditional Email for portal/pricing rows | 2 | dev1 | [graph.py](../src/agent/graph.py) |
| Tests for SMS-only and Email-only paths | 2 | dev1 | [tests/](../tests/) |

---

## Related documents

- [BRANDON_KB_ADMIN.md](BRANDON_KB_ADMIN.md) — structured chunks vs this routing matrix
- [ESCALATION_WORKFLOW.md](ESCALATION_WORKFLOW.md) — outage steps
- [ARCHITECTURE.md](ARCHITECTURE.md) — graph routing
- [PRD.md](PRD.md) — client rules
- [ROADMAP.md](ROADMAP.md) — phase owners and blockers
