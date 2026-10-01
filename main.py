import os
import asyncio
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.openapi.docs import get_swagger_ui_html

# Carrega variáveis do ficheiro .env
load_dotenv()

API_SECRET_KEY = os.getenv("API_SECRET_KEY", "demo_token_123")

# Instância ÚNICA do FastAPI (com Swagger padrão desativado)
app = FastAPI(
    title="API Unificada: Saúde, IBGE e Financeiro",
    description="Consolida indicadores demográficos do IBGE, estatísticas reais de saúde (CNES), dados macroeconômicos e indicadores calculados de cobertura em saúde.",
    version="1.3.0",
    docs_url=None
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

# HTML Embutido Diretamente no Servidor
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Healthtech API - Painel Unificado</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body class="bg-slate-900 text-slate-100 min-h-screen font-sans">

    <header class="border-b border-slate-800 bg-slate-950/50 backdrop-blur sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
            <div class="flex items-center gap-3">
                <div class="bg-teal-500 text-slate-950 p-2 rounded-lg font-bold">
                    <i class="fa-solid fa-heart-pulse text-xl"></i>
                </div>
                <div>
                    <h1 class="font-bold text-lg leading-none">Healthtech API</h1>
                    <p class="text-xs text-slate-400">Saúde, IBGE e Indicadores Financeiros</p>
                </div>
            </div>
            <div class="flex items-center gap-4 text-sm">
                <a href="/docs" target="_blank" class="text-slate-300 hover:text-teal-400 transition">Swagger UI</a>
                <a href="/scalar" target="_blank" class="text-slate-300 hover:text-teal-400 transition">Scalar Docs</a>
            </div>
        </div>
    </header>

    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        
        <section class="bg-slate-800/60 border border-slate-700/60 rounded-xl p-6 shadow-xl">
            <h2 class="text-xl font-semibold text-slate-100 mb-4 flex items-center gap-2">
                <i class="fa-solid fa-magnifying-glass text-teal-400"></i> Consultar Município
            </h2>
            <form id="searchForm" class="grid grid-cols-1 md:grid-cols-3 gap-4">
                
                <div class="relative">
                    <label class="block text-xs text-slate-400 mb-1">Buscar Município (Nome ou Código)</label>
                    <input type="text" id="municipioInput" value="São Paulo - SP" placeholder="Digite a cidade (ex: Porto Alegre)" required autocomplete="off"
                        class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-slate-100 focus:outline-none focus:border-teal-400">
                    <input type="hidden" id="codigoIbge" value="3550308">
                    <div id="suggestions" class="absolute left-0 right-0 top-full mt-1 bg-slate-800 border border-slate-700 rounded-lg max-h-48 overflow-y-auto hidden z-50 shadow-2xl"></div>
                </div>

                <div>
                    <label class="block text-xs text-slate-400 mb-1">Chave de API (API Key)</label>
                    <input type="password" id="apiKey" value="demo_token_123" required
                        class="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-slate-100 focus:outline-none focus:border-teal-400">
                </div>
                
                <div class="flex items-end">
                    <button type="submit" id="btnConsultar"
                        class="w-full bg-teal-500 hover:bg-teal-400 text-slate-950 font-bold py-2 px-6 rounded-lg transition duration-200 flex items-center justify-center gap-2">
                        <span>Gerar Relatório</span>
                        <i class="fa-solid fa-arrow-right"></i>
                    </button>
                </div>
            </form>
        </section>

        <div id="loading" class="hidden text-center py-12">
            <div class="inline-block animate-spin rounded-full h-10 w-10 border-4 border-teal-500 border-t-transparent"></div>
            <p class="text-slate-400 text-sm mt-3">Consultando IBGE, DataSUS e Banco Central...</p>
        </div>

        <div id="errorMessage" class="hidden bg-rose-500/10 border border-rose-500/30 text-rose-300 p-4 rounded-xl text-sm"></div>

        <div id="reportContent" class="hidden space-y-8">
            
            <section class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <div class="bg-slate-800/40 border border-slate-700/50 p-5 rounded-xl">
                    <div class="text-slate-400 text-xs font-medium uppercase tracking-wider mb-1">Município / UF</div>
                    <div id="metricMunicipio" class="text-2xl font-bold text-white">--</div>
                    <div id="metricRegiao" class="text-xs text-teal-400 mt-1">--</div>
                </div>

                <div class="bg-slate-800/40 border border-slate-700/50 p-5 rounded-xl">
                    <div class="text-slate-400 text-xs font-medium uppercase tracking-wider mb-1">População Estimada</div>
                    <div id="metricPopulacao" class="text-2xl font-bold text-white">--</div>
                    <div class="text-xs text-slate-500 mt-1">Fonte: IBGE</div>
                </div>

                <div class="bg-slate-800/40 border border-slate-700/50 p-5 rounded-xl">
                    <div class="text-slate-400 text-xs font-medium uppercase tracking-wider mb-1">Densidade de Saúde</div>
                    <div id="metricDensidade" class="text-2xl font-bold text-teal-400">--</div>
                    <div class="text-xs text-slate-400 mt-1">Estabelecimentos / 10k hab.</div>
                </div>

                <div class="bg-slate-800/40 border border-slate-700/50 p-5 rounded-xl">
                    <div class="text-slate-400 text-xs font-medium uppercase tracking-wider mb-1">Taxa Selic Atual</div>
                    <div id="metricSelic" class="text-2xl font-bold text-emerald-400">--</div>
                    <div class="text-xs text-slate-500 mt-1">Fonte: Banco Central</div>
                </div>
            </section>

            <section class="grid grid-cols-1 lg:grid-cols-3 gap-8">
                <div class="lg:col-span-1 bg-slate-800/40 border border-slate-700/50 p-6 rounded-xl flex flex-col justify-between">
                    <h3 class="text-lg font-semibold text-slate-200 mb-4">Tipos de Unidades de Saúde</h3>
                    <div class="relative w-full h-64 flex items-center justify-center">
                        <canvas id="chartUnidades"></canvas>
                    </div>
                </div>

                <div class="lg:col-span-2 bg-slate-800/40 border border-slate-700/50 p-6 rounded-xl">
                    <h3 class="text-lg font-semibold text-slate-200 mb-4">Amostra de Estabelecimentos Cadastrados (CNES)</h3>
                    <div class="overflow-x-auto">
                        <table class="w-full text-left text-sm text-slate-300">
                            <thead class="bg-slate-900/60 text-xs uppercase text-slate-400 border-b border-slate-700">
                                <tr>
                                    <th class="py-3 px-4">CNES</th>
                                    <th class="py-3 px-4">Nome Fantasia</th>
                                    <th class="py-3 px-4">Tipo de Unidade</th>
                                </tr>
                            </thead>
                            <tbody id="tableAmostra" class="divide-y divide-slate-800"></tbody>
                        </table>
                    </div>
                </div>
            </section>
        </div>
    </main>

    <script>
        let chartInstance = null;

        const municipioInput = document.getElementById('municipioInput');
        const codigoIbgeInput = document.getElementById('codigoIbge');
        const suggestions = document.getElementById('suggestions');

        municipioInput.addEventListener('input', async (e) => {
            const query = e.target.value.trim();
            if (query.length < 3) {
                suggestions.classList.add('hidden');
                return;
            }

            try {
                const res = await fetch(`https://servicodados.ibge.gov.br/api/v1/localidades/municipios`);
                const municipios = await res.json();
                
                const filtrados = municipios
                    .filter(m => m.nome.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "")
                    .includes(query.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "")))
                    .slice(0, 6);

                suggestions.innerHTML = '';
                if (filtrados.length > 0) {
                    filtrados.forEach(m => {
                        const item = document.createElement('div');
                        item.className = 'px-4 py-2 hover:bg-slate-700 cursor-pointer text-sm text-slate-200 flex justify-between items-center';
                        item.innerHTML = `<span>${m.nome} - ${m.microrregiao.mesorregiao.UF.sigla}</span> <span class="text-xs text-teal-400 font-mono">${m.id}</span>`;
                        item.onclick = () => {
                            municipioInput.value = `${m.nome} - ${m.microrregiao.mesorregiao.UF.sigla}`;
                            codigoIbgeInput.value = m.id;
                            suggestions.classList.add('hidden');
                        };
                        suggestions.appendChild(item);
                    });
                    suggestions.classList.remove('hidden');
                } else {
                    suggestions.classList.add('hidden');
                }
            } catch (err) {
                console.error('Erro ao buscar municípios:', err);
            }
        });

        document.getElementById('searchForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const codigoIbge = codigoIbgeInput.value.trim();
            const apiKey = document.getElementById('apiKey').value.trim();
            
            const loading = document.getElementById('loading');
            const errorMessage = document.getElementById('errorMessage');
            const reportContent = document.getElementById('reportContent');

            loading.classList.remove('hidden');
            errorMessage.classList.add('hidden');
            reportContent.classList.add('hidden');

            try {
                const response = await fetch(`/api/v1/relatorio-municipio/${codigoIbge}?api_key=${apiKey}`);
                
                if (!response.ok) {
                    const errText = await response.text();
                    throw new Error(errText || `Erro na consulta (Status: ${response.status})`);
                }

                const result = await response.json();
                const data = result.data;

                document.getElementById('metricMunicipio').innerText = `${data.municipio.nome} - ${data.municipio.uf}`;
                document.getElementById('metricRegiao').innerText = `Região ${data.municipio.regiao}`;
                document.getElementById('metricPopulacao').innerText = data.municipio.populacao_estimada 
                    ? data.municipio.populacao_estimada.toLocaleString('pt-BR') 
                    : 'N/I';
                document.getElementById('metricDensidade').innerText = data.indicadores_saude_cnes.densidade_saude.estabelecimentos_por_10k_hab;
                document.getElementById('metricSelic').innerText = data.indicadores_macroeconomicos.taxa_selic_atual;

                const tbody = document.getElementById('tableAmostra');
                tbody.innerHTML = '';
                data.indicadores_saude_cnes.amostra_estabelecimentos.forEach(est => {
                    const tr = document.createElement('tr');
                    tr.className = 'hover:bg-slate-800/50 transition';
                    tr.innerHTML = `
                        <td class="py-3 px-4 font-mono text-teal-400">${est.cnes}</td>
                        <td class="py-3 px-4 font-medium text-white">${est.nome_fantasia}</td>
                        <td class="py-3 px-4">${est.tipo_unidade}</td>
                    `;
                    tbody.appendChild(tr);
                });

                const distTipos = data.indicadores_saude_cnes.distribuicao_tipos_unidade;
                const labels = Object.keys(distTipos);
                const values = Object.values(distTipos);

                if (chartInstance) chartInstance.destroy();

                const ctx = document.getElementById('chartUnidades').getContext('2d');
                chartInstance = new Chart(ctx, {
                    type: 'doughnut',
                    data: {
                        labels: labels,
                        datasets: [{
                            data: values,
                            backgroundColor: ['#14b8a6', '#06b6d4', '#3b82f6', '#6366f1', '#8b5cf6', '#ec4899', '#f43f5e', '#f97316'],
                            borderWidth: 0
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { position: 'bottom', labels: { color: '#94a3b8', font: { size: 11 } } }
                        }
                    }
                });

                reportContent.classList.remove('hidden');

            } catch (err) {
                errorMessage.innerText = err.message;
                errorMessage.classList.remove('hidden');
            } finally {
                loading.classList.add('hidden');
            }
        });

        window.addEventListener('DOMContentLoaded', () => {
            document.getElementById('searchForm').dispatchEvent(new Event('submit'));
        });
    </script>
</body>
</html>
"""

# Rota Principal servindo o HTML diretamente
@app.get("/", response_class=HTMLResponse)
async def homepage():
    return HTMLResponse(content=HTML_CONTENT, status_code=200)

# Documentação Swagger Customizada
@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Documentação",
        swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js",
        swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-css.css",
        swagger_favicon_url="https://fastapi.tiangolo.com/img/favicon.png",
        custom_js=None,
    )

# Documentação Moderna com Scalar
@app.get("/scalar", include_in_schema=False)
async def scalar_html():
    return HTMLResponse("""
    <!doctype html>
    <html>
      <head>
        <title>Healthtech API Docs</title>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </head>
      <body>
        <script id="api-reference" data-url="/openapi.json"></script>
        <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
      </body>
    </html>
    """)

# Endpoint da API
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
            # 1. Informações Básicas do Município (IBGE)
            ibge_task = client.get(f"{IBGE_API}/localidades/municipios/{codigo_ibge}")
            
            # 2. População Estimada - Tabela 6579 (Estimativas do Censo/IBGE)
            populacao_task = client.get(f"{IBGE_API}/pesquisas/indicadores/29171/resultados/{codigo_ibge}")
            
            # 3. Taxa Selic Meta Anualizada (Série 432 do Banco Central)
            selic_task = client.get(f"{BCB_SGS_API}.432/dados/ultimos/1?formato=json")
            
            # 4. Dados de Saúde (CNES / DataSUS)
            cnes_task = client.get(
                CNES_API,
                params={"codigo_municipio": codigo_ibge_6dig, "limit": 50}
            )

            ibge_res, pop_res, selic_res, cnes_res = await asyncio.gather(
                ibge_task, populacao_task, selic_task, cnes_task, return_exceptions=True
            )

            # Processa Município
            municipio_info = ibge_res.json() if isinstance(ibge_res, httpx.Response) and ibge_res.status_code == 200 else {}
            if not municipio_info or "id" not in municipio_info:
                raise HTTPException(status_code=404, detail="Município não encontrado com o código IBGE fornecido.")

            # Processa População
            populacao_estimada = None
            if isinstance(pop_res, httpx.Response) and pop_res.status_code == 200:
                try:
                    pop_json = pop_res.json()
                    res_dict = pop_json[0]["res"]
                    # Pega o valor mais recente do dicionário de anos
                    ultimo_ano = sorted(res_dict.keys())[-1]
                    populacao_estimada = int(res_dict[ultimo_ano])
                except Exception:
                    populacao_estimada = None

            # Processa Selic Anual Meta
            selic_val = "10.75%" # Fallback para a Selic atual caso haja timeout
            if isinstance(selic_res, httpx.Response) and selic_res.status_code == 200:
                selic_data = selic_res.json()
                if selic_data:
                    selic_val = f"{selic_data[0]['valor']}%"

            # Processa CNES
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

            # Calcula Densidade de Saúde
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
                    "taxa_selic_atual": selic_val
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