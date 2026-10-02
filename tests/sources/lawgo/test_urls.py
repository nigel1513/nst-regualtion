from datetime import date

from reg.sources.lawgo import ids, urls


def test_law_and_article_pages():
    assert urls.law_page("국가연구개발혁신법") == "https://www.law.go.kr/법령/국가연구개발혁신법"
    assert urls.article_page("law", "국가연구개발혁신법", "a32.p1") == "https://www.law.go.kr/법령/국가연구개발혁신법/제32조"
    assert (urls.article_page("law", "공공기관의 운영에 관한 법률", "a11-2")
            == "https://www.law.go.kr/법령/공공기관의%20운영에%20관한%20법률/제11조의2")
    assert (urls.article_page("admrul", "영장심의위원회 운영세칙", "a2")
            == "https://www.law.go.kr/행정규칙/영장심의위원회%20운영세칙/제2조")
    assert urls.article_page("law", "가법", "supp@2020-01-01") is None
    assert urls.page_for("admrul", "가") == "https://www.law.go.kr/행정규칙/가"


def test_special_characters_are_percent_encoded():
    u = urls.law_page("과학기술분야 정부출연연구기관 등의 설립·운영 및 육성에 관한 법률")
    assert u.endswith("설립%C2%B7운영%20및%20육성에%20관한%20법률") and " " not in u


def test_jo_code_and_label():
    assert urls.jo_code("a32") == "003200" and urls.jo_code("a11-2.p1") == "001102" and urls.jo_code("c1") is None
    assert urls.article_label("a11-2.p1") == "제11조의2" and urls.article_label("body3") is None


def test_drf_and_annex_links_never_carry_oc():
    assert urls.drf_xml("law", "287535") == "https://www.law.go.kr/DRF/lawService.do?target=law&MST=287535&type=XML"
    assert urls.drf_html("admrul", "2100000285346") == (
        "https://www.law.go.kr/DRF/lawService.do?target=admrul&ID=2100000285346&type=HTML")
    assert urls.annex_page("law", "18272187", "287535") == (
        "https://www.law.go.kr/LSW/lsBylInfoP.do?bylSeq=18272187&lsiSeq=287535")
    assert urls.annex_page("admrul", "3220087", "2100000278740") == (
        "https://www.law.go.kr/LSW/admRulBylInfoP.do?bylSeq=3220087&admRulSeq=2100000278740&admFlag=0")
    assert urls.file_url("/LSW/flDownload.do?flSeq=1") == "https://www.law.go.kr/LSW/flDownload.do?flSeq=1"
    assert urls.file_url(None) is None
    assert urls.law_edition_page("국가연구개발혁신법", "21421", date(2026, 3, 10)) == (
        "https://www.law.go.kr/법령/국가연구개발혁신법/(21421,20260310)")
    for u in (urls.drf_xml("law", "1"), urls.annex_page("law", "1", "2")):
        assert "OC=" not in u


def test_ids():
    assert ids.master_id("law", "009402") == "009402" and ids.master_id("admrul", "75386") == "admrul:75386"
    assert ids.work_id_for("009402") == "kr/law/009402" and ids.work_id_for("admrul:75386") == "kr/admrul/75386"
    assert ids.family_of("admrul:1") == "admrul" and ids.family_of("009402") == "law"
