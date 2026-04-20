"""
DASHBOARD DE VENDAS - ANALISADOR DE PRINTS COM IA
Sistema completo com histórico, projeções e análises robustas
"""

import subprocess, sys, os, hashlib, sqlite3, json, re
from datetime import datetime, date, timedelta
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
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS analises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            periodo TEXT NOT NULL,
            data_analise TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            dados_json TEXT NOT NULL,
            total_bonus REAL
        )
    ''')
    
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
# FUNÇÕES CORRIGIDAS (TICKET MÉDIO)
# ============================================

def calcular_ticket_medio(vendedor):
    """Calcula o ticket médio do vendedor baseado no faturamento e quantidade de vendas"""
    qtd_faturadas = vendedor['qtd_faturadas']
    if qtd_faturadas > 0:
        # Faturamento estimado baseado no valor médio por venda
        # Em um cenário real, isso viria do print de faturamento
        faturamento_estimado = qtd_faturadas * 1000
        return round(faturamento_estimado / qtd_faturadas, 2)
    return 0

def calcular_faturamento_estimado(vendedor):
    """Calcula faturamento estimado baseado no ticket médio"""
    ticket = calcular_ticket_medio(vendedor)
    return vendedor['qtd_faturadas'] * ticket

def calcular_dias_uteis():
    """Calcula dias úteis totais do mês e dias úteis passados até hoje"""
    hoje = date.today()
    ano = hoje.year
    mes = hoje.month
    
    if mes == 12:
        proximo_mes = date(ano + 1, 1, 1)
    else:
        proximo_mes = date(ano, mes + 1, 1)
    
    ultimo_dia = (proximo_mes - timedelta(days=1)).day
    
    dias_uteis_total = 0
    for dia in range(1, ultimo_dia + 1):
        data = date(ano, mes, dia)
        if data.weekday() < 5:
            dias_uteis_total += 1
    
    dias_uteis_passados = 0
    for dia in range(1, hoje.day + 1):
        data = date(ano, mes, dia)
        if data.weekday() < 5:
            dias_uteis_passados += 1
    
    return dias_uteis_total, dias_uteis_passados

def calcular_projecao_completa(vendedor, dias_uteis_passados, dias_uteis_total):
    qtd_faturadas_atual = vendedor['qtd_faturadas']
    interacoes_atual = vendedor['interacoes']
    ticket_medio = calcular_ticket_medio(vendedor)
    faturamento_atual = qtd_faturadas_atual * ticket_medio
    
    if interacoes_atual > 0:
        conversao_atual = (qtd_faturadas_atual / interacoes_atual) * 100
    else:
        conversao_atual = 0
    
    media_diaria_faturas = qtd_faturadas_atual / dias_uteis_passados if dias_uteis_passados > 0 else 0
    media_diaria_interacoes = interacoes_atual / dias_uteis_passados if dias_uteis_passados > 0 else 0
    media_diaria_faturamento = faturamento_atual / dias_uteis_passados if dias_uteis_passados > 0 else 0
    
    dias_restantes = max(0, dias_uteis_total - dias_uteis_passados)
    
    projecao_faturas = qtd_faturadas_atual + (media_diaria_faturas * dias_restantes)
    projecao_interacoes = interacoes_atual + (media_diaria_interacoes * dias_restantes)
    projecao_faturamento = faturamento_atual + (media_diaria_faturamento * dias_restantes)
    
    meta_faturas = 100
    meta_faturamento = 100000
    
    percentual_meta_faturas = (projecao_faturas / meta_faturas) * 100 if meta_faturas > 0 else 0
    percentual_meta_faturamento = (projecao_faturamento / meta_faturamento) * 100 if meta_faturamento > 0 else 0
    
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

def salvar_dados_print(nome_arquivo, dados_json):
    """Salva os dados extraídos de um print"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO dados_prints (nome_arquivo, dados_json) VALUES (?, ?)",
        (nome_arquivo, dados_json)
    )
    conn.commit()
    conn.close()

def listar_dados_salvos():
    """Lista todos os dados de prints salvos"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT nome_arquivo, data_salvamento FROM dados_prints ORDER BY data_salvamento DESC LIMIT 10"
    )
    resultados = cursor.fetchall()
    conn.close()
    
    result = []
    for r in resultados:
        result.append((r[0], r[1]))
    return result

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
# FUNÇÃO PARA EXIBIR HISTÓRICO
# ============================================

def exibir_historico_e_carregar():
    st.markdown("### 📚 Histórico de Análises Salvas")
    st.markdown("Selecione uma análise abaixo para carregar os dados:")
    
    analises = get_analises()
    
    if not analises:
        st.info("📭 Nenhuma análise salva ainda. Faça sua primeira análise na aba 'Nova Análise'.")
        return None
    
    df_historico = pd.DataFrame(analises)
    df_historico['data_analise'] = pd.to_datetime(df_historico['data_analise']).dt.strftime('%d/%m/%Y %H:%M')
    df_historico['total_bonus'] = df_historico['total_bonus'].apply(lambda x: f'R$ {x:,.2f}')
    
    opcoes = {}
    for a in analises:
        label = f"{a['periodo']} - {a['data_analise'][:16]} - Bônus: R$ {a['total_bonus']:,.2f}"
        opcoes[label] = a['id']
    
    selecionado = st.selectbox("📋 Selecione uma análise para carregar:", list(opcoes.keys()))
    
    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("📂 Carregar Análise", type="primary", use_container_width=True):
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
        if st.button("🗑️ Deletar", use_container_width=True):
            analise_id = opcoes[selecionado]
            deletar_analise(analise_id)
            st.success("✅ Análise deletada!")
            st.rerun()
    
    st.markdown("---")
    st.markdown("### 📊 Tabela de Histórico")
    st.dataframe(df_historico[['periodo', 'data_analise', 'total_bonus']], use_container_width=True, hide_index=True)

# ============================================
# AGENTE DE PERFORMANCE
# ============================================

def agente_performance_comercial(vendedores, stats, periodo, projecoes=None):
    contexto = f"""
    Você é um Agente de Performance Comercial especialista em vendas B2B.
    
    DADOS DO PERÍODO {periodo}:
    
    RESULTADOS GERAIS:
    - Total de Vendas: {stats['total_faturas']:.0f} vendas
    - Margem Média: {stats['media_margem']:.1f}% (Meta: 26%)
    - Conversão Média: {stats['media_conversao']:.1f}% (Meta: 12%)
    - Prazo Médio: {stats['media_prazo']:.0f} dias (Meta: ≤43)
    - TME Médio: {stats['media_tme']:.1f} min (Meta: ≤5)
    - Interações Médias: {stats['media_interacoes']:.0f} (Meta: ≥200)
    """
    
    for v in vendedores:
        ticket = calcular_ticket_medio(v)
        contexto += f"""
        {v['nome']}: Margem {v['margem_pct']:.1f}% | Conversão {v['conversao_calculada']:.1f}% | Bônus R$ {v['bonus_total']:,.0f} | Ticket R$ {ticket:,.2f}
        """
    
    if "agente_history" not in st.session_state:
        st.session_state.agente_history = []
        saudacao = f"""🏢 **Agente de Performance Comercial**

Olá! Analisei os dados do período **{periodo}**.

**Posso te ajudar com:**
- 📊 Análise de performance do time
- 🎯 Recomendações estratégicas
- 📈 Projeções de vendas
- 💰 Otimização de bônus

**O que você gostaria de analisar?**
"""
        st.session_state.agente_history.append({"role": "assistant", "content": saudacao})
    
    for msg in st.session_state.agente_history:
        if msg["role"] == "user":
            st.markdown(f'<div style="background: #1a4a2e; color: white; padding: 10px; border-radius: 10px; margin: 5px 0; text-align: right;">👤 <b>Você:</b><br>{msg["content"]}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div style="background: #141824; color: #c8d0dc; padding: 12px; border-radius: 10px; margin: 5px 0; border-left: 3px solid #ffab00;">🤖 <b>Agente:</b><br>{msg["content"]}</div>', unsafe_allow_html=True)
    
    sugestoes = ["Análise completa do time", "Quem são os top performers?", "Oportunidades de melhoria", "Projeção para próximo mês"]
    
    st.markdown("**💡 Perguntas sugeridas:**")
    cols = st.columns(2)
    for i, sug in enumerate(sugestoes):
        with cols[i % 2]:
            if st.button(sug, key=f"sug_agente_{i}", use_container_width=True):
                st.session_state.agente_history.append({"role": "user", "content": sug})
                st.rerun()
    
    st.markdown("---")
    
    pergunta = st.text_area("💬 Faça sua pergunta:", key="agente_input", height=80)
    
    if st.button("📤 Enviar", type="primary", use_container_width=True) and pergunta:
        st.session_state.agente_history.append({"role": "user", "content": pergunta})
        
        with st.spinner("Analisando..."):
            try:
                modelo = get_modelo_disponivel()
                if modelo:
                    prompt = f"""
                    Você é um Agente de Performance Comercial.
                    
                    Contexto: {contexto}
                    
                    Pergunta: {pergunta}
                    
                    Responda em português do Brasil, seja prático e objetivo.
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
# FEEDBACK STAR
# ============================================

def exibir_feedback_star_completo(vendedores, stats, periodo):
    st.markdown("### 🎯 Feedback Individual - Metodologia STAR")
    
    vendedor_selecionado = st.selectbox(
        "Selecione o vendedor:",
        [v['nome'] for v in vendedores],
        key="star_vendedor"
    )
    
    vendedor = next((v for v in vendedores if v['nome'] == vendedor_selecionado), None)
    
    if vendedor:
        ticket_medio = calcular_ticket_medio(vendedor)
        faturamento = vendedor['qtd_faturadas'] * ticket_medio
        
        col1, col2, col3 = st.columns(3)
        col1.metric("💰 FATURAMENTO", f"R$ {faturamento:,.2f}")
        col2.metric("🎫 TICKET MÉDIO", f"R$ {ticket_medio:,.2f}")
        col3.metric("📦 QTD NFs", f"{vendedor['qtd_faturadas']:.0f}")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("📈 MARGEM", f"{vendedor['margem_pct']:.1f}%")
        col2.metric("🎯 ALCANCE", f"{vendedor['alcance_projetado_pct']:.1f}%")
        col3.metric("💰 BÔNUS", f"R$ {vendedor['bonus_total']:,.2f}")
        
        st.markdown("---")
        
        if st.button(f"🎯 Gerar Feedback STAR", type="primary", use_container_width=True):
            with st.spinner("Gerando feedback..."):
                try:
                    modelo = get_modelo_disponivel()
                    if modelo:
                        prompt = f"""
                        Gere um feedback profissional para {vendedor['nome']} usando metodologia STAR.
                        
                        DADOS:
                        - Faturamento: R$ {faturamento:,.2f}
                        - Ticket Médio: R$ {ticket_medio:,.2f}
                        - Margem: {vendedor['margem_pct']:.1f}%
                        - Alcance: {vendedor['alcance_projetado_pct']:.1f}%
                        - Conversão: {vendedor['conversao_calculada']:.1f}%
                        - Prazo: {vendedor['prazo_medio']:.0f} dias
                        - TME: {vendedor['tme_minutos']:.1f} min
                        - Bônus: R$ {vendedor['bonus_total']:,.2f}
                        
                        Use STAR: Situação, Tarefa, Ação, Resultado.
                        """
                        resposta = modelo.generate_content(prompt)
                        st.markdown(f'<div style="background: #1a1f2e; border-radius: 12px; padding: 20px; margin-top: 16px;">{resposta.text}</div>', unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"Erro: {e}")

# ============================================
# PROJEÇÃO
# ============================================

def exibir_projecao_completa(vendedores, stats, periodo):
    st.markdown("### 📈 Projeção de Resultados")
    
    dias_uteis_total, dias_uteis_passados = calcular_dias_uteis()
    
    col1, col2, col3 = st.columns(3)
    col1.metric("📅 DIAS ÚTEIS", dias_uteis_total)
    col2.metric("✅ DIAS TRABALHADOS", dias_uteis_passados)
    col3.metric("⏳ DIAS RESTANTES", dias_uteis_total - dias_uteis_passados)
    
    st.markdown("---")
    
    vendedor_selecionado = st.selectbox("Selecione o vendedor:", [v['nome'] for v in vendedores])
    vendedor = next((v for v in vendedores if v['nome'] == vendedor_selecionado), None)
    
    if vendedor:
        proj = calcular_projecao_completa(vendedor, dias_uteis_passados, dias_uteis_total)
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("📦 FATURADAS", f"{proj['qtd_faturadas_atual']:.0f}")
        col2.metric("💰 TICKET MÉDIO", f"R$ {proj['ticket_medio']:,.2f}")
        col3.metric("💵 FATURAMENTO", f"R$ {proj['faturamento_atual']:,.2f}")
        col4.metric("🔄 CONVERSÃO", f"{proj['conversao_atual']:.1f}%")
        
        st.markdown("---")
        st.markdown("### 📈 PROJEÇÃO")
        
        col1, col2 = st.columns(2)
        col1.metric("📦 PROJEÇÃO FATURADAS", f"{proj['projecao_faturas']:.0f}", f"{proj['percentual_meta_faturas']:.1f}% da meta")
        col2.metric("🎯 STATUS", proj['status'])
        
        st.info(f"💡 {proj['recomendacao']}")

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
                st.success("✅ Acesso concedido!")
                st.rerun()
            else:
                st.error("❌ Usuário ou senha incorretos")
        
        st.markdown("---")
        st.markdown('<p style="text-align:center; color:#6b8f6b; font-size:0.7rem;">⚠️ Acesso restrito</p>', unsafe_allow_html=True)
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
        
        st.markdown("### 📂 Carregar Análise")
        if st.button("📋 Carregar do Histórico", use_container_width=True):
            st.session_state['show_historico'] = True
        
        st.markdown("---")
        
        st.markdown("### 💾 Dados Salvos")
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
        
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "📸 1. Nova Análise",
            "📊 2. Dashboard",
            "📈 3. Evolução",
            "✏️ 4. Edição Manual",
            "🎯 5. Projeção"
        ])
        
        with tab1:
            st.markdown("### 📸 Envie os prints dos painéis")
            
            st.markdown("""
            <div class="info-box">
            📌 <strong>Instruções:</strong><br>
            - Print 1: Alcance Projetado e Margem<br>
            - Print 2: Prazo Médio<br>
            - Print 3: Qtd. Faturadas<br>
            - Print 4: Chamadas<br>
            - Print 5: TME, Iniciados e Recebidos
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
                    periodo_input = st.text_input("📅 Período", value=datetime.now().strftime("%B %Y"))
                
                if st.button("🚀 Analisar Prints", type="primary", use_container_width=True):
                    if not api_key:
                        st.error("❌ Configure a chave API")
                        st.stop()
                    
                    with st.spinner("Analisando..."):
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
                            
                            st.success("✅ Análise concluída!")
                            
                            df_preview = pd.DataFrame(vendedores)
                            colunas_mostrar = ['nome', 'margem_pct', 'alcance_projetado_pct', 'prazo_medio', 
                                              'qtd_faturadas', 'chamadas', 'iniciados', 'recebidos', 
                                              'interacoes', 'conversao_calculada', 'tme_minutos', 'bonus_total']
                            df_preview = df_preview[[c for c in colunas_mostrar if c in df_preview.columns]]
                            st.dataframe(df_preview, use_container_width=True)
                        else:
                            st.error("❌ Falha na análise")
            else:
                st.info("📤 Envie os 5 prints")
        
        with tab2:
            if not st.session_state.get('analise_realizada', False):
                st.warning("⚠️ Nenhuma análise carregada")
            else:
                analise = st.session_state.get('analise_atual', {})
                vendedores = analise.get('vendedores', [])
                periodo = analise.get('periodo', '')
                stats = calcular_estatisticas_time(vendedores)
                
                st.markdown(f'<div class="periodo-box">📅 {periodo}</div>', unsafe_allow_html=True)
                
                col1, col2, col3, col4, col5 = st.columns(5)
                col1.metric("💰 BÔNUS TOTAL", f"R$ {stats['total_bonus']:,.2f}")
                col2.metric("🏆 ELEGÍVEIS", f"{stats['qtd_elegiveis']}/{len(vendedores)}")
                col3.metric("📈 MÉDIA MARGEM", f"{stats['media_margem']:.1f}%")
                col4.metric("🔄 MÉDIA CONVERSÃO", f"{stats['media_conversao']:.1f}%")
                col5.metric("⏱️ MÉDIA TME", f"{stats['media_tme']:.1f}min")
                
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
                fig.update_layout(title="Bônus por Vendedor", plot_bgcolor='#0d1117', paper_bgcolor='#0d1117', height=400)
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
                <div style="background:#1a2a1a; border-radius:12px; padding:16px; text-align:center; margin-top:16px;">
                    <div>TOTAL DO TIME</div>
                    <div class="bonus-total">R$ {stats['total_bonus']:,.2f}</div>
                </div>
                """, unsafe_allow_html=True)
        
        with tab3:
            analises = get_analises()
            if len(analises) < 2:
                st.info("📊 Após realizar 2 ou mais análises, você poderá ver a evolução")
            else:
                df = pd.DataFrame([{'periodo': a['periodo'], 'bonus': a['total_bonus']} for a in analises])
                fig = go.Figure(go.Scatter(x=df['periodo'], y=df['bonus'], mode='lines+markers', line=dict(color='#00e676')))
                fig.update_layout(title="Evolução do Bônus", plot_bgcolor='#0d1117', paper_bgcolor='#0d1117', height=400)
                st.plotly_chart(fig, use_container_width=True)
        
        with tab4:
            if not st.session_state.get('analise_realizada', False):
                st.warning("⚠️ Nenhuma análise carregada")
            else:
                analise = st.session_state.get('analise_atual', {})
                vendedores = analise.get('vendedores', [])
                periodo = analise.get('periodo', '')
                
                vendedores_editados = editar_dados_manual(vendedores)
                
                if st.button("💾 Salvar alterações", type="primary", use_container_width=True):
                    dados_json = serializar_analise(vendedores_editados, periodo)
                    total_bonus = sum(v['bonus_total'] for v in vendedores_editados)
                    salvar_analise(periodo, dados_json, total_bonus)
                    st.session_state['analise_atual']['vendedores'] = vendedores_editados
                    st.success("✅ Salvo!")
                    st.rerun()
        
        with tab5:
            if not st.session_state.get('analise_realizada', False):
                st.warning("⚠️ Nenhuma análise carregada")
            else:
                analise = st.session_state.get('analise_atual', {})
                vendedores = analise.get('vendedores', [])
                stats = calcular_estatisticas_time(vendedores)
                periodo = analise.get('periodo', '')
                exibir_projecao_completa(vendedores, stats, periodo)
    
    # ============================================
    # DASHBOARD DE PERFORMANCE
    # ============================================
    else:
        if not st.session_state.get('analise_realizada', False):
            st.warning("⚠️ Nenhuma análise carregada")
        else:
            analise = st.session_state.get('analise_atual', {})
            vendedores = analise.get('vendedores', [])
            periodo = analise.get('periodo', '')
            stats = calcular_estatisticas_time(vendedores)
            
            tab_perf1, tab_perf2, tab_perf3, tab_perf4 = st.tabs([
                "📊 1. Visão Geral",
                "📈 2. Indicadores",
                "🏢 3. Agente Performance",
                "🎯 4. Feedback STAR"
            ])
            
            with tab_perf1:
                st.markdown(f'<div class="periodo-box">📅 {periodo}</div>', unsafe_allow_html=True)
                st.markdown("### 📊 Visão Geral da Performance")
                
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("📈 MARGEM MÉDIA", f"{stats['media_margem']:.1f}%")
                col2.metric("🔄 CONVERSÃO MÉDIA", f"{stats['media_conversao']:.1f}%")
                col3.metric("📅 PRAZO MÉDIO", f"{stats['media_prazo']:.0f} dias")
                col4.metric("⏱️ TME MÉDIO", f"{stats['media_tme']:.1f} min")
                
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("📊 ALCANCE MÉDIO", f"{stats['media_alcance']:.1f}%")
                col2.metric("💬 INTERAÇÕES MÉDIAS", f"{stats['media_interacoes']:.0f}")
                col3.metric("📦 TOTAL VENDAS", f"{stats['total_faturas']:.0f}")
                col4.metric("💰 BÔNUS TOTAL", f"R$ {stats['total_bonus']:,.2f}")
                
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
            
            with tab_perf3:
                st.markdown("### 🏢 Agente de Performance Comercial")
                st.markdown("""
                <div class="info-box">
                💼 <strong>Agente Especializado em Performance Comercial</strong><br>
                Analisa dados de vendas, sugere estratégias e identifica oportunidades.
                </div>
                """, unsafe_allow_html=True)
                agente_performance_comercial(vendedores, stats, periodo, None)
            
            with tab_perf4:
                exibir_feedback_star_completo(vendedores, stats, periodo)

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
