const fs = require("fs");
const path = require("path");

const root = process.argv[2] || process.cwd();
const intermediate = path.join(root, ".understand-anything", "intermediate");
const scan = JSON.parse(fs.readFileSync(path.join(intermediate, "scan-result.json"), "utf8"));
const batches = JSON.parse(fs.readFileSync(path.join(intermediate, "batches.json"), "utf8"));

const fileLevelTypes = new Set(["file", "config", "document", "service", "pipeline", "table", "schema", "resource", "endpoint"]);

function slash(p) {
  return p.replace(/\\/g, "/");
}

function readText(rel) {
  try {
    return fs.readFileSync(path.join(root, rel), "utf8");
  } catch {
    return "";
  }
}

function nodeType(file) {
  const p = file.path.toLowerCase();
  if (file.fileCategory === "config" || p.endsWith(".env") || p.endsWith(".toml") || p.endsWith(".json") || p.includes(".understandignore") || p.endsWith(".python-version")) return "config";
  if (file.fileCategory === "docs" || p.endsWith(".md") || p.endsWith(".txt") || p.endsWith(".docx")) return "document";
  if (p.includes("chroma_db/") || p.endsWith(".sqlite3")) return "resource";
  return "file";
}

function nodeIdForFile(file) {
  const t = nodeType(file);
  return `${t}:${file.path}`;
}

function nameForFile(rel) {
  return rel.split("/").pop();
}

const knownSummaries = new Map(Object.entries({
  "README.md": "Project overview and operating guide for the Setomatic/SpyderWash Operator AI, including architecture, setup, and runtime commands.",
  "app.py": "Streamlit chat interface that streams LangGraph node updates, renders chat history, and shows routing diagnostics in the sidebar.",
  "main.py": "FastAPI entry module plus a console multi-turn simulation harness for testing LangGraph memory and tool routing.",
  "src/agent/graph.py": "Builds the LangGraph state machine, connects router decisions to RAG, tool, guardrail, escalation, and out-of-domain nodes, and configures MemorySaver.",
  "src/agent/router.py": "Defines the structured OpenAI semantic router prompt, intent schema, continuation rules, and extracted entity handling.",
  "src/agent/tools.py": "LangChain tool definitions for live loyalty balance, transaction history, refund eligibility, refund execution, and global system-status checks.",
  "src/agent/nodes.py": "Implements RAG response generation, metadata filtering, hardware-status refusal, and static out-of-domain refusal nodes.",
  "src/agent/state.py": "Typed LangGraph state contract for messages, intent, routing flags, escalation status, and extracted entities.",
  "src/services/rag_service.py": "Loads KB PDF/DOCX manuals, enriches metadata, builds or opens ChromaDB, and runs Groq-backed retrieval-augmented generation.",
  "src/services/notifications.py": "Mock notification service for SMS and email escalation side effects.",
  "src/config.py": "Centralized environment-backed URL and feature-flag configuration for production and mock Setomatic APIs.",
  "src/api/server.py": "Production FastAPI chat endpoint with CORS, telemetry middleware, response extraction, and LangGraph invocation.",
  "src/api/routes.py": "Legacy API router exposing health, query, and notification endpoints.",
  "src/api/schemas.py": "Pydantic request and response schemas for query and notification endpoints.",
  "src/api/mock_server.py": "Mock FastAPI backend for loyalty balance, transaction lookup, and refund workflow endpoints.",
  "pyproject.toml": "Python project manifest declaring runtime dependencies for FastAPI, Streamlit, LangGraph, LangChain, Chroma, Groq, OpenAI, and document loaders."
}));

function summaryForFile(file) {
  if (knownSummaries.has(file.path)) return knownSummaries.get(file.path);
  const p = file.path.toLowerCase();
  if (p.startsWith("kb/")) return "Knowledge-base source material used by the RAG pipeline for SpyderWash troubleshooting and operator support answers.";
  if (p.startsWith("test_") || p.includes("/test")) return "Test or verification script covering agent behavior, API behavior, RAG behavior, or router context handling.";
  if (p.endsWith(".md")) return "Project documentation or verification notes related to Setomatic/SpyderWash operator support workflows.";
  if (p.endsWith(".docx")) return "Business, API, or source knowledge document retained in the repository for requirements or RAG ingestion.";
  if (p.includes("chroma_db/")) return "Persisted Chroma vector database artifact used by the RAG service.";
  return `${nameForFile(file.path)} participates in the Setomatic/SpyderWash Operator AI codebase.`;
}

function tagsForFile(file) {
  const p = file.path.toLowerCase();
  const tags = new Set([file.language || "unknown", file.fileCategory || "code"]);
  if (p.includes("agent/")) tags.add("langgraph");
  if (p.includes("api/")) tags.add("api");
  if (p.includes("services/")) tags.add("service");
  if (p.includes("rag") || p.includes("kb/") || p.includes("chroma")) tags.add("rag");
  if (p.includes("test")) tags.add("test");
  if (p.includes("router")) tags.add("routing");
  if (p.includes("tool")) tags.add("tools");
  if (p.includes("refund")) tags.add("refund");
  if (p.includes("config") || p.endsWith(".env") || p.endsWith(".toml")) tags.add("configuration");
  return Array.from(tags);
}

function complexity(lines) {
  if (lines >= 220) return "complex";
  if (lines >= 70) return "moderate";
  return "simple";
}

const filesByPath = new Map(scan.files.map(f => [f.path, f]));
const moduleToPath = new Map();
for (const file of scan.files) {
  if (file.language !== "python") continue;
  const noExt = file.path.replace(/\.py$/, "");
  moduleToPath.set(noExt.replace(/\//g, "."), file.path);
  if (file.path.endsWith("/__init__.py")) moduleToPath.set(noExt.replace(/\/__init__$/, "").replace(/\//g, "."), file.path);
}

function resolveImport(mod) {
  if (!mod) return null;
  if (moduleToPath.has(mod)) return moduleToPath.get(mod);
  const parts = mod.split(".");
  while (parts.length > 1) {
    const candidate = parts.join(".");
    if (moduleToPath.has(candidate)) return moduleToPath.get(candidate);
    parts.pop();
  }
  return null;
}

function extractPython(file) {
  const text = readText(file.path);
  const lines = text.split(/\r?\n/);
  const nodes = [];
  const edges = [];
  const fileId = nodeIdForFile(file);
  const imports = new Set();
  let pendingEndpoint = null;

  for (const line of lines) {
    let m = line.match(/^\s*from\s+([A-Za-z_][\w.]+)\s+import\s+(.+)$/);
    if (m) {
      const target = resolveImport(m[1]);
      if (target && target !== file.path) imports.add(target);
    }
    m = line.match(/^\s*import\s+([A-Za-z_][\w.]+)/);
    if (m) {
      const target = resolveImport(m[1]);
      if (target && target !== file.path) imports.add(target);
    }
    m = line.match(/^\s*@(?:app|router|mock_app)\.(get|post|put|delete|patch)\(["']([^"']+)["']/);
    if (m) pendingEndpoint = { method: m[1].toUpperCase(), route: m[2] };
    m = line.match(/^class\s+([A-Za-z_]\w*)/);
    if (m) {
      const id = `class:${file.path}:${m[1]}`;
      nodes.push({ id, type: "class", name: m[1], filePath: file.path, summary: `${m[1]} is a class defined in ${file.path}.`, tags: ["python", "class"], complexity: complexity(file.sizeLines) });
      edges.push({ source: fileId, target: id, type: "contains", weight: 1, direction: "forward" });
    }
    m = line.match(/^(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(/);
    if (m) {
      const id = `function:${file.path}:${m[1]}`;
      nodes.push({ id, type: "function", name: m[1], filePath: file.path, summary: `${m[1]} is a function defined in ${file.path}.`, tags: ["python", "function"], complexity: complexity(file.sizeLines) });
      edges.push({ source: fileId, target: id, type: "contains", weight: 1, direction: "forward" });
      if (pendingEndpoint) {
        const epName = `${pendingEndpoint.method} ${pendingEndpoint.route}`;
        const epId = `endpoint:${file.path}:${epName}`;
        nodes.push({ id: epId, type: "endpoint", name: epName, filePath: file.path, summary: `${epName} is a FastAPI endpoint handled by ${m[1]}.`, tags: ["api", "fastapi", pendingEndpoint.method.toLowerCase()], complexity: "simple" });
        edges.push({ source: fileId, target: epId, type: "contains", weight: 1, direction: "forward" });
        edges.push({ source: epId, target: id, type: "routes", weight: 0.5, direction: "forward" });
        pendingEndpoint = null;
      }
    }
  }
  for (const target of imports) {
    const targetFile = filesByPath.get(target);
    if (targetFile) edges.push({ source: fileId, target: nodeIdForFile(targetFile), type: "imports", weight: 0.7, direction: "forward" });
  }
  return { nodes, edges };
}

function makeFileNode(file) {
  const type = nodeType(file);
  return {
    id: nodeIdForFile(file),
    type,
    name: nameForFile(file.path),
    filePath: file.path,
    summary: summaryForFile(file),
    tags: tagsForFile(file),
    complexity: complexity(file.sizeLines),
    languageNotes: file.language ? `Detected as ${file.language}.` : "Language was not detected."
  };
}

for (const batch of batches.batches) {
  const nodes = [];
  const edges = [];
  for (const file of batch.files) {
    const fileNode = makeFileNode(file);
    nodes.push(fileNode);
    if (file.language === "python") {
      const extra = extractPython(file);
      nodes.push(...extra.nodes);
      edges.push(...extra.edges);
    }
  }
  fs.writeFileSync(path.join(intermediate, `batch-${batch.batchIndex}.json`), JSON.stringify({ nodes, edges, batchFiles: batch.files }, null, 2));
}

console.log(`Wrote ${batches.batches.length} batch graph files.`);
