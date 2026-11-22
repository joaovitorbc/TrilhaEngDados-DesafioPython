"""Configuração via variáveis de ambiente (arquivo .env opcional)."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

UF = os.getenv("UF", "ES").upper()
TIPO_INTERESSADO = os.getenv("TIPO_INTERESSADO", "Estado")
DATA_INICIO = os.getenv("DATA_INICIO") or None  # AAAA-MM-DD, opcional
DATA_FIM = os.getenv("DATA_FIM") or None        # AAAA-MM-DD, opcional
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))

TIMEOUT = int(os.getenv("TIMEOUT", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "5"))
INTERVALO_TESOURO = float(os.getenv("INTERVALO_TESOURO", "1.1"))  # limite de 1 req/s
INTERVALO_BCB = float(os.getenv("INTERVALO_BCB", "0.3"))

URL_TESOURO = "https://apidatalake.tesouro.gov.br/ords/cdwhprd/sadipem/tt/"
URL_BCB = "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"

# Nomes dos campos na API do Tesouro (confirmar na primeira execução)
CAMPO_MOEDA = os.getenv("CAMPO_MOEDA", "moeda")
CAMPO_DATA = os.getenv("CAMPO_DATA", "data_taxa_cambio")
CAMPO_TAXA = os.getenv("CAMPO_TAXA", "taxa_cambio")
