from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from datetime import date, datetime

import requests


class APIClient:
    """Base para clientes HTTP: sessão, timeout, erros e intervalo entre chamadas."""

    HEADERS = {"Accept": "application/json", "User-Agent": "Python-Requests/1.0"}

    def __init__(self, base_url: str, intervalo: float = 0.0, timeout: int = 30):
        self.base_url = base_url.rstrip("/") + "/"
        self.intervalo = intervalo
        self.timeout = timeout
        self._ultima_chamada = 0.0
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    def _aguardar(self) -> None:
        espera = self.intervalo - (time.monotonic() - self._ultima_chamada)
        if espera > 0:
            time.sleep(espera)
        self._ultima_chamada = time.monotonic()

    def get(self, url: str, params: dict | None = None) -> dict | None:
        self._aguardar()
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            print(f"Erro em {url}: {exc}")
            return None


class TesouroSadipem(APIClient):
    """Endpoints do Sadipem (Tesouro Nacional). Limite de 1 requisição por segundo."""

    def __init__(self):
        super().__init__("https://apidatalake.tesouro.gov.br/ords/cdwhprd/sadipem/tt/",
                         intervalo=1.1)

    def _paginar(self, endpoint: str, params: dict | None = None) -> list[dict]:
        url = self.base_url + endpoint
        itens: list[dict] = []
        while url:
            data = self.get(url, params)
            if not data:
                break
            itens.extend(data.get("items", []))
            url = next((l["href"] for l in data.get("links", []) if l.get("rel") == "next"), None)
            params = None  # o link 'next' já traz os parâmetros
        return itens

    def pvls(self, uf: str = "ES", tipo_interessado: str = "Estado") -> list[dict]:
        return self._paginar("pvl", {"uf": uf, "tipo_interessado": tipo_interessado})

    def cambios(self, id_pleito: int) -> list[dict]:
        return self._paginar("opc-taxa-cambio", {"id_pleito": id_pleito})


@dataclass(frozen=True)
class Ptax:
    data: date
    compra: float
    venda: float


class BancoCentralPTAX(APIClient):
    """PTAX de fechamento do dólar, com cache por dia."""

    def __init__(self):
        super().__init__("https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/",
                         intervalo=0.3)
        self._cache: dict[date, Ptax | None] = {}

    def do_dia(self, dia: date) -> Ptax | None:
        if dia not in self._cache:
            params = {
                "@dataCotacao": f"'{dia:%m-%d-%Y}'"   # formato exigido pela API do BCB
            }
            data = self.get(self.base_url + "CotacaoDolarDia(dataCotacao=@dataCotacao)", params)
            valores = (data or {}).get("value", [])
            if valores:
                ult = max(valores, key=lambda v: v["dataHoraCotacao"])  # último boletim do dia
                self._cache[dia] = Ptax(dia, float(ult["cotacaoCompra"]), float(ult["cotacaoVenda"]))
            else:
                self._cache[dia] = None  # fim de semana ou feriado
        return self._cache[dia]


@dataclass
class Comparacao:
    id_pleito: int
    num_pvl: str | None
    interessado: str | None
    data: date
    taxa_sadipem: float
    ptax: Ptax | None

    @property
    def dif_vs_compra(self) -> float | None:
        return round(self.taxa_sadipem - self.ptax.compra, 4) if self.ptax else None

    @property
    def dif_vs_venda(self) -> float | None:
        return round(self.taxa_sadipem - self.ptax.venda, 4) if self.ptax else None

    @property
    def dif_pct_vs_venda(self) -> float | None:
        return round((self.taxa_sadipem / self.ptax.venda - 1) * 100, 4) if self.ptax else None

    def to_dict(self) -> dict:
        return {
            "id_pleito": self.id_pleito,
            "num_pvl": self.num_pvl,
            "interessado": self.interessado,
            "data": self.data.isoformat(),
            "taxa_sadipem": self.taxa_sadipem,
            "ptax_compra": self.ptax.compra if self.ptax else None,
            "ptax_venda": self.ptax.venda if self.ptax else None,
            "dif_vs_compra": self.dif_vs_compra,
            "dif_vs_venda": self.dif_vs_venda,
            "dif_pct_vs_venda": self.dif_pct_vs_venda,
        }


class ComparadorCambio:
    # Ajuste conforme os campos reais de /opc-taxa-cambio
    CAMPO_MOEDA = "moeda"
    CAMPO_DATA = "data_taxa_cambio"
    CAMPO_TAXA = "taxa_cambio"

    def __init__(self, tesouro: TesouroSadipem, bc: BancoCentralPTAX):
        self.tesouro = tesouro
        self.bc = bc

    @classmethod
    def _e_dolar(cls, item: dict) -> bool:
        moeda = str(item.get(cls.CAMPO_MOEDA, "")).lower()
        return moeda == "dólar dos eua"

    @staticmethod
    def _parse_data(valor) -> date | None:
        texto = str(valor)[:10]
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(texto, fmt).date()
            except ValueError:
                pass
        return None

    def executar(self, uf: str = "ES") -> list[Comparacao]:
        resultados: list[Comparacao] = []
        for pvl in self.tesouro.pvls(uf=uf):
            id_pleito = pvl.get("id_pleito")
            if not id_pleito:
                continue
            for c in self.tesouro.cambios(id_pleito):
                if not self._e_dolar(c):
                    continue
                dia = self._parse_data(c.get(self.CAMPO_DATA))
                taxa_raw = c.get(self.CAMPO_TAXA)
                if dia is None or taxa_raw is None:
                    continue
                resultados.append(Comparacao(
                    id_pleito=id_pleito,
                    num_pvl=pvl.get("num_pvl"),
                    interessado=pvl.get("interessado"),
                    data=dia,
                    taxa_sadipem=float(str(taxa_raw).replace(",", ".")),
                    ptax=self.bc.do_dia(dia),
                ))
        return resultados

    @staticmethod
    def salvar_csv(comparacoes: list[Comparacao], caminho: str) -> None:
        if not comparacoes:
            print("Nenhuma taxa em dólar encontrada.")
            return
        linhas = [c.to_dict() for c in comparacoes]
        with open(caminho, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=linhas[0].keys())
            writer.writeheader()
            writer.writerows(linhas)
        print(f"{len(linhas)} linhas salvas em {caminho}")


if __name__ == "__main__":
    comparador = ComparadorCambio(TesouroSadipem(), BancoCentralPTAX())
    resultados = comparador.executar(uf="ES")
    comparador.salvar_csv(resultados, "comparacao_cambio_es_usd.csv")
