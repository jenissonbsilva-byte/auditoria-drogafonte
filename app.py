import streamlit as st
import pandas as pd
import re
import io
import os
from fpdf import FPDF

# 1. CONFIGURAÇÃO DA PÁGINA
st.set_page_config(page_title="Auditoria Drogafonte", page_icon="💊", layout="centered")

# --- NOVO: FUNÇÃO COM CACHE PARA VELOCIDADE MÁXIMA ---
@st.cache_data(show_spinner=False)
def carregar_base_cmed(caminho):
    try:
        df = pd.read_excel(caminho)
        df.columns = [str(c).strip().upper() for c in df.columns]
        
        # Se não achar o cabeçalho "REGISTRO", varre o ficheiro
        if not any('REGISTRO' in c for c in df.columns):
            df_temp = pd.read_excel(caminho, header=None)
            for i, r in df_temp.iterrows():
                if any('REGISTRO' in str(v).upper() for v in r):
                    df = pd.read_excel(caminho, skiprows=i)
                    df.columns = [str(c).strip().upper() for c in df.columns]
                    break
        return df
    except Exception as e:
        return None

# 2. LOGO E TÍTULO
if os.path.exists("logo_drogafonte.png"):
    st.image("logo_drogafonte.png", width=250)

st.title("Portal de Auditoria - Drogafonte")
st.markdown("Valide suas propostas com velocidade e precisão matemática.")
st.divider()

# 3. CONFIGURAÇÕES LATERAIS
st.sidebar.header("⚙️ Configurações")
if os.path.exists("logo_drogafonte.png"):
    st.sidebar.image("logo_drogafonte.png", use_container_width=True)

estado_destino = st.sidebar.selectbox(
    "Estado da Licitação:", 
    ["PF 12 %", "PF 17 %", "PF 17,5 %", "PF 18 %", "PF 19 %", "PF 20 %", "PF 20,5 %"], 
    index=6
).upper()

# 4. MOTOR DE FRACIONAMENTO BLINDADO (Decimais e Seringas)
def extrair_qtd_cmed(apres):
    texto = str(apres).upper().strip()
    if texto == 'NAN' or not texto: return 1
    
    termos_coletivos = ['CX', 'CAR', 'CT', 'ML', 'AMP', 'FA', 'FR', 'SER', 'BOLS', 'CART']
    if not any(termo in texto for termo in termos_coletivos):
        return 1
    
    if "DOS" in texto: return 1
    
    # Busca flexível de recipientes (SER, SERG, SERINGA, etc)
    m = re.search(r'\b(\d+)\s+(?:AMP|FA|FR|SER|BOLS|CARP|TUB|BOMBA|CANETA|SVD)[A-Z]*\b', texto)
    if m: return int(m.group(1))
    
    # Múltiplos com escudo decimal (ex: 50 BL X 10)
    m = re.search(r'\b(\d+)\s+(?:BL|ENV|STRIP).*?X\s+(\d+)\b(?!\s*[,.]|\s*(?:ML|MG|G|MCG|UI))', texto)
    if m: return int(m.group(1)) * int(m.group(2))
    
    # Multiplicador final com escudo decimal (Ignora volumes como X 0,6 ML)
    m = re.search(r'X\s+(\d+)\b(?!\s*[,.]|\s*(?:ML|MG|G|MCG|UI|U\.I\.))', texto)
    if m: return int(m.group(1))
    
    return 1

def ler_proposta_robusto(file_buffer):
    try:
        return pd.read_excel(file_buffer, header=None)
    except:
        file_buffer.seek(0)
        try:
            return pd.read_csv(file_buffer, encoding='latin1', sep=None, engine='python', header=None, on_bad_lines='skip')
        except:
            return None

# 5. EXECUÇÃO
if not os.path.exists('cmed_atual.xlsx'):
    st.error("Erro: O ficheiro 'cmed_atual.xlsx' não foi encontrado no GitHub.")
else:
    df_cmed_base = carregar_base_cmed('cmed_atual.xlsx')
    
    uploaded_file = st.file_uploader("📥 Arraste a proposta aqui", type=['xls', 'xlsx', 'csv'])

    if uploaded_file is not None:
        if st.button("🚀 Executar Auditoria", use_container_width=True):
            with st.spinner('A processar auditoria...'):
                try:
                    df_cmed = df_cmed_base.copy()
                    
                    # PROTEÇÃO CMED: Evita o erro 'REGISTRO' e 'Index out of range'
                    lista_apres = [c for c in df_cmed.columns if 'APRESENTA' in c]
                    c_apres_cmed = lista_apres[0] if lista_apres else df_cmed.columns[10]
                    
                    lista_reg = [c for c in df_cmed.columns if 'REGISTRO' in c]
                    c_reg_cmed = lista_reg[0] if lista_reg else df_cmed.columns[0]

                    df_raw = ler_proposta_robusto(uploaded_file)
                    
                    linha_cab = 0
                    achou = False
                    for i, row in df_raw.iterrows():
                        celulas = [str(v).upper() for v in row.tolist()]
                        if any('REG' in c or 'M.S' in c for c in celulas) and any('VLR' in c or 'UNIT' in c for c in celulas):
                            linha_cab = i
                            achou = True
                            break
                    
                    if not achou:
                        st.error("Cabeçalho da proposta não identificado.")
                        st.stop()

                    cab_pdf = [" ".join(df_raw.iloc[j].dropna().astype(str).tolist()) for j in range(linha_cab) if str(df_raw.iloc[j].dropna()).strip()]
                    df_prop = df_raw.iloc[linha_cab+1:].copy()
                    df_prop.columns = [str(c).strip().upper() for c in df_raw.iloc[linha_cab].tolist()]

                    # PROTEÇÃO PROPOSTA: Evita 'list index out of range'
                    def find_col(nomes, idx):
                        for c in df_prop.columns:
                            if any(n in str(c) for n in nomes): return c
                        return df_prop.columns[idx] if idx < len(df_prop.columns) else df_prop.columns[-1]

                    c_desc = find_col(['DISC', 'DESC', 'NOME', 'PROD'], 2)
                    c_reg = find_col(['REG', 'M.S', 'MS'], 6)
                    c_vlr = find_col(['VLR', 'UNIT', 'PREÇO'], 9)

                    # Cruzamento
                    df_prop['REG_L'] = df_prop[c_reg].astype(str).str.replace(r'[^0-9]', '', regex=True)
                    df_cmed['REG_C'] = df_cmed[c_reg_cmed].astype(str).str.replace(r'[^0-9]', '', regex=True)
                    
                    df_prop['V_UNIT_N'] = df_prop[c_vlr].astype(str).str.replace('R$', '').str.replace(' ', '').str.replace('.', '').str.replace(',', '.').astype(float)

                    df_m = pd.merge(df_prop, df_cmed[['REG_C', estado_destino, c_apres_cmed]], left_on='REG_L', right_on='REG_C', how='left')
                    df_m['PF_NUM'] = df_m[estado_destino].astype(str).str.replace('.', '').str.replace(',', '.').astype(float)
                    df_m['QTD_C'] = df_m[c_apres_cmed].apply(extrair_qtd_cmed)
                    df_m['TETO_U'] = df_m['PF_NUM'] / df_m['QTD_C']
                    
                    df_erros = df_m[df_m['V_UNIT_N'] > (df_m['TETO_U'] + 0.0001)].copy()

                    # PDF
                    pdf = FPDF(orientation='L', unit='mm', format='A4')
                    pdf.add_page()
                    if os.path.exists("logo_drogafonte.png"): pdf.image("logo_drogafonte.png", 10, 8, 40); pdf.ln(15)

                    pdf.set_font("Arial", 'B', 9)
                    for l in cab_pdf[:4]: pdf.cell(0, 5, l, ln=True)
                    pdf.ln(5); pdf.set_draw_color(180); pdf.line(10, pdf.get_y(), 287, pdf.get_y()); pdf.ln(5)
                    pdf.set_font("Arial", 'B', 14); pdf.set_text_color(200, 0, 0)
                    pdf.cell(0, 10, f"RELATÓRIO DE DIVERGÊNCIAS CMED - {estado_destino}", ln=True, align='C')
                    pdf.ln(5)

                    if df_erros.empty:
                        pdf.set_font("Arial", 'B', 16); pdf.set_text_color(0, 120, 0)
                        pdf.cell(0, 30, "✅ PROPOSTA 100% OK.", ln=True, align='C')
                    else:
                        pdf.set_font("Arial", 'B', 8); pdf.set_text_color(0); pdf.set_fill_color(240)
                        pdf.cell(12, 8, "Item", 1, 0, 'C', True)
                        pdf.cell(128, 8, "Descrição", 1, 0, 'C', True)
                        pdf.cell(34, 8, "Sua Proposta", 1, 0, 'C', True)
                        pdf.cell(34, 8, "Teto CMED", 1, 0, 'C', True)
                        pdf.cell(34, 8, "Diferença", 1, 1, 'C', True)
                        pdf.set_font("Arial", '', 8)
                        for _, r in df_erros.iterrows():
                            pdf.cell(12, 7, str(r.get('ITEM', '-')), 1, 0, 'C')
                            pdf.cell(128, 7, str(r[c_desc])[:80], 1)
                            pdf.cell(34, 7, f"R$ {r['V_UNIT_N']:.4f}", 1, 0, 'C')
                            pdf.cell(34, 7, f"R$ {r['TETO_U']:.4f}", 1, 0, 'C')
                            pdf.set_text_color(200, 0, 0)
                            pdf.cell(34, 7, f"R$ {(r['V_UNIT_N'] - r['TETO_U']):.4f}", 1, 1, 'C')
                            pdf.set_text_color(0)

                    pdf_file = "Auditoria_Final.pdf"
                    pdf.output(pdf_file)
                    st.success("Auditoria Concluída!")
                    with open(pdf_file, "rb") as f:
                        st.download_button("📩 Baixar Relatório (PDF)", f, file_name=pdf_file, mime="application/pdf", type="primary")

                except Exception as e:
                    st.error(f"Erro de Auditoria: {e}")

st.caption("Drogafonte - v2.8 | Layout Original e Motor Protegido")
