import pandas as pd
import requests
import streamlit as st
import io
from requests.auth import HTTPBasicAuth

# --- CONFIGURAÇÃO INTERNA ---
# O endereço foi movido para cá para não aparecer na tela
URL_REST_PROTHEUS = "https://dacolonia196730.protheus.cloudtotvs.com.br:10408/rest"

# --- 1. FUNÇÃO DE AUTENTICAÇÃO (WMS) ---
def gera_token(client_id, client_secret):
    AUTH_URL = "https://supply.rac.totvs.app/totvs.rac/connect/token" 
    token_data = {
        "client_id": client_id,
        "client_secret": client_secret,
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
def buscar_dados_protheus(url_base, user, pwd):
    todos_items = []
    pagina_prw = 1
    tem_proxima_prw = True
    url_limpa = url_base.strip().rstrip('/')
    endpoint_fixo = "/zsaldoslote/"
    url_completa = f"{url_limpa}{endpoint_fixo}"
    
    while tem_proxima_prw:
        try:
            url_paginada = f"{url_completa}?nPage={pagina_prw}&nPageSize=1000"
            response = requests.get(url_paginada, auth=HTTPBasicAuth(user, pwd), timeout=25)
            if response.status_code == 200:
                dados = response.json()
                items = dados.get('items', [])
                for i in items:
                    val_arm = str(i.get('armazem', i.get('armazém', ''))).strip()
                    if val_arm in ['01', '05', '1', '5']:
                        cod_arm = val_arm.zfill(2)
                        todos_items.append({
                            "produto": str(i.get('produto', '')).strip(),
                            "lote_protheus": str(i.get('lote', '')).strip(),
                            "validade_protheus": str(i.get('validade', '')),
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
    ID_PA = "04a6fd47-f32e-4cad-a803-620d03adf8f2"
    ID_MP = "019c94d5-c1b3-7b4a-8070-eac5381edda3"

    while tem_proxima_wms:
        url_pag = f"https://supply.logistica.totvs.app/wms/query/api/v3/estoques/analitico?page={pagina_wms}&pageSize=1000"
        payload = {
            "agrupadores": ["UNIDADE"],
            "unidadeIdPreferencial": "ac275b55-90f8-44b8-b8cb-bdcfca969526",
            "condicionais": [{"chave": "UNIDADE", "valor": "ac275b55-90f8-44b8-b8cb-bdcfca969526"}],
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
                    cod_arm = "01" if id_tipo == ID_PA else "05" if id_tipo == ID_MP else ""
                    if cod_arm:
                        lote, validade = "0", "1900-01-01"
                        for c in item.get('caracteristicas', []):
                            desc = c.get('descricao', '').upper()
                            if "LOTE" in desc: lote = str(c.get('valor', '0')).strip()
                            elif "VALIDADE" in desc: validade = str(c.get('valor', '1900-01-01')).strip()
                        todos_items_formatados.append({
                            "produto": str(item.get('produto', {}).get('codigo', '')).strip(),
                            "lote_wms": lote, 
                            "validade_wms": validade,
                            "quantidade": float(item.get('saldo', 0)),
                            "armazem": cod_arm
                        })
                tem_proxima_wms = dados.get('hasNext', False)
                pagina_wms += 1
            else: break
        except: break
    return pd.DataFrame(todos_items_formatados)

# --- 4. INTERFACE PRINCIPAL ---
st.set_page_config(page_title="Conciliador DaColonia", layout="wide")
st.title("📊 Conciliador de Estoque: Protheus x WMS")

with st.sidebar:
    st.header("🔑 Acesso Protheus")
    # Removido o st.text_input do endereço do servidor
    user_p = st.text_input("Usuário Protheus", key="saved_user")
    pass_p = st.text_input("Senha Protheus", type="password", key="saved_pass")
    st.divider()
    st.header("☁️ Acesso WMS SaaS")
    wms_id = st.text_input("Client ID", type="password", key="saved_wms_id")
    wms_secret = st.text_input("Client Secret", type="password", key="saved_wms_secret")
    st.divider()
    st.caption("🔒 Os dados são mantidos apenas durante a sessão.")

if st.button("🚀 Iniciar Conciliação"):
    # Verifica se os outros campos estão preenchidos (URL_REST_PROTHEUS é fixa agora)
    if not all([user_p, pass_p, wms_id, wms_secret]):
        st.warning("⚠️ Preencha todos os campos na barra lateral.")
    else:
        token = gera_token(wms_id, wms_secret)
        if token:
            with st.spinner("Comparando saldos..."):
                # Utiliza a variável oculta URL_REST_PROTHEUS
                df_p_raw = buscar_dados_protheus(URL_REST_PROTHEUS, user_p, pass_p)
                df_w_raw = buscar_dados_wms(token)

                if not df_p_raw.empty and not df_w_raw.empty:
                    df_p = df_p_raw.groupby(['produto', 'armazem', 'lote_protheus', 'validade_protheus'], as_index=False)['quantidade'].sum()
                    df_p.rename(columns={'quantidade': 'SALDO_PROTHEUS'}, inplace=True)

                    df_w = df_w_raw.groupby(['produto', 'armazem', 'lote_wms', 'validade_wms'], as_index=False)['quantidade'].sum()
                    df_w.rename(columns={'quantidade': 'SALDO_WMS'}, inplace=True)
                    
                    df_res = pd.merge(
                        df_p, 
                        df_w, 
                        left_on=['produto', 'armazem', 'lote_protheus', 'validade_protheus'],
                        right_on=['produto', 'armazem', 'lote_wms', 'validade_wms'],
                        how='outer'
                    ).fillna({'SALDO_PROTHEUS': 0, 'SALDO_WMS': 0, 'lote_protheus': '-', 'lote_wms': '-', 'validade_protheus': '-', 'validade_wms': '-'})
                    
                    df_res['DIFERENCA'] = df_res['SALDO_PROTHEUS'] - df_res['SALDO_WMS']
                    
                    cols = ['produto', 'armazem', 'lote_protheus', 'lote_wms', 'validade_protheus', 'validade_wms', 'SALDO_PROTHEUS', 'SALDO_WMS', 'DIFERENCA']
                    df_res = df_res[cols]
                    
                    st.success("Conciliação concluída!")
                    df_erros = df_res[df_res['DIFERENCA'] != 0].copy()
                    
                    st.write(f"### 📋 Divergências Detalhadas ({len(df_erros)})")
                    st.dataframe(df_erros, use_container_width=True)
                    
                    buffer = io.BytesIO()
                    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                        df_res.to_excel(writer, index=False, sheet_name='Geral')
                    st.download_button("📥 Baixar Relatório", buffer.getvalue(), "conciliacao_dacolonia.xlsx")
                else:
                    st.error("❌ Verifique as credenciais ou filtros de armazém.")
        else:
            st.error("❌ Falha na autenticação WMS.")
