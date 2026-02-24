import pandas as pd
import requests
import streamlit as st
import io
from requests.auth import HTTPBasicAuth

# --- 1. FUNÇÃO DE AUTENTICAÇÃO ---
def gera_token():
    AUTH_URL = "https://supply.rac.totvs.app/totvs.rac/connect/token" 
    CLIENT_ID = "2006151c237e4124ad27927d92a17861"
    CLIENT_SECRET = "0e3b002202e74259b52cf9a39c677052"
    token_data = {
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials", "scope": "authorization_api"
    }
    try:
        response = requests.post(AUTH_URL, data=token_data, timeout=10)
        return response.json().get("access_token") if response.status_code == 200 else None
    except: return None

# --- 2. BUSCA DADOS PROTHEUS ---
def buscar_dados_protheus(url_api, user, pwd):
    todos_items = []
    pagina_prw = 1
    tem_proxima_prw = True
    while tem_proxima_prw:
        try:
            url = f"{url_api}?nPage={pagina_prw}&nPageSize=1000"
            response = requests.get(url, auth=HTTPBasicAuth(user, pwd), timeout=25)
            if response.status_code == 200:
                dados = response.json()
                items = dados.get('items', [])
                for i in items:
                    val_arm = str(i.get('armazem', i.get('armazém', ''))).strip()
                    if val_arm in ['01', '05', '1', '5']:
                        cod_arm = val_arm.zfill(2)
                        todos_items.append({
                            "produto": str(i.get('produto', '')).strip(),
                            "lote": str(i.get('lote', '')).strip(),
                            "validade": str(i.get('validade', '')),
                            "quantidade": float(i.get('quantidade', 0)),
                            "armazem": cod_arm
                        })
                tem_proxima_prw = dados.get('hasNext', False)
                pagina_prw += 1
            else: break
        except: break
    return pd.DataFrame(todos_items)

# --- 3. BUSCA DADOS WMS (AJUSTADO AO SEU JSON) ---
def buscar_dados_wms(token):
    todos_items_formatados = []
    pagina_wms = 1
    tem_proxima_wms = True
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    # IDs fornecidos por você
    ID_PA = "019b93db-5f78-7d1d-84bb-77fc2c45b068" # 01
    ID_MP = "019b5bb5-cf01-781f-92be-49c08ab2d635" # 05

    while tem_proxima_wms:
        url_pag = f"https://supply.logistica.totvs.app/wms/query/api/v3/estoques/analitico?page={pagina_wms}&pageSize=1000"
        
        # Payload com o filtro direto pelos IDs que funcionam no seu WMS
        payload = {
            "agrupadores": ["UNIDADE"],
            "unidadeIdPreferencial": "404fc993-c7f1-4b24-926b-96b99c71ebdd",
            "condicionais": [{"chave": "UNIDADE", "valor": "404fc993-c7f1-4b24-926b-96b99c71ebdd"}],
            "filtros": {
                "unidades": ["404fc993-c7f1-4b24-926b-96b99c71ebdd"],
                "tiposEstoque": [ID_PA, ID_MP],
                "saldoDisponivel": False
            }
        }
        
        try:
            response = requests.post(url_pag, json=payload, headers=headers, timeout=30)
            if response.status_code == 200:
                dados = response.json()
                items = dados.get('items', [])
                
                for item in items:
                    # 1. Identificar Armazém pelo ID do Tipo de Estoque
                    id_tipo_estoque = item.get('tipoEstoque', {}).get('id', '')
                    cod_armazem = ""
                    if id_tipo_estoque == ID_PA: cod_armazem = "01"
                    elif id_tipo_estoque == ID_MP: cod_armazem = "05"
                    
                    # Se por algum motivo o ID não bater, tenta pela descrição (ex: "01 - ALMOX")
                    if not cod_armazem:
                        desc_tipo = item.get('tipoEstoque', {}).get('descricao', '')
                        if desc_tipo.startswith("01"): cod_armazem = "01"
                        elif desc_tipo.startswith("05"): cod_armazem = "05"

                    if cod_armazem:
                        # 2. Extrair Lote e Validade das características
                        lote = "0"
                        validade = "1900-01-01"
                        for carac in item.get('caracteristicas', []):
                            desc_carac = carac.get('descricao', '').upper()
                            if "LOTE" in desc_carac:
                                lote = str(carac.get('valor', '0')).strip()
                            elif "VALIDADE" in desc_carac:
                                validade = str(carac.get('valor', '1900-01-01')).strip()

                        todos_items_formatados.append({
                            "produto": str(item.get('produto', {}).get('codigo', '')).strip(),
                            "lote": lote,
                            "validade": validade,
                            "quantidade": float(item.get('saldo', 0)),
                            "armazem": cod_armazem
                        })
                
                tem_proxima_wms = dados.get('hasNext', False)
                pagina_wms += 1
            else: break
        except: break
            
    return pd.DataFrame(todos_items_formatados)

# --- 4. INTERFACE STREAMLIT ---
st.set_page_config(page_title="Conciliador DaColonia", layout="wide")
st.title("📊 Conciliador de Estoque: Protheus x WMS")

with st.sidebar:
    st.header("Credenciais Protheus")
    url_p = st.text_input("URL REST", "https://dacolonia196730.protheus.cloudtotvs.com.br:10408/rest/zsaldoslote/")
    user_p = st.text_input("Usuário", "integradorwms")
    pass_p = st.text_input("Senha", "TOTVS@@..", type="password")

if st.button("🚀 Iniciar Conciliação"):
    token = gera_token()
    if token:
        with st.spinner("Buscando dados nos dois sistemas..."):
            df_protheus = buscar_dados_protheus(url_p, user_p, pass_p)
            df_wms = buscar_dados_wms(token)

            if df_protheus.empty: st.error("❌ Protheus não retornou dados para armazéns 01/05.")
            if df_wms.empty: st.error("❌ WMS não retornou dados para os tipos de estoque filtrados.")

            if not df_protheus.empty and not df_wms.empty:
                # Soma saldos para evitar duplicatas de chave
                df_p_sum = df_protheus.groupby(['produto', 'lote', 'validade', 'armazem'], as_index=False)['quantidade'].sum()
                df_p_sum.rename(columns={'quantidade': 'SALDO_PROTHEUS'}, inplace=True)

                df_w_sum = df_wms.groupby(['produto', 'lote', 'validade', 'armazem'], as_index=False)['quantidade'].sum()
                df_w_sum.rename(columns={'quantidade': 'SALDO_WMS'}, inplace=True)

                # Cruzamento Total (Full Outer Join)
                df_final = pd.merge(df_p_sum, df_w_sum, on=['produto', 'lote', 'validade', 'armazem'], how='outer').fillna(0)
                df_final['DIFERENCA'] = df_final['SALDO_PROTHEUS'] - df_final['SALDO_WMS']

                st.success("Conciliação finalizada!")
                
                # Exibe apenas divergências na tela
                df_erros = df_final[df_final['DIFERENCA'] != 0].copy()
                st.write(f"### Itens com Divergência ({len(df_erros)})")
                st.dataframe(df_erros, use_container_width=True)

                # Download do Excel completo
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    df_final.to_excel(writer, index=False, sheet_name='Geral')
                st.download_button("📥 Baixar Relatório Completo", buffer.getvalue(), "conciliacao.xlsx")
    else:
        st.error("Erro ao autenticar no RAC (WMS).")
