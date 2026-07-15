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

# 확장 유니버스(2026-07-15) — VCB-Gap의 미국 반전(전 6조합 양수, 그러나
# 표본 353건으로 미달)이 재현되는지 KOSPI 때와 동일한 원칙(유니버스 확대
# 후 재검증, 새 조건 추가 아님)으로 확인하기 위해 추가. 여전히 "시가총액
# 상위 대형주" 손 고른 목록이라는 한계는 DEFAULT_CANDIDATES와 동일 — 완전한
# 시점 유니버스가 아니다.
EXPANDED_CANDIDATES: list[str] = DEFAULT_CANDIDATES + [
    "ORCL", "CRM", "ADBE", "CSCO", "INTC", "AMD", "QCOM", "TXN", "IBM", "NOW",
    "INTU", "AMAT", "MU", "ADI", "LRCX", "PANW", "SNPS", "CDNS", "KLAC", "ANET",
    "ABBV", "MRK", "LLY", "TMO", "ABT", "DHR", "BMY", "AMGN", "GILD", "CVS",
    "MDT", "ISRG", "VRTX", "REGN", "ZTS",
    "WFC", "GS", "MS", "C", "AXP", "SCHW", "BLK", "SPGI", "CB", "PNC",
    "USB", "TFC", "COF", "MET", "AIG",
    "MCD", "NKE", "SBUX", "TGT", "LOW", "COST", "PEP", "MO", "PM", "CL",
    "KMB", "EL", "YUM", "CMG", "TJX",
    "BA", "CAT", "GE", "HON", "UPS", "RTX", "LMT", "DE", "MMM", "UNP",
    "FDX", "NOC", "GD",
    "CVX", "COP", "SLB", "EOG", "PSX", "MPC",
    "NFLX", "CMCSA", "T", "VZ", "TMUS",
    "NEE", "DUK", "SO",
]
