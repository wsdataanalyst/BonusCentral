"""
DASHBOARD DE VENDAS - ANALISADOR DE PRINTS
Sistema com acesso exclusivo para um usuário
"""

import subprocess, sys, os, hashlib, sqlite3, json, re
from datetime import datetime
from io import BytesIO

# Instala bibliotecas automaticamente se não tiver
try:
    import streamlit as st
    import pandas as pd
    import plotly.graph_objects as go
    import google.generativeai as genai
    import PIL.Image
    from dotenv import load_dotenv
except ModuleNotFoundError as e:
    print(f"Instalando bibliotecas... {e}")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "streamlit", "pandas", "plotly", "google-generativeai", "Pillow", "python-dotenv"])
    import streamlit as st
    import pandas as pd
    import plotly.graph_objects as go
    import google.generativeai as genai
    import PIL.Image
    from dotenv import load_dotenv

# Carrega variáveis de ambiente
load_dotenv()

# Configura API do Gemini
api_key = os.getenv("GOOGLE_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

# ============================================
# CREDENCIAIS DO USUÁRIO (APENAS VOCÊ)
# ============================================
USUARIO_AUTORIZADO = "wsdataanalyst"
SENHA_AUTORIZADA = "#P161217m"

# ============================================
# BANCO DE DADOS
# ============================================

DB_PATH = "vendas.db"

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_database():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Recria a tabela analises (sem usuario_id)
    cursor.execute('DROP TABLE IF EXISTS analises')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS analises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            periodo TEXT NOT NULL,
            data_analise TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            dados_json TEXT NOT NULL,
            total_bonus REAL
        )
    ''')
    
    conn.commit()
    conn.close()

def salvar_analise(periodo, dados_json, total_bonus):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO analises (periodo, dados_json, total_bonus) VALUES (?, ?, ?)",
        (periodo, dados_json, total_bonus)
    )
    conn.commit()
    analise_id = cursor.lastrowid
    conn.close()
    return analise_id

def get_analises():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, periodo, data_analise, dados_json, total_bonus FROM analises ORDER BY data_analise DESC"
    )
    analises = cursor.fetchall()
    conn.close()
    
    result = []
    for a in analises:
        result.append({
            'id': a[0],
            'periodo': a[1],
            'data_analise': a[2],
            'dados_json': a[3],
            'total_bonus': a[4]
        })
    return result

def deletar_analise(analise_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM analises WHERE id = ?", (analise_id,))
    conn.commit()
    conn.close()

# ============================================
# FUNÇÕES UTILITÁRIAS
# ============================================

def calcular_estatisticas_time(vendedores):
    if not vendedores:
        return {}
    
    stats = {
        'media_margem': round(sum(v['margem_pct'] for v in vendedores) / len(vendedores), 1),
        'media_alcance': round(sum(v['alcance_projetado_pct'] for v in vendedores) / len(vendedores), 1),
        'media_prazo': round(sum(v['prazo_medio'] for v in vendedores) / len(vendedores), 0),
        'media_conversao': round(sum(v['conversao_calculada'] for v in vendedores) / len(vendedores), 1),
        'media_tme': round(sum(v['tme_minutos'] for v in vendedores) / len(vendedores), 1),
        'media_interacoes': round(sum(v['interacoes'] for v in vendedores) / len(vendedores), 0),
        'total_faturas': sum(v['qtd_faturadas'] for v in vendedores),
        'total_interacoes': sum(v['interacoes'] for v in vendedores),
        'total_bonus': sum(v['bonus_total'] for v in vendedores),
        'qtd_elegiveis': sum(1 for v in vendedores if v.get('elegivel_margem', False)),
        'acima_meta_margem': sum(1 for v in vendedores if v['margem_pct'] >= 26),
        'acima_meta_conversao': sum(1 for v in vendedores if v['conversao_calculada'] >= 12),
        'acima_meta_prazo': sum(1 for v in vendedores if v['prazo_medio'] <= 43 and v['prazo_medio'] > 0),
        'acima_meta_tme': sum(1 for v in vendedores if v['tme_minutos'] <= 5 and v['tme_minutos'] > 0),
        'acima_meta_interacoes': sum(1 for v in vendedores if v['interacoes'] >= 200)
    }
    return stats

def serializar_analise(vendedores, periodo):
    return json.dumps({
        'periodo': periodo,
        'data': datetime.now().isoformat(),
        'vendedores': vendedores
    }, ensure_ascii=False)

def desserializar_analise(dados_json):
    return json.loads(dados_json)

# ============================================
# LISTA DE VENDEDORES
# ============================================

VENDEDORES_VALIDOS = [
    "Gerson Lima",
    "Wesley Cavalcante",
    "Antonio Lima",
    "Cinthya Amaro",
    "Sara Dian",
    "Deborah Miriam",
    "Yago Silva"
]

MAPEAMENTO_NOMES = {
    "gerson moreira de lima": "Gerson Lima",
    "gerson lima": "Gerson Lima",
    "joao wesley souza cavalcante": "Wesley Cavalcante",
    "wesley cavalcante": "Wesley Cavalcante",
    "antonio ediones de lima": "Antonio Lima",
    "antonio lima": "Antonio Lima",
    "cinthya amaro de oliveira": "Cinthya Amaro",
    "cinthya amaro": "Cinthya Amaro",
    "sara dian araujo da silva santos": "Sara Dian",
    "sara dian": "Sara Dian",
    "deborah mirian barbosa braz": "Deborah Miriam",
    "deborah miriam": "Deborah Miriam",
    "yago silva costa": "Yago Silva",
    "yago silva": "Yago Silva"
}

def padronizar_nome(nome):
    if not nome:
        return None
    nome_lower = nome.lower().strip()
    for chave, valor in MAPEAMENTO_NOMES.items():
        if chave in nome_lower or nome_lower == chave:
            return valor
    return nome

# ============================================
# FUNÇÕES DA IA
# ============================================

def get_modelo_disponivel():
    try:
        modelos = list(genai.list_models())
        for modelo in modelos:
            if 'generateContent' in modelo.supported_generation_methods:
                return genai.GenerativeModel(modelo.name)
    except Exception as e:
        st.error(f"Erro ao conectar com Gemini: {e}")
        return None
    return None

def calcular_bonus(vendedor):
    bonus_total = 0
    detalhes = []
    
    margem = vendedor.get('margem_pct', 0) or 0
    alcance = vendedor.get('alcance_projetado_pct', 0) or 0
    prazo = vendedor.get('prazo_medio', 999) or 999
    tme = vendedor.get('tme_minutos', 999) or 999
    interacoes = vendedor.get('interacoes', 0) or 0
    conversao = vendedor.get('conversao_calculada', 0) or 0
    
    # Margem (precisa dos dois: margem >= 26% E alcance >= 90%)
    if margem >= 26 and alcance >= 90:
        bonus_total += 150
        detalhes.append("✅ Margem: R$ 150 (Meta atingida com Alcance ≥ 90%)")
    else:
        motivo = []
        if margem < 26:
            motivo.append(f"Margem {margem:.1f}% < 26%")
        if alcance < 90:
            motivo.append(f"Alcance {alcance:.1f}% < 90%")
        if not motivo:
            motivo.append("Dados não disponíveis")
        detalhes.append(f"❌ Margem: R$ 0 ({' e '.join(motivo)})")
    
    # Prazo Médio
    if prazo <= 43:
        bonus_total += 100
        detalhes.append(f"✅ Prazo Médio: R$ 100 ({prazo:.0f} dias ≤ 43)")
    else:
        detalhes.append(f"❌ Prazo Médio: R$ 0 ({prazo:.0f} dias > 43)")
    
    # Conversão
    if conversao >= 12:
        bonus_total += 100
        detalhes.append(f"✅ Conversão: R$ 100 ({conversao:.1f}% ≥ 12%)")
    else:
        detalhes.append(f"❌ Conversão: R$ 0 ({conversao:.1f}% < 12%)")
    
    # TME
    if tme <= 5:
        bonus_total += 150
        detalhes.append(f"✅ TME: R$ 150 ({tme:.1f} min ≤ 5)")
    else:
        detalhes.append(f"❌ TME: R$ 0 ({tme:.1f} min > 5)")
    
    # Interações
    if interacoes >= 200:
        bonus_total += 100
        detalhes.append(f"✅ Interações: R$ 100 ({interacoes:.0f} ≥ 200)")
    else:
        detalhes.append(f"❌ Interações: R$ 0 ({interacoes:.0f} < 200)")
    
    return bonus_total, detalhes

def analisar_prints_com_gemini(imagens_bytes):
    PROMPT = """
    Analise as imagens dos painéis de vendas e extraia os dados no seguinte formato JSON:
    
    {
        "periodo": "Mês/Ano ou período identificado",
        "vendedores": [
            {
                "nome": "nome completo do vendedor",
                "margem_pct": 0.0,
                "alcance_projetado_pct": 0.0,
                "prazo_medio": 0,
                "qtd_faturadas": 0,
                "chamadas": 0,
                "tme_minutos": 0.0,
                "iniciados": 0,
                "recebidos": 0
            }
        ]
    }
    
    Retorne APENAS o JSON, sem markdown.
    Se algum dado não estiver disponível, use null.
    """
    
    try:
        modelo = get_modelo_disponivel()
        if not modelo:
            return None
        
        imagens_pil = []
        for img_bytes in imagens_bytes:
            img = PIL.Image.open(BytesIO(img_bytes))
            imagens_pil.append(img)
        
        resposta = modelo.generate_content([PROMPT] + imagens_pil)
        texto = resposta.text
        texto = re.sub(r'^```(?:json)?\s*|\s*```$', '', texto.strip())
        return json.loads(texto)
    except Exception as e:
        st.error(f"Erro na análise: {e}")
        return None

def processar_dados_vendedores(dados_extraidos):
    vendedores_processados = []
    todos_vendedores = dados_extraidos.get('vendedores', [])
    
    for v in todos_vendedores:
        nome_original = v.get('nome', 'Desconhecido')
        nome_padronizado = padronizar_nome(nome_original)
        
        if nome_padronizado not in VENDEDORES_VALIDOS:
            continue
        
        # Valores com formatação correta (1 casa decimal para percentuais)
        chamadas = float(v.get('chamadas', 0) or 0)
        iniciados = float(v.get('iniciados', 0) or 0)
        recebidos = float(v.get('recebidos', 0) or 0)
        interacoes = chamadas + iniciados + recebidos
        
        qtd_faturadas = float(v.get('qtd_faturadas', 0) or 0)
        if interacoes > 0 and qtd_faturadas > 0:
            conversao = round((qtd_faturadas / interacoes) * 100, 1)
        else:
            conversao = 0.0
        
        margem = round(v.get('margem_pct', 0) or 0, 1)
        alcance = round(v.get('alcance_projetado_pct', 0) or 0, 1)
        prazo = round(v.get('prazo_medio', 0) or 0, 0)
        tme = round(v.get('tme_minutos', 0) or 0, 1)
        
        elegivel_margem = margem >= 26 and alcance >= 90
        
        vendedor = {
            'nome': nome_padronizado,
            'margem_pct': margem,
            'alcance_projetado_pct': alcance,
            'prazo_medio': prazo,
            'qtd_faturadas': qtd_faturadas,
            'chamadas': chamadas,
            'iniciados': iniciados,
            'recebidos': recebidos,
            'interacoes': interacoes,
            'conversao_calculada': conversao,
            'tme_minutos': tme,
            'elegivel_margem': elegivel_margem
        }
        
        bonus, detalhes = calcular_bonus(vendedor)
        vendedor['bonus_total'] = bonus
        vendedor['detalhes_bonus'] = detalhes
        vendedores_processados.append(vendedor)
    
    # Adiciona vendedores não encontrados
    nomes_encontrados = [v['nome'] for v in vendedores_processados]
    for nome in VENDEDORES_VALIDOS:
        if nome not in nomes_encontrados:
            vendedores_processados.append({
                'nome': nome,
                'margem_pct': 0.0,
                'alcance_projetado_pct': 0.0,
                'prazo_medio': 0,
                'qtd_faturadas': 0,
                'chamadas': 0,
                'iniciados': 0,
                'recebidos': 0,
                'interacoes': 0,
                'conversao_calculada': 0.0,
                'tme_minutos': 0.0,
                'elegivel_margem': False,
                'bonus_total': 0,
                'detalhes_bonus': ["⚠️ Dados não encontrados nos prints"]
            })
    
    return vendedores_processados

def editar_dados_manual(vendedores):
    st.markdown("### ✏️ Edição Manual de Dados")
    st.markdown("Caso algum dado não tenha sido extraído corretamente, você pode ajustá-lo manualmente:")
    
    vendedores_editados = []
    
    for i, v in enumerate(vendedores):
        with st.expander(f"✏️ {v['nome']} - Editar dados"):
            col1, col2 = st.columns(2)
            
            with col1:
                # Garantindo que os valores são float com 1 casa decimal
                margem_valor = float(v['margem_pct']) if isinstance(v['margem_pct'], (int, float)) else 0.0
                alcance_valor = float(v['alcance_projetado_pct']) if isinstance(v['alcance_projetado_pct'], (int, float)) else 0.0
                prazo_valor = float(v['prazo_medio']) if isinstance(v['prazo_medio'], (int, float)) else 0.0
                tme_valor = float(v['tme_minutos']) if isinstance(v['tme_minutos'], (int, float)) else 0.0
                
                # Limitar TME a 60
                if tme_valor > 60:
                    tme_valor = 5.0
                
                novo_margem = st.number_input(
                    "Margem (%)", 
                    min_value=0.0, 
                    max_value=100.0, 
                    value=margem_valor, 
                    step=0.1, 
                    format="%.1f",
                    key=f"margem_{i}"
                )
                novo_alcance = st.number_input(
                    "Alcance (%)", 
                    min_value=0.0, 
                    max_value=300.0, 
                    value=alcance_valor, 
                    step=0.1, 
                    format="%.1f",
                    key=f"alcance_{i}"
                )
                novo_prazo = st.number_input(
                    "Prazo (dias)", 
                    min_value=0, 
                    max_value=200, 
                    value=int(prazo_valor), 
                    step=1,
                    key=f"prazo_{i}"
                )
                novo_tme = st.number_input(
                    "TME (min)", 
                    min_value=0.0, 
                    max_value=60.0, 
                    value=tme_valor, 
                    step=0.1, 
                    format="%.1f",
                    key=f"tme_{i}"
                )
            
            with col2:
                qtd_valor = float(v['qtd_faturadas']) if isinstance(v['qtd_faturadas'], (int, float)) else 0.0
                chamadas_valor = float(v.get('chamadas', 0)) if isinstance(v.get('chamadas', 0), (int, float)) else 0.0
                iniciados_valor = float(v['iniciados']) if isinstance(v['iniciados'], (int, float)) else 0.0
                recebidos_valor = float(v['recebidos']) if isinstance(v['recebidos'], (int, float)) else 0.0
                
                novo_qtd = st.number_input(
                    "Qtd Faturadas", 
                    min_value=0, 
                    max_value=1000, 
                    value=int(qtd_valor), 
                    step=1,
                    key=f"qtd_{i}"
                )
                novo_chamadas = st.number_input(
                    "Chamadas", 
                    min_value=0, 
                    max_value=1000, 
                    value=int(chamadas_valor), 
                    step=1,
                    key=f"chamadas_{i}"
                )
                novo_iniciados = st.number_input(
                    "Iniciados", 
                    min_value=0, 
                    max_value=1000, 
                    value=int(iniciados_valor), 
                    step=1,
                    key=f"iniciados_{i}"
                )
                novo_recebidos = st.number_input(
                    "Recebidos", 
                    min_value=0, 
                    max_value=1000, 
                    value=int(recebidos_valor), 
                    step=1,
                    key=f"recebidos_{i}"
                )
            
            # Recalcula interações e conversão
            novas_interacoes = float(novo_chamadas + novo_iniciados + novo_recebidos)
            if novas_interacoes > 0 and novo_qtd > 0:
                nova_conversao = round((novo_qtd / novas_interacoes) * 100, 1)
            else:
                nova_conversao = 0.0
            
            vendedor_editado = {
                'nome': v['nome'],
                'margem_pct': round(novo_margem, 1),
                'alcance_projetado_pct': round(novo_alcance, 1),
                'prazo_medio': novo_prazo,
                'qtd_faturadas': float(novo_qtd),
                'chamadas': float(novo_chamadas),
                'iniciados': float(novo_iniciados),
                'recebidos': float(novo_recebidos),
                'interacoes': novas_interacoes,
                'conversao_calculada': nova_conversao,
                'tme_minutos': round(novo_tme, 1),
                'elegivel_margem': novo_margem >= 26 and novo_alcance >= 90
            }
            
            bonus, detalhes = calcular_bonus(vendedor_editado)
            vendedor_editado['bonus_total'] = bonus
            vendedor_editado['detalhes_bonus'] = detalhes
            
            st.markdown(f"**🔄 Novo bônus calculado: R$ {bonus:,.2f}**")
            vendedores_editados.append(vendedor_editado)
    
    return vendedores_editados

# ============================================
# CSS PERSONALIZADO
# ============================================

st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #0d1a0d, #0a120a);
        padding: 20px 25px;
        border-radius: 12px;
        margin-bottom: 20px;
        border: 1px solid #2d5a2d;
    }
    .main-header h1 { color: #00e676; margin: 0; font-size: 1.8rem; }
    .main-header p { color: #6b8f6b; margin: 5px 0 0 0; }
    .card-metrica {
        background: linear-gradient(135deg, #141824, #0d1117);
        border: 1px solid #2a3040;
        border-radius: 12px;
        padding: 16px;
        text-align: center;
        transition: all 0.2s;
    }
    .card-metrica:hover { border-color: #00e676; transform: translateY(-2px); }
    .bonus-total { font-size: 2rem; font-weight: bold; color: #00e676; }
    .valor-grande { font-size: 1.8rem; font-weight: bold; color: #00e676; }
    .valor-medio { font-size: 1.2rem; font-weight: bold; color: #ffab00; }
    .elegivel-sim {
        background-color: #1a4a2e;
        color: #00e676;
        padding: 4px 12px;
        border-radius: 20px;
        display: inline-block;
        font-weight: bold;
        font-size: 0.8rem;
    }
    .elegivel-nao {
        background-color: #3a1a1a;
        color: #ff5252;
        padding: 4px 12px;
        border-radius: 20px;
        display: inline-block;
        font-weight: bold;
        font-size: 0.8rem;
    }
    .meta-ok { color: #00e676; font-weight: bold; }
    .meta-ruim { color: #ff5252; font-weight: bold; }
    .info-box {
        background: #1a1f2e;
        border-left: 4px solid #00e676;
        padding: 12px 16px;
        border-radius: 8px;
        margin: 10px 0;
    }
    .periodo-box {
        background: #1a2a1a;
        padding: 8px 16px;
        border-radius: 8px;
        display: inline-block;
        margin-bottom: 16px;
    }
    .login-container {
        max-width: 400px;
        margin: 80px auto;
        padding: 30px;
        background: #141824;
        border-radius: 16px;
        border: 1px solid #2a3040;
    }
    .progresso-bar {
        background: #2a3040;
        border-radius: 10px;
        height: 8px;
        margin-top: 8px;
    }
    .progresso-fill {
        background: #00e676;
        border-radius: 10px;
        height: 8px;
        transition: width 0.3s;
    }
    .stButton > button {
        background: linear-gradient(135deg, #00e676, #00b248);
        color: #000;
        font-weight: bold;
        border: none;
        border-radius: 8px;
        padding: 10px 20px;
    }
    .stButton > button:hover {
        background: linear-gradient(135deg, #00b248, #008f3a);
        color: #fff;
    }
    hr {
        border-color: #2a3040;
    }
</style>
""", unsafe_allow_html=True)

# ============================================
# INICIALIZAÇÃO
# ============================================

st.set_page_config(
    page_title="Vendas Analytics | Dashboard",
    page_icon="📊",
    layout="wide"
)

# Recria o banco de dados com a estrutura correta
init_database()

# ============================================
# TELA DE LOGIN (APENAS PARA VOCÊ)
# ============================================

def tela_login():
    st.markdown("""
    <div class="main-header" style="text-align:center">
        <h1>📊 Dashboard de Vendas</h1>
        <p>Sistema de Análise de Bônus e Performance</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown('<div class="login-container">', unsafe_allow_html=True)
        
        st.markdown('<h3 style="text-align:center; color:#00e676;">🔐 Acesso Restrito</h3>', unsafe_allow_html=True)
        st.markdown('<p style="text-align:center; color:#6b8f6b; font-size:0.8rem;">Área exclusiva para administradores</p>', unsafe_allow_html=True)
        
        st.markdown("---")
        
        username = st.text_input("Usuário", key="login_user", placeholder="Digite seu usuário")
        password = st.text_input("Senha", type="password", key="login_pass", placeholder="Digite sua senha")
        
        if st.button("🔓 Entrar", type="primary", use_container_width=True):
            if username == USUARIO_AUTORIZADO and password == SENHA_AUTORIZADA:
                st.session_state['logado'] = True
                st.session_state['usuario'] = username
                st.success("✅ Acesso concedido! Redirecionando...")
                st.rerun()
            else:
                st.error("❌ Usuário ou senha incorretos")
        
        st.markdown("---")
        st.markdown('<p style="text-align:center; color:#6b8f6b; font-size:0.7rem;">⚠️ Acesso restrito - Somente usuário autorizado</p>', unsafe_allow_html=True)
        
        st.markdown('</div>', unsafe_allow_html=True)

# ============================================
# DASHBOARD PRINCIPAL
# ============================================

def dashboard_principal():
    
    # Sidebar
    with st.sidebar:
        st.markdown(f"### 👤 {st.session_state.get('usuario', 'Usuário')}")
        st.markdown('<span class="elegivel-sim">👑 Administrador</span>', unsafe_allow_html=True)
        st.markdown("---")
        
        st.markdown("### 📚 Histórico de Análises")
        analises = get_analises()
        
        if analises:
            for a in analises:
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**{a['periodo']}**")
                    st.caption(f"{a['data_analise'][:16]}")
                with col2:
                    if st.button("🗑️", key=f"del_{a['id']}"):
                        deletar_analise(a['id'])
                        st.rerun()
                st.markdown("---")
        else:
            st.info("Nenhuma análise salva ainda")
        
        st.markdown("---")
        
        if st.button("🚪 Sair", use_container_width=True):
            st.session_state['logado'] = False
            st.rerun()
    
    # Cabeçalho
    st.markdown(f"""
    <div class="main-header">
        <h1>📊 Central de Vendas | Analytics Platform</h1>
        <p>Sistema de Análise de Bônus e Performance - {datetime.now().strftime('%d/%m/%Y')}</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Seleção do Dashboard
    dashboard_tipo = st.radio(
        "Selecione o Dashboard:",
        ["💰 Dashboard de Bônus", "📊 Dashboard de Performance"],
        horizontal=True
    )
    
    # ============================================
    # DASHBOARD DE BÔNUS
    # ============================================
    if dashboard_tipo == "💰 Dashboard de Bônus":
        
        tab1, tab2, tab3, tab4 = st.tabs([
            "📸 1. Nova Análise",
            "📊 2. Dashboard",
            "📈 3. Evolução",
            "✏️ 4. Edição Manual"
        ])
        
        # TAB 1: Nova Análise
        with tab1:
            st.markdown("### 📸 Envie os prints dos painéis")
            
            st.markdown("""
            <div class="info-box">
            📌 <strong>Instruções:</strong><br>
            - <strong>Print 1:</strong> Alcance Projetado e Margem<br>
            - <strong>Print 2:</strong> Prazo Médio<br>
            - <strong>Print 3:</strong> Qtd. Faturadas<br>
            - <strong>Print 4:</strong> Chamadas<br>
            - <strong>Print 5:</strong> TME, Iniciados e Recebidos
            </div>
            """, unsafe_allow_html=True)
            
            prints_bytes = []
            nomes_print = [
                "Print 1 - Alcance e Margem",
                "Print 2 - Prazo Médio",
                "Print 3 - Qtd. Faturadas",
                "Print 4 - Chamadas",
                "Print 5 - TME, Iniciados e Recebidos"
            ]
            
            col1, col2 = st.columns(2)
            
            for i, nome in enumerate(nomes_print):
                with (col1 if i % 2 == 0 else col2):
                    arquivo = st.file_uploader(nome, type=["png", "jpg", "jpeg"], key=f"print_{i}")
                    if arquivo:
                        prints_bytes.append(arquivo.read())
                        st.success(f"✅ {nome} carregado!")
            
            if prints_bytes:
                st.markdown("---")
                
                col1, col2 = st.columns([1, 3])
                with col1:
                    periodo_input = st.text_input("📅 Período (ex: Abril 2024)", value=datetime.now().strftime("%B %Y"))
                
                if st.button("🚀 Analisar Prints com IA", type="primary", use_container_width=True):
                    if not api_key:
                        st.error("❌ Configure a chave API do Google Gemini no arquivo .env")
                        st.stop()
                    
                    with st.spinner("🔄 Analisando os prints... Isso pode levar alguns segundos"):
                        dados = analisar_prints_com_gemini(prints_bytes)
                        
                        if dados:
                            dados['periodo'] = periodo_input
                            vendedores = processar_dados_vendedores(dados)
                            total_bonus = sum(v['bonus_total'] for v in vendedores)
                            
                            # Salva no banco
                            dados_json = serializar_analise(vendedores, periodo_input)
                            salvar_analise(periodo_input, dados_json, total_bonus)
                            
                            st.session_state['analise_atual'] = {
                                'periodo': periodo_input,
                                'vendedores': vendedores,
                                'total_bonus': total_bonus
                            }
                            st.session_state['analise_realizada'] = True
                            
                            st.success("✅ Análise concluída e salva no histórico!")
                            
                            # Preview
                            st.markdown("### 📋 Dados Extraídos")
                            df_preview = pd.DataFrame(vendedores)
                            colunas_mostrar = ['nome', 'margem_pct', 'alcance_projetado_pct', 'prazo_medio', 
                                              'qtd_faturadas', 'chamadas', 'iniciados', 'recebidos', 
                                              'interacoes', 'conversao_calculada', 'tme_minutos', 'bonus_total']
                            df_preview = df_preview[[c for c in colunas_mostrar if c in df_preview.columns]]
                            st.dataframe(df_preview, use_container_width=True)
                            
                            st.info("👉 Vá para a aba 'Dashboard' para ver os resultados completos")
                        else:
                            st.error("❌ Falha na análise. Tente novamente com prints mais nítidos.")
            else:
                st.info("📤 Envie os 5 prints para começar a análise")
        
        # TAB 2: Dashboard
        with tab2:
            if not st.session_state.get('analise_realizada', False):
                st.warning("⚠️ Nenhuma análise carregada. Faça uma nova análise ou carregue do histórico na barra lateral.")
            else:
                analise = st.session_state.get('analise_atual', {})
                vendedores = analise.get('vendedores', [])
                periodo = analise.get('periodo', 'Período atual')
                stats = calcular_estatisticas_time(vendedores)
                
                st.markdown(f'<div class="periodo-box">📅 {periodo}</div>', unsafe_allow_html=True)
                
                # Cards principais
                col1, col2, col3, col4, col5 = st.columns(5)
                
                with col1:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">💰 BÔNUS TOTAL</div>
                        <div class="valor-grande">R$ {stats['total_bonus']:,.2f}</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col2:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">🏆 ELEGÍVEIS MARGEM</div>
                        <div class="valor-grande">{stats['qtd_elegiveis']}</div>
                        <div class="indicador-meta">de {len(vendedores)} vendedores</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col3:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">📈 MÉDIA MARGEM</div>
                        <div class="valor-medio">{stats['media_margem']:.1f}%</div>
                        <div class="indicador-meta">Meta: ≥ 26%</div>
                        <div class="progresso-bar">
                            <div class="progresso-fill" style="width: {min(100, stats['media_margem']/26*100)}%"></div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col4:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">🔄 MÉDIA CONVERSÃO</div>
                        <div class="valor-medio">{stats['media_conversao']:.1f}%</div>
                        <div class="indicador-meta">Meta: ≥ 12%</div>
                        <div class="progresso-bar">
                            <div class="progresso-fill" style="width: {min(100, stats['media_conversao']/12*100)}%"></div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col5:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">⏱️ MÉDIA TME</div>
                        <div class="valor-medio">{stats['media_tme']:.1f} min</div>
                        <div class="indicador-meta">Meta: ≤ 5 min</div>
                        <div class="progresso-bar">
                            <div class="progresso-fill" style="width: {min(100, (1 - stats['media_tme']/5) * 100 if stats['media_tme'] <= 5 else 0)}%; background:#ff5252"></div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                
                st.markdown("---")
                st.markdown("### 📊 Resultados por Vendedor")
                
                # Gráfico de bônus
                df_plot = pd.DataFrame(vendedores)
                df_plot = df_plot.sort_values('bonus_total', ascending=False)
                
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=df_plot['nome'],
                    y=df_plot['bonus_total'],
                    text=df_plot['bonus_total'].apply(lambda x: f'R$ {x:,.0f}'),
                    textposition='outside',
                    marker_color=['#00e676' if b >= 400 else '#ffab00' if b >= 250 else '#ff7043' for b in df_plot['bonus_total']]
                ))
                fig.update_layout(
                    title="Bônus por Vendedor",
                    xaxis_title="Vendedor",
                    yaxis_title="Bônus (R$)",
                    plot_bgcolor='#0d1117',
                    paper_bgcolor='#0d1117',
                    font_color='#c8d0dc',
                    height=400
                )
                st.plotly_chart(fig, use_container_width=True)
                
                # Tabela completa
                st.markdown("---")
                
                col_headers = st.columns([1.2, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7])
                headers = ["Vendedor", "Margem%", "Alcance%", "Elegível", "Prazo", "Conversão%", "TME", "Interações", "Bônus"]
                for i, header in enumerate(headers):
                    col_headers[i].markdown(f"**{header}**")
                
                st.markdown("<hr>", unsafe_allow_html=True)
                
                for v in vendedores:
                    cols = st.columns([1.2, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7])
                    
                    cols[0].markdown(f"**{v['nome']}**")
                    
                    margem_class = "meta-ok" if v['margem_pct'] >= 26 else "meta-ruim"
                    cols[1].markdown(f'<span class="{margem_class}">{v["margem_pct"]:.1f}%</span>', unsafe_allow_html=True)
                    
                    cols[2].markdown(f"{v['alcance_projetado_pct']:.1f}%" if v['alcance_projetado_pct'] > 0 else "N/D")
                    
                    if v['elegivel_margem']:
                        cols[3].markdown('<span class="elegivel-sim">Sim</span>', unsafe_allow_html=True)
                    else:
                        cols[3].markdown('<span class="elegivel-nao">Não</span>', unsafe_allow_html=True)
                    
                    prazo_class = "meta-ok" if v['prazo_medio'] <= 43 and v['prazo_medio'] > 0 else "meta-ruim"
                    cols[4].markdown(f'<span class="{prazo_class}">{v["prazo_medio"]:.0f}d</span>' if v['prazo_medio'] > 0 else "N/D", unsafe_allow_html=True)
                    
                    conv_class = "meta-ok" if v['conversao_calculada'] >= 12 else "meta-ruim"
                    cols[5].markdown(f'<span class="{conv_class}">{v["conversao_calculada"]:.1f}%</span>' if v['conversao_calculada'] > 0 else "N/D", unsafe_allow_html=True)
                    
                    tme_class = "meta-ok" if v['tme_minutos'] <= 5 and v['tme_minutos'] > 0 else "meta-ruim"
                    cols[6].markdown(f'<span class="{tme_class}">{v["tme_minutos"]:.1f}m</span>' if v['tme_minutos'] > 0 else "N/D", unsafe_allow_html=True)
                    
                    cols[7].markdown(f"{v['interacoes']:.0f}")
                    
                    cols[8].markdown(f"**R$ {v['bonus_total']:,.0f}**")
                
                st.markdown(f"""
                <div style="background:#1a2a1a; border:1px solid #2d5a2d; border-radius:12px; padding:16px; text-align:center; margin-top:16px;">
                    <div style="font-size:0.8rem; color:#6b8f6b;">TOTAL DO TIME</div>
                    <div class="bonus-total">R$ {stats['total_bonus']:,.2f}</div>
                </div>
                """, unsafe_allow_html=True)
        
        # TAB 3: Evolução
        with tab3:
            st.markdown("### 📈 Evolução do Time")
            
            analises = get_analises()
            
            if len(analises) < 2:
                st.info("📊 Após realizar 2 ou mais análises, você poderá ver a evolução do time aqui.")
                st.markdown("""
                <div class="info-box">
                💡 <strong>Dica:</strong> Realize análises em diferentes períodos (ex: Março, Abril, Maio) 
                para acompanhar a evolução dos resultados.
                </div>
                """, unsafe_allow_html=True)
            else:
                # Gráfico de evolução
                df_evolucao = pd.DataFrame([
                    {'periodo': a['periodo'], 'total_bonus': a['total_bonus'], 'data': a['data_analise']}
                    for a in analises
                ])
                df_evolucao = df_evolucao.sort_values('data')
                
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df_evolucao['periodo'],
                    y=df_evolucao['total_bonus'],
                    mode='lines+markers',
                    line=dict(color='#00e676', width=3),
                    marker=dict(size=10, color='#00e676'),
                    text=df_evolucao['total_bonus'].apply(lambda x: f'R$ {x:,.2f}'),
                    textposition='top center'
                ))
                fig.update_layout(
                    title="Evolução do Bônus Total do Time",
                    xaxis_title="Período",
                    yaxis_title="Bônus Total (R$)",
                    plot_bgcolor='#0d1117',
                    paper_bgcolor='#0d1117',
                    font_color='#c8d0dc',
                    height=400
                )
                st.plotly_chart(fig, use_container_width=True)
                
                # Comparação entre períodos
                st.markdown("---")
                st.markdown("### 📊 Comparação entre Períodos")
                
                col1, col2 = st.columns(2)
                with col1:
                    periodo_ant = st.selectbox("Período anterior", [a['periodo'] for a in analises[:-1]], key="periodo_ant")
                with col2:
                    periodo_atual = st.selectbox("Período atual", [a['periodo'] for a in analises[1:]], key="periodo_atual")
                
                if periodo_ant and periodo_atual:
                    dados_ant = next((a for a in analises if a['periodo'] == periodo_ant), None)
                    dados_atual = next((a for a in analises if a['periodo'] == periodo_atual), None)
                    
                    if dados_ant and dados_atual:
                        vendedores_ant = desserializar_analise(dados_ant['dados_json'])['vendedores']
                        vendedores_atual = desserializar_analise(dados_atual['dados_json'])['vendedores']
                        
                        v_ant = {v['nome']: v for v in vendedores_ant}
                        v_atual = {v['nome']: v for v in vendedores_atual}
                        
                        variacao = dados_atual['total_bonus'] - dados_ant['total_bonus']
                        pct = (variacao / dados_ant['total_bonus'] * 100) if dados_ant['total_bonus'] > 0 else 0
                        
                        col1, col2, col3 = st.columns(3)
                        col1.metric(periodo_ant, f"R$ {dados_ant['total_bonus']:,.2f}")
                        col2.metric(periodo_atual, f"R$ {dados_atual['total_bonus']:,.2f}")
                        col3.metric("Variação", f"{variacao:+,.2f}", f"{pct:+.1f}%")
                        
                        st.markdown("#### 👥 Evolução por Vendedor")
                        
                        for nome in VENDEDORES_VALIDOS:
                            ant = v_ant.get(nome, {})
                            atual = v_atual.get(nome, {})
                            if ant or atual:
                                cols = st.columns([2, 1.5, 1.5, 1.5, 2])
                                cols[0].markdown(f"**{nome}**")
                                cols[1].markdown(f"R$ {ant.get('bonus_total', 0):,.0f}")
                                cols[2].markdown(f"R$ {atual.get('bonus_total', 0):,.0f}")
                                var = atual.get('bonus_total', 0) - ant.get('bonus_total', 0)
                                cor = "#00e676" if var >= 0 else "#ff5252"
                                cols[3].markdown(f'<span style="color:{cor}">{var:+,.0f}</span>', unsafe_allow_html=True)
                                cols[4].markdown(f"{ant.get('margem_pct', 0):.1f}% → {atual.get('margem_pct', 0):.1f}%")
        
        # TAB 4: Edição Manual
        with tab4:
            if not st.session_state.get('analise_realizada', False):
                st.warning("⚠️ Nenhuma análise carregada. Faça uma nova análise primeiro.")
            else:
                analise = st.session_state.get('analise_atual', {})
                vendedores = analise.get('vendedores', [])
                periodo = analise.get('periodo', 'Período atual')
                
                st.markdown("### ✏️ Correção Manual de Dados")
                st.markdown("""
                <div class="info-box">
                📌 Altere os valores abaixo e clique em "Salvar alterações" para atualizar o dashboard.<br>
                Após salvar, os dados serão atualizados no histórico.
                </div>
                """, unsafe_allow_html=True)
                
                vendedores_editados = editar_dados_manual(vendedores)
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("💾 Salvar alterações e atualizar", type="primary", use_container_width=True):
                        dados_json = serializar_analise(vendedores_editados, periodo)
                        total_bonus = sum(v['bonus_total'] for v in vendedores_editados)
                        salvar_analise(periodo, dados_json, total_bonus)
                        
                        st.session_state['analise_atual'] = {
                            'periodo': periodo,
                            'vendedores': vendedores_editados,
                            'total_bonus': total_bonus
                        }
                        st.success("✅ Alterações salvas com sucesso!")
                        st.rerun()
                with col2:
                    if st.button("🔄 Cancelar e manter originais", use_container_width=True):
                        st.rerun()
    
    # ============================================
    # DASHBOARD DE PERFORMANCE
    # ============================================
    else:
        if not st.session_state.get('analise_realizada', False):
            st.warning("⚠️ Nenhuma análise carregada. Faça uma nova análise ou carregue do histórico na barra lateral.")
        else:
            analise = st.session_state.get('analise_atual', {})
            vendedores = analise.get('vendedores', [])
            periodo = analise.get('periodo', 'Período atual')
            stats = calcular_estatisticas_time(vendedores)
            
            st.markdown(f'<div class="periodo-box">📅 {periodo}</div>', unsafe_allow_html=True)
            st.markdown("### 📊 Visão Geral da Performance do Time")
            
            # Cards de todas as médias
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.markdown(f"""
                <div class="card-metrica">
                    <div class="indicador-titulo">📈 MARGEM MÉDIA</div>
                    <div class="valor-grande">{stats['media_margem']:.1f}%</div>
                    <div class="indicador-meta">Meta: ≥ 26%</div>
                    <div class="progresso-bar">
                        <div class="progresso-fill" style="width: {min(100, stats['media_margem']/26*100)}%"></div>
                    </div>
                    <div class="indicador-meta">{stats['acima_meta_margem']} de {len(vendedores)} acima da meta</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col2:
                st.markdown(f"""
                <div class="card-metrica">
                    <div class="indicador-titulo">🔄 CONVERSÃO MÉDIA</div>
                    <div class="valor-grande">{stats['media_conversao']:.1f}%</div>
                    <div class="indicador-meta">Meta: ≥ 12%</div>
                    <div class="progresso-bar">
                        <div class="progresso-fill" style="width: {min(100, stats['media_conversao']/12*100)}%"></div>
                    </div>
                    <div class="indicador-meta">{stats['acima_meta_conversao']} de {len(vendedores)} acima da meta</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col3:
                st.markdown(f"""
                <div class="card-metrica">
                    <div class="indicador-titulo">📅 PRAZO MÉDIO</div>
                    <div class="valor-grande">{stats['media_prazo']:.0f} dias</div>
                    <div class="indicador-meta">Meta: ≤ 43 dias</div>
                    <div class="progresso-bar">
                        <div class="progresso-fill" style="width: {min(100, (1 - stats['media_prazo']/43) * 100 if stats['media_prazo'] <= 43 else 0)}%; background:#ff5252"></div>
                    </div>
                    <div class="indicador-meta">{stats['acima_meta_prazo']} de {len(vendedores)} dentro da meta</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col4:
                st.markdown(f"""
                <div class="card-metrica">
                    <div class="indicador-titulo">⏱️ TME MÉDIO</div>
                    <div class="valor-grande">{stats['media_tme']:.1f} min</div>
                    <div class="indicador-meta">Meta: ≤ 5 min</div>
                    <div class="progresso-bar">
                        <div class="progresso-fill" style="width: {min(100, (1 - stats['media_tme']/5) * 100 if stats['media_tme'] <= 5 else 0)}%; background:#ff5252"></div>
                    </div>
                    <div class="indicador-meta">{stats['acima_meta_tme']} de {len(vendedores)} dentro da meta</div>
                </div>
                """, unsafe_allow_html=True)
            
            st.markdown("---")
            
            # Segunda linha de cards
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.markdown(f"""
                <div class="card-metrica">
                    <div class="indicador-titulo">📊 ALCANCE MÉDIO</div>
                    <div class="valor-medio">{stats['media_alcance']:.1f}%</div>
                    <div class="indicador-meta">Necessário ≥ 90% para bônus margem</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col2:
                st.markdown(f"""
                <div class="card-metrica">
                    <div class="indicador-titulo">💬 INTERAÇÕES MÉDIAS</div>
                    <div class="valor-medio">{stats['media_interacoes']:.0f}</div>
                    <div class="indicador-meta">Meta: ≥ 200</div>
                    <div class="progresso-bar">
                        <div class="progresso-fill" style="width: {min(100, stats['media_interacoes']/200*100)}%"></div>
                    </div>
                    <div class="indicador-meta">{stats['acima_meta_interacoes']} de {len(vendedores)} acima da meta</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col3:
                st.markdown(f"""
                <div class="card-metrica">
                    <div class="indicador-titulo">📦 TOTAL FATURADO</div>
                    <div class="valor-medio">{stats['total_faturas']:.0f}</div>
                    <div class="indicador-meta">Qtd. Faturadas no período</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col4:
                st.markdown(f"""
                <div class="card-metrica">
                    <div class="indicador-titulo">🏆 TOTAL INTERAÇÕES</div>
                    <div class="valor-medio">{stats['total_interacoes']:.0f}</div>
                    <div class="indicador-meta">Chamadas + Iniciados + Recebidos</div>
                </div>
                """, unsafe_allow_html=True)
            
            st.markdown("---")
            
            # Gráfico de radar comparativo
            st.markdown("### 🎯 Comparativo de Metas")
            
            categorias = ['Margem', 'Conversão', 'Prazo (inv)', 'TME (inv)', 'Interações']
            
            valores = [
                min(100, stats['media_margem']/26*100),
                min(100, stats['media_conversao']/12*100),
                min(100, max(0, (1 - stats['media_prazo']/43)*100)) if stats['media_prazo'] > 0 else 0,
                min(100, max(0, (1 - stats['media_tme']/5)*100)) if stats['media_tme'] > 0 else 0,
                min(100, stats['media_interacoes']/200*100)
            ]
            
            fig = go.Figure()
            
            fig.add_trace(go.Scatterpolar(
                r=valores,
                theta=categorias,
                fill='toself',
                name='Time',
                line=dict(color='#00e676', width=2),
                fillcolor='rgba(0, 230, 118, 0.2)'
            ))
            
            fig.add_trace(go.Scatterpolar(
                r=[100, 100, 100, 100, 100],
                theta=categorias,
                fill='none',
                name='Meta (100%)',
                line=dict(color='#ffab00', width=2, dash='dash')
            ))
            
            fig.update_layout(
                polar=dict(
                    radialaxis=dict(visible=True, range=[0, 100], color='#8892a4'),
                    angularaxis=dict(color='#8892a4')
                ),
                showlegend=True,
                plot_bgcolor='#0d1117',
                paper_bgcolor='#0d1117',
                font_color='#c8d0dc',
                height=450
            )
            
            st.plotly_chart(fig, use_container_width=True)
            
            # Insights gerais
            st.markdown("---")
            st.markdown("### 💡 Insights Gerais do Time")
            
            insights = []
            
            if stats['media_margem'] >= 26:
                insights.append("✅ **Margem:** Time está acima da meta de 26%")
            else:
                insights.append(f"⚠️ **Margem:** Time está {26 - stats['media_margem']:.1f}% abaixo da meta")
            
            if stats['media_conversao'] >= 12:
                insights.append("✅ **Conversão:** Time está acima da meta de 12%")
            else:
                insights.append(f"⚠️ **Conversão:** Time está {12 - stats['media_conversao']:.1f}% abaixo da meta")
            
            if stats['media_prazo'] <= 43:
                insights.append("✅ **Prazo:** Time está dentro da meta de 43 dias")
            else:
                insights.append(f"⚠️ **Prazo:** Time está {stats['media_prazo'] - 43:.0f} dias acima da meta")
            
            if stats['media_tme'] <= 5:
                insights.append("✅ **TME:** Time está dentro da meta de 5 minutos")
            else:
                insights.append(f"⚠️ **TME:** Time está {stats['media_tme'] - 5:.1f} minutos acima da meta")
            
            if stats['media_interacoes'] >= 200:
                insights.append("✅ **Interações:** Time está acima da meta de 200")
            else:
                insights.append(f"⚠️ **Interações:** Time está {200 - stats['media_interacoes']:.0f} abaixo da meta")
            
            for insight in insights:
                st.markdown(f'<div class="info-box">{insight}</div>', unsafe_allow_html=True)

# ============================================
# MAIN
# ============================================

def main():
    if not st.session_state.get('logado', False):
        tela_login()
    else:
        dashboard_principal()

if __name__ == "__main__":
    main()
