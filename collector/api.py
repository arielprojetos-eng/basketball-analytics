"""Cliente enxuto da Basketball API (basketballapi.net), plano gratuito.

Limites do plano gratuito: 10 chamadas por minuto e 100 por dia.
Todas as chamadas passam por aqui para que o orçamento seja contado em um só lugar.
"""
import time

import requests

BASE = "https://api.basketballapi.net/v1"


class ApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message


class QuotaExceeded(ApiError):
    """Cota diária esgotada no servidor."""


class UpgradeRequired(ApiError):
    """Endpoint ou período não liberado no plano gratuito."""


class BudgetExhausted(Exception):
    """Orçamento de chamadas desta execução acabou (controle local)."""


class TransientError(Exception):
    """Instabilidade do servidor ou da rede que persistiu depois das novas tentativas.

    Não é defeito do coletor: a fonte registra o aviso e a execução segue sem marcar falha.
    """


NET_ERRORS = (requests.ConnectionError, requests.Timeout)
RETRY_WAIT = 15  # segundos entre tentativas depois de queda de conexão ou erro 5xx


class Client:
    def __init__(self, key, budget=30, min_interval=6.5, session=None, sleep=time.sleep):
        self.key = key
        self.budget = budget
        self.min_interval = min_interval
        self.session = session or requests.Session()
        self.sleep = sleep
        self.calls = 0
        self._last = 0.0

    def remaining(self):
        return self.budget - self.calls

    def get(self, path, params=None):
        """Devolve (data, meta). Cada tentativa HTTP consome uma chamada do orçamento."""
        for attempt in range(3):
            if self.calls >= self.budget:
                raise BudgetExhausted()
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0 and self._last:
                self.sleep(wait)
            self.calls += 1
            self._last = time.monotonic()
            try:
                resp = self.session.get(
                    BASE + path,
                    params={k: v for k, v in (params or {}).items() if v is not None},
                    headers={"Authorization": f"Bearer {self.key}"},
                    timeout=30,
                )
            except NET_ERRORS as e:
                if attempt < 2:
                    self.sleep(RETRY_WAIT * (attempt + 1))
                    continue
                raise TransientError(f"Basketball API sem resposta: {e}") from e
            if resp.status_code >= 500:
                if attempt < 2:
                    self.sleep(RETRY_WAIT * (attempt + 1))
                    continue
                raise TransientError(f"Basketball API respondeu {resp.status_code}")
            if resp.status_code == 200:
                body = resp.json()
                return body.get("data"), body.get("meta") or {}
            err = {}
            try:
                err = resp.json().get("error") or {}
            except ValueError:
                pass
            code = err.get("code", "unknown")
            msg = err.get("message", resp.text[:200])
            if resp.status_code == 429 and code == "rate_limited" and attempt < 2:
                self.sleep(20)
                continue
            if code == "quota_exceeded":
                raise QuotaExceeded(resp.status_code, code, msg)
            if code == "upgrade_required" or resp.status_code == 403:
                raise UpgradeRequired(resp.status_code, code, msg)
            raise ApiError(resp.status_code, code, msg)
        raise ApiError(429, "rate_limited", "limite por minuto persistente")

    def paginate(self, path, params=None, max_pages=5):
        """Percorre as páginas de uma listagem, respeitando o orçamento."""
        out = []
        page = 1
        while page <= max_pages:
            p = dict(params or {})
            p["page"] = page
            p.setdefault("per_page", 50)
            data, meta = self.get(path, p)
            out.extend(data or [])
            total_pages = meta.get("total_pages")
            has_next = bool(meta.get("next_page")) or (total_pages and page < total_pages)
            if not has_next or not data:
                break
            page += 1
        return out
