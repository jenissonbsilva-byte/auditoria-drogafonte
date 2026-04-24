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
        # Blindagem: Força tudo a virar texto (str) antes de aplicar maiúsculo
        row_str = [str(val).upper().strip() for val in row.tolist()]
        if any(str(col).upper() in row_str for col in colunas_alvo):
            return i
    return None

def limpar_nome_coluna(col):
    """Padroniza os nomes das colunas da CMED para evitar erros de espaços da Anvisa"""
    nome = str(col).upper().strip()
    nome = re.sub(r'\s+', ' ', nome)
    nome = nome.replace(" %", "%")
    return nome

# NOVA FUNÇÃO: Trazida do Colab - Extração agressiva de quantidades
def extrair_qtd_cmed(apres):
    apres = str(apres).upper()
    if "DOS" in apres: return 1
    # Escudo para não fracionar Soro, Injetáveis e Cremes (ML, MG, G)
    m = re.search(r'\b(\d+)\s+(?:BL|ENV|STRIP).*?X\s+(\d+)\b(?!\s*(?:ML|MG|G|MCG|UI))', apres)
    if m: return int(m.group(1)) * int(m.group(2))
    m = re.search(r'\b(\d+)\s+(?:AMP|FA|FR|SER|BOLS|CARP|TUB|BOMBA|CANETA|SVD)\b', apres)
    if m: return int(m.group(1))
    m = re.search(r'X\s+(\d+)\b(?!\s*(?:ML|MG|G|MCG|UI|U\.I\.))', apres)
    if m: return int(m.group(1))
    return 1

# NOVA FUNÇÃO: Leitor robusto para lidar com falsos .xls gerados por ERPs
def ler_proposta_robusto(file_obj):
    try:
        df = pd.read_excel(file_obj, header=None)
        return df
    except:
        try:
            file_obj.seek(0) # Retorna o ponteiro do arquivo para o início
            content = file_obj.read().decode('latin1')
            df = pd.read_csv(io.StringIO(content), sep=None, engine='python', header=None)
            return df
        except Exception as e:
            raise Exception(f"Não foi possível ler o arquivo da proposta. Verifique se o formato é válido. Erro: {e}")

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
            
        df.columns = [limpar_nome_coluna(c) for c in df.columns]
            
        colunas_cmed = {
            'REGISTRO': ['REGISTRO', 'Nº REGISTRO', 'REGISTRO MS', 'NO REGISTRO'],
            'APRESENTAÇÃO': ['APRESENTAÇÃO', 'APRESENTACAO', 'DESCRICAO_CMED']
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
        # Usa o leitor robusto que não quebra com falsos XLS
        df_raw = ler_proposta_robusto(file_proposta)
        idx_cabecalho = buscar_cabecalho(df_raw, ['Reg.M.S', 'Registro MS', 'REG. MS', 'Registro'])
        
        if idx_cabecalho is None:
            return None, "Cabeçalho 'Reg.M.S' não identificado na proposta."

        # Fatiamento do DataFrame sem precisar ler o arquivo de novo
        df_prop = df_raw.iloc[idx_cabecalho+1:].copy()
        df_prop.columns = df_raw.iloc[idx_cabecalho].astype(str).str.strip()
        
        # Inclusão das variações de descrição vistas no Colab ('Nome Comercial', 'D i s c r i m i n a ç ã o')
        colunas_prop = {
            'Reg.M.S': ['Reg.M.S', 'REG. MS', 'Registro MS', 'Registro'],
            'Vlr. Unit.': ['Vlr. Unit.', 'Valor Unitário', 'Preço Unit.', 'Unitário', 'Vlr.Unit'],
            'Descrição': ['Descrição', 'PRODUTO', 'Item', 'NOME DO PRODUTO', 'Descricao', 'Nome Comercial', 'D i s c r i m i n a ç ã o']
        }
        
        # Mapeamento e renomeação
        for oficial, variantes in colunas_prop.items():
            for v in variantes:
                # Busca flexível por parte do nome (como no Colab)
                match = [c for c in df_prop.columns if v.upper().replace(' ', '') in str(c).upper().replace(' ', '')]
                if match:
                    df_prop.rename(columns={match[0]: oficial}, inplace=True)
                    break

        if 'Reg.M.S' not in df_prop.columns or 'Vlr. Unit.' not in df_prop.columns:
            return None, f"Colunas essenciais da proposta não identificadas."
        
        if 'REGISTRO' not in df_cmed.columns:
            return None, "Coluna de Registro não encontrada na CMED."

        if coluna_icms not in df_cmed.columns:
            cols_pf = [c for c in df_cmed.columns if 'PF' in c]
            return None, f"A coluna '{coluna_icms}' não foi encontrada na CMED. Colunas lidas: {cols_pf}"

        df_prop['REG_LIMPO'] = df_prop['Reg.M.S'].apply(limpar_registro)
        df_cmed_copy = df_cmed.copy()
        df_cmed_copy['REG_LIMPO'] = df_cmed_copy['REGISTRO'].apply(limpar_registro)
        
        resultado = pd.merge(df_prop, df_cmed_copy, on='REG_LIMPO', how='inner')
        
        # Aplicação da matemática correta (igual ao Colab)
        def calcular_teto(row):
            qtd = extrair_qtd_cmed(row['APRESENTAÇÃO'])
            pf = str(row[coluna_icms]).replace(',', '.') if isinstance(row[coluna_icms], str) else row[coluna_icms]
            return float(pf) / qtd

        resultado['Teto_Unitario'] = resultado.apply(calcular_teto, axis=1)
        
        resultado['Vlr. Unit.'] = resultado['Vlr. Unit.'].apply(
            lambda x: float(str(x).replace(',', '.')) if isinstance(x, str) else x
        )
        
        # Removida a tolerância de erro de arredondamento para ficar rigorosamente igual ao Colab
        acima = resultado[resultado['Vlr. Unit.'] > resultado['Teto_Unitario']].copy()
        
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
