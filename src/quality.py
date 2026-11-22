"""Validações de qualidade sobre a tabela final e relatório em JSON."""
import json
from datetime import datetime
from pathlib import Path

import duckdb

COLUNAS_ESPERADAS = {
    "id_pleito": "VARCHAR", "num_pvl": "VARCHAR", "interessado": "VARCHAR",
    "moeda": "VARCHAR", "data": "DATE", "taxa_sadipem": "DOUBLE",
    "ptax_compra": "DOUBLE", "ptax_venda": "DOUBLE",
    "dif_vs_compra": "DOUBLE", "dif_vs_venda": "DOUBLE", "dif_pct_vs_venda": "DOUBLE",
}
# nulos esperados quando não há PTAX no dia (fim de semana e feriado)
COLUNAS_PTAX = {"ptax_compra", "ptax_venda", "dif_vs_compra", "dif_vs_venda", "dif_pct_vs_venda"}
LIMITE_NULO_PTAX = 0.5
PTAX_MIN, PTAX_MAX = 0.5, 20.0   # faixa plausível para USD/BRL
DIF_PCT_MAX = 20.0               # diferença percentual acima disso é suspeita


def _check(nome: str, status: str, detalhe: dict) -> dict:
    return {"check": nome, "status": status, "detalhe": detalhe}


def _check_schema(con) -> dict:
    tipos = {linha[0]: linha[1] for linha in con.execute("DESCRIBE final").fetchall()}
    faltando = sorted(c for c in COLUNAS_ESPERADAS if c not in tipos)
    divergentes = {c: tipos[c] for c, t in COLUNAS_ESPERADAS.items()
                   if c in tipos and tipos[c] != t}
    ok = not faltando and not divergentes
    return _check("schema", "OK" if ok else "ERRO",
                  {"faltando": faltando, "tipos_divergentes": divergentes})


def _check_nulos(con, total: int) -> dict:
    ratios = {}
    for col in COLUNAS_ESPERADAS:
        n = con.execute(f"SELECT COUNT(*) FILTER (WHERE {col} IS NULL) FROM final").fetchone()[0]
        ratios[col] = round(n / total, 4)
    obrigatorios = [c for c, r in ratios.items() if c not in COLUNAS_PTAX and r > 0]
    ptax = [c for c, r in ratios.items() if c in COLUNAS_PTAX and r > LIMITE_NULO_PTAX]
    status = "ERRO" if obrigatorios else "ALERTA" if ptax else "OK"
    return _check("null_ratio", status, {
        "ratios": ratios,
        "obrigatorios_com_nulo": obrigatorios,
        "ptax_acima_do_limite": ptax,
    })


def _check_unicidade(con) -> dict:
    dup = con.execute("""
        SELECT COUNT(*) - (SELECT COUNT(*) FROM (
            SELECT DISTINCT id_pleito, data, taxa_sadipem FROM final))
        FROM final
    """).fetchone()[0]
    return _check("unicidade", "OK" if dup == 0 else "ERRO",
                  {"chave": ["id_pleito", "data", "taxa_sadipem"], "duplicadas": dup})


def _check_intervalos(con) -> dict:
    taxa_invalida, ptax_fora, dif_alta, data_futura = con.execute(f"""
        SELECT COUNT(*) FILTER (WHERE taxa_sadipem <= 0),
               COUNT(*) FILTER (WHERE ptax_venda IS NOT NULL
                                AND (ptax_venda < {PTAX_MIN} OR ptax_venda > {PTAX_MAX})),
               COUNT(*) FILTER (WHERE ABS(dif_pct_vs_venda) > {DIF_PCT_MAX}),
               COUNT(*) FILTER (WHERE data > CURRENT_DATE)
        FROM final
    """).fetchone()
    status = "ERRO" if (taxa_invalida or data_futura) else "ALERTA" if (ptax_fora or dif_alta) else "OK"
    return _check("intervalos", status, {
        "taxa_sadipem_nao_positiva": taxa_invalida,
        "ptax_venda_fora_da_faixa": ptax_fora,
        "dif_pct_acima_do_limite": dif_alta,
        "data_futura": data_futura,
    })


def validar(con: duckdb.DuckDBPyConnection, caminho: Path) -> dict:
    total = con.execute("SELECT COUNT(*) FROM final").fetchone()[0]
    checks = [_check("linhas", "OK" if total > 0 else "ERRO", {"linhas": total})]
    if total > 0:
        checks += [
            _check_schema(con),
            _check_nulos(con, total),
            _check_unicidade(con),
            _check_intervalos(con),
        ]

    statuses = [c["status"] for c in checks]
    relatorio = {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "status": "ERRO" if "ERRO" in statuses else "ALERTA" if "ALERTA" in statuses else "OK",
        "linhas": total,
        "checks": checks,
    }
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
    return relatorio
