# tests/core/test_parse_annex_inline.py
"""별표·별지 머리가 `【】`·`■ [ ]`로 쓰이거나 글 중간에 붙은 경우 (같은 문서 별표 미해석 4,596건의 원인).

예문은 실제 원문 줄(KARI·NIMS·KIMS·KRISS·ETRI·KAERI 등)을 줄여 쓴 것이다."""
from reg.core.model import Block
from reg.core.parse import annex_heading, parse_blocks


def _doc(*lines):
    return parse_blocks([Block(t) for t in lines])


def _annexes(d):
    return [(p.path, p.label, p.heading) for p in d.provisions if p.unit == "annex"]


# ---- 줄머리 머리: 【 】, ■ [ ], 가지번호 '-' ----

def test_kari_lenticular_bracket_forms_after_last_supplement():
    d = _doc("명예연구위원등임용기준", "제1조(목적) 이 기준은 명예연구위원 등의 임용에 관한 사항을 정한다.",
             "부 칙 <2017. 5. 26.>", "제1조(시행일) 이 기준은 공포한 날부터 시행한다.",
             "【별지 제1호 서식】", "(명예연구위원·명예정책위원·명예연구원) 위촉 추천서", "한국항공우주연구원장 귀하",
             "【별지 제2호 서식】", "(명예연구위원·명예정책위원·명예연구원) 위촉 동의서")
    assert d.get("supp@2017-05-26/a1").text == "이 기준은 공포한 날부터 시행한다."  # 부칙이 서식을 삼키지 않는다
    assert _annexes(d) == [("form1", "별지 제1호", None), ("form2", "별지 제2호", None)]
    assert d.get("form1").text.startswith("(명예연구위원·명예정책위원·명예연구원) 위촉 추천서")


def test_lenticular_heading_with_title_inside_and_amendment_note():
    d = _doc("자산관리규정", "제1조(목적) 자산 관리를 정한다.", "부 칙", "제1조(시행일) 이 규정은 2024년 1월 1일부터 시행한다.",
             "【별표 제1호_자산 분류체계】", "자산 분류체계",
             "【별지 제2호 서식】(개정 2018. 5.29)", "인수인계 신청서",
             "【 별지 제 3 호 】(개정 2021.8.2)", "휴대용 저장매체 등록 신청서",
             "【별지 제5-1호 서식】(삭제 2018. 5.29)")
    assert _annexes(d) == [("annex1", "별표 제1호", "자산 분류체계"), ("form2", "별지 제2호", None),
                           ("form3", "별지 제3호", None), ("form5", "별지 제5-1호", None)]
    assert d.get("form2").annotations == ["(개정 2018. 5.29)"]
    assert d.get("form3").annotations == ["(개정 2021.8.2)"]
    assert d.get("form5").annotations == ["(삭제 2018. 5.29)"]


def test_square_bullet_bracket_forms_and_hyphen_branch_number():
    d = _doc("이해충돌방지지침", "제1조(목적) 이해충돌 방지를 정한다.", "부 칙", "이 지침은 2022년 12월 1일부터 시행한다.",
             "■ [별지 제1호 서식]", "사적이해관계자 신고 및 회피 신청서",
             "■ [별지 제4-1호] <개정 2023. 10. 17.>", "위원 회피 신청서",
             "■ [별표 제13호] 위원 회피 신청서")
    # '제4-1호'는 참조 추출과 같게 form4로 둔다 (같은 번호가 또 나오면 form4~2)
    assert _annexes(d) == [("form1", "별지 제1호", None), ("form4", "별지 제4-1호", None),
                           ("annex13", "별표 제13호", "위원 회피 신청서")]
    assert d.get("form4").annotations == ["<개정 2023. 10. 17.>"]
    assert d.get("supp#1").text == "이 지침은 2022년 12월 1일부터 시행한다."


def test_annex_heading_tuple_for_new_shapes():
    assert annex_heading("【별지 제1호 서식】") == ("form", 1, None, "")
    assert annex_heading("【별표 1】 임원 및 보직자 청렴행동 수칙") == ("annex", 1, None, "임원 및 보직자 청렴행동 수칙")
    assert annex_heading("【별지 제7호서식_휴대용 저장매체 불용처리 확인서】") == ("form", 7, None, "휴대용 저장매체 불용처리 확인서")
    assert annex_heading("■ [별지 제4-2호]") == ("form", 4, None, "")
    assert annex_heading("[별지 제2호] (4쪽 중 1쪽)") == ("form", 2, None, "(4쪽 중 1쪽)")  # 예전대로
    assert annex_heading("【별지 제2호 서식공무수행 세부일정표】") == ("form", 2, None, "공무수행 세부일정표")  # KARI


# ---- 본문 인용은 머리가 아니다 ----

def test_citations_at_line_start_are_not_headings():
    for t in ("【별지 제1호 서식】에 의한 계약을 체결한다.", "【별표 제2호】의 지급기준 이내로 지급하며,",
              "【별지 제1호 서식】을 작성하여 기관 공문과 함께 제출한다.", "[별표 1]의 기준에 따른다.",
              "[별표 제2호]에 따른 문책 정도의 순위", "<별지 2>를 작성하여 인사담당부서에 신청하여야 한다.",
              "별지 제1호 서식에 따라 신청한다.", "[별지 제5호 서식] 재심청구서에 의거 재심을 청구할 수 있다.",
              "[별지 제3호] 용역업체 보안교육 대장에 참여자를 기록하여야 한다.",
              "[별지 제2호 서식] 승인서로 통보하여야 한다.", "[별표 제3호] 징계의 감경기준에 따라 징계를 감경할 수 있다.",
              "【별지 제2호 서식】의 비상소집결과보고서에 의하여"):
        assert annex_heading(t) is None, t


def test_citation_line_inside_article_stays_in_article():
    d = _doc("징계요령", "제1조(목적) 징계를 정한다.", "제2조(감경) 징계위원회는 다음에 해당하는 경우에는",
             "[별표 제3호] 징계의 감경기준에 따라 징계를 감경할 수 있다.", "제3조(위임) 원장이 정한다.")
    assert _annexes(d) == []
    assert "징계의 감경기준에 따라" in d.get("a2").text and d.get("a3") is not None


# ---- 글 중간의 머리: 서식이 끝난 자리·부칙이 끝난 자리에 붙은 경우만 나눈다 ----

def test_inline_heading_after_sentence_end_is_split():
    d = _doc("사업단운영규정", "제1조(목적) 사업단 운영을 정한다.", "부 칙 <2021. 10. 18.>",
             "제1조(시행일) 이 규정은 공포한 날부터 시행한다. 【별지 제1호 서식_고용계약서】 고용계약서 성 명 업 종")
    assert d.get("supp@2021-10-18/a1").text == "이 규정은 공포한 날부터 시행한다."
    assert _annexes(d) == [("form1", "별지 제1호", "고용계약서")]
    assert d.get("form1").text == "고용계약서 성 명 업 종"
    d = _doc("청렴행동수칙운영지침", "제1조(목적) 수칙을 정한다.", "부 칙",
             "이 지침은 2020년 11월 20일부터 시행한다. 【별표 1】 임원 및 보직자 청렴행동 수칙",
             "임원 및 보직자가 직무를 수행함에 있어 다음 사항을 준수하고 이행한다.")
    assert d.get("supp#1").text == "이 지침은 2020년 11월 20일부터 시행한다."
    assert _annexes(d) == [("annex1", "별표 제1호", "임원 및 보직자 청렴행동 수칙")]


def test_inline_heading_after_form_signature_is_split():
    d = _doc("교원임용기준", "제1조(목적) 교원 임용을 정한다.", "부 칙", "이 기준은 공포한 날부터 시행한다.",
             "【별지 제1호서식】 교원 신규임용 신청서", "신 청 인 성 명 : (인) 【별지 제2호서식】 교원 임용연장 신청서",
             "연구보안소위원회 귀중 ■ [별지 제3호] 기피 신청서")
    assert [p for p, _, _ in _annexes(d)] == ["form1", "form2", "form3"]
    assert d.get("form1").text == "신 청 인 성 명 : (인)"
    assert d.get("form2").text == "연구보안소위원회 귀중"


def test_inline_citations_are_not_split():
    for line in ("② 특수사업직원은 당해 사업의 계약기간의 범위 내에서 【별지 제1호 서식】에 의한 계약을 체결한다.",
                 "② 사용자그룹 등록을 위해서는【별지 제1호 서식】을 작성하여 기관 공문과 함께 제출한다.",
                 "3. 개인별 교육훈련실적기록부(【별지 제3호 서식】)",
                 "여 영상자료를 검색 후 【별지 제4호 서식】,【별지 제5호 서식】의 영상자료 주문",
                 "붙 임 :【별표 제4호】해외출장(파견)시 보안준수사항 1부",
                 "접수된 신청서는 최소 7일 전까지 [별지 제2호 서식] 승인서로 통보하여야 한다.",
                 "보안교육을 진행할 경우 담당부서는 [별지 제3호] 용역업체 보안교육 대장에 참여자를 기록하여야 한다.",
                 "배출된 폐기물은 별도의 전용 보관소에 보관하여야 한다.[별표6]",
                 "타 정상 등을 참작하여 [별표 제1호] 징계양정기준, [별표 제1호의2] 금품 징계양정",
                 "발명을 한 직원 등은 [별표 제1호] 직무발명신고서, [별표 제4호] 프로그램등록신청서를 제출하여야 한다."):
        d = _doc("규정", "제1조(목적) 정한다.", "제2조(절차) " + line)
        assert _annexes(d) == [], line


def test_heading_shapes_seen_in_real_files():
    assert annex_heading("[별표1: 주요사업 비목별 계상기준]") == ("annex", 1, None, "주요사업 비목별 계상기준")  # KFRI
    assert annex_heading("<별지 제3호 서식> 이 력 서") == ("form", 3, None, "이 력 서")  # KFRI: '이'는 조사가 아니다
    assert annex_heading("[별표 제4호] 가.감산평정기준 (별표 제3호에서 이동 및 개정 2020.9.11.)")[:3] == ("annex", 4, None)
    assert annex_heading("【별표 2-2】신용평가등급에 의한 경영상태 평가") == ("annex", 2, None, "신용평가등급에 의한 경영상태 평가")
    assert annex_heading("[별표 제1-4호] 음주운전 징계기준 <개정 2019.12.26., 2024.10.04.) <별표 호 이동: 기존 1-3호에서")[:3] \
        == ("annex", 1, None)
    assert annex_heading("[별표 3] (삭제 2016. 8. 1)-수의계약에 의할 수 있는 경우")[:3] == ("annex", 3, None)  # KISTI
    assert annex_heading("<별표2 개정 2008.3.18, 2008.10.21>") is None  # 조문 끝 개정 주석 (KFRI 여비규정)
    assert annex_heading("[별표 7], [별표 8], [별표 9], [별표10] 신설 <개정 2022.09.26.>") is None  # 개정 기록


def test_runs_of_headings_on_one_line_are_split():
    d = _doc("지침", "제1조(목적) 정한다.", "부 칙", "이 규정은 2020년 4월 22일부터 시행한다. [별표1] 삭제 <1999.06.30> "
             "[별표2] 삭제 <1999.06.30> [별표3] 삭제 <2020.04.20>", "[별표4] 위원회 운영 기준")
    assert [p for p, _, _ in _annexes(d)] == ["annex1", "annex2", "annex3", "annex4"]
    assert d.get("annex1").heading == "삭제" and d.get("annex1").annotations == ["<1999.06.30>"]
    d = _doc("보안업무규정", "제1조(목적) 정한다.", "부 칙", "이 규정은 공포한 날부터 시행한다.",
             "【별지 제8호 서식_비밀・암호자재취급 서약서】 【별지 제9호 서식】(삭제 2021. 7.12)", "서약서 본문")
    assert _annexes(d) == [("form8", "별지 제8호", "비밀・암호자재취급 서약서"), ("form9", "별지 제9호", None)]
    assert d.get("form9").annotations == ["(삭제 2021. 7.12)"] and d.get("form9").text == "서약서 본문"


def test_amendment_note_and_trailing_citation_are_not_split():
    for line in ("항공운임은 별표2의 구분에 의하여 실비액을 지급한다. <별표2 개정 2008.3.18, 2008.10.21>",
                 "월 1회 이상 야간에 불시 보안점검을 실시할 수 있다.[별지 제36호 서",
                 "사실과 그 사유를 문서로 지원조직에 제출하여야 한다. [별지 제8호서식]",
                 "일부를 다음과 같이 개정한다. [별표1〕직무분장표 중 \"미래창조과학부\"를 \"과학기술정보통신부\"로 한다."):
        d = _doc("규정", "제1조(목적) 정한다.", "제2조(지급) " + line)
        assert _annexes(d) == [], line
