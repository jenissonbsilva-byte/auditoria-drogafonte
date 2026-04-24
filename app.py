import streamlit as st
import pandas as pd
from fpdf import FPDF
import io
import re
import os

# Configuração da página
st.set_page_config(page_title="Auditoria Drogafonte - CMED", layout="wide")

# --- MOTORES LÓGICOS BLINDADOS ---

def limpar_texto_pdf(texto):
    """Higieniza o texto para o FPDF, removendo aspas, quebras de linha e caracteres não suportados."""
    if pd.isna(texto): return ""
    # Remove \n, \r, aspas e espaços duplos
    texto = str(texto).replace('\n', ' ').replace('\r', '').replace('"', '').strip()
    texto = re.sub(r'\s+', ' ', texto)
    # Garante a codificação correta para o PDF
    return texto.encode('latin-1', 'replace').decode('latin-1')

def converter_para_float(valor):
    """Converte valores financeiros em texto (ex: "4,20" ou "1.200,50") para float matemático."""
    v = str(valor).replace('R$', '').replace('"', '').strip()
    if ',' in v and '.' in v:
        v = v.replace('.', '') # Remove separador de milhar se existir
    v = v.replace(',', '.')
    try:
        return float(v)
    except:
        return 0.0

def extrair_qtd_cmed(apres):
    """Motor Regex exato do Colab para fracionar as caixas da CMED"""
    apres = str(apres).upper()
    if "DOS" in apres: return 1
    m = re.search(r'\b(\d+)\s+(?:BL|ENV|STRIP).*?X\s+(\d+)\b(?!\s*(?:ML|MG|G|MCG|UI))', apres)
    if m: return int(m.group(1)) * int(m.group(2))
    m = re.search(r'\b(\d+)\s+(?:AMP|FA|FR|SER|BOLS|CARP|TUB|BOMBA|CANETA|SVD)\b', apres)
    if m: return int(m.group(1))
    m = re.search(r'X\s+(\d+)\b(?!\s*(?:ML|MG|G|MCG|UI|U\.I\.))', apres)
    if m: return int(m.group(1))
    return 1

def ler_proposta_robusto(file_obj):
    """Desmascara arquivos do ERP que dizem ser .xls mas são .csv"""
    file_obj.seek(0)
    try:
        return pd.read_excel(file_obj, header=None)
    except:
        try:
            file_obj.seek(0)
            content = file_obj.read().decode('latin1', errors='ignore')
            # Detecta o separador dinamicamente
            sep = ';' if ';' in content else ','
            return pd.read_csv(io.StringIO(content), sep=sep, header=None, dtype=str)
        except Exception as e:
            raise Exception(f"Formato de arquivo corrompido ou irreconhecível. Erro: {e}")

@st.cache_data
def carregar_cmed():
    if os.path.exists('cmed_atual.xlsx'):
        df_raw = pd.read_excel('cmed_atual.xlsx', header=None, dtype=str)
        linha_cab = 0
        for i, row in df_raw.iterrows():
            if row.astype(str).str.contains('REGISTRO', case=False).any():
                linha_cab = i
                break
        
        df_cmed = pd.read_excel('cmed_atual.xlsx', skiprows=linha_cab, dtype=str)
        df_cmed.columns = df_cmed.columns.astype(str).str.replace(' %', '%').str.strip()
        return df_cmed
    return None

def processar_dados(file_proposta, df_cmed, coluna_icms):
    try:
        df_raw = ler_proposta_robusto(file_proposta)
        
        # Encontra a linha de cabeçalho
        linha_cab = 0
        for i, row in df_raw.iterrows():
            if row.astype(str).str.contains('Reg.M.S|Registro MS', case=False, na=False).any():
                linha_cab = i
                break
                
        # Extrai o cabeçalho (nome da prefeitura, pregão, etc) higienizando a sujeira
        cabecalho_info = []
        for j in range(linha_cab):
            linha_texto = " ".join([str(x) for x in df_raw.iloc[j].dropna() if str(x).strip()])
            linha_limpa = limpar_texto_pdf(linha_texto)
            if linha_limpa:
                cabecalho_info.append(linha_limpa)

        df_prop = df_raw.iloc[linha_cab+1:].copy()
        # Limpa os nomes das colunas (tira \n e aspas)
        df_prop.columns = [limpar_texto_pdf(c) for c in df_raw.iloc[linha_cab]]
        
        # Mapeamento Flexível
        c_desc = [c for c in df_prop.columns if 'D i s c' in c or 'Nome Com' in c or 'Descrição' in c][0]
        c_reg = [c for c in df_prop.columns if 'REG.M.S' in c.upper().replace(' ', '') or 'REGISTRO' in c.upper()][0]
        c_vlr = [c for c in df_prop.columns if 'VLR' in c.upper() and 'UNIT' in c.upper()][0]
        
        try:
            c_item = [c for c in df_prop.columns if 'ITEM' in c.upper()][0]
        except:
            df_prop['Item'] = range(1, len(df_prop) + 1)
            c_item = 'Item'

        c_apres_cmed = [c for c in df_cmed.columns if 'APRESENTA' in str(c).upper()][0]

        # Tratamento de Registros (só números)
        df_prop['Reg_L'] = df_prop[c_reg].astype(str).str.replace(r'[^0-9]', '', regex=True)
        df_cmed['Reg_C'] = df_cmed['REGISTRO'].astype(str).str.replace(r'[^0-9]', '', regex=True)
        
        # Conversão Matemática Blindada
        df_prop['V_Unit'] = df_prop[c_vlr].apply(converter_para_float)

        df_m = pd.merge(df_prop, df_cmed[['Reg_C', coluna_icms, c_apres_cmed]], left_on='Reg_L', right_on='Reg_C', how='left')
        
        df_m['PF_Num'] = df_m[coluna_icms].apply(converter_para_float)
        df_m['Qtd_C'] = df_m[c_apres_cmed].apply(extrair_qtd_cmed)
        df_m['Teto_U'] = df_m['PF_Num'] / df_m['Qtd_C']
        
        # Filtra quem estourou a CMED (Tolerância de 4 casas decimais)
        df_erros = df_m[round(df_m['V_Unit'], 4) > round(df_m['Teto_U'], 4)].copy()

        df_erros['Item_View'] = df_erros[c_item].apply(limpar_texto_pdf)
        df_erros['Desc_View'] = df_erros[c_desc].apply(limpar_texto_pdf)

        return df_erros, cabecalho_info, None

    except Exception as e:
        return None, None, f"Erro Crítico: {str(e)}"

# --- INTERFACE ---
st.title("🛡️ Auditoria Drogafonte - Validador CMED")
st.markdown("---")

df_cmed = carregar_cmed()

with st.sidebar:
    st.image("https://drogafonte.com.br/wp-content/uploads/2021/10/logo-drogafonte.png", width=200)
    st.header("Configurações")
    
    opcoes_icms = [
        "PF 12%", "PF 17%", "PF 17,5%", "PF 18%", "PF 19%", 
        "PF 19,5%", "PF 20%", "PF 20,5%", "PF 21%", "PF 22%"
    ]
    escolha_icms = st.selectbox("Selecione a Alíquota ICMS:", opcoes_icms, index=7)

    st.markdown("---")
    if df_cmed is not None:
        st.success("✅ Base CMED Ativa")
    else:
        st.error("❌ 'cmed_atual.xlsx' ausente.")

if df_cmed is not None:
    upload_prop = st.file_uploader("Arraste a Proposta (Excel/XLS) aqui", type=['xls', 'xlsx', 'csv'])

    if upload_prop:
        with st.spinner("Analisando proposta e higienizando dados..."):
            dados_finais, cabecalho_pdf, erro = processar_dados(upload_prop, df_cmed, escolha_icms)
            
            if erro:
                st.error(erro)
            elif dados_finais.empty:
                st.success("✅ PROPOSTA AUDITADA: 100% DENTRO DOS TETOS LEGAIS.")
            else:
                st.warning(f"🚨 {len(dados_finais)} itens acima do teto!")
                
                exibicao = dados_finais[['Item_View', 'Desc_View', 'V_Unit', 'Teto_U']].copy()
                exibicao.columns = ['Item', 'Descrição', 'Valor Proposta', 'Teto CMED']
                st.dataframe(exibicao.style.format({'Valor Proposta': 'R$ {:.4f}', 'Teto CMED': 'R$ {:.4f}'}))

                # --- GERAÇÃO DO PDF LIMPO ---
                if st.button("📥 Baixar Relatório Profissional"):
                    pdf = FPDF(orientation='L', unit='mm', format='A4')
                    pdf.add_page()
                    
                    pdf.set_font("Arial", 'B', 10)
                    for linha in cabecalho_pdf[:5]:
                        pdf.cell(0, 5, linha, ln=True)
                    
                    pdf.ln(5); pdf.set_draw_color(180)
                    pdf.line(10, pdf.get_y(), 287, pdf.get_y()); pdf.ln(5)
                    
                    pdf.set_font("Arial", 'B', 14); pdf.set_text_color(200, 0, 0)
                    pdf.cell(0, 10, f"RELATÓRIO DE DIVERGÊNCIAS CMED - DESTINO: {escolha_icms}", ln=True, align='C')
                    pdf.ln(5)

                    pdf.set_font("Arial", 'B', 8); pdf.set_text_color(0); pdf.set_fill_color(240, 240, 240)
                    pdf.cell(15, 8, "Item", 1, 0, 'C', True)
                    pdf.cell(140, 8, "Descrição do Medicamento", 1, 0, 'C', True)
                    pdf.cell(30, 8, "Proposta", 1, 0, 'C', True)
                    pdf.cell(30, 8, "Teto CMED", 1, 0, 'C', True)
                    pdf.cell(30, 8, "Diferença", 1, 1, 'C', True)
                    
                    pdf.set_font("Arial", '', 8)
                    for _, r in dados_finais.iterrows():
                        pdf.cell(15, 7, str(r['Item_View']).split('.')[0], 1, 0, 'C')
                        pdf.cell(140, 7, str(r['Desc_View'])[:85], 1)
                        
                        pdf.cell(30, 7, f"R$ {r['V_Unit']:.4f}", 1, 0, 'C')
                        pdf.cell(30, 7, f"R$ {r['Teto_U']:.4f}", 1, 0, 'C')
                        
                        diferenca = r['V_Unit'] - r['Teto_U']
                        pdf.set_text_color(200, 0, 0)
                        pdf.cell(30, 7, f"R$ {diferenca:.4f}", 1, 1, 'C')
                        pdf.set_text_color(0)

                    pdf_output = pdf.output(dest='S').encode('latin-1')
                    st.download_button(
                        "Salvar Relatório PDF", 
                        data=pdf_output, 
                        file_name="Relatorio_Auditoria.pdf", 
                        mime="application/pdf"
                    )
