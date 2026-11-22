# Câmbio dos PVLs do Espírito Santo x PTAX do Banco Central

Compara a taxa de câmbio em dólar usada nos PVLs (API Sadipem, Tesouro Nacional) com a PTAX de fechamento do Banco Central no mesmo dia.

## Como executar

```bash
chmod +x run.sh
./run.sh
```

Ou manualmente:
```bash
pip install -r requirements.txt
python main.py
```

Configure os parâmetros copiando `.env.example` para `.env`.

## Estrutura
- `src/config.py`: parâmetros lidos de variáveis de ambiente.
- `src/clients.py`: chamadas HTTP com retentativas (backoff, `Retry-After`) e rate-limit por origem.
- `src/transform.py`: SQL no DuckDB (UNNEST da lista de câmbios, tipagem, filtro de dólar, nulos, período, deduplicação, JOIN com PTAX).
- `src/quality.py`: schema, razão de nulos, unicidade da chave e intervalos. Gera `output/relatorio_qualidade.json`.
- `src/storage.py`: Parquet com Snappy, particionado em `output/parquet/ano=AAAA/mes=MM/`.

## Regras de qualidade

| Check | Severidade |
|---|---|
| Schema e tipos esperados | ERRO |
| Nulos em colunas obrigatórias | ERRO |
| Duplicidade de (id_pleito, data, taxa_sadipem) | ERRO |
| Taxa não positiva ou data futura | ERRO |
| Nulos acima de 50% nas colunas de PTAX | ALERTA |
| PTAX venda fora de 0,5 a 20 ou diferença acima de 20% | ALERTA |
Com status ERRO, o Parquet não é gravado. O relatório é gravado sempre.

## Leitura do resultado
```python
import duckdb
duckdb.sql("SELECT * FROM 'output/parquet/**/*.parquet' LIMIT 10").show()
``
