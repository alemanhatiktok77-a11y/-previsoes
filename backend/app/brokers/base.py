"""BROKER ADAPTER — interface independente de corretora.

Regras do projeto:
  * Nenhuma corretora é presumida como tendo API de negociação.
  * Proibido: engenharia reversa, uso de sessões privadas, scraping ou automação de cliques.
  * Execução real só com: adaptador baseado em API OFICIAL documentada + flag de aprovação legal
    + validação de segurança. Nenhum adaptador real é fornecido neste projeto.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.models import Trade


@dataclass(frozen=True)
class BrokerCapabilities:
    name: str
    real_money: bool
    official_api_docs: str           # URL da documentação oficial (obrigatório para adaptadores reais)
    supports_binary_options: bool
    supports_otc: bool


class BrokerAdapter(ABC):
    capabilities: BrokerCapabilities

    @abstractmethod
    def open_trade(self, trade: Trade, price: float) -> Trade: ...

    @abstractmethod
    def settle_trade(self, trade: Trade, exit_price: float) -> Trade: ...

    @abstractmethod
    def balance(self) -> float: ...


class RealExecutionDisabled(RuntimeError):
    pass


class BrokerRegistry:
    def __init__(self):
        self._adapters: dict = {}

    def register(self, adapter: BrokerAdapter, *, legal_approval: bool = False, security_review: bool = False):
        cap = adapter.capabilities
        if cap.real_money:
            if not cap.official_api_docs.startswith("https://"):
                raise RealExecutionDisabled("Adaptador real exige documentação oficial da API")
            if not (legal_approval and security_review):
                raise RealExecutionDisabled("Execução real bloqueada: falta aprovação legal e validação de segurança")
        self._adapters[cap.name] = adapter

    def get(self, name: str) -> BrokerAdapter:
        return self._adapters[name]

    def list(self) -> list:
        return [{"name": a.capabilities.name, "real_money": a.capabilities.real_money} for a in self._adapters.values()]
