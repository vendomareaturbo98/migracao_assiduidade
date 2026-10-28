"""Cálculos reutilizáveis do painel de assiduidade.

As funções deste módulo não dependem do Streamlit nem do banco. Isso mantém
os indicadores consistentes e permite validá-los com dados fictícios.
"""
from __future__ import annotations

from datetime import date

import pandas as pd


SITUACOES = ["Agendado", "Realizado", "Cancelado", "Remarcado"]
RESULTADOS = ["Presente", "Ausente", "Pendente", "Cancelado"]


def classificar_resultados(registros: pd.DataFrame, referencia: date | None = None) -> pd.DataFrame:
    """Classifica cada elegibilidade pelo resultado que deve aparecer no painel."""
    dados = registros.copy()
    if dados.empty:
        dados["resultado"] = pd.Series(dtype="object")
        return dados

    referencia = referencia or date.today()
    dados["data"] = pd.to_datetime(dados["data"], errors="coerce")
    dados["resultado"] = "Pendente"
    dados.loc[dados["situacao"] == "Cancelado", "resultado"] = "Cancelado"

    realizado = (
        dados["situacao"].eq("Realizado")
        & dados["data"].notna()
        & dados["data"].dt.date.le(referencia)
    )
    dados.loc[realizado & dados["presente"].eq(1), "resultado"] = "Presente"
    dados.loc[
        realizado & (dados["presente"].isna() | dados["presente"].eq(0)),
        "resultado",
    ] = "Ausente"
    return dados


def aplicar_filtros(
    dados: pd.DataFrame,
    data_inicial: date,
    data_final: date,
    cargos: list[str] | None = None,
    situacoes: list[str] | None = None,
) -> pd.DataFrame:
    """Aplica os filtros do painel sem mutar a consulta original."""
    filtrados = dados.copy()
    if filtrados.empty:
        return filtrados
    filtrados["data"] = pd.to_datetime(filtrados["data"], errors="coerce")
    periodo = filtrados["data"].dt.date.between(data_inicial, data_final)
    filtrados = filtrados.loc[periodo].copy()
    if cargos:
        filtrados = filtrados[filtrados["cargo"].fillna("").isin(cargos)].copy()
    if situacoes:
        filtrados = filtrados[filtrados["situacao"].isin(situacoes)].copy()
    return filtrados


def calcular_metricas(
    colaboradores: pd.DataFrame,
    treinamentos: pd.DataFrame,
    participacoes: pd.DataFrame,
    cargos: list[str] | None = None,
) -> dict[str, float | int]:
    """Gera os indicadores principais, protegendo contra divisão por zero."""
    ativos = colaboradores.copy()
    if cargos:
        ativos = ativos[ativos["cargo"].fillna("").isin(cargos)]

    realizados = treinamentos[treinamentos["situacao"] == "Realizado"]
    presencas = int(participacoes["resultado"].eq("Presente").sum())
    ausencias = int(participacoes["resultado"].eq("Ausente").sum())
    concluidos = presencas + ausencias
    taxa = round((presencas / concluidos) * 100, 1) if concluidos else 0.0
    return {
        "colaboradores_ativos": int(len(ativos)),
        "treinamentos": int(len(treinamentos)),
        "treinamentos_realizados": int(len(realizados)),
        "presencas": presencas,
        "ausencias": ausencias,
        "pendencias": int(participacoes["resultado"].eq("Pendente").sum()),
        "taxa_presenca": taxa,
    }


def resumo_por_cargo(participacoes: pd.DataFrame) -> pd.DataFrame:
    """Resume presença e ausência por cargo para um gráfico comparativo."""
    if participacoes.empty:
        return pd.DataFrame(columns=["cargo", "resultado", "quantidade"])
    base = participacoes[participacoes["resultado"].isin(["Presente", "Ausente"])]
    if base.empty:
        return pd.DataFrame(columns=["cargo", "resultado", "quantidade"])
    return (
        base.groupby(["cargo", "resultado"], dropna=False)
        .size()
        .rename("quantidade")
        .reset_index()
        .sort_values(["cargo", "resultado"])
    )


def evolucao_mensal(participacoes: pd.DataFrame) -> pd.DataFrame:
    """Calcula a taxa de presença mensal para os treinamentos concluídos."""
    if participacoes.empty:
        return pd.DataFrame(columns=["mes", "taxa_presenca", "participacoes"])
    base = participacoes[participacoes["resultado"].isin(["Presente", "Ausente"])].copy()
    if base.empty:
        return pd.DataFrame(columns=["mes", "taxa_presenca", "participacoes"])
    base["mes"] = pd.to_datetime(base["data"]).dt.to_period("M").astype(str)
    tabela = base.groupby("mes").agg(
        presencas=("resultado", lambda serie: int(serie.eq("Presente").sum())),
        participacoes=("resultado", "size"),
    )
    tabela["taxa_presenca"] = (tabela["presencas"] / tabela["participacoes"] * 100).round(1)
    return tabela.reset_index()[["mes", "taxa_presenca", "participacoes"]]


def desempenho_por_treinamento(participacoes: pd.DataFrame) -> pd.DataFrame:
    """Retorna uma visão comparável por treinamento concluído."""
    if participacoes.empty:
        return pd.DataFrame(columns=["treinamento", "data", "presentes", "ausentes", "taxa_presenca"])
    base = participacoes[participacoes["resultado"].isin(["Presente", "Ausente"])].copy()
    if base.empty:
        return pd.DataFrame(columns=["treinamento", "data", "presentes", "ausentes", "taxa_presenca"])
    tabela = base.groupby(["treinamento", "data"], as_index=False).agg(
        presentes=("resultado", lambda serie: int(serie.eq("Presente").sum())),
        ausentes=("resultado", lambda serie: int(serie.eq("Ausente").sum())),
    )
    total = tabela["presentes"] + tabela["ausentes"]
    tabela["taxa_presenca"] = (tabela["presentes"] / total * 100).round(1)
    return tabela.sort_values(["data", "treinamento"], ascending=[False, True])
