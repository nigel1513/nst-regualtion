# src/reg/core/extract/layout.py
"""쪽 배치 판정 (M6-6): 두 쪽 모아찍기(가로 용지에 세로 쪽 두 개) 가르기, 머리글·꼬리글 줄 판정.

pdfplumber(줄 추출)와 pypdfium2(별표 그림) 양쪽에서 쓰도록 상자 목록만 받는 순수 함수로 둔다.
"""
import re

PAGE_NO = re.compile(r"^[-–]\s*\d+\s*[-–]$|^\d+\s*/\s*\d+$|^\d{1,3}$")
# '- 3 - 연구관리요령', '보안업무요령 - 28 -': 쪽번호 표시가 낀 짧은 머리글·꼬리글 줄
# 쪽번호 표시 앞뒤는 공백이어야 한다: '2024-03-01', '042-860-1234'의 '-03-'은 쪽번호가 아니다
PAGE_NO_WITH_TITLE = re.compile(r"^(?:\S.{0,40}?\s)?[-–]\s?\d{1,3}\s?[-–](?:\s.{0,40}\S)?$")
# 별표·부칙·조·장 머리 줄은 쪽마다 비슷해 보여도(별지 제1호 서식, 별지 제2호 서식 …) 머리글이 아니다
STRUCTURAL = re.compile(r"^[<\[〈【(]?\s*(?:별\s*표|별\s*지|부\s*칙|제\s*\d+\s*(?:조|장|절))")


def two_up_gutter(boxes: list[tuple[float, float]], width: float, height: float) -> float | None:
    """가로 용지의 가운데 세로 띠를 가로지르는 글자 상자가 2% 이하이고 양쪽에 글이 있으면 가운데 x를 돌려준다."""
    if width <= height or len(boxes) < 20:
        return None
    mid = width / 2
    left = sum(1 for _, x1 in boxes if x1 <= mid)
    right = sum(1 for x0, _ in boxes if x0 >= mid)
    cross = sum(1 for x0, x1 in boxes if x0 < mid - 3 and x1 > mid + 3)
    if left >= 10 and right >= 10 and cross <= 0.02 * len(boxes):
        return mid
    return None


def running_key(text: str) -> str:
    """머리글·꼬리글 비교용 키: 공백을 지우고 숫자를 #으로 (쪽마다 바뀌는 쪽번호를 같은 줄로 본다)."""
    return re.sub(r"\d+", "#", re.sub(r"\s", "", text))


def is_page_number_line(text: str) -> bool:
    t = text.strip()
    return bool(PAGE_NO.match(t) or PAGE_NO_WITH_TITLE.match(t))


def is_structural(text: str) -> bool:
    return bool(STRUCTURAL.match(text.strip()))
