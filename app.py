"""
DASHBOARD DE VENDAS - ANALISADOR DE PRINTS COM IA
Sistema completo com projeções, salvamento de dados, exportação de feedback STAR para PDF
e simulador de metas mensais
"""

import sys, os, sqlite3, json, re
from datetime import datetime
from io import BytesIO

# Importações diretas (sem instalação automática)
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import google.generativeai as genai
import PIL.Image
from dotenv import load_dotenv
from fpdf import FPDF

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
    
    # Tabela de análises
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS analises (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            periodo TEXT NOT NULL,
            data_analise TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            dados_json TEXT NOT NULL,
            total_bonus REAL
        )
    ''')
    
    # Tabela para salvar dados dos prints (persistência)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS dados_prints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_arquivo TEXT NOT NULL,
            dados_json TEXT NOT NULL,
            data_salvamento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabela para armazenar a última análise ativa
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ultima_analise (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            analise_id INTEGER NOT NULL,
            data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (analise_id) REFERENCES analises(id) ON DELETE CASCADE
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
    
    # Se a análise deletada era a última ativa, limpar referência
    ultima = carregar_ultima_analise()
    if ultima and ultima['id'] == analise_id:
        limpar_ultima_analise()

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
# FUNÇÕES PARA GERENCIAR A ÚLTIMA ANÁLISE ATIVA
# ============================================

def salvar_ultima_analise(analise_id):
    """Salva o ID da análise que deve ser carregada automaticamente na próxima execução"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO ultima_analise (id, analise_id, data_atualizacao)
        VALUES (1, ?, CURRENT_TIMESTAMP)
    ''', (analise_id,))
    conn.commit()
    conn.close()

def carregar_ultima_analise():
    """Retorna a última análise ativa salva, ou None"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT analise_id FROM ultima_analise WHERE id = 1
    ''')
    resultado = cursor.fetchone()
    conn.close()
    if resultado:
        analise_id = resultado[0]
        return carregar_analise_por_id(analise_id)
    return None

def limpar_ultima_analise():
    """Remove a referência à última análise (usado quando a análise é deletada)"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM ultima_analise WHERE id = 1')
    conn.commit()
    conn.close()

def atualizar_ultima_analise_se_necessario(analise_id):
    """Atualiza a última análise apenas se não for a mesma já salva, para evitar escrita desnecessária"""
    atual = carregar_ultima_analise()
    if not atual or atual['id'] != analise_id:
        salvar_ultima_analise(analise_id)

# ============================================
# FUNÇÕES PARA SALVAR/CARREGAR DADOS DOS PRINTS
# ============================================

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

def carregar_dados_print(nome_arquivo):
    """Carrega dados salvos de um print específico"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT dados_json FROM dados_prints WHERE nome_arquivo = ? ORDER BY data_salvamento DESC LIMIT 1",
        (nome_arquivo,)
    )
    resultado = cursor.fetchone()
    conn.close()
    if resultado:
        return json.loads(resultado[0])
    return None

def listar_dados_salvos():
    """Lista todos os dados de prints salvos"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT nome_arquivo, data_salvamento FROM dados_prints ORDER BY data_salvamento DESC"
    )
    resultados = cursor.fetchall()
    conn.close()
    return resultados

# ============================================
# FUNÇÕES DE PROJEÇÃO
# ============================================

def calcular_projecao(vendedor, dias_uteis_trabalhados, dias_uteis_total):
    """
    Calcula projeção de resultados baseado no desempenho atual
    """
    qtd_faturadas_atual = vendedor['qtd_faturadas']
    interacoes_atual = vendedor['interacoes']
    
    # Taxa de conversão atual
    if interacoes_atual > 0:
        conversao_atual = (qtd_faturadas_atual / interacoes_atual) * 100
    else:
        conversao_atual = 0
    
    # Média diária
    media_diaria_faturas = qtd_faturadas_atual / dias_uteis_trabalhados if dias_uteis_trabalhados > 0 else 0
    media_diaria_interacoes = interacoes_atual / dias_uteis_trabalhados if dias_uteis_trabalhados > 0 else 0
    
    # Projeção para o mês
    dias_restantes = max(0, dias_uteis_total - dias_uteis_trabalhados)
    projecao_faturas = qtd_faturadas_atual + (media_diaria_faturas * dias_restantes)
    projecao_interacoes = interacoes_atual + (media_diaria_interacoes * dias_restantes)
    
    # Cálculo do percentual de meta
    # Meta base: 100 faturas/mês (ajustável)
    meta_faturas = 100
    percentual_meta = (projecao_faturas / meta_faturas) * 100 if meta_faturas > 0 else 0
    
    # Ticket médio (faturamento / NFs faturadas)
    faturamento = vendedor.get('faturamento', 0)
    if qtd_faturadas_atual > 0 and faturamento > 0:
        ticket_medio = faturamento / qtd_faturadas_atual
    else:
        ticket_medio = 0
    
    # Avaliação do resultado
    if percentual_meta >= 100:
        status = "✅ ACIMA DA META"
        cor = "#00e676"
        recomendacao = "Excelente! Continue com o mesmo ritmo."
    elif percentual_meta >= 70:
        status = "⚠️ PRÓXIMO DA META"
        cor = "#ffab00"
        recomendacao = "Bom desempenho! Aumente o ritmo para garantir a meta."
    else:
        status = "🔴 ABAIXO DA META"
        cor = "#ff5252"
        recomendacao = "Necessário acelerar as vendas e interações."
    
    return {
        'qtd_faturadas_atual': qtd_faturadas_atual,
        'interacoes_atual': interacoes_atual,
        'conversao_atual': round(conversao_atual, 1),
        'media_diaria_faturas': round(media_diaria_faturas, 1),
        'media_diaria_interacoes': round(media_diaria_interacoes, 1),
        'projecao_faturas': round(projecao_faturas, 0),
        'projecao_interacoes': round(projecao_interacoes, 0),
        'percentual_meta': round(percentual_meta, 1),
        'ticket_medio': round(ticket_medio, 2),
        'status': status,
        'cor': cor,
        'recomendacao': recomendacao,
        'dias_restantes': dias_restantes
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
        'acima_meta_interacoes': sum(1 for v in vendedores if v['interacoes'] >= 200),
        'media_meta_venda_avista': round(sum(v.get('meta_venda_avista', 0) for v in vendedores) / len(vendedores), 1) if vendedores else 0,
        'media_percentual_meta': round(sum(v.get('percentual_meta', 0) for v in vendedores) / len(vendedores), 1) if vendedores else 0,
        'media_percentual_venda_avista': round(sum(v.get('percentual_venda_avista', 0) for v in vendedores) / len(vendedores), 1) if vendedores else 0,
        'media_desconto': round(sum(v.get('desconto', 0) for v in vendedores) / len(vendedores), 1) if vendedores else 0,
        'total_desconto_qtd': sum(v.get('desconto_qtd', 0) for v in vendedores),
        'total_faturamento': sum(v.get('faturamento', 0) for v in vendedores)
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
                "recebidos": 0,
                "meta_venda_avista": 0.0,
                "percentual_meta": 0.0,
                "percentual_venda_avista": 0.0,
                "desconto": 0.0,
                "desconto_qtd": 0,
                "faturamento": 0.0
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
        
        # NOVOS CAMPOS
        meta_venda_avista = v.get('meta_venda_avista', 0) or 0
        percentual_meta = v.get('percentual_meta', 0) or 0
        percentual_venda_avista = v.get('percentual_venda_avista', 0) or 0
        desconto = v.get('desconto', 0) or 0
        desconto_qtd = v.get('desconto_qtd', 0) or 0
        faturamento = v.get('faturamento', 0) or 0
        
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
            'elegivel_margem': elegivel_margem,
            'meta_venda_avista': meta_venda_avista,
            'percentual_meta': percentual_meta,
            'percentual_venda_avista': percentual_venda_avista,
            'desconto': desconto,
            'desconto_qtd': desconto_qtd,
            'faturamento': faturamento
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
                'detalhes_bonus': ["⚠️ Dados não encontrados nos prints"],
                'meta_venda_avista': 0,
                'percentual_meta': 0,
                'percentual_venda_avista': 0,
                'desconto': 0,
                'desconto_qtd': 0,
                'faturamento': 0
            })
    
    return vendedores_processados

# ============================================
# FUNÇÃO EDIÇÃO MANUAL (CORRIGIDA)
# ============================================

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
                if tme_valor < 0:
                    tme_valor = 0.0
                
                novo_margem = st.number_input("Margem (%)", 0.0, 100.0, margem_valor, 0.1, format="%.1f", key=f"margem_{i}")
                novo_alcance = st.number_input("Alcance (%)", 0.0, 300.0, alcance_valor, 0.1, format="%.1f", key=f"alcance_{i}")
                novo_prazo = st.number_input("Prazo (dias)", 0, 200, int(prazo_valor), 1, key=f"prazo_{i}")
                novo_tme = st.number_input("TME (min)", 0.0, 60.0, tme_valor, 0.1, format="%.1f", key=f"tme_{i}")
            
            with col2:
                qtd_valor = float(v['qtd_faturadas']) if isinstance(v['qtd_faturadas'], (int, float)) else 0.0
                chamadas_valor = float(v.get('chamadas', 0)) if isinstance(v.get('chamadas', 0), (int, float)) else 0.0
                iniciados_valor = float(v['iniciados']) if isinstance(v['iniciados'], (int, float)) else 0.0
                recebidos_valor = float(v['recebidos']) if isinstance(v['recebidos'], (int, float)) else 0.0
                
                meta_avista_valor = float(v.get('meta_venda_avista', 0)) if isinstance(v.get('meta_venda_avista', 0), (int, float)) else 0.0
                if meta_avista_valor < 0:
                    meta_avista_valor = 0.0
                    
                perc_meta_valor = float(v.get('percentual_meta', 0)) if isinstance(v.get('percentual_meta', 0), (int, float)) else 0.0
                if perc_meta_valor > 100:
                    perc_meta_valor = 100.0
                if perc_meta_valor < 0:
                    perc_meta_valor = 0.0
                    
                perc_avista_valor = float(v.get('percentual_venda_avista', 0)) if isinstance(v.get('percentual_venda_avista', 0), (int, float)) else 0.0
                if perc_avista_valor > 100:
                    perc_avista_valor = 100.0
                if perc_avista_valor < 0:
                    perc_avista_valor = 0.0
                    
                desconto_valor = float(v.get('desconto', 0)) if isinstance(v.get('desconto', 0), (int, float)) else 0.0
                if desconto_valor > 100:
                    desconto_valor = 100.0
                if desconto_valor < 0:
                    desconto_valor = 0.0
                    
                desconto_qtd_valor = float(v.get('desconto_qtd', 0)) if isinstance(v.get('desconto_qtd', 0), (int, float)) else 0.0
                if desconto_qtd_valor < 0:
                    desconto_qtd_valor = 0.0
                    
                faturamento_valor = float(v.get('faturamento', 0)) if isinstance(v.get('faturamento', 0), (int, float)) else 0.0
                if faturamento_valor < 0:
                    faturamento_valor = 0.0
                
                novo_qtd = st.number_input("Qtd Faturadas", 0, 1000, int(qtd_valor), 1, key=f"qtd_{i}")
                novo_chamadas = st.number_input("Chamadas", 0, 1000, int(chamadas_valor), 1, key=f"chamadas_{i}")
                novo_iniciados = st.number_input("Iniciados", 0, 1000, int(iniciados_valor), 1, key=f"iniciados_{i}")
                novo_recebidos = st.number_input("Recebidos", 0, 1000, int(recebidos_valor), 1, key=f"recebidos_{i}")
                
                st.markdown("---")
                st.markdown("**📊 Novos Indicadores:**")
                
                novo_meta_avista = st.number_input("Meta Venda à Vista", 0.0, 1000000.0, meta_avista_valor, 100.0, format="%.0f", key=f"meta_avista_{i}")
                valor_perc_meta = min(perc_meta_valor, 100.0)
                novo_perc_meta = st.number_input("% Meta", 0.0, 100.0, valor_perc_meta, 0.1, format="%.1f", key=f"perc_meta_{i}")
                valor_perc_avista = min(perc_avista_valor, 100.0)
                novo_perc_avista = st.number_input("% Venda à Vista", 0.0, 100.0, valor_perc_avista, 0.1, format="%.1f", key=f"perc_avista_{i}")
                valor_desconto = desconto_valor if desconto_valor <= 100 else 0.0
                novo_desconto = st.number_input("Desconto (%)", 0.0, 100.0, valor_desconto, 0.1, format="%.1f", key=f"desconto_{i}")
                novo_desconto_qtd = st.number_input("Qtd Desconto", 0, 1000, int(desconto_qtd_valor), 1, key=f"desconto_qtd_{i}")
                novo_faturamento = st.number_input("Faturamento (R$)", 0.0, 10000000.0, faturamento_valor, 1000.0, format="%.2f", key=f"faturamento_{i}")
            
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
                'elegivel_margem': novo_margem >= 26 and novo_alcance >= 90,
                'meta_venda_avista': novo_meta_avista,
                'percentual_meta': novo_perc_meta,
                'percentual_venda_avista': novo_perc_avista,
                'desconto': novo_desconto,
                'desconto_qtd': novo_desconto_qtd,
                'faturamento': novo_faturamento
            }
            
            bonus, detalhes = calcular_bonus(vendedor_editado)
            vendedor_editado['bonus_total'] = bonus
            vendedor_editado['detalhes_bonus'] = detalhes
            
            st.markdown(f"**🔄 Novo bônus calculado: R$ {bonus:,.2f}**")
            vendedores_editados.append(vendedor_editado)
    
    return vendedores_editados

# ============================================
# FUNÇÃO PARA GERAR PDF DO FEEDBACK STAR (COM ASSINATURAS E DATA)
# ============================================

def gerar_pdf_feedback(vendedor, feedback_texto, periodo):
    """Gera um PDF com o feedback STAR formatado (compatível com ASCII) com linhas de assinatura"""
    pdf = FPDF()
    pdf.add_page()
    
    # Cabeçalho
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, f"Feedback STAR - {vendedor['nome']}", ln=True, align="C")
    pdf.set_font("Arial", "I", 10)
    pdf.cell(0, 6, f"Periodo: {periodo}", ln=True, align="C")
    data_feedback = datetime.now().strftime('%d/%m/%Y')
    pdf.cell(0, 6, f"Data do Feedback: {data_feedback}", ln=True, align="C")
    pdf.ln(10)
    
    # Dados do vendedor em tabela simples
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, "Resumo de Performance:", ln=True)
    pdf.set_font("Arial", "", 10)
    
    # Função para sanitizar texto (remove caracteres não suportados pela fonte Arial)
    def sanitize(text):
        return text.replace("≤", "<=").replace("≥", ">=").replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u").replace("ç", "c").replace("ã", "a").replace("õ", "o").replace("â", "a").replace("ê", "e").replace("ô", "o").replace("Á", "A").replace("É", "E").replace("Í", "I").replace("Ó", "O").replace("Ú", "U").replace("Ç", "C").replace("Ã", "A").replace("Õ", "O")
    
    dados = [
        f"Margem: {vendedor['margem_pct']:.1f}% (Meta: 26%)",
        f"Conversao: {vendedor['conversao_calculada']:.1f}% (Meta: 12%)",
        f"Prazo Medio: {vendedor['prazo_medio']:.0f} dias (Meta: <=43)",
        f"TME: {vendedor['tme_minutos']:.1f} min (Meta: <=5)",
        f"Interacoes: {vendedor['interacoes']:.0f} (Meta: >=200)",
        f"Bonus Total: R$ {vendedor['bonus_total']:,.2f}",
        f"Faturamento: R$ {vendedor.get('faturamento', 0):,.2f}",
        f"Meta Faturamento: R$ {vendedor.get('meta_venda_avista', 0):,.2f}",
        f"% Meta: {vendedor.get('percentual_meta', 0):.1f}%",
        f"% Venda a Vista: {vendedor.get('percentual_venda_avista', 0):.1f}%",
        f"Desconto Medio: {vendedor.get('desconto', 0):.1f}%"
    ]
    
    for dado in dados:
        pdf.cell(0, 6, f" - {dado}", ln=True)
    
    pdf.ln(6)
    
    # Feedback STAR
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 8, "Feedback Detalhado (Metodologia STAR):", ln=True)
    pdf.set_font("Arial", "", 10)
    
    # Limpar formatação markdown e caracteres especiais
    texto_limpo = feedback_texto.replace("**", "").replace("__", "")
    texto_limpo = sanitize(texto_limpo)
    
    # Quebrar em linhas para caber na página
    pdf.multi_cell(0, 6, texto_limpo)
    
    # Linhas de assinatura
    pdf.ln(12)
    pdf.set_font("Arial", "", 10)
    
    # Linha para assinatura do Gestor
    pdf.cell(0, 10, "_________________________________________", ln=True, align="C")
    pdf.cell(0, 6, "Assinatura do Gestor", ln=True, align="C")
    
    pdf.ln(6)
    
    # Linha para assinatura do Coordenador
    pdf.cell(0, 10, "_________________________________________", ln=True, align="C")
    pdf.cell(0, 6, "Assinatura do Coordenador", ln=True, align="C")
    
    # Rodapé
    pdf.ln(6)
    pdf.set_font("Arial", "I", 8)
    pdf.cell(0, 6, f"Gerado automaticamente por Central de Vendas Analytics em {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align="C")
    
    # Salvar em bytes para download
    output = BytesIO()
    pdf.output(output)
    output.seek(0)
    return output

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
                    'id': analise['id'],
                    'periodo': analise['periodo'],
                    'vendedores': dados['vendedores'],
                    'total_bonus': analise['total_bonus']
                }
                st.session_state['analise_realizada'] = True
                # Salva como última análise ativa
                salvar_ultima_analise(analise['id'])
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
# AGENTE DE PERFORMANCE COMERCIAL
# ============================================

def agente_performance_comercial(vendedores, stats, periodo):
    """Agente especializado em análise de performance comercial"""
    
    contexto = f"""
    Você é um Agente de Performance Comercial especialista em vendas B2B.
    
    DADOS DO PERÍODO {periodo}:
    
    RESULTADOS GERAIS:
    - Total de Vendas: {stats['total_faturas']:.0f} vendas
    - Margem Média: {stats['media_margem']:.1f}% (Meta: 26%)
    - Conversão Média: {stats['media_conversao']:.1f}% (Meta: 12%)
    - Prazo Médio: {stats['media_prazo']:.0f} dias (Meta: ≤ 43)
    - TME Médio: {stats['media_tme']:.1f} min (Meta: ≤ 5)
    - Interações Médias: {stats['media_interacoes']:.0f} (Meta: ≥ 200)
    
    META ATINGIMENTO:
    - Margem: {stats['acima_meta_margem']}/{len(vendedores)} vendedores acima da meta
    - Conversão: {stats['acima_meta_conversao']}/{len(vendedores)} acima da meta
    
    BÔNUS TOTAL: R$ {stats['total_bonus']:,.2f}
    
    NOVOS INDICADORES:
    - Faturamento Total: R$ {stats['total_faturamento']:,.2f}
    - Média % Meta: {stats['media_percentual_meta']:.1f}%
    - Média % Venda à Vista: {stats['media_percentual_venda_avista']:.1f}%
    - Média Desconto: {stats['media_desconto']:.1f}%
    """
    
    for v in vendedores:
        contexto += f"""
        {v['nome']}: Margem {v['margem_pct']:.1f}% | Conversão {v['conversao_calculada']:.1f}% | Bônus R$ {v['bonus_total']:,.0f} | Faturamento R$ {v.get('faturamento', 0):,.2f} | %Meta {v.get('percentual_meta', 0):.1f}%
        """
    
    if "agente_history" not in st.session_state:
        st.session_state.agente_history = []
        saudacao = f"""🏢 **Agente de Performance Comercial Ativo**

Olá! Analisei os dados do período **{periodo}**.

**Posso te ajudar com:**
- 📊 Análise de performance do time
- 🎯 Recomendações estratégicas
- 📈 Projeções de vendas
- 💰 Otimização de bônus
- 🚀 Plano de ação comercial

**O que você gostaria de analisar?**
"""
        st.session_state.agente_history.append({"role": "assistant", "content": saudacao})
    
    for msg in st.session_state.agente_history:
        if msg["role"] == "user":
            st.markdown(f'<div style="background: #1a4a2e; color: white; padding: 10px; border-radius: 10px; margin: 5px 0; text-align: right;">👤 <b>Você:</b><br>{msg["content"]}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div style="background: #141824; color: #c8d0dc; padding: 12px; border-radius: 10px; margin: 5px 0; border-left: 3px solid #ffab00;">🤖 <b>Agente de Performance:</b><br>{msg["content"]}</div>', unsafe_allow_html=True)
    
    sugestoes = [
        "Análise completa do time",
        "Quem são os top performers?",
        "Oportunidades de melhoria",
        "Projeção para próximo mês",
        "Plano de ação para equipe"
    ]
    
    st.markdown("**💡 Perguntas sugeridas:**")
    cols = st.columns(3)
    for i, sug in enumerate(sugestoes):
        with cols[i % 3]:
            if st.button(sug, key=f"sug_agente_{i}", use_container_width=True):
                st.session_state.agente_history.append({"role": "user", "content": sug})
                st.rerun()
    
    st.markdown("---")
    
    pergunta = st.text_area("💬 Faça sua pergunta comercial:", key="agente_input", height=80)
    
    if st.button("📤 Enviar para Agente", type="primary", use_container_width=True) and pergunta:
        st.session_state.agente_history.append({"role": "user", "content": pergunta})
        
        with st.spinner("🏢 Agente de Performance analisando..."):
            try:
                modelo = get_modelo_disponivel()
                if modelo:
                    prompt = f"""
                    Você é um Agente de Performance Comercial sênior.
                    
                    Contexto dos dados:
                    {contexto}
                    
                    Pergunta: {pergunta}
                    
                    Responda como um consultor comercial especialista. Seja prático, objetivo e traga insights acionáveis.
                    Responda em português do Brasil.
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
# FUNÇÃO DE PROJEÇÃO
# ============================================

def exibir_projecao(vendedores, stats, periodo):
    """Exibe a aba de projeção de resultados"""
    
    st.markdown("### 📈 Projeção de Resultados")
    st.markdown("""
    <div class="info-box">
    📊 <strong>Projeção de Metas</strong><br>
    Esta ferramenta projeta o resultado final do mês baseado no desempenho atual,
    considerando dias úteis trabalhados e dias restantes.
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        dias_uteis_total = st.number_input("📅 Total de dias úteis no mês", min_value=1, max_value=30, value=22)
    
    with col2:
        dias_uteis_trabalhados = st.number_input("✅ Dias úteis trabalhados até agora", min_value=1, max_value=dias_uteis_total, value=min(15, dias_uteis_total))
    
    st.markdown("---")
    
    # Seletor de vendedor
    vendedor_selecionado = st.selectbox(
        "Selecione o vendedor para projeção:",
        [v['nome'] for v in vendedores]
    )
    
    vendedor = next((v for v in vendedores if v['nome'] == vendedor_selecionado), None)
    
    if vendedor:
        proj = calcular_projecao(vendedor, dias_uteis_trabalhados, dias_uteis_total)
        
        # Cards de resultados atuais
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">📦 FATURADAS ATUAL</div>
                <div class="valor-grande">{proj['qtd_faturadas_atual']:.0f}</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">💬 INTERAÇÕES ATUAL</div>
                <div class="valor-grande">{proj['interacoes_atual']:.0f}</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">🔄 CONVERSÃO ATUAL</div>
                <div class="valor-medio">{proj['conversao_atual']:.1f}%</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col4:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">💰 TICKET MÉDIO</div>
                <div class="valor-medio">R$ {proj['ticket_medio']:,.2f}</div>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("---")
        st.markdown("### 📊 PROJEÇÃO PARA FIM DO MÊS")
        
        # Cards de projeção
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">📦 PROJEÇÃO FATURADAS</div>
                <div class="valor-grande">{proj['projecao_faturas']:.0f}</div>
                <div class="indicador-meta">Meta: 100 vendas</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">💬 PROJEÇÃO INTERAÇÕES</div>
                <div class="valor-grande">{proj['projecao_interacoes']:.0f}</div>
                <div class="indicador-meta">Meta: 200 interações</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown(f"""
            <div class="card-metrica" style="border-color: {proj['cor']}">
                <div class="indicador-titulo">🎯 PERCENTUAL DA META</div>
                <div class="valor-grande" style="color: {proj['cor']}">{proj['percentual_meta']:.1f}%</div>
                <div class="indicador-meta">{proj['status']}</div>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        # Métricas diárias
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">📈 MÉDIA DIÁRIAS FATURADAS</div>
                <div class="valor-medio">{proj['media_diaria_faturas']:.1f} vendas/dia</div>
                <div class="indicador-meta">Ritmo atual de vendas</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">📞 MÉDIA DIÁRIA INTERAÇÕES</div>
                <div class="valor-medio">{proj['media_diaria_interacoes']:.1f} interações/dia</div>
                <div class="indicador-meta">Ritmo atual de contatos</div>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        # Recomendação
        st.markdown(f"""
        <div class="info-box" style="border-left-color: {proj['cor']}">
        <strong>💡 RECOMENDAÇÃO:</strong><br>
        {proj['recomendacao']}<br><br>
        <strong>📅 Dias restantes no mês:</strong> {proj['dias_restantes']} dias úteis
        </div>
        """, unsafe_allow_html=True)
        
        # Meta necessária
        if proj['percentual_meta'] < 100:
            faturas_faltando = 100 - proj['projecao_faturas']
            if faturas_faltando > 0:
                st.warning(f"⚠️ Para atingir a meta de 100 vendas, é necessário aumentar o ritmo em aproximadamente {faturas_faltando / max(proj['dias_restantes'], 1):.1f} vendas por dia.")

# ============================================
# FUNÇÃO PARA EXIBIR FEEDBACK STAR (COM DOWNLOAD PDF - CORRIGIDA)
# ============================================

def exibir_feedback_star(vendedores, stats, periodo):
    st.markdown("### 🎯 Feedback Individual - Metodologia STAR")
    st.markdown("""
    <div class="info-box">
    📌 <strong>Metodologia STAR</strong><br>
    <strong>S</strong> - Situação: Contexto atual do vendedor<br>
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
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">📊 RESULTADOS DE {vendedor['nome'].upper()}</div>
                <div>💰 Bônus: <b>R$ {vendedor['bonus_total']:,.2f}</b></div>
                <div>📈 Margem: <b>{vendedor['margem_pct']:.1f}%</b> (Meta: 26%)</div>
                <div>🔄 Conversão: <b>{vendedor['conversao_calculada']:.1f}%</b> (Meta: 12%)</div>
                <div>📅 Prazo: <b>{vendedor['prazo_medio']:.0f} dias</b> (Meta: ≤43)</div>
                <div>⏱️ TME: <b>{vendedor['tme_minutos']:.1f} min</b> (Meta: ≤5)</div>
                <div>💬 Interações: <b>{vendedor['interacoes']:.0f}</b> (Meta: ≥200)</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">📊 NOVOS INDICADORES</div>
                <div>💰 Faturamento: <b>R$ {vendedor.get('faturamento', 0):,.2f}</b></div>
                <div>🎯 Meta Faturamento: <b>R$ {vendedor.get('meta_venda_avista', 0):,.2f}</b></div>
                <div>🎯 % Meta: <b>{vendedor.get('percentual_meta', 0):.1f}%</b></div>
                <div>📈 % Venda à Vista: <b>{vendedor.get('percentual_venda_avista', 0):.1f}%</b></div>
                <div>💸 Desconto: <b>{vendedor.get('desconto', 0):.1f}%</b></div>
                <div>🔢 Qtd Desconto: <b>{vendedor.get('desconto_qtd', 0):.0f}</b></div>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        # Gerar feedback
        pontos_fortes = []
        pontos_melhorar = []
        
        if vendedor['margem_pct'] >= 26:
            pontos_fortes.append(f"Margem de {vendedor['margem_pct']:.1f}%")
        else:
            pontos_melhorar.append(f"Margem (atual {vendedor['margem_pct']:.1f}%, meta 26%)")
        
        if vendedor['conversao_calculada'] >= 12:
            pontos_fortes.append(f"Conversão de {vendedor['conversao_calculada']:.1f}%")
        else:
            pontos_melhorar.append(f"Conversão (atual {vendedor['conversao_calculada']:.1f}%, meta 12%)")
        
        if vendedor['prazo_medio'] <= 43:
            pontos_fortes.append(f"Prazo de {vendedor['prazo_medio']:.0f} dias")
        else:
            pontos_melhorar.append(f"Prazo (atual {vendedor['prazo_medio']:.0f} dias, meta 43)")
        
        if vendedor['tme_minutos'] <= 5:
            pontos_fortes.append(f"TME de {vendedor['tme_minutos']:.1f} min")
        else:
            pontos_melhorar.append(f"TME (atual {vendedor['tme_minutos']:.1f} min, meta 5)")
        
        if vendedor['interacoes'] >= 200:
            pontos_fortes.append(f"Interações: {vendedor['interacoes']:.0f}")
        else:
            pontos_melhorar.append(f"Interações (atual {vendedor['interacoes']:.0f}, meta 200)")
        
        if vendedor.get('percentual_meta', 0) >= 80:
            pontos_fortes.append(f"% Meta: {vendedor.get('percentual_meta', 0):.1f}%")
        else:
            pontos_melhorar.append(f"% Meta (atual {vendedor.get('percentual_meta', 0):.1f}%, ideal 80%+)")
        
        if vendedor.get('desconto', 0) <= 10:
            pontos_fortes.append(f"Desconto controlado: {vendedor.get('desconto', 0):.1f}%")
        else:
            pontos_melhorar.append(f"Desconto alto: {vendedor.get('desconto', 0):.1f}% (reduzir para aumentar margem)")
        
        st.markdown("#### ✅ Pontos Fortes")
        for pf in pontos_fortes:
            st.success(f"✅ {pf}")
        
        if pontos_melhorar:
            st.markdown("#### ⚠️ Pontos a Melhorar")
            for pm in pontos_melhorar:
                st.warning(f"⚠️ {pm}")
        
        st.markdown("---")
        
        # Botão para gerar feedback STAR
        if st.button(f"🎯 Gerar Feedback STAR para {vendedor['nome']}", type="primary", use_container_width=True):
            with st.spinner("Gerando feedback personalizado..."):
                try:
                    modelo = get_modelo_disponivel()
                    if modelo:
                        prompt = f"""
                        Gere um feedback profissional para o vendedor {vendedor['nome']} usando a metodologia STAR.
                        
                        DADOS DO VENDEDOR:
                        - Margem: {vendedor['margem_pct']:.1f}% (Meta: 26%)
                        - Conversão: {vendedor['conversao_calculada']:.1f}% (Meta: 12%)
                        - Prazo: {vendedor['prazo_medio']:.0f} dias (Meta: ≤43)
                        - TME: {vendedor['tme_minutos']:.1f} min (Meta: ≤5)
                        - Interações: {vendedor['interacoes']:.0f} (Meta: ≥200)
                        - Bônus: R$ {vendedor['bonus_total']:,.0f}
                        - Faturamento: R$ {vendedor.get('faturamento', 0):,.2f}
                        - Meta Faturamento: R$ {vendedor.get('meta_venda_avista', 0):,.2f}
                        - % Meta: {vendedor.get('percentual_meta', 0):.1f}%
                        - % Venda à Vista: {vendedor.get('percentual_venda_avista', 0):.1f}%
                        - Desconto: {vendedor.get('desconto', 0):.1f}%
                        
                        PONTOS FORTES: {', '.join(pontos_fortes)}
                        PONTOS A MELHORAR: {', '.join(pontos_melhorar)}
                        
                        Use a metodologia STAR:
                        
                        **SITUAÇÃO:** Descreva o cenário atual
                        **TAREFA:** Defina os objetivos
                        **AÇÃO:** Liste 3-5 ações práticas
                        **RESULTADO:** Mostre o impacto esperado
                        
                        Responda em português do Brasil.
                        """
                        resposta = modelo.generate_content(prompt)
                        feedback_texto = resposta.text
                        st.markdown(f'<div style="background: #1a1f2e; border-radius: 12px; padding: 20px; margin-top: 16px; border: 1px solid #2a3040;">{feedback_texto}</div>', unsafe_allow_html=True)
                        
                        # Botão para baixar PDF
                        st.markdown("---")
                        col_pdf1, col_pdf2, col_pdf3 = st.columns([1, 2, 1])
                        with col_pdf2:
                            pdf_bytes = gerar_pdf_feedback(vendedor, feedback_texto, periodo)
                            st.download_button(
                                label="📄 Baixar Feedback em PDF",
                                data=pdf_bytes,
                                file_name=f"Feedback_STAR_{vendedor['nome'].replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                                mime="application/pdf",
                                use_container_width=True
                            )
                except Exception as e:
                    st.error(f"Erro ao gerar feedback: {e}")

# ============================================
# FUNÇÃO SIMULADOR DE METAS MENSAIS (NOVA ABA)
# ============================================

def exibir_simulador_metas(vendedores, stats, periodo):
    st.markdown("### 🎯 Simulador de Metas Mensais")
    st.markdown("""
    <div class="info-box">
    📊 <strong>Simulador de Planejamento de Metas</strong><br>
    Esta ferramenta ajuda a projetar as metas do mês com base no faturamento desejado,
    dias úteis, ticket médio e taxa de conversão esperada.
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        meta_faturamento = st.number_input("💰 Meta de Faturamento do Mês (R$)", min_value=0.0, value=100000.0, step=10000.0, format="%.2f")
        dias_uteis = st.number_input("📅 Dias Úteis no Mês", min_value=1, max_value=30, value=22)
    
    with col2:
        # Opção de usar ticket médio histórico ou informar manualmente
        usar_ticket_historico = st.checkbox("Usar ticket médio histórico da análise", value=True)
        if usar_ticket_historico and stats.get('total_faturas', 0) > 0:
            ticket_medio_historico = stats['total_faturamento'] / stats['total_faturas'] if stats['total_faturas'] > 0 else 0
            ticket_medio = ticket_medio_historico
            st.info(f"Ticket médio histórico do time: R$ {ticket_medio:,.2f}")
        else:
            ticket_medio = st.number_input("🎫 Ticket Médio Estimado (R$)", min_value=0.0, value=5000.0, step=500.0, format="%.2f")
        
        # Opção de usar conversão histórica ou informar manualmente
        usar_conversao_historica = st.checkbox("Usar taxa de conversão histórica", value=True)
        if usar_conversao_historica and stats.get('media_conversao', 0) > 0:
            conversao_media = stats['media_conversao']
            st.info(f"Taxa de conversão média do time: {conversao_media:.1f}%")
        else:
            conversao_media = st.number_input("🔄 Taxa de Conversão Esperada (%)", min_value=0.0, max_value=100.0, value=12.0, step=1.0, format="%.1f")
    
    st.markdown("---")
    
    if meta_faturamento > 0 and dias_uteis > 0 and ticket_medio > 0:
        # Cálculos principais
        nfs_necessarias = meta_faturamento / ticket_medio
        nfs_por_dia = nfs_necessarias / dias_uteis
        
        if conversao_media > 0:
            interacoes_necessarias = (nfs_necessarias / (conversao_media / 100))
            interacoes_por_dia = interacoes_necessarias / dias_uteis
        else:
            interacoes_necessarias = 0
            interacoes_por_dia = 0
        
        st.markdown("### 📈 Resultados da Simulação")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">📦 NFs NECESSÁRIAS</div>
                <div class="valor-grande">{nfs_necessarias:.0f}</div>
                <div class="indicador-meta">Total no mês</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">📊 NFs POR DIA</div>
                <div class="valor-medio">{nfs_por_dia:.1f}</div>
                <div class="indicador-meta">Média diária</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">💬 INTERAÇÕES NECESSÁRIAS</div>
                <div class="valor-grande">{interacoes_necessarias:.0f}</div>
                <div class="indicador-meta">Total no mês</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col4:
            st.markdown(f"""
            <div class="card-metrica">
                <div class="indicador-titulo">📞 INTERAÇÕES POR DIA</div>
                <div class="valor-medio">{interacoes_por_dia:.0f}</div>
                <div class="indicador-meta">Média diária</div>
            </div>
            """, unsafe_allow_html=True)
        
        st.markdown("---")
        
        # Comparação com desempenho atual do time
        if stats.get('total_faturas', 0) > 0:
            st.markdown("### 📊 Comparação com o Desempenho Atual do Time")
            
            desempenho_atual = {
                'faturamento': stats['total_faturamento'],
                'nfs': stats['total_faturas'],
                'nfs_dia': stats['total_faturas'] / dias_uteis if dias_uteis > 0 else 0,
                'interacoes': stats['total_interacoes'],
                'interacoes_dia': stats['total_interacoes'] / dias_uteis if dias_uteis > 0 else 0,
                'conversao': stats['media_conversao']
            }
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("**Metas Projetadas vs. Atual**")
                df_compare = pd.DataFrame({
                    'Métrica': ['Faturamento (R$)', 'Quantidade de NFs', 'Interações', 'Conversão (%)'],
                    'Meta Projetada': [f"R$ {meta_faturamento:,.2f}", f"{nfs_necessarias:.0f}", f"{interacoes_necessarias:.0f}", f"{conversao_media:.1f}%"],
                    'Desempenho Atual': [f"R$ {desempenho_atual['faturamento']:,.2f}", f"{desempenho_atual['nfs']:.0f}", f"{desempenho_atual['interacoes']:.0f}", f"{desempenho_atual['conversao']:.1f}%"]
                })
                st.dataframe(df_compare, use_container_width=True, hide_index=True)
            
            with col2:
                # Diferença percentual
                perc_fat = (meta_faturamento / desempenho_atual['faturamento'] - 1) * 100 if desempenho_atual['faturamento'] > 0 else 0
                perc_nfs = (nfs_necessarias / desempenho_atual['nfs'] - 1) * 100 if desempenho_atual['nfs'] > 0 else 0
                
                st.markdown("**Necessidade de Crescimento**")
                st.metric("Faturamento", f"R$ {meta_faturamento:,.2f}", delta=f"{perc_fat:+.1f}%" if perc_fat != 0 else "igual")
                st.metric("Quantidade de NFs", f"{nfs_necessarias:.0f}", delta=f"{perc_nfs:+.1f}%" if perc_nfs != 0 else "igual")
        
        st.markdown("---")
        
        # Gráfico de metas diárias
        st.markdown("### 📈 Metas Diárias Projetadas")
        
        dias = list(range(1, dias_uteis + 1))
        nfs_acumuladas = [nfs_por_dia * i for i in range(1, dias_uteis + 1)]
        interacoes_acumuladas = [interacoes_por_dia * i for i in range(1, dias_uteis + 1)]
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=dias, y=nfs_acumuladas, mode='lines+markers', name='NFs Acumuladas', line=dict(color='#00e676', width=2)))
        fig.add_trace(go.Scatter(x=dias, y=interacoes_acumuladas, mode='lines+markers', name='Interações Acumuladas', line=dict(color='#ffab00', width=2)))
        fig.update_layout(title="Acumulado de Metas ao Longo do Mês", xaxis_title="Dia Útil", yaxis_title="Quantidade", plot_bgcolor='#0d1117', paper_bgcolor='#0d1117', height=400)
        st.plotly_chart(fig, use_container_width=True)
        
        # Recomendações
        st.markdown("---")
        st.markdown("### 💡 Recomendações Estratégicas")
        
        recomendacoes = []
        
        if nfs_por_dia > 5:
            recomendacoes.append("📌 A meta diária de NFs está alta (acima de 5). Considere revisar o ticket médio ou o prazo.")
        elif nfs_por_dia < 2:
            recomendacoes.append("✅ A meta diária de NFs está confortável. Mantenha o ritmo.")
        else:
            recomendacoes.append("📊 A meta diária de NFs está dentro do esperado. Foco na consistência.")
        
        if interacoes_por_dia > 50:
            recomendacoes.append("⚠️ A necessidade diária de interações é alta (acima de 50). Invista em estratégias de prospecção.")
        elif interacoes_por_dia < 20:
            recomendacoes.append("✅ A necessidade de interações está baixa. Mantenha a qualidade dos contatos.")
        else:
            recomendacoes.append("📞 Nível de interações diárias adequado. Continue acompanhando.")
        
        if conversao_media < 10:
            recomendacoes.append("🎯 Taxa de conversão baixa. Treinamento em técnicas de fechamento pode ajudar.")
        elif conversao_media > 20:
            recomendacoes.append("🏆 Excelente taxa de conversão! Foco em aumentar o volume de interações.")
        
        for rec in recomendacoes:
            st.info(rec)
        
        # Botão para exportar simulação
        st.markdown("---")
        if st.button("📄 Exportar Simulação", type="primary"):
            # Criar PDF da simulação
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", "B", 16)
            pdf.cell(0, 10, "Simulador de Metas Mensais", ln=True, align="C")
            pdf.set_font("Arial", "I", 10)
            pdf.cell(0, 6, f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align="C")
            pdf.ln(10)
            
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 8, "Parametros de Entrada:", ln=True)
            pdf.set_font("Arial", "", 10)
            pdf.cell(0, 6, f"Meta de Faturamento: R$ {meta_faturamento:,.2f}", ln=True)
            pdf.cell(0, 6, f"Dias Uteis: {dias_uteis}", ln=True)
            pdf.cell(0, 6, f"Ticket Medio: R$ {ticket_medio:,.2f}", ln=True)
            pdf.cell(0, 6, f"Taxa de Conversao: {conversao_media:.1f}%", ln=True)
            
            pdf.ln(6)
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 8, "Resultados:", ln=True)
            pdf.set_font("Arial", "", 10)
            pdf.cell(0, 6, f"NFs Necessarias: {nfs_necessarias:.0f}", ln=True)
            pdf.cell(0, 6, f"NFs por Dia: {nfs_por_dia:.1f}", ln=True)
            pdf.cell(0, 6, f"Interacoes Necessarias: {interacoes_necessarias:.0f}", ln=True)
            pdf.cell(0, 6, f"Interacoes por Dia: {interacoes_por_dia:.0f}", ln=True)
            
            pdf.ln(6)
            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 8, "Recomendacoes:", ln=True)
            pdf.set_font("Arial", "", 10)
            for rec in recomendacoes:
                pdf.cell(0, 6, rec, ln=True)
            
            output = BytesIO()
            pdf.output(output)
            output.seek(0)
            
            st.download_button(
                label="📥 Baixar Simulação em PDF",
                data=output,
                file_name=f"Simulador_Metas_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                mime="application/pdf",
                use_container_width=True
            )

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
# FUNÇÃO PARA SALVAR ANÁLISE ATUAL NO HISTÓRICO E COMO ÚLTIMA
# ============================================

def salvar_analise_atual():
    if st.session_state.get('analise_realizada', False):
        analise = st.session_state.get('analise_atual', {})
        if analise and analise.get('vendedores'):
            # Se já existe um ID (análise carregada do histórico), apenas atualizamos a última análise
            if 'id' in analise and analise['id']:
                # Já existe no banco, apenas atualizar a referência de última análise
                salvar_ultima_analise(analise['id'])
                st.success("✅ Análise definida como ativa!")
            else:
                # Nova análise, precisa salvar no histórico
                dados_json = serializar_analise(analise['vendedores'], analise['periodo'])
                novo_id = salvar_analise(analise['periodo'], dados_json, analise['total_bonus'])
                # Atualiza o session_state com o ID
                st.session_state['analise_atual']['id'] = novo_id
                salvar_ultima_analise(novo_id)
                st.success("✅ Análise salva no histórico e definida como ativa!")
            st.rerun()

# ============================================
# DASHBOARD PRINCIPAL
# ============================================

def dashboard_principal():
    global DATA_ATUALIZACAO
    
    # Tentar carregar a última análise ativa se ainda não houver análise no session_state
    if not st.session_state.get('analise_realizada', False):
        ultima = carregar_ultima_analise()
        if ultima:
            dados = desserializar_analise(ultima['dados_json'])
            st.session_state['analise_atual'] = {
                'id': ultima['id'],
                'periodo': ultima['periodo'],
                'vendedores': dados['vendedores'],
                'total_bonus': ultima['total_bonus']
            }
            st.session_state['analise_realizada'] = True
            # Não precisa salvar novamente a última, já está salva
    
    with st.sidebar:
        st.markdown(f"### 👤 {st.session_state.get('usuario', 'Usuário')}")
        st.markdown('<span class="elegivel-sim">👑 Administrador</span>', unsafe_allow_html=True)
        st.markdown("---")
        
        st.markdown("### 📚 Histórico de Análises")
        analises = get_analises()
        
        if analises:
            for a in analises[:5]:
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**{a['periodo']}**")
                    st.caption(f"{a['data_analise'][:16]}")
                with col2:
                    if st.button("🗑️", key=f"del_{a['id']}"):
                        deletar_analise(a['id'])
                        st.rerun()
                st.markdown("---")
            
            if st.button("📋 Ver Histórico Completo", use_container_width=True):
                st.session_state['show_historico'] = True
        else:
            st.info("Nenhuma análise salva ainda")
        
        st.markdown("---")
        
        st.markdown("### 💾 Ações")
        
        if st.session_state.get('analise_realizada', False):
            if st.button("💾 Salvar/Atualizar Análise Atual", use_container_width=True):
                salvar_analise_atual()
        
        st.markdown("---")
        
        st.markdown("### 💾 Dados Salvos dos Prints")
        dados_salvos = listar_dados_salvos()
        if dados_salvos:
            for nome, data in dados_salvos[:3]:
                st.caption(f"📄 {nome[:25]}...")
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
        
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "📸 1. Nova Análise",
            "📊 2. Dashboard",
            "📈 3. Evolução",
            "✏️ 4. Edição Manual",
            "🎯 5. Projeção",
            "🤖 6. Análise com IA"
        ])
        
        # TAB 1: Nova Análise
        with tab1:
            st.markdown("### 📸 Envie os prints dos painéis")
            
            st.markdown("""
            <div class="info-box">
            📌 <strong>Instruções:</strong><br>
            - <strong>Print 1:</strong> Alcance Projetado, Margem, Meta Venda, %Meta, %Venda Avista, Desconto, Qtd Desconto, Faturamento<br>
            - <strong>Print 2:</strong> Prazo Médio<br>
            - <strong>Print 3:</strong> Qtd. Faturadas<br>
            - <strong>Print 4:</strong> Chamadas<br>
            - <strong>Print 5:</strong> TME, Iniciados e Recebidos
            </div>
            """, unsafe_allow_html=True)
            
            prints_bytes = []
            nomes_print = [
                "Print 1 - Alcance, Margem, Meta, %Meta, %Venda, Desconto, Faturamento",
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
                            analise_id = salvar_analise(periodo_input, dados_json, total_bonus)
                            
                            st.session_state['analise_atual'] = {
                                'id': analise_id,
                                'periodo': periodo_input,
                                'vendedores': vendedores,
                                'total_bonus': total_bonus
                            }
                            st.session_state['analise_realizada'] = True
                            # Salva como última análise ativa
                            salvar_ultima_analise(analise_id)
                            
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
        
        # TAB 3: Evolução
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
        
        # TAB 4: Edição Manual
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
                        
                        # Se já tem ID, atualiza o registro no banco (deleta o antigo e insere novo)
                        if 'id' in analise and analise['id']:
                            deletar_analise(analise['id'])
                            novo_id = salvar_analise(periodo, dados_json, total_bonus)
                            st.session_state['analise_atual'] = {
                                'id': novo_id,
                                'periodo': periodo,
                                'vendedores': vendedores_editados,
                                'total_bonus': total_bonus
                            }
                            salvar_ultima_analise(novo_id)
                        else:
                            novo_id = salvar_analise(periodo, dados_json, total_bonus)
                            st.session_state['analise_atual'] = {
                                'id': novo_id,
                                'periodo': periodo,
                                'vendedores': vendedores_editados,
                                'total_bonus': total_bonus
                            }
                            salvar_ultima_analise(novo_id)
                        
                        st.success("✅ Alterações salvas com sucesso!")
                        st.rerun()
                with col2:
                    if st.button("🔄 Cancelar e manter originais", use_container_width=True):
                        st.rerun()
        
        # TAB 5: Projeção
        with tab5:
            if not st.session_state.get('analise_realizada', False):
                st.warning("⚠️ Nenhuma análise carregada. Faça uma nova análise primeiro.")
            else:
                analise = st.session_state.get('analise_atual', {})
                vendedores = analise.get('vendedores', [])
                stats = calcular_estatisticas_time(vendedores)
                periodo = analise.get('periodo', 'Período atual')
                exibir_projecao(vendedores, stats, periodo)
        
        # TAB 6: Análise com IA
        with tab6:
            if not st.session_state.get('analise_realizada', False):
                st.warning("⚠️ Nenhuma análise carregada. Faça uma nova análise primeiro.")
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
    # DASHBOARD DE PERFORMANCE (COM NOVA ABA DE SIMULADOR)
    # ============================================
    else:
        if not st.session_state.get('analise_realizada', False):
            st.warning("⚠️ Nenhuma análise carregada. Faça uma nova análise ou carregue do histórico na barra lateral.")
        else:
            analise = st.session_state.get('analise_atual', {})
            vendedores = analise.get('vendedores', [])
            periodo = analise.get('periodo', 'Período atual')
            stats = calcular_estatisticas_time(vendedores)
            
            tab_perf1, tab_perf2, tab_perf3, tab_perf4, tab_perf5, tab_perf6 = st.tabs([
                "📊 1. Visão Geral",
                "📈 2. Indicadores",
                "🏢 3. Agente Performance",
                "🎯 4. Feedback STAR",
                "📊 5. Projeção",
                "🎯 6. Simulador de Metas"
            ])
            
            # TAB 1: Visão Geral
            with tab_perf1:
                st.markdown(f'<div class="periodo-box">📅 {periodo}</div>', unsafe_allow_html=True)
                st.markdown("### 📊 Visão Geral da Performance do Time")
                
                # Linha 1 - Indicadores de Bônus
                st.markdown("#### 🎯 Indicadores de Bônus")
                col1, col2, col3, col4 = st.columns(4)
                
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
                        <div class="progresso-bar"><div class="progresso-fill" style="width: {min(100, stats['media_margem']/26*100)}%"></div></div>
                        <div>{stats['acima_meta_margem']}/{len(vendedores)} acima da meta</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col4:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">🔄 MÉDIA CONVERSÃO</div>
                        <div class="valor-medio">{stats['media_conversao']:.1f}%</div>
                        <div class="progresso-bar"><div class="progresso-fill" style="width: {min(100, stats['media_conversao']/12*100)}%"></div></div>
                        <div>{stats['acima_meta_conversao']}/{len(vendedores)} acima da meta</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                st.markdown("---")
                
                # Linha 2 - Indicadores de Performance
                st.markdown("#### 📊 Indicadores de Performance")
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">💰 FATURAMENTO TOTAL</div>
                        <div class="valor-medio">R$ {stats['total_faturamento']:,.2f}</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col2:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">🎯 MÉDIA % META</div>
                        <div class="valor-medio">{stats['media_percentual_meta']:.1f}%</div>
                        <div class="progresso-bar"><div class="progresso-fill" style="width: {min(100, stats['media_percentual_meta'])}%"></div></div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col3:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">📊 MÉDIA % VENDA À VISTA</div>
                        <div class="valor-medio">{stats['media_percentual_venda_avista']:.1f}%</div>
                        <div class="progresso-bar"><div class="progresso-fill" style="width: {min(100, stats['media_percentual_venda_avista'])}%"></div></div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col4:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">💸 MÉDIA DESCONTO</div>
                        <div class="valor-medio">{stats['media_desconto']:.1f}%</div>
                        <div class="progresso-bar"><div class="progresso-fill" style="width: {min(100, 100 - stats['media_desconto'])}%; background:#ff5252"></div></div>
                    </div>
                    """, unsafe_allow_html=True)
                
                st.markdown("---")
                
                # Linha 3 - Métricas Operacionais
                st.markdown("#### ⏱️ Métricas Operacionais")
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">📅 PRAZO MÉDIO</div>
                        <div class="valor-medio">{stats['media_prazo']:.0f} dias</div>
                        <div class="progresso-bar"><div class="progresso-fill" style="width: {min(100, (1 - stats['media_prazo']/43) * 100 if stats['media_prazo'] <= 43 else 0)}%; background:#ff5252"></div></div>
                        <div>{stats['acima_meta_prazo']}/{len(vendedores)} dentro da meta</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col2:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">⏱️ TME MÉDIO</div>
                        <div class="valor-medio">{stats['media_tme']:.1f} min</div>
                        <div class="progresso-bar"><div class="progresso-fill" style="width: {min(100, (1 - stats['media_tme']/5) * 100 if stats['media_tme'] <= 5 else 0)}%; background:#ff5252"></div></div>
                        <div>{stats['acima_meta_tme']}/{len(vendedores)} dentro da meta</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col3:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">📊 ALCANCE MÉDIO</div>
                        <div class="valor-medio">{stats['media_alcance']:.1f}%</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col4:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">💬 INTERAÇÕES MÉDIAS</div>
                        <div class="valor-medio">{stats['media_interacoes']:.0f}</div>
                        <div class="progresso-bar"><div class="progresso-fill" style="width: {min(100, stats['media_interacoes']/200*100)}%"></div></div>
                        <div>{stats['acima_meta_interacoes']}/{len(vendedores)} acima da meta</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                st.markdown("---")
                
                # Linha 4 - Totais
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">📦 TOTAL VENDAS</div>
                        <div class="valor-medio">{stats['total_faturas']:.0f}</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col2:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">💬 TOTAL INTERAÇÕES</div>
                        <div class="valor-medio">{stats['total_interacoes']:.0f}</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col3:
                    st.markdown(f"""
                    <div class="card-metrica">
                        <div class="indicador-titulo">🔢 TOTAL DESCONTOS</div>
                        <div class="valor-medio">{stats['total_desconto_qtd']:.0f}</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                st.markdown("---")
                st.markdown("### 🎯 Comparativo de Metas")
                
                categorias = ['Margem', 'Conversão', 'Prazo (inv)', 'TME (inv)', 'Interações', '% Meta', '% Venda Avista']
                valores = [
                    min(100, stats['media_margem']/26*100),
                    min(100, stats['media_conversao']/12*100),
                    min(100, max(0, (1 - stats['media_prazo']/43)*100)) if stats['media_prazo'] > 0 else 0,
                    min(100, max(0, (1 - stats['media_tme']/5)*100)) if stats['media_tme'] > 0 else 0,
                    min(100, stats['media_interacoes']/200*100),
                    min(100, stats['media_percentual_meta']),
                    min(100, stats['media_percentual_venda_avista'])
                ]
                
                fig = go.Figure()
                fig.add_trace(go.Scatterpolar(r=valores, theta=categorias, fill='toself', name='Time', line=dict(color='#00e676')))
                fig.add_trace(go.Scatterpolar(r=[100,100,100,100,100,100,100], theta=categorias, fill='none', name='Meta', line=dict(color='#ffab00', dash='dash')))
                fig.update_layout(polar=dict(radialaxis=dict(range=[0,100])), height=500, plot_bgcolor='#0d1117', paper_bgcolor='#0d1117')
                st.plotly_chart(fig, use_container_width=True)
            
            # TAB 2: Indicadores
            with tab_perf2:
                st.markdown("### 📈 Indicadores por Vendedor")
                
                indicador = st.selectbox("Selecione o indicador:", [
                    "Margem (%)", "Conversão (%)", "Prazo (dias)", "TME (min)", 
                    "Interações", "Alcance (%)", "Faturamento (R$)", "% Meta", 
                    "% Venda à Vista", "Desconto (%)", "Ticket Médio (R$)"
                ])
                
                campo_map = {
                    "Margem (%)": ("margem_pct", "%", 26, True),
                    "Conversão (%)": ("conversao_calculada", "%", 12, True),
                    "Prazo (dias)": ("prazo_medio", "dias", 43, False),
                    "TME (min)": ("tme_minutos", "min", 5, False),
                    "Interações": ("interacoes", "", 200, True),
                    "Alcance (%)": ("alcance_projetado_pct", "%", 90, True),
                    "Faturamento (R$)": ("faturamento", "R$", 0, True),
                    "% Meta": ("percentual_meta", "%", 80, True),
                    "% Venda à Vista": ("percentual_venda_avista", "%", 50, True),
                    "Desconto (%)": ("desconto", "%", 10, False),
                    "Ticket Médio (R$)": ("ticket_medio", "R$", 0, True)
                }
                
                campo, unidade, meta, maior_melhor = campo_map[indicador]
                
                if campo == "ticket_medio":
                    df_indicador = pd.DataFrame(vendedores)
                    df_indicador['ticket_medio'] = df_indicador.apply(lambda x: x['faturamento'] / x['qtd_faturadas'] if x['qtd_faturadas'] > 0 else 0, axis=1)
                    df_indicador = df_indicador.sort_values('ticket_medio', ascending=False)
                    valores = df_indicador['ticket_medio']
                    texto = valores.apply(lambda x: f'R$ {x:,.2f}' if x > 0 else 'N/D')
                    meta_valor = 0
                else:
                    df_indicador = pd.DataFrame(vendedores)
                    df_indicador = df_indicador.sort_values(campo, ascending=not maior_melhor)
                    valores = df_indicador[campo]
                    texto = valores.apply(lambda x: f'{x:.1f}{unidade}' if x > 0 else 'N/D')
                    meta_valor = meta
                
                cores = []
                for v in valores:
                    valor = v or 0
                    if campo == "ticket_medio":
                        atingiu = valor > 0
                    elif maior_melhor:
                        atingiu = valor >= meta
                    else:
                        atingiu = valor <= meta and valor > 0
                    cores.append('#00e676' if atingiu else '#ff5252')
                
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=df_indicador['nome'],
                    y=valores,
                    text=texto,
                    textposition='outside',
                    marker_color=cores
                ))
                if meta_valor > 0:
                    fig.add_hline(y=meta, line_dash="dash", line_color="#ffab00", annotation_text=f"Meta: {meta}{unidade}")
                fig.update_layout(title=f"{indicador} por Vendedor", plot_bgcolor='#0d1117', paper_bgcolor='#0d1117', height=450)
                st.plotly_chart(fig, use_container_width=True)
                
                st.markdown("---")
                if campo == "ticket_medio":
                    st.dataframe(df_indicador[['nome', 'ticket_medio']].rename(columns={'ticket_medio': 'Ticket Médio (R$)'}), use_container_width=True)
                else:
                    st.dataframe(df_indicador[['nome', campo]], use_container_width=True)
            
            # TAB 3: Agente de Performance
            with tab_perf3:
                st.markdown("### 🏢 Agente de Performance Comercial")
                st.markdown("""
                <div class="info-box">
                💼 <strong>Agente Especializado em Performance Comercial</strong><br>
                Este agente foi treinado para analisar dados de vendas, sugerir estratégias, 
                identificar oportunidades e fazer projeções baseadas nos resultados do time.
                </div>
                """, unsafe_allow_html=True)
                agente_performance_comercial(vendedores, stats, periodo)
            
            # TAB 4: Feedback STAR (com exportação PDF)
            with tab_perf4:
                exibir_feedback_star(vendedores, stats, periodo)
            
            # TAB 5: Projeção
            with tab_perf5:
                exibir_projecao(vendedores, stats, periodo)
            
            # TAB 6: Simulador de Metas Mensais (NOVA)
            with tab_perf6:
                exibir_simulador_metas(vendedores, stats, periodo)

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
