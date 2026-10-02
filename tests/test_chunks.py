from reg.index.chunks import MAX_CHARS, chunk_version


def P(path, unit, label, text="", heading=None, parent=None):
    return {"path": path, "unit": unit, "label": label, "heading": heading, "text": text, "parent": parent}


def test_article_with_paragraphs_is_one_chunk_with_context():
    provs = [P("c6", "chapter", "제6장", heading="보칙"),
             P("a27", "article", "제27조", heading="출장증빙의 제출", parent="c6"),
             P("a27.p1", "paragraph", "①", "출장자는 7일 이내에 증빙서를 제출하여야 한다.", parent="a27"),
             P("a27.p2", "paragraph", "②", "출장 증빙은 승차권 등으로 한다.", parent="a27")]
    cs = chunk_version("w@2024-01-17", "w", "여비규정", provs)
    assert [c.path for c in cs] == ["a27"]
    assert cs[0].text.startswith("제27조(출장증빙의 제출)") and "① 출장자는 7일" in cs[0].text and "② 출장 증빙은" in cs[0].text
    assert cs[0].context_text == "여비규정 > 제6장 보칙 > 제27조(출장증빙의 제출)"
    assert cs[0].chunk_id == "w@2024-01-17|a27"


def test_long_article_splits_by_paragraph_without_loss():
    body = "가" * 700
    provs = [P("a5", "article", "제5조", heading="활용"),
             P("a5.p1", "paragraph", "①", body, parent="a5"), P("a5.p2", "paragraph", "②", body, parent="a5"),
             P("a5.p2.i1", "item", "1.", "호 본문", parent="a5.p2")]
    cs = chunk_version("v", "w", "규정", provs)
    assert [c.path for c in cs] == ["a5.p1", "a5.p2"]
    assert all(c.text.startswith("제5조(활용)") for c in cs) and "1. 호 본문" in cs[1].text
    assert sum(c.text.count("가") for c in cs) == 1400


def test_long_article_without_paragraphs_is_cut():
    provs = [P("a9", "article", "제9조", "나" * (MAX_CHARS * 2 + 10), heading="긴 조")]
    cs = chunk_version("v", "w", "규정", provs)
    assert [c.path for c in cs] == ["a9#1", "a9#2", "a9#3"]
    assert sum(c.text.count("나") for c in cs) == MAX_CHARS * 2 + 10


def test_supplement_and_annex_chunks():
    provs = [P("a1", "article", "제1조", "목적.", heading="목적"),
             P("supp@2024-01-17", "supplement", "부칙", "이 규정은 2024년 1월 17일부터 시행한다."),
             P("annex1", "annex", "별표 제1호", "국내여비 지급기준표 …", heading="국내여비")]
    cs = chunk_version("v", "w", "규정", provs)
    assert [c.path for c in cs] == ["a1", "supp@2024-01-17", "annex1"]
    assert cs[1].text.startswith("부칙 2024. 1. 17.")
