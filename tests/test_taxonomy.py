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


def test_build_taxonomy_keyword_labels_without_llm():
    papers = [
        {"title": "Graph retrieval", "abstract": "graph retrieval", "year": 2020, "id": "x1"},
        {"title": "Graph ranking retrieval", "abstract": "graph retrieval ranking", "year": 2021, "id": "x2"},
        {"title": "Protein folding", "abstract": "protein folding", "year": 2019, "id": "x3"},
    ]
    tree = taxonomy.build_taxonomy(papers, llm=None)
    # partition preserved across groups
    ids = sorted(p["id"] for g in tree for p in g["papers"])
    assert ids == ["x1", "x2", "x3"]
    # a group with the two graph papers has a keyword-derived label
    graph_group = next(g for g in tree if any(p["id"] == "x1" for p in g["papers"]))
    assert graph_group["label"] in ("Graph", "Retrieval")
    assert any(p["id"] == "x2" for p in graph_group["papers"])


def test_build_taxonomy_uses_llm_labels_when_provided():
    papers = [
        {"title": "Graph retrieval", "abstract": "graph retrieval embeddings", "year": 2020, "id": "x1"},
        {"title": "Graph ranking retrieval", "abstract": "graph retrieval ranking", "year": 2021, "id": "x2"},
        {"title": "Protein folding study", "abstract": "protein folding biology structure", "year": 2019, "id": "x3"},
    ]
    tree = taxonomy.build_taxonomy(papers, llm=lambda prompt: "Graph-based Retrieval")
    assert len(tree) == 2  # genuine multi-cluster: not collapsed
    graph_group = next(g for g in tree if any(p["id"] == "x1" for p in g["papers"]))
    assert graph_group["label"] == "Graph-based Retrieval"
    assert any(p["id"] == "x2" for p in graph_group["papers"])


def test_collapse_fallback_single_group_when_all_singletons():
    papers = [{"title": "alpha", "abstract": "", "year": 1, "id": "a"},
              {"title": "beta", "abstract": "", "year": 2, "id": "b"},
              {"title": "gamma", "abstract": "", "year": 3, "id": "c"}]
    tree = taxonomy.build_taxonomy(papers, llm=None)
    assert len(tree) == 1 and tree[0]["label"] == "Related work"
    assert len(tree[0]["papers"]) == 3


def test_collapse_fallback_label_is_related_work_even_with_llm():
    papers = [{"title": "alpha unique", "abstract": "", "year": 1, "id": "a"},
              {"title": "beta distinct", "abstract": "", "year": 2, "id": "b"}]  # all-singletons -> collapse
    tree = taxonomy.build_taxonomy(papers, llm=lambda prompt: "Should Not Be Used")
    assert len(tree) == 1 and tree[0]["label"] == "Related work"
