import streamlit as st
import requests
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="Healthtech Analytics", layout="wide")
st.title("Painel de Indicadores de Saúde e Economia")

codigo_ibge = st.text_input("Código IBGE do Município:", value="3550308")
api_key = st.text_input("Chave API:", value="demo_token_123", type="password")

if st.button("Consultar Relatório"):
    url = f"https://healthtech-ripb.onrender.com/api/v1/relatorio-municipio/{codigo_ibge}"
    response = requests.get(url, params={"api_key": api_key})

    if response.status_code == 200:
        data = response.json()["data"]

        # Métrica rápidas
        col1, col2, col3 = st.columns(3)
        col1.metric("Município", f"{data['municipio']['nome']} - {data['municipio']['uf']}")
        col2.metric("População Estimada", f"{data['municipio']['populacao_estimada']:,}")
        col3.metric("Taxa Selic", data['indicadores_macroeconomicos']['taxa_selic_atual'])

        st.divider()

        # Gráfico de Tipos de Unidade de Saúde
        distribuicao = data['indicadores_saude_cnes']['distribuicao_tipos_unidade']
        df_dist = pd.DataFrame(list(distribuicao.items()), columns=['Tipo de Unidade', 'Quantidade'])

        fig = px.bar(df_dist, x='Tipo de Unidade', y='Quantidade', title="Distribuição de Estabelecimentos de Saúde")
        st.plotly_chart(fig, use_container_width=True)

        # Tabela de Amostra
        st.subheader("Amostra de Estabelecimentos Cadastrados")
        st.dataframe(pd.DataFrame(data['indicadores_saude_cnes']['amostra_estabelecimentos']))
    else:
        st.error("Erro ao consultar a API. Verifique a chave ou o código IBGE.")