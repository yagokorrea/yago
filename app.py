"""
Validador de Dígitos CNPJ/CPF — API REST v3
Parser determinístico de português brasileiro para contexto de documentos.
Regra central: todo número por extenso vira seus dígitos resultantes.
"mil quinhentos e setenta e oito" = 1578 = 4 dígitos
"trinta" = 30 = 2 dígitos
"mil" (isolado, contexto CNPJ) = 0001 quando precedido por outros dígitos
"""

from flask import Flask, request, jsonify
import re
import unicodedata

app = Flask(__name__)

UNIDADES = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2,
    "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "meia": 6,
    "sete": 7, "oito": 8, "nove": 9,
}

ESPECIAIS = {
    "dez": 10, "onze": 11, "doze": 12, "treze": 13,
    "catorze": 14, "quatorze": 14, "quinze": 15,
    "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19,
}

DEZENAS = {
    "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50,
    "sessenta": 60, "setenta": 70, "oitenta": 80, "noventa": 90,
}

CENTENAS = {
    "cem": 100, "cento": 100,
    "duzentos": 200, "duzentas": 200,
    "trezentos": 300, "trezentas": 300,
    "quatrocentos": 400, "quatrocentas": 400,
    "quinhentos": 500, "quinhentas": 500,
    "seiscentos": 600, "seiscentas": 600,
    "setecentos": 700, "setecentas": 700,
    "oitocentos": 800, "oitocentas": 800,
    "novecentos": 900, "novecentas": 900,
}

ALL_NUMBERS = {}
ALL_NUMBERS.update(UNIDADES)
ALL_NUMBERS.update(ESPECIAIS)
ALL_NUMBERS.update(DEZENAS)
ALL_NUMBERS.update(CENTENAS)
ALL_NUMBERS['mil'] = 1000

IGNORAR = {
    'de', 'do', 'da', 'o', 'a', 'os', 'as', 'meu', 'minha',
    'cnpj', 'cpf', 'numero', 'eh', 'ponto', 'barra', 'traco',
    'hifen', 'com', 'por', 'favor', 'deixa', 'ver', 'eu',
    'acho', 'que', 'so', 'momento', 'espera', 'seria',
    'posso', 'repetir', 'no', 'na', 'para', 'anota',
    'ai', 'la', 'ne', 'ta', 'entao', 'olha', 'seguinte',
    'ao', 'contrario', 'invertido', 'tras', 'frente', 'pra',
    'minuto', 'segundo', 'ok', 'to', 'pegando', 'aqui',
    'vou', 'pegar', 'deixe', 'perai', 'calma', 'espere',
}


def normalizar(texto):
    texto = texto.lower().strip()
    texto = unicodedata.normalize('NFD', texto)
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[^\w\s]', ' ', texto)
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto


def tokenizar(texto):
    """Normaliza e retorna tokens, pré-processando atalhos."""
    texto = normalizar(texto)
    
    atalhos = [
        # "mil ao contrário" e variações = 0001 (gíria carioca/brasileira pra bloco CNPJ)
        ("1000 ao contrario", "_0001"),
        ("1000 ao contrário", "_0001"),
        ("1.000 ao contrario", "_0001"),
        ("mil ao contrario", "_0001"),
        ("miuo ao contrario", "_0001"),
        ("miu ao contrario", "_0001"),
        ("mil invertido", "_0001"),
        ("mil de tras pra frente", "_0001"),
        ("ao contrario mil", "_0001"),
        ("1000 invertido", "_0001"),
        ("1000 de tras pra frente", "_0001"),
        # Triplos e duplos
        ("triplo zero", "_000"), ("triplo meia", "_666"), ("triplo seis", "_666"),
        ("triplo sete", "_777"), ("triplo oito", "_888"), ("triplo nove", "_999"),
        ("duplo zero", "_00"), ("duplo um", "_11"), ("duplo dois", "_22"),
        ("duplo tres", "_33"), ("duplo quatro", "_44"), ("duplo cinco", "_55"),
        ("duplo seis", "_66"), ("duplo meia", "_66"), ("duplo sete", "_77"),
        ("duplo oito", "_88"), ("duplo nove", "_99"),
    ]
    for atalho, valor in atalhos:
        texto = texto.replace(atalho, f' {valor} ')
    
    return texto.split()


def parse_numero_composto(tokens, pos):
    """
    A partir da posição pos, tenta consumir o maior número composto possível.
    Retorna (valor_inteiro, quantidade_tokens_consumidos).
    
    Exemplos:
    "mil quinhentos e setenta e oito" → (1578, 7)
    "novecentos e um" → (901, 3)
    "quarenta e sete" → (47, 3)
    "setenta e tres" → (73, 3)
    "quinze" → (15, 1)
    "zero" → (0, 1)
    "mil" → (1000, 1) — será tratado no contexto
    """
    if pos >= len(tokens):
        return None, 0
    
    token = tokens[pos]
    
    # Atalho pré-processado
    if token.startswith('_') and token[1:].isdigit():
        return int(token[1:]), 1
    
    # Número puro no token
    if token.isdigit():
        return int(token), 1
    
    valor = 0
    consumed = 0
    
    # Tentar MIL
    if token == 'mil':
        # Verificar se é "mil" como parte de número composto (mil quinhentos = 1500)
        # ou "mil" isolado significando 0001 no CNPJ
        # Heurística: se o próximo token é centena (quinhentos, etc), é composto
        # Se é dezena ou unidade, "mil" é isolado (0001)
        consumed = 1
        next_pos = pos + consumed
        # Pular "e" se houver
        if next_pos < len(tokens) and tokens[next_pos] == 'e':
            peek_pos = next_pos + 1
        else:
            peek_pos = next_pos
        
        if peek_pos < len(tokens) and tokens[peek_pos] in CENTENAS:
            # "mil quinhentos..." = número composto real
            valor = 1000
            next_val, next_consumed = _parse_centena_dezena_unidade(tokens, next_pos)
            if next_consumed > 0:
                valor += next_val
                consumed += next_consumed
            return valor, consumed
        else:
            # "mil" isolado ou seguido de dezena/unidade = tratar como 1000
            # (será convertido para 0001 na fase final se tiver números antes)
            return 1000, 1
    
    # Tentar número começando por centena, dezena, especial ou unidade
    val, cons = _parse_centena_dezena_unidade(tokens, pos)
    if cons > 0:
        # NO CONTEXTO DE CNPJ/CPF: NÃO compor com "mil" depois.
        # "novecentos e um mil" = 901 + 0001, não 901000.
        # Ninguém fala "novecentos e um mil" querendo dizer 901000 num CNPJ.
        return val, cons
    
    return None, 0


def _parse_centena_dezena_unidade(tokens, pos):
    """Parse centena (+ e + dezena (+ e + unidade))."""
    if pos >= len(tokens):
        return 0, 0
    
    token = tokens[pos]
    valor = 0
    consumed = 0
    
    # Centena
    if token in CENTENAS:
        valor = CENTENAS[token]
        consumed = 1
        
        # + e + dezena/especial/unidade
        if _peek_e(tokens, pos + consumed):
            prox = tokens[pos + consumed + 1] if pos + consumed + 1 < len(tokens) else None
            if prox:
                if prox in DEZENAS:
                    valor += DEZENAS[prox]
                    consumed += 2  # "e" + dezena
                    # + e + unidade
                    if _peek_e(tokens, pos + consumed):
                        prox2 = tokens[pos + consumed + 1] if pos + consumed + 1 < len(tokens) else None
                        if prox2 and (prox2 in UNIDADES or prox2 in ('um', 'uma')):
                            valor += UNIDADES.get(prox2, 1)
                            consumed += 2
                elif prox in ESPECIAIS:
                    valor += ESPECIAIS[prox]
                    consumed += 2
                elif prox in UNIDADES or prox in ('um', 'uma'):
                    valor += UNIDADES.get(prox, 1)
                    consumed += 2
        
        return valor, consumed
    
    # Dezena
    if token in DEZENAS:
        valor = DEZENAS[token]
        consumed = 1
        
        # + e + unidade
        if _peek_e(tokens, pos + consumed):
            prox = tokens[pos + consumed + 1] if pos + consumed + 1 < len(tokens) else None
            if prox and (prox in UNIDADES or prox in ('um', 'uma')):
                valor += UNIDADES.get(prox, 1)
                consumed += 2
        
        return valor, consumed
    
    # Especial (10-19)
    if token in ESPECIAIS:
        return ESPECIAIS[token], 1
    
    # Unidade (0-9)
    if token in UNIDADES:
        return UNIDADES[token], 1
    
    if token in ('um', 'uma'):
        return 1, 1
    
    return 0, 0


def _peek_e(tokens, pos):
    """Verifica se na posição pos tem 'e' seguido de algo."""
    return (pos < len(tokens) and tokens[pos] == 'e' and 
            pos + 1 < len(tokens) and tokens[pos + 1] != 'e')


def extrair_digitos(texto_original):
    """
    Converte texto em string de dígitos puros.
    Cada número composto gera os dígitos do seu valor.
    "mil quinhentos e setenta e oito" → "1578"
    "quarenta e sete" → "47"
    "novecentos e um" → "901"
    "mil" (isolado após outros números) → "0001"
    """
    texto = normalizar(texto_original)
    
    # PRÉ-PROCESSAMENTO: substituir expressões de inversão ANTES de qualquer análise
    # "1000 ao contrario" → "0001", "mil ao contrario" → "0001"
    inversoes = [
        ("1000 ao contrario", "0001"),
        ("1 000 ao contrario", "0001"),
        ("mil ao contrario", "0001"),
        ("miuo ao contrario", "0001"),
        ("miu ao contrario", "0001"),
        ("mil invertido", "0001"),
        ("mil de tras pra frente", "0001"),
        ("ao contrario mil", "0001"),
        ("1000 invertido", "0001"),
        ("1000 de tras pra frente", "0001"),
        ("ao contrario 1000", "0001"),
    ]
    for expr, subst in inversoes:
        texto = texto.replace(expr, f' {subst} ')
    texto = re.sub(r'\s+', ' ', texto).strip()
    
    # Se só contém dígitos (e espaços/pontuação), extrai direto
    digitos_presentes = re.findall(r'\d+', texto)
    if digitos_presentes:
        palavras = re.findall(r'[a-z]+', texto)
        palavras_numericas = [p for p in palavras if p in ALL_NUMBERS]
        # Se tem blocos de dígitos longos (3+), é número puro com texto ao redor
        # Ignorar palavras numéricas ambíguas como "um", "uma"
        tem_bloco_longo = any(len(d) >= 3 for d in digitos_presentes)
        palavras_num_reais = [p for p in palavras_numericas if p not in ('um', 'uma')]
        if not palavras_numericas or (tem_bloco_longo and not palavras_num_reais):
            return ''.join(digitos_presentes)
    
    tokens = tokenizar(texto_original)
    partes = []  # Lista de valores inteiros encontrados
    
    i = 0
    while i < len(tokens):
        token = tokens[i]
        
        # Conectivo "e" solto (entre grupos separados, não compostos)
        if token == 'e':
            i += 1
            continue
        
        # Ignorar palavras não-numéricas
        if token in IGNORAR:
            i += 1
            continue
        
        # Token é dígito puro
        if token.isdigit():
            partes.append(int(token))
            i += 1
            continue
        
        # Atalho — preservar como string pra manter zeros (ex: _000 → "000")
        if token.startswith('_') and token[1:].isdigit():
            partes.append(token[1:])  # String, não int
            i += 1
            continue
        
        # "um"/"uma" — ambíguo: pode ser dígito 1 ou artigo "um minuto"
        # DEVE ser checado ANTES de parse_numero_composto pra evitar
        # que "um momento" vire dígito 1
        if token in ('um', 'uma'):
            if i + 1 < len(tokens):
                proximo = tokens[i + 1]
                # Separadores de documento são transparentes — olhar o token depois
                separadores = {'ponto', 'barra', 'traco', 'hifen'}
                if proximo in separadores and i + 2 < len(tokens):
                    proximo = tokens[i + 2]
                # Se próximo é número, dígito, atalho, ou conectivo "e" → é dígito 1
                if (proximo.isdigit() or proximo in ALL_NUMBERS or 
                    proximo in ('e', 'um', 'uma') or
                    (proximo.startswith('_') and proximo[1:].isdigit()) or
                    proximo == 'mil'):
                    partes.append(1)
                # Se próximo é palavra não-numérica → é artigo, ignorar
                else:
                    pass  # ignorar
            else:
                # Último token → é dígito 1
                partes.append(1)
            i += 1
            continue
        
        # Tentar parsear número composto
        valor, consumed = parse_numero_composto(tokens, i)
        if consumed > 0 and valor is not None:
            partes.append(valor)
            i += consumed
            continue
        
        # Token desconhecido — extrair dígitos se tiver
        d = re.sub(r'[^0-9]', '', token)
        if d:
            partes.append(int(d))
        
        i += 1
    
    # Converter partes para string de dígitos
    resultado = []
    for idx, val in enumerate(partes):
        if isinstance(val, str):
            # Atalho já é string com zeros preservados
            resultado.append(val)
        elif val == 1000 and len(partes) > 1 and idx > 0:
            resultado.append("0001")
        else:
            resultado.append(str(val))
    
    return ''.join(resultado)


@app.route('/api/validation/documento', methods=['GET', 'POST'])
def validar_documento():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        cnpj_raw = data.get('cnpj', '')
        cpf_raw = data.get('cpf', '')
    else:
        cnpj_raw = request.args.get('cnpj', '').strip('"').strip("'")
        cpf_raw = request.args.get('cpf', '').strip('"').strip("'")
    
    response = {}
    
    if cnpj_raw:
        digitos = extrair_digitos(cnpj_raw)
        qtd = len(digitos)
        if qtd == 14:
            response['cnpj_valido'] = "True"
        else:
            response['cnpj_valido'] = "False"
            response['mensagem'] = f"CNPJ COM APENAS {qtd} DIGITOS"
    
    if cpf_raw:
        digitos = extrair_digitos(cpf_raw)
        qtd = len(digitos)
        if qtd == 11:
            response['cpf_valido'] = "True"
        else:
            response['cpf_valido'] = "False"
            response['mensagem'] = f"CPF COM APENAS {qtd} DIGITOS"
    
    return jsonify(response)


@app.route('/api/validation/teste', methods=['GET'])
def teste():
    texto = request.args.get('texto', '').strip('"').strip("'")
    if not texto:
        return jsonify({"erro": "Passe ?texto=seu texto aqui"})
    digitos = extrair_digitos(texto)
    return jsonify({
        "input": texto,
        "digitos_extraidos": digitos,
        "quantidade_digitos": len(digitos)
    })


@app.route('/', methods=['GET'])
def health():
    return jsonify({"status": "ok", "servico": "Validador CNPJ/CPF v3"})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
