import streamlit as st
import pandas as pd
from fpdf import FPDF
import io
import re
import os
import base64

# Configuração da Página
st.set_page_config(page_title="Auditoria Drogafonte - CMED", layout="wide", page_icon="🛡️")

# --- FUNÇÃO PARA LOGO (PREVINE QUE SUMA) ---
def get_image_base64(path):
    try:
        with open(path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    except:
        return None

# --- ESTADOS DO SISTEMA ---
if 'tela_resultado' not in st.session_state:
    st.session_state.tela_resultado = False

def resetar_app():
    st.session_state.tela_resultado = False
    for key in ['dados_finais', 'erros_registro', 'cabecalho_pdf', 'erro', 'aliquota']:
        if key in st.session_state: del st.session_state[key]

# --- MOTORES LÓGICOS ---
def extrair_qtd_cmed(apres):
    apres = str(apres).upper()
    
    # 1. REGRA: Se for DOSE, o divisor é 1 (Unitário)
    if "DOS" in apres or "DOSE" in apres: 
        return 1
    
    # Lista de unidades de peso/volume que NÃO devem ser multiplicadas
    unidades_ignoradas = r'(?:ML|MG|G|MCG|UI|%|L|KG|GOTAS)'
    
    # 2. Busca padrões de multiplicação válidos (ex: 3 BL X 10) - IGNORANDO ML/MG
    m = re.search(rf'\b(\d+)\s+(?:BL|ENV|STRIP|CPR|CAP|AMP|FA|FR|SER|TB|BS|CJ|SVD).*?X\s+(\d+)\b(?!\s*{unidades_ignoradas})', apres)
    if m: 
        return float(m.group(1)) * float(m.group(2))
    
    # 3. Busca quantidade principal de embalagens físicas ANTES de ML (ex: "50 AMP X 2 ML" -> Pega o 50)
    m = re.search(r'\b(\d+)\s+(?:AMP|FA|FR|SER|TB|BS|CJ|BOLS|CARP|TUB|BOMBA|CANETA|SVD|CX|CT)\b', apres)
    if m:
        return float(m.group(1))
    
    # 4. Busca padrão "X Quantidade" (ex: CX X 30) - IGNORANDO ML/MG
    m = re.search(rf'X\s+(\d+)\b(?!\s*{unidades_ignoradas})', apres)
    if m: 
        return float(m.group(1))
    
    # 5. Busca padrão "Contém/Com" (ex: CT C/ 20)
    m = re.search(r'(?:C/|CT|CX|COM|CONTEM)\s*(\d+)\b', apres)
    if m: 
        return float(m.group(1))
    
    # Se nada bater, considera que é 1 unidade
    return 1

def formatar_moeda(val):
    v = str(val).replace('R$', '').replace(' ', '').strip()
    if pd.isna(val) or v.lower() == 'nan' or v == '': return 0.0
    if '.' in v and ',' in v: v = v.replace('.', '')
    v = v.replace(',', '.')
    try: return float(v)
    except: return 0.0

def exportar_excel(df_precos, df_alertas):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
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

        df_prop['Reg_L'] = df_prop[c_reg].astype(str).str.replace(r'[^0-9]', '', regex=True)
        df_cmed['Reg_C'] = df_cmed['REGISTRO'].astype(str).str.replace(r'[^0-9]', '', regex=True)
        df_prop['V_Unit'] = df_prop[c_vlr].apply(formatar_moeda)
        c_apres_cmed = [c for c in df_cmed.columns if 'APRESENTA' in str(c).upper()][0]

        df_m = pd.merge(df_prop, df_cmed[['Reg_C', coluna_icms, c_apres_cmed]], left_on='Reg_L', right_on='Reg_C', how='left')
        df_m['PF_Num'] = df_m[coluna_icms].apply(formatar_moeda)
        
        # CÁLCULO DE DIVISOR CMED SEGURO
        df_m['Divisor'] = df_m[c_apres_cmed].apply(extrair_qtd_cmed)
        df_m['Teto_U'] = df_m['PF_Num'] / df_m['Divisor']

        df_precos = df_m[(df_m['V_Unit'] > (df_m['Teto_U'] + 0.0005)) & (df_m['Teto_U'] > 0)].copy()
        df_reg_err = df_m[(df_m['Reg_L'].str.len() > 0) & ((df_m['Reg_L'].str.len() != 13) | (df_m['Reg_C'].isna()))].copy()

        for df in [df_precos, df_reg_err]:
            if not df.empty:
                df['Col_Item'] = df[c_item]; df['Col_Desc'] = df[c_desc]; df['Col_Reg'] = df[c_reg]
                if 'Teto_U' in df.columns: df['Diferenca'] = df['V_Unit'] - df['Teto_U']

        return df_precos, df_reg_err, cabecalho_info, None
    except Exception as e:
        return None, None, None, f"Erro: {str(e)}"

# --- INTERFACE ---
df_cmed = carregar_cmed()
with st.sidebar:
    logo_b64 = get_image_base64("logo.png") or get_image_base64("logo_drogafonte.png")
    if logo_b64:
        st.markdown(f'<img src="data:image/png;base64,{logo_b64}" width="200">', unsafe_allow_html=True)
    else:
        st.image("https://drogafonte.com.br/wp-content/uploads/2021/10/logo-drogafonte.png", width=200)
    
    st.divider()
    aliquota = st.selectbox("ICMS Destino:", ["PF 12%", "PF 17%", "PF 17,5%", "PF 18%", "PF 19%", "PF 19,5%", "PF 20%", "PF 20,5%", "PF 21%", "PF 22%"], index=7)

st.title("🛡️ Validador CMED - Drogafonte")

if not st.session_state.tela_resultado:
    upload = st.file_uploader("Arraste a Proposta", type=['xls', 'xlsx', 'csv'])
    if upload and st.button("🚀 Iniciar Auditoria", use_container_width=True, type="primary"):
        p, r, c, err = processar_dados(upload, df_cmed, aliquota)
        st.session_state.dados_finais, st.session_state.erros_registro, st.session_state.cabecalho_pdf, st.session_state.erro, st.session_state.aliquota = p, r, c, err, aliquota
        st.session_state.tela_resultado = True
        st.rerun()
else:
    st.button("⬅️ Nova Análise", on_click=resetar_app)
    
    if st.session_state.erro:
        st.error(st.session_state.erro)
    else:
        df_p = st.session_state.dados_finais
        df_r = st.session_state.erros_registro

        st.subheader("🚨 Preços Acima do Teto")
        if df_p.empty: st.success("Tudo OK!")
        else:
            st.dataframe(
                df_p[['Col_Item', 'Col_Desc', 'V_Unit', 'Teto_U', 'Diferenca']].style.format({
                    'V_Unit': '{:.4f}', 
                    'Teto_U': '{:.4f}', 
                    'Diferenca': '{:.4f}'
                }), 
                use_container_width=True
            )

        st.divider()
        st.subheader("⚠️ Alertas de Registro / Notificados")
        if not df_r.empty:
            st.dataframe(df_r[['Col_Item', 'Col_Desc', 'Col_Reg']], use_container_width=True)
        
        # DOWNLOAD EXCEL
        st.download_button("📥 Baixar Auditoria Completa (Excel)", exportar_excel(df_p, df_r), "Auditoria_Drogafonte.xlsx")

        # GERADOR DE PDF UNIFICADO
        if st.button("📄 Gerar Relatório PDF Final", type="primary", use_container_width=True):
            pdf = FPDF(orientation='L', unit='mm', format='A4')
            
            # PÁGINA 1: DIVERGÊNCIAS
            if not df_p.empty:
                pdf.add_page()
                pdf.set_font("Arial", 'B', 14); pdf.set_text_color(180, 0, 0)
                pdf.cell(0, 10, f"DIVERGENCIAS DE PRECO - {st.session_state.aliquota}", ln=True, align='C')
                pdf.ln(5)
                pdf.set_font("Arial", 'B', 8); pdf.set_text_color(0); pdf.set_fill_color(230, 230, 230)
                pdf.cell(15, 8, "Item", 1, 0, 'C', True); pdf.cell(160, 8, "Descricao", 1, 0, 'C', True)
                pdf.cell(30, 8, "Proposta", 1, 0, 'C', True); pdf.cell(30, 8, "Teto", 1, 0, 'C', True); pdf.cell(30, 8, "Dif.", 1, 1, 'C', True)
                
                pdf.set_font("Arial", '', 8)
                for _, row in df_p.iterrows():
                    pdf.cell(15, 7, str(row['Col_Item']), 1, 0, 'C')
                    pdf.cell(160, 7, str(row['Col_Desc'])[:95].encode('latin-1', 'replace').decode('latin-1'), 1)
                    pdf.cell(30, 7, f"{row['V_Unit']:.4f}", 1, 0, 'C')
                    pdf.cell(30, 7, f"{row['Teto_U']:.4f}", 1, 0, 'C')
                    pdf.cell(30, 7, f"{row['Diferenca']:.4f}", 1, 1, 'C')

            # PÁGINA 2: ALERTAS DE REGISTRO
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
