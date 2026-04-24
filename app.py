import streamlit as st
import pandas as pd
import re
import io
import os
from fpdf import FPDF

# 1. CONFIGURAÇÃO DA PÁGINA
st.set_page_config(page_title="Auditoria Drogafonte", page_icon="💊", layout="centered")

# 2. LOGO E TÍTULO
if os.path.exists("logo_drogafonte.png"):
    st.image("logo_drogafonte.png", width=250)

st.title("Portal de Auditoria - Drogafonte")
st.markdown("Valide suas propostas contra o teto da **CMED**.")
st.divider()

# 3. CONFIGURAÇÕES LATERAIS
st.sidebar.header("⚙️ Configurações")
if os.path.exists("logo_drogafonte.png"):
    st.sidebar.image("logo_drogafonte.png", use_container_width=True)

estado_destino = st.sidebar.selectbox(
    "Estado da Licitação (Coluna CMED):", 
    ["PF 12 %", "PF 17 %", "PF 17,5 %", "PF 18 %", "PF 19 %", "PF 20 %", "PF 20,5 %"], 
    index=6
)

# 4. FUNÇÃO DE FRACIONAMENTO BLINDADA (v2.5)
def extrair_qtd_cmed(apres):
    # Força a conversão para string e trata valores vazios
    texto = str(apres).upper().strip()
    if texto == 'NAN' or not texto:
        return 1
    
    # NOVA REGRA: Se não tiver menção a termos de embalagem/volume, considera 1 UNIDADE
    # Adicionamos 'UNID' e 'UN' para reforçar
    termos_coletivos = ['CX', 'CAR', 'CT', 'ML', 'AMP', 'FA', 'FR', 'SER', 'BOLS', 'CART']
    if not any(termo in texto for termo in termos_coletivos):
        return 1
    
    # Exceção para Doses (bombinhas)
    if "DOS" in texto: return 1
    
    # Busca por multiplicadores protegidos (Ex: 50 BL X 10)
    m = re.search(r'\b(\d+)\s+(?:BL|ENV|STRIP).*?X\s+(\d+)\b(?!\s*(?:ML|MG|G|MCG|UI))', texto)
    if m: return int(m.group(1)) * int(m.group(2))
    
    # Busca por recipientes (Ex: 100 AMP)
    m = re.search(r'\b(\d+)\s+(?:AMP|FA|FR|SER|BOLS|CARP|TUB|BOMBA|CANETA|SVD)\b', texto)
    if m: return int(m.group(1))
    
    # Busca pelo X de quantidade final (Ex: CT X 30)
    m = re.search(r'X\s+(\d+)\b(?!\s*(?:ML|MG|G|MCG|UI|U\.I\.))', texto)
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

# 5. ÁREA DE UPLOAD
uploaded_file = st.file_uploader("📥 Arraste a proposta (Excel ou arquivo do sistema)", type=['xls', 'xlsx', 'csv'])

if uploaded_file is not None:
    if st.button("🚀 Executar Auditoria Oficial", use_container_width=True):
        with st.spinner('Auditando itens...'):
            try:
                # Carregar Base CMED
                df_cmed = pd.read_excel('cmed_atual.xlsx')
                df_cmed.columns = [str(c).strip().upper() for c in df_cmed.columns]
                
                if 'REGISTRO' not in df_cmed.columns:
                    for i, r in pd.read_excel('cmed_atual.xlsx', header=None).iterrows():
                        if any('REGISTRO' in str(v).upper() for v in r):
                            df_cmed = pd.read_excel('cmed_atual.xlsx', skiprows=i)
                            df_cmed.columns = [str(c).strip().upper() for c in df_cmed.columns]
                            break
                
                col_apres_list = [c for c in df_cmed.columns if 'APRESENTA' in str(c).upper()]
                c_apres_cmed = col_apres_list[0] if col_apres_list else df_cmed.columns[10]

                # Processar Proposta
                df_raw = ler_proposta_robusto(uploaded_file)
                if df_raw is None: st.error("Erro na leitura."); st.stop()
                
                # BUSCA DE CABEÇALHO (Blindada contra floats)
                linha_cab = 0
                achou = False
                for i, row in df_raw.iterrows():
                    # Forçamos cada célula a ser string antes de testar o 'in'
                    celulas = [str(v).upper() for v in row.tolist()]
                    tem_reg = any('REG' in c or 'M.S' in c for c in celulas)
                    tem_vlr = any('VLR' in c or 'UNIT' in c for c in celulas)
                    
                    if tem_reg and tem_vlr:
                        linha_cab = i
                        achou = True
                        break
                
                if not achou:
                    st.error("Cabeçalho não identificado. Verifique as colunas da proposta.")
                    st.stop()

                cab_pdf = [" ".join(df_raw.iloc[j].dropna().astype(str).tolist()) for j in range(linha_cab) if str(df_raw.iloc[j].dropna()).strip()]
                df_prop = df_raw.iloc[linha_cab+1:].copy()
                df_prop.columns = [str(c).strip() for c in df_raw.iloc[linha_cab].tolist()]

                def find_col(nomes, idx_padrao):
                    for c in df_prop.columns:
                        if any(n.upper() in str(c).upper() for n in nomes):
                            return c
                    return df_prop.columns[idx_padrao]

                c_desc = find_col(['DISC', 'DESC', 'NOME', 'PRODUTO'], 2)
                c_reg = find_col(['REG', 'M.S', 'MS'], 6)
                c_vlr = find_col(['VLR', 'UNIT', 'PREÇO'], 9)

                # Cálculos
                df_prop['Reg_L'] = df_prop[c_reg].astype(str).str.replace(r'[^0-9]', '', regex=True)
                df_cmed['Reg_C'] = df_cmed['REGISTRO'].astype(str).str.replace(r'[^0-9]', '', regex=True)
                
                # Limpeza de valores (remove R$ e espaços)
                df_prop['V_Unit'] = df_prop[c_vlr].astype(str).str.replace('R$', '').str.replace(' ', '').str.replace('.', '').str.replace(',', '.').astype(float)

                df_m = pd.merge(df_prop, df_cmed[['Reg_C', estado_destino.upper(), c_apres_cmed]], left_on='Reg_L', right_on='Reg_C', how='left')
                df_m['PF_Num'] = df_m[estado_destino.upper()].astype(str).str.replace('.', '').str.replace(',', '.').astype(float)
                df_m['Qtd_C'] = df_m[c_apres_cmed].apply(extrair_qtd_cmed)
                df_m['Teto_U'] = df_m['PF_Num'] / df_m['Qtd_C']
                
                df_erros = df_m[df_m['V_Unit'] > (df_m['Teto_U'] + 0.0001)].copy()

                # 6. GERAÇÃO DO PDF
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
                    pdf.cell(0, 30, "✅ PROPOSTA 100% OK - DENTRO DO TETO CMED.", ln=True, align='C')
                else:
                    pdf.set_font("Arial", 'B', 8); pdf.set_text_color(0); pdf.set_fill_color(240)
                    pdf.cell(12, 8, "Item", 1, 0, 'C', True)
                    pdf.cell(128, 8, "Descrição", 1, 0, 'C', True)
                    pdf.cell(34, 8, "Sua Proposta", 1, 0, 'C', True)
                    pdf.cell(34, 8, "Teto CMED", 1, 0, 'C', True)
                    pdf.cell(34, 8, "Diferença", 1, 1, 'C', True)
                    pdf.set_font("Arial", '', 8)
                    for _, r in df_erros.iterrows():
                        pdf.cell(12, 7, str(r.get('Item', '-')), 1, 0, 'C')
                        pdf.cell(128, 7, str(r[c_desc])[:80], 1)
                        pdf.cell(34, 7, f"R$ {r['V_Unit']:.4f}", 1, 0, 'C')
                        pdf.cell(34, 7, f"R$ {r['Teto_U']:.4f}", 1, 0, 'C')
                        pdf.set_text_color(200, 0, 0)
                        pdf.cell(34, 7, f"R$ {(r['V_Unit'] - r['Teto_U']):.4f}", 1, 1, 'C')
                        pdf.set_text_color(0)

                pdf_file = "Auditoria_Final.pdf"
                pdf.output(pdf_file)
                st.success("Concluído!")
                with open(pdf_file, "rb") as f:
                    st.download_button("📩 Baixar Relatório (PDF)", f, file_name=pdf_file, mime="application/pdf", type="primary")

            except Exception as e:
                st.error(f"Erro Crítico de Auditoria: {e}")

st.caption("Drogafonte - Sistema de Integridade v2.5")
