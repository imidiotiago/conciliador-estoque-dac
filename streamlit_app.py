import pandas as pd
import requests
import streamlit as st
import io
from requests.auth import HTTPBasicAuth

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
                if not items: break
                
                for i in items:
                    val_arm = str(i.get('armazem', i.get('armazém', ''))).strip()
                    # Mantendo apenas o filtro básico de armazéns que você utiliza
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

    while tem_proxima_wms:
        url_pag = f"https://supply.logistica.totvs.app/wms/query/api/v3/estoques/analitico?page={pagina_wms}&pageSize=1000"
        # Payload simplificado: sem filtros de ID de Tipo de Estoque (PA/MP)
        payload = {
            "agrupadores": ["UNIDADE"],
            "unidadeIdPreferencial": "404fc993-c7f1-4b24-926b-96b99c71ebdd",
            "condicionais": [{"chave": "UNIDADE", "valor": "404fc993-c7f1-4b24-926b-96b99c71ebdd"}],
            "filtros": {
                "unidades": ["404fc993-c7f1-4b24-926b-96b99c71ebdd"],
                "saldoDisponivel": False
            }
        }
        try:
            response = requests.post(url_pag, json=payload, headers=headers, timeout=30)
            if response.status_code == 200:
                dados = response.json()
                items = dados.get('items', [])
                if not items: break

                for item in items:
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
                        # Pegamos o armazém/tipo direto do retorno se disponível ou tratamos depois
                        "tipo_estoque": item.get('tipoEstoque', {}).get('descricao', '')
                    })
                tem_proxima_wms = dados.get('hasNext', False)
                pagina_wms += 1
            else: break
        except: break
    return pd.DataFrame(todos_items_formatados)

# --- 4. INTERFACE PRINCIPAL (STREAMLIT) ---
st.set_page_config(page_title="Conciliador DaColonia", layout="wide")
st.title("📊 Conciliador de Estoque: Protheus x WMS")

with st.sidebar:
    st.header("🔑 Acesso Protheus")
    url_prw = st.text_input("URL REST Protheus", value="https://dacolonia196730.protheus.cloudtotvs.com.br:10408/rest")
    user_p = st.text_input("Usuário Protheus")
    pass_p = st.text_input("Senha Protheus", type="password")
    
    st.divider()
    st.header("☁️ Acesso WMS SaaS")
    wms_id = st.text_input("Client ID", type="password")
    wms_secret = st.text_input("Client Secret", type="password")
    
    st.divider()
    st.caption("🔒 Dados processados apenas em tempo de execução.")

if st.button("🚀 Iniciar Conciliação"):
    if not all([user_p, pass_p, wms_id, wms_secret]):
        st.warning("⚠️ Preencha todas as credenciais na barra lateral.")
    else:
        with st.status("Processando...", expanded=True) as status:
            token = gera_token(wms_id, wms_secret)
            if not token:
                st.error("❌ Erro de Token WMS.")
                st.stop()
            
            df_p = buscar_dados_protheus(url_prw, user_p, pass_p)
            df_w = buscar_dados_wms(token)
            status.update(label="Dados obtidos!", state="complete", expanded=False)

        if not df_p.empty and not df_w.empty:
            # Consolidação Protheus
            df_p_agg = df_p.groupby(['produto', 'lote_protheus'], as_index=False)['quantidade'].sum()
            df_p_agg.rename(columns={'quantidade': 'SALDO_PROTHEUS'}, inplace=True)

            # Consolidação WMS
            df_w_agg = df_w.groupby(['produto', 'lote_wms'], as_index=False)['quantidade'].sum()
            df_w_agg.rename(columns={'quantidade': 'SALDO_WMS'}, inplace=True)

            # Cruzamento por Produto e Lote
            df_res = pd.merge(
                df_p_agg, df_w_agg, 
                left_on=['produto', 'lote_protheus'],
                right_on=['produto', 'lote_wms'],
                how='outer'
            ).fillna(0)

            df_res['DIFERENCA'] = df_res['SALDO_PROTHEUS'] - df_res['SALDO_WMS']
            
            st.subheader("📋 Divergências Encontradas")
            st.dataframe(df_res[df_res['DIFERENCA'] != 0], use_container_width=True)

            # Exportação
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_res.to_excel(writer, index=False, sheet_name='Resultado')
            
            st.download_button("📥 Baixar Planilha", buffer.getvalue(), "conciliacao.xlsx")
        else:
            st.error("Nenhum dado retornado para comparação.")
