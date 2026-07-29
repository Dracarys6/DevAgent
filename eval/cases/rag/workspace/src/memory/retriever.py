class KeywordRetriever:
    """Rank chunks with deterministic BM25 keyword relevance."""

    def score(self, term_frequency: float, document_frequency: int) -> float:
        inverse_document_frequency = self.idf(document_frequency)
        return term_frequency * inverse_document_frequency

# BM25 combines term frequency, inverse document frequency, and length normalization.
