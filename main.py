import os
import asyncio
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query

# Carrega variáveis do ficheiro .env
load_dotenv()

API_SECRET_KEY = os.getenv("API_SECRET_KEY", "demo_token_123")

app = FastAPI(
    title="API Unificada: Saúde, IBGE e Financeiro",
    description="Consolida indicadores demográficos do IBGE, estatísticas reais de saúde (CNES), dados macroeconômicos e indicadores calculados de cobertura em saúde.",
    version="1.3.0"
)

# Mapeamento Oficial do Tipo de Unidade do CNES (DataSUS)
CNES_TIPOS_UNIDADE = {
    "1": "Posto de Saúde",
    "01": "Posto de Saúde",
    "2": "Centro de Saúde / Unidade Básica",
    "02": "Centro de Saúde / Unidade Básica",
    "4": "Policlínica",
    "04": "Policlínica",
    "5": "Hospital Especializado",
    "05": "Hospital Especializado",
    "7": "Hospital Geral",
    "07": "Hospital Geral",
    "20": "Pronto Atendimento",
    "22": "Consultório Isolado",
    "36": "Clínica / Centro Especializado",
    "39": "Unidade Móvel Terrestre",
    "40": "Unidade Móvel Pré-Hospitalar (SAMU)",
    "43": "Farmácia",
    "60": "Laboratório Central (LACEN)",
    "67": "Laboratório de Patologia / Citopatologia",
    "70": "Centro de Atenção Psicossocial (CAPS)",
    "73": "Unidade de Acolhimento"
}

IBGE_API = "https://servicodados.ibge.gov.br/api/v1"
BCB_SGS_API = "https://api.bcb.gov.br/dados/serie/bcdata.sgs"
CNES_API = "https://apidadosabertos.saude.gov.br/cnes/estabelecimentos"

@app.get("/")
def home():
    return {"status": "online", "docs": "/docs"}

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

    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
        try:
            # Requisições assíncronas em paralelo
            ibge_task = client.get(f"{IBGE_API}/localidades/municipios/{codigo_ibge}")
            populacao_task = client.get(f"{IBGE_API}/pesquisas/37/resultados/{codigo_ibge}")
            selic_task = client.get(f"{BCB_SGS_API}.11/dados/ultimos/1?formato=json")
            cnes_task = client.get(
                CNES_API,
                params={"codigo_municipio": codigo_ibge_6dig, "limit": 50}
            )

            ibge_res, pop_res, selic_res, cnes_res = await asyncio.gather(
                ibge_task, populacao_task, selic_task, cnes_task, return_exceptions=True
            )

            # 1. Dados do Município (IBGE)
            municipio_info = ibge_res.json() if isinstance(ibge_res, httpx.Response) and ibge_res.status_code == 200 else {}
            if not municipio_info or "id" not in municipio_info:
                raise HTTPException(status_code=404, detail="Município não encontrado com o código IBGE fornecido.")

            # População Residente (Estimativa IBGE)
            populacao_estimada = None
            if isinstance(pop_res, httpx.Response) and pop_res.status_code == 200:
                try:
                    pop_json = pop_res.json()
                    populacao_estimada = int(pop_json[0]["res"][0]["res"]["2021"])
                except Exception:
                    populacao_estimada = None

            # 2. Selic (Banco Central)
            selic_data = selic_res.json() if isinstance(selic_res, httpx.Response) and selic_res.status_code == 200 else []
            selic_val = selic_data[0]["valor"] if selic_data else "N/A"

            # 3. Saúde (CNES)
            resumo_tipos = {}
            amostra_estabelecimentos = []
            total_estabelecimentos = 0

            if isinstance(cnes_res, httpx.Response) and cnes_res.status_code == 200:
                cnes_json = cnes_res.json()
                estabelecimentos = cnes_json.get("estabelecimentos", cnes_json if isinstance(cnes_json, list) else [])
                total_estabelecimentos = len(estabelecimentos)

                for est in estabelecimentos:
                    if isinstance(est, dict):
                        cod_tipo = str(
                            est.get("codigo_tipo_unidade") or
                            est.get("tp_unidade") or
                            est.get("tipo_unidade") or
                            "Outros"
                        )
                        
                        # Tradução do código para o nome amigável
                        nome_tipo = CNES_TIPOS_UNIDADE.get(cod_tipo, f"Outros ({cod_tipo})")
                        resumo_tipos[nome_tipo] = resumo_tipos.get(nome_tipo, 0) + 1

                        nome_fantasia = est.get("nome_fantasia") or est.get("no_fantasia") or "Não Informado"
                        codigo_cnes = est.get("codigo_cnes") or est.get("co_cnes") or "N/A"

                        if len(amostra_estabelecimentos) < 5:
                            amostra_estabelecimentos.append({
                                "cnes": codigo_cnes,
                                "nome_fantasia": nome_fantasia,
                                "tipo_unidade": nome_tipo
                            })

            # 4. Indicadores Calculados
            estabelecimentos_por_10k = None
            if populacao_estimada and populacao_estimada > 0:
                estabelecimentos_por_10k = round((total_estabelecimentos / populacao_estimada) * 10000, 2)

            dados_consolidados = {
                "municipio": {
                    "codigo_ibge": codigo_ibge,
                    "nome": municipio_info.get("nome"),
                    "uf": municipio_info.get("microrregiao", {}).get("mesorregiao", {}).get("UF", {}).get("sigla"),
                    "regiao": municipio_info.get("microrregiao", {}).get("mesorregiao", {}).get("UF", {}).get("regiao", {}).get("nome"),
                    "populacao_estimada": populacao_estimada
                },
                "indicadores_macroeconomicos": {
                    "fonte": "Banco Central do Brasil",
                    "taxa_selic_atual": f"{selic_val}%"
                },
                "indicadores_saude_cnes": {
                    "fonte": "DataSUS / CNES - Ministério da Saúde",
                    "total_estabelecimentos_consultados": total_estabelecimentos,
                    "densidade_saude": {
                        "estabelecimentos_por_10k_hab": estabelecimentos_por_10k if estabelecimentos_por_10k else "Indisponível"
                    },
                    "distribuicao_tipos_unidade": resumo_tipos,
                    "amostra_estabelecimentos": amostra_estabelecimentos
                }
            }

            return {
                "status": "sucesso",
                "data": dados_consolidados
            }

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erro ao processar dados integrados: {str(e)}")