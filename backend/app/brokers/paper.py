"""PaperBroker — corretora simulada. Nenhum dinheiro real envolvido."""
from __future__ import annotations

from app.brokers.base import BrokerAdapter, BrokerCapabilities
from app.core.models import Direction, Trade, TradeStatus, now_ms


class PaperBroker(BrokerAdapter):
    capabilities = BrokerCapabilities(name="paper", real_money=False, official_api_docs="", supports_binary_options=True, supports_otc=False)

    def __init__(self, initial_capital: float = 1000.0):
        self.initial = initial_capital
        self.cash = initial_capital
        self.reserved = 0.0

    def balance(self) -> float:
        return round(self.cash, 2)

    def open_trade(self, trade: Trade, price: float) -> Trade:
        if trade.stake > self.cash:
            trade.status, trade.cancel_reason = TradeStatus.CANCELLED, "capital simulado insuficiente"
            return trade
        self.cash -= trade.stake
        self.reserved += trade.stake
        trade.entry_price, trade.status = price, TradeStatus.OPEN
        return trade

    def settle_trade(self, trade: Trade, exit_price: float) -> Trade:
        if trade.status != TradeStatus.OPEN:
            return trade
        trade.exit_price = exit_price
        self.reserved -= trade.stake
        if exit_price == trade.entry_price:
            trade.status, trade.pnl = TradeStatus.DRAW, 0.0
            self.cash += trade.stake
        else:
            win = (exit_price > trade.entry_price) == (trade.direction == Direction.CALL)
            if win:
                trade.status, trade.pnl = TradeStatus.WIN, round(trade.stake * trade.payout, 2)
                self.cash += trade.stake + trade.pnl
            else:
                trade.status, trade.pnl = TradeStatus.LOSS, -trade.stake
        trade.closed_ms = now_ms()
        return trade

    def cancel(self, trade: Trade, reason: str) -> Trade:
        if trade.status == TradeStatus.OPEN:
            self.cash += trade.stake
            self.reserved -= trade.stake
        trade.status, trade.cancel_reason, trade.closed_ms = TradeStatus.CANCELLED, reason, now_ms()
        return trade

    def reset(self, capital: float | None = None):
        self.initial = capital or self.initial
        self.cash, self.reserved = self.initial, 0.0
