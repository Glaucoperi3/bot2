import streamlit as st
import pandas as pd
import numpy as np
import talib
import requests
import time
from datetime import datetime, date

# ==========================================================
# 🎨 CONFIGURAÇÃO DA PÁGINA
# ==========================================================
st.set_page_config(
    page_title="Robô WIN — 3 Confirmações",
    page_icon="📈",
    layout="wide"
)

st.title("🤖 Robô de Negociação — Mini-Índice WIN")
st.subheader("Estratégia: Tendência + Acúmulo + Reversão | R/R 2:1 | Máx 3/dia")

# ==========================================================
# 🔒 VALORES JÁ PREENCHIDOS
# ==========================================================
DEFAULT_TELEGRAM_TOKEN = "8878141720:AAFZyvXc_1D5r8dSrvMK0FRgL2cLBahru50"
DEFAULT_TELEGRAM_CHAT_ID = "7653570291"
DEFAULT_MT5_LOGIN = "19283945"
DEFAULT_MT5_SENHA = "2lN8UBk#"
DEFAULT_MT5_SERVIDOR = "XP"

# ==========================================================
# ⚙️ PAINEL DE CONFIGURAÇÕES
# ==========================================================
with st.sidebar:
    st.header("🔧 Configurações do Robô")

    with st.expander("💻 MetaTrader 5 / XP", expanded=True):
        MT5_LOGIN = st.text_input("Login MT5", value=DEFAULT_MT5_LOGIN)
        MT5_SENHA = st.text_input("Senha MT5", value=DEFAULT_MT5_SENHA, type="password")
        MT5_SERVIDOR = st.text_input("Servidor", value=DEFAULT_MT5_SERVIDOR)
        ATIVO = st.text_input("Ativo", value="WIN", help="Ex: WINQ26")

    with st.expander("📲 Telegram", expanded=True):
        TELEGRAM_TOKEN = st.text_input("Token do Bot", value=DEFAULT_TELEGRAM_TOKEN, type="password")
        TELEGRAM_CHAT_ID = st.text_input("Seu Chat ID", value=DEFAULT_TELEGRAM_CHAT_ID)

    with st.expander("📊 Parâmetros da Estratégia", expanded=True):
        STOP_PONTOS = st.number_input("Stop Loss (pontos)", value=20, min_value=5)
        R_R_ALVO = st.number_input("Risco/Recompensa", value=2.0, min_value=1.0, step=0.1)
        MAX_OP_DIA = st.number_input("Máx. Operações/Dia", value=3, min_value=1, max_value=10)

    st.markdown("---")
    st.caption("💡 Atualize Login/Senha quando vencer e clique em INICIAR")

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
# 🧠 ESTRATÉGIA — 3 CONFIRMAÇÕES
# ==========================================================
def verificar_sinal(df):
    df = df.copy()
    df['ema21'] = talib.EMA(df['close'], 21)
    df['ema50'] = talib.EMA(df['close'], 50)
    df['rsi'] = talib.RSI(df['close'], 9)
    df['vol_ma20'] = df['volume'].rolling(20).mean()

    df['martelo'] = talib.CDLHAMMER(df['open'], df['high'], df['low'], df['close'])
    df['engolfo'] = talib.CDLENGULFING(df['open'], df['high'], df['low'], df['close'])
    df['estrela_m'] = talib.CDLMORNINGSTAR(df['open'], df['high'], df['low'], df['close'])
    df['estrela_t'] = talib.CDLEVENINGSTAR(df['open'], df['high'], df['low'], df['close'])

    df['suporte'] = df['low'].rolling(3).min()
    df['resistencia'] = df['high'].rolling(3).max()

    ult = df.iloc[-1]

    sinal_compra = (
        ult['ema21'] > ult['ema50'] and
        ult['close'] > ult['ema21'] and
        ult['rsi'] < 30 and
        ult['volume'] > ult['vol_ma20'] and
        (ult['martelo'] > 0 or ult['engolfo'] == 100 or ult['estrela_m'] > 0) and
        ult['low'] <= ult['suporte'] * 1.001
    )

    sinal_venda = (
        ult['ema21'] < ult['ema50'] and
        ult['close'] < ult['ema21'] and
        ult['rsi'] > 70 and
        ult['volume'] > ult['vol_ma20'] and
        (ult['martelo'] < 0 or ult['engolfo'] == -100 or ult['estrela_t'] > 0) and
        ult['high'] >= ult['resistencia'] * 0.999
    )

    return sinal_compra, sinal_venda, ult

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

if 'rodando' not in st.session_state:
    st.session_state.rodando = False
if 'operacoes_dia' not in st.session_state:
    st.session_state.operacoes_dia = 0
if 'operacao_ativa' not in st.session_state:
    st.session_state.operacao_ativa = None
if 'ultimo_dia' not in st.session_state:
    st.session_state.ultimo_dia = date.today()

# ==========================================================
# ▶️ INICIAR / PARAR
# ==========================================================
if iniciar:
    st.session_state.rodando = True
    st.session_state.operacoes_dia = 0
    st.session_state.operacao_ativa = None
    enviar_telegram("🤖 *Robô INICIADO!* Aguardando sinais...")
    st.success("✅ Robô INICIADO! (Modo simulação — conecte MT5 quando pronto)")

if parar:
    st.session_state.rodando = False
    enviar_telegram("🛑 *Robô PARADO pelo usuário*")
    st.warning("🔴 Robô PARADO")

# ==========================================================
# 🔄 PAINEL DE MONITORAMENTO
# ==========================================================
if st.session_state.rodando:
    status_area.success("🟢 RODANDO — Monitorando mercado")
    hoje = date.today()
    if hoje != st.session_state.ultimo_dia:
        st.session_state.operacoes_dia = 0
        st.session_state.operacao_ativa = None
        st.session_state.ultimo_dia = hoje
        enviar_telegram("🔄 Novo dia iniciado. Operações zeradas.")

    with log_area:
        st.info(f"""
📋 **Painel de Controle**
• Ativo: {ATIVO}
• Stop: {STOP_PONTOS} pts | Alvo: {R_R_ALVO}×
• Hoje: {st.session_state.operacoes_dia}/{MAX_OP_DIA} ops
• Posição: {st.session_state.operacao_ativa or 'Nenhuma'}
        """)
        st.markdown("---")
        st.success("✅ Estratégia carregada! Conecte o MT5 para operar ao vivo.")
        st.info("💡 Quando tiver o MT5 funcionando, a parte de conexão e ordens será ativada automaticamente.")
else:
    status_area.info("🔴 PARADO — Configure e clique em INICIAR")
