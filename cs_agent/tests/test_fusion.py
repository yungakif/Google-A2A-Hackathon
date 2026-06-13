from fusion import reciprocal_rank_fusion


def test_item_in_both_lists_ranks_first():
    bm25 = ["a", "b", "c"]
    vec = ["b", "d", "a"]
    # scores: b=1/62+1/61, a=1/61+1/63, d=1/62, c=1/63  ->  b > a > d > c
    assert reciprocal_rank_fusion([bm25, vec]) == ["b", "a", "d", "c"]


def test_top_k_truncates():
    assert reciprocal_rank_fusion([["a", "b", "c", "d"]], top_k=2) == ["a", "b"]


def test_empty_rankings():
    assert reciprocal_rank_fusion([[], []]) == []


def test_single_ranking_preserves_order():
    assert reciprocal_rank_fusion([["x", "y", "z"]]) == ["x", "y", "z"]
