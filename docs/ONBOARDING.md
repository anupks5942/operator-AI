# Setomatic/SpyderWash Operator AI Onboarding Guide

## Project Overview

Setomatic/SpyderWash Operator AI is a LangGraph-orchestrated technical support agent for laundry operators. It combines RAG over legacy manuals with live loyalty-card and transaction tools, refund workflow support, global status checks, escalation handling, and guardrails.

- Primary language: Python
- Key frameworks: FastAPI, Streamlit, LangGraph, LangChain, ChromaDB, OpenAI, Groq
- Start here: `README.md`

## Architecture Layers

### Operator Interfaces and APIs

Entry points that receive operator messages and return agent responses.

Key files:
- `app.py` - Streamlit chat interface with graph streaming and routing diagnostics.
- `main.py` - FastAPI entry module plus console multi-turn simulation harness.
- `src/api/server.py` - Production FastAPI chat endpoint with CORS, telemetry, and LangGraph invocation.
- `src/api/routes.py` - Legacy API router for health, query, and notification endpoints.
- `src/api/schemas.py` - Pydantic request and response schemas.
- `src/api/mock_server.py` - Mock backend for loyalty, transaction, and refund endpoints.

### Agent Orchestration

LangGraph state, routing, nodes, tools, escalation, and guardrails.

Key files:
- `src/agent/graph.py` - Builds the LangGraph state machine and connects router decisions to RAG, tools, guardrails, escalation, and refusal nodes.
- `src/agent/router.py` - Defines the structured OpenAI semantic router prompt, intent schema, continuation rules, and entity extraction.
- `src/agent/nodes.py` - Implements RAG response generation, metadata filtering, hardware-status refusal, and out-of-domain refusal.
- `src/agent/tools.py` - LangChain tools for loyalty balance, transaction history, refund workflow, and global status checks.
- `src/agent/state.py` - Typed LangGraph state contract.
- `src/services/notifications.py` - Mock SMS and email notification side effects.

### Knowledge Retrieval

RAG service, Chroma persistence, and KB documents used for troubleshooting answers.

Key files:
- `src/services/rag_service.py` - Loads KB manuals, enriches metadata, builds or opens ChromaDB, and runs Groq-backed retrieval-augmented generation.
- `KB/SpyderWash Manual.txt` - SpyderWash source manual content.
- `KB/Condensed Troubleshooting Guide.docx.txt` - Condensed troubleshooting source text.
- `KB/Voiceover SpyderWash Troubleshooting Guide.docx.txt` - Voiceover troubleshooting source text.
- `chroma_db/chroma.sqlite3` - Persisted Chroma vector database artifact.

### Configuration and Documentation

Project setup, environment, requirements, and operational documentation.

Key files:
- `pyproject.toml` - Python dependencies and project metadata.
- `.env` - Runtime secrets and environment configuration.
- `src/config.py` - Centralized environment-backed URL and feature-flag configuration.
- `README.md` - Project overview, setup, and runtime commands.
- `API_Requirements.docx`, `Requirement understading.docx`, `Setomatic Summary Document.docx` - Business and API source documents.

### Tests and Validation

Verification scripts for graph behavior, routing context, RAG, and API behavior.

Key files:
- `test_graph.py` - Graph behavior checks.
- `test_router_context.py` - Router continuation/context checks.
- `test_rag.py` - RAG behavior checks.
- `test_server.py` - API/server behavior checks.
- `KB_VERIFICATION_QA.md` and `rag_test_results.md` - Manual QA and verification notes.

## Key Concepts

### LangGraph as the Control Plane

`src/agent/graph.py` wires the semantic router into RAG, tool execution, guardrail, escalation, and refusal paths. New developers should understand this file before changing behavior because it defines the execution flow.

### Structured Semantic Routing

`src/agent/router.py` classifies operator intent and extracts entities like card numbers, machine IDs, transaction IDs, and confirmations. It also handles short follow-up replies during multi-turn workflows.

### Tool-Driven Workflows

`src/agent/tools.py` contains the operational integrations. It handles:
- Live loyalty balance lookup
- Live transaction history lookup
- Refund eligibility check
- Refund execution
- Global system status scraping and fallback logic

Refund behavior is intentionally sequential: transaction lookup, eligibility check, then refund execution only if eligible.

### RAG for Troubleshooting

`src/services/rag_service.py` loads PDF/DOCX manuals from `KB/`, enriches metadata, chunks content, persists embeddings in Chroma, and answers support questions through a Groq-backed chain.

### Guardrails by Route

Hardware status and out-of-domain requests are handled by explicit graph paths rather than free-form model behavior. This keeps the agent from claiming real-time hardware visibility or responding to unrelated and adversarial prompts.

### Session Memory

LangGraph `MemorySaver` is keyed by thread/session so follow-up replies can continue workflows, such as a user providing a card number after the assistant asks for one.

## Guided Tour

1. **Project Overview**
   Read `README.md` and `pyproject.toml` to understand the product goal, dependencies, and runtime commands.

2. **Operator Entry Points**
   Review `app.py`, `main.py`, `src/api/server.py`, and `src/api/routes.py` to see how operator messages enter the system.

3. **LangGraph Workflow**
   Follow `src/agent/graph.py`, `src/agent/router.py`, `src/agent/state.py`, and `src/agent/nodes.py` to understand classification and routing.

4. **Tool and API Workflows**
   Inspect `src/agent/tools.py`, `src/api/mock_server.py`, `src/config.py`, and `src/services/notifications.py` to understand live API calls, mock refund development, and notifications.

5. **RAG Knowledge Path**
   Trace `src/services/rag_service.py`, the `KB/` manuals, and `chroma_db/chroma.sqlite3` to understand ingestion, retrieval, metadata filters, and answer generation.

6. **Validation Coverage**
   Finish with `test_graph.py`, `test_router_context.py`, `test_rag.py`, and `test_server.py`.

## File Map

### Application Entry Points

- `app.py` - Streamlit UI that streams graph node updates, renders chat history, and displays routing diagnostics.
- `main.py` - API setup plus console simulation for multi-turn graph memory and tool routing.
- `src/api/server.py` - Production REST API for frontend integration.
- `src/api/routes.py` - Legacy API router.
- `src/api/mock_server.py` - Local mock API for development and refund workflow testing.

### Agent Core

- `src/agent/graph.py` - Main graph definition and routing table.
- `src/agent/router.py` - Intent classification and entity extraction.
- `src/agent/nodes.py` - RAG node, guardrail node, and out-of-domain handler.
- `src/agent/tools.py` - External tool implementations and tool exports.
- `src/agent/state.py` - Shared state schema.

### Services

- `src/services/rag_service.py` - Document processing, Chroma integration, and RAG query execution.
- `src/services/notifications.py` - Mock notification delivery.
- `src/config.py` - Environment-driven configuration.

### Knowledge Assets

- `KB/SpyderWash Manual.txt`
- `KB/Condensed Troubleshooting Guide.docx.txt`
- `KB/Voiceover SpyderWash Troubleshooting Guide.docx.txt`
- `chroma_db/chroma.sqlite3`

### Tests and QA

- `test_graph.py`
- `test_router_context.py`
- `test_rag.py`
- `test_server.py`
- `test.py`
- `KB_VERIFICATION_QA.md`
- `rag_test_results.md`

## Complexity Hotspots

- `src/agent/tools.py` - Complex live/mock API logic, refund workflow ordering, system-status scraping, and error handling.
- `src/agent/graph.py` - Core LangGraph routing and ReAct-style tool loop behavior.
- `src/api/server.py` - Production API surface with telemetry, CORS, session memory, and response extraction.
- `src/services/rag_service.py` - Document ingestion, metadata enrichment, Chroma setup, retriever construction, and Groq response chain.
- `KB/` documents and `chroma_db/chroma.sqlite3` - Large knowledge assets that drive RAG answer quality but are not normal application code.

## Suggested First Tasks for New Developers

1. Run the app locally using the commands in `README.md`.
2. Send one RAG troubleshooting query through the Streamlit UI.
3. Send one loyalty-card or refund-related query through the API path.
4. Read `src/agent/router.py` and map the detected intent to the graph route in `src/agent/graph.py`.
5. Add or update a small test before changing router, tool, or RAG behavior.

