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
    "MARANHÃO (23%)": "PF 22%", # A CMED geralmente agrupa o teto máximo em 22% na tabela padrão
    "MATO GROSSO (17%)": "PF 17%",
    "MATO GROSSO DO SUL (17%)": "PF 17%",
    "MINAS GERAIS (18%)": "PF 18%",
    "MINAS GERAIS - GENÉRICOS (12%)": "PF 12%",
    "PARÁ (19%)": "PF 19%",
    "PARAÍBA (20%)": "PF 20%",
    "PARANÁ (19,5%)": "PF 19,5%",
    "PERNAMBUCO (20,5%)": "PF 20,5%",
    "PIAUÍ (22,5%)": "PF 22%", # Ajustado para o teto máximo atual da tabela CMED
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
    """Lida com valores financeiros, removendo R$, asteriscos e caracteres especiais"""
    if pd.isna(val) or str(val).strip() == '': 
        return 0.0
    v = str(val)
    v = re.sub(r'[^\d\.,]', '', v)
    if v == '': return 0.0
    if '.' in v and ',' in v: v = v.replace('.', '')
    v = v.replace(',', '.')
    try: return float(v)
    except: return 0.0

# --- ESTADOS DO SISTEMA ---
if 'tela_resultado' not in st.session_state:
    st.session_state.tela_resultado = False

def resetar_app():
    st.session_state.tela_resultado = False
    for key in ['dados_todos', 'dados_finais', 'erros_registro', 'cabecalho_pdf', 'erro', 'aliquota', 'estado_nome']:
        if key in st.session_state: del st.session_state[key]

# --- MOTOR LÓGICO DE QUANTIDADES ---
def extrair_qtd_cmed(apres_cmed, desc_proposta):
    apres = str(apres_cmed).upper()
    desc = str(desc_proposta).upper()
    
    padrao_dose = r'\b(DOSES?|AEROSSOL|AEROSOL|AER\b|SPRAY|JATOS?|ACIONAMENTOS?|INALADOR|PULVERIZA[A-Z]*)\b'
    if re.search(padrao_dose, apres) or re.search(padrao_dose, desc):
        return 1
    
    unidades_ignoradas = r'(?:ML|MG|G|MCG|UI|%|L|KG|GOTAS|MM|CM)'
    
    m = re.search(rf'\b(\d+)\s+(?:BL|ENV|STRIP|CPR|CAP|AMP|FA|FR|SER|TB|BS|CJ|SVD).*?X\s+(\d+)\b(?!\s*{unidades_ignoradas})', apres)
    if m: return float(m.group(1)) * float(m.group(2))
    
    m = re.search(r'\b(\d+)\s+(?:AMP|FA|FR|SER|TB|BS|CJ|BOLS|CARP|TUB|BOMBA|CANETA|SVD|CX|CT|BL|ENV|STRIP|CPR|COMP?|CPRS|CAP|UN)\b', apres)
    if m: return float(m.group(1))
    
    m = re.search(rf'X\s+(\d+)\b(?!\s*{unidades_ignoradas})', apres)
    if m: return float(m.group(1))
    
    m = re.search(r'(?:C/|CT|CX|COM|CONTEM)\s*(\d+)\b', apres)
    if m: return float(m.group(1))
    
    return 1

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
        
        c_desc = [c for c in df_prop.columns if any(x in str(c) for x in ['D i s c', 'Nome Com', 'Descrição'])][0]
        c_reg = [c for c in df_prop.columns if 'REG.M.S' in str(c).upper().replace(' ', '') or 'REGISTRO' in str(c).upper()][0]
        c_vlr = [c for c in df_prop.columns if 'VLR' in str(c).upper() and 'UNIT' in str(c).upper()][0]
        c_item = [c for c in df_prop.columns if 'ITEM' in str(c).upper()][0]

        df_prop['Reg_L'] = df_prop[c_reg].apply(limpar_registro)
        df_cmed['Reg_C'] = df_cmed['REGISTRO'].apply(limpar_registro)
        
        df_prop['V_Unit'] = df_prop[c_vlr].apply(formatar_moeda)
        c_apres_cmed = [c for c in df_cmed.columns if 'APRESENTA' in str(c).upper()][0]

        df_m = pd.merge(df_prop, df_cmed[['Reg_C', coluna_icms, c_apres_cmed]], left_on='Reg_L', right_on='Reg_C', how='left')
        df_m['PF_Num'] = df_m[coluna_icms].apply(formatar_moeda)
        
        df_m['Divisor'] = df_m.apply(lambda row: extrair_qtd_cmed(row[c_apres_cmed], row[c_desc]), axis=1)
        df_m['Teto_U'] = df_m['PF_Num'] / df_m['Divisor']
        df_m['Diferenca'] = df_m['V_Unit'] - df_m['Teto_U']

        # Prepara a tabela completa
        df_m['Col_Item'] = df_m[c_item]
        df_m['Col_Desc'] = df_m[c_desc]
        df_m['Col_Reg'] = df_m[c_reg]
        df_m['Status'] = df_m.apply(lambda x: '🔴 Acima do Teto' if x['Diferenca'] > 0.0005 else '🟢 Dentro do Teto', axis=1)

        # Filtra linhas completamente vazias (rodapés do excel)
        df_valido = df_m[df_m['Col_Desc'].notna() & (df_m['Col_Desc'].astype(str).str.strip() != '')].copy()

        # Preços acima do teto
        df_precos = df_valido[(df_valido['Diferenca'] > 0.0005) & (df_valido['Teto_U'] > 0)].copy()

        # Condição Definitiva de Alertas de Registro
        cond_alerta = (
            df_valido['Col_Reg'].astype(str).str.upper().str.contains(r'NOTIFICADO|RDC', na=False) |
            (df_valido['Reg_L'].str.len() != 13) |
            (df_valido['Reg_C'].isna())
        )
        df_reg_err = df_valido[cond_alerta].copy()

        return df_valido, df_precos, df_reg_err, cabecalho_info, None
    except Exception as e:
        return None, None, None, None, f"Erro: {str(e)}"

# --- INTERFACE ---
df_cmed = carregar_cmed()
with st.sidebar:
    logo_b64 = get_image_base64("logo.png") or get_image_base64("logo_drogafonte.png")
    if logo_b64:
        st.markdown(f'<img src="data:image/png;base64,{logo_b64}" width="200">', unsafe_allow_html=True)
    else:
        st.image("https://drogafonte.com.br/wp-content/uploads/2021/10/logo-drogafonte.png", width=200)
    
    st.divider()
    
    # --- NOVO SELECTBOX POR ESTADO ---
    lista_estados = list(ESTADOS_ICMS.keys())
    indice_pe = lista_estados.index("PERNAMBUCO (20,5%)") # Deixa PE como padrão
    estado_selecionado = st.selectbox("Estado de Destino:", lista_estados, index=indice_pe)
    aliquota = ESTADOS_ICMS[estado_selecionado]
    
    st.caption(f"📍 Mapeado para: **{aliquota}**")

st.title("🛡️ Validador CMED - Modo Diagnóstico")

if not st.session_state.tela_resultado:
    upload = st.file_uploader("Arraste a Proposta", type=['xls', 'xlsx', 'csv'])
    if upload and st.button("🚀 Iniciar Auditoria", use_container_width=True, type="primary"):
        t, p, r, c, err = processar_dados(upload, df_cmed, aliquota)
        st.session_state.dados_todos, st.session_state.dados_finais, st.session_state.erros_registro, st.session_state.cabecalho_pdf, st.session_state.erro, st.session_state.aliquota, st.session_state.estado_nome = t, p, r, c, err, aliquota, estado_selecionado
        st.session_state.tela_resultado = True
        st.rerun()
else:
    st.button("⬅️ Nova Análise", on_click=resetar_app)
    
    if st.session_state.erro:
        st.error(st.session_state.erro)
    else:
        # SISTEMA DE ABAS
        tab1, tab2, tab3 = st.tabs(["🔴 Acima do Teto (Divergências)", "🔍 Análise Completa (Todos os Itens)", "⚠️ Alertas de Registro"])

        # ABA 1: DIVERGÊNCIAS
        with tab1:
            df_p = st.session_state.dados_finais
            if df_p.empty: 
                st.success("Tudo OK! Nenhum item com preço abusivo.")
            else:
                exib_p = df_p[['Col_Item', 'Col_Desc', 'V_Unit', 'PF_Num', 'Divisor', 'Teto_U', 'Diferenca']].copy()
                exib_p.columns = ['Item', 'Descrição', 'Valor Proposta', 'PF CMED', 'Divisor', 'Teto Unit.', 'Diferença']
                st.dataframe(
                    exib_p.style.format({'Valor Proposta': 'R$ {:.4f}', 'PF CMED': 'R$ {:.4f}', 'Divisor': '{:.0f}', 'Teto Unit.': 'R$ {:.4f}', 'Diferença': 'R$ {:.4f}'}), 
                    use_container_width=True
                )

        # ABA 2: TODOS OS ITENS
        with tab2:
            df_t = st.session_state.dados_todos
            st.info("Aqui estão todos os itens processados. Use para verificar se as divisões de caixas e os preços estão perfeitos.")
            exib_t = df_t[['Col_Item', 'Col_Desc', 'V_Unit', 'PF_Num', 'Divisor', 'Teto_U', 'Diferenca', 'Status']].copy()
            exib_t.columns = ['Item', 'Descrição', 'Valor Proposta', 'PF CMED', 'Divisor', 'Teto Unit.', 'Diferença', 'Status']
            st.dataframe(
                exib_t.style.format({'Valor Proposta': 'R$ {:.4f}', 'PF CMED': 'R$ {:.4f}', 'Divisor': '{:.0f}', 'Teto Unit.': 'R$ {:.4f}', 'Diferença': 'R$ {:.4f}'}), 
                use_container_width=True
            )

        # ABA 3: ALERTAS DE REGISTRO
        with tab3:
            df_r = st.session_state.erros_registro
            if not df_r.empty:
                st.warning("Aqui estão itens que devem ser revisados: RDC, Notificados, Registros com tamanho errado ou não localizados na CMED.")
                st.dataframe(df_r[['Col_Item', 'Col_Desc', 'Col_Reg']], use_container_width=True)
            else:
                st.info("Nenhum alerta de registro.")
        
        st.divider()

        st.download_button("📥 Baixar Planilha Completa (Excel)", exportar_excel(st.session_state.dados_todos, st.session_state.dados_finais, st.session_state.erros_registro), "Auditoria_Diagnostico.xlsx", use_container_width=True)

        if st.button("📄 Gerar Relatório PDF Final", type="primary", use_container_width=True):
            pdf = FPDF(orientation='L', unit='mm', format='A4')
            
            if not df_p.empty:
                pdf.add_page()
                pdf.set_font("Arial", 'B', 9)
                for h in st.session_state.cabecalho_pdf[:5]: pdf.cell(0, 5, str(h).encode('latin-1', 'replace').decode('latin-1'), ln=True)
                pdf.ln(5)
                
                pdf.set_font("Arial", 'B', 14); pdf.set_text_color(180, 0, 0)
                # O título do PDF agora mostra o Estado escolhido
                pdf.cell(0, 10, f"DIVERGENCIAS DE PRECO - {st.session_state.estado_nome}", ln=True, align='C')
                pdf.ln(3)
                
                pdf.set_font("Arial", 'B', 8); pdf.set_text_color(0); pdf.set_fill_color(230, 230, 230)
                pdf.cell(15, 8, "Item", 1, 0, 'C', True); pdf.cell(130, 8, "Descricao", 1, 0, 'C', True)
                pdf.cell(25, 8, "Proposta", 1, 0, 'C', True); pdf.cell(25, 8, "PF CMED", 1, 0, 'C', True)
                pdf.cell(15, 8, "Div.", 1, 0, 'C', True); pdf.cell(25, 8, "Teto", 1, 0, 'C', True); pdf.cell(25, 8, "Dif.", 1, 1, 'C', True)
                
                pdf.set_font("Arial", '', 8)
                for _, row in df_p.iterrows():
                    pdf.cell(15, 7, str(row['Col_Item']), 1, 0, 'C')
                    pdf.cell(130, 7, str(row['Col_Desc'])[:85].encode('latin-1', 'replace').decode('latin-1'), 1)
                    pdf.cell(25, 7, f"{row['V_Unit']:.4f}", 1, 0, 'C')
                    pdf.cell(25, 7, f"{row['PF_Num']:.4f}", 1, 0, 'C')
                    pdf.cell(15, 7, str(int(row['Divisor'])), 1, 0, 'C')
                    pdf.cell(25, 7, f"{row['Teto_U']:.4f}", 1, 0, 'C')
                    pdf.cell(25, 7, f"{row['Diferenca']:.4f}", 1, 1, 'C')

            if not df_r.empty:
                pdf.add_page()
                pdf.set_font("Arial", 'B', 14); pdf.set_text_color(0)
                pdf.cell(0, 10, "ALERTAS DE REGISTRO / PRODUTOS NOTIFICADOS", ln=True, align='C')
                pdf.ln(5)
                pdf.set_font("Arial", 'B', 8); pdf.set_fill_color(230, 230, 230)
                pdf.cell(15, 8, "Item", 1, 0, 'C', True); pdf.cell(190, 8, "Descricao", 1, 0, 'C', True); pdf.cell(50, 8, "Registro", 1, 1, 'C', True)
                
                pdf.set_font("Arial", '', 8)
                for _, row in df_r.iterrows():
                    pdf.cell(15, 7, str(row['Col_Item']), 1, 0, 'C')
                    pdf.cell(190, 7, str(row['Col_Desc'])[:110].encode('latin-1', 'replace').decode('latin-1'), 1)
                    pdf.cell(50, 7, str(row['Col_Reg']), 1, 1, 'C')

            st.download_button("💾 Baixar PDF do Relatório", pdf.output(dest='S').encode('latin-1'), "Relatorio_Auditoria.pdf", "application/pdf")
