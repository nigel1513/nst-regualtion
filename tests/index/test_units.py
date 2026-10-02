"""M7 §2.1 문서 모델: provision_version 1건 = 문서 1건, 번호 필드, 정식 라벨, 창 분할, 벡터 대상."""
from reg.index.units import article_path, numbers, unit_docs


def test_numbers_table():
    assert numbers("a27-2.p1.i3") == {"article_no": 27, "article_branch": 2, "paragraph_no": 1, "item_no": 3,
                                      "item_branch": 0}
    assert numbers("a5.i2.s가") == {"article_no": 5, "article_branch": 0, "item_no": 2, "item_branch": 0, "subitem": "가"}
    assert numbers("annex3-1") == {"annex_no": 3, "annex_branch": 1}
    assert numbers("form2") == {"annex_no": 2, "annex_branch": 0}
    assert numbers("a27.p1#2")["paragraph_no"] == 1
    assert numbers("a3~2.p1") == {"article_no": 3, "article_branch": 0, "paragraph_no": 1}
    assert numbers("c1") == {}


def test_numbers_skip_supplement():
    assert numbers("supp@2024-01-17/a1") == {}
    assert numbers("supp#3/a2.p1") == {}


def test_article_path():
    assert article_path("a27.p1.i3") == "a27"
    assert article_path("supp#3/a2.p1") == "supp#3/a2"
    assert article_path("supp@2024-01-17/a2.p1") == "supp@2024-01-17/a2"
    assert article_path("annex1") == "annex1"


V = {"id": "v1", "work_id": "kr/reg/KASI/여비규정", "title": "여비규정", "institution": "KASI",
     "institution_name": "한국천문연구원", "institution_aliases": ["천문연"], "kind": "INTERNAL_REG", "state": "CURRENT",
     "effective_from": "2024-01-17", "effective_to": None}
P = [{"id": 1, "path": "c5", "unit": "chapter", "label": "제5장", "heading": "보칙", "text": "", "parent": None},
     {"id": 2, "path": "a27", "unit": "article", "label": "제27조", "heading": "출장증빙의 제출", "text": "", "parent": "c5"},
     {"id": 3, "path": "a27.p1", "unit": "paragraph", "label": "①", "heading": None, "text": "7일 이내에 제출한다.",
      "parent": "a27"},
     {"id": 4, "path": "a27.p1.i3", "unit": "item", "label": "3.", "heading": None, "text": "영수증", "parent": "a27.p1"},
     {"id": 5, "path": "a27.p1.i3.s가", "unit": "subitem", "label": "가.", "heading": None, "text": "카드 영수증",
      "parent": "a27.p1.i3"},
     {"id": 6, "path": "annex1", "unit": "annex", "label": "별표 제1호", "heading": "여비 지급표", "text": "가" * 3000,
      "parent": None},
     {"id": 7, "path": "form1", "unit": "annex", "label": "별지 제1호", "heading": "확인서", "text": "서식", "parent": None},
     {"id": 8, "path": "supp@2024-01-17", "unit": "supplement", "label": "부칙", "heading": None, "text": "",
      "parent": None},
     {"id": 9, "path": "supp@2024-01-17/a1", "unit": "supp_article", "label": "제1조", "heading": "시행일",
      "text": "이 규정은 공포한 날부터 시행한다.", "parent": "supp@2024-01-17"}]


def _by_path(v=V):
    return {d.doc["path"]: d for d in unit_docs(v, P)}


def test_unit_docs_fields():
    docs = _by_path()
    p1 = docs["a27.p1"].doc
    assert p1["doc_id"] == "v1|a27.p1" and p1["pv_id"] == 3 and p1["unit"] == "paragraph"
    assert p1["full_label"] == "여비규정 제27조 제1항" and p1["label"] == "제1항" and p1["marker"] == "①"
    assert p1["breadcrumb"] == "한국천문연구원 > 여비규정 > 제5장 보칙 > 제27조(출장증빙의 제출) > 제1항"
    assert p1["article_key"] == "v1|a27" and p1["article_path"] == "a27" and p1["parent_path"] == "a27"
    assert p1["heading"] == "출장증빙의 제출" and p1["article_no"] == 27 and p1["paragraph_no"] == 1
    assert p1["family"] == "reg" and p1["version_state"] == "CURRENT" and "article_text" not in p1
    assert p1["text"] == "7일 이내에 제출한다."
    art = docs["a27"].doc
    assert art["article_text"] == "제27조(출장증빙의 제출)\n① 7일 이내에 제출한다.\n3. 영수증\n가. 카드 영수증"
    assert art["label"] == "제27조" and art["full_label"] == "여비규정 제27조"
    item = docs["a27.p1.i3"]
    assert item.doc["full_label"] == "여비규정 제27조 제1항 제3호" and item.embed_text is None
    assert item.doc["context"].startswith("제27조(출장증빙의 제출) ① 7일")
    assert docs["a27.p1.i3.s가"].doc["full_label"] == "여비규정 제27조 제1항 제3호 가목"
    assert docs["a27.p1.i3.s가"].doc["subitem"] == "가"
    assert docs["a27.p1"].embed_text == "제27조(출장증빙의 제출)\n① 7일 이내에 제출한다.\n3. 영수증\n가. 카드 영수증"
    assert docs["a27"].embed_text == art["article_text"]
    assert "c5" not in docs


def test_annex_form_and_supplement_units():
    docs = _by_path()
    assert docs["form1#1" if "form1#1" in docs else "form1"].doc["unit"] == "form"
    assert docs["form1"].embed_text is None                       # 서식에는 벡터를 넣지 않는다
    sa = docs["supp@2024-01-17/a1"].doc
    assert sa["full_label"] == "여비규정 부칙(2024. 1. 17.) 제1조" and "article_no" not in sa
    assert sa["article_path"] == "supp@2024-01-17/a1"
    assert docs["annex1#1"].doc["annex_image"].startswith("/api/v1/annex?")


def test_long_units_window_and_only_current_gets_vectors():
    docs = unit_docs(V, P)
    wins = [d for d in docs if d.doc["path"].startswith("annex1#")]
    assert len(wins) == 3 and wins[0].doc["doc_id"] == "v1|annex1#1" and wins[0].doc["window"] == 1
    assert {w.doc["base_path"] for w in wins} == {"annex1"} and wins[1].doc["article_path"] == "annex1"
    assert all(w.embed_text and w.embed_text.startswith("별표 제1호(여비 지급표)\n") for w in wins)
    assert all(len(w.embed_text) <= 1200 for w in wins)
    assert "article_text" in wins[0].doc and "article_text" not in wins[1].doc
    assert all(d.embed_text is None for d in unit_docs({**V, "state": "HISTORICAL"}, P))
    assert all(d.embed_text is None for d in unit_docs({**V, "state": "ABOLISHED"}, P))


def test_mapping_accepts_synonyms_and_userdict(os_url):
    import httpx

    from reg.index.os import OpenSearch

    os = OpenSearch(os_url)
    os.delete_index("reg-provisions-rtest")
    os.create_index("reg-provisions-rtest", 4)
    try:
        r = httpx.post(f"{os_url}/reg-provisions-rtest/_analyze", json={"analyzer": "ko_syn", "text": "출장비"}).json()
        assert "여비" in {t["token"] for t in r["tokens"]}
        for word, want in (("지출결의", "정산"), ("연차", "연가"), ("천문연", "천문")):   # lenient가 규칙을 버리지 않았나
            r = httpx.post(f"{os_url}/reg-provisions-rtest/_analyze", json={"analyzer": "ko_syn", "text": word}).json()
            assert want in {t["token"] for t in r["tokens"]}, (word, r)
        r = httpx.post(f"{os_url}/reg-provisions-rtest/_analyze", json={"analyzer": "ko", "text": "에트리 출장복명서"}).json()
        assert {"에트리", "출장복명서", "복명서"} <= {t["token"] for t in r["tokens"]}
    finally:
        os.delete_index("reg-provisions-rtest")
