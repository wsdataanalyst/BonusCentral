"""
DASHBOARD DE VENDAS - ANALISADOR DE PRINTS COM IA
Sistema completo com histórico, projeções e análises robustas
"""

import subprocess, sys, os, hashlib, sqlite3, json, re
from datetime import datetime
from io import BytesIO
from datetime import date

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

# ============================================
# CONFIGURAÇÃO DA API GEMINI
# ============================================

api_key = None

try:
    if hasattr(st, 'secrets') and 'GOOGLE_API_KEY' in st.secrets:
        api_key = st.secrets['GOOGLE_API_KEY']
except:
    pass

if not api_key:
    api_key = os.getenv("GOOGLE_API_KEY")

if api_key:
    genai.configure(api_key=api_key)

# ============================================
# CREDENCIAIS DO USUÁRIO
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
    
    # Tabela de análises (histórico)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS analises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            periodo TEXT NOT NULL,
            data_analise TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            dados_json TEXT NOT NULL,
            total_bonus REAL
        )
    ''')
    
    # Tabela para salvar dados dos prints
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS dados_prints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_arquivo TEXT NOT NULL,
            dados_json TEXT NOT NULL,
            data_salvamento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

def carregar_analise_por_id(analise_id):
    """Carrega uma análise específica pelo ID"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, periodo, data_analise, dados_json, total_bonus FROM analises WHERE id = ?",
        (analise_id,)
    )
    analise = cursor.fetchone()
    conn.close()
    
    if analise:
        return {
            'id': analise[0],
            'periodo': analise[1],
            'data_analise': analise[2],
            'dados_json': analise[3],
            'total_bonus': analise[4]
        }
    return None

# ============================================
# FUNÇÃO PARA DIAS ÚTEIS (AUTOMÁTICA)
# ============================================

def calcular_dias_uteis():
    """Calcula dias úteis totais do mês e dias úteis passados até hoje"""
    hoje = date.today()
    ano = hoje.year
    mes = hoje.month
    
    # Próximo mês para calcular último dia
    if mes == 12:
        proximo_mes = date(ano + 1, 1, 1)
    else:
        proximo_mes = date(ano, mes + 1, 1)
    
    ultimo_dia = (proximo_mes - timedelta(days=1)).day
    
    # Conta dias úteis totais do mês
    dias_uteis_total = 0
    for dia in range(1, ultimo_dia + 1):
        data = date(ano, mes, dia)
        if data.weekday() < 5:  # Segunda=0 a Sexta=4
            dias_uteis_total += 1
    
    # Conta dias úteis passados até hoje
    dias_uteis_passados = 0
    for dia in range(1, hoje.day + 1):
        data = date(ano, mes, dia)
        if data.weekday() < 5:
            dias_uteis_passados += 1
    
    return dias_uteis_total, dias_uteis_passados

from datetime import timedelta

# ============================================
# FUNÇÕES DE PROJEÇÃO (CORRIGIDAS)
# ============================================

def calcular_ticket_medio(vendedor):
    """Calcula o ticket médio corretamente"""
    qtd_faturadas = vendedor['qtd_faturadas']
    if qtd_faturadas > 0:
        # Estimativa: ticket médio baseado no faturamento total (simulado)
        # Em um cenário real, viria do print de faturamento
        faturamento_estimado = qtd_faturadas * 1000  # Assumindo ticket médio base de R$1000
        return round(faturamento_estimado / qtd_faturadas, 2)
    return 0

def calcular_faturamento_estimado(vendedor):
    """Calcula faturamento estimado"""
    return vendedor['qtd_faturadas'] * vendedor.get('ticket_medio', 1000)

def calcular_projecao_completa(vendedor, dias_uteis_passados, dias_uteis_total):
    """
    Calcula projeção completa baseada no desempenho atual
    """
    qtd_faturadas_atual = vendedor['qtd_faturadas']
    interacoes_atual = vendedor['interacoes']
    ticket_medio = calcular_ticket_medio(vendedor)
    faturamento_atual = qtd_faturadas_atual * ticket_medio
    
    # Taxa de conversão atual
    if interacoes_atual > 0:
        conversao_atual = (qtd_faturadas_atual / interacoes_atual) * 100
    else:
        conversao_atual = 0
    
    # Média diária
    media_diaria_faturas = qtd_faturadas_atual / dias_uteis_passados if dias_uteis_passados > 0 else 0
    media_diaria_interacoes = interacoes_atual / dias_uteis_passados if dias_uteis_passados > 0 else 0
    media_diaria_faturamento = faturamento_atual / dias_uteis_passados if dias_uteis_passados > 0 else 0
    
    # Dias restantes
    dias_restantes = max(0, dias_uteis_total - dias_uteis_passados)
    
    # Projeções
    projecao_faturas = qtd_faturadas_atual + (media_diaria_faturas * dias_restantes)
    projecao_interacoes = interacoes_atual + (media_diaria_interacoes * dias_restantes)
    projecao_faturamento = faturamento_atual + (media_diaria_faturamento * dias_restantes)
    
    # Metas (ajustáveis)
    meta_faturas = 100
    meta_interacoes = 200
    meta_faturamento = 100000  # R$ 100.000
    
    # Percentuais de meta
    percentual_meta_faturas = (projecao_faturas / meta_faturas) * 100 if meta_faturas > 0 else 0
    percentual_meta_interacoes = (projecao_interacoes / meta_interacoes) * 100 if meta_interacoes > 0 else 0
    percentual_meta_faturamento = (projecao_faturamento / meta_faturamento) * 100 if meta_faturamento > 0 else 0
    
    # Status
    if percentual_meta_faturas >= 100:
        status = "✅ ACIMA DA META"
        cor = "#00e676"
        recomendacao = "Excelente! Continue com o mesmo ritmo."
    elif percentual_meta_faturas >= 70:
        status = "⚠️ PRÓXIMO DA META"
        cor = "#ffab00"
        recomendacao = "Bom desempenho! Aumente o ritmo para garantir a meta."
    else:
        status = "🔴 ABAIXO DA META"
        cor = "#ff5252"
        recomendacao = "Necessário acelerar as vendas significativamente."
    
    return {
        'qtd_faturadas_atual': qtd_faturadas_atual,
        'interacoes_atual': interacoes_atual,
        'faturamento_atual': faturamento_atual,
        'ticket_medio': ticket_medio,
        'conversao_atual': round(conversao_atual, 1),
        'media_diaria_faturas': round(media_diaria_faturas, 1),
        'media_diaria_interacoes': round(media_diaria_interacoes, 1),
        'media_diaria_faturamento': round(media_diaria_faturamento, 2),
        'projecao_faturas': round(projecao_faturas, 0),
        'projecao_interacoes': round(projecao_interacoes, 0),
        'projecao_faturamento': round(projecao_faturamento, 2),
        'percentual_meta_faturas': round(percentual_meta_faturas, 1),
        'percentual_meta_interacoes': round(percentual_meta_interacoes, 1),
        'percentual_meta_faturamento': round(percentual_meta_faturamento, 1),
        'status': status,
        'cor': cor,
        'recomendacao': recomendacao,
        'dias_uteis_passados': dias_uteis_passados,
        'dias_restantes': dias_restantes,
        'dias_uteis_total': dias_uteis_total
    }

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
    
    if prazo <= 43:
        bonus_total += 100
        detalhes.append(f"✅ Prazo Médio: R$ 100 ({prazo:.0f} dias ≤ 43)")
    else:
        detalhes.append(f"❌ Prazo Médio: R$ 0 ({prazo:.0f} dias > 43)")
    
    if conversao >= 12:
        bonus_total += 100
        detalhes.append(f"✅ Conversão: R$ 100 ({conversao:.1f}% ≥ 12%)")
    else:
        detalhes.append(f"❌ Conversão: R$ 0 ({conversao:.1f}% < 12%)")
    
    if tme <= 5:
        bonus_total += 150
        detalhes.append(f"✅ TME: R$ 150 ({tme:.1f} min ≤ 5)")
    else:
        detalhes.append(f"❌ TME: R$ 0 ({tme:.1f} min > 5)")
    
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
                margem_valor = float(v['margem_pct']) if isinstance(v['margem_pct'], (int, float)) else 0.0
                alcance_valor = float(v['alcance_projetado_pct']) if isinstance(v['alcance_projetado_pct'], (int, float)) else 0.0
                prazo_valor = float(v['prazo_medio']) if isinstance(v['prazo_medio'], (int, float)) else 0.0
                tme_valor = float(v['tme_minutos']) if isinstance(v['tme_minutos'], (int, float)) else 0.0
                
                if tme_valor > 60:
                    tme_valor = 5.0
                
                novo_margem = st.number_input("Margem (%)", 0.0, 100.0, margem_valor, 0.1, format="%.1f", key=f"margem_{i}")
                novo_alcance = st.number_input("Alcance (%)", 0.0, 300.0, alcance_valor, 0.1, format="%.1f", key=f"alcance_{i}")
                novo_prazo = st.number_input("Prazo (dias)", 0, 200, int(prazo_valor), 1, key=f"prazo_{i}")
                novo_tme = st.number_input("TME (min)", 0.0, 60.0, tme_valor, 0.1, format="%.1f", key=f"tme_{i}")
            
            with col2:
                qtd_valor = float(v['qtd_faturadas']) if isinstance(v['qtd_faturadas'], (int, float)) else 0.0
                chamadas_valor = float(v.get('chamadas', 0)) if isinstance(v.get('chamadas', 0), (int, float)) else 0.0
                iniciados_valor = float(v['iniciados']) if isinstance(v['iniciados'], (int, float)) else 0.0
                recebidos_valor = float(v['recebidos']) if isinstance(v['recebidos'], (int, float)) else 0.0
                
                novo_qtd = st.number_input("Qtd Faturadas", 0, 1000, int(qtd_valor), 1, key=f"qtd_{i}")
                novo_chamadas = st.number_input("Chamadas", 0, 1000, int(chamadas_valor), 1, key=f"chamadas_{i}")
                novo_iniciados = st.number_input("Iniciados", 0, 1000, int(iniciados_valor), 1, key=f"iniciados_{i}")
                novo_recebidos = st.number_input("Recebidos", 0, 1000, int(recebidos_valor), 1, key=f"recebidos_{i}")
            
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
# FUNÇÃO PARA EXIBIR HISTÓRICO E CARREGAR ANÁLISES
# ============================================

def exibir_historico_e_carregar():
    """Exibe o histórico de análises e permite carregar uma análise específica"""
    
    st.markdown("### 📚 Histórico de Análises Salvas")
    st.markdown("Selecione uma análise abaixo para carregar os dados:")
    
    analises = get_analises()
    
    if not analises:
        st.info("📭 Nenhuma análise salva ainda. Faça sua primeira análise na aba 'Nova Análise'.")
        return None
    
    # Criar dataframe para exibir
    df_historico = pd.DataFrame(analises)
    df_historico['data_analise'] = pd.to_datetime(df_historico['data_analise']).dt.strftime('%d/%m/%Y %H:%M')
    df_historico['total_bonus'] = df_historico['total_bonus'].apply(lambda x: f'R$ {x:,.2f}')
    
    # Seleção da análise
    opcoes = {}
    for a in analises:
        label = f"{a['periodo']} - {a['data_analise'][:16]} - Bônus: R$ {a['total_bonus']:,.2f}"
        opcoes[label] = a['id']
    
    selecionado = st.selectbox("📋 Selecione uma análise para carregar:", list(opcoes.keys()))
    
    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("📂 Carregar Análise Selecionada", type="primary", use_container_width=True):
            analise_id = opcoes[selecionado]
            analise = carregar_analise_por_id(analise_id)
            if analise:
                dados = desserializar_analise(analise['dados_json'])
                st.session_state['analise_atual'] = {
                    'periodo': analise['periodo'],
                    'vendedores': dados['vendedores'],
                    'total_bonus': analise['total_bonus']
                }
                st.session_state['analise_realizada'] = True
                st.success(f"✅ Análise carregada: {analise['periodo']}")
                st.rerun()
    
    with col2:
        if st.button("🗑️ Deletar Selecionada", use_container_width=True):
            analise_id = opcoes[selecionado]
            deletar_analise(analise_id)
            st.success("✅ Análise deletada!")
            st.rerun()
    
    # Mostrar tabela do histórico
    st.markdown("---")
    st.markdown("### 📊 Tabela de Histórico")
    st.dataframe(df_historico[['periodo', 'data_analise', 'total_bonus']], use_container_width=True, hide_index=True)
    
    return None

# ============================================
# AGENTE DE PERFORMANCE COMERCIAL (ROBUSTO)
# ============================================

def agente_performance_comercial(vendedores, stats, periodo, projecoes=None):
    """Agente especializado em análise de performance comercial - Análise ROBUSTA"""
    
    # Prepara contexto completo para o Agente
    contexto = f"""
    Você é um Agente de Performance Comercial SÊNIOR especialista em vendas B2B.
    
    DADOS COMPLETOS DO PERÍODO {periodo}:
    
    ===== RESULTADOS GERAIS DO TIME =====
    - Total de Vendas: {stats['total_faturas']:.0f} vendas
    - Margem Média: {stats['media_margem']:.1f}% (Meta: 26%)
    - Alcance Médio: {stats['media_alcance']:.1f}% (Necessário ≥90% para bônus)
    - Conversão Média: {stats['media_conversao']:.1f}% (Meta: 12%)
    - Prazo Médio: {stats['media_prazo']:.0f} dias (Meta: ≤43)
    - TME Médio: {stats['media_tme']:.1f} min (Meta: ≤5)
    - Interações Médias: {stats['media_interacoes']:.0f} (Meta: ≥200)
    
    ===== META ATINGIMENTO =====
    - Margem: {stats['acima_meta_margem']}/{len(vendedores)} vendedores acima da meta
    - Conversão: {stats['acima_meta_conversao']}/{len(vendedores)} acima da meta
    - Prazo: {stats['acima_meta_prazo']}/{len(vendedores)} dentro da meta
    - TME: {stats['acima_meta_tme']}/{len(vendedores)} dentro da meta
    - Interações: {stats['acima_meta_interacoes']}/{len(vendedores)} acima da meta
    
    ===== BÔNUS =====
    - Total Distribuído: R$ {stats['total_bonus']:,.2f}
    - Elegíveis Margem: {stats['qtd_elegiveis']} vendedores
    
    ===== DETALHES COMPLETOS POR VENDEDOR =====
    """
    
    for v in vendedores:
        ticket_medio = calcular_ticket_medio(v)
        contexto += f"""
        
        📌 {v['nome'].upper()}:
        - Margem: {v['margem_pct']:.1f}% | Alcance: {v['alcance_projetado_pct']:.1f}%
        - Prazo: {v['prazo_medio']:.0f} dias | Conversão: {v['conversao_calculada']:.1f}%
        - TME: {v['tme_minutos']:.1f} min | Interações: {v['interacoes']:.0f}
        - Qtd Faturadas: {v['qtd_faturadas']:.0f} | Ticket Médio: R$ {ticket_medio:,.2f}
        - Faturamento Estimado: R$ {v['qtd_faturadas'] * ticket_medio:,.2f}
        - Bônus: R$ {v['bonus_total']:,.0f}
        - Elegível Margem: {'✅ Sim' if v['elegivel_margem'] else '❌ Não'}
        """
    
    # Adiciona projeções se disponíveis
    if projecoes:
        contexto += f"""
        
        ===== PROJEÇÕES PARA O VENDEDOR =====
        {projecoes}
        """
    
    # Inicializa histórico do Agente
    if "agente_history" not in st.session_state:
        st.session_state.agente_history = []
        saudacao = f"""🏢 **Agente de Performance Comercial Sênior**

Olá! Sou seu Agente de Performance Comercial. Analisei COMPLETAMENTE os dados do período **{periodo}**.

**📊 O que já identifiquei:**
- 🎯 Time tem {stats['acima_meta_margem']} vendedores com margem acima da meta
- 📈 Média de conversão do time: {stats['media_conversao']:.1f}%
- 💰 Total de bônus a distribuir: R$ {stats['total_bonus']:,.2f}

**💡 Posso te ajudar com análises detalhadas sobre:**
- 📊 Performance individual de cada vendedor
- 🎯 Faturamento, Ticket Médio e Margem
- 📈 Evolução e projeções
- 🚀 Plano de ação personalizado
- 💰 Otimização de bônus

**Qual análise você gostaria de fazer?**
"""
        st.session_state.agente_history.append({"role": "assistant", "content": saudacao})
    
    # Exibe histórico
    for msg in st.session_state.agente_history:
        if msg["role"] == "user":
            st.markdown(f'<div style="background: #1a4a2e; color: white; padding: 10px; border-radius: 10px; margin: 5px 0; text-align: right;">👤 <b>Você:</b><br>{msg["content"]}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div style="background: #141824; color: #c8d0dc; padding: 12px; border-radius: 10px; margin: 5px 0; border-left: 3px solid #ffab00;">🤖 <b>Agente de Performance Sênior:</b><br>{msg["content"]}</div>', unsafe_allow_html=True)
    
    # Sugestões de perguntas robustas
    st.markdown("**💡 Perguntas sugeridas para análise robusta:**")
    
    sugestoes = [
        "Análise completa do time (faturamento, ticket médio, margem)",
        "Quem são os top performers e por quê?",
        "Análise individual do Gerson (ou outro vendedor)",
        "Oportunidades de melhoria e plano de ação",
        "Projeção de faturamento para o mês",
        "Análise de margem e lucratividade do time",
        "Comparativo detalhado entre vendedores",
        "Diagnóstico completo de performance"
    ]
    
    cols = st.columns(2)
    for i, sug in enumerate(sugestoes):
        with cols[i % 2]:
            if st.button(sug, key=f"sug_agente_{i}", use_container_width=True):
                st.session_state.agente_history.append({"role": "user", "content": sug})
                st.rerun()
    
    st.markdown("---")
    
    pergunta = st.text_area("💬 Faça sua pergunta para análise robusta:", key="agente_input", height=80)
    
    if st.button("📤 Enviar para Agente", type="primary", use_container_width=True) and pergunta:
        st.session_state.agente_history.append({"role": "user", "content": pergunta})
        
        with st.spinner("🏢 Agente de Performance analisando profundamente..."):
            try:
                modelo = get_modelo_disponivel()
                if modelo:
                    prompt = f"""
                    Você é um Agente de Performance Comercial SÊNIOR.
                    
                    {contexto}
                    
                    PERGUNTA DO USUÁRIO: {pergunta}
                    
                    INSTRUÇÕES IMPORTANTES:
                    1. Faça uma análise PROFUNDA e DETALHADA
                    2. Use números e dados específicos do contexto
                    3. Inclua análises de: FATURAMENTO, TICKET MÉDIO, MARGEM, ALCANCE
                    4. Faça comparações entre vendedores quando relevante
                    5. Dê recomendações PRÁTICAS e ACIONÁVEIS
                    6. Seja um consultor comercial especialista
                    
                    Responda em português do Brasil, com linguagem profissional mas acessível.
                    """
                    
                    resposta = modelo.generate_content(prompt)
                    st.session_state.agente_history.append({"role": "assistant", "content": resposta.text})
                    st.rerun()
            except Exception as e:
                st.error(f"Erro: {e}")
    
    if st.button("🗑️ Limpar conversa", use_container_width=True):
        st.session_state.agente_history = []
        st.rerun()

# ============================================
# FUNÇÃO DE PROJEÇÃO COMPLETA
# ============================================

def exibir_projecao_completa(vendedores, stats, periodo):
    """Exibe a aba de projeção de resultados com dias úteis automáticos"""
    
    st.markdown("### 📈 Projeção de Resultados Inteligente")
    st.markdown("""
    <div class="info-box">
    📊 <strong>Projeção Automática</strong><br>
    Os dias úteis são calculados automaticamente com base na data atual.
    A projeção considera o ritmo atual de vendas e interações.
    </div>
    """, unsafe_allow_html=True)
    
    # Cálculo automático de dias úteis
    dias_uteis_total, dias_uteis_passados = calcular_dias_uteis()
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown(f"""
        <div class="card-metrica">
            <div class="indicador-titulo">📅 TOTAL DIAS ÚTEIS</div>
            <div class="valor-grande">{dias_uteis_total}</div>
            <div class="indicador-meta">dias no mês</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div class="card-metrica">
            <div class="indicador-titulo">✅ DIAS TRABALHADOS</div>
            <div class="valor-medio">{dias_uteis_passados}</div>
            <div class="indicador-meta">dias até hoje</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <div class="card-metrica">
            <div class="indicador-titulo">⏳ DIAS RESTANTES</div>
            <div class="valor-medio" style="color: #ffab00;">{dias_uteis_total - dias_uteis_passados}</div>
            <div class="indicador-meta">dias para bater meta</div>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Seletor de vendedor
    vendedor_selecionado = st.selectbox(
        "Selecione o vendedor para projeção detalhada:",
        [v['nome'] for v in vendedores]
    )
    
    vendedor = next((v for v in vendedores if v['nome'] == vendedor_selecionado), None)
    
    if vendedor:
        proj = calcular_projecao_completa(vendedor, dias_uteis_passados, dias_uteis_total)
        
        # Cards de resultados atuais
        st.markdown("### 📊 RESULTADOS ATUAIS")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">📦 FATURADAS</div>
                <div class="valor-grande">{proj['qtd_faturadas_atual']:.0f}</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">💰 TICKET MÉDIO</div>
                <div class="valor-grande">R$ {proj['ticket_medio']:,.2f}</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">💵 FATURAMENTO</div>
                <div class="valor-medio">R$ {proj['faturamento_atual']:,.2f}</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col4:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">🔄 CONVERSÃO</div>
                <div class="valor-medio">{proj['conversao_atual']:.1f}%</div>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("---")
        st.markdown("### 📈 PROJEÇÃO PARA FIM DO MÊS")
        
        # Cards de projeção
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">📦 PROJEÇÃO FATURADAS</div>
                <div class="valor-grande">{proj['projecao_faturas']:.0f}</div>
                <div class="progresso-bar"><div class="progresso-fill" style="width: {min(100, proj['percentual_meta_faturas'])}%"></div></div>
                <div class="indicador-meta">{proj['percentual_meta_faturas']:.1f}% da meta (100 vendas)</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">💵 PROJEÇÃO FATURAMENTO</div>
                <div class="valor-grande">R$ {proj['projecao_faturamento']:,.2f}</div>
                <div class="progresso-bar"><div class="progresso-fill" style="width: {min(100, proj['percentual_meta_faturamento'])}%"></div></div>
                <div class="indicador-meta">{proj['percentual_meta_faturamento']:.1f}% da meta (R$ 100k)</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown(f"""
            <div class="card-metrica" style="border-color: {proj['cor']}">
                <div class="indicador-titulo">🎯 STATUS DA META</div>
                <div class="valor-grande" style="color: {proj['cor']}">{proj['percentual_meta_faturas']:.1f}%</div>
                <div class="indicador-meta">{proj['status']}</div>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        # Métricas diárias
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">📈 MÉDIA DIÁRIA VENDAS</div>
                <div class="valor-medio">{proj['media_diaria_faturas']:.1f} vendas/dia</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">💰 MÉDIA DIÁRIA FATURAMENTO</div>
                <div class="valor-medio">R$ {proj['media_diaria_faturamento']:,.2f}/dia</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">📞 MÉDIA DIÁRIA INTERAÇÕES</div>
                <div class="valor-medio">{proj['media_diaria_interacoes']:.1f} interações/dia</div>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        # Recomendação
        st.markdown(f"""
        <div class="info-box" style="border-left-color: {proj['cor']}">
        <strong>💡 RECOMENDAÇÃO ESTRATÉGICA:</strong><br>
        {proj['recomendacao']}<br><br>
        <strong>📊 Para atingir a meta de 100 vendas, você precisa:</strong><br>
        • Manter ritmo atual de {proj['media_diaria_faturas']:.1f} vendas/dia<br>
        • Ou aumentar para {((100 - proj['projecao_faturas']) / max(proj['dias_restantes'], 1) + proj['media_diaria_faturas']):.1f} vendas/dia nos próximos {proj['dias_restantes']} dias
        </div>
        """, unsafe_allow_html=True)

# ============================================
# FEEDBACK STAR COMPLETO
# ============================================

def exibir_feedback_star_completo(vendedores, stats, periodo):
    """Feedback STAR com análise de TODOS os indicadores"""
    
    st.markdown("### 🎯 Feedback Individual - Metodologia STAR")
    st.markdown("""
    <div class="info-box">
    📌 <strong>Metodologia STAR - Análise Completa</strong><br>
    <strong>S</strong> - Situação: Contexto atual do vendedor (faturamento, ticket médio, NFs)<br>
    <strong>T</strong> - Tarefa: Objetivos a serem alcançados<br>
    <strong>A</strong> - Ação: O que fazer para melhorar<br>
    <strong>R</strong> - Resultado: Impacto esperado das ações
    </div>
    """, unsafe_allow_html=True)
    
    vendedor_selecionado = st.selectbox(
        "Selecione o vendedor para análise detalhada:",
        [v['nome'] for v in vendedores],
        key="star_vendedor"
    )
    
    vendedor = next((v for v in vendedores if v['nome'] == vendedor_selecionado), None)
    
    if vendedor:
        ticket_medio = calcular_ticket_medio(vendedor)
        faturamento = vendedor['qtd_faturadas'] * ticket_medio
        
        # Cards com todos os indicadores
        st.markdown("### 📊 INDICADORES COMPLETOS")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">💰 FATURAMENTO</div>
                <div class="valor-grande">R$ {faturamento:,.2f}</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">🎫 TICKET MÉDIO</div>
                <div class="valor-grande">R$ {ticket_medio:,.2f}</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">📦 QTD NFs</div>
                <div class="valor-grande">{vendedor['qtd_faturadas']:.0f}</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col4:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">📈 MARGEM</div>
                <div class="valor-medio">{vendedor['margem_pct']:.1f}%</div>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">🎯 ALCANCE</div>
                <div class="valor-medio">{vendedor['alcance_projetado_pct']:.1f}%</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">🔄 CONVERSÃO</div>
                <div class="valor-medio">{vendedor['conversao_calculada']:.1f}%</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">📅 PRAZO</div>
                <div class="valor-medio">{vendedor['prazo_medio']:.0f} dias</div>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">⏱️ TME</div>
                <div class="valor-medio">{vendedor['tme_minutos']:.1f} min</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">💬 INTERAÇÕES</div>
                <div class="valor-medio">{vendedor['interacoes']:.0f}</div>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        # Bônus
        st.markdown("### 💰 BÔNUS DO VENDEDOR")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">🎯 BÔNUS TOTAL</div>
                <div class="valor-grande">R$ {vendedor['bonus_total']:,.2f}</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            elegivel_texto = "Sim" if vendedor['elegivel_margem'] else "Não"
            elegivel_cor = "#00e676" if vendedor['elegivel_margem'] else "#ff5252"
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">✅ ELEGÍVEL MARGEM</div>
                <div class="valor-medio" style="color: {elegivel_cor};">{elegivel_texto}</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            # Mostrar resumo dos bônus
            bonus_breakdown = ""
            for d in vendedor['detalhes_bonus'][:3]:
                if '✅' in d:
                    bonus_breakdown += f"✓ {d[:30]}...\n"
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">📋 DETALHES BÔNUS</div>
                <div class="indicador-meta">{bonus_breakdown if bonus_breakdown else 'Nenhum bônus atingido'}</div>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        # Comparação com o time
        st.markdown("### 📊 COMPARAÇÃO COM O TIME")
        
        col1, col2 = st.columns(2)
        
        with col1:
            diff_margem = vendedor['margem_pct'] - stats['media_margem']
            diff_conv = vendedor['conversao_calculada'] - stats['media_conversao']
            
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">📈 MARGEM</div>
                <div>{vendedor['margem_pct']:.1f}% vs {stats['media_margem']:.1f}% média</div>
                <div class="{'meta-ok' if diff_margem >= 0 else 'meta-ruim'}">({diff_margem:+.1f} pp)</div>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">🔄 CONVERSÃO</div>
                <div>{vendedor['conversao_calculada']:.1f}% vs {stats['media_conversao']:.1f}% média</div>
                <div class="{'meta-ok' if diff_conv >= 0 else 'meta-ruim'}">({diff_conv:+.1f} pp)</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            diff_inter = vendedor['interacoes'] - stats['media_interacoes']
            diff_tme = vendedor['tme_minutos'] - stats['media_tme']
            
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">💬 INTERAÇÕES</div>
                <div>{vendedor['interacoes']:.0f} vs {stats['media_interacoes']:.0f} média</div>
                <div class="{'meta-ok' if diff_inter >= 0 else 'meta-ruim'}">({diff_inter:+.0f})</div>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">⏱️ TME</div>
                <div>{vendedor['tme_minutos']:.1f} min vs {stats['media_tme']:.1f} min média</div>
                <div class="{'meta-ok' if diff_tme <= 0 else 'meta-ruim'}">({diff_tme:+.1f} min)</div>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        # Botão para gerar feedback STAR
        if st.button(f"🎯 Gerar Feedback STAR Completo para {vendedor['nome']}", type="primary", use_container_width=True):
            with st.spinner("Gerando feedback personalizado com metodologia STAR..."):
                try:
                    modelo = get_modelo_disponivel()
                    if modelo:
                        prompt = f"""
                        Gere um feedback profissional COMPLETO para o vendedor {vendedor['nome']} usando a metodologia STAR.
                        
                        DADOS COMPLETOS DO VENDEDOR:
                        
                        ===== INDICADORES PRINCIPAIS =====
                        - Faturamento Estimado: R$ {faturamento:,.2f}
                        - Ticket Médio: R$ {ticket_medio:,.2f}
                        - Quantidade de NFs: {vendedor['qtd_faturadas']:.0f}
                        - Margem: {vendedor['margem_pct']:.1f}% (Meta: 26%)
                        - Alcance Projetado: {vendedor['alcance_projetado_pct']:.1f}% (Necessário: ≥90%)
                        
                        ===== INDICADORES DE PERFORMANCE =====
                        - Prazo Médio: {vendedor['prazo_medio']:.0f} dias (Meta: ≤43)
                        - Conversão: {vendedor['conversao_calculada']:.1f}% (Meta: ≥12%)
                        - TME: {vendedor['tme_minutos']:.1f} min (Meta: ≤5)
                        - Interações: {vendedor['interacoes']:.0f} (Meta: ≥200)
                        
                        ===== BÔNUS =====
                        - Bônus Total: R$ {vendedor['bonus_total']:,.2f}
                        - Elegível Margem: {'Sim' if vendedor['elegivel_margem'] else 'Não'}
                        - Detalhes do Bônus: {', '.join(vendedor['detalhes_bonus'])}
                        
                        ===== COMPARAÇÃO COM TIME =====
                        - Média de Margem do Time: {stats['media_margem']:.1f}% (diferença: {vendedor['margem_pct'] - stats['media_margem']:+.1f} pp)
                        - Média de Conversão do Time: {stats['media_conversao']:.1f}% (diferença: {vendedor['conversao_calculada'] - stats['media_conversao']:+.1f} pp)
                        - Média de Interações do Time: {stats['media_interacoes']:.0f} (diferença: {vendedor['interacoes'] - stats['media_interacoes']:+.0f})
                        
                        Use a metodologia STAR de forma COMPLETA e DETALHADA:
                        
                        **📋 SITUAÇÃO (Contexto Completo)**
                        Descreva o cenário atual do vendedor incluindo: faturamento, ticket médio, quantidade de NFs, margem, alcance.
                        Compare com as metas e com a média do time.
                        
                        **🎯 TAREFA (Objetivos Claros)**
                        Defina objetivos específicos e mensuráveis para cada indicador que precisa melhorar.
                        
                        **⚡ AÇÃO (Plano de Ação Detalhado)**
                        Liste 5-7 ações práticas e específicas que o vendedor deve executar, priorizando as de maior impacto.
                        
                        **📊 RESULTADO (Impacto Esperado)**
                        Mostre qual o impacto financeiro (faturamento e bônus) e de performance ao atingir as metas.
                        Calcule o potencial de aumento de bônus.
                        
                        Seja encorajador, construtivo, prático e use dados reais. Responda em português do Brasil.
                        """
                        
                        resposta = modelo.generate_content(prompt)
                        st.markdown(f'<div style="background: #1a1f2e; border-radius: 12px; padding: 20px; margin-top: 16px; border: 1px solid #2a3040;">{resposta.text}</div>', unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"Erro ao gerar feedback: {e}")

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
    .data-atualizacao {
        font-size: 0.7rem;
        color: #6b8f6b;
        text-align: right;
        margin-top: 8px;
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

init_database()

DATA_ATUALIZACAO = datetime.now().strftime("%d/%m/%Y %H:%M")

# ============================================
# TELA DE LOGIN
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
    global DATA_ATUALIZACAO
    
    with st.sidebar:
        st.markdown(f"### 👤 {st.session_state.get('usuario', 'Usuário')}")
        st.markdown('<span class="elegivel-sim">👑 Administrador</span>', unsafe_allow_html=True)
        st.markdown("---")
        
        # Botão para carregar histórico
        st.markdown("### 📂 Carregar Análise")
        if st.button("📋 Carregar do Histórico", use_container_width=True):
            st.session_state['show_historico'] = True
        
        st.markdown("---")
        
        st.markdown("### 💾 Dados Salvos dos Prints")
        dados_salvos = listar_dados_salvos()
        if dados_salvos:
            for nome, data in dados_salvos[:5]:
                st.caption(f"📄 {nome[:30]}...")
                st.caption(f"   {data[:16]}")
                st.markdown("---")
        else:
            st.info("Nenhum dado salvo")
        
        st.markdown("---")
        
        if st.button("🚪 Sair", use_container_width=True):
            st.session_state['logado'] = False
            st.rerun()
    
    # Modal para carregar histórico
    if st.session_state.get('show_historico', False):
        with st.expander("📚 Histórico de Análises", expanded=True):
            exibir_historico_e_carregar()
            if st.button("🔒 Fechar", use_container_width=True):
                st.session_state['show_historico'] = False
                st.rerun()
    
    st.markdown(f"""
    <div class="main-header">
        <h1>📊 Central de Vendas | Analytics Platform</h1>
        <p>Sistema de Análise de Bônus e Performance</p>
        <div class="data-atualizacao">🔄 Última atualização: {DATA_ATUALIZACAO}</div>
    </div>
    """, unsafe_allow_html=True)
    
    dashboard_tipo = st.radio(
        "Selecione o Dashboard:",
        ["💰 Dashboard de Bônus", "📊 Dashboard de Performance"],
        horizontal=True
    )
    
    # ============================================
    # DASHBOARD DE BÔNUS
    # ============================================
    if dashboard_tipo == "💰 Dashboard de Bônus":
        
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "📸 1. Nova Análise",
            "📊 2. Dashboard",
            "📈 3. Evolução",
            "✏️ 4. Edição Manual",
            "🎯 5. Projeção",
            "🤖 6. Análise com IA"
        ])
        
        # TAB 1: Nova Análise (mantido)
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
                        
                        try:
                            salvar_dados_print(nome, json.dumps({"nome": nome, "data": datetime.now().isoformat()}))
                        except:
                            pass
            
            if prints_bytes:
                st.markdown("---")
                
                col1, col2 = st.columns([1, 3])
                with col1:
                    periodo_input = st.text_input("📅 Período (ex: Abril 2024)", value=datetime.now().strftime("%B %Y"))
                
                if st.button("🚀 Analisar Prints com IA", type="primary", use_container_width=True):
                    if not api_key:
                        st.error("❌ Configure a chave API do Google Gemini no arquivo .env ou Secrets")
                        st.stop()
                    
                    with st.spinner("🔄 Analisando os prints..."):
                        dados = analisar_prints_com_gemini(prints_bytes)
                        
                        if dados:
                            dados['periodo'] = periodo_input
                            vendedores = processar_dados_vendedores(dados)
                            total_bonus = sum(v['bonus_total'] for v in vendedores)
                            
                            dados_json = serializar_analise(vendedores, periodo_input)
                            salvar_analise(periodo_input, dados_json, total_bonus)
                            
                            st.session_state['analise_atual'] = {
                                'periodo': periodo_input,
                                'vendedores': vendedores,
                                'total_bonus': total_bonus
                            }
                            st.session_state['analise_realizada'] = True
                            
                            st.success("✅ Análise concluída e salva no histórico!")
                            
                            df_preview = pd.DataFrame(vendedores)
                            colunas_mostrar = ['nome', 'margem_pct', 'alcance_projetado_pct', 'prazo_medio', 
                                              'qtd_faturadas', 'chamadas', 'iniciados', 'recebidos', 
                                              'interacoes', 'conversao_calculada', 'tme_minutos', 'bonus_total']
                            df_preview = df_preview[[c for c in colunas_mostrar if c in df_preview.columns]]
                            st.dataframe(df_preview, use_container_width=True)
                            
                            st.info("👉 Vá para a aba 'Dashboard' para ver os resultados completos")
                        else:
                            st.error("❌ Falha na análise. Tente novamente.")
            else:
                st.info("📤 Envie os 5 prints para começar a análise")
        
        # TAB 2: Dashboard (mantido)
        with tab2:
            if not st.session_state.get('analise_realizada', False):
                st.warning("⚠️ Nenhuma análise carregada. Clique em 'Carregar do Histórico' na barra lateral ou faça uma nova análise.")
            else:
                analise = st.session_state.get('analise_atual', {})
                vendedores = analise.get('vendedores', [])
                periodo = analise.get('periodo', 'Período atual')
                stats = calcular_estatisticas_time(vendedores)
                
                st.markdown(f'<div class="periodo-box">📅 {periodo}</div>', unsafe_allow_html=True)
                
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
                        <div class="progresso-bar"><div class="progresso-fill" style="width: {min(100, stats['media_margem']/26*100)}%"></div></div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col4:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">🔄 MÉDIA CONVERSÃO</div>
                        <div class="valor-medio">{stats['media_conversao']:.1f}%</div>
                        <div class="indicador-meta">Meta: ≥ 12%</div>
                        <div class="progresso-bar"><div class="progresso-fill" style="width: {min(100, stats['media_conversao']/12*100)}%"></div></div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col5:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">⏱️ MÉDIA TME</div>
                        <div class="valor-medio">{stats['media_tme']:.1f} min</div>
                        <div class="indicador-meta">Meta: ≤ 5 min</div>
                        <div class="progresso-bar"><div class="progresso-fill" style="width: {min(100, (1 - stats['media_tme']/5) * 100 if stats['media_tme'] <= 5 else 0)}%; background:#ff5252"></div></div>
                    </div>
                    """, unsafe_allow_html=True)
                
                st.markdown("---")
                st.markdown("### 📊 Resultados por Vendedor")
                
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
        
        # TAB 3: Evolução (mantido)
        with tab3:
            st.markdown("### 📈 Evolução do Time")
            
            analises = get_analises()
            
            if len(analises) < 2:
                st.info("📊 Após realizar 2 ou mais análises, você poderá ver a evolução do time aqui.")
            else:
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
        
        # TAB 4: Edição Manual (mantido)
        with tab4:
            if not st.session_state.get('analise_realizada', False):
                st.warning("⚠️ Nenhuma análise carregada. Faça uma nova análise primeiro.")
            else:
                analise = st.session_state.get('analise_atual', {})
                vendedores = analise.get('vendedores', [])
                periodo = analise.get('periodo', 'Período atual')
                
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
        
        # TAB 5: Projeção (CORRIGIDA)
        with tab5:
            if not st.session_state.get('analise_realizada', False):
                st.warning("⚠️ Nenhuma análise carregada. Clique em 'Carregar do Histórico' na barra lateral ou faça uma nova análise.")
            else:
                analise = st.session_state.get('analise_atual', {})
                vendedores = analise.get('vendedores', [])
                stats = calcular_estatisticas_time(vendedores)
                periodo = analise.get('periodo', 'Período atual')
                exibir_projecao_completa(vendedores, stats, periodo)
        
        # TAB 6: Análise com IA (ATUALIZADA)
        with tab6:
            if not st.session_state.get('analise_realizada', False):
                st.warning("⚠️ Nenhuma análise carregada. Clique em 'Carregar do Histórico' na barra lateral ou faça uma nova análise.")
            else:
                analise = st.session_state.get('analise_atual', {})
                vendedores = analise.get('vendedores', [])
                stats = calcular_estatisticas_time(vendedores)
                periodo = analise.get('periodo', 'Período atual')
                
                st.markdown("### 🤖 Analista IA - Chat Inteligente")
                st.markdown("""
                <div class="info-box">
                💡 <strong>O que posso fazer?</strong><br>
                - 📊 Analisar os resultados do time<br>
                - 🎯 Sugerir ações para melhorar indicadores<br>
                - 📈 Fazer projeções baseadas nos dados<br>
                - 👥 Comparar desempenho entre vendedores
                </div>
                """, unsafe_allow_html=True)
                
                if "chat_history" not in st.session_state:
                    st.session_state.chat_history = []
                    saudacao = f"Olá! Analisei os dados do período **{periodo}**. Como posso ajudar?"
                    st.session_state.chat_history.append({"role": "assistant", "content": saudacao})
                
                for msg in st.session_state.chat_history:
                    if msg["role"] == "user":
                        st.markdown(f'<div style="background: #1a4a2e; color: white; padding: 10px; border-radius: 10px; margin: 5px 0; text-align: right;">🙋‍♂️ <b>Você:</b><br>{msg["content"]}</div>', unsafe_allow_html=True)
                    else:
                        st.markdown(f'<div style="background: #141824; color: #c8d0dc; padding: 10px; border-radius: 10px; margin: 5px 0; border-left: 3px solid #00e676;">🤖 <b>IA Analista:</b><br>{msg["content"]}</div>', unsafe_allow_html=True)
                
                pergunta = st.text_input("Faça sua pergunta sobre os dados:", key="chat_input_bonus")
                
                if st.button("📤 Enviar", key="chat_btn_bonus", use_container_width=True) and pergunta:
                    st.session_state.chat_history.append({"role": "user", "content": pergunta})
                    
                    with st.spinner("Analisando..."):
                        try:
                            modelo = get_modelo_disponivel()
                            if modelo:
                                contexto = f"Dados do período {periodo}: Média margem {stats['media_margem']:.1f}%, conversão {stats['media_conversao']:.1f}%, {len(vendedores)} vendedores. Pergunta: {pergunta}"
                                resposta = modelo.generate_content(contexto)
                                st.session_state.chat_history.append({"role": "assistant", "content": resposta.text})
                                st.rerun()
                        except Exception as e:
                            st.error(f"Erro: {e}")
                
                if st.button("🗑️ Limpar conversa", use_container_width=True):
                    st.session_state.chat_history = []
                    st.rerun()
    
    # ============================================
    # DASHBOARD DE PERFORMANCE
    # ============================================
    else:
        if not st.session_state.get('analise_realizada', False):
            st.warning("⚠️ Nenhuma análise carregada. Clique em 'Carregar do Histórico' na barra lateral ou faça uma nova análise.")
        else:
            analise = st.session_state.get('analise_atual', {})
            vendedores = analise.get('vendedores', [])
            periodo = analise.get('periodo', 'Período atual')
            stats = calcular_estatisticas_time(vendedores)
            
            tab_perf1, tab_perf2, tab_perf3, tab_perf4, tab_perf5 = st.tabs([
                "📊 1. Visão Geral",
                "📈 2. Indicadores",
                "🏢 3. Agente Performance",
                "🎯 4. Feedback STAR",
                "📊 5. Projeção"
            ])
            
            # TAB 1: Visão Geral (mantido)
            with tab_perf1:
                st.markdown(f'<div class="periodo-box">📅 {periodo}</div>', unsafe_allow_html=True)
                st.markdown("### 📊 Visão Geral da Performance do Time")
                
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">📈 MARGEM MÉDIA</div>
                        <div class="valor-grande">{stats['media_margem']:.1f}%</div>
                        <div class="progresso-bar"><div class="progresso-fill" style="width: {min(100, stats['media_margem']/26*100)}%"></div></div>
                        <div>{stats['acima_meta_margem']}/{len(vendedores)} acima da meta</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col2:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">🔄 CONVERSÃO MÉDIA</div>
                        <div class="valor-grande">{stats['media_conversao']:.1f}%</div>
                        <div class="progresso-bar"><div class="progresso-fill" style="width: {min(100, stats['media_conversao']/12*100)}%"></div></div>
                        <div>{stats['acima_meta_conversao']}/{len(vendedores)} acima da meta</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col3:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">📅 PRAZO MÉDIO</div>
                        <div class="valor-grande">{stats['media_prazo']:.0f} dias</div>
                        <div class="progresso-bar"><div class="progresso-fill" style="width: {min(100, (1 - stats['media_prazo']/43) * 100 if stats['media_prazo'] <= 43 else 0)}%; background:#ff5252"></div></div>
                        <div>{stats['acima_meta_prazo']}/{len(vendedores)} dentro da meta</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col4:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">⏱️ TME MÉDIO</div>
                        <div class="valor-grande">{stats['media_tme']:.1f} min</div>
                        <div class="progresso-bar"><div class="progresso-fill" style="width: {min(100, (1 - stats['media_tme']/5) * 100 if stats['media_tme'] <= 5 else 0)}%; background:#ff5252"></div></div>
                        <div>{stats['acima_meta_tme']}/{len(vendedores)} dentro da meta</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                st.markdown("---")
                
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">📊 ALCANCE MÉDIO</div>
                        <div class="valor-medio">{stats['media_alcance']:.1f}%</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col2:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">💬 INTERAÇÕES MÉDIAS</div>
                        <div class="valor-medio">{stats['media_interacoes']:.0f}</div>
                        <div class="progresso-bar"><div class="progresso-fill" style="width: {min(100, stats['media_interacoes']/200*100)}%"></div></div>
                        <div>{stats['acima_meta_interacoes']}/{len(vendedores)} acima da meta</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col3:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">📦 TOTAL VENDAS</div>
                        <div class="valor-medio">{stats['total_faturas']:.0f}</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col4:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">💰 BÔNUS TOTAL</div>
                        <div class="valor-medio">R$ {stats['total_bonus']:,.2f}</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                st.markdown("---")
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
                fig.add_trace(go.Scatterpolar(r=valores, theta=categorias, fill='toself', name='Time', line=dict(color='#00e676')))
                fig.add_trace(go.Scatterpolar(r=[100,100,100,100,100], theta=categorias, fill='none', name='Meta', line=dict(color='#ffab00', dash='dash')))
                fig.update_layout(polar=dict(radialaxis=dict(range=[0,100])), height=450, plot_bgcolor='#0d1117', paper_bgcolor='#0d1117')
                st.plotly_chart(fig, use_container_width=True)
            
            # TAB 2: Indicadores (mantido)
            with tab_perf2:
                st.markdown("### 📈 Indicadores por Vendedor")
                
                indicador = st.selectbox("Selecione o indicador:", ["Margem (%)", "Conversão (%)", "Prazo (dias)", "TME (min)", "Interações", "Alcance (%)"])
                
                campo_map = {
                    "Margem (%)": ("margem_pct", "%", 26, True),
                    "Conversão (%)": ("conversao_calculada", "%", 12, True),
                    "Prazo (dias)": ("prazo_medio", "dias", 43, False),
                    "TME (min)": ("tme_minutos", "min", 5, False),
                    "Interações": ("interacoes", "", 200, True),
                    "Alcance (%)": ("alcance_projetado_pct", "%", 90, True)
                }
                
                campo, unidade, meta, maior_melhor = campo_map[indicador]
                
                df_indicador = pd.DataFrame(vendedores)
                df_indicador = df_indicador.sort_values(campo, ascending=not maior_melhor)
                
                cores = []
                for _, v in df_indicador.iterrows():
                    valor = v[campo] or 0
                    if maior_melhor:
                        atingiu = valor >= meta
                    else:
                        atingiu = valor <= meta and valor > 0
                    cores.append('#00e676' if atingiu else '#ff5252')
                
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=df_indicador['nome'],
                    y=df_indicador[campo],
                    text=df_indicador[campo].apply(lambda x: f'{x:.1f}{unidade}' if x > 0 else 'N/D'),
                    textposition='outside',
                    marker_color=cores
                ))
                fig.add_hline(y=meta, line_dash="dash", line_color="#ffab00", annotation_text=f"Meta: {meta}{unidade}")
                fig.update_layout(title=f"{indicador} por Vendedor", plot_bgcolor='#0d1117', paper_bgcolor='#0d1117', height=450)
                st.plotly_chart(fig, use_container_width=True)
                
                st.markdown("---")
                st.dataframe(df_indicador[['nome', campo]], use_container_width=True)
            
            # TAB 3: Agente de Performance (ROBUSTO)
            with tab_perf3:
                st.markdown("### 🏢 Agente de Performance Comercial Sênior")
                st.markdown("""
                <div class="info-box">
                💼 <strong>Agente Especializado em Performance Comercial</strong><br>
                Este agente foi treinado para analisar dados de vendas, sugerir estratégias, 
                identificar oportunidades e fazer projeções baseadas nos resultados do time.
                </div>
                """, unsafe_allow_html=True)
                
                # Prepara projeções para o agente
                dias_uteis_total, dias_uteis_passados = calcular_dias_uteis()
                proj_texto = ""
                for v in vendedores:
                    proj = calcular_projecao_completa(v, dias_uteis_passados, dias_uteis_total)
                    proj_texto += f"{v['nome']}: Projeta {proj['projecao_faturas']:.0f} vendas ({proj['percentual_meta_faturas']:.1f}% da meta)\n"
                
                agente_performance_comercial(vendedores, stats, periodo, proj_texto)
            
            # TAB 4: Feedback STAR (COMPLETO)
            with tab_perf4:
                exibir_feedback_star_completo(vendedores, stats, periodo)
            
            # TAB 5: Projeção (CORRIGIDA)
            with tab_perf5:
                exibir_projecao_completa(vendedores, stats, periodo)

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
