from research_companion import taxonomy


def test_keywords_basic():
    kw = taxonomy._keywords("Graph Neural Networks for the retrieval task")
    assert "graph" in kw and "neural" in kw and "retrieval" in kw
    assert "for" not in kw and "the" not in kw  # stopwords/short dropped


def test_cluster_is_a_partition_grouping_similar_papers():
    papers = [
        {"title": "Graph neural networks for retrieval", "abstract": "graph neural retrieval embeddings"},
        {"title": "Retrieval with graph neural nets", "abstract": "graph neural retrieval ranking"},
        {"title": "A study of protein folding", "abstract": "protein folding biology structure"},
    ]
    clusters = taxonomy.cluster_papers(papers)
    flat = sorted(i for c in clusters for i in c)
    assert flat == [0, 1, 2]                      # partition: every paper once
    # the two graph-retrieval papers land together; protein paper separate
    same = next(c for c in clusters if 0 in c)
    assert 1 in same and 2 not in same


def test_all_singletons_when_no_overlap():
    papers = [{"title": "alpha beta", "abstract": ""},
              {"title": "gamma delta", "abstract": ""},
              {"title": "epsilon zeta", "abstract": ""}]
    clusters = taxonomy.cluster_papers(papers)
    assert sorted(len(c) for c in clusters) == [1, 1, 1]
