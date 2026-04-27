import streamlit as st
import pandas as pd
import re
import io
import os
from fpdf import FPDF

# 1. CONFIGURAÇÃO DA PÁGINA
st.set_page_config(page_title="Auditoria Drogafonte", page_icon="💊", layout="centered")

# --- CACHE PARA PERFORMANCE ---
@st.cache_data(show_spinner=False)
def carregar_base_cmed(caminho):
    try:
        df = pd.read_excel(caminho)
        df.columns = [str(c).strip().upper() for c in df.columns]
        if 'REGISTRO' not in df.columns:
            df_temp = pd.read_excel(caminho, header=None)
            for i, r in df_temp.iterrows():
                if any('REGISTRO' in str(v).upper() for v in r):
                    df = pd.read_excel(caminho, skiprows=i)
                    df.columns = [str(c).strip().upper() for c in df.columns]
                    break
        return df
    except:
        return None

# 2. INTERFACE E LOGO
if os.path.exists("logo_drogafonte.png"):
    st.image("logo_drogafonte.png", width=250)
st.title("Portal de Auditoria - Drogafonte")
st.markdown("Sistema blindado contra erros de decimais (v2.7).")
st.divider()

# 3. SIDEBAR
st.sidebar.header("⚙️ Configurações")
if os.path.exists("logo_drogafonte.png"):
    st.sidebar.image("logo_drogafonte.png", use_container_width=True)
estado_destino = st.sidebar.selectbox("Estado:", ["PF 12 %", "PF 17 %", "PF 17,5 %", "PF 18 %", "PF 19 %", "PF 20 %", "PF 20,5 %"], index=6).upper()

# 4. MOTOR DE EXTRAÇÃO BLINDADO (v2.7)
def extrair_qtd_cmed(apres):
    texto = str(apres).upper().strip()
    if texto == 'NAN' or not texto: return 1
    
    # Se não houver indício de embalagem coletiva, é 1 unidade
    termos_coletivos = ['CX', 'CAR', 'CT', 'ML', 'AMP', 'FA', 'FR', 'SER', 'BOLS', 'CART']
    if not any(termo in texto for termo in termos_coletivos): return 1
    if "DOS" in texto: return 1
    
    # 1. Busca recipientes de forma flexível (SER, SERG, SERINGA, etc)
    m = re.search(r'\b(\d+)\s+(?:AMP|FA|FR|SER|BOLS|CARP|TUB|BOMBA|CANETA|SVD)[A-Z]*\b', texto)
    if m: return int(m.group(1))
    
    # 2. Busca múltiplos (50 BL X 10) - Ignora se houver vírgula logo após o número
    m = re.search(r'\b(\d+)\s+(?:BL|ENV|STRIP).*?X\s+(\d+)\b(?!\s*[,.]|\s*(?:ML|MG|G|MCG|UI))', texto)
    if m: return int(m.group(1)) * int(m.group(2))
    
    # 3. Busca X final - Ignora volumes decimais (ex: X 0,6 ML)
    m = re.search(r'X\s+(\d+)\b(?!\s*[,.]|\s*(?:ML|MG|G|MCG|UI|U\.I\.))', texto)
    if m: return int(m.group(1))
    
    return 1

def ler_proposta(file):
    try:
        return pd.read_excel(file, header=None)
    except:
        file.seek(0)
        return pd.read_csv(file, encoding='latin1', sep=None, engine='python', header=None, on_bad_lines='skip')

# 5. EXECUÇÃO
if os.path.exists('cmed_atual.xlsx'):
    df_cmed_base = carregar_base_cmed('cmed_atual.xlsx')
    file = st.file_uploader("📥 Submeta a Proposta", type=['xls', 'xlsx', 'csv'])

    if file and st.button("🚀 Auditar"):
        with st.spinner('A processar...'):
            try:
                df_cmed = df_cmed_base.copy()
                c_apres = [c for c in df_cmed.columns if 'APRESENTA' in c][0]
                df_raw = ler_proposta(file)
                
                linha_cab = 0
                for i, row in df_raw.iterrows():
                    cel = [str(v).upper() for v in row.tolist()]
                    if any('REG' in c or 'M.S' in c for c in cel) and any('VLR' in c or 'UNIT' in c for c in cel):
                        linha_cab = i
                        break
                
                cab_pdf = [" ".join(df_raw.iloc[j].dropna().astype(str).tolist()) for j in range(linha_cab) if str(df_raw.iloc[j].dropna()).strip()]
                df_prop = df_raw.iloc[linha_cab+1:].copy()
                df_prop.columns = [str(c).strip().upper() for c in df_raw.iloc[linha_cab].tolist()]

                def fc(n, i):
                    for c in df_prop.columns:
                        if any(x in str(c) for x in n): return c
                    return df_prop.columns[i]

                c_d, c_r, c_v = fc(['DISC', 'DESC', 'NOME'], 2), fc(['REG', 'M.S', 'MS'], 6), fc(['VLR', 'UNIT'], 9)
                
                df_prop['REG_L'] = df_prop[c_r].astype(str).str.replace(r'[^0-9]', '', regex=True)
                df_cmed['REG_C'] = df_cmed['REGISTRO'].astype(str).str.replace(r'[^0-9]', '', regex=True)
                df_prop['V_UNIT_N'] = df_prop[c_v].astype(str).str.replace('R$', '').str.replace(' ', '').str.replace('.', '').str.replace(',', '.').astype(float)

                df_m = pd.merge(df_prop, df_cmed[['REG_C', estado_destino, c_apres]], left_on='REG_L', right_on='REG_C', how='left')
                df_m['PF_VAL'] = df_m[estado_destino].astype(str).str.replace('.', '').str.replace(',', '.').astype(float)
                df_m['DIV'] = df_m[c_apres].apply(extrair_qtd_cmed)
                df_m['TETO'] = df_m['PF_VAL'] / df_m['DIV']
                
                df_err = df_m[df_m['V_UNIT_N'] > (df_m['TETO'] + 0.0001)].copy()

                pdf = FPDF(orientation='L', unit='mm', format='A4')
                pdf.add_page()
                if os.path.exists("logo_drogafonte.png"): pdf.image("logo_drogafonte.png", 10, 8, 40); pdf.ln(15)
                pdf.set_font("Arial", 'B', 9)
                for l in cab_pdf[:4]: pdf.cell(0, 5, l, ln=True)
                pdf.ln(5); pdf.set_draw_color(180); pdf.line(10, pdf.get_y(), 287, pdf.get_y()); pdf.ln(5)
                pdf.set_font("Arial", 'B', 14); pdf.set_text_color(200, 0, 0)
                pdf.cell(0, 10, f"DIVERGÊNCIAS CMED - {estado_destino}", ln=True, align='C')
                
                if df_err.empty:
                    pdf.set_font("Arial", 'B', 16); pdf.set_text_color(0, 120, 0)
                    pdf.cell(0, 30, "✅ TUDO OK.", ln=True, align='C')
                else:
                    pdf.set_font("Arial", 'B', 8); pdf.set_text_color(0); pdf.set_fill_color(240)
                    pdf.cell(10, 8, "Item", 1, 0, 'C', True); pdf.cell(130, 8, "Medicamento", 1, 0, 'C', True)
                    pdf.cell(32, 8, "Proposta", 1, 0, 'C', True); pdf.cell(32, 8, "Teto CMED", 1, 0, 'C', True); pdf.cell(32, 8, "Excesso", 1, 1, 'C', True)
                    pdf.set_font("Arial", '', 8)
                    for _, r in df_err.iterrows():
                        pdf.cell(10, 7, str(r.get('ITEM', '-')), 1)
                        pdf.cell(130, 7, str(r[c_d])[:85], 1)
                        pdf.cell(32, 7, f"R$ {r['V_UNIT_N']:.4f}", 1, 0, 'C')
                        pdf.cell(32, 7, f"R$ {r['TETO']:.4f}", 1, 0, 'C')
                        pdf.set_text_color(200, 0, 0); pdf.cell(32, 7, f"R$ {(r['V_UNIT_N']-r['TETO']):.4f}", 1, 1, 'C'); pdf.set_text_color(0)

                pdf.output("Auditoria.pdf")
                st.success("Concluído!")
                with open("Auditoria.pdf", "rb") as f:
                    st.download_button("📩 Baixar PDF", f, file_name="Auditoria_Drogafonte.pdf", mime="application/pdf")
            except Exception as e:
                st.error(f"Erro: {e}")
