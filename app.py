import streamlit as st
import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime, date
from typing import Optional, Dict, Tuple

# MetaTrader 5 is required for real market data/execution.
try:
    import MetaTrader5 as mt5
    MT5_LIB_OK = True
except ImportError:
    mt5 = None
    MT5_LIB_OK = False


# ==========================================================
# CONFIGURAÇÃO
# ==========================================================
st.set_page_config(
    page_title="Robô Trading — MT5",
    page_icon="📊",
    layout="wide",
)

st.title("🤖 Robô Trading — MT5")
st.caption("Dados do próprio MetaTrader 5 • candles fechados • Paper Trade por padrão")


# ==========================================================
# FUNÇÕES
# ==========================================================
def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def enviar_telegram(token: str, chat_id: str, mensagem: str) -> bool:
    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    try:
        response = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": mensagem,
                "parse_mode": "Markdown",
            },
            timeout=10,
        )
        return response.ok
    except requests.RequestException:
        return False


def conectar_mt5(login: str, senha: str, servidor: str) -> Tuple[bool, str]:
    if not MT5_LIB_OK:
        return False, "Biblioteca MetaTrader5 não instalada."

    # Se já estiver conectado, tenta reutilizar.
    info = mt5.account_info()
    if info is not None:
        return True, "MT5 já conectado."

    if not mt5.initialize():
        return False, f"Falha ao inicializar MT5: {mt5.last_error()}"

    if login and senha and servidor:
        ok = mt5.login(int(login), password=senha, server=servidor)
        if not ok:
            return False, f"Falha no login MT5: {mt5.last_error()}"

    info = mt5.account_info()
    if info is None:
        return False, f"Conta MT5 indisponível: {mt5.last_error()}"

    return True, f"Conectado: {info.name} | {info.server}"


def desconectar_mt5():
    if MT5_LIB_OK:
        try:
            mt5.shutdown()
        except Exception:
            pass


def encontrar_simbolo(candidatos: str) -> Optional[str]:
    """
    Recebe nomes separados por vírgula e escolhe o primeiro símbolo
    existente no terminal. Isso permite lidar com nomes diferentes
    entre corretoras/contratos.
    """
    if not MT5_LIB_OK:
        return None

    for candidato in [x.strip() for x in candidatos.split(",") if x.strip()]:
        info = mt5.symbol_info(candidato)
        if info is not None:
            if not info.visible:
                mt5.symbol_select(candidato, True)
            return candidato

    return None


def buscar_dados_mt5(simbolo: str, velas: int = 150) -> Optional[pd.DataFrame]:
    if not MT5_LIB_OK or not simbolo:
        return None

    # M5: posição 0 é o candle atual/incompleto.
    # Começamos em 1 para usar somente candles fechados.
    rates = mt5.copy_rates_from_pos(simbolo, mt5.TIMEFRAME_M5, 1, velas)

    if rates is None or len(rates) < 60:
        return None

    df = pd.DataFrame(rates)
    df["datetime"] = pd.to_datetime(df["time"], unit="s")
    df.rename(
        columns={
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "tick_volume": "volume",
        },
        inplace=True,
    )

    return df[["datetime", "open", "high", "low", "close", "volume"]].copy()


# ==========================================================
# INDICADORES
# ==========================================================
def calcular_ema(serie: pd.Series, periodo: int) -> pd.Series:
    return serie.ewm(span=periodo, adjust=False).mean()


def calcular_rsi_wilder(serie: pd.Series, periodo: int = 9) -> pd.Series:
    delta = serie.diff()
    ganho = delta.clip(lower=0)
    perda = -delta.clip(upper=0)

    media_ganho = ganho.ewm(alpha=1 / periodo, adjust=False, min_periods=periodo).mean()
    media_perda = perda.ewm(alpha=1 / periodo, adjust=False, min_periods=periodo).mean()

    rs = media_ganho / media_perda.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    # Tratamento de extremos.
    rsi = rsi.where(~((media_perda == 0) & (media_ganho > 0)), 100)
    rsi = rsi.where(~((media_ganho == 0) & (media_perda > 0)), 0)

    return rsi


def detectar_martelo(df: pd.DataFrame) -> pd.Series:
    corpo = (df["close"] - df["open"]).abs()
    corpo_seguro = corpo.replace(0, np.finfo(float).eps)

    sombra_inf = np.minimum(df["open"], df["close"]) - df["low"]
    sombra_sup = df["high"] - np.maximum(df["open"], df["close"])

    return (
        (sombra_inf >= 2 * corpo_seguro)
        & (sombra_sup <= corpo_seguro)
    )


def detectar_shooting_star(df: pd.DataFrame) -> pd.Series:
    corpo = (df["close"] - df["open"]).abs()
    corpo_seguro = corpo.replace(0, np.finfo(float).eps)

    sombra_inf = np.minimum(df["open"], df["close"]) - df["low"]
    sombra_sup = df["high"] - np.maximum(df["open"], df["close"])

    return (
        (sombra_sup >= 2 * corpo_seguro)
        & (sombra_inf <= corpo_seguro)
    )


def detectar_engolfo_alta(df: pd.DataFrame) -> pd.Series:
    corpo_atual = (df["close"] - df["open"]).abs()
    corpo_anterior = (df["close"].shift(1) - df["open"].shift(1)).abs()

    return (
        (df["close"].shift(1) < df["open"].shift(1))
        & (df["close"] > df["open"])
        & (df["open"] <= df["close"].shift(1))
        & (df["close"] >= df["open"].shift(1))
        & (corpo_atual >= corpo_anterior * 0.8)
    )


def detectar_engolfo_baixa(df: pd.DataFrame) -> pd.Series:
    corpo_atual = (df["close"] - df["open"]).abs()
    corpo_anterior = (df["close"].shift(1) - df["open"].shift(1)).abs()

    return (
        (df["close"].shift(1) > df["open"].shift(1))
        & (df["close"] < df["open"])
        & (df["open"] >= df["close"].shift(1))
        & (df["close"] <= df["open"].shift(1))
        & (corpo_atual >= corpo_anterior * 0.8)
    )


def preparar_indicadores(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["ema21"] = calcular_ema(df["close"], 21)
    df["ema50"] = calcular_ema(df["close"], 50)
    df["rsi"] = calcular_rsi_wilder(df["close"], 9)

    df["vol_ma20"] = df["volume"].rolling(20).mean()

    df["martelo"] = detectar_martelo(df)
    df["shooting_star"] = detectar_shooting_star(df)
    df["engolfo_alta"] = detectar_engolfo_alta(df)
    df["engolfo_baixa"] = detectar_engolfo_baixa(df)

    # Suporte/resistência usa somente candles anteriores.
    df["suporte"] = df["low"].shift(1).rolling(10).min()
    df["resistencia"] = df["high"].shift(1).rolling(10).max()

    return df


def verificar_sinal(
    df: pd.DataFrame,
    rsi_compra: float,
    rsi_venda: float,
) -> Tuple[Optional[str], pd.Series]:

    df = preparar_indicadores(df)
    ult = df.iloc[-1]

    valores_ok = not ult[
        ["ema21", "ema50", "rsi", "vol_ma20", "suporte", "resistencia"]
    ].isna().any()

    if not valores_ok:
        return None, ult

    volume_forte = ult["volume"] > ult["vol_ma20"]

    reversao_alta = bool(ult["martelo"] or ult["engolfo_alta"])
    reversao_baixa = bool(ult["shooting_star"] or ult["engolfo_baixa"])

    # Estratégia por confluência.
    compra = (
        ult["ema21"] > ult["ema50"]
        and ult["close"] > ult["ema21"]
        and ult["rsi"] <= rsi_compra
        and volume_forte
        and reversao_alta
        and ult["low"] <= ult["suporte"] * 1.002
    )

    venda = (
        ult["ema21"] < ult["ema50"]
        and ult["close"] < ult["ema21"]
        and ult["rsi"] >= rsi_venda
        and volume_forte
        and reversao_baixa
        and ult["high"] >= ult["resistencia"] * 0.998
    )

    if compra:
        return "COMPRA", ult

    if venda:
        return "VENDA", ult

    return None, ult


# ==========================================================
# PREÇO / STOP / ALVO
# ==========================================================
def calcular_niveis(
    tipo: str,
    entrada: float,
    distancia: float,
    rr: float,
    digits: int,
) -> Tuple[float, float]:
    if tipo == "COMPRA":
        stop = entrada - distancia
        alvo = entrada + distancia * rr
    else:
        stop = entrada + distancia
        alvo = entrada - distancia * rr

    return round(stop, digits), round(alvo, digits)


def normalizar_volume(simbolo: str, volume: float) -> float:
    info = mt5.symbol_info(simbolo)

    if info is None:
        return volume

    step = safe_float(info.volume_step, 0.01)
    vmin = safe_float(info.volume_min, step)
    vmax = safe_float(info.volume_max, volume)

    if step <= 0:
        return max(vmin, min(volume, vmax))

    volume = max(vmin, min(volume, vmax))
    passos = round(volume / step)
    return round(passos * step, 8)


def calcular_volume_por_risco(
    simbolo: str,
    entrada: float,
    stop: float,
    risco_reais: float,
) -> float:
    """
    Estima o volume usando tick_value/tick_size do próprio MT5.
    Para instrumentos com especificações especiais, confira o
    contrato da corretora antes de usar execução automática.
    """
    info = mt5.symbol_info(simbolo)

    if info is None:
        return 0.0

    tick_size = safe_float(info.trade_tick_size)
    tick_value = safe_float(info.trade_tick_value)

    distancia = abs(entrada - stop)

    if tick_size <= 0 or tick_value <= 0 or distancia <= 0:
        return 0.0

    risco_por_lote = (distancia / tick_size) * tick_value

    if risco_por_lote <= 0:
        return 0.0

    volume = risco_reais / risco_por_lote
    return normalizar_volume(simbolo, volume)


# ==========================================================
# EXECUÇÃO MT5
# ==========================================================
def enviar_ordem_mt5(
    simbolo: str,
    tipo: str,
    volume: float,
    entrada: float,
    stop: float,
    alvo: float,
) -> Tuple[bool, str]:

    if not MT5_LIB_OK:
        return False, "MetaTrader5 não instalado."

    info = mt5.symbol_info_tick(simbolo)

    if info is None:
        return False, f"Sem tick para {simbolo}."

    if tipo == "COMPRA":
        order_type = mt5.ORDER_TYPE_BUY
        price = info.ask
    else:
        order_type = mt5.ORDER_TYPE_SELL
        price = info.bid

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": simbolo,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": stop,
        "tp": alvo,
        "deviation": 20,
        "magic": 26081501,
        "comment": "RoboStreamlit",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_RETURN,
    }

    result = mt5.order_send(request)

    if result is None:
        return False, f"order_send retornou None: {mt5.last_error()}"

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return False, f"Ordem recusada: retcode={result.retcode}, comentário={result.comment}"

    return True, f"Ordem executada. Ticket={result.order}"


# ==========================================================
# CONFIGURAÇÃO SIDEBAR
# ==========================================================
with st.sidebar:
    st.header("⚙️ Configurações")

    st.subheader("📈 Ativos")
    usar_win = st.checkbox("WIN", True)
    usar_eurusd = st.checkbox("EURUSD", True)
    usar_usdjpy = st.checkbox("USDJPY", True)
    usar_xauusd = st.checkbox("XAUUSD", True)

    st.caption(
        "Use o nome EXATO do símbolo mostrado no Market Watch do seu MT5. "
        "Você pode informar alternativas separadas por vírgula."
    )

    simbolo_win = st.text_input("Símbolo WIN", "WIN$N,WINQ26,WINM26")
    simbolo_eurusd = st.text_input("Símbolo EURUSD", "EURUSD,EURUSDm")
    simbolo_usdjpy = st.text_input("Símbolo USDJPY", "USDJPY,USDJPYm")
    simbolo_xauusd = st.text_input("Símbolo XAUUSD", "XAUUSD,XAUUSDm")

    st.subheader("🎯 Estratégia")
    stop_dist = st.number_input(
        "Stop em preço/pontos",
        min_value=0.00001,
        value=20.0,
        step=1.0,
        format="%.5f",
    )
    rr = st.number_input(
        "Risco/Recompensa",
        min_value=1.0,
        value=2.0,
        step=0.5,
    )
    rsi_compra = st.slider("RSI máximo para COMPRA", 10, 50, 30)
    rsi_venda = st.slider("RSI mínimo para VENDA", 50, 90, 70)
    max_sinais = st.number_input(
        "Máx. sinais/dia por ativo",
        min_value=1,
        max_value=20,
        value=3,
    )

    st.subheader("💰 Gestão de risco")
    risco_reais = st.number_input(
        "Risco máximo por operação (R$)",
        min_value=1.0,
        value=20.0,
        step=5.0,
    )

    st.subheader("📲 Telegram")
    telegram_token = st.text_input(
        "Token do bot",
        value="",
        type="password",
        help="Não coloque o token diretamente no código.",
    )
    telegram_chat_id = st.text_input("Chat ID", value="")

    st.subheader("💻 MT5")
    mt5_login = st.text_input("Login", value="")
    mt5_senha = st.text_input("Senha", value="", type="password")
    mt5_servidor = st.text_input("Servidor", value="XP")

    modo_execucao = st.selectbox(
        "Modo",
        [
            "PAPER TRADE — não envia ordens",
            "REAL — envia ordens para o MT5",
        ],
        index=0,
    )

    confirmar_real = st.checkbox(
        "CONFIRMO QUE O MODO REAL PODE ENVIAR ORDENS",
        value=False,
        disabled=modo_execucao.startswith("PAPER"),
    )

    st.caption("⚠️ Nunca opere dinheiro real antes de validar a estratégia em backtest/demo.")


# ==========================================================
# ESTADO
# ==========================================================
if "rodando" not in st.session_state:
    st.session_state.rodando = False

if "ultimo_sinal" not in st.session_state:
    st.session_state.ultimo_sinal = {}

if "operacoes" not in st.session_state:
    st.session_state.operacoes = {}

if "contagem_dia" not in st.session_state:
    st.session_state.contagem_dia = {}

if "ultimo_dia" not in st.session_state:
    st.session_state.ultimo_dia = date.today()

if "logs" not in st.session_state:
    st.session_state.logs = []


def log_evento(texto: str):
    hora = datetime.now().strftime("%H:%M:%S")
    st.session_state.logs.insert(0, f"[{hora}] {texto}")
    st.session_state.logs = st.session_state.logs[:100]


# ==========================================================
# ATIVOS
# ==========================================================
config_ativos = {}

if usar_win:
    config_ativos["WIN"] = simbolo_win

if usar_eurusd:
    config_ativos["EURUSD"] = simbolo_eurusd

if usar_usdjpy:
    config_ativos["USDJPY"] = simbolo_usdjpy

if usar_xauusd:
    config_ativos["XAUUSD"] = simbolo_xauusd


# ==========================================================
# BOTÕES
# ==========================================================
col1, col2 = st.columns(2)

with col1:
    if st.button("🟢 INICIAR ROBÔ", type="primary", use_container_width=True):
        st.session_state.rodando = True

        for ativo in config_ativos:
            st.session_state.ultimo_sinal.setdefault(ativo, "")
            st.session_state.operacoes.setdefault(ativo, None)
            st.session_state.contagem_dia.setdefault(ativo, 0)

        log_evento("Robô iniciado.")
        if telegram_token and telegram_chat_id:
            enviar_telegram(
                telegram_token,
                telegram_chat_id,
                f"🤖 *Robô iniciado*\nAtivos: {', '.join(config_ativos.keys())}\nModo: {modo_execucao}",
            )

with col2:
    if st.button("🔴 PARAR ROBÔ", use_container_width=True):
        st.session_state.rodando = False
        log_evento("Robô parado.")

        if telegram_token and telegram_chat_id:
            enviar_telegram(
                telegram_token,
                telegram_chat_id,
                "🛑 *Robô parado pelo usuário.*",
            )


# ==========================================================
# CONEXÃO
# ==========================================================
if st.session_state.rodando:
    if not MT5_LIB_OK:
        st.error(
            "A biblioteca MetaTrader5 não está instalada. "
            "Instale o requirements.txt e rode o app em Windows com o MT5 instalado."
        )
        st.session_state.rodando = False
        st.stop()

    ok, mensagem = conectar_mt5(mt5_login, mt5_senha, mt5_servidor)

    if not ok:
        st.error(mensagem)
        st.stop()

    st.success(mensagem)

    hoje = date.today()

    if hoje != st.session_state.ultimo_dia:
        st.session_state.ultimo_dia = hoje
        for ativo in config_ativos:
            st.session_state.contagem_dia[ativo] = 0
            st.session_state.ultimo_sinal[ativo] = ""
            st.session_state.operacoes[ativo] = None

        log_evento("Novo dia: contadores zerados.")


# ==========================================================
# MONITORAMENTO
# ==========================================================
if st.session_state.rodando:
    st.subheader("📊 Monitoramento")

    for ativo, candidatos in config_ativos.items():
        st.markdown(f"### {ativo}")

        simbolo = encontrar_simbolo(candidatos)

        if not simbolo:
            st.error(
                f"{ativo}: nenhum símbolo encontrado. "
                f"Confira o nome no Market Watch do MT5."
            )
            continue

        info = mt5.symbol_info(simbolo)

        if info is None:
            st.error(f"{ativo}: não foi possível obter informações de {simbolo}.")
            continue

        digits = int(info.digits)

        df = buscar_dados_mt5(simbolo, 150)

        if df is None:
            st.warning(f"{ativo}: sem dados suficientes para {simbolo}.")
            continue

        sinal, ult = verificar_sinal(
            df,
            rsi_compra=float(rsi_compra),
            rsi_venda=float(rsi_venda),
        )

        preco = float(ult["close"])
        horario_candle = ult["datetime"]

        # ==================================================
        # ACOMPANHAR OPERAÇÃO PAPER/REAL
        # ==================================================
        operacao = st.session_state.operacoes.get(ativo)

        if operacao:
            if operacao["tipo"] == "COMPRA":
                stop_bateu = preco <= operacao["stop"]
                alvo_bateu = preco >= operacao["alvo"]
            else:
                stop_bateu = preco >= operacao["stop"]
                alvo_bateu = preco <= operacao["alvo"]

            if stop_bateu or alvo_bateu:
                resultado = "STOP" if stop_bateu else "ALVO"

                texto = (
                    f"{'🛑' if stop_bateu else '✅'} {ativo} — "
                    f"{resultado} atingido | "
                    f"Entrada {operacao['entrada']:.{digits}f} | "
                    f"Preço {preco:.{digits}f}"
                )

                st.info(texto)
                log_evento(texto)

                if telegram_token and telegram_chat_id:
                    enviar_telegram(telegram_token, telegram_chat_id, texto)

                st.session_state.operacoes[ativo] = None

        # ==================================================
        # NOVO SINAL
        # ==================================================
        if (
            sinal
            and st.session_state.operacoes.get(ativo) is None
            and st.session_state.contagem_dia.get(ativo, 0) < max_sinais
        ):
            # Identificador baseado no candle fechado.
            sinal_id = f"{simbolo}-{sinal}-{horario_candle}"

            if sinal_id != st.session_state.ultimo_sinal.get(ativo):
                entrada = preco
                distancia = float(stop_dist)

                stop, alvo = calcular_niveis(
                    sinal,
                    entrada,
                    distancia,
                    float(rr),
                    digits,
                )

                volume = calcular_volume_por_risco(
                    simbolo,
                    entrada,
                    stop,
                    float(risco_reais),
                )

                operacao = {
                    "tipo": sinal,
                    "entrada": entrada,
                    "stop": stop,
                    "alvo": alvo,
                    "volume": volume,
                    "candle": str(horario_candle),
                }

                st.session_state.ultimo_sinal[ativo] = sinal_id
                st.session_state.operacoes[ativo] = operacao
                st.session_state.contagem_dia[ativo] += 1

                mensagem = (
                    f"{'🟢' if sinal == 'COMPRA' else '🔴'} *SINAL {sinal} — {ativo}*\n"
                    f"Símbolo: `{simbolo}`\n"
                    f"Entrada: `{entrada:.{digits}f}`\n"
                    f"Stop: `{stop:.{digits}f}`\n"
                    f"Alvo: `{alvo:.{digits}f}`\n"
                    f"R/R: `{rr}:1`\n"
                    f"Risco: `R$ {risco_reais:.2f}`\n"
                    f"Volume estimado: `{volume}`\n"
                    f"Candle fechado: `{horario_candle}`"
                )

                st.success(mensagem.replace("*", ""))

                log_evento(f"Sinal {sinal} em {ativo} ({simbolo}).")

                if telegram_token and telegram_chat_id:
                    enviar_telegram(telegram_token, telegram_chat_id, mensagem)

                # ==========================================
                # EXECUÇÃO REAL — EXPLICITAMENTE PROTEGIDA
                # ==========================================
                if (
                    modo_execucao.startswith("REAL")
                    and confirmar_real
                ):
                    if volume <= 0:
                        erro = (
                            f"{ativo}: volume calculado inválido. "
                            "Ordem REAL não enviada."
                        )
                        st.error(erro)
                        log_evento(erro)
                    else:
                        ok_ordem, retorno = enviar_ordem_mt5(
                            simbolo,
                            sinal,
                            volume,
                            entrada,
                            stop,
                            alvo,
                        )

                        if ok_ordem:
                            st.success(f"💰 {retorno}")
                            log_evento(retorno)
                        else:
                            st.error(retorno)
                            log_evento(retorno)

        # ==================================================
        # PAINEL
        # ==================================================
        c1, c2, c3, c4 = st.columns(4)

        with c1:
            st.metric("Preço", f"{preco:.{digits}f}")

        with c2:
            st.metric(
                "RSI",
                "—" if pd.isna(ult["rsi"]) else f"{ult['rsi']:.1f}",
            )

        with c3:
            st.metric(
                "Tendência",
                "ALTA" if ult["ema21"] > ult["ema50"] else "BAIXA",
            )

        with c4:
            st.metric(
                "Sinais hoje",
                f"{st.session_state.contagem_dia.get(ativo, 0)}/{max_sinais}",
            )

        op = st.session_state.operacoes.get(ativo)

        if op:
            st.info(
                f"📌 Operação {op['tipo']} | "
                f"Entrada: {op['entrada']:.{digits}f} | "
                f"Stop: {op['stop']:.{digits}f} | "
                f"Alvo: {op['alvo']:.{digits}f} | "
                f"Volume: {op['volume']}"
            )
        else:
            st.caption(
                f"Sem operação aberta • Último candle fechado: {horario_candle}"
            )

        st.divider()

    # Atualização automática sem bloquear o processo com time.sleep.
    # Compatível com versões recentes do Streamlit.
    time.sleep(1)
    st.rerun()


# ==========================================================
# PARADO
# ==========================================================
else:
    st.info("🔴 Robô parado. Configure os ativos e clique em INICIAR.")

st.subheader("📋 Log")
if st.session_state.logs:
    st.code("\n".join(st.session_state.logs[:30]))
else:
    st.caption("Nenhum evento ainda.")
