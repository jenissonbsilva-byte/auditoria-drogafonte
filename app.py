import streamlit as st
import pandas as pd
from fpdf import FPDF
import io
import re
import os

# Configuração da página
st.set_page_config(page_title="Auditoria Drogafonte - CMED", layout="wide")

# --- MOTOR DE INTELIGÊNCIA DO COLAB IMPORTADO ---

def extrair_qtd_cmed(apres):
    """Expressões Regulares do Colab para não errar a quantidade da caixa da CMED"""
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

def ler_proposta_robusto(file_obj):
    """Leitura à prova de falhas para arquivos gerados por ERPs"""
    try:
        df = pd.read_excel(file_obj, header=None)
        return df
    except:
        try:
            file_obj.seek(0)
            content = file_obj.read().decode('latin1')
            df = pd.read_csv(io.StringIO(content), sep=None, engine='python', header=None)
            return df
        except Exception as e:
            raise Exception(f"Formato de arquivo inválido ou corrompido. Erro: {e}")

@st.cache_data
def carregar_cmed():
    """Carregamento inteligente da CMED adaptado do Colab"""
    if os.path.exists('cmed_atual.xlsx'):
        df_raw = pd.read_excel('cmed_atual.xlsx', header=None)
        
        linha_cab = 0
        for i, row in df_raw.iterrows():
            if row.astype(str).str.contains('REGISTRO', case=False).any():
                linha_cab = i
                break
                
        df_cmed = pd.read_excel('cmed_atual.xlsx', skiprows=linha_cab)
        # Padroniza as colunas de porcentagem ("PF 20,5 %" -> "PF 20,5%") para não haver erros de busca
        df_cmed.columns = df_cmed.columns.astype(str).str.replace(' %', '%').str.strip()
        return df_cmed
    return None

def processar_dados(file_proposta, df_cmed, coluna_icms):
    try:
        # 1. Leitura
        df_raw = ler_proposta_robusto(file_proposta)
        
        # 2. Busca do Cabeçalho e Extração de Metadados (Igual ao Colab para o PDF)
        linha_cab = 0
        for i, row in df_raw.iterrows():
            if row.astype(str).str.contains('Reg.M.S|Vlr. Unit.', case=False).any():
                linha_cab = i
                break
                
        cabecalho_info = [
            " ".join(df_raw.iloc[j].dropna().astype(str).tolist()) 
            for j in range(linha_cab) if str(df_raw.iloc[j].dropna()).strip()
        ]

        # 3. Reconstrói a Proposta com as colunas corretas
        df_prop = df_raw.iloc[linha_cab+1:].copy()
        df_prop.columns = df_raw.iloc[linha_cab].astype(str).str.strip()
        
        # 4. Mapeamento Dinâmico de Colunas
        c_desc = [c for c in df_prop.columns if 'D i s c' in str(c) or 'Nome Com' in str(c) or 'Descrição' in str(c) or 'PRODUTO' in str(c).upper()][0]
        c_reg = [c for c in df_prop.columns if 'REG.M.S' in str(c).upper().replace(' ', '') or 'REGISTRO' in str(c).upper()][0]
        c_vlr = [c for c in df_prop.columns if 'VLR' in str(c).upper() and 'UNIT' in str(c).upper()][0]
        
        try:
            c_item = [c for c in df_prop.columns if 'ITEM' in str(c).upper()][0]
        except IndexError:
            df_prop['Item'] = range(1, len(df_prop) + 1)
            c_item = 'Item'

        c_apres_cmed = [c for c in df_cmed.columns if 'APRESENTA' in str(c).upper()][0]

        # 5. Cruzamento de Dados e Auditoria Matemática
        df_prop['Reg_L'] = df_prop[c_reg].astype(str).str.replace(r'[^0-9]', '', regex=True)
        df_cmed['Reg_C'] = df_cmed['REGISTRO'].astype(str).str.replace(r'[^0-9]', '', regex=True)
        df_prop['V_Unit'] = df_prop[c_vlr].astype(str).str.replace(',', '.').astype(float)

        # Merge Left garante que os dados da proposta não se percam na leitura
        df_m = pd.merge(df_prop, df_cmed[['Reg_C', coluna_icms, c_apres_cmed]], left_on='Reg_L', right_on='Reg_C', how='left')
        
        df_m['PF_Num'] = df_m[coluna_icms].astype(str).str.replace(',', '.').astype(float)
        df_m['Qtd_C'] = df_m[c_apres_cmed].apply(extrair_qtd_cmed)
        df_m['Teto_U'] = df_m['PF_Num'] / df_m['Qtd_C']
        
        # Filtra apenas quem ultrapassou o teto
        df_erros = df_m[df_m['V_Unit'] > df_m['Teto_U']].copy()

        # Passa os metadados visuais para a geração da tabela e do PDF
        df_erros['Item_View'] = df_erros[c_item]
        df_erros['Desc_View'] = df_erros[c_desc]

        return df_erros, cabecalho_info, None

    except Exception as e:
        return None, None, f"Erro Crítico: {str(e)}"

# --- INTERFACE VISUAL ---
st.title("🛡️ Auditoria Drogafonte - Validador CMED")
st.markdown("---")

df_cmed = carregar_cmed()

with st.sidebar:
    if os.path.exists('logo_drogafonte.png'):
        st.image('logo_drogafonte.png', width=200)
    else:
        st.image("https://drogafonte.com.br/wp-content/uploads/2021/10/logo-drogafonte.png", width=200)
    
    st.header("Configurações")
    
    opcoes_icms = [
        "PF 12%", "PF 17%", "PF 17,5%", "PF 18%", "PF 19%", 
        "PF 19,5%", "PF 20%", "PF 20,5%", "PF 21%", "PF 22%"
    ]
    
    escolha_icms = st.selectbox("Selecione a Alíquota ICMS (Destino):", opcoes_icms, index=7) # 7 = PF 20,5%

    st.markdown("---")
    if df_cmed is not None:
        st.success("✅ Base CMED Ativa")
    else:
        st.error("❌ Arquivo 'cmed_atual.xlsx' não encontrado na nuvem.")

if df_cmed is not None:
    upload_prop = st.file_uploader("Arraste a Proposta (Excel) aqui", type=['xls', 'xlsx'])

    if upload_prop:
        with st.spinner(f"Processando com motor lógico Colab ({escolha_icms})..."):
            dados_finais, cabecalho_pdf, erro = processar_dados(upload_prop, df_cmed, escolha_icms)
            
            if erro:
                st.error(erro)
            elif dados_finais.empty:
                st.success(f"✅ PROPOSTA AUDITADA: 100% DENTRO DOS TETOS LEGAIS PARA {escolha_icms}.")
            else:
                st.warning(f"🚨 {len(dados_finais)} itens ultrapassaram o teto legal!")
                
                # Exibição na tela do Streamlit
                exibicao = dados_finais[['Item_View', 'Desc_View', 'V_Unit', 'Teto_U']].copy()
                exibicao.columns = ['Item', 'Descrição do Medicamento', 'Valor Proposta', 'Teto CMED']
                st.dataframe(exibicao.style.format({'Valor Proposta': 'R$ {:.4f}', 'Teto CMED': 'R$ {:.4f}'}))

                # --- GERAÇÃO EXATA DO PDF (IGUAL AO MODELO ENVIADO) ---
                if st.button("📥 Baixar Relatório Profissional (PDF)"):
                    # Formato Paisagem (L) igual ao Colab para caber a descrição
                    pdf = FPDF(orientation='L', unit='mm', format='A4')
                    pdf.add_page()
                    
                    # 1. Cabeçalho Dinâmico da Drogafonte/Licitação
                    pdf.set_font("Arial", 'B', 10)
                    for linha in cabecalho_pdf[:5]:
                        # Limpa caracteres estranhos para evitar erros no FPDF
                        texto_limpo = str(linha).encode('latin-1', 'replace').decode('latin-1')
                        pdf.cell(0, 5, texto_limpo, ln=True)
                    
                    # Linha divisória cinza
                    pdf.ln(5)
                    pdf.set_draw_color(180)
                    pdf.line(10, pdf.get_y(), 287, pdf.get_y())
                    pdf.ln(5)
                    
                    # 2. Título Centralizado em Vermelho
                    pdf.set_font("Arial", 'B', 14)
                    pdf.set_text_color(200, 0, 0)
                    pdf.cell(0, 10, f"RELATÓRIO DE DIVERGÊNCIAS CMED - DESTINO: {escolha_icms}", ln=True, align='C')
                    pdf.ln(5)

                    # 3. Cabeçalho da Tabela
                    pdf.set_font("Arial", 'B', 8)
                    pdf.set_text_color(0) # Retorna texto para preto
                    pdf.set_fill_color(240, 240, 240) # Fundo Cinza Claro
                    
                    # Larguras exatas do Colab
                    pdf.cell(10, 8, "Item", 1, 0, 'C', True)
                    pdf.cell(125, 8, "Descrição do Medicamento", 1, 0, 'C', True)
                    pdf.cell(35, 8, "Valor Proposta", 1, 0, 'C', True)
                    pdf.cell(35, 8, "Teto CMED", 1, 0, 'C', True)
                    pdf.cell(35, 8, "Diferença", 1, 1, 'C', True)
                    
                    # 4. Dados da Tabela
                    pdf.set_font("Arial", '', 8)
                    for _, r in dados_finais.iterrows():
                        # Item
                        item_str = str(r['Item_View']).split('.')[0] if '.' in str(r['Item_View']) else str(r['Item_View'])
                        pdf.cell(10, 7, item_str, 1, 0, 'C')
                        
                        # Descrição Limitada e Padronizada
                        desc = str(r['Desc_View'])[:75].encode('latin-1', 'replace').decode('latin-1')
                        pdf.cell(125, 7, desc, 1)
                        
                        # Preços
                        pdf.cell(35, 7, f"R$ {r['V_Unit']:.4f}", 1, 0, 'C')
                        pdf.cell(35, 7, f"R$ {r['Teto_U']:.4f}", 1, 0, 'C')
                        
                        # Diferença em Vermelho (matemática igual ao Colab)
                        diferenca = r['V_Unit'] - r['Teto_U']
                        pdf.set_text_color(200, 0, 0) # Fica Vermelho
                        pdf.cell(35, 7, f"R$ {diferenca:.4f}", 1, 1, 'C')
                        pdf.set_text_color(0) # Volta pro preto para a próxima linha

                    # Baixar Arquivo
                    pdf_output = pdf.output(dest='S').encode('latin-1')
                    st.download_button(
                        "Clique aqui para salvar o Relatório PDF", 
                        data=pdf_output, 
                        file_name="Relatorio_Auditoria_Drogafonte.pdf", 
                        mime="application/pdf"
                    )
