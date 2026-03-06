from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator
from datetime import datetime

from plain.views import ServerSentEvent, ServerSentEventsView


class ClockView(ServerSentEventsView):
    """Streams the current time every second."""

    async def stream(self) -> AsyncIterator[ServerSentEvent]:
        while True:
            yield ServerSentEvent(data={"time": datetime.now().strftime("%H:%M:%S")})
            await asyncio.sleep(1)


class StockTickerView(ServerSentEventsView):
    """Simulates a stock ticker with random price changes."""

    async def stream(self) -> AsyncIterator[ServerSentEvent]:
        prices = {"ACME": 142.50, "GLOB": 89.30, "WIDG": 213.75}

        while True:
            symbol = random.choice(list(prices.keys()))
            change = round(random.uniform(-2.0, 2.0), 2)
            prices[symbol] = round(prices[symbol] + change, 2)

            yield ServerSentEvent(
                data={
                    "symbol": symbol,
                    "price": prices[symbol],
                    "change": change,
                },
                event="tick",
            )
            await asyncio.sleep(0.5)
