"""
Utils - Funções auxiliares
"""

import json
from datetime import datetime

def calcular_estatisticas_time(vendedores):
    """Calcula todas as estatísticas do time"""
    
    if not vendedores:
        return {}
    
    stats = {
        'media_margem': sum(v['margem_pct'] for v in vendedores) / len(vendedores),
        'media_alcance': sum(v['alcance_projetado_pct'] for v in vendedores) / len(vendedores),
        'media_prazo': sum(v['prazo_medio'] for v in vendedores) / len(vendedores),
        'media_conversao': sum(v['conversao_calculada'] for v in vendedores) / len(vendedores),
        'media_tme': sum(v['tme_minutos'] for v in vendedores) / len(vendedores),
        'media_interacoes': sum(v['interacoes'] for v in vendedores) / len(vendedores),
        'media_faturas': sum(v['qtd_faturadas'] for v in vendedores) / len(vendedores),
        'total_faturas': sum(v['qtd_faturadas'] for v in vendedores),
        'total_interacoes': sum(v['interacoes'] for v in vendedores),
        'total_bonus': sum(v['bonus_total'] for v in vendedores),
        'qtd_elegiveis': sum(1 for v in vendedores if v.get('elegivel_margem', False)),
        'melhor_margem': max(v['margem_pct'] for v in vendedores),
        'pior_margem': min(v['margem_pct'] for v in vendedores),
        'melhor_conversao': max(v['conversao_calculada'] for v in vendedores),
        'pior_conversao': min(v['conversao_calculada'] for v in vendedores),
        'acima_meta_margem': sum(1 for v in vendedores if v['margem_pct'] >= 26),
        'acima_meta_conversao': sum(1 for v in vendedores if v['conversao_calculada'] >= 12),
        'acima_meta_prazo': sum(1 for v in vendedores if v['prazo_medio'] <= 43 and v['prazo_medio'] > 0),
        'acima_meta_tme': sum(1 for v in vendedores if v['tme_minutos'] <= 5 and v['tme_minutos'] > 0),
        'acima_meta_interacoes': sum(1 for v in vendedores if v['interacoes'] >= 200)
    }
    
    return stats

def serializar_analise(vendedores, periodo):
    """Serializa os dados da análise para JSON"""
    return json.dumps({
        'periodo': periodo,
        'data': datetime.now().isoformat(),
        'vendedores': vendedores
    }, ensure_ascii=False)

def desserializar_analise(dados_json):
    """Desserializa os dados da análise"""
    return json.loads(dados_json)

def formatar_moeda(valor):
    """Formata valor para moeda brasileira"""
    return f"R$ {valor:,.2f}".replace(",", "v").replace(".", ",").replace("v", ".")

def formatar_percentual(valor):
    """Formata valor para percentual"""
    return f"{valor:.1f}%"