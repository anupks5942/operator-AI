import os
import re
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_classic.chains import create_retrieval_chain
from src.llm import create_chat_model

# ── Metadata helpers ──────────────────────────────────────────────────────────

# Maps lowercase filename keywords -> canonical display name
_BRAND_DISPLAY = {
    "speed_queen": "Speed Queen",
    "speedqueen":  "Speed Queen",
    "maytag":      "Maytag",
    "huebsch":     "Huebsch",
    "alliance":    "Alliance",
    "spyderwash":  "SpyderWash",
    "setomatic":   "SpyderWash",
}

def _infer_doc_type(filename: str) -> str:
    """Infer document type from filename."""
    name_lower = filename.lower()
    if "troubleshoot" in name_lower or "guide" in name_lower or "voiceover" in name_lower:
        return "troubleshooting_guide"
    if "manual" in name_lower or "operator" in name_lower:
        return "manual"
    if "release" in name_lower or "notes" in name_lower:
        return "release_notes"
    if "overview" in name_lower:
        return "overview"
    return "general"

def _infer_brand(filename: str) -> str:
    """Infer primary brand from filename, returning the canonical display name."""
    name_lower = filename.lower().replace(" ", "_").replace("-", "_")
    for keyword, display_name in _BRAND_DISPLAY.items():
        if keyword in name_lower:
            return display_name
    return "SpyderWash"  # default brand for this KB

def _enrich_metadata(doc, file_path: str):
    """
    Enrich a document chunk's metadata with:
      - source_file: basename of the source file
      - doc_type:    inferred document type (manual, troubleshooting_guide, etc.)
      - brand:       inferred brand name from filename
    """
    filename = os.path.basename(file_path)
    doc.metadata["source_file"] = filename
    doc.metadata["doc_type"] = _infer_doc_type(filename)
    doc.metadata["brand"] = _infer_brand(filename)
    return doc

# ── RAGService ────────────────────────────────────────────────────────────────

class RAGService:
    def __init__(self, kb_dir: str = "KB", persist_dir: str = "./chroma_db", force_reingest: bool = False):
        self.kb_dir = kb_dir
        self.persist_dir = persist_dir
        from src.config import OPENAI_EMBEDDING_MODEL
        self.embeddings = OpenAIEmbeddings(model=OPENAI_EMBEDDING_MODEL)

        # Load or build vectorstore
        db_exists = os.path.exists(self.persist_dir) and len(os.listdir(self.persist_dir)) > 0
        if db_exists and not force_reingest:
            self.vectorstore = Chroma(
                persist_directory=self.persist_dir,
                embedding_function=self.embeddings,
            )
        else:
            splits = self.load_and_process_documents()
            if splits:
                self.vectorstore = self.initialize_vectorstore(splits)
            else:
                self.vectorstore = None

        if self.vectorstore:
            # Default retriever (MMR for diversity); overridden per-query when filters are applied
            self.retriever = self.vectorstore.as_retriever(
                search_type="mmr",
                search_kwargs={"k": 6, "fetch_k": 20, "lambda_mult": 0.6},
            )
            self.llm = create_chat_model(temperature=0)

            system_prompt = (
                "You are an expert Technical Support AI Agent for the Setomatic/SpyderWash ecosystem. "
                "Use the provided context from manuals, release notes, and product documentation to answer "
                "the user's questions about SpyderWash hardware, portal operations, product features, and troubleshooting. "
                "Be brutally direct, technically rigorous, and zero fluff. "
                "If the answer is not contained in the context, explicitly state that you do not have that information in the current KB. "
                "\n\n"
                "Context:\n{context}"
            )
            prompt = ChatPromptTemplate.from_messages([
                ("system", system_prompt),
                ("human", "{input}"),
            ])
            self.question_answer_chain = create_stuff_documents_chain(self.llm, prompt)
            self.rag_chain = create_retrieval_chain(self.retriever, self.question_answer_chain)
        else:
            self.retriever = None
            self.rag_chain = None

    # ── Ingestion ─────────────────────────────────────────────────────────────

    def load_and_process_documents(self):
        """
        Load all PDF, DOCX, and TXT files from kb_dir, split into chunks of 500/50,
        enrich each chunk with source metadata, and prepend a provenance header
        to each chunk's page_content so the LLM sees the source inline.

        Provenance header format (prepended before Chroma ingestion):
            [DOCUMENT: {filename} | PAGE: {page_number}]
        """
        docs = []

        if not os.path.exists(self.kb_dir):
            return None

        for filename in os.listdir(self.kb_dir):
            file_path = os.path.join(self.kb_dir, filename)
            if filename.endswith(".pdf"):
                raw_docs = PyPDFLoader(file_path).load()
            elif filename.endswith(".docx"):
                raw_docs = Docx2txtLoader(file_path).load()
            elif filename.endswith(".txt"):
                raw_docs = TextLoader(file_path, encoding="utf-8").load()
            else:
                continue

            # Enrich metadata before splitting so every chunk inherits it
            for doc in raw_docs:
                _enrich_metadata(doc, file_path)

            docs.extend(raw_docs)

        if not docs:
            return None

        # Semantic chunking with tighter window for precision
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
            separators=["\n\n", "\n", ".", " ", ""],
        )
        splits = splitter.split_documents(docs)

        # ── Prepend provenance header to each chunk's page_content ────────────
        # Embedding the source/page directly in the text ensures the LLM sees
        # where each passage came from, independent of metadata retrieval.
        for chunk in splits:
            source = os.path.basename(
                chunk.metadata.get("source_file") or
                chunk.metadata.get("source", "Unknown")
            )
            page = chunk.metadata.get("page", "N/A")
            header = f"[DOCUMENT: {source} | PAGE: {page}]\n\n"
            chunk.page_content = header + chunk.page_content

        return splits

    def initialize_vectorstore(self, splits):
        """Build a fresh Chroma vectorstore from the enriched splits."""
        return Chroma.from_documents(
            documents=splits,
            embedding=self.embeddings,
            persist_directory=self.persist_dir,
        )

    # ── Query ─────────────────────────────────────────────────────────────────

    def _build_retriever(self, metadata_filter: dict | None = None):
        """
        Build a retriever with optional metadata filter and MMR re-ranking.

        MMR (Maximal Marginal Relevance) balances relevance with diversity,
        ensuring the top-k results are not all near-duplicate passages.

        Args:
            metadata_filter: Chroma-compatible $eq/$in filter dict, e.g.
                             {"brand": {"$eq": "Speed Queen"}} or
                             {"doc_type": {"$eq": "troubleshooting_guide"}}
        """
        search_kwargs = {
            "k": 3,           # final top-k after MMR re-ranking
            "fetch_k": 20,    # candidate pool before MMR
            "lambda_mult": 0.6,  # 0=pure diversity, 1=pure similarity
        }
        if metadata_filter:
            search_kwargs["filter"] = metadata_filter

        return self.vectorstore.as_retriever(
            search_type="mmr",
            search_kwargs=search_kwargs,
        )

    def query(self, input_text: str, metadata_filter: dict | None = None) -> dict:
        """
        Query the RAG pipeline.

        If a metadata_filter is provided and retrieval returns zero context documents,
        the query is retried without the filter as a fallback to avoid false "not in KB"
        responses when the filter is too restrictive.

        Args:
            input_text:      The user's question.
            metadata_filter: Optional Chroma filter dict to restrict retrieval
                             to specific doc_type or brand. Example:
                             {"brand": {"$eq": "Speed Queen"}}

        Returns:
            dict with keys: "answer" (str) and "context" (list of Documents).
        """
        if not self.vectorstore:
            return {"answer": "Error: RAG Chain not initialized (no KB documents found).", "context": []}

        result = self._invoke_rag(input_text, metadata_filter)

        if metadata_filter and not result.get("context"):
            result = self._invoke_rag(input_text, metadata_filter=None)

        return result

    def _invoke_rag(self, input_text: str, metadata_filter: dict | None = None) -> dict:
        """Run a single retrieval-augmented generation pass."""
        retriever = self._build_retriever(metadata_filter)
        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are an expert Technical Support AI Agent for the Setomatic/SpyderWash ecosystem. "
             "Use the provided context from manuals, release notes, and product documentation to answer "
             "the user's questions about SpyderWash hardware, portal operations, product features, and troubleshooting. "
             "Setomatic Systems is the company that manufactures SpyderWash — treat any SpyderWash context as relevant when answering questions about Setomatic, and vice versa. "
             "Be brutally direct, technically rigorous, and zero fluff. "
             "If the answer is not contained in the context, explicitly state that you do not have that information in the current KB. "
             "\n\nContext:\n{context}"),
            ("human", "{input}"),
        ])
        qa_chain = create_stuff_documents_chain(self.llm, prompt)
        rag_chain = create_retrieval_chain(retriever, qa_chain)
        return rag_chain.invoke({"input": input_text})
