"""고아 그래프 엣지(삭제된 정점을 가리키는 엣지) 정리 스크립트.

배경: Product 정점이 삭제된 뒤에도 그 정점을 start/end 로 가리키던 CONTAINS 등의
엣지가 남아 있으면, Apache AGE 의 가변 길이 경로([*1..3]) 쿼리가
"insert_vertex_edge: failed to insert" 에러로 실패한다(진단 완료). 이 스크립트는
ag_catalog.ag_label 에서 그래프의 엣지/정점 라벨을 동적으로 조회해, start_id 또는
end_id 가 어떤 정점 라벨 테이블에도 존재하지 않는 엣지를 찾아 정리한다.

기본 실행은 dry-run(목록만 출력, 삭제 없음). --apply 를 주면 실제 DELETE 후
traverse_cache 를 무효화한다(그래프 토폴로지가 바뀌므로 기존 캐시가 stale 해진다).

실행: .venv/Scripts/python.exe scripts/cleanup_orphan_graph_edges.py [--apply]
"""

from __future__ import annotations

import argparse
import os

import psycopg
import structlog
from psycopg import sql

logger = structlog.get_logger()

GRAPH_NAME = "skinmate"


def _table(label: str) -> sql.Composed:
    return sql.SQL("{}.{}").format(sql.Identifier(GRAPH_NAME), sql.Identifier(label))


def _labels(cur: psycopg.Cursor[tuple[str]], kind: str) -> list[str]:
    """ag_catalog.ag_label 에서 'skinmate' 그래프의 라벨명을 동적으로 조회(base 라벨 제외)."""
    cur.execute(
        """
        SELECT name FROM ag_catalog.ag_label
        WHERE graph = (SELECT graphid FROM ag_catalog.ag_graph WHERE name = %s)
          AND kind = %s AND name NOT LIKE '\\_ag\\_label\\_%%'
        """,
        (GRAPH_NAME, kind),
    )
    return [row[0] for row in cur.fetchall()]


def _find_orphans(
    cur: psycopg.Cursor[tuple[object, ...]], edge_labels: list[str], vertex_labels: list[str]
) -> list[tuple[str, str, str, str, str]]:
    """(edge_label, edge_id, start_id, end_id, missing_side) 목록 반환. missing_side 는
    'start'/'end'/'both' 중 하나 — 어느 endpoint 가 정점 테이블에 없는지 표시."""
    vertex_union = sql.SQL(" UNION ALL ").join(
        sql.SQL("SELECT id FROM {}").format(_table(v)) for v in vertex_labels
    )
    orphans: list[tuple[str, str, str, str, str]] = []
    for edge_label in edge_labels:
        cur.execute(
            sql.SQL("""
                SELECT id, start_id, end_id,
                       start_id NOT IN (SELECT id FROM ({verts}) AS sv) AS start_missing,
                       end_id NOT IN (SELECT id FROM ({verts}) AS ev) AS end_missing
                FROM {edge}
                WHERE start_id NOT IN (SELECT id FROM ({verts}) AS sv2)
                   OR end_id NOT IN (SELECT id FROM ({verts}) AS ev2)
                """).format(verts=vertex_union, edge=_table(edge_label)),
        )
        for edge_id, start_id, end_id, start_missing, end_missing in cur.fetchall():
            missing_side = (
                "both" if start_missing and end_missing else ("start" if start_missing else "end")
            )
            orphans.append((edge_label, str(edge_id), str(start_id), str(end_id), missing_side))
    return orphans


def main() -> None:
    parser = argparse.ArgumentParser(
        description="고아 그래프 엣지(존재하지 않는 정점을 가리키는 엣지) 정리"
    )
    parser.add_argument("--apply", action="store_true", help="실제 삭제 수행(기본은 dry-run)")
    args = parser.parse_args()

    user = os.getenv("POSTGRES_USER", "skinmate")
    password = os.getenv("POSTGRES_PASSWORD")
    if not password:
        logger.error("POSTGRES_PASSWORD is not set")
        exit(1)
    db_name = os.getenv("POSTGRES_DB", "skinmate")
    port = os.getenv("POSTGRES_PORT", "5432")
    host = os.getenv("POSTGRES_HOST", "localhost")  # 기본값 localhost, Docker 컨테이너 내에서는 db

    db_url = f"postgresql://{user}:{password}@{host}:{port}/{db_name}"

    logger.info("cleanup_started", host=host, port=port, db=db_name, apply=args.apply)

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        edge_labels = _labels(cur, "e")
        vertex_labels = _labels(cur, "v")
        logger.info("labels_discovered", edges=edge_labels, vertices=vertex_labels)

        orphans = _find_orphans(cur, edge_labels, vertex_labels)
        logger.info("orphan_edges_found", count=len(orphans))
        for edge_label, edge_id, start_id, end_id, missing_side in orphans:
            logger.info(
                "orphan_edge",
                label=edge_label,
                edge_id=edge_id,
                start_id=start_id,
                end_id=end_id,
                missing_side=missing_side,
            )

        if not args.apply:
            logger.info("dry_run_complete_rerun_with_apply_to_delete")
            return

        if not orphans:
            logger.info("nothing_to_delete")
            return

        for edge_label, edge_id, _start_id, _end_id, _missing_side in orphans:
            cur.execute(
                sql.SQL("DELETE FROM {} WHERE id = %s").format(_table(edge_label)),
                (edge_id,),
            )
        # 그래프 토폴로지가 바뀌었으므로 traverse 캐시(traverse.py 소유)를 무효화한다.
        cur.execute("DELETE FROM public.traverse_cache;")
        conn.commit()
        logger.info("cleanup_applied", deleted=len(orphans))


if __name__ == "__main__":
    main()
