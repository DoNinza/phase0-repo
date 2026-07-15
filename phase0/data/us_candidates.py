"""미국주식 섹터 후보 종목 (2026-07-15, KOSPI candidate_batch.py와 분리).

주의(candidate_batch.DEFAULT_CANDIDATES와 동일한 한계): 시가총액 상위
대형주를 손으로 고른 플레이스홀더다 — 진짜 시점 유니버스(과거 그 시점에
실제로 거래 가능했던 종목, 상장폐지·인수합병 포함)가 아니라 "현재 대형주"를
과거 10년에 소급 적용한 것이므로 생존편향이 있다. KOSPI 쪽과 마찬가지로
배치 파이프라인 자체를 실제 데이터로 검증하기 위한 목록이다.
"""

from __future__ import annotations

DEFAULT_CANDIDATES: list[str] = [
    "AAPL",   # Apple
    "MSFT",   # Microsoft
    "GOOGL",  # Alphabet
    "AMZN",   # Amazon
    "NVDA",   # NVIDIA
    "META",   # Meta Platforms
    "TSLA",   # Tesla
    "JPM",    # JPMorgan Chase
    "V",      # Visa
    "JNJ",    # Johnson & Johnson
    "WMT",    # Walmart
    "PG",     # Procter & Gamble
    "UNH",    # UnitedHealth Group
    "HD",     # Home Depot
    "MA",     # Mastercard
    "DIS",    # Disney
    "BAC",    # Bank of America
    "XOM",    # Exxon Mobil
    "KO",     # Coca-Cola
    "PFE",    # Pfizer
]
