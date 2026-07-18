from research_companion import store


def _make_pdf(path, pages):
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument.new()
    for _ in range(pages):
        pdf.new_page(200, 200)
    pdf.save(str(path))


def test_counts_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "papers_dir", lambda: tmp_path)
    d = store.paper_dir("arxiv:1")
    _make_pdf(d / "paper.pdf", 3)
    assert store.pdf_page_count("arxiv:1") == 3


def test_none_when_no_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "papers_dir", lambda: tmp_path)
    store.paper_dir("arxiv:2")  # dir exists, no pdf
    assert store.pdf_page_count("arxiv:2") is None
