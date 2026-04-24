import streamlit as st
import pandas as pd
import re
import io
import os
from fpdf import FPDF

# 1. CONFIGURAÇÃO DA PÁGINA
st.set_page_config(page_title="Auditoria Drogafonte", page_icon="💊", layout="centered")

# 2. LOGO E TÍTULO
# Tenta carregar a logo. Se não encontrar, exibe apenas o título.
if os.path.exists("logo_drogafonte.png"):
    st.image("logo_drogafonte.png", width=250)
else:
    st.sidebar.warning("Arquivo 'logo_drogafonte.png' não encontrado no GitHub.")

st.title("Portal de Auditoria - Drogafonte")
st.markdown("Valide suas propostas contra o teto da **CMED** com inteligência de fracionamento.")
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

# 4. FUNÇÕES DE APOIO
def extrair_qtd_cmed(apres):
    apres = str(apres).upper()
    if "DOS" in apres: return 1
    m = re.search(r'\b(\d+)\s+(?:BL|ENV|STRIP).*?X\s+(\d+)\b(?!\s*(?:ML|MG|G|MCG|UI))', apres)
    if m: return int(m.group(1)) * int(m.group(2))
    m = re.search(r'\b(\d+)\s+(?:AMP|FA|FR|SER|BOLS|CARP|TUB|BOMBA|CANETA|SVD)\b', apres)
    if m: return int(m.group(1))
    m = re.search(r'X\s+(\d+)\b(?!\s*(?:ML|MG|G|MCG|UI|U\.I\.))', apres)
    if m: return int(m.group(1))
    return 1

def ler_proposta_robusto(file_buffer):
    try:
        # Tenta ler como Excel real
        return pd.read_excel(file_buffer, header=None)
    except:
        # Fallback para CSV/TXT disfarçado de XLS (comum em ERPs)
        file_buffer.seek(0)
        return pd.read_csv(file_buffer, encoding='latin1', sep=None, engine='python', header=None, on_bad_lines='skip')

# 5. ÁREA DE UPLOAD
uploaded_file = st.file_uploader("📥 Arraste a proposta (Excel ou arquivo do sistema)", type=['xls', 'xlsx', 'csv'])

if uploaded_file is not None:
    if st.button("🚀 Executar Auditoria Oficial", use_container_width=True):
        with st.spinner('Cruzando dados com a base da Anvisa...'):
            try:
                # Carregar Base CMED
                df_cmed = pd.read_excel('cmed_atual.xlsx')
                df_cmed.columns = df_cmed.columns.astype(str).str.strip()
                
                # Localizar cabeçalho da CMED se necessário
                if 'REGISTRO' not in df_cmed.columns:
                    for i, r in pd.read_excel('cmed_atual.xlsx', header=None).iterrows():
                        if r.astype(str).str.contains('REGISTRO').any():
                            df_cmed = pd.read_excel('cmed_atual.xlsx', skiprows=i)
                            df_cmed.columns = df_cmed.columns.astype(str).str.strip()
                            break
                
                c_apres_cmed = [c for c in df_cmed.columns if 'APRESENTA' in str(c).upper()][0]

                # Processar Proposta
                df_raw = ler_proposta_robusto(uploaded_file)
                
                # Localizar linha do cabeçalho na proposta
                linha_cab = 0
                for i, row in df_raw.iterrows():
                    if row.astype(str).str.contains('Reg.M.S|Vlr. Unit.', case=False).any():
                        linha_cab = i
                        break
                
                # Capturar dados da Drogafonte para o cabeçalho do PDF
                cabecalho_pdf = [" ".join(df_raw.iloc[j].dropna().astype(str).tolist()) for j in range(linha_cab) if str(df_raw.iloc[j].dropna()).strip()]

                df_prop = df_raw.iloc[linha_cab+1:].copy()
                df_prop.columns = df_raw.iloc[linha_cab].astype(str).str.strip()

                # Mapear colunas da proposta
                c_desc = [c for c in df_prop.columns if any(x in str(c) for x in ['D i s c', 'Descrição', 'Nome'])][0]
                c_reg = [c for c in df_prop.columns if 'REG.M.S' in str(c).upper().replace(' ', '') or 'REGISTRO' in str(c).upper()][0]
                c_vlr = [c for c in df_prop.columns if 'VLR' in str(c).upper() and 'UNIT' in str(c).upper()][0]

                # Cálculos de Auditoria
                df_prop['Reg_L'] = df_prop[c_reg].astype(str).str.replace(r'[^0-9]', '', regex=True)
                df_cmed['Reg_C'] = df_cmed['REGISTRO'].astype(str).str.replace(r'[^0-9]', '', regex=True)
                df_prop['V_Unit'] = df_prop[c_vlr].astype(str).str.replace(',', '.').astype(float)

                df_m = pd.merge(df_prop, df_cmed[['Reg_C', estado_destino, c_apres_cmed]], left_on='Reg_L', right_on='Reg_C', how='left')
                df_m['PF_Num'] = df_m[estado_destino].astype(str).str.replace(',', '.').astype(float)
                df_m['Qtd_C'] = df_m[c_apres_cmed].apply(extrair_qtd_cmed)
                df_m['Teto_U'] = df_m['PF_Num'] / df_m['Qtd_C']
                
                df_erros = df_m[df_m['V_Unit'] > (df_m['Teto_U'] + 0.0001)].copy()

                # 6. GERAÇÃO DO PDF PROFISSIONAL
                pdf = FPDF(orientation='L', unit='mm', format='A4')
                pdf.add_page()
                
                # Logo no PDF (se existir)
                if os.path.exists("logo_drogafonte.png"):
                    pdf.image("logo_drogafonte.png", 10, 8, 40)
                    pdf.ln(15)

                pdf.set_font("Arial", 'B', 9)
                for l in cabecalho_pdf[:4]: pdf.cell(0, 5, l, ln=True)
                pdf.ln(5); pdf.set_draw_color(180); pdf.line(10, pdf.get_y(), 287, pdf.get_y()); pdf.ln(5)
                
                pdf.set_font("Arial", 'B', 14); pdf.set_text_color(200, 0, 0)
                pdf.cell(0, 10, f"RELATÓRIO DE DIVERGÊNCIAS CMED - DESTINO: {estado_destino}", ln=True, align='C')
                pdf.ln(5)

                if df_erros.empty:
                    pdf.set_font("Arial", 'B', 16); pdf.set_text_color(0, 120, 0)
                    pdf.cell(0, 30, "✅ PROPOSTA AUDITADA: TODOS OS ITENS DENTRO DO TETO.", ln=True, align='C')
                else:
                    pdf.set_font("Arial", 'B', 8); pdf.set_text_color(0); pdf.set_fill_color(240)
                    pdf.cell(12, 8, "Item", 1, 0, 'C', True)
                    pdf.cell(128, 8, "Descrição do Medicamento", 1, 0, 'C', True)
                    pdf.cell(34, 8, "Vlr. Proposta", 1, 0, 'C', True)
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

                pdf_file = "Auditoria_Drogafonte.pdf"
                pdf.output(pdf_file)

                st.success("Auditoria Concluída!")
                with open(pdf_file, "rb") as f:
                    st.download_button("📩 Baixar Relatório de Divergências (PDF)", f, file_name=pdf_file, mime="application/pdf", type="primary")

            except Exception as e:
                st.error(f"Erro Crítico: {e}")

# Rodapé
st.caption("Drogafonte - Sistema de Integridade em Licitações Públicas v2.0")
