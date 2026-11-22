"""Gravação em Parquet com Snappy, particionado por ano e mês (ano=AAAA/mes=MM)."""
import shutil
from pathlib import Path

import duckdb


def gravar_particionado(con: duckdb.DuckDBPyConnection, pasta: Path) -> int:
    if pasta.exists():
        shutil.rmtree(pasta)  # evita partições antigas misturadas com as novas
    pasta.parent.mkdir(parents=True, exist_ok=True)

    con.execute(f"""
        COPY (
            SELECT *,
                   CAST(YEAR(data) AS VARCHAR) AS ano,
                   LPAD(CAST(MONTH(data) AS VARCHAR), 2, '0') AS mes
            FROM final
        ) TO '{pasta.as_posix()}' (
            FORMAT PARQUET,
            COMPRESSION SNAPPY,
            PARTITION_BY (ano, mes)
        )
    """)
    return con.execute("SELECT COUNT(*) FROM final").fetchone()[0]
