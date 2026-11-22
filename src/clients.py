"""Clientes HTTP: retentativas com backoff, rate-limit por origem e paginação ORDS."""
import time
from datetime import date

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config

HEADERS = {"Accept": "application/json", "User-Agent": "Python-Requests/1.0"}
_ultima_chamada = {"tesouro": 0.0, "bcb": 0.0}


def _criar_session() -> requests.Session:
    retry = Retry(
        total=config.MAX_RETRIES,
        backoff_factor=2,  # espera 2, 4, 8, 16... segundos
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
        raise_on_status=False,  # após esgotar, raise_for_status levanta o erro
    )
    s = requests.Session()
    s.headers.update(HEADERS)
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


session = _criar_session()


def get_json(url: str, params: dict | None, origem: str, intervalo: float) -> dict:
    """GET respeitando o intervalo mínimo por origem. Propaga erros para o chamador."""
    espera = intervalo - (time.monotonic() - _ultima_chamada[origem])
    if espera > 0:
        time.sleep(espera)
    _ultima_chamada[origem] = time.monotonic()

    resp = session.get(url, params=params, timeout=config.TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def fetch_all_tesouro(endpoint: str, params: dict | None = None) -> list[dict]:
    """Lê todas as páginas de um endpoint do Sadipem (paginação via link 'next')."""
    url = config.URL_TESOURO + endpoint
    itens: list[dict] = []
    while url:
        data = get_json(url, params, "tesouro", config.INTERVALO_TESOURO)
        itens.extend(data.get("items", []))
        url = next((l["href"] for l in data.get("links", []) if l.get("rel") == "next"), None)
        params = None  # o link 'next' já traz os parâmetros
    return itens


def get_pvls(uf: str, tipo_interessado: str) -> list[dict]:
    return fetch_all_tesouro("pvl", {"uf": uf, "tipo_interessado": tipo_interessado})


def get_cambios(id_pleito) -> list[dict]:
    return fetch_all_tesouro("opc-taxa-cambio", {"id_pleito": id_pleito})


def get_ptax(dia: date) -> dict | None:
    """PTAX de fechamento do dia. None em fim de semana e feriado."""
    params = {
        "@dataCotacao": f"'{dia:%m-%d-%Y}'",
        "$format": "json",
        "$select": "cotacaoCompra,cotacaoVenda,dataHoraCotacao",
    }
    data = get_json(
        config.URL_BCB + "CotacaoDolarDia(dataCotacao=@dataCotacao)",
        params, "bcb", config.INTERVALO_BCB,
    )
    valores = data.get("value", [])
    # se houver mais de um boletim no dia, usa o último (fechamento)
    return max(valores, key=lambda v: v["dataHoraCotacao"]) if valores else None
