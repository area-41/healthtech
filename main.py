import os
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional
import urllib.parse

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import httpx
#from cachetools import TTLCache
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
import time
from fastapi import FastAPI
from scalar_fastapi import get_scalar_api_reference

# Estrutura simples de cache em memória
_cache = {}
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("healthtech_api")

API_SECRET_KEY = os.getenv("API_SECRET_KEY", "demo_token_123")
IBGE_API = "https://servicodados.ibge.gov.br/api/v1"
IBGE_V3_API = "https://servicodados.ibge.gov.br/api/v3"
BCB_SGS_API = "https://api.bcb.gov.br/dados/serie/bcdata.sgs"

CNES_TIPOS_UNIDADE = {
    "1": "Posto de Saúde",
    "2": "Centro de Saúde / Unidade Básica",
    "4": "Policlínica",
    "7": "Hospital Geral",
    "22": "Consultório Isolado",
    "36": "Clinica / Centro Especializado",
    "70": "Unidade de Pronto Atendimento (UPA)"
}

# Cache simples em memória usando dicionários nativos
cache_24h = {}
cache_1h = {}

def get_cached(cache_dict: dict, key: str, ttl_seconds: int):
    if key in cache_dict:
        val, timestamp = cache_dict[key]
        if time.time() - timestamp < ttl_seconds:
            return val
        else:
            del cache_dict[key]
    return None

def set_cached(cache_dict: dict, key: str, value: any):
    cache_dict[key] = (value, time.time())

scheduler = AsyncIOScheduler()

def get_from_cache(key: str, ttl_seconds: int = 3600):
    """Recupera valor do cache se ainda estiver válido."""
    if key in _cache:
        val, timestamp = _cache[key]
        if time.time() - timestamp < ttl_seconds:
            return val
        else:
            del _cache[key]
    return None

def set_in_cache(key: str, value: any):
    """Salva valor no cache com o timestamp atual."""
    _cache[key] = (value, time.time())

async def sync_macro_data_background():
    logger.info("Sincronizando Selic em background...")
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
            res = await client.get(f"{BCB_SGS_API}.432/dados/ultimos/1?formato=json")
            if res.status_code == 200 and res.json():
                selic_val = f"{res.json()[0]['valor']}%"
                cache_24h["selic_atual"] = selic_val
    except Exception as e:
        logger.error(f"Erro ao sincronizar Selic: {str(e)}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(sync_macro_data_background, 'cron', hour=3, minute=0)
    scheduler.start()
    asyncio.create_task(sync_macro_data_background())
    yield
    scheduler.shutdown()

app = FastAPI(
    title="Healthtech API",
    description="Saúde, IBGE e Indicadores Financeiros Unificados",
    version="1.0.0",
    lifespan=lifespan
)

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def serve_index():
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    return {"status": "online", "docs": "/docs"}

# ==========================================
# PARSERS CORRIGIDOS
# ==========================================
async def fetch_municipio_ibge(client: httpx.AsyncClient, codigo_ibge: str) -> Optional[Dict[str, Any]]:
    cache_key = f"ibge_{codigo_ibge}"
    if cache_key in cache_24h:
        return cache_24h[cache_key]

    try:
        res = await client.get(f"{IBGE_API}/localidades/municipios/{codigo_ibge}")
        if res.status_code == 200:
            data = res.json()
            if data and "id" in data:
                cache_24h[cache_key] = data
                return data
    except Exception as e:
        logger.warning(f"Erro ao consultar município IBGE: {e}")
    return None

async def fetch_populacao_ibge(client: httpx.AsyncClient, codigo_ibge: str) -> Optional[int]:
    cache_key = f"pop_{codigo_ibge}"
    if cache_key in cache_24h:
        return cache_24h[cache_key]

    populacao = None

    # Método 1: Censo 2022 (Agregado 4714 / Variável 93 - População residente)
    try:
        url_censo = f"{IBGE_V3_API}/agregados/4714/periodos/2022/variaveis/93?localidades=N6%5B{codigo_ibge}%5D"
        res_censo = await client.get(url_censo)
        if res_censo.status_code == 200:
            data_censo = res_censo.json()
            if isinstance(data_censo, list) and len(data_censo) > 0:
                resultados = data_censo[0].get("resultados", [])
                if resultados:
                    series = resultados[0].get("series", [])
                    if series:
                        serie_val = series[0].get("serie", {})
                        if serie_val:
                            val = list(serie_val.values())[0]
                            if str(val).isdigit():
                                populacao = int(val)
    except Exception as e:
        logger.warning(f"Falha ao consultar Censo 2022 IBGE: {e}")

    # Método 2: Pesquisa 37 (Varredura recursiva de chaves de resultado)
    if not populacao:
        try:
            res = await client.get(f"{IBGE_API}/pesquisas/37/resultados/{codigo_ibge}")
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list):
                    for item in data:
                        for res_elem in item.get("res", []):
                            sub_res = res_elem.get("res", {})
                            if isinstance(sub_res, dict):
                                for k, v in sub_res.items():
                                    val_clean = str(v).replace(".", "").replace(" ", "").strip()
                                    if val_clean.isdigit() and int(val_clean) > 1000:
                                        populacao = int(val_clean)
                                        break
                            if populacao:
                                break
                        if populacao:
                            break
        except Exception as e:
            logger.warning(f"Falha na Pesquisa 37: {e}")

    if populacao:
        cache_24h[cache_key] = populacao

    return populacao

async def fetch_selic_meta(client: httpx.AsyncClient) -> str:
    if "selic_atual" in cache_24h:
        return cache_24h["selic_atual"]

    try:
        res = await client.get(f"{BCB_SGS_API}.432/dados/ultimos/1?formato=json")
        if res.status_code == 200:
            selic_data = res.json()
            if selic_data and len(selic_data) > 0:
                val = f"{selic_data[0]['valor']}%"
                cache_24h["selic_atual"] = val
                return val
    except Exception as e:
        logger.warning(f"Falha ao consultar Selic: {e}")

    return "13.75%"

async def fetch_cnes_saude(client: httpx.AsyncClient, codigo_ibge_6dig: str) -> Dict[str, Any]:
    cache_key = f"cnes_{codigo_ibge_6dig}"
    if cache_key in cache_1h:
        return cache_1h[cache_key]

    resultado = {"total": 0, "tipos": {}, "amostra": []}

    headers_cnes = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://cnes.datasus.gov.br",
        "Referer": "https://cnes.datasus.gov.br/pages/estabelecimentos/consulta.jsp"
    }

    try:
        url_cnes = f"https://cnes.datasus.gov.br/services/estabelecimentos?municipio={codigo_ibge_6dig}&limit=100&offset=0"
        res = await client.get(url_cnes, headers=headers_cnes)
        if res.status_code == 200:
            estabelecimentos = res.json()
            if isinstance(estabelecimentos, list) and len(estabelecimentos) > 0:
                resultado["total"] = len(estabelecimentos)
                for est in estabelecimentos:
                    if isinstance(est, dict):
                        # Extrai o tipo de unidade tratando chaves string/int
                        tp_cod = str(
                            est.get("tpUnidade") or 
                            est.get("codigo_tipo_unidade") or 
                            est.get("tp_unidade") or "1"
                        )
                        nome_tipo = CNES_TIPOS_UNIDADE.get(tp_cod, "Outros / Clínica")
                        resultado["tipos"][nome_tipo] = resultado["tipos"].get(nome_tipo, 0) + 1

                        # Extrai o código CNES numérico de 7 dígitos
                        cnes_num = str(
                            est.get("cnes") or 
                            est.get("coCnes") or 
                            est.get("co_cnes") or 
                            est.get("codigo_cnes") or "N/A"
                        )

                        if len(resultado["amostra"]) < 5:
                            resultado["amostra"].append({
                                "cnes": cnes_num,
                                "nome_fantasia": est.get("noFantasia") or est.get("no_fantasia") or est.get("nome_fantasia") or "Unidade de Saúde",
                                "tipo_unidade": nome_tipo
                            })
                cache_1h[cache_key] = resultado
                return resultado
    except Exception as e:
        logger.warning(f"CNES DataSUS indisponível para {codigo_ibge_6dig}: {e}")

    return resultado

@app.get("/api/v1/relatorio-municipio/{codigo_ibge}")
async def get_combined_report(
    codigo_ibge: str,
    api_key: str = Query(..., description="Chave de acesso da API")
):
    if api_key != API_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Chave de API inválida.")

    codigo_ibge_6dig = codigo_ibge[:6]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }

    async with httpx.AsyncClient(timeout=15.0, headers=headers, follow_redirects=True) as client:
        ibge_info, populacao, selic_val, cnes_info = await asyncio.gather(
            fetch_municipio_ibge(client, codigo_ibge),
            fetch_populacao_ibge(client, codigo_ibge),
            fetch_selic_meta(client),
            fetch_cnes_saude(client, codigo_ibge_6dig)
        )

        if not ibge_info or "id" not in ibge_info:
            raise HTTPException(status_code=404, detail="Município não encontrado com o código IBGE fornecido.")

        estabelecimentos_por_10k = None
        if populacao and populacao > 0 and cnes_info["total"] > 0:
            estabelecimentos_por_10k = round((cnes_info["total"] / populacao) * 10000, 2)

        dados_consolidados = {
            "municipio": {
                "codigo_ibge": codigo_ibge,
                "nome": ibge_info.get("nome"),
                "uf": ibge_info.get("microrregiao", {}).get("mesorregiao", {}).get("UF", {}).get("sigla"),
                "regiao": ibge_info.get("microrregiao", {}).get("mesorregiao", {}).get("UF", {}).get("regiao", {}).get("nome"),
                "populacao_estimada": populacao if populacao else "Não informada pelo IBGE"
            },
            "indicadores_macroeconomicos": {
                "fonte": "Banco Central do Brasil",
                "taxa_selic_atual": selic_val
            },
            "indicadores_saude_cnes": {
                "fonte": "DataSUS / CNES - Ministério da Saúde",
                "total_estabelecimentos_consultados": cnes_info["total"],
                "densidade_saude": {
                    "estabelecimentos_por_10k_hab": estabelecimentos_por_10k if estabelecimentos_por_10k is not None else "Indisponível"
                },
                "distribuicao_tipos_unidade": cnes_info["tipos"],
                "amostra_estabelecimentos": cnes_info["amostra"]
            }
        }

        return {
            "status": "sucesso",
            "data": dados_consolidados
        }

@app.get("/scalar", include_in_schema=False)
async def scalar_html():
    return get_scalar_api_reference(
        openapi_url=app.openapi_url,
        title=app.title + " - Scalar",
    )