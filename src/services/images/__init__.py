"""KB Image Extraction and Retrieval Pipeline.

Modules:
    pdf_prep      - DOCX->PDF conversion
    empty_page    - Empty page detection and skip logic
    case_mapper   - Article boundary -> page range mapping
    extractor     - PyMuPDF image extraction + full-page render fallback
    dedupe        - SHA256 + dimension/aspect deduplication
    captioner     - GPT-4o vision captioning with cache
    search_terms  - Extract searchable terms from captions
    pipeline      - One-shot orchestrator CLI
"""
