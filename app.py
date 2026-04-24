import streamlit as st
import pandas as pd
from fpdf import FPDF
import io
import re
import os

# Configuração da página
st.set_page_config(page_title="Auditoria Drogafonte - CMED", layout="wide")

# Cache para carregar a CMED apenas uma vez (deixa o app muito mais rápido)
@st.cache_data
def carregar_cmed():
    # Verifica se o arquivo existe na base
    if os.path.exists('cmed_atual.xlsx'):
        return pd.read_excel('cmed_atual.xlsx')
    else:
        return None

def limpar_registro(reg):
    """Limpa o Registro MS para garantir o cruzamento correto"""
    return re.sub(r'\D', '', str(reg))

def buscar_cabecalho(df, colunas_alvo):
    """Busca dinamicamente em qual linha está o cabeçalho"""
    for i, row in df.iterrows():
        row_str = row.astype(str).tolist()
        if any(col in row_str for col in colunas_alvo):
            return i
    return None

def processar_dados(file_proposta, df_cmed):
    try:
        # 1. Leitura Inicial sem cabeçalho definido para localizar os dados
        df_raw = pd.read_excel(file_proposta, header=None)
        
        # Procura a linha onde está o 'Reg.M.S'
        idx_cabecalho = buscar_cabecalho(df_raw, ['Reg.M.S', 'Registro MS', 'REG. MS'])
        
        if idx_cabecalho is None:
            return None, "Cabeçalho 'Reg.M.S' não identificado na proposta."

        # Re-lê o arquivo a partir da linha correta
        df_prop = pd.read_excel(file_proposta, skiprows=idx_cabecalho)
        
        # Padronização de colunas necessárias
        colunas_prop = {
            'Reg.M.S': ['Reg.M.S', 'REG. MS', 'Registro MS'],
            'Vlr. Unit.': ['Vlr. Unit.', 'Valor Unitário', 'Preço Unit.', 'Unitário'],
            'Descrição': ['Descrição', 'PRODUTO', 'Item', 'NOME DO PRODUTO']
        }
        
        for oficial, variantes in colunas_prop.items():
            for v in variantes:
                if v in df_prop.columns:
                    df_prop.rename(columns={v: oficial}, inplace=True)
                    break

        if 'Reg.M.S' not in df_prop.columns or 'Vlr. Unit.' not in df_prop.columns:
            return None, "Colunas essenciais (Reg.M.S ou Vlr. Unit.) não encontradas."

        # Limpeza e Cruzamento
        df_prop['REG_LIMPO'] = df_prop['Reg.M.S'].apply(limpar_registro)
        df_cmed['REG_LIMPO'] = df_cmed['REGISTRO'].apply(limpar_registro)
        
        # Merge
        resultado = pd.merge(df_prop, df_cmed, left_on='REG_LIMPO', right_on='REG_LIMPO', how='inner')
        
        # Lógica de Unidade vs Caixa (Apresentação)
        def calcular_teto(row):
            if "DOS" in str(row['APRESENTAÇÃO']).upper():
                qtd = 1
            else:
                match = re.search(r'(\d+)\s*(?:COMP|CAP|DRG|ENV|FR|AMP|SER|TAB)', str(row['APRESENTAÇÃO']).upper())
                qtd = int(match.group(1)) if match else 1
            return row['PF 20,5%'] / qtd

        resultado['Teto_Unitario'] = resultado.apply(calcular_teto, axis=1)
        
        # Filtrar apenas acima do preço
        acima = resultado[resultado['Vlr. Unit.'] > resultado['Teto_Unitario']].copy()
        
        return acima, None

    except Exception as e:
        return None, f"Erro Crítico: {str(e)}"

# Interface Streamlit
st.title("🛡️ Auditoria Drogafonte - Validador CMED")
st.markdown("---")

# Carrega a base CMED fixa
df_cmed = carregar_cmed()

with st.sidebar:
    st.image("https://drogafonte.com.br/wp-content/uploads/2021/10/logo-drogafonte.png", width=200)
    st.header("Informações do Sistema")
    if df_cmed is not None:
        st.success("✅ Base CMED carregada com sucesso!")
    else:
        st.error("❌ Arquivo 'cmed_atual.xlsx' não encontrado na base.")
    st.markdown("Faça o upload da proposta ao lado para iniciar a auditoria.")

# Área Principal
if df_cmed is not None:
    upload_prop = st.file_uploader("Selecione a Proposta para Analisar", type=['xls', 'xlsx'])

    if upload_prop:
        with st.spinner("Processando..."):
            dados_finais, erro = processar_dados(upload_prop, df_cmed)
            
            if erro:
                st.error(erro)
            elif dados_finais.empty:
                st.success("✅ Nenhum item acima da CMED encontrado!")
            else:
                st.warning(f"⚠️ Encontrados {len(dados_finais)} itens acima do valor permitido.")
                st.dataframe(dados_finais[['Descrição', 'Reg.M.S', 'Vlr. Unit.', 'Teto_Unitario']])

                # Gerar PDF
                if st.button("Gerar Relatório PDF"):
                    pdf = FPDF()
                    pdf.add_page()
                    
                    pdf.set_font("Arial", 'B', 16)
                    pdf.cell(190, 10, "RELATORIO DE AUDITORIA - DROGAFONTE", 0, 1, 'C')
                    pdf.set_font("Arial", '', 10)
                    pdf.cell(190, 10, f"Proposta: {upload_prop.name}", 0, 1, 'C')
                    pdf.ln(10)
                    
                    pdf.set_font("Arial", 'B', 8)
                    pdf.set_fill_color(200, 200, 200)
                    pdf.cell(80, 8, "Descricao", 1, 0, 'C', True)
                    pdf.cell(30, 8, "Vlr. Prop.", 1, 0, 'C', True)
                    pdf.cell(30, 8, "Teto CMED", 1, 0, 'C', True)
                    pdf.cell(30, 8, "Diferenca", 1, 1, 'C', True)
                    
                    pdf.set_font("Arial", '', 7)
                    for _, r in dados_finais.iterrows():
                        # Removendo acentos e caracteres especiais para evitar erros no FPDF
                        desc = str(r['Descrição'])[:45].encode('latin-1', 'replace').decode('latin-1')
                        
                        pdf.cell(80, 7, desc, 1)
                        pdf.cell(30, 7, f"R$ {r['Vlr. Unit.']:.4f}", 1, 0, 'C')
                        pdf.cell(30, 7, f"R$ {r['Teto_Unitario']:.4f}", 1, 0, 'C')
                        diff = r['Vlr. Unit.'] - r['Teto_Unitario']
                        pdf.cell(30, 7, f"R$ {diff:.4f}", 1, 1, 'C')

                    pdf_output = pdf.output(dest='S').encode('latin-1')
                    st.download_button("Baixar PDF", data=pdf_output, file_name="relatorio_auditoria.pdf", mime="application/pdf")
