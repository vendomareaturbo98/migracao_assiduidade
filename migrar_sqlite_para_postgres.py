"""Migra dados de dados/assiduidade.db para um PostgreSQL vazio, preservando IDs."""
from __future__ import annotations

import argparse
import getpass
import os
import sqlite3
import sys
from pathlib import Path

import psycopg2

from db_postgres import conectar, inicializar_banco, obter_database_url

TABELAS = {
    "colaboradores": ["id", "nome", "nome_chave", "matricula", "cargo", "ativo", "criado_em"],
    "treinamentos": ["id", "titulo", "data", "hora_inicio", "hora_fim", "carga_horaria", "publico", "situacao", "observacoes", "criado_em"],
    "elegibilidade": ["treinamento_id", "colaborador_id"],
    "presencas": ["treinamento_id", "colaborador_id", "presente", "observacao", "atualizado_em"],
}


def garantir_url():
    if not os.environ.get("DATABASE_URL", "").strip():
        url = getpass.getpass("Cole a URL de conexão PostgreSQL (entrada oculta): ").strip()
        if not url:
            raise RuntimeError("Nenhuma URL foi informada.")
        os.environ["DATABASE_URL"] = url
    obter_database_url()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sqlite",
        default=str(Path(__file__).resolve().parent / "dados" / "assiduidade.db"),
        help="Caminho do banco SQLite original (padrão: ./dados/assiduidade.db)",
    )
    args = parser.parse_args()
    caminho = Path(args.sqlite).expanduser().resolve()

    if not caminho.is_file():
        raise FileNotFoundError(f"Banco SQLite não encontrado: {caminho}")

    garantir_url()
    print(f"Origem SQLite: {caminho}")
    print("Preparando as tabelas PostgreSQL (sem apagar tabelas existentes)...")
    inicializar_banco()

    with sqlite3.connect(str(caminho)) as sqlite_conn:
        sqlite_conn.row_factory = sqlite3.Row
        tabelas_origem = {
            r[0] for r in sqlite_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        faltantes = set(TABELAS) - tabelas_origem
        if faltantes:
            raise RuntimeError(
                "O SQLite não contém as tabelas esperadas: " + ", ".join(sorted(faltantes))
            )

        dados = {}
        for tabela, colunas in TABELAS.items():
            lista_colunas = ", ".join(f'"{c}"' for c in colunas)
            linhas = sqlite_conn.execute(
                f'SELECT {lista_colunas} FROM "{tabela}"'
            ).fetchall()
            dados[tabela] = [tuple(linha[c] for c in colunas) for linha in linhas]

    total = sum(len(linhas) for linhas in dados.values())
    print("Registros encontrados:")
    for tabela, linhas in dados.items():
        print(f"  {tabela}: {len(linhas)}")
    if total == 0:
        print("Aviso: o SQLite não contém registros. Nenhum dado foi transferido.")

    # A migração só prossegue se as quatro tabelas de destino estiverem vazias.
    with conectar() as conn:
        for tabela in TABELAS:
            quantidade = conn.execute(f'SELECT COUNT(*) AS n FROM "{tabela}"').fetchone()["n"]
            if quantidade:
                raise RuntimeError(
                    f'A tabela PostgreSQL "{tabela}" já tem {quantidade} registro(s). '
                    "Para evitar duplicidade ou sobrescrita, a migração foi interrompida. "
                    "Use um banco de destino vazio."
                )

        cursor = conn.raw.cursor()
        try:
            for tabela, colunas in TABELAS.items():
                linhas = dados[tabela]
                if not linhas:
                    continue
                nomes = ", ".join(f'"{c}"' for c in colunas)
                marcadores = ", ".join(["%s"] * len(colunas))
                sql = f'INSERT INTO "{tabela}" ({nomes}) VALUES ({marcadores})'
                cursor.executemany(sql, linhas)

            # Faz com que o próximo ID automático seja maior que o maior ID migrado.
            for tabela in ("colaboradores", "treinamentos"):
                cursor.execute(
                    "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {tabela}), 1), "
                    f"EXISTS (SELECT 1 FROM {tabela}))",
                    (tabela,),
                )
        finally:
            cursor.close()

    print("\nMigração concluída. Os IDs e os relacionamentos foram preservados.")
    print("O arquivo SQLite original não foi alterado.")
    print("Próximo passo: conferir os totais no sistema e testar relatórios antes de publicar.")


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as erro:
        print(f"\nMIGRAÇÃO INTERROMPIDA: {erro}", file=sys.stderr)
        sys.exit(1)
