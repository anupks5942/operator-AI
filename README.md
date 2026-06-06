# Setomatic/SpyderWash Operator AI

An intelligent, LangGraph-orchestrated Technical Support AI Agent for the Setomatic/SpyderWash ecosystem. The agent provides operators with immediate answers to troubleshooting queries from legacy manuals, looks up loyalty card balances via live production APIs, retrieves transaction histories, checks for global system outages, and handles emergency escalations.

## 🧠 Architecture Overview

The system utilizes a state machine architecture powered by **LangGraph**, providing robust routing, guardrails, and multi-turn memory.

*   **User Interface**: Streamlit (`app.py`) providing a conversational chat interface with real-time routing diagnostics.
*   **Orchestration**: LangGraph (`src/agent/graph.py`) with `MemorySaver` for multi-turn SQLite checkpointing.
*   **Intent Routing**: OpenAI `gpt-4o` powered semantic router with structured output (Pydantic).
*   **Retrieval-Augmented Generation (RAG)**:
    *   **LLM**: Groq `llama-3.3-70b-versatile` for fast, accurate generation.
    *   **Embeddings**: HuggingFace `all-MiniLM-L6-v2`.
    *   **Vector Store**: ChromaDB (persisted in `chroma_db/`).
    *   **Document Processing**: Parses `.pdf` and `.docx` from the `KB/` directory using LangChain's RecursiveCharacterTextSplitter. Applies metadata enrichment (inferring brand and document type) and utilizes MMR (Maximal Marginal Relevance) for diverse retrieval.
*   **APIs**: FastAPI for serving the core agent endpoints (`main.py`) and a mock backend for development (`src/api/mock_server.py`).

## 🛤️ LangGraph Workflow

1.  **Semantic Router**: Analyzes user input and categorizes intent into one of 8 distinct categories (e.g., `technical_support`, `loyalty_balance_query`, `emergency_store_down`). Extracts entities like card numbers and machine brands.
2.  **Guardrail Node**: Blocks attempts to request live hardware/port status, directing the user to the official operator portal.
3.  **Escalation Node**: Detects critical intents (e.g., "whole store is down") and simulates triggering an SMS alert payload to an on-call technician.
4.  **Tool Node**: Dynamically executes tools using GPT-4o based on intent:
    *   **Loyalty Balance**: Calls the live SpyderWash production API (`betasetomaticposwebapplication.spyderwash.com`) dynamically passing the extracted loyalty card number with a hardcoded Operator ID.
    *   **Transaction Lookup**: Calls a mock local API to retrieve transaction histories.
    *   **System Status Check**: Scrapes the live Setomatic system status page with WAF bypass headers (and falls back to Cantaloupe with staleness/historical incident checks) to verify global outages.
5.  **RAG Node**: For general queries and troubleshooting, filters the vector database by brand and answers the query using Groq, citing specific source manuals.

## 🚀 Setup and Configuration

### Prerequisites
*   Python >= 3.10
*   `uv` (Python package manager)

### Environment Variables
Create a `.env` file in the root directory. You will need API keys for the LLM providers:
```env
OPENAI_API_KEY="your_openai_api_key"
GROQ_API_KEY="your_groq_api_key"
# Add any other required keys (e.g., LangSmith tracking if applicable)
```

### Installation
Install all dependencies as defined in `pyproject.toml`:
```bash
uv sync
```

## 💻 Running the Application

The system requires multiple processes for the full experience (UI, Main API, and Mock API for transactions).

1.  **Start the Mock Backend** (Required for transaction lookups):
    ```bash
    uv run uvicorn src.api.mock_server:mock_app --port 8001 --reload
    ```

2.  **Start the Main Agent API** (Optional, if you want to query via REST instead of UI):
    ```bash
    uv run uvicorn main:app --reload
    ```
    *   Health check: `GET http://localhost:8000/health`
    *   Query endpoint: `POST http://localhost:8000/query`

3.  **Launch the Streamlit UI**:
    ```bash
    uv run streamlit run app.py
    ```

## 🛠️ Developer Workflow & Testing

*   **Knowledge Base Management**: Add new troubleshooting guides, manuals, or release notes (PDF/DOCX) to the `KB/` directory. The `RAGService` will automatically parse, semantically chunk, enrich metadata, and ingest them into ChromaDB on the next initialization (if `chroma_db` is empty or if forced).
*   **Testing Multi-turn Memory**: Run the included simulation script to verify that the `MemorySaver` checkpointer successfully retains context (like card numbers) across consecutive turns and streams tokens:
    ```bash
    uv run python main.py
    ```

## 🔒 Security & Resilience

*   **WAF Bypass**: The `check_global_system_status` tool utilizes `requests.Session()` with spoofed Chrome headers, `Referer`, `Origin`, and `DNT` flags to bypass OpenResty WAF blocks on Setomatic's public status pages. It explicitly disables `Accept-Encoding` to avoid receiving unparseable binary compressed payloads.
*   **Graceful API Degradation**: The tools include comprehensive `try/except` blocks handling HTTP 500s, timeouts, and missing JSON keys (specifically in the nested SpyderWash payload) to ensure the LLM receives formatted fallback strings rather than raw exceptions.
*   **Guardrails**: Explicitly prevents LLM hallucination regarding real-time machine hardware states.
