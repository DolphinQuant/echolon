"""
US Futures Session Configuration
================================

Trading session configuration for US futures (CME Globex).

CME Globex trading hours (Eastern Time):
- Sunday 6:00 PM - Friday 5:00 PM (nearly continuous)
- Daily maintenance: 5:00 PM - 6:00 PM ET

Session breakdown:
- Pre-market: 6:00 PM - 9:30 AM (next day)
- Regular hours: 9:30 AM - 4:00 PM
- After-hours: 4:00 PM - 5:00 PM
- Maintenance break: 5:00 PM - 6:00 PM

Key considerations:
- Spans midnight (crosses_midnight=True for evening session)
- Different liquidity during regular vs extended hours
- Regular hours have tighter spreads
- Consider limiting trading to regular hours for better execution

Note: This is a skeleton for future implementation.
"""

from datetime import time
from echolon.config.markets.core.types import SessionWindow

# TODO: Define session constants (future work):
# - EVENING_SESSION = SessionWindow("evening", time(18,0), time(9,30), crosses_midnight=True)
# - REGULAR_SESSION = SessionWindow("regular", time(9,30), time(16,0))
# - AFTER_HOURS = SessionWindow("after_hours", time(16,0), time(17,0))
# - ALL_SESSIONS = [EVENING_SESSION, REGULAR_SESSION, AFTER_HOURS]
