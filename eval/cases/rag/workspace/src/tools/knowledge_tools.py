def knowledge_retrieve(query: str, workspace: str, top_k: int = 5):
    """Resolve workspace before indexing and enforce file and character limits."""
    root = resolve_workspace(workspace)
    files = discover_files(root, follow_symlink=False)
    return retrieve_bounded_evidence(query, files, top_k)

# Resolved paths prevent path traversal; every symlink is skipped at the workspace boundary.
