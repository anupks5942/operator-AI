import streamlit as st
import os
from dotenv import load_dotenv
from src.services.rag_service import RAGService

load_dotenv()

st.set_page_config(page_title="Setomatic KB RAG Prototype", page_icon="🤖")
st.title("SpyderWash Technical Support Agent (Prototype)")

groq_api_key = os.environ.get("GROQ_API_KEY")

# Setup Sidebar for config
with st.sidebar:
    st.header("Configuration")
    if not groq_api_key:
        groq_api_key = st.text_input("Groq API Key", type="password")
        if groq_api_key:
            os.environ["GROQ_API_KEY"] = groq_api_key
    else:
        st.success("API Key loaded from .env")
        
    st.markdown("""
    **Architecture:**
    - UI: Streamlit
    - LLM: Groq (llama-3.3-70b-versatile)
    - Embeddings: HuggingFace (all-MiniLM-L6-v2)
    - Vector Store: ChromaDB
    - Backend: LangGraph & FastAPI (API)
    """)

if not groq_api_key:
    st.warning("Please enter your Groq API Key in the sidebar or add it to a .env file to continue.")
    st.stop()

@st.cache_resource
def get_rag_service():
    return RAGService()

with st.spinner("Initializing RAG Service... (Loading documents if needed)"):
    rag_service = get_rag_service()
    if not rag_service.rag_chain:
        st.error("Could not initialize RAG Chain. Please ensure the KB directory contains documents.")
        st.stop()

# Streamlit Chat UI
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt_input := st.chat_input("Ask a troubleshooting question..."):
    st.session_state.messages.append({"role": "user", "content": prompt_input})
    with st.chat_message("user"):
        st.markdown(prompt_input)

    with st.chat_message("assistant"):
        with st.spinner("Retrieving from KB and generating response..."):
            response = rag_service.query(prompt_input)
            answer = response.get("answer", "No answer found.")
            st.markdown(answer)
            
            # Show retrieved sources
            if "context" in response and response["context"]:
                with st.expander("Source Documents"):
                    for i, doc in enumerate(response["context"]):
                        source_name = os.path.basename(doc.metadata.get('source', 'Unknown'))
                        page = doc.metadata.get('page', 'N/A')
                        st.write(f"**Source {i+1}:** {source_name} (Page {page})")
                        st.caption(doc.page_content[:200] + "...")
                    
    st.session_state.messages.append({"role": "assistant", "content": answer})