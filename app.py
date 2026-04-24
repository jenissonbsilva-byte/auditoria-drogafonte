import streamlit as st
import pandas as pd
from fpdf import FPDF
import io
import re
import os

# Configuração da Página
st.set_page_config(page_title="Auditoria Drogafonte", layout="wide", page_icon="🛡️")

# --- ESTADOS DO SISTEMA ---
if 'tela_resultado' not in st.session_state:
    st.session_state.tela_resultado = False

def resetar_app():
    st.session_state.tela_resultado = False
    for key in ['dados_finais', 'erros_registro', 'cabecalho_pdf', 'erro', 'aliquota']:
        if key in st.session_state: del st.session_state[key]

# --- MOTOR DE INTELIGÊNCIA DE DIVISORES (REGRA ATUALIZADA) ---
def extrair_divisor_inteligente(apres_cmed, unid_proposta):
    apres_cmed = str(apres_cmed).upper()
    unid_proposta = str(unid_proposta).upper().strip()

    # 1. Se for Caixa (CX) ou Dose (DOS) -> Mantém preço integral
    if any(x in unid_proposta for x in ["CX", "CAIXA", "DOS", "DOSE"]):
        return 1

    # 2. Se for Cartela (CAR) -> Divide pela quantidade na cartela (ex: 1 X 21)
    if "CAR" in unid_proposta:
        m = re.search(r'(\d+)\s*X\s*(\d+)', apres_cmed)
        return float(m.group(2)) if m else 1

    # 3. PADRÃO: CONSIDERAR UNIDADE (Para ML, CPR, AMP, UN, etc)
    # O robô vasculha a CMED para descobrir o total de unidades na caixa
    
    # Padrão: 3 BLISTERS X 10 ou 10 FRASCOS X 5ML
    m = re.search(r'\b(\d+)\s+(?:BL|ENV|STRIP|CPR|CAP|AMP|FA|FR|SER).*?X\s+(\d+)\b', apres_cmed)
    if m: return float(m.group(1)) * float(m.group(2))
    
    # Padrão: CX X 30
    m = re.search(r'X\s+(\d+)\b(?!\s*(?:ML|MG|G|MCG|UI))', apres_cmed)
    if m: return float(m.group(1))
    
    # Padrão: CT C/ 20
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
        elif file_proposta.name.endswith('.xlsx'):
            df_raw = pd.read_excel(file_proposta, header=None, engine='openpyxl')
        else:
            df_raw = pd.read_csv(file_proposta, sep=None, engine='python', header=None)
            
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

# --- INTERFACE STREAMLIT ---
df_cmed = carregar_cmed()
with st.sidebar:
    try:
        st.image("https://drogafonte.com.br/wp-content/uploads/2021/10/logo-drogafonte.png", width=200)
    except:
        st.markdown("### 🛡️ DROGAFONTE")
    st.divider()
    aliquota = st.selectbox("ICMS Destino:", ["PF 12%", "PF 17%", "PF 17,5%", "PF 18%", "PF 19%", "PF 19,5%", "PF 20%", "PF 20,5%", "PF 21%", "PF 22%"], index=7)

st.title("🛡️ Validador CMED - Drogafonte")

if not st.session_state.tela_resultado:
    upload = st.file_uploader("Arraste sua Proposta (Excel ou CSV)", type=['xls', 'xlsx', 'csv'])
    if upload and st.button("🚀 Iniciar Auditoria", use_container_width=True, type="primary"):
        p, r, c, err = processar_dados(upload, df_cmed, aliquota)
        st.session_state.dados_finais, st.session_state.erros_registro, st.session_state.cabecalho_pdf, st.session_state.erro, st.session_state.aliquota = p, r, c, err, aliquota
        st.session_state.tela_resultado = True
        st.rerun()
else:
    st.button("⬅️ Nova Auditoria", on_click=resetar_app)
    
    if st.session_state.erro:
        st.error(st.session_state.erro)
    else:
        # Tabela de Preços
        st.subheader("🚨 Preços Acima do Teto")
        df_p = st.session_state.dados_finais
        if df_p.empty:
            st.success("Nenhuma divergência encontrada.")
        else:
            st.dataframe(df_p[['Col_Item', 'Col_Desc', 'V_Unit', 'Teto_U', 'Diferenca']].style.format('{:.4f}'), use_container_width=True)
            st.download_button("📥 Exportar Divergências (Excel)", exportar_excel(df_p), "Divergencias.xlsx")

        st.divider()

        # Alertas de Registro
        df_r = st.session_state.erros_registro
        if not df_r.empty:
            st.subheader("⚠️ Alertas de Registro")
            st.dataframe(df_r[['Col_Item', 'Col_Desc', 'Col_Reg']], use_container_width=True)
            st.download_button("📥 Exportar Alertas (Excel)", exportar_excel(df_r), "Alertas_Registro.xlsx")

        # Botão PDF
        if st.button("📄 Gerar Relatório PDF Final", type="primary", use_container_width=True):
            pdf = FPDF(orientation='L', unit='mm', format='A4')
            
            # Página 1: Preços
            pdf.add_page()
            pdf.set_font("Arial", 'B', 14); pdf.set_text_color(180, 0, 0)
            pdf.cell(0, 10, f"DIVERGENCIAS DE PRECO - {st.session_state.aliquota}", ln=True, align='C')
            pdf.set_font("Arial", 'B', 8); pdf.set_text_color(0); pdf.set_fill_color(230, 230, 230)
            pdf.cell(15, 8, "Item", 1, 0, 'C', True)
            pdf.cell(160, 8, "Descricao", 1, 0, 'C', True)
            pdf.cell(30, 8, "Proposta", 1, 0, 'C', True)
            pdf.cell(30, 8, "Teto", 1, 0, 'C', True)
            pdf.cell(30, 8, "Dif.", 1, 1, 'C', True)
            pdf.set_font("Arial", '', 8)
            for _, r in df_p.iterrows():
                pdf.cell(15, 7, str(r['Col_Item']), 1, 0, 'C')
                pdf.cell(160, 7, str(r['Col_Desc'])[:95].encode('latin-1', 'replace').decode('latin-1'), 1)
                pdf.cell(30, 7, f"{r['V_Unit']:.4f}", 1, 0, 'C')
                pdf.cell(30, 7, f"{r['Teto_U']:.4f}", 1, 0, 'C')
                pdf.cell(30, 7, f"{r['Diferenca']:.4f}", 1, 1, 'C')

            # Página 2: Registros
            if not df_r.empty:
                pdf.add_page()
                pdf.set_font("Arial", 'B', 14); pdf.cell(0, 10, "ALERTAS DE REGISTRO / NOTIFICADOS", ln=True, align='C')
                pdf.ln(5)
                pdf.set_font("Arial", 'B', 8); pdf.set_fill_color(230, 230, 230)
                pdf.cell(15, 8, "Item", 1, 0, 'C', True); pdf.cell(190, 8, "Descricao", 1, 0, 'C', True); pdf.cell(50, 8, "Registro", 1, 1, 'C', True)
                pdf.set_font("Arial", '', 8)
                for _, r in df_r.iterrows():
                    pdf.cell(15, 7, str(r['Col_Item']), 1, 0, 'C')
                    pdf.cell(190, 7, str(r['Col_Desc'])[:110].encode('latin-1', 'replace').decode('latin-1'), 1)
                    pdf.cell(50, 7, str(r['Col_Reg']), 1, 1, 'C')

            st.download_button("💾 Baixar PDF", pdf.output(dest='S').encode('latin-1'), "Relatorio_Drogafonte.pdf", "application/pdf")
