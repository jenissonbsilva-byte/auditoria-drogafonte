import streamlit as st
import pandas as pd
from fpdf import FPDF
import io
import re
import os

# Configuração da Página
st.set_page_config(page_title="Auditoria Drogafonte - CMED", layout="wide", page_icon="🛡️")

# --- DICIONÁRIO DE ALÍQUOTAS ---
ESTADOS_ICMS = {
    "ACRE (19%)": "PF 19%", "ALAGOAS (19%)": "PF 19%", "AMAPÁ (18%)": "PF 18%",
    "AMAZONAS (20%)": "PF 20%", "BAHIA (20,5%)": "PF 20,5%", "CEARÁ (20%)": "PF 20%",
    "DISTRITO FEDERAL (17%)": "PF 17%", "ESPÍRITO SANTO (17%)": "PF 17%",
    "GOIÁS (19%)": "PF 19%", "MARANHÃO (22%)": "PF 22%", "MATO GROSSO (17%)": "PF 17%",
    "MATO GROSSO DO SUL (17%)": "PF 17%", "MINAS GERAIS (18%)": "PF 18%",
    "MINAS GERAIS - GENÉRICOS (12%)": "PF 12%", "PARÁ (19%)": "PF 19%",
    "PARAÍBA (20%)": "PF 20%", "PARANÁ (19,5%)": "PF 19,5%", "PERNAMBUCO (20,5%)": "PF 20,5%",
    "PIAUÍ (22%)": "PF 22%", "RIO DE JANEIRO (22%)": "PF 22%", "RIO GRANDE DO NORTE (20%)": "PF 20%",
    "RIO GRANDE DO SUL (17%)": "PF 17%", "RONDÔNIA (19,5%)": "PF 19,5%",
    "RORAIMA (20%)": "PF 20%", "SANTA CATARINA (17%)": "PF 17%", "SÃO PAULO (18%)": "PF 18%",
    "SÃO PAULO - GENÉRICOS (12%)": "PF 12%", "SERGIPE (19%)": "PF 19%", "TOCANTINS (20%)": "PF 20%"
}

# --- FUNÇÕES DE APOIO ---
def limpar_registro(reg):
    if pd.isna(reg) or str(reg).strip().upper() in ['NAN', 'NONE', '']: return ""
    s = str(reg).strip()
    if s.endswith('.0'): s = s[:-2]
    return re.sub(r'[^0-9]', '', s)

def formatar_moeda(val):
    if pd.isna(val) or str(val).strip() == '': return 0.0
    v = str(val).replace('R$', '').strip()
    if '.' in v and ',' in v: v = v.replace('.', '')
    v = v.replace(',', '.')
    try: return float(v)
    except: return 0.0

def extrair_qtd_cmed(apres_cmed, desc_proposta):
    apres = str(apres_cmed).upper()
    desc = str(desc_proposta).upper()
    if re.search(r'\b(DOSES?|AEROSSOL|SPRAY|JATOS?|INALADOR)\b', apres) or re.search(r'\b(DOSES?|AEROSSOL|SPRAY|JATOS?|INALADOR)\b', desc):
        return 1
    unidades_ignoradas = r'(?:ML|MG|G|MCG|UI|%|L|KG|GOTAS|MM|CM)'
    m = re.search(rf'\b(\d+)\s+(?:BL|ENV|STRIP|CPR|CAP|AMP|FA|FR|SER|TB|BS|CJ|SVD).*?X\s+(\d+)\b(?!\s*[,.]\s*\d+)(?!\s*{unidades_ignoradas})', apres)
    if m: return float(m.group(1)) * float(m.group(2))
    m = re.search(r'\b(\d+)\s+(?:AMP|FA|FR|SER|TB|BS|CJ|BOLS|CARP|TUB|CX|CT|BL|CPR|CAP|UN)\b', apres)
    if m: return float(m.group(1))
    m = re.search(rf'X\s+(\d+)\b(?!\s*[,.]\s*\d+)(?!\s*{unidades_ignoradas})', apres)
    if m: return float(m.group(1))
    m = re.search(r'(?:C/|CT|CX|COM|CONTEM)\s*(\d+)\b', apres)
    if m: return float(m.group(1))
    return 1

# --- PROCESSAMENTO ---
def processar_dados(file_proposta, df_cmed, coluna_icms):
    try:
        df_raw = pd.read_excel(file_proposta, header=None)
        linha_cab = 0
        for i, row in df_raw.iterrows():
            if row.astype(str).str.contains('Reg.M.S|Vlr. Unit.', case=False).any():
                linha_cab = i
                break
        
        # Captura o cabeçalho da proposta (informações acima da tabela)
        cabecalho_info = []
        for j in range(linha_cab):
            texto = " ".join(df_raw.iloc[j].dropna().astype(str).tolist()).strip()
            if texto: cabecalho_info.append(texto)

        df_prop = df_raw.iloc[linha_cab+1:].copy()
        df_prop.columns = df_raw.iloc[linha_cab].astype(str).str.strip()
        
        # Mapeamento dinâmico de colunas
        c_desc = [c for c in df_prop.columns if any(x in str(c) for x in ['D i s c', 'Nome Com', 'Descrição'])][0]
        c_reg = [c for c in df_prop.columns if 'REG.M.S' in str(c).upper().replace(' ', '') or 'REGISTRO' in str(c).upper()][0]
        c_vlr = [c for c in df_prop.columns if 'VLR' in str(c).upper() and 'UNIT' in str(c).upper()][0]
        c_item = [c for c in df_prop.columns if 'ITEM' in str(c).upper()][0]
        c_marca = [c for c in df_prop.columns if any(x in str(c).upper() for x in ['MARCA', 'FABRICANTE'])][0]

        df_prop['Reg_L'] = df_prop[c_reg].apply(limpar_registro)
        df_cmed['Reg_C'] = df_cmed['REGISTRO'].apply(limpar_registro)
        df_prop['V_Unit'] = df_prop[c_vlr].apply(formatar_moeda)
        c_apres_cmed = [c for c in df_cmed.columns if 'APRESENTA' in str(c).upper()][0]

        df_m = pd.merge(df_prop, df_cmed[['Reg_C', coluna_icms, c_apres_cmed]], left_on='Reg_L', right_on='Reg_C', how='left')
        df_m['PF_Num'] = df_m[coluna_icms].apply(formatar_moeda)
        df_m['Divisor'] = df_m.apply(lambda row: extrair_qtd_cmed(row[c_apres_cmed], row[c_desc]), axis=1)
        df_m['Teto_U'] = df_m['PF_Num'] / df_m['Divisor']
        df_m['Diferenca'] = df_m['V_Unit'] - df_m['Teto_U']
        
        df_m['Col_Item'] = df_m[c_item]
        df_m['Col_Desc'] = df_m[c_desc]
        df_m['Col_Marca'] = df_m[c_marca]
        df_m['Col_Reg'] = df_m[c_reg]
        df_m['Status'] = df_m.apply(lambda x: '🔴 Acima' if x['Diferenca'] > 0.0005 else '🟢 Ok', axis=1)

        df_valido = df_m[df_m['Col_Desc'].notna()].copy()
        df_precos = df_valido[(df_valido['Diferenca'] > 0.0005) & (df_valido['Teto_U'] > 0)].copy()
        
        cond_alerta = (df_valido['Col_Reg'].astype(str).str.upper().str.contains(r'NOTIFICADO|RDC', na=False) | 
                       (df_valido['Reg_L'].str.len() != 13) | (df_valido['Reg_C'].isna()))
        df_reg_err = df_valido[cond_alerta].copy()

        return df_valido, df_precos, df_reg_err, cabecalho_info, None
    except Exception as e:
        return None, None, None, None, f"Erro: {str(e)}"

# --- INTERFACE ---
df_cmed = pd.read_excel('cmed_atual.xlsx', skiprows=54) # Exemplo de skip dependendo da sua planilha

with st.sidebar:
    st.image("https://drogafonte.com.br/wp-content/uploads/2021/10/logo-drogafonte.png", width=180)
    estado = st.selectbox("Estado:", list(ESTADOS_ICMS.keys()), index=17) # PE Default
    aliquota = ESTADOS_ICMS[estado]

st.title("🛡️ Auditoria Drogafonte")

upload = st.file_uploader("Upload da Proposta", type=['xls', 'xlsx'])

if upload:
    if st.button("Analisar"):
        t, p, r, c, err = processar_dados(upload, df_cmed, aliquota)
        if err: st.error(err)
        else:
            st.session_state.dados = (t, p, r, c, estado)
            st.success("Análise concluída!")

if 'dados' in st.session_state:
    t, p, r, c, est_nome = st.session_state.dados
    
    tab1, tab2 = st.tabs(["🔴 Divergências", "⚠️ Alertas"])
    
    with tab1:
        st.dataframe(p[['Col_Item', 'Col_Desc', 'Col_Marca', 'V_Unit', 'Teto_U', 'Diferenca']], use_container_width=True)
    
    with tab2:
        st.dataframe(r[['Col_Item', 'Col_Desc', 'Col_Reg']], use_container_width=True)

    # --- GERAÇÃO DO PDF ---
    if st.button("Gerar PDF"):
        pdf = FPDF(orientation='L', unit='mm', format='A4')
        pdf.add_page()
        
        # Logo no Canto Superior Direito
        try:
            pdf.image("https://drogafonte.com.br/wp-content/uploads/2021/10/logo-drogafonte.png", x=245, y=8, w=35)
        except: pass
        
        # Título e Cabeçalho da Proposta
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(0, 8, "RELATÓRIO DE AUDITORIA CMED", ln=True)
        pdf.set_font("Arial", '', 9)
        pdf.cell(0, 5, f"Estado de Destino: {est_nome}", ln=True)
        pdf.ln(2)
        
        # Bloco de Identificação (O "Modelo" solicitado)
        pdf.set_fill_color(245, 245, 245)
        pdf.set_font("Arial", 'B', 8)
        pdf.cell(0, 5, "DADOS DA PROPOSTA:", ln=True, fill=True)
        pdf.set_font("Arial", '', 8)
        for info in c: # c contém as linhas do cabeçalho da proposta
            pdf.cell(0, 4, info.encode('latin-1', 'replace').decode('latin-1'), ln=True)
        pdf.ln(5)

        # Tabela de Divergências
        if not p.empty:
            pdf.set_font("Arial", 'B', 8)
            pdf.set_fill_color(200, 0, 0); pdf.set_text_color(255, 255, 255)
            pdf.cell(10, 7, "Item", 1, 0, 'C', True)
            pdf.cell(110, 7, "Descricao", 1, 0, 'C', True)
            pdf.cell(50, 7, "Marca/Fabricante", 1, 0, 'C', True)
            pdf.cell(25, 7, "Vlr. Prop", 1, 0, 'C', True)
            pdf.cell(25, 7, "Vlr. Teto", 1, 0, 'C', True)
            pdf.cell(25, 7, "Dif.", 1, 1, 'C', True)
            
            pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", '', 7)
            for _, row in p.iterrows():
                # Altura dinâmica para descrições longas
                h = 6
                pdf.cell(10, h, str(row['Col_Item']), 1, 0, 'C')
                pdf.cell(110, h, str(row['Col_Desc'])[:75].encode('latin-1', 'replace').decode('latin-1'), 1)
                pdf.cell(50, h, str(row['Col_Marca'])[:30].encode('latin-1', 'replace').decode('latin-1'), 1)
                pdf.cell(25, h, f"{row['V_Unit']:.4f}", 1, 0, 'R')
                pdf.cell(25, h, f"{row['Teto_U']:.4f}", 1, 0, 'R')
                pdf.cell(25, h, f"{row['Diferenca']:.4f}", 1, 1, 'R')
        
        st.download_button("📥 Baixar PDF", pdf.output(dest='S').encode('latin-1'), "Auditoria_Drogafonte.pdf")
