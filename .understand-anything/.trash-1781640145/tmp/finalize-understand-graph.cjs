const fs = require("fs");
const path = require("path");

const root = process.argv[2] || process.cwd();
const gitCommitHash = process.argv[3] || "";
const intermediate = path.join(root, ".understand-anything", "intermediate");
const scan = JSON.parse(fs.readFileSync(path.join(intermediate, "scan-result.json"), "utf8"));
const assembledPath = path.join(intermediate, "assembled-graph.json");
const assembled = JSON.parse(fs.readFileSync(assembledPath, "utf8"));

const fileLevelTypes = new Set(["file", "config", "document", "service", "pipeline", "table", "schema", "resource", "endpoint"]);
const nodeIds = new Set(assembled.nodes.map(n => n.id));

function layerId(name) {
  return "layer:" + name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

const layers = [
  {
    id: layerId("Operator Interfaces and APIs"),
    name: "Operator Interfaces and APIs",
    description: "Streamlit and FastAPI entry points that receive operator messages, expose REST endpoints, and return agent responses.",
    nodeIds: []
  },
  {
    id: layerId("Agent Orchestration"),
    name: "Agent Orchestration",
    description: "LangGraph state, routing, nodes, and tools that classify intents and execute RAG, API, escalation, and guardrail workflows.",
    nodeIds: []
  },
  {
    id: layerId("Knowledge Retrieval"),
    name: "Knowledge Retrieval",
    description: "RAG service, Chroma persistence, and knowledge-base documents used to answer troubleshooting questions from manuals.",
    nodeIds: []
  },
  {
    id: layerId("Configuration and Documentation"),
    name: "Configuration and Documentation",
    description: "Project configuration, environment settings, requirements, README, and verification documents that describe or configure the system.",
    nodeIds: []
  },
  {
    id: layerId("Tests and Validation"),
    name: "Tests and Validation",
    description: "Test scripts and QA artifacts that verify graph behavior, router continuity, RAG behavior, and API endpoints.",
    nodeIds: []
  }
];

function chooseLayer(node) {
  const p = (node.filePath || "").toLowerCase();
  if (p.startsWith("test") || p.includes("/test") || p.includes("verification") || p.includes("rag_test_results")) return 4;
  if (node.type === "endpoint" || p === "app.py" || p === "main.py" || p.startsWith("src/api/")) return 0;
  if (p.startsWith("src/agent/")) return 1;
  if (p.startsWith("src/services/rag_service.py") || p.startsWith("kb/") || p.includes("chroma_db")) return 2;
  if (p.startsWith("src/services/notifications.py")) return 1;
  return 3;
}

for (const node of assembled.nodes) {
  if (!fileLevelTypes.has(node.type)) continue;
  layers[chooseLayer(node)].nodeIds.push(node.id);
}

for (const layer of layers) {
  layer.nodeIds = Array.from(new Set(layer.nodeIds)).filter(id => nodeIds.has(id)).sort();
}

const tour = [
  {
    order: 1,
    title: "Project Overview",
    description: "Start with the README and project manifest to understand the Setomatic/SpyderWash Operator AI purpose, dependencies, and runtime commands.",
    nodeIds: ["document:README.md", "config:pyproject.toml"].filter(id => nodeIds.has(id))
  },
  {
    order: 2,
    title: "Operator Entry Points",
    description: "Review the Streamlit UI and FastAPI entry modules to see how operator messages enter the system and how responses are surfaced.",
    nodeIds: ["file:app.py", "file:main.py", "file:src/api/server.py", "file:src/api/routes.py"].filter(id => nodeIds.has(id))
  },
  {
    order: 3,
    title: "LangGraph Workflow",
    description: "Follow the graph, router, state, and node implementations to understand intent classification and workflow routing.",
    nodeIds: ["file:src/agent/graph.py", "file:src/agent/router.py", "file:src/agent/state.py", "file:src/agent/nodes.py"].filter(id => nodeIds.has(id))
  },
  {
    order: 4,
    title: "Tool and API Workflows",
    description: "Inspect the tool layer and mock backend to understand loyalty balance, transaction lookup, refund, system-status, and notification flows.",
    nodeIds: ["file:src/agent/tools.py", "file:src/api/mock_server.py", "file:src/config.py", "file:src/services/notifications.py"].filter(id => nodeIds.has(id))
  },
  {
    order: 5,
    title: "RAG Knowledge Path",
    description: "Trace how KB documents are loaded, enriched, embedded into Chroma, retrieved with filters, and passed to the Groq-backed answer chain.",
    nodeIds: ["file:src/services/rag_service.py", "document:KB/SpyderWash Manual.txt", "document:KB/Condensed Troubleshooting Guide.docx.txt", "resource:chroma_db/chroma.sqlite3"].filter(id => nodeIds.has(id))
  },
  {
    order: 6,
    title: "Validation Coverage",
    description: "Finish with the test scripts that exercise graph construction, router context continuity, RAG responses, and API behavior.",
    nodeIds: ["file:test_graph.py", "file:test_router_context.py", "file:test_rag.py", "file:test_server.py"].filter(id => nodeIds.has(id))
  }
].filter(step => step.nodeIds.length > 0);

const languages = Object.keys(scan.stats?.byLanguage || {}).sort();
const graph = {
  version: "1.0.0",
  project: {
    name: "Setomatic/SpyderWash Operator AI",
    languages,
    frameworks: ["FastAPI", "Streamlit", "LangGraph", "LangChain", "ChromaDB", "OpenAI", "Groq"],
    description: "LangGraph-orchestrated technical support agent for Setomatic/SpyderWash operators with RAG over legacy manuals, live loyalty and transaction tools, refund workflow support, status checks, escalation handling, and guardrails.",
    analyzedAt: new Date().toISOString(),
    gitCommitHash
  },
  nodes: assembled.nodes,
  edges: assembled.edges,
  layers,
  tour
};

const issues = [];
const warnings = [];
const allIds = new Set(graph.nodes.map(n => n.id));
const layerAssigned = new Map();

for (const layer of graph.layers) {
  for (const field of ["id", "name", "description", "nodeIds"]) {
    if (!(field in layer)) issues.push(`Layer '${layer.name || layer.id}' missing ${field}`);
  }
  for (const id of layer.nodeIds || []) {
    if (!allIds.has(id)) issues.push(`Layer '${layer.id}' refs missing node '${id}'`);
    if (layerAssigned.has(id)) issues.push(`Node '${id}' appears in multiple layers`);
    layerAssigned.set(id, layer.id);
  }
}

for (const node of graph.nodes) {
  if (fileLevelTypes.has(node.type) && !layerAssigned.has(node.id)) {
    issues.push(`File-level node '${node.id}' not in any layer`);
  }
}

for (const step of graph.tour) {
  for (const field of ["order", "title", "description", "nodeIds"]) {
    if (!(field in step)) issues.push(`Tour step '${step.title || step.order}' missing ${field}`);
  }
  for (const id of step.nodeIds || []) {
    if (!allIds.has(id)) issues.push(`Tour step '${step.title}' refs missing node '${id}'`);
  }
}

const edgeRefs = new Set();
for (const edge of graph.edges) {
  if (!allIds.has(edge.source)) issues.push(`Edge source '${edge.source}' not found`);
  if (!allIds.has(edge.target)) issues.push(`Edge target '${edge.target}' not found`);
  edgeRefs.add(edge.source);
  edgeRefs.add(edge.target);
}
for (const node of graph.nodes) {
  if (!edgeRefs.has(node.id)) warnings.push(`Node '${node.id}' has no edges`);
}

const stats = {
  totalNodes: graph.nodes.length,
  totalEdges: graph.edges.length,
  totalLayers: graph.layers.length,
  tourSteps: graph.tour.length,
  nodeTypes: graph.nodes.reduce((acc, n) => (acc[n.type] = (acc[n.type] || 0) + 1, acc), {}),
  edgeTypes: graph.edges.reduce((acc, e) => (acc[e.type] = (acc[e.type] || 0) + 1, acc), {})
};

fs.writeFileSync(assembledPath, JSON.stringify(graph, null, 2));
fs.writeFileSync(path.join(intermediate, "review.json"), JSON.stringify({ issues, warnings, stats }, null, 2));
console.log(JSON.stringify({ issues: issues.length, warnings: warnings.length, stats }, null, 2));
