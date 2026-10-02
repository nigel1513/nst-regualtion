# tests/core/test_quality_report.py
import json

from reg.core.model import ParsedDoc, Prov
from reg.core.quality_report import compare, doc_metrics, glued_words, report, split_words
from tests.core.helpers import load_pdf_version

LEX = {"관하여": 50, "필요한": 80, "사항을": 90, "개인정보보호법": 40, "내자": 9, "구매요령": 9}


def _doc(*provs):
    return ParsedDoc("x", None, [], list(provs))


def test_text_defects_are_counted_by_section():
    d = _doc(Prov("a1", "article", "제1조", "목적", "필요한 사항을 정한다. 보안업무요령 - 28 - 다음"),
             Prov("a2", "article", "제2조", "정의", "설립\U0000f09e운영 및 개인정 보보호법"),
             Prov("a4", "article", "제4조", "기타", "정한다. 제5조(위원회) 위원회를 둔다."),
             Prov("annex1", "annex", "별표 제1호", None, "소 액 구 매 신 청 서 - 3 -"))
    m = doc_metrics(d)
    assert m["body:page_number"] == 1 and m["body:pua"] == 1 and m["body:missed_article"] == 1
    assert m["annex:spaced"] == 1 and m["annex:page_number"] == 1 and m["annexes"] == 1
    assert m["articles_zero"] == 0 and m["article_rate_lt95"] == 1  # a1, a2, a4 → 3/4


def test_glued_counts_only_word_plus_ending_pairs():
    assert glued_words("관하여필요한 사항을", LEX) == 1   # '관하여'(어미 '하여') + '필요한'
    assert glued_words("내자구매요령 사항을", LEX) == 0   # 복합명사는 세지 않는다
    assert split_words("개인정 보보호법", LEX) == 1


def test_compare_flags_only_regressions():
    before = {"text": {"body:pua": 5, "body:glued": 10, "article_rate_mean": 0.98, "versions": 3}}
    after = {"text": {"body:pua": 1, "body:glued": 12, "article_rate_mean": 0.97, "versions": 4}}
    assert compare(before, after) == [("body:glued", 10, 12), ("article_rate_mean", 0.98, 0.97)]


def test_report_reads_db_without_writing(conn, tmp_path):
    from reg.platform.storage.blob import LocalBlobStore

    load_pdf_version(conn, LocalBlobStore(tmp_path), "kasi_form4_p48-49.pdf")
    conn.execute("UPDATE regulation.work_version SET version_state = 'CURRENT'")
    conn.commit()
    r = report(conn, "current")
    assert r["text"]["versions"] == 1 and r["text"]["annexes"] == 2
    assert json.dumps(r, ensure_ascii=False)  # JSON 직렬화 가능
