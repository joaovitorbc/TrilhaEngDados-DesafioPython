"""Transformações em DuckDB com SQL: desaninhamento, tipagem, nulos, deduplicação e junção com PTAX."""
from datetime import date

import duckdb

from . import config


def carregar_raw(con: duckdb.DuckDBPyConnection, caminho) -> None:
    """Carrega o JSON Lines (um PVL por linha, com a lista 'cambios' aninhada)."""
    caminho_sql = str(caminho).replace("'", "''")
    con.execute(
        f"CREATE OR REPLACE TABLE raw_pvl AS "
        f"SELECT * FROM read_json_auto('{caminho_sql}', format='newline_delimited')"
    )


def normalizar(con: duckdb.DuckDBPyConnection, data_inicio: str | None, data_fim: str | None) -> None:
    """UNNEST da lista de câmbios, tipagem, filtro de dólar, nulos, período e deduplicação."""
    moeda, data, taxa = config.CAMPO_MOEDA, config.CAMPO_DATA, config.CAMPO_TAXA

    filtros = [
        "data IS NOT NULL",
        "taxa_sadipem IS NOT NULL",
        "(lower(moeda) LIKE '%dólar%' OR lower(moeda) LIKE '%dolar%' OR lower(moeda) LIKE '%usd%')",
    ]
    # datas validadas com fromisoformat antes de entrar no SQL
    if data_inicio:
        filtros.append(f"data >= DATE '{date.fromisoformat(data_inicio).isoformat()}'")
    if data_fim:
        filtros.append(f"data <= DATE '{date.fromisoformat(data_fim).isoformat()}'")
    where = " AND ".join(filtros)

    con.execute(f"""
        CREATE OR REPLACE TABLE cambio_norm AS
        WITH desaninhado AS (
            SELECT CAST(id_pleito AS VARCHAR) AS id_pleito,
                   CAST(num_pvl AS VARCHAR) AS num_pvl,
                   CAST(interessado AS VARCHAR) AS interessado,
                   UNNEST(cambios) AS c
            FROM raw_pvl
        ),
        tipado AS (
            SELECT id_pleito, num_pvl, interessado,
                   COALESCE(CAST(c."{moeda}" AS VARCHAR), 'DESCONHECIDA') AS moeda,
                   COALESCE(
                       TRY_CAST(LEFT(CAST(c."{data}" AS VARCHAR), 10) AS DATE),
                       TRY_CAST(TRY_STRPTIME(LEFT(CAST(c."{data}" AS VARCHAR), 10), '%d/%m/%Y') AS DATE)
                   ) AS data,
                   TRY_CAST(REPLACE(CAST(c."{taxa}" AS VARCHAR), ',', '.') AS DOUBLE) AS taxa_sadipem
            FROM desaninhado
        ),
        filtrado AS (
            SELECT * FROM tipado WHERE {where}
        )
        SELECT id_pleito,
               COALESCE(num_pvl, 'NAO_INFORMADO') AS num_pvl,
               COALESCE(interessado, 'NAO_INFORMADO') AS interessado,
               moeda, data, taxa_sadipem
        FROM filtrado
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY id_pleito, data, taxa_sadipem ORDER BY id_pleito
        ) = 1
    """)


def datas_distintas(con: duckdb.DuckDBPyConnection) -> list[date]:
    return [r[0] for r in con.execute(
        "SELECT DISTINCT data FROM cambio_norm ORDER BY data").fetchall()]


def carregar_ptax(con: duckdb.DuckDBPyConnection, linhas: list[dict]) -> None:
    con.execute("CREATE OR REPLACE TABLE ptax (data DATE, ptax_compra DOUBLE, ptax_venda DOUBLE)")
    if linhas:
        con.executemany(
            "INSERT INTO ptax VALUES (?, ?, ?)",
            [(l["data"], l["ptax_compra"], l["ptax_venda"]) for l in linhas],
        )


def juntar(con: duckdb.DuckDBPyConnection) -> None:
    """Junta câmbio do Sadipem com a PTAX do dia e calcula as diferenças."""
    con.execute("""
        CREATE OR REPLACE TABLE final AS
        SELECT c.id_pleito, c.num_pvl, c.interessado, c.moeda, c.data, c.taxa_sadipem,
               p.ptax_compra, p.ptax_venda,
               ROUND(c.taxa_sadipem - p.ptax_compra, 4) AS dif_vs_compra,
               ROUND(c.taxa_sadipem - p.ptax_venda, 4) AS dif_vs_venda,
               ROUND((c.taxa_sadipem / p.ptax_venda - 1) * 100, 4) AS dif_pct_vs_venda
        FROM cambio_norm c
        LEFT JOIN ptax p ON p.data = c.data
    """)
