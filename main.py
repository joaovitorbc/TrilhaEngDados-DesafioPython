"""Pipeline: Sadipem (PVLs e câmbio) + BCB (PTAX) -> DuckDB -> qualidade -> Parquet particionado."""
import json
import sys

import duckdb
import requests

from src import config
from src.clients import get_cambios, get_pvls, get_ptax
from src.quality import validar
from src.storage import gravar_particionado
from src.transform import carregar_ptax, carregar_raw, datas_distintas, juntar, normalizar


def main() -> int:
    saida = config.OUTPUT_DIR
    saida.mkdir(parents=True, exist_ok=True)
    raw_path = saida / "_raw_pvl_cambios.jsonl"

    pvls = get_pvls(config.UF, config.TIPO_INTERESSADO)
    print(f"{len(pvls)} PVLs ({config.UF}, {config.TIPO_INTERESSADO}) encontradas")

    com_cambio = 0
    with raw_path.open("w", encoding="utf-8") as f:
        for pvl in pvls:
            id_pleito = pvl.get("id_pleito")
            if id_pleito is None:
                continue
            cambios = get_cambios(id_pleito)
            com_cambio += bool(cambios)
            registro = {
                "id_pleito": str(id_pleito),
                "num_pvl": pvl.get("num_pvl"),
                "interessado": pvl.get("interessado"),
                "cambios": cambios,
            }
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")

    if com_cambio == 0:
        print("Nenhum PVL com registros de câmbio. Nada a gravar.")
        raw_path.unlink(missing_ok=True)
        return 1

    con = duckdb.connect()
    carregar_raw(con, raw_path)
    raw_path.unlink(missing_ok=True)  # os dados já estão no DuckDB

    normalizar(con, config.DATA_INICIO, config.DATA_FIM)

    linhas_ptax = []
    datas = datas_distintas(con)
    for dia in datas:
        p = get_ptax(dia)  # erro de rede após as retentativas interrompe a execução
        if p:
            linhas_ptax.append({
                "data": dia,
                "ptax_compra": float(p["cotacaoCompra"]),
                "ptax_venda": float(p["cotacaoVenda"]),
            })
    print(f"{len(datas)} datas de câmbio; PTAX encontrada em {len(linhas_ptax)}")

    carregar_ptax(con, linhas_ptax)
    juntar(con)

    relatorio = validar(con, saida / "relatorio_qualidade.json")
    print(f"Qualidade: {relatorio['status']} ({relatorio['linhas']} linhas) "
          f"-> {saida / 'relatorio_qualidade.json'}")
    if relatorio["status"] == "ERRO":
        print("Parquet não gravado por falha crítica de qualidade. Veja o relatório.")
        return 1

    total = gravar_particionado(con, saida / "parquet")
    print(f"{total} linhas gravadas em {saida / 'parquet'} (particionado por ano/mes)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (requests.RequestException, ValueError) as exc:
        print(f"Execução interrompida, nenhum arquivo final foi gravado: {exc}")
        sys.exit(1)
