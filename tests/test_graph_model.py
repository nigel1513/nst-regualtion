from reg.graph.model import extract_terms, full_label, is_definition_article, unit_label, uses_terms


def test_unit_labels():
    assert unit_label("paragraph", "①") == "제1항" and unit_label("paragraph", "⑳") == "제20항"
    assert unit_label("item", "3.") == "제3호" and unit_label("item", "4의2.") == "제4호의2"
    assert unit_label("subitem", "가.") == "가목" and unit_label("subitem", "1)") == "1)"
    assert unit_label("article", "제27조의2") == "제27조의2" and unit_label("supplement", "부칙") == "부칙"


def test_full_label_skips_chapters():
    chain = [("chapter", "제5장"), ("article", "제27조"), ("paragraph", "①")]
    assert full_label("여비규정", chain) == "여비규정 제27조 제1항"
    assert full_label("여비규정", [("annex", "별표 1")]) == "여비규정 별표 1"


def test_extract_terms_variants():
    assert extract_terms('"출장"이란 공무로 여행하는 것을 말한다.') == [("출장", '"출장"이란 공무로 여행하는 것을 말한다')]
    assert [n for n, _ in extract_terms("“고시금액”이라 함은 법에 따른 금액을 말한다.")] == ["고시금액"]
    assert [n for n, _ in extract_terms("1. ‘여비’란 운임을 말하고, 2. '일비'란 일당을 말한다.")] == ["여비", "일비"]
    assert extract_terms("이 규정에서 사용하는 용어의 정의는 다음과 같다.") == []
    assert extract_terms('(이하 "법"이라 한다)에 따른다.') == []  # 약칭 정의는 용어 정의가 아니다


def test_definition_article_and_uses():
    assert is_definition_article("article", "정의") and is_definition_article("article", "용어의 정의")
    assert not is_definition_article("paragraph", "정의") and not is_definition_article("article", "목적")
    assert uses_terms("출장자는 여비를 받는다.", ["출장", "여비", "일비", "출"]) == ["출장", "여비"]


def test_definition_with_nested_quotes():
    t = '"추정가격"이라 함은 「국가를 당사자로 하는 계약에 관한 법률」(이하 "법"이라 한다) 제4조에 따른 가격을 말한다.'
    assert [n for n, _ in extract_terms(t)] == ["추정가격"]


def test_definition_without_malhanda_does_not_swallow_the_next_term():
    t = '1. "연구원"이란 직원을 포함한다. 2. "출장"이란 근무지 밖에 가는 것을 말한다.'
    assert [n for n, _ in extract_terms(t)] == ["출장"]


def test_forms_get_their_own_label():
    """PostgreSQL은 별지 서식도 unit='annex'로 두고 경로만 form…으로 구분한다 — 그래프에서는 Form으로 나눈다."""
    from reg.graph.model import node_label

    assert node_label("annex", "form2") == "Form" and node_label("annex", "annex1") == "Annex"
    assert node_label("article", "a3") == "Article" and node_label("chapter", "c1") == "Chapter"
