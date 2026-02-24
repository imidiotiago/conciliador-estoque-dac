import pandas as pd
import requests
import streamlit as st
import io
from requests.auth import HTTPBasicAuth

# --- 1. FUNÇÃO DE AUTENTICAÇÃO (WMS) ---
def gera_token():
    # Mantivemos as chaves fixas aqui conforme solicitado
    AUTH_URL = "https://supply.rac.totvs.app/totvs.rac/connect/token" 
    CLIENT_ID = "2006151c237e4124ad27927d92a17861"
    CLIENT_SECRET = "0e3b002202e74259b52cf9a39c677052"

    token_data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials",
        "scope": "authorization_api"
    }
    try:
        response = requests.post(AUTH_URL, data=token_data, timeout=10)
        if response.status_code == 200:
            return response.json().get("access_token")
        return None
    except:
        return None

# --- 2. BUSCA DADOS PROTHEUS ---
def buscar_dados_protheus(url_api, user, pwd):
    todos_items = []
    pagina_prw = 1
    tem_proxima_prw = True
    
    while tem_proxima_prw:
        try:
            url = f"{url_api}?nPage={pagina_prw}&nPageSize=1000"
            # Utiliza as credenciais passadas pelo usuário na interface
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

# --- 3. BUSCA DADOS WMS ---
def buscar_dados_wms(token):
    todos_items_formatados = []
    pagina_wms = 1
    tem_proxima_wms = True
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    # IDs de Tipo de Estoque fixos do ambiente DaColonia
    ID_PA = "019b93db-5f78-7d1d-84bb-77fc2c45b068" # 01
    ID_MP = "019b5bb5-cf01-781f-92be-49c08ab2d635" # 05

    while tem_proxima_wms:
        url_pag = f"https://supply.logistica.totvs.app/wms/query/api/v3/estoques/analitico?page={pagina_wms}&pageSize=1000"
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
                for item in dados.get('items', []):
                    id_tipo = item.get('tipoEstoque', {}).get('id', '')
                    cod_armazem = "01" if id_tipo == ID_PA else "05" if id_tipo == ID_MP else ""

                    if cod_armazem:
                        lote, validade = "0", "1900-01-01"
                        for carac in item.get('caracteristicas', []):
                            desc = carac.get('descricao', '').upper()
                            if "LOTE" in desc: lote = str(carac.get('valor', '0')).strip()
                            elif "VALIDADE" in desc: validade = str(carac.get('valor', '1900-01-01')).strip()

                        todos_items_formatados.append({
                            "produto": str(item.get('produto', {}).get('codigo', '')).strip(),
                            "lote": lote, "validade": validade,
                            "quantidade": float(item.get('saldo', 0)),
                            "armazem": cod_armazem
                        })
                tem_proxima_wms = dados.get('hasNext', False)
                pagina_wms += 1
            else: break
        except: break
    return pd.DataFrame(todos_items_formatados)

# --- 4. INTERFACE ---
st.set_page_config(page_title="Conciliador DaColonia", layout="wide")
st.title("📊 Conciliador de Estoque: Protheus x WMS")

with st.sidebar:
    st.header("🔑 Login Protheus")
    # URL mantida como padrão para facilitar, mas editável
    url_p = st.text_input("URL REST", value="https://dacolonia196730.protheus.cloudtotvs.com.br:10408/rest/zsaldoslote/")
    # Usuário e Senha agora vêm vazios para entrada manual
    user_p = st.text_input("Usuário")
    pass_p = st.text_input("Senha", type="password")
    
    st.divider()
    st.caption("As credenciais do WMS SaaS estão configuradas internamente.")

if st.button("🚀 Iniciar Conciliação"):
    if not user_p or not pass_p:
        st.error("⚠️ Informe o Usuário e a Senha na barra lateral para continuar.")
    else:
        token = gera_token()
        if token:
            with st.spinner("Processando dados..."):
                df_p_raw = buscar_dados_protheus(url_p, user_p, pass_p)
                df_w_raw = buscar_dados_wms(token)

                if not df_p_raw.empty and not df_w_raw.empty:
                    df_p = df_p_raw.groupby(['produto', 'lote', 'validade', 'armazem'], as_index=False)['quantidade'].sum().rename(columns={'quantidade': 'SALDO_PROTHEUS'})
                    df_w = df_w_raw.groupby(['produto', 'lote', 'validade', 'armazem'], as_index=False)['quantidade'].sum().rename(columns={'quantidade': 'SALDO_WMS'})
                    
                    df_res = pd.merge(df_p, df_w, on=['produto', 'lote', 'validade', 'armazem'], how='outer').fillna(0)
                    df_res['DIFERENCA'] = df_res['SALDO_PROTHEUS'] - df_res['SALDO_WMS']
                    
                    st.success("Conciliação finalizada!")
                    st.dataframe(df_res[df_res['DIFERENCA'] != 0], use_container_width=True)
                    
                    buffer = io.BytesIO()
                    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                        df_res.to_excel(writer, index=False)
                    st.download_button("📥 Baixar Relatório Excel", buffer.getvalue(), "conciliacao.xlsx")
                else:
                    st.error("Verifique as credenciais ou filtros. Uma das bases retornou vazia.")
        else:
            st.error("Falha na autenticação do WMS.")
