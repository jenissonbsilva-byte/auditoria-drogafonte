import streamlit as st
import pandas as pd
from fpdf import FPDF
import io
import re
import os
import base64

# Configuração da Página
st.set_page_config(page_title="Auditoria Drogafonte - CMED", layout="wide", page_icon="🛡️")

# --- DICIONÁRIO DE ALÍQUOTAS POR ESTADO ---
ESTADOS_ICMS = {
    "ACRE (19%)": "PF 19%",
    "ALAGOAS (19%)": "PF 19%",
    "AMAPÁ (18%)": "PF 18%",
    "AMAZONAS (20%)": "PF 20%",
    "BAHIA (20,5%)": "PF 20,5%",
    "CEARÁ (20%)": "PF 20%",
    "DISTRITO FEDERAL (17%)": "PF 17%",
    "ESPÍRITO SANTO (17%)": "PF 17%",
    "GOIÁS (19%)": "PF 19%",
    "MARANHÃO (23%)": "PF 22%", 
    "MATO GROSSO (17%)": "PF 17%",
    "MATO GROSSO DO SUL (17%)": "PF 17%",
    "MINAS GERAIS (18%)": "PF 18%",
    "MINAS GERAIS - GENÉRICOS (12%)": "PF 12%",
    "PARÁ (19%)": "PF 19%",
    "PARAÍBA (20%)": "PF 20%",
    "PARANÁ (19,5%)": "PF 19,5%",
    "PERNAMBUCO (20,5%)": "PF 20,5%",
    "PIAUÍ (22,5%)": "PF 22%", 
    "RIO DE JANEIRO (22%)": "PF 22%",
    "RIO GRANDE DO NORTE (20%)": "PF 20%",
    "RIO GRANDE DO SUL (17%)": "PF 17%",
    "RONDÔNIA (19,5%)": "PF 19,5%",
    "RORAIMA (20%)": "PF 20%",
    "SANTA CATARINA (17%)": "PF 17%",
    "SÃO PAULO (18%)": "PF 18%",
    "SÃO PAULO - GENÉRICOS (12%)": "PF 12%",
    "SERGIPE (19%)": "PF 19%",
    "TOCANTINS (20%)": "PF 20%"
}

# --- FUNÇÕES DE APOIO E LIMPEZA ---
def get_image_base64(path):
    try:
        with open(path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    except:
        return None

def limpar_registro(reg):
    """Garante que o registro seja lido corretamente com 13 dígitos"""
    if pd.isna(reg) or str(reg).strip().upper() in ['NAN', 'NONE', '']: 
        return ""
    if isinstance(reg, (float, int)):
        return str(int(reg))
    s = str(reg).strip()
    if s.endswith('.0'): 
        s = s[:-2]
    return re.sub(r'[^0-9]', '', s)

def formatar_moeda(val):
    """Lida com valores financeiros, removendo R$ e normalizando separadores"""
    if pd.isna(val) or str(val).strip() == '': 
        return 0.0
    v = str(val)
    v = re.sub(r'[^\d\.,]', '', v)
    if v == '': return 0.0
    if '.' in v and ',' in v: v = v.replace('.', '')
    v = v.replace(',', '.')
    try: return float(v)
    except: return 0.0

# --- MOTOR LÓGICO DE QUANTIDADES (BLINDADO CONTRA DIVISOR ZERO) ---
def extrair_qtd_cmed(apres_cmed, desc_proposta):
    apres = str(apres_cmed).upper()
    desc = str(desc_proposta).upper()
    
    padrao_dose = r'\b(DOSES?|AEROSSOL|AEROSOL|AER\b|SPRAY|JATOS?|ACIONAMENTOS?|INALADOR|PULVERIZA[A-Z]*)\b'
    if re.search(padrao_dose, apres) or re.search(padrao_dose, desc):
        return 1
    
    unidades_ignoradas = r'(?:ML|MG|G|MCG|UI|%|L|KG|GOTAS|MM|CM)'
    
    # Busca padrões de multiplicação (Ex: 10 BL X 10) - Trava para não ler decimais (ex: 0,6ml)
    m = re.search(rf'\b(\d+)\s+(?:BL|ENV|STRIP|CPR|CAP|AMP|FA|FR|SER|TB|BS|CJ|SVD).*?X\s+(\d+)\b(?!\s*[,.]\s*\d+)(?!\s*{unidades_ignoradas})', apres)
    if m: 
        return float(m.group(1)) * float(m.group(2))
    
    # Busca quantidades isoladas de recipientes (Ex: 2 SER PREENCHIDAS)
    m = re.search(r'\b(\d+)\s+(?:AMP|FA|FR|SER|TB|BS|CJ|BOLS|CARP|TUB|BOMBA|CANETA|SVD|CX|CT|BL|ENV|STRIP|CPR|COMP?|CPRS|CAP|UN)\b', apres)
    if m:
        return float(m.group(1))
    
    # Busca padrão "X Quantidade" (Ex: X 500)
    m = re.search(rf'X\s+(\d+)\b(?!\s*[,.]\s*\d+)(?!\s*{unidades_ignoradas})', apres)
    if m: 
        return float(m.group(1))
    
    # Busca padrão "C/ Quantidade"
    m = re.search(r'(?:C/|CT|CX|COM|CONTEM)\s*(\d+)\b', apres)
    if m: 
        return float(m.group(1))
    
    return 1

# --- PROCESSAMENTO DOS ARQUIVOS ---
def processar_dados(file_proposta, df_cmed, coluna_icms):
    try:
        if file_proposta.name.endswith('.xls'):
            df_raw = pd.read_excel(file_proposta, header=None, engine='xlrd')
        else:
            df_raw = pd.read_excel(file_proposta, header=None, engine='openpyxl')
            
        linha_cab = 0
        for i, row in df_raw.iterrows():
            if row.astype(str).str.contains('Reg.M.S|Vlr. Unit.', case=False).any():
                linha_cab = i
                break
        
        cabecalho_info = [" ".join(df_raw.iloc[j].dropna().astype(str).tolist()) for j in range(linha_cab) if str(df_raw.iloc[j].dropna()).strip()]
        df_prop = df_raw.iloc[linha_cab+1:].copy()
        df_prop.columns = df_raw.iloc[linha_cab].astype(str).str.strip()
        
        # Mapeamento de Colunas
        c_desc = [c for c in df_prop.columns if any(x in str(c) for x in ['D i s c', 'Nome Com', 'Descrição'])][0]
        c_reg = [c for c in df_prop.columns if 'REG.M.S' in str(c).upper().replace(' ', '') or 'REGISTRO' in str(c).upper()][0]
        c_vlr = [c for c in df_prop.columns if 'VLR' in str(c).upper() and 'UNIT' in str(c).upper()][0]
        c_item = [c for c in df_prop.columns if 'ITEM' in str(c).upper()][0]

        df_prop['Reg_L'] = df_prop[c_reg].apply(limpar_registro)
        df_cmed['Reg_C'] = df_cmed['REGISTRO'].apply(limpar_registro)
        df_prop['V_Unit'] = df_prop[c_vlr].apply(formatar_moeda)
        c_apres_cmed = [c for c in df_cmed.columns if 'APRESENTA' in str(c).upper()][0]

        # Merge com a CMED
        df_m = pd.merge(df_prop, df_cmed[['Reg_C', coluna_icms, c_apres_cmed]], left_on='Reg_L', right_on='Reg_C', how='left')
        df_m['PF_Num'] = df_m[coluna_icms].apply(formatar_moeda)
        
        # Cálculos
        df_m['Divisor'] = df_m.apply(lambda row: extrair_qtd_cmed(row[c_apres_cmed], row[c_desc]), axis=1)
        df_m['Teto_U'] = df_m['PF_Num'] / df_m['Divisor']
        df_m['Diferenca'] = df_m['V_Unit'] - df_m['Teto_U']

        # Normalização de nomes de colunas para exibição
        df_m['Col_Item'] = df_m[c_item]
        df_m['Col_Desc'] = df_m[c_desc]
        df_m['Col_Reg'] = df_m[c_reg]
        df_m['Status'] = df_m.apply(lambda x: '🔴 Acima do Teto' if x['Diferenca'] > 0.0005 else '🟢 Dentro do Teto', axis=1)

        # Filtro de linhas válidas
        df_valido = df_m[df_m['Col_Desc'].notna() & (df_m['Col_Desc'].astype(str).str.strip() != '')].copy()

        # Tabelas de Saída
        df_precos = df_valido[(df_valido['Diferenca'] > 0.0005) & (df_valido['Teto_U'] > 0)].copy()

        # REGRAS PARA ALERTAS DE REGISTRO
        cond_alerta = (
            df_valido['Col_Reg'].astype(str).str.upper().str.contains(r'NOTIFICADO|RDC', na=False) |
            (df_valido['Reg_L'].str.len() != 13) |
            (df_valido['Reg_C'].isna())
        )
        df_reg_err = df_valido[cond_alerta].copy()

        return df_valido, df_precos, df_reg_err, cabecalho_info, None
    except Exception as e:
        return None, None, None, None, f"Erro no processamento: {str(e)}"

# --- INTERFACE ---
if 'tela_resultado' not in st.session_state:
    st.session_state.tela_resultado = False

def resetar_app():
    st.session_state.tela_resultado = False

def exportar_excel(df_todos, df_precos, df_alertas):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_todos.to_excel(writer, index=False, sheet_name='Analise_Completa')
        df_precos.to_excel(writer, index=False, sheet_name='Divergencias_Preco')
        df_alertas.to_excel(writer, index=False, sheet_name='Alertas_Registro')
    return output.getvalue()

@st.cache_data
def carregar_cmed():
    if os.path.exists('cmed_atual.xlsx'):
        df_raw = pd.read_excel('cmed_atual.xlsx', header=None, engine='openpyxl')
        for i, r in df_raw.iterrows():
            if r.astype(str).str.contains('REGISTRO').any():
                df = pd.read_excel('cmed_atual.xlsx', skiprows=i)
                df.columns = df.columns.astype(str).str.replace(' %', '%').str.strip()
                return df
    return None

df_cmed = carregar_cmed()

with st.sidebar:
    st.image("https://drogafonte.com.br/wp-content/uploads/2021/10/logo-drogafonte.png", width=200)
    st.divider()
    
    # Seleção de Estado
    lista_estados = list(ESTADOS_ICMS.keys())
    try: indice_def = lista_estados.index("PERNAMBUCO (20,5%)")
    except: indice_def = 0
    
    estado_selecionado = st.selectbox("Estado de Destino:", lista_estados, index=indice_def)
    aliquota_cmed = ESTADOS_ICMS[estado_selecionado]
    st.caption(f"Mapeado para coluna: **{aliquota_cmed}**")

st.title("🛡️ Validador Drogafonte - Diagnóstico CMED")

if not st.session_state.tela_resultado:
    upload = st.file_uploader("Arraste a Proposta (Excel ou XLS)", type=['xls', 'xlsx'])
    if upload and st.button("🚀 Iniciar Auditoria", use_container_width=True, type="primary"):
        t, p, r, c, err = processar_dados(upload, df_cmed, aliquota_cmed)
        if err:
            st.error(err)
        else:
            st.session_state.dados_todos = t
            st.session_state.dados_finais = p
            st.session_state.erros_registro = r
            st.session_state.cabecalho_pdf = c
            st.session_state.aliquota_usada = aliquota_cmed
            st.session_state.estado_usado = estado_selecionado
            st.session_state.tela_resultado = True
            st.rerun()
else:
    st.button("⬅️ Nova Análise", on_click=resetar_app)
    
    tab1, tab2, tab3 = st.tabs(["🔴 Divergências de Preço", "🔍 Análise Completa", "⚠️ Alertas de Registro"])

    with tab1:
        if st.session_state.dados_finais.empty:
            st.success("Nenhuma divergência encontrada!")
        else:
            df_p = st.session_state.dados_finais[['Col_Item', 'Col_Desc', 'V_Unit', 'PF_Num', 'Divisor', 'Teto_U', 'Diferenca']]
            st.dataframe(df_p.style.format({'V_Unit': 'R$ {:.4f}', 'PF_Num': 'R$ {:.4f}', 'Teto_U': 'R$ {:.4f}', 'Diferenca': 'R$ {:.4f}'}), use_container_width=True)

    with tab2:
        df_t = st.session_state.dados_todos[['Col_Item', 'Col_Desc', 'V_Unit', 'Teto_U', 'Status']]
        st.dataframe(df_t, use_container_width=True)

    with tab3:
        if not st.session_state.erros_registro.empty:
            st.warning("Itens com Registro Inválido, Notificados ou não encontrados na CMED:")
            st.dataframe(st.session_state.erros_registro[['Col_Item', 'Col_Desc', 'Col_Reg']], use_container_width=True)
        else:
            st.info("Nenhum alerta de registro.")

    st.divider()
    
    # Exportações
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("📥 Baixar Excel", exportar_excel(st.session_state.dados_todos, st.session_state.dados_finais, st.session_state.erros_registro), "Auditoria_CMED.xlsx", use_container_width=True)
    
    with col2:
        if st.button("📄 Gerar PDF", use_container_width=True):
            pdf = FPDF(orientation='L', unit='mm', format='A4')
            pdf.add_page()
            pdf.set_font("Arial", 'B', 12)
            pdf.cell(0, 10, f"RELATÓRIO DE AUDITORIA - {st.session_state.estado_usado}", ln=True, align='C')
            pdf.ln(5)
            
            # Tabela de Divergências no PDF
            if not st.session_state.dados_finais.empty:
                pdf.set_font("Arial", 'B', 9); pdf.set_fill_color(200, 200, 200)
                pdf.cell(15, 8, "Item", 1, 0, 'C', True); pdf.cell(150, 8, "Descricao", 1, 0, 'C', True)
                pdf.cell(25, 8, "Proposta", 1, 0, 'C', True); pdf.cell(25, 8, "Teto", 1, 0, 'C', True); pdf.cell(25, 8, "Dif.", 1, 1, 'C', True)
                pdf.set_font("Arial", '', 8)
                for _, row in st.session_state.dados_finais.iterrows():
                    pdf.cell(15, 7, str(row['Col_Item']), 1)
                    pdf.cell(150, 7, str(row['Col_Desc'])[:90].encode('latin-1', 'replace').decode('latin-1'), 1)
                    pdf.cell(25, 7, f"{row['V_Unit']:.4f}", 1)
                    pdf.cell(25, 7, f"{row['Teto_U']:.4f}", 1)
                    pdf.cell(25, 7, f"{row['Diferenca']:.4f}", 1, 1)
            
            st.download_button("💾 Salvar PDF", pdf.output(dest='S').encode('latin-1'), "Auditoria.pdf", "application/pdf")
