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
                if not items: break # Evita loop infinito se items vier vazio
                
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
def buscar_dados_wms(token, id_pa, id_mp, id_unidade):
    todos_items_formatados = []
    pagina_wms = 1
    tem_proxima_wms = True
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    while tem_proxima_wms:
        url_pag = f"https://supply.logistica.totvs.app/wms/query/api/v3/estoques/analitico?page={pagina_wms}&pageSize=1000"
        payload = {
            "agrupadores": ["UNIDADE"],
            "unidadeIdPreferencial": id_unidade,
            "condicionais": [{"chave": "UNIDADE", "valor": id_unidade}],
            "filtros": {
                "unidades": [id_unidade],
                "tiposEstoque": [id_pa, id_mp],
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
                    id_tipo = item.get('tipoEstoque', {}).get('id', '')
                    cod_arm = "01" if id_tipo == id_pa else "05" if id_tipo == id_mp else ""
                    
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

# Sidebar para inputs
with st.sidebar:
    st.header("🔑 Acesso Protheus")
    url_prw = st.text_input("URL REST Protheus", value="https://dacolonia196730.protheus.cloudtotvs.com.br:10408/rest")
    user_p = st.text_input("Usuário Protheus")
    pass_p = st.text_input("Senha Protheus", type="password")
    
    st.divider()
    st.header("☁️ Acesso WMS SaaS")
    wms_id = st.text_input("Client ID", type="password")
    wms_secret = st.text_input("Client Secret", type="password")
    
    with st.expander("Configurações Avançadas de IDs"):
        id_pa = st.text_input("ID Tipo PA", value="019b93db-5f78-7d1d-84bb-77fc2c45b068")
        id_mp = st.text_input("ID Tipo MP", value="019b5bb5-cf01-781f-92be-49c08ab2d635")
        id_unidade = st.text_input("ID Unidade", value="404fc993-c7f1-4b24-926b-96b99c71ebdd")

    st.divider()
    st.caption("🔒 Dados mantidos apenas em memória durante a execução.")

# Botão de Ação
if st.button("🚀 Iniciar Conciliação"):
    if not all([user_p, pass_p, wms_id, wms_secret, url_prw]):
        st.warning("⚠️ Preencha todos os campos de login na barra lateral.")
    else:
        # 1. Autenticação WMS
        with st.status("Autenticando e buscando dados...", expanded=True) as status:
            st.write("Obtendo Token WMS...")
            token = gera_token(wms_id, wms_secret)
            
            if not token:
                st.error("❌ Falha na autenticação WMS. Verifique Client ID e Secret.")
                st.stop()
            
            # 2. Busca de Dados
            st.write("Buscando dados no Protheus...")
            df_p_raw = buscar_dados_protheus(url_prw, user_p, pass_p)
            
            st.write("Buscando dados no WMS...")
            df_w_raw = buscar_dados_wms(token, id_pa, id_mp, id_unidade)
            
            status.update(label="Processamento Concluído!", state="complete", expanded=False)

        # 3. Lógica de Comparação
        if not df_p_raw.empty and not df_w_raw.empty:
            # Agrupamento e Merge (Mantendo sua lógica original)
            df_p = df_p_raw.groupby(['produto', 'armazem', 'lote_protheus', 'validade_protheus'], as_index=False)['quantidade'].sum()
            df_p.rename(columns={'quantidade': 'SALDO_PROTHEUS'}, inplace=True)

            df_w = df_w_raw.groupby(['produto', 'armazem', 'lote_wms', 'validade_wms'], as_index=False)['quantidade'].sum()
            df_w.rename(columns={'quantidade': 'SALDO_WMS'}, inplace=True)

            df_res = pd.merge(
                df_p, df_w, 
                left_on=['produto', 'armazem', 'lote_protheus', 'validade_protheus'],
                right_on=['produto', 'armazem', 'lote_wms', 'validade_wms'],
                how='outer'
            )

            df_res = df_res.fillna({'SALDO_PROTHEUS': 0, 'SALDO_WMS': 0})
            df_res['DIFERENCA'] = df_res['SALDO_PROTHEUS'] - df_res['SALDO_WMS']
            
            # Exibição
            df_erros = df_res[df_res['DIFERENCA'] != 0].copy()
            st.subheader(f"Divergências Encontradas: {len(df_erros)}")
            st.dataframe(df_erros, use_container_width=True)

            # Download Excel
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_res.to_excel(writer, index=False, sheet_name='Conciliacao')
            
            st.download_button(
                label="📥 Baixar Relatório Completo",
                data=buffer.getvalue(),
                file_name="conciliacao.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.error("Não foi possível obter dados de uma das fontes. Verifique se há saldo nos armazéns 01/05.")
