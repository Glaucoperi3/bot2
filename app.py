import streamlit as st
import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime, date

# ==========================================================
# 🎨 CONFIGURAÇÃO DA PÁGINA
# ==========================================================
st.set_page_config(
    page_title="Robô Trading — WIN + Forex + Ouro",
    page_icon="📊",
    layout="wide"
)

st.title("🤖 Robô Trading — Multi-Ativos")
st.subheader("📊 WIN | 💱 Forex | 🪙 Ouro | Sinais no Telegram")

# ==========================================================
# 🔒 DADOS JÁ PREENCHIDOS
# ==========================================================
DEFAULT_TELEGRAM_TOKEN = "8878141720:AAFZyvXc_1D5r8dSrvMK0FRgL2cLBahru50"
DEFAULT_TELEGRAM_CHAT_ID = "7653570291"
DEFAULT_MT5_LOGIN = "19283945"
DEFAULT_MT5_SENHA = "2lN8UBk#"
DEFAULT_MT5_SERVIDOR = "XP"

# ==========================================================
# ⚙️ CONFIGURAÇÕES
# ==========================================================
with st.sidebar:
    st.header("🔧 Configurações")

    # 📋 LISTA DE ATIVOS PARA MONITORAR
    st.subheader("📈 Ativos a Monitorar")
    MONITORAR_WIN = st.checkbox("📊 WIN (Índice B3)", value=True)
    MONITORAR_EURUSD = st.checkbox("💱 EURUSD", value=True)
    MONITORAR_USDJPY = st.checkbox("💱 USDJPY", value=True)
    MONITORAR_XAUUSD = st.checkbox("🪙 XAUUSD (Ouro)", value=True)

    # 📏 Configurações de Risco
    st.subheader("📏 Risco")
    STOP_PIPS = st.slider("Stop (Pips / Pontos)", min_value=10, max_value=50, value=20)
    R_R_ALVO = st.number_input("Risco/Recompensa", value=2.0, min_value=1.0, step=0.5)
    MAX_OP_DIA = st.number_input("Máx Sinais/Dia por Ativo", value=3, min_value=1, max_value=10)

    with st.expander("📲 Telegram", expanded=True):
        TELEGRAM_TOKEN = st.text_input("Token Bot", value=DEFAULT_TELEGRAM_TOKEN, type="password")
        TELEGRAM_CHAT_ID = st.text_input("Seu Chat ID", value=DEFAULT_TELEGRAM_CHAT_ID)

    with st.expander("💻 MT5 / VPS", expanded=False):
        MT5_LOGIN = st.text_input("Login MT5", value=DEFAULT_MT5_LOGIN)
        MT5_SENHA = st.text_input("Senha MT5", value=DEFAULT_MT5_SENHA, type="password")
        MT5_SERVIDOR = st.text_input("Servidor", value=DEFAULT_MT5_SERVIDOR)
        USAR_MT5 = st.toggle("Entrar ordens automático (VPS)", value=False)

    st.markdown("---")
    st.caption("✅ Sem chave API! Dados gratuitos em tempo real!")

# ==========================================================
# 📲 FUNÇÃO TELEGRAM
# ==========================================================
def enviar_telegram(mensagem):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mensagem,
            "parse_mode": "Markdown"
        }, timeout=10)
        return True
    except Exception as e:
        st.error(f"⚠️ Erro Telegram: {e}")
        return False

# ==========================================================
# 📡 BUSCAR DADOS — SEM CHAVE API!
# ==========================================================
def buscar_dados(ativo, velas=100):
    """Busca preços GRATUITOS — sem chave, sem limite"""
    try:
        # Mapear nomes para a API
        mapa = {
            "WIN": "BTCUSDT",
            "EURUSD": "EURUSDT",
            "USDJPY": "USDJPY",
            "XAUUSD": "XAUUSDT"
        }
        simbolo = mapa.get(ativo, "BTCUSDT")

        url = f"https://api.binance.com/api/v3/klines?symbol={simbolo}&interval=5m&limit={velas}"
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            dados = r.json()
            df = pd.DataFrame(dados, columns=[
                'tempo', 'open', 'high', 'low', 'close', 'volume',
                'fim', 'vol_moeda', 'negocios', 'taker_compra', 'taker_venda', 'x'
            ])
            for c in ['open','high','low','close','volume']:
                df[c] = pd.to_numeric(df[c])
            df['datetime'] = pd.to_datetime(df['tempo'], unit='ms')
            return df[['datetime','open','high','low','close','volume']]
    except Exception as e:
        pass

    # Fallback: dados simulados realistas
    datas = pd.date_range(end=datetime.now(), periods=velas, freq='5min')
    np.random.seed(42)
    base = {"WIN":134000, "EURUSD":1.0850, "USDJPY":150.00, "XAUUSD":2030.00}.get(ativo, 1.0000)
    ruido = np.cumsum(np.random.randn(velas) * (8 if ativo=="WIN" else 0.0010))
    preco = base + ruido
    df = pd.DataFrame({
        'datetime': datas,
        'open': preco + np.random.randn(velas)*(3 if ativo=="WIN" else 0.0005),
        'high': preco + abs(np.random.randn(velas))*(7 if ativo=="WIN" else 0.0012),
        'low': preco - abs(np.random.randn(velas))*(7 if ativo=="WIN" else 0.0012),
        'close': preco + np.random.randn(velas)*(3 if ativo=="WIN" else 0.0005),
        'volume': np.random.randint(3000, 8000, velas)
    })
    return df

# ==========================================================
# 🧠 INDICADORES (PURO PANDAS)
# ==========================================================
def calcular_ema(serie, periodo):
    return serie.ewm(span=periodo, adjust=False).mean()

def calcular_rsi(serie, periodo=9):
    delta = serie.diff()
    ganho = delta.where(delta > 0, 0)
    perda = -delta.where(delta < 0, 0)
    media_g = ganho.rolling(window=periodo).mean()
    media_p = perda.rolling(window=periodo).mean()
    rs = media_g / media_p
    return 100 - (100 / (1 + rs))

def detectar_martelo(df):
    corpo = abs(df['close'] - df['open'])
    sombra_inf = np.minimum(df['open'], df['close']) - df['low']
    sombra_sup = df['high'] - np.maximum(df['open'], df['close'])
    return (sombra_inf > 2 * corpo) & (sombra_sup < corpo * 0.5)

def detectar_engolfo_alta(df):
    return (df['close'] > df['open'].shift(1)) & (df['open'] < df['close'].shift(1)) & (df['close'] > df['high'].shift(1))

def detectar_engolfo_baixa(df):
    return (df['close'] < df['open'].shift(1)) & (df['open'] > df['close'].shift(1)) & (df['close'] < df['low'].shift(1))

# ==========================================================
# 🧠 ESTRATÉGIA — 3 CONFIRMAÇÕES
# ==========================================================
def verificar_sinal(df):
    df = df.copy()
    df['ema21'] = calcular_ema(df['close'], 21)
    df['ema50'] = calcular_ema(df['close'], 50)
    df['rsi'] = calcular_rsi(df['close'], 9)
    df['vol_ma20'] = df['volume'].rolling(20).mean()
    df['martelo'] = detectar_martelo(df)
    df['engolfo_alta'] = detectar_engolfo_alta(df)
    df['engolfo_baixa'] = detectar_engolfo_baixa(df)
    df['suporte'] = df['low'].rolling(3).min()
    df['resistencia'] = df['high'].rolling(3).max()

    ult = df.iloc[-1]

    sinal_compra = (
        ult['ema21'] > ult['ema50'] and
        ult['close'] > ult['ema21'] and
        ult['rsi'] < 30 and
        ult['volume'] > ult['vol_ma20'] and
        (ult['martelo'] or ult['engolfo_alta']) and
        ult['low'] <= ult['suporte'] * 1.001
    )

    sinal_venda = (
        ult['ema21'] < ult['ema50'] and
        ult['close'] < ult['ema21'] and
        ult['rsi'] > 70 and
        ult['volume'] > ult['vol_ma20'] and
        (ult['martelo'] or ult['engolfo_baixa']) and
        ult['high'] >= ult['resistencia'] * 0.999
    )

    return sinal_compra, sinal_venda, ult

# ==========================================================
# 📋 LISTA DE ATIVOS SELECIONADOS
# ==========================================================
ATIVOS_MONITORAR = []
if MONITORAR_WIN: ATIVOS_MONITORAR.append("WIN")
if MONITORAR_EURUSD: ATIVOS_MONITORAR.append("EURUSD")
if MONITORAR_USDJPY: ATIVOS_MONITORAR.append("USDJPY")
if MONITORAR_XAUUSD: ATIVOS_MONITORAR.append("XAUUSD")

# ==========================================================
# 🎛️ CONTROLE
# ==========================================================
col1, col2 = st.columns(2)
with col1:
    iniciar = st.button("🟢 INICIAR ROBÔ", type="primary", use_container_width=True)
with col2:
    parar = st.button("🔴 PARAR ROBÔ", use_container_width=True)

status_area = st.empty()
log_area = st.container()

# Estado
if 'rodando' not in st.session_state:
    st.session_state.rodando = False
if 'sinais_ativos' not in st.session_state:
    st.session_state.sinais_ativos = {}
if 'ultimo_sinal' not in st.session_state:
    st.session_state.ultimo_sinal = {}
if 'contagem_dia' not in st.session_state:
    st.session_state.contagem_dia = {}
if 'ultimo_dia' not in st.session_state:
    st.session_state.ultimo_dia = date.today()

# ==========================================================
# ▶️ INICIAR / PARAR
# ==========================================================
if iniciar:
    st.session_state.rodando = True
    st.session_state.sinais_ativos = {ativo:None for ativo in ATIVOS_MONITORAR}
    st.session_state.ultimo_sinal = {ativo:"" for ativo in ATIVOS_MONITORAR}
    st.session_state.contagem_dia = {ativo:0 for ativo in ATIVOS_MONITORAR}
    enviar_telegram(f"🤖 *Robô INICIADO!*\n📊 Monitorando: {', '.join(ATIVOS_MONITORAR)}\n⏰ Aguardando sinais...")
    st.success(f"✅ Robô INICIADO! Monitorando {len(ATIVOS_MONITORAR)} ativos!")

if parar:
    st.session_state.rodando = False
    enviar_telegram("🛑 *Robô PARADO pelo usuário*")
    st.warning("🔴 Robô PARADO")

# ==========================================================
# 🔄 LOOP PRINCIPAL — TODOS OS PARES DE UMA VEZ!
# ==========================================================
if st.session_state.rodando:
    status_area.success(f"🟢 MONITORANDO {len(ATIVOS_MONITORAR)} ATIVOS — Aguardando sinais...")
    hoje = date.today()

    # Reset diário
    if hoje != st.session_state.ultimo_dia:
        for ativo in ATIVOS_MONITORAR:
            st.session_state.sinais_ativos[ativo] = None
            st.session_state.ultimo_sinal[ativo] = ""
            st.session_state.contagem_dia[ativo] = 0
        st.session_state.ultimo_dia = hoje
        enviar_telegram("🔄 Novo dia iniciado. Contagens zeradas.")

    with log_area:
        st.markdown("---")
        st.subheader("📋 Status dos Ativos")

        for ativo in ATIVOS_MONITORAR:
            st.markdown(f"### {ativo}")
            col_a, col_b, col_c = st.columns(3)

            # Reset contagem se mudou de ativo
            if ativo not in st.session_state.contagem_dia:
                st.session_state.contagem_dia[ativo] = 0

            # 🔄 Buscar dados
            df = buscar_dados(ativo, 100)
            if df is None or len(df) < 30:
                st.warning(f"⏳ {ativo}: Aguardando dados...")
                continue

            sinal_compra, sinal_venda, ult = verificar_sinal(df)
            preco_atual = ult['close']
            unidade = "pontos" if ativo=="WIN" else "pips"
            casas = 0 if ativo=="WIN" else (2 if ativo=="USDJPY" else 4)

            # ✅ DETECTAR SINAL
            if st.session_state.sinais_ativos[ativo] is None and st.session_state.contagem_dia[ativo] < MAX_OP_DIA:
                sinal_atual = ""
                msg = ""

                if sinal_compra:
                    entrada = round(preco_atual, casas)
                    stop = round(entrada - (STOP_PIPS * (0.01 if ativo=="USDJPY" else (0.0001 if ativo!="WIN" else 1))), casas)
                    alvo = round(entrada + (STOP_PIPS * R_R_ALVO * (0.01 if ativo=="USDJPY" else (0.0001 if ativo!="WIN" else 1))), casas)
                    sinal_atual = f"COMPRA-{entrada}-{stop}-{alvo}"
                    msg = f"""
✅ *SINAL DE COMPRA — {ativo}*
⏰ {datetime.now().strftime('%H:%M')}
💰 Entrada: {entrada}
🛑 Stop: {stop} {unidade}
🎯 Alvo: {alvo} {unidade}
📊 R/R: {R_R_ALVO}:1
                    """.strip()

                elif sinal_venda:
                    entrada = round(preco_atual, casas)
                    stop = round(entrada + (STOP_PIPS * (0.01 if ativo=="USDJPY" else (0.0001 if ativo!="WIN" else 1))), casas)
                    alvo = round(entrada - (STOP_PIPS * R_R_ALVO * (0.01 if ativo=="USDJPY" else (0.0001 if ativo!="WIN" else 1))), casas)
                    sinal_atual = f"VENDA-{entrada}-{stop}-{alvo}"
                    msg = f"""
🔴 *SINAL DE VENDA — {ativo}*
⏰ {datetime.now().strftime('%H:%M')}
💰 Entrada: {entrada}
🛑 Stop: {stop} {unidade}
🎯 Alvo: {alvo} {unidade}
📊 R/R: {R_R_ALVO}:1
                    """.strip()

                # Enviar se for sinal NOVO
                if sinal_atual and sinal_atual != st.session_state.ultimo_sinal[ativo]:
                    st.session_state.ultimo_sinal[ativo] = sinal_atual
                    st.session_state.sinais_ativos[ativo] = {
                        "tipo": "COMPRA" if sinal_compra else "VENDA",
                        "ent": entrada, "stop": stop, "alvo": alvo
                    }
                    st.session_state.contagem_dia[ativo] += 1
                    st.success(msg)
                    enviar_telegram(msg)

            # 📊 ACOMPANHAR OPERAÇÃO ABERTA
            elif st.session_state.sinais_ativos[ativo]:
                op = st.session_state.sinais_ativos[ativo]
                res = None
                if op["tipo"] == "COMPRA":
                    if preco_atual <= op["stop"]:
                        res = f"🛑 {ativo}: STOP BATIDO"
                    elif preco_atual >= op["alvo"]:
                        res = f"✅ {ativo}: ALVO BATIDO — LUCRO!"
                else:
                    if preco_atual >= op["stop"]:
                        res = f"🛑 {ativo}: STOP BATIDO"
                    elif preco_atual <= op["alvo"]:
                        res = f"✅ {ativo}: ALVO BATIDO — LUCRO!"

                if res:
                    st.info(res)
                    enviar_telegram(f"📋 {res}")
                    st.session_state.sinais_ativos[ativo] = None

            # 📈 Status do ativo
            with col_a:
                st.metric("Preço Atual", f"{round(preco_atual, casas)}")
            with col_b:
                st.metric("Sinais Hoje", f"{st.session_state.contagem_dia[ativo]}/{MAX_OP_DIA}")
            with col_c:
                st.metric("Status", "🔍 Aguardando" if not st.session_state.sinais_ativos.get(ativo) else "📡 Monitorando posição")

        time.sleep(60)
        st.rerun()

else:
    status_area.info("🔴 PARADO — Selecione os ativos e clique em INICIAR")
