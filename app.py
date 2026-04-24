import streamlit as st
import pandas as pd
from fpdf import FPDF
import io
import re
import os
import base64

# Configuração da Página
st.set_page_config(page_title="Auditoria Drogafonte", layout="wide", page_icon="🛡️")

# --- FUNÇÃO PARA LOGO EM BASE64 (PREVINE QUE A LOGO SUMA) ---
def get_image_base64(path):
    try:
        with open(path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    except:
        return None

# --- ESTADOS DO SISTEMA ---
if 'tela_resultado' not in st.session_state:
    st.session_state.tela_resultado = False

def resetar_app():
    st.session_state.tela_resultado = False
    for key in ['dados_finais', 'erros_registro', 'cabecalho_pdf', 'erro', 'aliquota']:
        if key in st.session_state: del st.session_state[key]

# --- MOTOR DE INTELIGÊNCIA V3 (FOCO TOTAL NA CMED) ---
def extrair_divisor_inteligente(apres_cmed, unid_proposta):
    apres_cmed = str(apres_cmed).upper()
    unid_proposta = str(unid_proposta).upper().strip()

    # EXCEÇÃO: Se a proposta explicitar que o preço é por DOSE, CX ou CAR, não divide.
    if any(x in unid_proposta for x in ["DOS", "DOSE", "CX", "CAIXA", "CAR", "CART"]):
        return 1

    # PARA TODO O RESTO: Ignora a coluna 'Apr.' da proposta e busca a qtde na CMED
    
    # 1. Busca padrão de multiplicação (ex: 3 BLISTERS X 10 ou 10 FRASCOS X 5ML)
    m = re.search(r'\b(\d+)\s+(?:BL|ENV|STRIP|CPR|CAP|AMP|FA|FR|SER|TB|BS|CJ).*?X\s+(\d+)\b', apres_cmed)
    if m: 
        return float(m.group(1)) * float(m.group(2))
    
    # 2. Busca padrão "X Quantidade" (ex: CX X 30) - Ignora se for milhagem ou porcentagem
    m = re.search(r'X\s+(\d+)\b(?!\s*(?:ML|MG|G|MCG|UI|%))', apres_cmed)
    if m: 
        return float(m.group(1))
    
    # 3. Busca padrão "Contém/Com" (ex: CT C/ 20)
    m = re.search(r'(?:C/|CT|CX|COM|CONTEM)\s*(\d+)\b', apres_cmed)
    if m: 
        return float(m.group(1))
    
    return 1 # Fallback para unidade simples

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
        df.to_excel(writer, index=False, sheet_name='Auditoria_Drogafonte')
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
        
        # APLICAÇÃO DA REGRA: CMED É SOBERANA (EXCETO DOSE)
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
    # Logo Robusta (Base64 + Fallback URL)
    logo_b64 = get_image_base64("logo.png") or get_image_base64("logo_drogafonte.png")
    if logo_b64:
        st.markdown(f'<img src="data:image/png;base64,{logo_b64}" width="200">', unsafe_allow_html=True)
    else:
        st.image("https://drogafonte.com.br/wp-content/uploads/2021/10/logo-drogafonte.png", width=200)

    st.divider()
    aliquota = st.selectbox("ICMS Destino:", ["PF 12%", "PF 17%", "PF 17,5%", "PF 18%", "PF 19%", "PF 19,5%", "PF 20%", "PF 20,5%", "PF 21%", "PF 22%"], index=7)
    if df_cmed is not None: st.success("Base CMED Ativa")

st.title("🛡️ Auditoria Drogafonte - Validador CMED")

if not st.session_state.tela_resultado:
    upload = st.file_uploader("Arraste a Proposta (Excel ou CSV)", type=['xls', 'xlsx', 'csv'])
    if upload and st.button("🚀 Iniciar Auditoria", use_container_width=True, type="primary"):
        p, r, c, err = processar_dados(upload, df_cmed, aliquota)
        st.session_state.dados_finais, st.session_state.erros_registro, st.session_state.cabecalho_pdf, st.session_state.erro, st.session_state.aliquota = p, r, c, err, aliquota
        st.session_state.tela_resultado = True
        st.rerun()
else:
    if st.button("⬅️ Realizar Nova Análise", on_click=resetar_app): pass
    
    if st.session_state.erro:
        st.error(st.session_state.erro)
    else:
        # TABELA DIVERGÊNCIAS
        st.subheader("🚨 Itens Acima do Teto")
        df_p = st.session_state.dados_finais
        if df_p.empty:
            st.success("Nenhuma divergência encontrada!")
        else:
            exib_p = df_p[['Col_Item', 'Col_Desc', 'V_Unit', 'Teto_U', 'Diferenca']].copy()
            exib_p.columns = ['Item', 'Descrição', 'Valor Proposta', 'Teto CMED', 'Diferença']
            st.dataframe(exib_p.style.format({'Valor Proposta': 'R$ {:.4f}', 'Teto CMED': 'R$ {:.4f}', 'Diferença': 'R$ {:.4f}'}), use_container_width=True)
            st.download_button("📥 Baixar Planilha de Divergências", exportar_excel(exib_p), "Divergencias_CMED.xlsx")

        # TABELA REGISTROS
        df_r = st.session_state.erros_registro
        if not df_r.empty:
            st.divider()
            st.subheader("⚠️ Alertas de Registro / Notificados")
            exib_r = df_r[['Col_Item', 'Col_Desc', 'Col_Reg']].copy()
            exib_r.columns = ['Item', 'Descrição', 'Registro Informado']
            st.dataframe(exib_r, use_container_width=True)
            st.download_button("📥 Baixar Planilha de Alertas", exportar_excel(exib_r), "Alertas_Registro.xlsx")

        # PDF FINAL
        if st.button("📄 Gerar Relatório PDF Final", type="primary", use_container_width=True):
            pdf = FPDF(orientation='L', unit='mm', format='A4')
            pdf.add_page()
            pdf.set_font("Arial", 'B', 10)
            for h in st.session_state.cabecalho_pdf[:4]: 
                pdf.cell(0, 5, str(h).encode('latin-1', 'replace').decode('latin-1'), ln=True)
            pdf.ln(5)
            pdf.set_font("Arial", 'B', 14); pdf.set_text_color(180, 0, 0)
            pdf.cell(0, 10, f"RELATORIO DE DIVERGENCIAS - {st.session_state.aliquota}", ln=True, align='C')
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

            st.download_button("💾 Salvar Relatório PDF", pdf.output(dest='S').encode('latin-1'), "Auditoria_Drogafonte.pdf", "application/pdf")
