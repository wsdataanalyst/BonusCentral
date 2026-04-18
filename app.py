"""
DASHBOARD DE VENDAS - ANALISADOR DE PRINTS COM AUTENTICAÇÃO
Sistema seguro para extrair dados de prints e calcular bônus
"""

import subprocess, sys, os

# Instala bibliotecas automaticamente se não tiver
try:
    import google.generativeai as genai
except ModuleNotFoundError:
    print("Instalando Google Gemini...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "google-generativeai"])
    import google.generativeai as genai

from dotenv import load_dotenv

# Carrega variáveis de ambiente
load_dotenv()

# Configura API do Gemini
api_key = os.getenv("GOOGLE_API_KEY")
if api_key:
    genai.configure(api_key=api_key)

# Imports principais
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import PIL.Image
from io import BytesIO
import json
import re
from datetime import datetime
import hashlib

# Importa módulos locais
from database import init_database, get_connection, salvar_analise, get_analises_usuario
from auth import registrar_usuario, fazer_login, logout, get_usuario_atual, is_admin
from utils import calcular_estatisticas_time, serializar_analise, desserializar_analise

# ============================================
# INICIALIZAÇÃO
# ============================================

# Inicializa banco de dados
init_database()

# Configuração da página
st.set_page_config(
    page_title="Vendas Analytics | Dashboard Seguro",
    page_icon="🔒",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================
# LISTA DE VENDEDORES VÁLIDOS
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

def filtrar_vendedores_validos(vendedores):
    return [v for v in vendedores if padronizar_nome(v.get('nome', '')) in VENDEDORES_VALIDOS]

# ============================================
# FUNÇÕES PRINCIPAIS
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
    
    # Margem
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
    
    # Prazo
    if prazo <= 43:
        bonus_total += 100
        detalhes.append(f"✅ Prazo Médio: R$ 100 ({prazo:.0f} dias ≤ 43)")
    else:
        detalhes.append(f"❌ Prazo Médio: R$ 0 ({prazo:.0f} dias > 43)" if prazo != 999 else "❌ Prazo Médio: R$ 0")
    
    # Conversão
    if conversao >= 12:
        bonus_total += 100
        detalhes.append(f"✅ Conversão: R$ 100 ({conversao:.1f}% ≥ 12%)")
    else:
        detalhes.append(f"❌ Conversão: R$ 0 ({conversao:.1f}% < 12%)" if conversao > 0 else "❌ Conversão: R$ 0")
    
    # TME
    if tme <= 5:
        bonus_total += 150
        detalhes.append(f"✅ TME: R$ 150 ({tme:.1f} min ≤ 5)")
    else:
        detalhes.append(f"❌ TME: R$ 0 ({tme:.1f} min > 5)" if tme != 999 else "❌ TME: R$ 0")
    
    # Interações
    if interacoes >= 200:
        bonus_total += 100
        detalhes.append(f"✅ Interações: R$ 100 ({interacoes:.0f} ≥ 200)")
    else:
        detalhes.append(f"❌ Interações: R$ 0 ({interacoes:.0f} < 200)" if interacoes > 0 else "❌ Interações: R$ 0")
    
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
    
    vendedores_filtrados = filtrar_vendedores_validos(todos_vendedores)
    
    for v in vendedores_filtrados:
        nome_padronizado = padronizar_nome(v.get('nome', 'Desconhecido'))
        if nome_padronizado not in VENDEDORES_VALIDOS:
            continue
        
        chamadas = v.get('chamadas', 0) or 0
        iniciados = v.get('iniciados', 0) or 0
        recebidos = v.get('recebidos', 0) or 0
        interacoes = chamadas + iniciados + recebidos
        
        qtd_faturadas = v.get('qtd_faturadas', 0) or 0
        if interacoes > 0 and qtd_faturadas > 0:
            conversao = (qtd_faturadas / interacoes) * 100
            conversao = round(conversao, 2)
        else:
            conversao = 0
        
        margem = v.get('margem_pct', 0) or 0
        alcance = v.get('alcance_projetado_pct', 0) or 0
        prazo = v.get('prazo_medio', 0) or 0
        tme = v.get('tme_minutos', 0) or 0
        
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
            vendedor_vazio = {
                'nome': nome,
                'margem_pct': 0,
                'alcance_projetado_pct': 0,
                'prazo_medio': 0,
                'qtd_faturadas': 0,
                'chamadas': 0,
                'iniciados': 0,
                'recebidos': 0,
                'interacoes': 0,
                'conversao_calculada': 0,
                'tme_minutos': 0,
                'elegivel_margem': False,
                'bonus_total': 0,
                'detalhes_bonus': ["⚠️ Dados não encontrados"]
            }
            vendedores_processados.append(vendedor_vazio)
    
    return vendedores_processados

def editar_dados_manual(vendedores):
    st.markdown("### ✏️ Edição Manual de Dados")
    
    vendedores_editados = []
    
    for i, v in enumerate(vendedores):
        with st.expander(f"✏️ {v['nome']} - Editar dados"):
            col1, col2 = st.columns(2)
            
            with col1:
                novo_margem = st.number_input("Margem (%)", 0.0, 100.0, float(v['margem_pct']), 0.1, key=f"margem_{i}")
                novo_alcance = st.number_input("Alcance (%)", 0.0, 300.0, float(v['alcance_projetado_pct']), 0.1, key=f"alcance_{i}")
                novo_prazo = st.number_input("Prazo (dias)", 0, 200, int(v['prazo_medio']), 1, key=f"prazo_{i}")
                tme_valor = min(float(v['tme_minutos']), 60)
                novo_tme = st.number_input("TME (min)", 0.0, 60.0, tme_valor, 0.1, key=f"tme_{i}")
            
            with col2:
                novo_qtd = st.number_input("Qtd Faturadas", 0, 1000, int(v['qtd_faturadas']), 1, key=f"qtd_{i}")
                novo_chamadas = st.number_input("Chamadas", 0, 1000, int(v.get('chamadas', 0)), 1, key=f"chamadas_{i}")
                novo_iniciados = st.number_input("Iniciados", 0, 1000, int(v['iniciados']), 1, key=f"iniciados_{i}")
                novo_recebidos = st.number_input("Recebidos", 0, 1000, int(v['recebidos']), 1, key=f"recebidos_{i}")
            
            novas_interacoes = novo_chamadas + novo_iniciados + novo_recebidos
            nova_conversao = round((novo_qtd / novas_interacoes) * 100, 2) if novas_interacoes > 0 and novo_qtd > 0 else 0
            
            vendedor_editado = {
                'nome': v['nome'],
                'margem_pct': novo_margem,
                'alcance_projetado_pct': novo_alcance,
                'prazo_medio': novo_prazo,
                'qtd_faturadas': novo_qtd,
                'chamadas': novo_chamadas,
                'iniciados': novo_iniciados,
                'recebidos': novo_recebidos,
                'interacoes': novas_interacoes,
                'conversao_calculada': nova_conversao,
                'tme_minutos': novo_tme,
                'elegivel_margem': novo_margem >= 26 and novo_alcance >= 90
            }
            
            bonus, detalhes = calcular_bonus(vendedor_editado)
            vendedor_editado['bonus_total'] = bonus
            vendedor_editado['detalhes_bonus'] = detalhes
            
            st.markdown(f"**🔄 Novo bônus: R$ {bonus:,.2f}**")
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
    .card-metrica:hover { border-color: #00e676; }
    .bonus-total { font-size: 2rem; font-weight: bold; color: #00e676; }
    .valor-grande { font-size: 1.8rem; font-weight: bold; color: #00e676; }
    .elegivel-sim {
        background-color: #1a4a2e;
        color: #00e676;
        padding: 4px 12px;
        border-radius: 20px;
        display: inline-block;
        font-weight: bold;
    }
    .elegivel-nao {
        background-color: #3a1a1a;
        color: #ff5252;
        padding: 4px 12px;
        border-radius: 20px;
        display: inline-block;
        font-weight: bold;
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
        margin: 100px auto;
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
    }
</style>
""", unsafe_allow_html=True)

# ============================================
# TELA DE LOGIN
# ============================================

def tela_login():
    st.markdown("""
    <div class="main-header" style="text-align:center">
        <h1>🔒 Dashboard de Vendas</h1>
        <p>Sistema seguro de análise de bônus e performance</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown('<div class="login-container">', unsafe_allow_html=True)
        
        tab_login, tab_registro = st.tabs(["🔐 Login", "📝 Registrar"])
        
        with tab_login:
            username = st.text_input("Usuário", key="login_user")
            password = st.text_input("Senha", type="password", key="login_pass")
            
            if st.button("Entrar", type="primary", use_container_width=True):
                if username and password:
                    # Pega IP (simulado, Streamlit Cloud não dá acesso real)
                    ip = st.request.headers.get('X-Forwarded-For', 'desconhecido') if hasattr(st, 'request') else 'local'
                    usuario = fazer_login(username, password, ip)
                    
                    if usuario:
                        st.session_state['usuario'] = usuario
                        st.session_state['logado'] = True
                        st.success(f"✅ Bem-vindo, {username}!")
                        st.rerun()
                    else:
                        st.error("❌ Usuário ou senha incorretos")
                else:
                    st.warning("Preencha usuário e senha")
        
        with tab_registro:
            new_user = st.text_input("Usuário", key="reg_user")
            new_email = st.text_input("E-mail (opcional)", key="reg_email")
            new_pass = st.text_input("Senha", type="password", key="reg_pass")
            confirm_pass = st.text_input("Confirmar senha", type="password", key="reg_confirm")
            
            if st.button("Criar conta", type="primary", use_container_width=True):
                if new_user and new_pass:
                    if new_pass != confirm_pass:
                        st.error("❌ Senhas não conferem")
                    else:
                        sucesso, msg = registrar_usuario(new_user, new_pass, new_email)
                        if sucesso:
                            st.success(msg)
                            st.info("Agora faça login com suas credenciais")
                        else:
                            st.error(f"❌ {msg}")
                else:
                    st.warning("Preencha todos os campos obrigatórios")
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        st.markdown("""
        <div class="info-box" style="text-align:center; margin-top:20px">
        🔐 <strong>Segurança:</strong> Suas informações são protegidas com criptografia.<br>
        Os dados são armazenados localmente no banco de dados do sistema.
        </div>
        """, unsafe_allow_html=True)

# ============================================
# DASHBOARD PRINCIPAL (APÓS LOGIN)
# ============================================

def dashboard_principal():
    usuario = st.session_state.get('usuario', {})
    
    # Sidebar
    with st.sidebar:
        st.markdown(f"### 👤 {usuario.get('username', 'Usuário')}")
        if usuario.get('is_admin', False):
            st.markdown('<span class="elegivel-sim">👑 Administrador</span>', unsafe_allow_html=True)
        st.markdown("---")
        
        # Seletor de análise (histórico)
        st.markdown("### 📚 Histórico de Análises")
        analises = get_analises_usuario(usuario['id'])
        
        if analises:
            opcoes = {f"{a['periodo']} ({a['data_analise'][:16]})": a for a in analises}
            selecionado = st.selectbox("Carregar análise anterior:", ["--- Nova análise ---"] + list(opcoes.keys()))
            
            if selecionado != "--- Nova análise ---" and selecionado in opcoes:
                analise_selecionada = opcoes[selecionado]
                dados = desserializar_analise(analise_selecionada['dados_json'])
                st.session_state['analise_atual'] = {
                    'periodo': dados['periodo'],
                    'vendedores': dados['vendedores'],
                    'total_bonus': analise_selecionada['total_bonus']
                }
                st.session_state['analise_realizada'] = True
                st.success(f"✅ Carregado: {analise_selecionada['periodo']}")
        else:
            st.info("Nenhuma análise salva ainda")
        
        st.markdown("---")
        
        if st.button("🚪 Sair", use_container_width=True):
            logout()
            st.rerun()
    
    # Cabeçalho
    st.markdown(f"""
    <div class="main-header">
        <h1>📊 Central de Vendas | Analytics Platform</h1>
        <p>Sistema Inteligente de Análise de Bônus e Desempenho - {datetime.now().strftime('%d/%m/%Y')}</p>
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
        
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "📸 1. Nova Análise",
            "📊 2. Dashboard",
            "📈 3. Evolução",
            "💰 4. Detalhamento",
            "✏️ 5. Edição Manual"
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
                    periodo_input = st.text_input("📅 Período", value=datetime.now().strftime("%B %Y"))
                
                if st.button("🚀 Analisar Prints com IA", type="primary", use_container_width=True):
                    if not api_key:
                        st.error("❌ Configure a chave API do Google Gemini no arquivo .env")
                        st.stop()
                    
                    with st.spinner("🔄 Analisando os prints..."):
                        dados = analisar_prints_com_gemini(prints_bytes)
                        
                        if dados:
                            dados['periodo'] = periodo_input
                            vendedores = processar_dados_vendedores(dados)
                            total_bonus = sum(v['bonus_total'] for v in vendedores)
                            
                            # Salva no banco
                            dados_json = serializar_analise(vendedores, periodo_input)
                            salvar_analise(usuario['id'], periodo_input, dados_json, total_bonus)
                            
                            st.session_state['analise_atual'] = {
                                'periodo': periodo_input,
                                'vendedores': vendedores,
                                'total_bonus': total_bonus
                            }
                            st.session_state['analise_realizada'] = True
                            
                            st.success("✅ Análise concluída e salva no histórico!")
                            
                            df_preview = pd.DataFrame(vendedores)
                            st.dataframe(df_preview, use_container_width=True)
                        else:
                            st.error("❌ Falha na análise. Tente novamente.")
            else:
                st.info("📤 Envie os 5 prints para começar a análise")
        
        # TAB 2: Dashboard
        with tab2:
            if not st.session_state.get('analise_realizada', False):
                st.warning("⚠️ Nenhuma análise carregada. Faça uma nova análise ou carregue do histórico.")
            else:
                analise = st.session_state.get('analise_atual', {})
                vendedores = analise.get('vendedores', [])
                periodo = analise.get('periodo', 'Período atual')
                stats = calcular_estatisticas_time(vendedores)
                
                st.markdown(f'<div class="periodo-box">📅 {periodo}</div>', unsafe_allow_html=True)
                
                # Cards
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
                        <div class="indicador-titulo">🏆 ELEGÍVEIS</div>
                        <div class="valor-grande">{stats['qtd_elegiveis']}</div>
                        <div class="indicador-meta">de {len(vendedores)} vendedores</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col3:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">📈 MÉDIA MARGEM</div>
                        <div class="valor-medio">{stats['media_margem']:.1f}%</div>
                        <div class="indicador-meta">Meta: 26%</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col4:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">🔄 MÉDIA CONVERSÃO</div>
                        <div class="valor-medio">{stats['media_conversao']:.1f}%</div>
                        <div class="indicador-meta">Meta: 12%</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col5:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">⏱️ MÉDIA TME</div>
                        <div class="valor-medio">{stats['media_tme']:.1f} min</div>
                        <div class="indicador-meta">Meta: 5 min</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                st.markdown("---")
                st.markdown("### 📊 Resultados por Vendedor")
                
                # Gráfico
                df_plot = pd.DataFrame(vendedores).sort_values('bonus_total', ascending=False)
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=df_plot['nome'],
                    y=df_plot['bonus_total'],
                    text=df_plot['bonus_total'].apply(lambda x: f'R$ {x:,.0f}'),
                    textposition='outside',
                    marker_color=['#00e676' if b >= 400 else '#ffab00' if b >= 250 else '#ff7043' for b in df_plot['bonus_total']]
                ))
                fig.update_layout(title="Bônus por Vendedor", plot_bgcolor='#0d1117', paper_bgcolor='#0d1117', height=400)
                st.plotly_chart(fig, use_container_width=True)
                
                # Tabela
                st.markdown("---")
                
                col_headers = st.columns([1.2, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7])
                headers = ["Vendedor", "Margem%", "Alcance%", "Elegível", "Prazo", "Conversão%", "TME", "Interações", "Bônus"]
                for i, h in enumerate(headers):
                    col_headers[i].markdown(f"**{h}**")
                
                for v in vendedores:
                    cols = st.columns([1.2, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7])
                    cols[0].markdown(f"**{v['nome']}**")
                    margem_class = "meta-ok" if v['margem_pct'] >= 26 else "meta-ruim"
                    cols[1].markdown(f'<span class="{margem_class}">{v["margem_pct"]:.1f}%</span>', unsafe_allow_html=True)
                    cols[2].markdown(f"{v['alcance_projetado_pct']:.1f}%" if v['alcance_projetado_pct'] > 0 else "N/D")
                    elegivel = "Sim" if v['elegivel_margem'] else "Não"
                    elegivel_class = "elegivel-sim" if v['elegivel_margem'] else "elegivel-nao"
                    cols[3].markdown(f'<span class="{elegivel_class}">{elegivel}</span>', unsafe_allow_html=True)
                    prazo_class = "meta-ok" if v['prazo_medio'] <= 43 else "meta-ruim"
                    cols[4].markdown(f'<span class="{prazo_class}">{v["prazo_medio"]:.0f}d</span>', unsafe_allow_html=True)
                    conv_class = "meta-ok" if v['conversao_calculada'] >= 12 else "meta-ruim"
                    cols[5].markdown(f'<span class="{conv_class}">{v["conversao_calculada"]:.1f}%</span>', unsafe_allow_html=True)
                    tme_class = "meta-ok" if v['tme_minutos'] <= 5 else "meta-ruim"
                    cols[6].markdown(f'<span class="{tme_class}">{v["tme_minutos"]:.1f}m</span>', unsafe_allow_html=True)
                    cols[7].markdown(f"{v['interacoes']:.0f}")
                    cols[8].markdown(f"**R$ {v['bonus_total']:,.0f}**")
        
        # TAB 3: Evolução
        with tab3:
            st.markdown("### 📈 Evolução do Time")
            
            analises = get_analises_usuario(usuario['id'])
            
            if len(analises) < 2:
                st.info("📊 Após realizar 2 ou mais análises, você poderá ver a evolução do time aqui.")
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
                                col1, col2, col3, col4, col5 = st.columns(5)
                                col1.markdown(f"**{nome}**")
                                col2.markdown(f"R$ {ant.get('bonus_total', 0):,.0f}")
                                col3.markdown(f"R$ {atual.get('bonus_total', 0):,.0f}")
                                var = atual.get('bonus_total', 0) - ant.get('bonus_total', 0)
                                cor = "#00e676" if var >= 0 else "#ff5252"
                                col4.markdown(f'<span style="color:{cor}">{var:+,.0f}</span>', unsafe_allow_html=True)
                                col5.markdown(f"{ant.get('margem_pct', 0):.1f}% → {atual.get('margem_pct', 0):.1f}%")
        
        # TAB 4: Detalhamento
        with tab4:
            if not st.session_state.get('analise_realizada', False):
                st.warning("⚠️ Nenhuma análise carregada.")
            else:
                vendedores = st.session_state.get('analise_atual', {}).get('vendedores', [])
                
                for v in vendedores:
                    with st.expander(f"💰 {v['nome']} - Total: R$ {v['bonus_total']:,.2f}"):
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown("**📈 Indicadores:**")
                            st.markdown(f"- Margem: {v['margem_pct']:.1f}%")
                            st.markdown(f"- Alcance: {v['alcance_projetado_pct']:.1f}%")
                            st.markdown(f"- Prazo Médio: {v['prazo_medio']:.0f} dias")
                            st.markdown(f"- TME: {v['tme_minutos']:.1f} min")
                        with col2:
                            st.markdown("**💬 Atendimentos:**")
                            st.markdown(f"- Qtd Faturadas: {v['qtd_faturadas']:.0f}")
                            st.markdown(f"- Chamadas: {v.get('chamadas', 0):.0f}")
                            st.markdown(f"- Iniciados: {v['iniciados']:.0f}")
                            st.markdown(f"- Recebidos: {v['recebidos']:.0f}")
                            st.markdown(f"- **Interações: {v['interacoes']:.0f}**")
                            st.markdown(f"- **Conversão: {v['conversao_calculada']:.1f}%**")
                        
                        st.markdown("**🎯 Bônus:**")
                        for d in v.get('detalhes_bonus', []):
                            if '✅' in d:
                                st.success(d)
                            else:
                                st.error(d)
        
        # TAB 5: Edição Manual
        with tab5:
            if not st.session_state.get('analise_realizada', False):
                st.warning("⚠️ Nenhuma análise carregada.")
            else:
                vendedores = st.session_state.get('analise_atual', {}).get('vendedores', [])
                periodo = st.session_state.get('analise_atual', {}).get('periodo', '')
                
                vendedores_editados = editar_dados_manual(vendedores)
                
                if st.button("💾 Salvar alterações e atualizar", type="primary", use_container_width=True):
                    dados_json = serializar_analise(vendedores_editados, periodo)
                    total_bonus = sum(v['bonus_total'] for v in vendedores_editados)
                    salvar_analise(usuario['id'], periodo, dados_json, total_bonus)
                    
                    st.session_state['analise_atual'] = {
                        'periodo': periodo,
                        'vendedores': vendedores_editados,
                        'total_bonus': total_bonus
                    }
                    st.success("✅ Alterações salvas!")
                    st.rerun()
    
    # ============================================
    # DASHBOARD DE PERFORMANCE
    # ============================================
    else:
        if not st.session_state.get('analise_realizada', False):
            st.warning("⚠️ Nenhuma análise carregada. Faça uma nova análise ou carregue do histórico.")
        else:
            analise = st.session_state.get('analise_atual', {})
            vendedores = analise.get('vendedores', [])
            periodo = analise.get('periodo', 'Período atual')
            stats = calcular_estatisticas_time(vendedores)
            
            st.markdown(f'<div class="periodo-box">📅 {periodo}</div>', unsafe_allow_html=True)
            st.markdown("### 📊 Visão Geral da Performance")
            
            # Cards de métricas
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.markdown(f"""
                <div class="card-metrica">
                    <div class="indicador-titulo">📈 MARGEM MÉDIA</div>
                    <div class="valor-grande">{stats['media_margem']:.1f}%</div>
                    <div class="progresso-bar"><div class="progresso-fill" style="width:{min(100, stats['media_margem']/26*100)}%"></div></div>
                    <div>{stats['acima_meta_margem']}/{len(vendedores)} acima da meta</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col2:
                st.markdown(f"""
                <div class="card-metrica">
                    <div class="indicador-titulo">🔄 CONVERSÃO MÉDIA</div>
                    <div class="valor-grande">{stats['media_conversao']:.1f}%</div>
                    <div class="progresso-bar"><div class="progresso-fill" style="width:{min(100, stats['media_conversao']/12*100)}%"></div></div>
                    <div>{stats['acima_meta_conversao']}/{len(vendedores)} acima da meta</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col3:
                st.markdown(f"""
                <div class="card-metrica">
                    <div class="indicador-titulo">⏱️ TME MÉDIO</div>
                    <div class="valor-grande">{stats['media_tme']:.1f} min</div>
                    <div class="progresso-bar"><div class="progresso-fill" style="width:{min(100, (1-stats['media_tme']/5)*100 if stats['media_tme']<=5 else 0)}%; background:#ff5252"></div></div>
                    <div>{stats['acima_meta_tme']}/{len(vendedores)} dentro da meta</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col4:
                st.markdown(f"""
                <div class="card-metrica">
                    <div class="indicador-titulo">💬 INTERAÇÕES MÉDIAS</div>
                    <div class="valor-grande">{stats['media_interacoes']:.0f}</div>
                    <div class="progresso-bar"><div class="progresso-fill" style="width:{min(100, stats['media_interacoes']/200*100)}%"></div></div>
                    <div>{stats['acima_meta_interacoes']}/{len(vendedores)} acima da meta</div>
                </div>
                """, unsafe_allow_html=True)
            
            st.markdown("---")
            
            # Gráfico radar
            st.markdown("### 🎯 Comparativo de Metas")
            
            categorias = ['Margem', 'Conversão', 'Prazo (inv)', 'TME (inv)', 'Interações']
            valores = [
                min(100, stats['media_margem']/26*100),
                min(100, stats['media_conversao']/12*100),
                min(100, max(0, (1 - stats['media_prazo']/43)*100)) if stats['media_prazo']>0 else 0,
                min(100, max(0, (1 - stats['media_tme']/5)*100)) if stats['media_tme']>0 else 0,
                min(100, stats['media_interacoes']/200*100)
            ]
            
            fig = go.Figure()
            fig.add_trace(go.Scatterpolar(r=valores, theta=categorias, fill='toself', name='Time', line=dict(color='#00e676')))
            fig.add_trace(go.Scatterpolar(r=[100,100,100,100,100], theta=categorias, fill='none', name='Meta', line=dict(color='#ffab00', dash='dash')))
            fig.update_layout(polar=dict(radialaxis=dict(range=[0,100])), height=450, plot_bgcolor='#0d1117', paper_bgcolor='#0d1117')
            st.plotly_chart(fig, use_container_width=True)

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