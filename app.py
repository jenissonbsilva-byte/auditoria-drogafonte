import streamlit as st
import pandas as pd
from fpdf import FPDF
import io
import re
import os

# Configuração da página
st.set_page_config(page_title="Auditoria Drogafonte - CMED", layout="wide")

def limpar_registro(reg):
    return re.sub(r'\D', '', str(reg))

def buscar_cabecalho(df, colunas_alvo):
    for i, row in df.iterrows():
        # Blindagem: Força tudo a virar texto (str) antes de aplicar maiúsculo (.upper())
        row_str = [str(val).upper().strip() for val in row.tolist()]
        if any(str(col).upper() in row_str for col in colunas_alvo):
            return i
    return None

# Cache para carregar a CMED apenas uma vez
@st.cache_data
def carregar_cmed():
    if os.path.exists('cmed_atual.xlsx'):
        df_raw = pd.read_excel('cmed_atual.xlsx', header=None)
        idx_cabecalho = buscar_cabecalho(df_raw, ['REGISTRO', 'CÓDIGO GGREM', 'SUBSTÂNCIA'])
        
        if idx_cabecalho is not None:
            df = pd.read_excel('cmed_atual.xlsx', skiprows=idx_cabecalho)
        else:
            df = pd.read_excel('cmed_atual.xlsx')
            
        # Limpa os espaços em branco de todas as colunas para facilitar a busca
        df.columns = [str(c).strip() for c in df.columns]
            
        # Padronização de Colunas Base
        colunas_cmed = {
            'REGISTRO': ['REGISTRO', 'Registro', 'Nº REGISTRO', 'REGISTRO MS', 'No REGISTRO'],
            'APRESENTAÇÃO': ['APRESENTAÇÃO', 'Apresentação', 'APRESENTACAO', 'DESCRICAO_CMED']
        }
        
        for oficial, variantes in colunas_cmed.items():
            for v in variantes:
                if v in df.columns:
                    idx = list(df.columns).index(v)
                    df.rename(columns={df.columns[idx]: oficial}, inplace=True)
                    break
        return df
    else:
        return None

def processar_dados(file_proposta, df_cmed, coluna_icms):
    try:
        df_raw = pd.read_excel(file_proposta, header=None)
        idx_cabecalho = buscar_cabecalho(df_raw, ['Reg.M.S', 'Registro MS', 'REG. MS', 'Registro'])
        
        if idx_cabecalho is None:
            return None, "Cabeçalho 'Reg.M.S' não identificado na proposta."

        df_prop = pd.read_excel(file_proposta, skiprows=idx_cabecalho)
        
        colunas_prop = {
            'Reg.M.S': ['Reg.M.S', 'REG. MS', 'Registro MS', 'Registro'],
            'Vlr. Unit.': ['Vlr. Unit.', 'Valor Unitário', 'Preço Unit.', 'Unitário', 'Vlr.Unit'],
            'Descrição': ['Descrição', 'PRODUTO', 'Item', 'NOME DO PRODUTO', 'Descricao']
        }
        
        for oficial, variantes in colunas_prop.items():
            for v in variantes:
                if v in df_prop.columns:
                    df_prop.rename(columns={v: oficial}, inplace=True)
                    break

        if 'Reg.M.S' not in df_prop.columns or 'Vlr. Unit.' not in df_prop.columns:
            return None, f"Colunas essenciais da proposta não identificadas."
        
        if 'REGISTRO' not in df_cmed.columns:
            return None, "Coluna de Registro não encontrada na CMED."

        # Verifica se a coluna de ICMS escolhida existe na CMED
        if coluna_icms not in df_cmed.columns:
            return None, f"A coluna '{coluna_icms}' não foi encontrada na tabela CMED."

        df_prop['REG_LIMPO'] = df_prop['Reg.M.S'].apply(limpar_registro)
        df_cmed_copy = df_cmed.copy()
        df_cmed_copy['REG_LIMPO'] = df_cmed_copy['REGISTRO'].apply(limpar_registro)
        
        resultado = pd.merge(df_prop, df_cmed_copy, on='REG_LIMPO', how='inner')
        
        def calcular_teto(row):
            apres = str(row['APRESENTAÇÃO']).upper()
            if "DOS" in apres:
                qtd = 1
            else:
                match = re.search(r'(\d+)\s*(?:COMP|CAP|DRG|ENV|FR|AMP|SER|TAB|UNID|UN)', apres)
                qtd = int(match.group(1)) if match else 1
                
            pf = str(row[coluna_icms]).replace(',', '.') if isinstance(row[coluna_icms], str) else row[coluna_icms]
            return float(pf) / qtd

        resultado['Teto_Unitario'] = resultado.apply(calcular_teto, axis=1)
        
        resultado['Vlr. Unit.'] = resultado['Vlr. Unit.'].apply(
            lambda x: float(str(x).replace(',', '.')) if isinstance(x, str) else x
        )
        
        acima = resultado[resultado['Vlr. Unit.'] > (resultado['Teto_Unitario'] + 0.0001)].copy()
        
        return acima, None

    except Exception as e:
        return None, f"Erro no Processamento: {str(e)}"

# --- INTERFACE ---
st.title("🛡️ Auditoria Drogafonte - Validador CMED")
st.markdown("---")

df_cmed = carregar_cmed()

with st.sidebar:
    if os.path.exists('logo_drogafonte.png'):
        st.image('logo_drogafonte.png', width=200)
    else:
        st.image("https://drogafonte.com.br/wp-content/uploads/2021/10/logo-drogafonte.png", width=200)
    
    st.header("Configurações")
    
    opcoes_icms = {
        "PF 12%": "PF 12%",
        "PF 17%": "PF 17%",
        "PF 17,5%": "PF 17,5%",
        "PF 18%": "PF 18%",
        "PF 19%": "PF 19%",
        "PF 19,5%": "PF 19,5%",
        "PF 20%": "PF 20%",
        "PF 20,5% (Pernambuco)": "PF 20,5%",
        "PF 21%": "PF 21%",
        "PF 22%": "PF 22%"
    }
    
    escolha_icms = st.selectbox("Selecione a Alíquota ICMS (Destino):", list(opcoes_icms.keys()), index=7)
    coluna_icms_real = opcoes_icms[escolha_icms]

    st.markdown("---")
    st.header("Status do Sistema")
    if df_cmed is not None:
        st.success("✅ Base CMED Ativa")
    else:
        st.error("❌ Arquivo 'cmed_atual.xlsx' não encontrado.")

if df_cmed is not None:
    upload_prop = st.file_uploader("Arraste a Proposta (Excel) aqui", type=['xls', 'xlsx'])

    if upload_prop:
        with st.spinner(f"Analisando proposta com base no {escolha_icms}..."):
            dados_finais, erro = processar_dados(upload_prop, df_cmed, coluna_icms_real)
            
            if erro:
                st.error(erro)
            elif dados_finais.empty:
                st.success(f"✅ Tudo certo! Nenhum item acima da CMED para a alíquota {escolha_icms}.")
            else:
                st.warning(f"🚨 {len(dados_finais)} itens com valor acima do teto ({escolha_icms})!")
                
                exibicao = dados_finais[['Descrição', 'Reg.M.S', 'Vlr. Unit.', 'Teto_Unitario']].copy()
                exibicao.columns = ['Item', 'Registro MS', 'Preço Proposta', f'Teto CMED ({escolha_icms})']
                
                st.dataframe(exibicao.style.format({
                    'Preço Proposta': 'R$ {:.4f}', 
                    f'Teto CMED ({escolha_icms})': 'R$ {:.4f}'
                }))

                if st.button("📥 Baixar Relatório em PDF"):
                    pdf = FPDF()
                    pdf.add_page()
                    pdf.set_font("Arial", 'B', 14)
                    pdf.cell(190, 10, "DROGAFONTE - RELATORIO DE AUDITORIA CMED", 0, 1, 'C')
                    pdf.set_font("Arial", '', 9)
                    pdf.cell(190, 7, f"Arquivo: {upload_prop.name} | Aliquota: {escolha_icms}", 0, 1, 'C')
                    pdf.ln(5)
                    
                    pdf.set_font("Arial", 'B', 8)
                    pdf.set_fill_color(230, 230, 230)
                    pdf.cell(90, 8, "Item/Descricao", 1, 0, 'L', True)
                    pdf.cell(33, 8, "Vlr. Proposta", 1, 0, 'C', True)
                    pdf.cell(33, 8, "Teto CMED", 1, 0, 'C', True)
                    pdf.cell(34, 8, "Diferenca", 1, 1, 'C', True)
                    
                    pdf.set_font("Arial", '', 7)
                    for _, r in dados_finais.iterrows():
                        desc = str(r['Descrição'])[:55].encode('latin-1', 'replace').decode('latin-1')
                        pdf.cell(90, 7, desc, 1)
                        pdf.cell(33, 7, f"R$ {r['Vlr. Unit.']:.4f}", 1, 0, 'C')
                        pdf.cell(33, 7, f"R$ {r['Teto_Unitario']:.4f}", 1, 0, 'C')
                        diff = r['Vlr. Unit.'] - r['Teto_Unitario']
                        pdf.cell(34, 7, f"R$ {diff:.4f}", 1, 1, 'C')

                    pdf_output = pdf.output(dest='S').encode('latin-1')
                    st.download_button("Clique aqui para salvar o PDF", data=pdf_output, file_name="auditoria_cmed.pdf", mime="application/pdf")
