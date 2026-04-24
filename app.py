import streamlit as st
import pandas as pd
from fpdf import FPDF
import io
import re
import os

# Configuração da página
st.set_page_config(page_title="Auditoria Drogafonte - CMED", layout="wide")

# --- CONTROLE DE ESTADO (Para limpar a tela como você pediu) ---
if 'tela_resultado' not in st.session_state:
    st.session_state.tela_resultado = False

def resetar_app():
    st.session_state.tela_resultado = False
    for key in ['dados_finais', 'cabecalho_pdf', 'erro', 'nome_arquivo']:
        if key in st.session_state:
            del st.session_state[key]

# --- MOTORES LÓGICOS (Clone Exato do seu Colab) ---
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

def ler_proposta_robusto(file_obj):
    file_obj.seek(0)
    try:
        return pd.read_excel(file_obj, header=None)
    except:
        file_obj.seek(0)
        content = file_obj.read().decode('latin1', errors='ignore')
        return pd.read_csv(io.StringIO(content), sep=None, engine='python', header=None)

@st.cache_data
def carregar_cmed():
    if os.path.exists('cmed_atual.xlsx'):
        df_cmed = pd.read_excel('cmed_atual.xlsx')
        df_cmed.columns = df_cmed.columns.astype(str).str.strip()
        
        # Leitura cega como no Colab para achar onde os dados começam
        if 'REGISTRO' not in df_cmed.columns:
            df_raw = pd.read_excel('cmed_atual.xlsx', header=None)
            for i, r in df_raw.iterrows():
                if r.astype(str).str.contains('REGISTRO').any():
                    df_cmed = pd.read_excel('cmed_atual.xlsx', skiprows=i)
                    df_cmed.columns = df_cmed.columns.astype(str).str.replace(' %', '%').str.strip()
                    break
        return df_cmed
    return None

def formatar_moeda(val):
    """Tratamento rigoroso para garantir que vírgulas e pontos não quebrem a matemática"""
    v = str(val).replace('R$', '').strip()
    if pd.isna(val) or v == 'nan' or v == 'None' or v == '': return 0.0
    if '.' in v and ',' in v:
        v = v.replace('.', '')
    v = v.replace(',', '.')
    try: return float(v)
    except: return 0.0

def processar_dados(file_proposta, df_cmed, coluna_icms):
    try:
        df_raw = ler_proposta_robusto(file_proposta)
        
        # Acha linha de cabeçalho
        linha_cab = 0
        for i, row in df_raw.iterrows():
            if row.astype(str).str.contains('Reg.M.S|Vlr. Unit.', case=False).any():
                linha_cab = i
                break
                
        # Extrai metadados do cabeçalho
        cabecalho_info = [" ".join(df_raw.iloc[j].dropna().astype(str).tolist()) for j in range(linha_cab) if str(df_raw.iloc[j].dropna()).strip()]

        df_prop = df_raw.iloc[linha_cab+1:].copy()
        df_prop.columns = df_raw.iloc[linha_cab].astype(str).str.strip()
        
        # Mapeamento dinâmico
        c_desc = [c for c in df_prop.columns if 'D i s c' in str(c) or 'Nome Com' in str(c) or 'Descrição' in str(c)][0]
        c_reg = [c for c in df_prop.columns if 'REG.M.S' in str(c).upper().replace(' ', '') or 'REGISTRO' in str(c).upper()][0]
        c_vlr = [c for c in df_prop.columns if 'VLR' in str(c).upper() and 'UNIT' in str(c).upper()][0]
        
        try:
            c_item = [c for c in df_prop.columns if 'ITEM' in str(c).upper()][0]
        except:
            df_prop['Item'] = range(1, len(df_prop) + 1)
            c_item = 'Item'

        c_apres_cmed = [c for c in df_cmed.columns if 'APRESENTA' in str(c).upper()][0]
        
        if coluna_icms not in df_cmed.columns:
            return None, None, f"Coluna '{coluna_icms}' ausente na CMED. Verifique o padrão de nomenclatura."

        # Limpeza de chaves de cruzamento
        df_prop['Reg_L'] = df_prop[c_reg].astype(str).str.replace(r'[^0-9]', '', regex=True)
        df_cmed['Reg_C'] = df_cmed['REGISTRO'].astype(str).str.replace(r'[^0-9]', '', regex=True)
        
        df_prop['V_Unit'] = df_prop[c_vlr].apply(formatar_moeda)

        # Merge Left (A magia do Colab)
        df_m = pd.merge(df_prop, df_cmed[['Reg_C', coluna_icms, c_apres_cmed]], left_on='Reg_L', right_on='Reg_C', how='left')
        
        df_m['PF_Num'] = df_m[coluna_icms].apply(formatar_moeda)
        df_m['Qtd_C'] = df_m[c_apres_cmed].apply(extrair_qtd_cmed)
        
        # Evita crash matemático
        df_m['Qtd_C'] = df_m['Qtd_C'].apply(lambda x: 1 if x == 0 else x)
        df_m['Teto_U'] = df_m['PF_Num'] / df_m['Qtd_C']
        
        # Filtragem Rigorosa Idêntica ao Colab
        df_erros = df_m[df_m['V_Unit'] > df_m['Teto_U']].copy()
        
        # Armazena visualizações seguras
        df_erros['Col_Item'] = df_erros[c_item]
        df_erros['Col_Desc'] = df_erros[c_desc]

        return df_erros, cabecalho_info, None

    except Exception as e:
        return None, None, f"Erro Crítico: {str(e)}"

# --- INTERFACE ---
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
    escolha_icms = st.selectbox("Selecione a Alíquota ICMS:", opcoes_icms, index=7)
    
    st.markdown("---")
    if df_cmed is not None: st.success("✅ Base CMED Ativa")
    else: st.error("❌ 'cmed_atual.xlsx' não encontrado.")

st.title("🛡️ Auditoria Drogafonte - Validador CMED")
st.markdown("---")

# TELA 1: Upload (Só aparece se NÃO estiver na tela de resultado)
if not st.session_state.tela_resultado:
    if df_cmed is not None:
        upload_prop = st.file_uploader("Anexe a Proposta (Excel/XLS/CSV)", type=['xls', 'xlsx', 'csv'])
        
        # BOTÃO DE PROCESSAR
        if upload_prop:
            if st.button("▶️ Processar Arquivo", use_container_width=True, type="primary"):
                with st.spinner("Lendo Proposta e Cruzando com a CMED..."):
                    dados, cab, erro = processar_dados(upload_prop, df_cmed, escolha_icms)
                    st.session_state.dados_finais = dados
                    st.session_state.cabecalho_pdf = cab
                    st.session_state.erro = erro
                    st.session_state.nome_arquivo = upload_prop.name
                    st.session_state.tela_resultado = True
                    st.rerun()

# TELA 2: Resultados e Limpeza
else:
    # BOTÃO DE LIMPAR (Apaga a tela atual e permite novo upload)
    st.button("🔄 Limpar e Processar Novo Arquivo", on_click=resetar_app, use_container_width=True)
    st.markdown("---")
    
    if st.session_state.erro:
        st.error(st.session_state.erro)
    else:
        dados_finais = st.session_state.dados_finais
        cabecalho_pdf = st.session_state.cabecalho_pdf
        
        if dados_finais.empty:
            st.success("✅ PROPOSTA AUDITADA: 100% DENTRO DOS TETOS LEGAIS.")
        else:
            st.warning(f"🚨 Atenção: {len(dados_finais)} itens da proposta ultrapassaram o teto legal!")
            
            exibicao = dados_finais[['Col_Item', 'Col_Desc', 'V_Unit', 'Teto_U']].copy()
            exibicao.columns = ['Item', 'Descrição', 'Valor Proposta', 'Teto CMED']
            st.dataframe(exibicao.style.format({'Valor Proposta': 'R$ {:.4f}', 'Teto CMED': 'R$ {:.4f}'}))

            # GERAÇÃO DO PDF EXATO
            if st.button("📥 Baixar Relatório Profissional (PDF)"):
                pdf = FPDF(orientation='L', unit='mm', format='A4')
                pdf.add_page()
                
                pdf.set_font("Arial", 'B', 10)
                for linha in cabecalho_pdf[:5]:
                    linha_limpa = str(linha).encode('latin-1', 'replace').decode('latin-1')
                    pdf.cell(0, 5, linha_limpa, ln=True)
                
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
                    item_str = str(r['Col_Item']).replace('.0', '')
                    desc_str = str(r['Col_Desc'])[:85].encode('latin-1', 'replace').decode('latin-1')
                    v_prop = r['V_Unit']
                    teto = r['Teto_U']
                    diff = v_prop - teto
                    
                    pdf.cell(15, 7, item_str, 1, 0, 'C')
                    pdf.cell(140, 7, desc_str, 1)
                    pdf.cell(30, 7, f"R$ {v_prop:.4f}", 1, 0, 'C')
                    pdf.cell(30, 7, f"R$ {teto:.4f}", 1, 0, 'C')
                    
                    pdf.set_text_color(200, 0, 0)
                    pdf.cell(30, 7, f"R$ {diff:.4f}", 1, 1, 'C')
                    pdf.set_text_color(0)

                pdf_output = pdf.output(dest='S').encode('latin-1')
                st.download_button(
                    "Salvar PDF", 
                    data=pdf_output, 
                    file_name="Relatorio_Auditoria.pdf", 
                    mime="application/pdf"
                )
