from app.intelligence.documents import CHUNK_OVERLAP, CHUNK_SIZE, split_document


def test_document_chunks_are_bounded_and_keep_overlap():
    source = "A useful evidence sentence with order fulfilment data. " * 120
    chunks = split_document(source)
    assert len(chunks) > 1
    assert all(len(part) <= CHUNK_SIZE for part in chunks)
    for previous, following in zip(chunks, chunks[1:]):
        assert previous[-CHUNK_OVERLAP:] in following


def test_document_chunks_preserve_small_documents():
    assert split_document("  Customer note\n\nRefund delivered after four business days.  ") == [
        "Customer note Refund delivered after four business days."
    ]
