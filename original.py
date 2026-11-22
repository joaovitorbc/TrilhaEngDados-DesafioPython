"""
Compara as taxas de câmbio (USD) das PVLs do Espírito Santo
com a PTAX do Banco Central no mesmo dia e salva em Parquet.
Requer Python 3.10+ e: pip install requests pandas pyarrow
"""
import time
from datetime import date, datetime

import pandas as pd
import requests

URL_TESOURO = "https://apidatalake.tesouro.gov.br/ords/cdwhprd/sadipem/tt/"
URL_BCB = "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
HEADERS = {"Accept": "application/json", "User-Agent": "Python-Requests/1.0"}
TIMEOUT = 30
INTERVALO_TESOURO = 1.1  # a API do Tesouro permite 1 requisição por segundo
INTERVALO_BCB = 0.3
ARQUIVO_SAIDA = "comparacao_cambio_usd.parquet"


session = requests.Session()
session.headers.update(HEADERS)
_ultima_chamada = {"tesouro": 0.0, "bcb": 0.0}


def get_json(url: str, params: dict | None, origem: str, intervalo: float) -> dict | None:
    """GET com controle de intervalo entre chamadas e tratamento de erro."""
    espera = intervalo - (time.monotonic() - _ultima_chamada[origem])
    if espera > 0:
        time.sleep(espera)
    _ultima_chamada[origem] = time.monotonic()
    try:
        resp = session.get(url, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"Erro em {url} {params or ''}: {exc}")
        return None


def fetch_all_tesouro(endpoint: str, params: dict | None = None) -> list[dict]:
    """Lê todas as páginas de um endpoint do Sadipem (paginação via link 'next')."""
    url = URL_TESOURO + endpoint
    itens: list[dict] = []
    while url:
        data = get_json(url, params, "tesouro", INTERVALO_TESOURO)
        if not data:
            break
        itens.extend(data.get("items", []))
        url = next((l["href"] for l in data.get("links", []) if l.get("rel") == "next"), None)
        params = None  # o link 'next' já traz os parâmetros
    return itens


def get_pvls(uf: str, tipo_interessado: str = "Estado") -> list[dict]:
    return fetch_all_tesouro("pvl", {"uf": uf, "tipo_interessado": tipo_interessado})


def e_dolar(item: dict) -> bool:
    moeda = str(item.get("moeda", "")).lower()
    return moeda == "dólar dos eua"


def get_cambios_usd(id_pleito) -> list[dict]:
    cambios = fetch_all_tesouro("opc-taxa-cambio", {"id_pleito": id_pleito})
    return [c for c in cambios if e_dolar(c)]


def parse_data(valor) -> date | None:
    texto = str(valor)[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            pass
    return None


def get_ptax(dia: date, cache: dict) -> dict | None:
    """PTAX de fechamento do dia ('mm-dd-yyyy' com aspas simples). Usa cache para não repetir chamadas. None em fim de semana/feriado."""
    if dia in cache:
        return cache[dia]
    params = {
        "@dataCotacao": f"'{dia:%m-%d-%Y}'",
    }
    data = get_json(URL_BCB + "CotacaoDolarDia(dataCotacao=@dataCotacao)", params, "bcb", INTERVALO_BCB)
    valores = (data or {}).get("value", [])
    # se houver mais de um boletim no dia, usa o último (fechamento)
    cache[dia] = max(valores, key=lambda v: v["dataHoraCotacao"]) if valores else None
    return cache[dia]


def salvar_parquet(linhas: list[dict], caminho: str) -> None:
    df = pd.DataFrame(linhas)
    df["data"] = pd.to_datetime(df["data"])  # tipo data, não texto
    df["num_pvl"] = df["num_pvl"].astype("string")
    df["interessado"] = df["interessado"].astype("string")
    df.to_parquet(caminho, engine="pyarrow", compression="snappy", index=False)
    print(f"{len(df)} linhas salvas em {caminho}")


def main() -> None:
    uf = "ES"
    pvls = get_pvls(uf)
    print(f"{len(pvls)} PVLs da UF {uf} (Estado) encontradas")

    cache_ptax: dict = {}
    linhas: list[dict] = []

    for pvl in pvls:
        id_pleito = pvl.get("id_pleito")
        if not id_pleito:
            continue

        for c in get_cambios_usd(id_pleito):
            dia = parse_data(c.get("data_taxa_cambio"))
            taxa_raw = c.get("taxa_cambio")
            if dia is None or taxa_raw is None:
                continue

            taxa = float(str(taxa_raw).replace(",", "."))
            ptax = get_ptax(dia, cache_ptax)
            compra = float(ptax["cotacaoCompra"]) if ptax else None
            venda = float(ptax["cotacaoVenda"]) if ptax else None

            linhas.append({
                "id_pleito": id_pleito,
                "num_pvl": pvl.get("num_pvl"),
                "interessado": pvl.get("interessado"),
                "data": dia,
                "taxa_sadipem": taxa,
                "ptax_compra": compra,
                "ptax_venda": venda,
                "dif_vs_compra": round(taxa - compra, 4) if compra is not None else None,
                "dif_vs_venda": round(taxa - venda, 4) if venda is not None else None,
                "dif_pct_vs_venda": round((taxa / venda - 1) * 100, 4) if venda else None,
            })

    if not linhas:
        print("Nenhuma taxa em dólar encontrada.")
        return

    salvar_parquet(linhas, ARQUIVO_SAIDA)


if __name__ == "__main__":
    main()
