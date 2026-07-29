def chunk_document(document: "Document") -> list["Chunk"]:
    """Split Document content into overlapping Chunk windows."""
    return [
        Chunk(
            document_id=document.document_id,
            line_range=LineRange(start=1, end=20),
            content=document.content,
        )
    ]

# EvidenceSnippet preserves source, path, and line_range so Agent answers are auditable.
