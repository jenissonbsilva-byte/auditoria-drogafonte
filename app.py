import streamlit as st
import pandas as pd
from fpdf import FPDF
import io
import re
import os
import base64

# Configuração da Página
st.set_page_config(page_title="Auditoria Drogafonte", layout="wide", page_icon="🛡️")

# --- FUNÇÃO PARA GARANTIR A LOGO (BASE64) ---
def get_image_base64(path):
    with open(path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode()

# --- ESTADOS DO SISTEMA ---
if 'tela_resultado' not in st.session_state:
    st.session_state.tela_resultado = False

def resetar_app():
    st.session_state.tela_resultado = False
    for key in ['dados_finais', 'erros_registro', 'cabecalho_pdf', 'erro', 'aliquota']:
        if key in st.session_state: del st.session_state[key]

# --- MOTOR DE INTELIGÊNCIA DE DIVISORES ---
def extrair_divisor_inteligente(apres_cmed, unid_proposta):
    apres_cmed = str(apres_cmed).upper()
    unid_proposta = str(unid_proposta).upper().strip()

    if any(x in unid_proposta for x in ["CX", "CAIXA", "DOS", "DOSE"]):
        return 1
    if "CAR" in unid_proposta:
        m = re.search(r'(\d+)\s*X\s*(\d+)', apres_cmed)
        return float(m.group(2)) if m else 1

    # PADRÃO: UNIDADE (ML, CPR, AMP, etc)
    m = re.search(r'\b(\d+)\s+(?:BL|ENV|STRIP|CPR|CAP|AMP|FA|FR|SER).*?X\s+(\d+)\b', apres_cmed)
    if m: return float(m.group(1)) * float(m.group(2))
    m = re.search(r'X\s+(\d+)\b(?!\s*(?:ML|MG|G|MCG|UI))', apres_cmed)
    if m: return float(m.group(1))
    m = re.search(r'(?:C/|CT|CX)\s*(\d+)\b', apres_cmed)
    return float(m.group(1)) if m else 1

def formatar_moeda(val):
    v = str(val).replace('R$', '').replace(' ', '').strip()
    if pd.isna(val) or v.lower() == 'nan' or v == '': return 0.0
    if '.' in v and ',' in v: v = v.replace('.', '')
    v = v.replace(',', '.')
    try: return float(v)
    except: return 0.0

def exportar_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Auditoria')
    return output.getvalue()

@st.cache_data
def carregar_cmed():
    if os.path.exists('cmed_atual.xlsx'):
        df_raw = pd.read_excel('cmed_atual.xlsx', header=None, engine='openpyxl')
        for i, r in df_raw.iterrows():
            if r.astype(str).str.contains('REGISTRO').any():
                df = pd.read_excel('cmed_atual.xlsx', skiprows=i)
                df.columns = df.columns.astype(str).str.replace(' %', '%').str.strip()
                return df
    return None

def processar_dados(file_proposta, df_cmed, coluna_icms):
    try:
        if file_proposta.name.endswith('.xls'):
            df_raw = pd.read_excel(file_proposta, header=None, engine='xlrd')
        else:
            df_raw = pd.read_excel(file_proposta, header=None, engine='openpyxl')
            
        linha_cab = 0
        for i, row in df_raw.iterrows():
            if row.astype(str).str.contains('Reg.M.S|Vlr. Unit.', case=False).any():
                linha_cab = i
                break
        
        cabecalho_info = [" ".join(df_raw.iloc[j].dropna().astype(str).tolist()) for j in range(linha_cab) if str(df_raw.iloc[j].dropna()).strip()]
        df_prop = df_raw.iloc[linha_cab+1:].copy()
        df_prop.columns = df_raw.iloc[linha_cab].astype(str).str.strip()
        
        c_desc = [c for c in df_prop.columns if any(x in str(c) for x in ['D i s c', 'Nome Com', 'Descrição'])][0]
        c_reg = [c for c in df_prop.columns if 'REG.M.S' in str(c).upper().replace(' ', '') or 'REGISTRO' in str(c).upper()][0]
        c_vlr = [c for c in df_prop.columns if 'VLR' in str(c).upper() and 'UNIT' in str(c).upper()][0]
        c_unid = [c for c in df_prop.columns if 'APR' in str(c).upper() and len(str(c)) < 10][0]
        c_item = [c for c in df_prop.columns if 'ITEM' in str(c).upper()][0]

        df_prop['Reg_L'] = df_prop[c_reg].astype(str).str.replace(r'[^0-9]', '', regex=True)
        df_cmed['Reg_C'] = df_cmed['REGISTRO'].astype(str).str.replace(r'[^0-9]', '', regex=True)
        df_prop['V_Unit'] = df_prop[c_vlr].apply(formatar_moeda)
        c_apres_cmed = [c for c in df_cmed.columns if 'APRESENTA' in str(c).upper()][0]

        df_m = pd.merge(df_prop, df_cmed[['Reg_C', coluna_icms, c_apres_cmed]], left_on='Reg_L', right_on='Reg_C', how='left')
        df_m['PF_Num'] = df_m[coluna_icms].apply(formatar_moeda)
        df_m['Divisor'] = df_m.apply(lambda x: extrair_divisor_inteligente(x[c_apres_cmed], x[c_unid]), axis=1)
        df_m['Teto_U'] = df_m['PF_Num'] / df_m['Divisor']

        df_precos = df_m[(df_m['V_Unit'] > (df_m['Teto_U'] + 0.0005)) & (df_m['Teto_U'] > 0)].copy()
        df_reg_err = df_m[(df_m['Reg_L'].str.len() > 0) & ((df_m['Reg_L'].str.len() != 13) | (df_m['Reg_C'].isna()))].copy()

        for df in [df_precos, df_reg_err]:
            if not df.empty:
                df['Col_Item'] = df[c_item]; df['Col_Desc'] = df[c_desc]; df['Col_Reg'] = df[c_reg]
                if 'Teto_U' in df.columns: df['Diferenca'] = df['V_Unit'] - df['Teto_U']

        return df_precos, df_reg_err, cabecalho_info, None
    except Exception as e:
        return None, None, None, f"Erro: {str(e)}"

# --- INTERFACE ---
df_cmed = carregar_cmed()
with st.sidebar:
    # Lógica Robusta de Logo
    logo_carregada = False
    for nome_arq in ["logo.png", "logo_drogafonte.png"]:
        if os.path.exists(nome_arq):
            try:
                base64_img = get_image_base64(nome_arq)
                st.markdown(f'<img src="data:image/png;base64,{base64_img}" width="200">', unsafe_表面=True)
                logo_carregada = True
                break
            except: continue
    
    if not logo_carregada:
        st.image("https://drogafonte.com.br/wp-content/uploads/2021/10/logo-drogafonte.png", width=200)

    st.divider()
    aliquota = st.selectbox("ICMS Destino:", ["PF 12%", "PF 17%", "PF 17,5%", "PF 18%", "PF 19%", "PF 19,5%", "PF 20%", "PF 20,5%", "PF 21%", "PF 22%"], index=7)

st.title("🛡️ Validador CMED - Drogafonte")

if not st.session_state.tela_resultado:
    upload = st.file_uploader("Arraste sua Proposta", type=['xls', 'xlsx', 'csv'])
    if upload and st.button("🚀 Iniciar Auditoria", use_container_width=True, type="primary"):
        p, r, c, err = processar_dados(upload, df_cmed, aliquota)
        st.session_state.dados_finais, st.session_state.erros_registro, st.session_state.cabecalho_pdf, st.session_state.erro, st.session_state.aliquota = p, r, c, err, aliquota
        st.session_state.tela_resultado = True
        st.rerun()
else:
    st.button("⬅️ Voltar", on_click=resetar_app)
    if st.session_state.erro: st.error(st.session_state.erro)
    else:
        st.subheader("🚨 Divergências")
        st.dataframe(st.session_state.dados_finais[['Col_Item', 'Col_Desc', 'V_Unit', 'Teto_U', 'Diferenca']], use_container_width=True)
        st.download_button("📥 Excel", exportar_excel(st.session_state.dados_finais), "Resultado.xlsx")
        
        if st.button("📄 Gerar PDF"):
            pdf = FPDF(orientation='L', unit='mm', format='A4')
            pdf.add_page()
            pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "Relatório de Auditoria", ln=True, align='C')
            # ... (Lógica do PDF continua aqui)
            st.download_button("💾 Baixar PDF", pdf.output(dest='S').encode('latin-1'), "Relatorio.pdf", "application/pdf")
