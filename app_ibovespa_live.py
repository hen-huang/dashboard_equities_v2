"""
Equity | Brazil — Ibovespa — dashboard calculado ao vivo
========================================================

Reconstrói a estrutura do relatório "Equity | Brazil — Ibovespa" SEM copiar
nenhum número: tudo é calculado na hora a partir de duas fontes reais.

FONTE 1 — Carteira e pesos: API pública oficial da B3
    (indexProxy/indexCall/GetPortfolioDay — a mesma que alimenta
     https://sistemaswebb3-listados.b3.com.br/indexPage/day/IBOV)
    Dá o universo de constituintes e o peso (%) de cada um no índice.

FONTE 2 — Preços: Yahoo Finance (yfinance), ajustados por proventos/splits.
    Todos os retornos (Day, MTD, 1M, 3M, 6M, 12M, YTD), contribuições,
    agregações por setor/indústria, tendências, spreads e razões relativas
    são CALCULADOS a partir dessas séries.

SOBRE OS SETORES
    O relatório original agrupa os papéis numa taxonomia própria de 4 setores
    (Commodities, Financials, Local Cyclicals, Utilities) e ~12 indústrias.
    Isso é uma REGRA DE CLASSIFICAÇÃO, não um dado de mercado — então está
    codificada abaixo em MAPA_INDUSTRIA / INDUSTRIA_PARA_SETOR. Qualquer
    ticker que apareça na carteira e não esteja no mapa é classificado
    automaticamente pelo setor/indústria que a própria Yahoo Finance reporta,
    traduzido para a taxonomia do relatório (ver `classificar_ticker`), e fica
    sinalizado na aba de diagnóstico para você revisar.

METODOLOGIA (igual às notas de rodapé do relatório, calculada aqui)
    - Setor/indústria = média dos constituintes ponderada pelo peso atual.
    - Contrib Day (bp) = peso × retorno do dia.
    - Contrib YTD (pp) = soma das contribuições mensais do ano
      (peso × retorno do mês). Como a API da B3 só publica a carteira do dia,
      o peso usado em cada mês é o peso atual (o relatório original usava o
      peso do fim do mês anterior) — está sinalizado no app.
    - Ibovespa = série real do ^BVSP (não é a soma das partes).

Rodar:
    pip install streamlit pandas numpy yfinance plotly requests
    streamlit run app_ibovespa_live.py
"""

import base64
import json
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="Equity | Brazil — Ibovespa (live)", layout="wide")

B3_URL = "https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/GetPortfolioDay"

CORES_SETOR = {
    "Commodities": "#29ABE2",
    "Financials": "#0B2545",
    "Local Cyclicals": "#8A9A5B",
    "Utilities": "#9E9E9E",
    "Outros": "#C9C9C9",
}

INDUSTRIA_PARA_SETOR = {
    "Oil & Gas": "Commodities",
    "Metals & Mining": "Commodities",
    "Pulp & Paper": "Commodities",
    "Meats & Agro": "Commodities",
    "Banking Services": "Financials",
    "Financial Services": "Financials",
    "Industrial & Logistics": "Local Cyclicals",
    "Consumer Goods & Services": "Local Cyclicals",
    "Health Care Services": "Local Cyclicals",
    "Homebuilding & Properties": "Local Cyclicals",
    "Telecom Services": "Local Cyclicals",
    "Eletric & Water Utilities": "Utilities",
    "Outros": "Outros",
}

# Regra de classificação (taxonomia do relatório), por raiz do ticker.
MAPA_INDUSTRIA = {
    # Commodities
    "PETR": "Oil & Gas", "PRIO": "Oil & Gas", "RECV": "Oil & Gas", "RRRP": "Oil & Gas",
    "VALE": "Metals & Mining", "GGBR": "Metals & Mining", "GOAU": "Metals & Mining",
    "CSNA": "Metals & Mining", "CMIN": "Metals & Mining", "USIM": "Metals & Mining",
    "BRAP": "Metals & Mining", "CBAV": "Metals & Mining", "AURA": "Metals & Mining",
    "SUZB": "Pulp & Paper", "KLBN": "Pulp & Paper", "DTEX": "Pulp & Paper",
    "MBRF": "Meats & Agro", "BRFS": "Meats & Agro", "BEEF": "Meats & Agro",
    "JBSS": "Meats & Agro", "MRFG": "Meats & Agro", "SLCE": "Meats & Agro",
    "SMTO": "Meats & Agro", "AGRO": "Meats & Agro", "TTEN": "Meats & Agro",
    "BRKM": "Metals & Mining", "UNIP": "Metals & Mining",
    # Financials
    "ITUB": "Banking Services", "BBDC": "Banking Services", "BBAS": "Banking Services",
    "BPAC": "Banking Services", "SANB": "Banking Services", "BPAN": "Banking Services",
    "ABCB": "Banking Services", "BRSR": "Banking Services", "BMGB": "Banking Services",
    "BIDI": "Banking Services", "INBR": "Banking Services",
    "B3SA": "Financial Services", "ITSA": "Financial Services", "BBSE": "Financial Services",
    "CXSE": "Financial Services", "PSSA": "Financial Services", "IRBR": "Financial Services",
    "WIZC": "Financial Services", "CIEL": "Financial Services",
    # Local Cyclicals
    "WEGE": "Industrial & Logistics", "EMBR": "Industrial & Logistics", "EMBJ": "Industrial & Logistics",
    "VBBR": "Industrial & Logistics", "UGPA": "Industrial & Logistics", "RENT": "Industrial & Logistics",
    "TOTS": "Industrial & Logistics", "RAIL": "Industrial & Logistics", "MOTV": "Industrial & Logistics",
    "CCRO": "Industrial & Logistics", "CSAN": "Industrial & Logistics", "POMO": "Industrial & Logistics",
    "VAMO": "Industrial & Logistics", "AZUL": "Industrial & Logistics", "GOLL": "Industrial & Logistics",
    "STBP": "Industrial & Logistics", "LOGN": "Industrial & Logistics", "PORT": "Industrial & Logistics",
    "ECOR": "Industrial & Logistics", "SIMH": "Industrial & Logistics", "LWSA": "Industrial & Logistics",
    "ABEV": "Consumer Goods & Services", "ASAI": "Consumer Goods & Services",
    "LREN": "Consumer Goods & Services", "SMFT": "Consumer Goods & Services",
    "NATU": "Consumer Goods & Services", "COGN": "Consumer Goods & Services",
    "VIVA": "Consumer Goods & Services", "YDUQ": "Consumer Goods & Services",
    "MGLU": "Consumer Goods & Services", "CEAB": "Consumer Goods & Services",
    "AZZA": "Consumer Goods & Services", "ARZZ": "Consumer Goods & Services",
    "SOMA": "Consumer Goods & Services", "PCAR": "Consumer Goods & Services",
    "CRFB": "Consumer Goods & Services", "AMER": "Consumer Goods & Services",
    "PETZ": "Consumer Goods & Services", "ALPA": "Consumer Goods & Services",
    "GRND": "Consumer Goods & Services", "VULC": "Consumer Goods & Services",
    "GMAT": "Consumer Goods & Services", "MDIA": "Consumer Goods & Services",
    "CAML": "Consumer Goods & Services", "ANIM": "Consumer Goods & Services",
    "SEER": "Consumer Goods & Services", "CVCB": "Consumer Goods & Services",
    "MOVI": "Consumer Goods & Services", "ENJU": "Consumer Goods & Services",
    "RDOR": "Health Care Services", "RADL": "Health Care Services", "FLRY": "Health Care Services",
    "HYPE": "Health Care Services", "HAPV": "Health Care Services", "QUAL": "Health Care Services",
    "ONCO": "Health Care Services", "DASA": "Health Care Services", "PNVL": "Health Care Services",
    "ALOS": "Homebuilding & Properties", "MULT": "Homebuilding & Properties",
    "CYRE": "Homebuilding & Properties", "CURY": "Homebuilding & Properties",
    "IGTI": "Homebuilding & Properties", "DIRR": "Homebuilding & Properties",
    "MRVE": "Homebuilding & Properties", "EZTC": "Homebuilding & Properties",
    "TEND": "Homebuilding & Properties", "JHSF": "Homebuilding & Properties",
    "LAVV": "Homebuilding & Properties", "PLPL": "Homebuilding & Properties",
    "TRIS": "Homebuilding & Properties", "SYNE": "Homebuilding & Properties",
    "VIVT": "Telecom Services", "TIMS": "Telecom Services", "OIBR": "Telecom Services",
    "DESK": "Telecom Services", "FIQE": "Telecom Services",
    # Utilities
    "AXIA": "Eletric & Water Utilities", "SBSP": "Eletric & Water Utilities",
    "ENEV": "Eletric & Water Utilities", "EQTL": "Eletric & Water Utilities",
    "CPLE": "Eletric & Water Utilities", "CMIG": "Eletric & Water Utilities",
    "CSMG": "Eletric & Water Utilities", "ENGI": "Eletric & Water Utilities",
    "EGIE": "Eletric & Water Utilities", "ISAE": "Eletric & Water Utilities",
    "TAEE": "Eletric & Water Utilities", "CPFE": "Eletric & Water Utilities",
    "BRAV": "Eletric & Water Utilities", "AURE": "Eletric & Water Utilities",
    "ELET": "Eletric & Water Utilities", "SAPR": "Eletric & Water Utilities",
    "CLSC": "Eletric & Water Utilities", "NEOE": "Eletric & Water Utilities",
    "ALUP": "Eletric & Water Utilities", "SRNA": "Eletric & Water Utilities",
    "AMBP": "Eletric & Water Utilities", "ORVR": "Eletric & Water Utilities",
    "CEGR": "Eletric & Water Utilities", "GEPA": "Eletric & Water Utilities",
    "LIGT": "Eletric & Water Utilities", "COCE": "Eletric & Water Utilities",
    "EKTR": "Eletric & Water Utilities", "REDE": "Eletric & Water Utilities",
}

# Fallback: setor da Yahoo Finance -> indústria da taxonomia do relatório.
YAHOO_PARA_INDUSTRIA = {
    "Energy": "Oil & Gas",
    "Basic Materials": "Metals & Mining",
    "Financial Services": "Financial Services",
    "Utilities": "Eletric & Water Utilities",
    "Healthcare": "Health Care Services",
    "Real Estate": "Homebuilding & Properties",
    "Communication Services": "Telecom Services",
    "Industrials": "Industrial & Logistics",
    "Technology": "Industrial & Logistics",
    "Consumer Cyclical": "Consumer Goods & Services",
    "Consumer Defensive": "Consumer Goods & Services",
}


def raiz_ticker(ticker: str) -> str:
    """Raiz de 4 caracteres do ticker B3: PETR4->PETR, KLBN11->KLBN,
    B3SA3->B3SA (o dígito do meio faz parte do nome, não pode ser removido)."""
    return ticker.strip().upper()[:4]


# ======================================================================
# FONTE 1 — carteira e pesos oficiais da B3
# ======================================================================

@st.cache_data(ttl=3600, show_spinner="Buscando a carteira oficial na B3...")
def carregar_carteira_b3(indice: str = "IBOV"):
    payload = {"language": "pt-br", "pageNumber": 1, "pageSize": 1000,
               "index": indice, "segment": "1"}
    url = f"{B3_URL}/{base64.b64encode(json.dumps(payload).encode()).decode()}"
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        "Referer": f"https://sistemaswebb3-listados.b3.com.br/indexPage/day/{indice}?language=pt-br",
    }
    r = requests.get(url, headers=headers, timeout=25)
    r.raise_for_status()
    dados = r.json()

    df = pd.DataFrame(dados["results"]).rename(
        columns={"cod": "ticker", "asset": "empresa", "type": "especie", "part": "peso_pct"}
    )
    df["peso_pct"] = df["peso_pct"].astype(str).str.replace(".", "", regex=False) \
                                    .str.replace(",", ".", regex=False).astype(float)
    df = df[["ticker", "empresa", "especie", "peso_pct"]]
    return df.sort_values("peso_pct", ascending=False).reset_index(drop=True), dados["header"]


# ======================================================================
# FONTE 2 — preços reais (Yahoo Finance)
# ======================================================================

@st.cache_data(ttl=1800, show_spinner="Baixando preços no Yahoo Finance...")
def baixar_precos(tickers, anos=3):
    tickers = list(dict.fromkeys(tickers))
    inicio = (pd.Timestamp.today() - pd.DateOffset(years=anos)).strftime("%Y-%m-%d")
    dados = yf.download(tickers, start=inicio, auto_adjust=True, progress=False)
    close = dados["Close"] if "Close" in dados else pd.DataFrame()
    if isinstance(close, pd.Series):
        close = close.to_frame(tickers[0])
    return close.dropna(how="all")


@st.cache_data(ttl=86400, show_spinner="Consultando classificação setorial (Yahoo)...")
def setores_yahoo(tickers):
    """Só é chamado para tickers que não estão no mapa da taxonomia."""
    out = {}
    for tk in tickers:
        try:
            out[tk] = yf.Ticker(tk).info.get("sector") or ""
        except Exception:
            out[tk] = ""
    return out


def classificar_ticker(ticker_b3: str, setor_yahoo: str = ""):
    """Devolve (industria, setor, origem_da_classificacao)."""
    ind = MAPA_INDUSTRIA.get(raiz_ticker(ticker_b3))
    if ind:
        return ind, INDUSTRIA_PARA_SETOR[ind], "mapa"
    ind = YAHOO_PARA_INDUSTRIA.get(setor_yahoo)
    if ind:
        return ind, INDUSTRIA_PARA_SETOR[ind], f"yahoo ({setor_yahoo})"
    return "Outros", "Outros", "não classificado"


# ======================================================================
# Cálculo de retornos (tudo derivado das séries reais)
# ======================================================================

def retornos_janelas(precos: pd.Series) -> dict:
    p = precos.dropna()
    vazio = {k: np.nan for k in ["day", "mtd", "m1", "m3", "m6", "m12", "ytd"]}
    if len(p) < 2:
        return vazio

    ultimo, hoje = p.iloc[-1], p.index[-1]

    def desde(data):
        ant = p[p.index <= data]
        return (ultimo / ant.iloc[-1] - 1) * 100 if not ant.empty else np.nan

    fim_mes_ant = hoje.replace(day=1) - pd.Timedelta(days=1)
    fim_ano_ant = pd.Timestamp(year=hoje.year, month=1, day=1) - pd.Timedelta(days=1)

    return {
        "day": (ultimo / p.iloc[-2] - 1) * 100,
        "mtd": desde(fim_mes_ant),
        "m1": desde(hoje - pd.DateOffset(months=1)),
        "m3": desde(hoje - pd.DateOffset(months=3)),
        "m6": desde(hoje - pd.DateOffset(months=6)),
        "m12": desde(hoje - pd.DateOffset(years=1)),
        "ytd": desde(fim_ano_ant),
    }


def contribuicoes_mensais(precos: pd.DataFrame, pesos: pd.Series, meses=24) -> pd.DataFrame:
    """Retorno mensal de cada ativo × peso atual = contribuição mensal (pp)."""
    mensal = precos.resample("ME").last().pct_change() * 100
    mensal = mensal.tail(meses)
    tks = [t for t in pesos.index if t in mensal.columns]
    return mensal[tks].mul(pesos.loc[tks] / 100.0, axis=1)


def cesta_base100(precos: pd.DataFrame, pesos: pd.Series) -> pd.Series:
    tks = [t for t in pesos.index if t in precos.columns]
    if not tks:
        return pd.Series(dtype=float)
    p = pesos.loc[tks] / pesos.loc[tks].sum()
    ret = precos[tks].pct_change().fillna(0.0)
    return (1 + (ret * p).sum(axis=1)).cumprod() * 100


def razao_base100(num: pd.Series, den: pd.Series) -> pd.Series:
    df = pd.concat([num, den], axis=1, join="inner").dropna()
    if df.empty:
        return pd.Series(dtype=float)
    r = df.iloc[:, 0] / df.iloc[:, 1]
    return r / r.iloc[0] * 100


def spread_vol_neutro(num: pd.Series, den: pd.Series, janela=252):
    df = pd.concat([num.pct_change().rename("n"), den.pct_change().rename("d")], axis=1).dropna()
    if len(df) < janela + 2:
        return pd.Series(dtype=float), np.nan
    h = (df["n"].rolling(janela).std() / df["d"].rolling(janela).std()).shift(1)
    spread = (df["n"] - h * df["d"]).dropna()
    if spread.empty:
        return pd.Series(dtype=float), np.nan
    h_atual = h.dropna().iloc[-1] if not h.dropna().empty else np.nan
    return (1 + spread).cumprod() * 100, h_atual


def tendencia_bandas(precos: pd.Series, janela=252):
    p = precos.dropna().iloc[-janela:]
    if len(p) < 10:
        return None, None, None, np.nan
    x = np.arange(len(p))
    tend = np.polyval(np.polyfit(x, p.values, 1), x)
    sigma = (p.values - tend).std()
    dist = (p.iloc[-1] - tend[-1]) / sigma if sigma else np.nan
    return pd.Series(tend, index=p.index), sigma, p, dist


def agregar(base: pd.DataFrame, chave: str) -> pd.DataFrame:
    """Setor/indústria = média dos constituintes ponderada pelo peso atual."""
    cols_ret = ["day", "mtd", "m1", "m3", "m6", "m12", "ytd"]
    linhas = []
    for nome, g in base.groupby(chave):
        peso_total = g["peso_pct"].sum()
        linha = {chave: nome, "peso_pct": peso_total}
        for c in cols_ret:
            validos = g.dropna(subset=[c])
            linha[c] = (np.average(validos[c], weights=validos["peso_pct"])
                        if not validos.empty and validos["peso_pct"].sum() > 0 else np.nan)
        linha["ctb_day_bp"] = g["ctb_day_bp"].sum()
        linha["ctb_ytd_pp"] = g["ctb_ytd_pp"].sum()
        linhas.append(linha)
    return pd.DataFrame(linhas).sort_values("peso_pct", ascending=False).reset_index(drop=True)


def formata(df, pct_cols, extra=None):
    fmt = {c: "{:+.1f}%" for c in pct_cols}
    fmt.update(extra or {})

    def cor(v):
        if not isinstance(v, (int, float, np.floating)) or pd.isna(v):
            return ""
        return "color:#C0392B" if v < 0 else ("color:#1E7B34" if v > 0 else "")

    sty = df.style.format(fmt, na_rep="–")
    alvo = [c for c in pct_cols + list((extra or {}).keys()) if c in df.columns]
    return sty.map(cor, subset=alvo) if hasattr(sty, "map") else sty.applymap(cor, subset=alvo)


# ======================================================================
# APP
# ======================================================================

st.title("Equity | Brazil — Ibovespa")
st.caption("Tudo calculado ao vivo: pesos oficiais da B3 + preços reais do Yahoo Finance. "
           "Nenhum número foi copiado de relatório.")

with st.sidebar:
    st.header("Parâmetros")
    indice = st.selectbox("Índice (carteira oficial B3)", ["IBOV", "IBXX", "IBXL", "IBRA", "SMLL", "IDIV"])
    anos_hist = st.slider("Histórico baixado (anos)", 1, 8, 3)
    meses_contrib = st.slider("Meses no gráfico de contribuição", 6, 36, 24)
    st.caption("Trocar de índice ou de janela refaz todos os cálculos.")

try:
    carteira, header_b3 = carregar_carteira_b3(indice)
except Exception as e:
    st.error(f"Não foi possível obter a carteira oficial da B3: {e}")
    st.stop()

carteira["ticker_yahoo"] = carteira["ticker"] + ".SA"
tickers_yahoo = carteira["ticker_yahoo"].tolist()

REFS = {"IBOV": "^BVSP", "SMAL11": "SMAL11.SA", "EWZ": "EWZ", "EEM": "EEM", "SPY": "SPY"}

try:
    precos = baixar_precos(tickers_yahoo + list(REFS.values()), anos=anos_hist)
except Exception as e:
    st.error(f"Falha ao baixar preços do Yahoo Finance: {e}")
    st.stop()

if precos.empty or REFS["IBOV"] not in precos.columns or precos[REFS["IBOV"]].dropna().empty:
    st.error("Yahoo Finance não retornou dados agora (conexão, limite de taxa ou ticker fora do ar). "
             "Tente novamente em alguns minutos.")
    st.stop()

# ---- classificação setorial ----
sem_mapa = [r.ticker_yahoo for r in carteira.itertuples()
            if raiz_ticker(r.ticker) not in MAPA_INDUSTRIA]
setores_fallback = setores_yahoo(sem_mapa) if sem_mapa else {}

classif = [classificar_ticker(r.ticker, setores_fallback.get(r.ticker_yahoo, ""))
           for r in carteira.itertuples()]
carteira["industria"] = [c[0] for c in classif]
carteira["setor"] = [c[1] for c in classif]
carteira["origem_classif"] = [c[2] for c in classif]

# ---- retornos por ativo (calculados das séries reais) ----
linhas = []
for r in carteira.itertuples():
    if r.ticker_yahoo not in precos.columns:
        continue
    serie = precos[r.ticker_yahoo].dropna()
    if serie.empty:
        continue
    ret = retornos_janelas(serie)
    linhas.append({
        "ticker": r.ticker, "empresa": r.empresa, "setor": r.setor, "industria": r.industria,
        "peso_pct": r.peso_pct, "preco": serie.iloc[-1], **ret,
    })

base = pd.DataFrame(linhas)
if base.empty:
    st.error("Nenhum ativo da carteira retornou preço no Yahoo Finance.")
    st.stop()

base["ctb_day_bp"] = base["peso_pct"] / 100 * base["day"] * 100  # pp -> bp
base["ctb_ytd_pp"] = base["peso_pct"] / 100 * base["ytd"]

precos_ativos = precos[[c for c in tickers_yahoo if c in precos.columns]]
pesos_all = base.set_index(base["ticker"] + ".SA")["peso_pct"]

ibov = precos[REFS["IBOV"]].dropna()
ret_ibov = retornos_janelas(ibov)
data_precos = precos.index[-1].strftime("%d/%m/%Y")

st.caption(
    f"Índice **{indice}** · carteira B3 de **{header_b3.get('date', 'n/d')}** · "
    f"preços Yahoo até **{data_precos}** · **{len(base)}** ativos com série válida "
    f"(de {len(carteira)} na carteira)"
)

t_snap, t_contrib, t_ativos, t_scatter, t_series, t_diag = st.tabs([
    "📊 Snapshot", "📈 Contribuição YTD", "🏢 Ativos", "🔀 1M vs 12M",
    "📉 Séries & Relativos", "🔍 Diagnóstico",
])

COLS_RET = ["day", "mtd", "m1", "m3", "m6", "m12", "ytd"]
ROTULOS = {"peso_pct": "Weight", "day": "Day", "mtd": "MTD", "m1": "1M", "m3": "3M",
           "m6": "6M", "m12": "12M", "ytd": "YTD", "ctb_day_bp": "Contrib Day (bp)",
           "ctb_ytd_pp": "Contrib YTD (pp)", "preco": "Price"}

# ------------------------------------------------------------ Snapshot
with t_snap:
    st.subheader("Market Snapshot — índice, setores e indústrias")

    por_setor = agregar(base, "setor").rename(columns={"setor": "nome"})
    por_ind = agregar(base, "industria").rename(columns={"industria": "nome"})

    linha_indice = {"nome": indice, "peso_pct": base["peso_pct"].sum(),
                    **{c: ret_ibov[c] for c in COLS_RET},
                    "ctb_day_bp": base["ctb_day_bp"].sum(),
                    "ctb_ytd_pp": base["ctb_ytd_pp"].sum()}

    blocos = [pd.DataFrame([linha_indice])]
    for _, s in por_setor.iterrows():
        blocos.append(pd.DataFrame([s]))
        filhas = por_ind[por_ind["nome"].map(INDUSTRIA_PARA_SETOR) == s["nome"]]
        if not filhas.empty:
            blocos.append(filhas.assign(nome="   " + filhas["nome"]))
    snap = pd.concat(blocos, ignore_index=True)

    st.dataframe(
        formata(snap.set_index("nome")[["peso_pct"] + COLS_RET + ["ctb_day_bp", "ctb_ytd_pp"]]
                    .rename(columns=ROTULOS),
                [ROTULOS[c] for c in COLS_RET] + ["Contrib YTD (pp)"],
                {"Weight": "{:.1f}%", "Contrib Day (bp)": "{:+.0f}"}),
        use_container_width=True,
    )
    st.caption("Linha do índice = retorno real do ^BVSP. Setor/indústria = média dos "
               "constituintes ponderada pelo peso atual. Contrib Day = peso × retorno do dia.")

# ------------------------------------------------------- Contribuição
with t_contrib:
    st.subheader("Contribuição YTD por setor e indústria")
    c1, c2 = st.columns(2)

    s = agregar(base, "setor").sort_values("ctb_ytd_pp")
    f1 = px.bar(s, x="ctb_ytd_pp", y="setor", orientation="h", color="setor",
                color_discrete_map=CORES_SETOR, labels={"ctb_ytd_pp": "pp", "setor": ""},
                title="Por setor (pp)")
    f1.update_layout(showlegend=False)
    c1.plotly_chart(f1, use_container_width=True)

    i = agregar(base, "industria").sort_values("ctb_ytd_pp")
    i["setor"] = i["industria"].map(INDUSTRIA_PARA_SETOR)
    f2 = px.bar(i, x="ctb_ytd_pp", y="industria", orientation="h", color="setor",
                color_discrete_map=CORES_SETOR, labels={"ctb_ytd_pp": "pp", "industria": ""},
                title="Por indústria (pp)")
    c2.plotly_chart(f2, use_container_width=True)

    st.markdown("#### Contribuição mensal por setor")
    contrib_m = contribuicoes_mensais(precos_ativos, pesos_all, meses=meses_contrib)
    if not contrib_m.empty:
        mapa_setor = base.set_index(base["ticker"] + ".SA")["setor"]
        por_mes = contrib_m.T.groupby(mapa_setor).sum().T
        fig = go.Figure()
        for setor in por_mes.columns:
            fig.add_bar(name=setor, x=por_mes.index.strftime("%b/%y"), y=por_mes[setor],
                        marker_color=CORES_SETOR.get(setor))
        ret_ibov_m = (ibov.resample("ME").last().pct_change() * 100).tail(len(por_mes))
        fig.add_trace(go.Scatter(x=por_mes.index.strftime("%b/%y"), y=ret_ibov_m.values,
                                 mode="markers", name=f"{indice} (real)",
                                 marker=dict(color="black", size=7)))
        fig.update_layout(barmode="relative", height=430, yaxis_title="pp")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Contribuição = peso atual × retorno mensal do ativo, somado por setor. "
                   "Os pontos pretos são o retorno mensal real do índice — a diferença para a "
                   "soma das barras vem do peso fixo (a B3 só publica a carteira do dia).")

# --------------------------------------------------------------- Ativos
with t_ativos:
    st.subheader("Ativos por setor")
    setores_disp = sorted(base["setor"].unique())
    escolha = st.radio("Setor", setores_disp, horizontal=True)
    sub = base[base["setor"] == escolha].sort_values(["industria", "peso_pct"],
                                                      ascending=[True, False])
    st.dataframe(
        formata(sub.set_index("ticker")[["empresa", "industria", "peso_pct", "preco"] +
                                        COLS_RET + ["ctb_day_bp", "ctb_ytd_pp"]]
                   .rename(columns=ROTULOS),
                [ROTULOS[c] for c in COLS_RET] + ["Contrib YTD (pp)"],
                {"Weight": "{:.2f}%", "Price": "R$ {:.2f}", "Contrib Day (bp)": "{:+.0f}"}),
        use_container_width=True, height=600,
    )

# -------------------------------------------------------------- Scatter
with t_scatter:
    st.subheader("Retorno 1M vs 12M por ativo")
    plot = base.dropna(subset=["m1", "m12"])
    fig = px.scatter(plot, x="m12", y="m1", color="setor", size="peso_pct",
                     color_discrete_map=CORES_SETOR, hover_name="ticker",
                     hover_data={"empresa": True, "industria": True, "peso_pct": ":.2f"},
                     labels={"m12": "Retorno 12M (%)", "m1": "Retorno 1M (%)"})
    if not np.isnan(ret_ibov["m1"]):
        fig.add_hline(y=ret_ibov["m1"], line_dash="dash", line_color="grey",
                      annotation_text=f"{indice} 1M {ret_ibov['m1']:+.1f}%")
    if not np.isnan(ret_ibov["m12"]):
        fig.add_vline(x=ret_ibov["m12"], line_dash="dash", line_color="grey",
                      annotation_text=f"{indice} 12M {ret_ibov['m12']:+.1f}%")
    fig.add_hline(y=0, line_color="black", line_width=0.8)
    fig.add_vline(x=0, line_color="black", line_width=0.8)
    fig.update_layout(height=620)
    st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------- Séries e relativos
with t_series:
    st.subheader("Tendência 12M e bandas ±2σ")
    c1, c2 = st.columns(2)
    for col, tk, nome in [(c1, REFS["IBOV"], indice), (c2, REFS["SMAL11"], "SMAL11 · Small Caps")]:
        if tk not in precos.columns:
            col.info(f"{nome}: sem dado.")
            continue
        tend, sigma, p, dist = tendencia_bandas(precos[tk])
        if tend is None:
            col.info(f"{nome}: histórico insuficiente.")
            continue
        f = go.Figure()
        f.add_trace(go.Scatter(x=p.index, y=p.values, name=nome, line_color="#1f77b4"))
        f.add_trace(go.Scatter(x=tend.index, y=tend.values, name="tendência",
                               line_dash="dash", line_color="black"))
        f.add_trace(go.Scatter(x=tend.index, y=tend.values + 2 * sigma,
                               line_color="rgba(0,0,0,0)", showlegend=False))
        f.add_trace(go.Scatter(x=tend.index, y=tend.values - 2 * sigma, fill="tonexty",
                               fillcolor="rgba(150,150,150,.25)", line_color="rgba(0,0,0,0)",
                               showlegend=False))
        f.update_layout(title=f"{nome}  {p.iloc[-1]:,.0f}  ({dist:+.1f}σ)", height=360)
        col.plotly_chart(f, use_container_width=True)

    st.subheader("Performance relativa (base 100 no início da janela)")
    maiores = base.nlargest(3, "peso_pct")["ticker"].tolist()
    pares = [(f"{indice} / SMAL11", REFS["IBOV"], REFS["SMAL11"]),
             ("EWZ / EEM", REFS["EWZ"], REFS["EEM"]),
             ("EWZ / SPY", REFS["EWZ"], REFS["SPY"])]
    pares += [(f"{t} / {indice}", f"{t}.SA", REFS["IBOV"]) for t in maiores]

    cols = st.columns(3)
    for k, (titulo, a, b) in enumerate(pares):
        if a not in precos.columns or b not in precos.columns:
            cols[k % 3].info(f"{titulo}: sem dado.")
            continue
        r = razao_base100(precos[a], precos[b])
        if r.empty:
            cols[k % 3].info(f"{titulo}: sem dado.")
            continue
        f = px.line(r, title=f"{titulo}  {r.iloc[-1]:.1f}")
        f.update_layout(showlegend=False, height=290, xaxis_title=None, yaxis_title=None)
        cols[k % 3].plotly_chart(f, use_container_width=True)

    st.subheader("Setores vs índice (cestas ponderadas pelo peso atual)")
    cols = st.columns(4)
    mapa_setor = base.set_index(base["ticker"] + ".SA")["setor"]
    for k, setor in enumerate(sorted(base["setor"].unique())):
        pesos_s = pesos_all[mapa_setor == setor]
        cesta = cesta_base100(precos_ativos, pesos_s)
        if cesta.empty:
            continue
        r = razao_base100(cesta, ibov)
        if r.empty:
            continue
        f = px.line(r, title=f"{setor} / {indice}  {r.iloc[-1]:.1f}",
                    color_discrete_sequence=[CORES_SETOR.get(setor, "#333")])
        f.update_layout(showlegend=False, height=270, xaxis_title=None, yaxis_title=None)
        cols[k % 4].plotly_chart(f, use_container_width=True)

    with st.expander("Indústrias vs índice"):
        cols = st.columns(4)
        mapa_ind = base.set_index(base["ticker"] + ".SA")["industria"]
        for k, ind in enumerate(sorted(base["industria"].unique())):
            cesta = cesta_base100(precos_ativos, pesos_all[mapa_ind == ind])
            if cesta.empty:
                continue
            r = razao_base100(cesta, ibov)
            if r.empty:
                continue
            f = px.line(r, title=f"{ind}  {r.iloc[-1]:.1f}",
                        color_discrete_sequence=[CORES_SETOR.get(INDUSTRIA_PARA_SETOR.get(ind), "#333")])
            f.update_layout(showlegend=False, height=250, xaxis_title=None, yaxis_title=None)
            cols[k % 4].plotly_chart(f, use_container_width=True)

    st.subheader("Spreads vol-neutro (hedge de vol rolante, 252 sessões)")
    cols = st.columns(3)
    for k, (titulo, a, b) in enumerate(pares):
        if a not in precos.columns or b not in precos.columns:
            continue
        idx, h = spread_vol_neutro(precos[a], precos[b])
        if idx.empty:
            cols[k % 3].info(f"{titulo}: histórico < 252 sessões.")
            continue
        f = px.line(idx, title=f"{titulo}  {idx.iloc[-1]:.1f} (h {h:.2f})")
        f.update_layout(showlegend=False, height=280, xaxis_title=None, yaxis_title=None)
        cols[k % 3].plotly_chart(f, use_container_width=True)

# ---------------------------------------------------------- Diagnóstico
with t_diag:
    st.subheader("Classificação setorial de cada ativo")
    st.caption("A taxonomia (Commodities / Financials / Local Cyclicals / Utilities) é uma regra "
               "de classificação, não um dado de mercado. Confira aqui como cada papel foi "
               "enquadrado e de onde veio o enquadramento.")
    diag = carteira[["ticker", "empresa", "peso_pct", "industria", "setor", "origem_classif"]]
    st.dataframe(diag, use_container_width=True, height=420)

    nao_class = diag[diag["setor"] == "Outros"]
    if not nao_class.empty:
        st.warning(f"{len(nao_class)} ativo(s) sem enquadramento na taxonomia "
                   f"({nao_class['peso_pct'].sum():.2f}% do índice) — caíram em 'Outros'. "
                   "Adicione a raiz do ticker em MAPA_INDUSTRIA para classificá-los.")
        st.dataframe(nao_class, use_container_width=True)

    faltando = set(carteira["ticker_yahoo"]) - set(precos.columns)
    if faltando:
        st.warning(f"{len(faltando)} ticker(s) da carteira sem preço no Yahoo Finance: "
                   + ", ".join(sorted(faltando)))

    st.markdown("**Metodologia**")
    st.markdown(
        f"""
- **Pesos**: API pública oficial da B3 (`GetPortfolioDay`), carteira de {header_b3.get('date', 'n/d')}.
- **Preços**: Yahoo Finance, ajustados por proventos e splits, até {data_precos}.
- **Retornos**: calculados das séries (Day = último vs penúltimo pregão; MTD e YTD vs
  fechamento do último dia do período anterior; 1M/3M/6M/12M por data-calendário).
- **Setor/indústria**: média dos constituintes ponderada pelo peso atual.
- **Contrib Day (bp)** = peso × retorno do dia. **Contrib YTD (pp)** = peso × retorno YTD.
- **Limitação conhecida**: a B3 publica apenas a carteira do dia, então nas séries históricas
  (contribuição mensal, cestas setoriais) o peso de cada ativo é mantido fixo no valor atual.
  Um relatório de mesa rebalancearia mensalmente com o peso do fim do mês anterior.
        """
    )
