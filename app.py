import streamlit as st
import pandas as pd
import re
import io
import os
from fpdf import FPDF

# Configuração da Página
st.set_page_config(page_title="Auditoria Drogafonte", page_icon="💊", layout="centered")

# Cabeçalho Visual
st.image("https://cdn-icons-png.flaticon.com/512/3024/3024310.png", width=80) # Ícone genérico (pode trocar pela logo depois)
st.title("Portal de Auditoria - Drogafonte")
st.markdown("Valide suas propostas contra o teto da **CMED** com processamento inteligente de fracionamento e doses.")
st.divider()

# Menu Lateral (Sidebar)
st.sidebar.header("⚙️ Configurações")
estado_destino = st.sidebar.selectbox(
    "Estado da Licitação:", 
    ["PF 12 %", "PF 17 %", "PF 17,5 %", "PF 18 %", "PF 19 %", "PF 20 %", "PF 20,5 %"], 
    index=6
)
st.sidebar.info("A base da CMED é lida automaticamente do sistema. Suba apenas a sua proposta.")

# Motor Matemático (O mesmo que validamos)
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

def ler_proposta(file_buffer, nome_arq):
    try:
        return pd.read_excel(file_buffer, header=None)
    except:
        file_buffer.seek(0)
        content = file_buffer.read().decode('latin1')
        return pd.read_csv(io.StringIO(content), sep=None, engine='python', header=None)

# Área de Upload
uploaded_file = st.file_uploader("📥 Arraste sua proposta aqui (Excel ou arquivo do sistema)", type=['xls', 'xlsx', 'csv'])

if uploaded_file is not None:
    if st.button("🚀 Executar Auditoria", use_container_width=True):
        with st.spinner('Lendo dados e cruzando com a Anvisa...'):
            try:
                # 1. Lê CMED (O arquivo deve estar na mesma pasta no GitHub)
                df_cmed = pd.read_excel('cmed_atual.xlsx')
                df_cmed.columns = df_cmed.columns.astype(str).str.strip()
                if 'REGISTRO' not in df_cmed.columns:
                    for i, r in pd.read_excel('cmed_atual.xlsx', header=None).iterrows():
                        if r.astype(str).str.contains('REGISTRO').any():
                            df_cmed = pd.read_excel('cmed_atual.xlsx', skiprows=i)
                            df_cmed.columns = df_cmed.columns.astype(str).str.strip()
                            break
                c_apres = [c for c in df_cmed.columns if 'APRESENTA' in str(c).upper()][0]

                # 2. Lê Proposta
                df_raw = ler_proposta(uploaded_file, uploaded_file.name)
                linha_cab = 0
                for i, row in df_raw.iterrows():
                    if row.astype(str).str.contains('Reg.M.S|Vlr. Unit.', case=False).any():
                        linha_cab = i
                        break
                
                cabecalho_info = [" ".join(df_raw.iloc[j].dropna().astype(str).tolist()) for j in range(linha_cab) if str(df_raw.iloc[j].dropna()).strip()]
                
                df_prop = df_raw.iloc[linha_cab+1:].copy()
                df_prop.columns = df_raw.iloc[linha_cab].astype(str).str.strip()
                c_desc = [c for c in df_prop.columns if 'D i s c' in c or 'Nome Com' in c or 'Descrição' in c][0]
                c_reg = [c for c in df_prop.columns if 'REG.M.S' in c.upper().replace(' ', '') or 'REGISTRO' in c.upper()][0]
                c_vlr = [c for c in df_prop.columns if 'VLR' in c.upper() and 'UNIT' in c.upper()][0]

                # 3. Cruzamento
                df_prop['Reg_L'] = df_prop[c_reg].astype(str).str.replace(r'[^0-9]', '', regex=True)
                df_cmed['Reg_C'] = df_cmed['REGISTRO'].astype(str).str.replace(r'[^0-9]', '', regex=True)
                df_prop['V_Unit'] = df_prop[c_vlr].astype(str).str.replace(',', '.').astype(float)

                df_m = pd.merge(df_prop, df_cmed[['Reg_C', estado_destino, c_apres]], left_on='Reg_L', right_on='Reg_C', how='left')
                df_m['PF_Num'] = df_m[estado_destino].astype(str).str.replace(',', '.').astype(float)
                df_m['Qtd_C'] = df_m[c_apres].apply(extrair_qtd_cmed)
                df_m['Teto_U'] = df_m['PF_Num'] / df_m['Qtd_C']
                df_erros = df_m[df_m['V_Unit'] > df_m['Teto_U']].copy()

                # 4. Geração do PDF
                pdf = FPDF(orientation='L', unit='mm', format='A4')
                pdf.add_page()
                pdf.set_font("Arial", 'B', 10)
                for l in cabecalho_info[:5]: pdf.cell(0, 5, l, ln=True)
                pdf.ln(5); pdf.set_draw_color(180); pdf.line(10, pdf.get_y(), 287, pdf.get_y()); pdf.ln(5)
                pdf.set_font("Arial", 'B', 14); pdf.set_text_color(200, 0, 0)
                pdf.cell(0, 10, f"RELATÓRIO DE DIVERGÊNCIAS CMED - {estado_destino}", ln=True, align='C')
                pdf.ln(5)

                if df_erros.empty:
                    pdf.set_font("Arial", 'B', 16); pdf.set_text_color(0, 120, 0)
                    pdf.cell(0, 30, "✅ PROPOSTA AUDITADA: 100% DENTRO DOS TETOS LEGAIS.", ln=True, align='C')
                else:
                    pdf.set_font("Arial", 'B', 8); pdf.set_text_color(0); pdf.set_fill_color(240)
                    pdf.cell(10, 8, "Item", 1, 0, 'C', True)
                    pdf.cell(125, 8, "Descrição do Medicamento", 1, 0, 'C', True)
                    pdf.cell(35, 8, "Valor Proposta", 1, 0, 'C', True)
                    pdf.cell(35, 8, "Teto CMED", 1, 0, 'C', True)
                    pdf.cell(35, 8, "Diferença", 1, 1, 'C', True)
                    pdf.set_font("Arial", '', 8)
                    for _, r in df_erros.iterrows():
                        pdf.cell(10, 7, str(r['Item']), 1)
                        pdf.cell(125, 7, str(r[c_desc])[:75], 1)
                        pdf.cell(35, 7, f"R$ {r['V_Unit']:.4f}", 1, 0, 'C')
                        pdf.cell(35, 7, f"R$ {r['Teto_U']:.4f}", 1, 0, 'C')
                        pdf.set_text_color(200, 0, 0)
                        pdf.cell(35, 7, f"R$ {(r['V_Unit'] - r['Teto_U']):.4f}", 1, 1, 'C')
                        pdf.set_text_color(0)

                # Salva o PDF na memória para o botão de download
                pdf_output = "Relatorio_Auditoria.pdf"
                pdf.output(pdf_output)
                
                st.success("✅ Auditoria finalizada com sucesso!")
                
                with open(pdf_output, "rb") as f:
                    st.download_button(
                        label="📄 Baixar PDF Oficial",
                        data=f,
                        file_name="Auditoria_Drogafonte.pdf",
                        mime="application/pdf",
                        type="primary"
                    )

            except Exception as e:
                st.error(f"Ocorreu um erro ao processar. Detalhe: {e}")
