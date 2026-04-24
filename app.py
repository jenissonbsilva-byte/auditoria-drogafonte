import streamlit as st
import pandas as pd
from fpdf import FPDF
import io
import re
import os

st.set_page_config(page_title="Auditoria Drogafonte - CMED", layout="wide")

if 'tela_resultado' not in st.session_state:
    st.session_state.tela_resultado = False

def resetar_app():
    st.session_state.tela_resultado = False
    for key in ['dados_finais', 'erros_registro', 'cabecalho_pdf', 'erro', 'nome_arquivo']:
        if key in st.session_state:
            del st.session_state[key]

# --- MOTORES LÓGICOS ---
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

def formatar_moeda(val):
    v = str(val).replace('R$', '').strip()
    if pd.isna(val) or v.lower() == 'nan' or v == '': return 0.0
    if '.' in v and ',' in v: v = v.replace('.', '')
    v = v.replace(',', '.')
    try: return float(v)
    except: return 0.0

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
        df_raw = pd.read_excel('cmed_atual.xlsx', header=None)
        for i, r in df_raw.iterrows():
            if r.astype(str).str.contains('REGISTRO').any():
                df = pd.read_excel('cmed_atual.xlsx', skiprows=i)
                df.columns = df.columns.astype(str).str.replace(' %', '%').str.strip()
                return df
    return None

def processar_dados(file_proposta, df_cmed, coluna_icms):
    try:
        df_raw = ler_proposta_robusto(file_proposta)
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

        # Limpeza e Cruzamento
        df_prop['Reg_L'] = df_prop[c_reg].astype(str).str.replace(r'[^0-9]', '', regex=True)
        df_cmed['Reg_C'] = df_cmed['REGISTRO'].astype(str).str.replace(r'[^0-9]', '', regex=True)
        
        df_prop['V_Unit'] = df_prop[c_vlr].apply(formatar_moeda)
        c_apres_cmed = [c for c in df_cmed.columns if 'APRESENTA' in str(c).upper()][0]

        df_m = pd.merge(df_prop, df_cmed[['Reg_C', coluna_icms, c_apres_cmed]], left_on='Reg_L', right_on='Reg_C', how='left')
        
        df_m['PF_Num'] = df_m[coluna_icms].apply(formatar_moeda)
        df_m['Qtd_C'] = df_m[c_apres_cmed].apply(extrair_qtd_cmed).fillna(1)
        df_m['Qtd_C'] = df_m['Qtd_C'].apply(lambda x: 1 if x == 0 else x)
        df_m['Teto_U'] = df_m['PF_Num'] / df_m['Qtd_C']

        # --- LÓGICA DE FILTRAGEM (SOLICITADA) ---
        
        # 1. ERROS DE PREÇO (Somente se o Teto for > 0)
        df_precos = df_m[(df_m['V_Unit'] > (df_m['Teto_U'] + 0.0001)) & (df_m['Teto_U'] > 0)].copy()
        
        # 2. ERROS DE REGISTRO (13 dígitos ou não encontrado)
        # Filtramos o que não é Notificado (se tem algo escrito no campo Reg MS mas não bate 13 dígitos)
        df_reg_err = df_m[
            (df_m['Reg_L'].str.len() > 0) & 
            ((df_m['Reg_L'].str.len() != 13) | (df_m['Reg_C'].isna()))
        ].copy()

        # Preparar colunas para exibição
        for df in [df_precos, df_reg_err]:
            if not df.empty:
                df['Col_Item'] = df[c_item]
                df['Col_Desc'] = df[c_desc]
                df['Col_Reg'] = df[c_reg]

        return df_precos, df_reg_err, cabecalho_info, None

    except Exception as e:
        return None, None, None, f"Erro: {str(e)}"

# --- INTERFACE ---
df_cmed = carregar_cmed()

with st.sidebar:
    st.image("https://drogafonte.com.br/wp-content/uploads/2021/10/logo-drogafonte.png", width=200)
    escolha_icms = st.selectbox("Alíquota ICMS:", ["PF 12%", "PF 17%", "PF 17,5%", "PF 18%", "PF 19%", "PF 19,5%", "PF 20%", "PF 20,5%", "PF 21%", "PF 22%"], index=7)
    if df_cmed is not None: st.success("✅ Base CMED Ativa")

st.title("🛡️ Auditoria Drogafonte - Validador CMED")

if not st.session_state.tela_resultado:
    upload_prop = st.file_uploader("Anexe a Proposta", type=['xls', 'xlsx', 'csv'])
    if upload_prop and st.button("▶️ Processar Arquivo", use_container_width=True, type="primary"):
        res_precos, res_reg, cab, erro = processar_dados(upload_prop, df_cmed, escolha_icms)
        st.session_state.dados_finais = res_precos
        st.session_state.erros_registro = res_reg
        st.session_state.cabecalho_pdf = cab
        st.session_state.erro = erro
        st.session_state.tela_resultado = True
        st.rerun()
else:
    st.button("🔄 Limpar e Nova Análise", on_click=resetar_app, use_container_width=True)
    
    if st.session_state.erro:
        st.error(st.session_state.erro)
    else:
        df_p = st.session_state.dados_finais
        df_r = st.session_state.erros_registro
        
        # TABELA 1: DIVERGÊNCIAS DE PREÇO
        st.subheader("🚨 Divergências de Preço (Acima do Teto)")
        if df_p.empty:
            st.success("Nenhum preço acima do teto encontrado.")
        else:
            exib_p = df_p[['Col_Item', 'Col_Desc', 'V_Unit', 'Teto_U']].copy()
            exib_p.columns = ['Item', 'Descrição', 'Preço Unit.', 'Teto CMED']
            st.dataframe(exib_p.style.format({'Preço Unit.': 'R$ {:.4f}', 'Teto CMED': 'R$ {:.4f}'}), use_container_width=True)

        # TABELA 2: ERROS DE REGISTRO
        st.subheader("⚠️ Alertas de Registro (Inválidos ou Não Encontrados)")
        if df_r.empty:
            st.info("Todos os registros MS são válidos e foram encontrados.")
        else:
            exib_r = df_r[['Col_Item', 'Col_Desc', 'Col_Reg']].copy()
            exib_r['Motivo'] = df_r.apply(lambda x: "Fora do padrão (13 dígitos)" if len(str(x['Reg_L'])) != 13 else "Não encontrado na CMED", axis=1)
            exib_r.columns = ['Item', 'Descrição', 'Registro na Proposta', 'Diagnóstico']
            st.warning("Estes itens abaixo podem ser Notificados/RDC ou estar com erro de digitação no Registro MS.")
            st.dataframe(exib_r, use_container_width=True)

        # BOTÃO PDF (Inclui apenas os erros de preço para o relatório oficial)
        if not df_p.empty and st.button("📥 Gerar PDF de Divergências"):
            pdf = FPDF(orientation='L', unit='mm', format='A4')
            pdf.add_page()
            pdf.set_font("Arial", 'B', 10)
            for linha in st.session_state.cabecalho_pdf[:5]:
                pdf.cell(0, 5, str(linha).encode('latin-1', 'replace').decode('latin-1'), ln=True)
            pdf.ln(10)
            pdf.set_font("Arial", 'B', 14); pdf.set_text_color(200, 0, 0)
            pdf.cell(0, 10, f"RELATÓRIO DE DIVERGÊNCIAS - {escolha_icms}", ln=True, align='C')
            pdf.ln(5)
            # Cabeçalho Tabela PDF
            pdf.set_font("Arial", 'B', 8); pdf.set_text_color(0); pdf.set_fill_color(240, 240, 240)
            pdf.cell(15, 8, "Item", 1, 0, 'C', True)
            pdf.cell(140, 8, "Descricao", 1, 0, 'C', True)
            pdf.cell(30, 8, "Proposta", 1, 0, 'C', True)
            pdf.cell(30, 8, "Teto", 1, 0, 'C', True)
            pdf.cell(30, 8, "Dif.", 1, 1, 'C', True)
            
            pdf.set_font("Arial", '', 8)
            for _, r in df_p.iterrows():
                pdf.cell(15, 7, str(r['Col_Item']), 1, 0, 'C')
                pdf.cell(140, 7, str(r['Col_Desc'])[:80].encode('latin-1', 'replace').decode('latin-1'), 1)
                pdf.cell(30, 7, f"R$ {r['V_Unit']:.4f}", 1, 0, 'C')
                pdf.cell(30, 7, f"R$ {r['Teto_U']:.4f}", 1, 0, 'C')
                pdf.set_text_color(200,0,0)
                pdf.cell(30, 7, f"R$ {(r['V_Unit']-r['Teto_U']):.4f}", 1, 1, 'C')
                pdf.set_text_color(0)

            st.download_button("Clique para Salvar o PDF", pdf.output(dest='S').encode('latin-1'), "Relatorio_Auditoria.pdf", "application/pdf")
