"""Persistência do Playbook dentro da UnitOfWork central.

O módulo não conhece caminhos físicos de mídia nem a interface. Arquivos locais
são representados apenas por uma chave relativa, cuja resolução protegida fica
no serviço de aplicação.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping


PLAYBOOK_TABLES = frozenset(
    {
        "playbook_folders",
        "playbook_contents",
        "playbook_content_revisions",
        "playbook_content_folders",
        "playbook_content_aliases",
        "playbook_content_positions",
        "playbook_content_relations",
        "playbook_attachments",
        "playbook_favorites",
        "playbook_recent_views",
        "playbook_training_plans",
        "playbook_training_plan_revisions",
        "playbook_training_plan_items",
        "playbook_series",
        "playbook_sessions",
        "playbook_session_revisions",
        "playbook_session_event_links",
        "playbook_session_event_history",
        "playbook_session_evaluations",
    }
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _ids(values: Iterable[int]) -> tuple[int, ...]:
    return tuple(sorted({int(value) for value in values if int(value) > 0}))


def _placeholders(values: Iterable[object]) -> str:
    return ",".join("?" for _ in values)


class PlaybookRepository:
    """SQL do Playbook. Todas as chamadas usam a conexão da UnitOfWork."""

    def __init__(self, connection: Any, *, read_only: bool = False) -> None:
        self.connection = connection
        self.read_only = read_only

    def _table_exists(self, table: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?",
            (table,),
        ).fetchone() is not None

    def is_available(self) -> bool:
        return all(self._table_exists(table) for table in PLAYBOOK_TABLES)

    def _require_available(self) -> None:
        if not self.is_available():
            raise RuntimeError(
                "O Playbook ainda precisa da migração de banco aprovada. "
                "Nenhuma estrutura foi criada automaticamente."
            )

    def _audit(
        self,
        *,
        actor_user_id: int,
        action: str,
        entity: str,
        target_id: int | str | None,
        before: Any = None,
        after: Any = None,
    ) -> None:
        self.connection.execute(
            """INSERT INTO security_audit_events(
                   actor_user_id,occurred_at,action,entity,target_id,origin,
                   before_json,after_json,request_id
               ) VALUES(?,?,?,?,?,?,?,?,NULL)""",
            (
                int(actor_user_id),
                _now_iso(),
                action,
                entity,
                str(target_id) if target_id is not None else None,
                "playbook",
                json.dumps(before, ensure_ascii=False, sort_keys=True)
                if before is not None
                else None,
                json.dumps(after, ensure_ascii=False, sort_keys=True)
                if after is not None
                else None,
            ),
        )

    @staticmethod
    def _normalize_texts(values: Iterable[object]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in values:
            value = str(raw or "").strip()
            key = value.casefold()
            if not value or key in seen:
                continue
            seen.add(key)
            result.append(value)
        return result

    def _assert_team_exists(self, team_id: int) -> None:
        if self.connection.execute(
            "SELECT 1 FROM teams WHERE id=? AND active=1", (int(team_id),)
        ).fetchone() is None:
            raise KeyError("Equipe não encontrada ou inativa.")

    def active_team_ids(self) -> tuple[int, ...]:
        """Escopo esportivo de DEV/ADMIN sem abrir acesso SQLite no módulo."""
        self._require_available()
        return tuple(
            int(row[0])
            for row in self.connection.execute(
                "SELECT id FROM teams WHERE active=1 ORDER BY id"
            ).fetchall()
        )

    def teams(self, team_ids: Iterable[int]) -> list[dict[str, Any]]:
        """Nomes da equipe para a interface, sempre filtrados pelo escopo."""

        self._require_available()
        allowed = _ids(team_ids)
        if not allowed:
            return []
        return [
            dict(row)
            for row in self.connection.execute(
                f"""SELECT id,code,slug,display_name
                    FROM teams WHERE id IN ({_placeholders(allowed)}) AND active=1
                    ORDER BY display_name COLLATE NOCASE,id""",
                allowed,
            ).fetchall()
        ]

    def _folder(self, folder_id: int) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM playbook_folders WHERE id=?", (int(folder_id),)
        ).fetchone()
        return dict(row) if row is not None else None

    def _content(self, content_id: int) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM playbook_contents WHERE id=?", (int(content_id),)
        ).fetchone()
        return dict(row) if row is not None else None

    def _allowed_folder(
        self,
        folder_id: int,
        team_ids: Iterable[int],
        *,
        include_archived: bool = True,
    ) -> dict[str, Any]:
        allowed = _ids(team_ids)
        folder = self._folder(folder_id)
        if folder is None or int(folder["team_id"]) not in allowed:
            raise KeyError("Pasta não encontrada na equipe autorizada.")
        if not include_archived and folder["archived_at"] is not None:
            raise ValueError("A pasta está arquivada; restaure-a antes de usá-la.")
        return folder

    def _allowed_content(
        self,
        content_id: int,
        team_ids: Iterable[int],
        *,
        published_only: bool = False,
    ) -> dict[str, Any]:
        allowed = _ids(team_ids)
        content = self._content(content_id)
        if content is None or int(content["team_id"]) not in allowed:
            raise KeyError("Conteúdo não encontrado na equipe autorizada.")
        if published_only and content["status"] != "PUBLISHED":
            raise KeyError("Conteúdo publicado não encontrado.")
        return content

    def _folder_ids_in_subtree(self, folder_id: int) -> list[int]:
        pending = [int(folder_id)]
        result: list[int] = []
        while pending:
            current = pending.pop()
            result.append(current)
            pending.extend(
                int(row[0])
                for row in self.connection.execute(
                    "SELECT id FROM playbook_folders WHERE parent_id=? ORDER BY id",
                    (current,),
                ).fetchall()
            )
        return result

    def _next_folder_order(self, team_id: int, parent_id: int | None) -> int:
        if parent_id is None:
            row = self.connection.execute(
                "SELECT COALESCE(MAX(sort_order),-1)+1 FROM playbook_folders "
                "WHERE team_id=? AND parent_id IS NULL",
                (int(team_id),),
            ).fetchone()
        else:
            row = self.connection.execute(
                "SELECT COALESCE(MAX(sort_order),-1)+1 FROM playbook_folders "
                "WHERE team_id=? AND parent_id=?",
                (int(team_id), int(parent_id)),
            ).fetchone()
        return int(row[0])

    def _content_snapshot(self, content_id: int) -> dict[str, Any]:
        content = self._content(content_id)
        if content is None:
            raise KeyError("Conteúdo não encontrado.")
        aliases = [
            str(row[0])
            for row in self.connection.execute(
                "SELECT alias FROM playbook_content_aliases WHERE content_id=? "
                "ORDER BY alias COLLATE NOCASE",
                (int(content_id),),
            ).fetchall()
        ]
        positions = [
            str(row[0])
            for row in self.connection.execute(
                "SELECT position FROM playbook_content_positions WHERE content_id=? "
                "ORDER BY position COLLATE NOCASE",
                (int(content_id),),
            ).fetchall()
        ]
        folders = [
            {
                "folder_id": int(row["folder_id"]),
                "placement_kind": str(row["placement_kind"]),
                "sort_order": int(row["sort_order"]),
            }
            for row in self.connection.execute(
                """SELECT folder_id,placement_kind,sort_order
                   FROM playbook_content_folders WHERE content_id=?
                   ORDER BY sort_order,folder_id""",
                (int(content_id),),
            ).fetchall()
        ]
        exercise_row = self.connection.execute(
            "SELECT spec_json FROM playbook_exercise_specs WHERE content_id=?",
            (int(content_id),),
        ).fetchone() if self._table_exists("playbook_exercise_specs") else None
        exercise_variants = [] if exercise_row is None else json.loads(str(exercise_row[0])).get("variants", [])
        return {
            "title": str(content["title"]),
            "content_kind": str(content["content_kind"]),
            "perspective": content["perspective"],
            "objective": str(content["objective"]),
            "when_to_use": str(content["when_to_use"]),
            "prerequisites": str(content["prerequisites"]),
            "steps": str(content["steps"]),
            "notes": str(content["notes"]),
            "aliases": aliases,
            "positions": positions,
            "folders": folders,
            "exercise_variants": exercise_variants,
        }

    def _replace_exercise_spec(self, content_id: int, payload: Mapping[str, Any]) -> None:
        variants = list(payload.get("exercise_variants") or ())
        content_kind = str(payload.get("content_kind") or "CONTENT").strip().upper()
        if variants and content_kind != "EXERCISE":
            raise ValueError("Requisitos de exercício exigem conteúdo do tipo EXERCISE.")
        if not self._table_exists("playbook_exercise_specs"):
            if variants:
                raise RuntimeError("O banco ainda não recebeu a atualização de requisitos de exercícios.")
            return
        self.connection.execute("DELETE FROM playbook_exercise_specs WHERE content_id=?", (int(content_id),))
        if variants:
            self.connection.execute(
                "INSERT INTO playbook_exercise_specs(content_id,spec_json,updated_at) VALUES(?,?,?)",
                (
                    int(content_id),
                    json.dumps({"variants": variants}, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    _now_iso(),
                ),
            )

    def _store_revision(
        self,
        content_id: int,
        *,
        revision_number: int,
        actor_user_id: int,
        change_note: str = "",
        restored_from_revision_id: int | None = None,
    ) -> None:
        self.connection.execute(
            """INSERT INTO playbook_content_revisions(
                   content_id,revision_number,snapshot_json,change_note,
                   restored_from_revision_id,created_by_user_id,created_at
               ) VALUES(?,?,?,?,?,?,?)""",
            (
                int(content_id),
                int(revision_number),
                json.dumps(
                    self._content_snapshot(content_id),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                str(change_note or "").strip(),
                restored_from_revision_id,
                int(actor_user_id),
                _now_iso(),
            ),
        )

    def _replace_aliases_positions(self, content_id: int, payload: Mapping[str, Any]) -> None:
        aliases = self._normalize_texts(payload.get("aliases") or ())
        positions = self._normalize_texts(payload.get("positions") or ())
        self.connection.execute(
            "DELETE FROM playbook_content_aliases WHERE content_id=?", (int(content_id),)
        )
        self.connection.execute(
            "DELETE FROM playbook_content_positions WHERE content_id=?", (int(content_id),)
        )
        self.connection.executemany(
            "INSERT INTO playbook_content_aliases(content_id,alias) VALUES(?,?)",
            [(int(content_id), alias) for alias in aliases],
        )
        self.connection.executemany(
            "INSERT INTO playbook_content_positions(content_id,position) VALUES(?,?)",
            [(int(content_id), position) for position in positions],
        )

    def _replace_placements(
        self,
        content_id: int,
        team_id: int,
        placements: Iterable[Mapping[str, Any]],
    ) -> None:
        normalized: list[tuple[int, str, int]] = []
        seen: set[int] = set()
        for ordinal, raw in enumerate(placements):
            folder_id = int(raw["folder_id"])
            if folder_id in seen:
                continue
            folder = self._folder(folder_id)
            if folder is None or int(folder["team_id"]) != int(team_id):
                raise ValueError("Uma pasta escolhida não pertence à mesma equipe.")
            if folder["archived_at"] is not None:
                raise ValueError("Não é possível colocar conteúdo em pasta arquivada.")
            kind = str(raw.get("placement_kind") or "PLACEMENT").upper()
            if kind not in {"PLACEMENT", "SHORTCUT"}:
                raise ValueError("Tipo de atalho inválido.")
            seen.add(folder_id)
            normalized.append((folder_id, kind, int(raw.get("sort_order", ordinal))))
        if not normalized:
            raise ValueError("Escolha ao menos uma pasta para o conteúdo.")
        self.connection.execute(
            "DELETE FROM playbook_content_folders WHERE content_id=?", (int(content_id),)
        )
        self.connection.executemany(
            """INSERT INTO playbook_content_folders(
                   content_id,folder_id,placement_kind,sort_order,created_at
               ) VALUES(?,?,?,?,?)""",
            [
                (int(content_id), folder_id, kind, order, _now_iso())
                for folder_id, kind, order in normalized
            ],
        )

    # ------------------------------------------------------------------
    # Pastas e taxonomia inicial
    # ------------------------------------------------------------------
    def seed_initial_taxonomy(self, team_id: int, *, actor_user_id: int) -> dict[str, Any]:
        self._require_available()
        self._assert_team_exists(team_id)
        existing = self.connection.execute(
            "SELECT COUNT(*) FROM playbook_folders WHERE team_id=?", (int(team_id),)
        ).fetchone()
        if int(existing[0]):
            raise ValueError(
                "A equipe já possui uma árvore de Playbook; a estrutura inicial "
                "não substitui pastas existentes."
            )

        def add(name: str, parent_id: int | None) -> int:
            return int(
                self.create_folder(
                    team_id,
                    name=name,
                    parent_id=parent_id,
                    actor_user_id=actor_user_id,
                    audit=False,
                )["id"]
            )

        tecnica = add("Técnica", None)
        tatica = add("Tática", None)
        handball = add("Handball", tecnica)
        academia = add("Academia", tecnica)
        for name in (
            "Passe e recepção",
            "Drible",
            "Arremesso",
            "Finta",
            "1x1",
            "Pivô",
            "Defesa individual",
            "Goleiro",
        ):
            add(name, handball)
        for name in (
            "Ombros",
            "Peito",
            "Costas",
            "Core",
            "Quadríceps",
            "Posterior de coxa",
            "Glúteos",
            "Panturrilhas",
            "Braços",
        ):
            add(name, academia)

        ataque = add("Ataque", tatica)
        defesa = add("Defesa", tatica)
        transicao = add("Transição", tatica)
        especiais = add("Situações especiais", tatica)
        jogadas = (
            "X",
            "Desdobre",
            "Corrida",
            "Circulação",
            "Roda",
            "Islândia",
            "Portugal",
            "Espanha",
            "Cruzamento",
            "Amplitude",
        )
        principais = add("Jogadas principais", ataque)
        for name in jogadas:
            add(name, principais)
        contra = add("Contra esquemas defensivos", ataque)
        for scheme in ("6x0", "5x1"):
            scheme_id = add(scheme, contra)
            for name in jogadas:
                add(name, scheme_id)
        reduzidas_ataque = add("Situações reduzidas e propostas da defesa", ataque)
        for name in ("1x1", "2x2", "Subida", "Triângulo", "Troca de pivô", "Ímpar", "Dissuasão"):
            add(name, reduzidas_ataque)
        for scheme in ("6x0", "5x1"):
            scheme_id = add(scheme, defesa)
            for name in jogadas:
                add(name, scheme_id)
        reduzidas_defesa = add("Situações reduzidas e respostas defensivas", defesa)
        for name in ("1x1", "2x2", "Subida", "Triângulo", "Troca de pivô", "Ímpar", "Dissuasão"):
            add(name, reduzidas_defesa)
        for name in ("Contra-ataque", "Retorno defensivo", "Segunda onda", "Troca ataque-defesa"):
            add(name, transicao)
        for name in ("Tiro de 7 m", "Tiro livre", "Superioridade numérica", "Inferioridade numérica", "Fim de jogo"):
            add(name, especiais)
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.taxonomy.seed",
            entity="playbook_team",
            target_id=team_id,
            after={"roots": ["Técnica", "Tática"]},
        )
        return self.tree([team_id])

    def tree(
        self,
        team_ids: Iterable[int],
        *,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        self._require_available()
        allowed = _ids(team_ids)
        if not allowed:
            return {"items": [], "roots": []}
        archived_clause = "" if include_archived else " AND f.archived_at IS NULL"
        rows = self.connection.execute(
            f"""SELECT f.id,f.team_id,f.parent_id,f.name,f.sort_order,f.archived_at,
                       f.created_at,f.updated_at,
                       COUNT(DISTINCT p.content_id) content_count
                FROM playbook_folders f
                LEFT JOIN playbook_content_folders p ON p.folder_id=f.id
                WHERE f.team_id IN ({_placeholders(allowed)}){archived_clause}
                GROUP BY f.id
                ORDER BY f.team_id,f.parent_id IS NOT NULL,f.parent_id,f.sort_order,f.id""",
            allowed,
        ).fetchall()
        items = [dict(row) for row in rows]
        by_id: dict[int, dict[str, Any]] = {}
        roots: list[dict[str, Any]] = []
        for row in items:
            row["children"] = []
            by_id[int(row["id"])] = row
        for row in items:
            parent_id = row["parent_id"]
            if parent_id is None or int(parent_id) not in by_id:
                roots.append(row)
            else:
                by_id[int(parent_id)]["children"].append(row)
        return {"items": items, "roots": roots}

    def create_folder(
        self,
        team_id: int,
        *,
        name: str,
        parent_id: int | None,
        actor_user_id: int,
        sort_order: int | None = None,
        audit: bool = True,
    ) -> dict[str, Any]:
        self._require_available()
        self._assert_team_exists(team_id)
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("O nome da pasta é obrigatório.")
        if len(clean_name) > 160:
            raise ValueError("O nome da pasta pode ter no máximo 160 caracteres.")
        if parent_id is not None:
            parent = self._folder(parent_id)
            if parent is None or int(parent["team_id"]) != int(team_id):
                raise ValueError("A pasta pai não pertence à mesma equipe.")
            if parent["archived_at"] is not None:
                raise ValueError("Restaure a pasta pai antes de criar uma subpasta.")
        now = _now_iso()
        cursor = self.connection.execute(
            """INSERT INTO playbook_folders(
                   team_id,parent_id,name,sort_order,archived_at,archived_by_user_id,
                   created_by_user_id,updated_by_user_id,created_at,updated_at
               ) VALUES(?,?,?,?,NULL,NULL,?,?,?,?)""",
            (
                int(team_id),
                int(parent_id) if parent_id is not None else None,
                clean_name,
                self._next_folder_order(team_id, parent_id)
                if sort_order is None
                else max(0, int(sort_order)),
                int(actor_user_id),
                int(actor_user_id),
                now,
                now,
            ),
        )
        folder = self._folder(int(cursor.lastrowid))
        if folder is None:
            raise RuntimeError("A pasta criada não pôde ser relida.")
        if audit:
            self._audit(
                actor_user_id=actor_user_id,
                action="playbook.folder.create",
                entity="playbook_folder",
                target_id=folder["id"],
                after=folder,
            )
        return folder

    def update_folder(
        self,
        folder_id: int,
        *,
        name: str,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]:
        self._require_available()
        before = self._allowed_folder(folder_id, team_ids)
        clean_name = str(name or "").strip()
        if not clean_name or len(clean_name) > 160:
            raise ValueError("Informe um nome de pasta entre 1 e 160 caracteres.")
        self.connection.execute(
            "UPDATE playbook_folders SET name=?,updated_by_user_id=?,updated_at=? WHERE id=?",
            (clean_name, int(actor_user_id), _now_iso(), int(folder_id)),
        )
        after = self._folder(folder_id)
        if after is None:
            raise RuntimeError("A pasta renomeada não pôde ser relida.")
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.folder.rename",
            entity="playbook_folder",
            target_id=folder_id,
            before=before,
            after=after,
        )
        return after

    def move_folder(
        self,
        folder_id: int,
        *,
        parent_id: int | None,
        sort_order: int | None,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]:
        self._require_available()
        before = self._allowed_folder(folder_id, team_ids, include_archived=False)
        if parent_id is not None:
            parent = self._allowed_folder(parent_id, team_ids, include_archived=False)
            if int(parent["team_id"]) != int(before["team_id"]):
                raise ValueError("A pasta de destino pertence a outra equipe.")
            if int(parent_id) in self._folder_ids_in_subtree(folder_id):
                raise ValueError("Não é possível mover uma pasta para dentro dela mesma.")
        next_order = (
            self._next_folder_order(int(before["team_id"]), parent_id)
            if sort_order is None
            else max(0, int(sort_order))
        )
        self.connection.execute(
            """UPDATE playbook_folders
               SET parent_id=?,sort_order=?,updated_by_user_id=?,updated_at=?
               WHERE id=?""",
            (
                int(parent_id) if parent_id is not None else None,
                next_order,
                int(actor_user_id),
                _now_iso(),
                int(folder_id),
            ),
        )
        after = self._folder(folder_id)
        if after is None:
            raise RuntimeError("A pasta movida não pôde ser relida.")
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.folder.move",
            entity="playbook_folder",
            target_id=folder_id,
            before=before,
            after=after,
        )
        return after

    def copy_folder_structure(
        self,
        folder_id: int,
        *,
        parent_id: int | None,
        name: str,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]:
        """Cria um modelo de árvore sem duplicar conteúdos ou arquivos.

        A cópia só é permitida dentro da mesma equipe. Isso mantém os IDs de
        conteúdo, favoritos, planos e anexos fora da operação, que é justamente
        o comportamento seguro esperado de um "modelo de estrutura".
        """

        self._require_available()
        source = self._allowed_folder(folder_id, team_ids, include_archived=False)
        if parent_id is not None:
            parent = self._allowed_folder(parent_id, team_ids, include_archived=False)
            if int(parent["team_id"]) != int(source["team_id"]):
                raise ValueError("A pasta de destino pertence a outra equipe.")
        clean_name = str(name or "").strip()
        if not clean_name or len(clean_name) > 160:
            raise ValueError("Informe um nome de modelo entre 1 e 160 caracteres.")

        created: list[int] = []

        def clone(source_id: int, destination_parent_id: int | None, *, root: bool = False) -> int:
            original = self._folder(source_id)
            if original is None:
                raise RuntimeError("A estrutura de origem não pôde ser relida.")
            copied = self.create_folder(
                int(source["team_id"]),
                name=clean_name if root else str(original["name"]),
                parent_id=destination_parent_id,
                actor_user_id=actor_user_id,
                audit=False,
            )
            copied_id = int(copied["id"])
            created.append(copied_id)
            children = self.connection.execute(
                "SELECT id FROM playbook_folders WHERE parent_id=? AND archived_at IS NULL "
                "ORDER BY sort_order,id",
                (int(source_id),),
            ).fetchall()
            for child in children:
                clone(int(child[0]), copied_id)
            return copied_id

        root_id = clone(int(folder_id), parent_id, root=True)
        result = {
            "folder": self._folder(root_id),
            "source_folder_id": int(folder_id),
            "copied_folder_ids": created,
            "copied_count": len(created),
            "contents_copied": 0,
        }
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.folder.copy_structure",
            entity="playbook_folder",
            target_id=root_id,
            before={"source_folder_id": int(folder_id)},
            after=result,
        )
        return result

    def reorder_folders(
        self,
        folder_ids: Iterable[int],
        *,
        parent_id: int | None,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> list[dict[str, Any]]:
        self._require_available()
        ordered = [int(value) for value in folder_ids]
        if not ordered or len(set(ordered)) != len(ordered):
            raise ValueError("Informe uma ordenação sem duplicar pastas.")
        allowed = _ids(team_ids)
        parent_team_id: int | None = None
        if parent_id is not None:
            parent = self._allowed_folder(parent_id, allowed, include_archived=False)
            parent_team_id = int(parent["team_id"])
        folders = [self._allowed_folder(folder_id, allowed, include_archived=False) for folder_id in ordered]
        if any(
            (folder["parent_id"] != parent_id)
            or (parent_team_id is not None and int(folder["team_id"]) != parent_team_id)
            for folder in folders
        ):
            raise ValueError("A ordenação só pode conter pastas irmãs do mesmo destino.")
        now = _now_iso()
        self.connection.executemany(
            "UPDATE playbook_folders SET sort_order=?,updated_by_user_id=?,updated_at=? WHERE id=?",
            [(index, int(actor_user_id), now, folder_id) for index, folder_id in enumerate(ordered)],
        )
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.folder.reorder",
            entity="playbook_folder_collection",
            target_id=parent_id,
            after={"folder_ids": ordered},
        )
        return [self._folder(folder_id) or {} for folder_id in ordered]

    def folder_impact(
        self,
        folder_id: int,
        *,
        team_ids: Iterable[int],
    ) -> dict[str, Any]:
        self._require_available()
        folder = self._allowed_folder(folder_id, team_ids)
        subtree = self._folder_ids_in_subtree(folder_id)
        placeholders = _placeholders(subtree)
        content_rows = self.connection.execute(
            f"""SELECT DISTINCT c.id,c.title,c.status
                FROM playbook_contents c
                JOIN playbook_content_folders p ON p.content_id=c.id
                WHERE p.folder_id IN ({placeholders})
                ORDER BY c.title COLLATE NOCASE""",
            subtree,
        ).fetchall()
        content_ids = [int(row["id"]) for row in content_rows]
        other_locations: dict[int, list[dict[str, Any]]] = {content_id: [] for content_id in content_ids}
        linked_events: list[dict[str, Any]] = []
        if content_ids:
            content_placeholders = _placeholders(content_ids)
            for row in self.connection.execute(
                f"""SELECT p.content_id,f.id folder_id,f.name
                    FROM playbook_content_folders p
                    JOIN playbook_folders f ON f.id=p.folder_id
                    WHERE p.content_id IN ({content_placeholders})
                    ORDER BY f.name COLLATE NOCASE""",
                content_ids,
            ).fetchall():
                if int(row["folder_id"]) not in subtree:
                    other_locations[int(row["content_id"])].append(dict(row))
            linked_events = [
                dict(row)
                for row in self.connection.execute(
                    f"""SELECT DISTINCT e.id,e.starts_at,e.title,e.status
                        FROM playbook_training_plan_items i
                        JOIN playbook_sessions ps ON ps.plan_id=i.plan_id
                        JOIN playbook_session_event_links l ON l.session_id=ps.id
                        JOIN calendar_events e ON e.id=l.calendar_event_id
                        WHERE i.content_id IN ({content_placeholders})
                        ORDER BY e.starts_at,e.id""",
                    content_ids,
                ).fetchall()
            ]
        return {
            "folder": folder,
            "subfolder_count": max(0, len(subtree) - 1),
            "content_count": len(content_rows),
            "contents": [
                {**dict(row), "other_locations": other_locations[int(row["id"])]}
                for row in content_rows
            ],
            "linked_events": linked_events,
            "is_archived": folder["archived_at"] is not None,
            "reversible_action": "archive" if folder["archived_at"] is None else "restore",
        }

    def archive_folder(
        self,
        folder_id: int,
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
        restore: bool = False,
    ) -> dict[str, Any]:
        self._require_available()
        before = self.folder_impact(folder_id, team_ids=team_ids)
        subtree = self._folder_ids_in_subtree(folder_id)
        now = _now_iso()
        if restore:
            self.connection.execute(
                f"""UPDATE playbook_folders
                    SET archived_at=NULL,archived_by_user_id=NULL,
                        updated_by_user_id=?,updated_at=?
                    WHERE id IN ({_placeholders(subtree)})""",
                (int(actor_user_id), now, *subtree),
            )
            action = "restore"
        else:
            self.connection.execute(
                f"""UPDATE playbook_folders
                    SET archived_at=?,archived_by_user_id=?,
                        updated_by_user_id=?,updated_at=?
                    WHERE id IN ({_placeholders(subtree)})""",
                (now, int(actor_user_id), int(actor_user_id), now, *subtree),
            )
            action = "archive"
        after = self.folder_impact(folder_id, team_ids=team_ids)
        self._audit(
            actor_user_id=actor_user_id,
            action=f"playbook.folder.{action}",
            entity="playbook_folder",
            target_id=folder_id,
            before=before,
            after=after,
        )
        return after

    def hard_delete_folder(
        self,
        folder_id: int,
        *,
        confirmation: str,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]:
        self._require_available()
        expected = f"EXCLUIR PASTA {int(folder_id)}"
        if str(confirmation or "").strip() != expected:
            raise ValueError(f"Para excluir definitivamente, digite exatamente: {expected}")
        impact = self.folder_impact(folder_id, team_ids=team_ids)
        if not impact["is_archived"]:
            raise ValueError("Archive a pasta antes da exclusão definitiva para ter uma etapa reversível.")
        subtree = self._folder_ids_in_subtree(folder_id)
        self.connection.execute(
            f"DELETE FROM playbook_content_folders WHERE folder_id IN ({_placeholders(subtree)})",
            subtree,
        )
        for candidate in reversed(subtree):
            self.connection.execute("DELETE FROM playbook_folders WHERE id=?", (candidate,))
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.folder.delete_permanent",
            entity="playbook_folder",
            target_id=folder_id,
            before=impact,
            after={"deleted_folder_ids": subtree},
        )
        return {"deleted": True, "folder_id": int(folder_id), "impact": impact}

    # ------------------------------------------------------------------
    # Conteúdos, revisões, relações e mídia
    # ------------------------------------------------------------------
    def list_contents(
        self,
        team_ids: Iterable[int],
        *,
        folder_id: int | None = None,
        query: str | None = None,
        perspective: str | None = None,
        position: str | None = None,
        published_only: bool = False,
        include_archived: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._require_available()
        allowed = _ids(team_ids)
        if not allowed:
            return []
        clauses = [f"c.team_id IN ({_placeholders(allowed)})"]
        parameters: list[Any] = list(allowed)
        if published_only:
            clauses.append("c.status='PUBLISHED'")
        elif not include_archived:
            clauses.append("c.status<>'ARCHIVED'")
        if folder_id is not None:
            clauses.append("EXISTS(SELECT 1 FROM playbook_content_folders pf WHERE pf.content_id=c.id AND pf.folder_id=?)")
            parameters.append(int(folder_id))
        clean_perspective = str(perspective or "").strip().upper()
        if clean_perspective:
            if clean_perspective not in {"ATTACK", "DEFENSE", "NEUTRAL"}:
                raise ValueError("Perspectiva de filtro inválida.")
            clauses.append("c.perspective=?")
            parameters.append(clean_perspective)
        clean_position = str(position or "").strip()
        if clean_position:
            clauses.append(
                "EXISTS(SELECT 1 FROM playbook_content_positions pp "
                "WHERE pp.content_id=c.id AND pp.position=? COLLATE NOCASE)"
            )
            parameters.append(clean_position)
        clean_query = str(query or "").strip()
        if clean_query:
            term = f"%{clean_query}%"
            clauses.append(
                "(c.title LIKE ? COLLATE NOCASE OR c.objective LIKE ? COLLATE NOCASE "
                "OR c.steps LIKE ? COLLATE NOCASE OR EXISTS(SELECT 1 FROM "
                "playbook_content_aliases pa WHERE pa.content_id=c.id AND pa.alias LIKE ? COLLATE NOCASE))"
            )
            parameters.extend((term, term, term, term))
        rows = self.connection.execute(
            f"""SELECT c.id,c.team_id,c.title,c.content_kind,c.status,c.perspective,
                       c.objective,c.when_to_use,c.current_revision,c.updated_at,
                       COUNT(DISTINCT a.id) attachment_count
                FROM playbook_contents c
                LEFT JOIN playbook_attachments a ON a.content_id=c.id
                WHERE {' AND '.join(clauses)}
                GROUP BY c.id
                ORDER BY c.updated_at DESC,c.id DESC
                LIMIT ?""",
            (*parameters, max(1, min(int(limit), 250))),
        ).fetchall()
        items = [dict(row) for row in rows]
        for item in items:
            content_id = int(item["id"])
            item["aliases"] = [
                str(row[0])
                for row in self.connection.execute(
                    "SELECT alias FROM playbook_content_aliases WHERE content_id=? ORDER BY alias COLLATE NOCASE",
                    (content_id,),
                ).fetchall()
            ]
            item["positions"] = [
                str(row[0])
                for row in self.connection.execute(
                    "SELECT position FROM playbook_content_positions WHERE content_id=? ORDER BY position COLLATE NOCASE",
                    (content_id,),
                ).fetchall()
            ]
            item["folders"] = [
                dict(row)
                for row in self.connection.execute(
                    """SELECT f.id,f.name,p.placement_kind,p.sort_order
                       FROM playbook_content_folders p
                       JOIN playbook_folders f ON f.id=p.folder_id
                       WHERE p.content_id=? ORDER BY p.sort_order,f.name COLLATE NOCASE""",
                    (content_id,),
                ).fetchall()
            ]
        return items

    def content_detail(
        self,
        content_id: int,
        *,
        team_ids: Iterable[int],
        published_only: bool = False,
    ) -> dict[str, Any]:
        self._require_available()
        content = self._allowed_content(content_id, team_ids, published_only=published_only)
        result = dict(content)
        result["aliases"] = [
            str(row[0])
            for row in self.connection.execute(
                "SELECT alias FROM playbook_content_aliases WHERE content_id=? ORDER BY alias COLLATE NOCASE",
                (int(content_id),),
            ).fetchall()
        ]
        result["positions"] = [
            str(row[0])
            for row in self.connection.execute(
                "SELECT position FROM playbook_content_positions WHERE content_id=? ORDER BY position COLLATE NOCASE",
                (int(content_id),),
            ).fetchall()
        ]
        exercise_row = self.connection.execute(
            "SELECT spec_json FROM playbook_exercise_specs WHERE content_id=?",
            (int(content_id),),
        ).fetchone() if self._table_exists("playbook_exercise_specs") else None
        result["exercise_variants"] = [] if exercise_row is None else json.loads(str(exercise_row[0])).get("variants", [])
        result["folders"] = [
            dict(row)
            for row in self.connection.execute(
                """SELECT f.id,f.name,f.archived_at,p.placement_kind,p.sort_order
                   FROM playbook_content_folders p
                   JOIN playbook_folders f ON f.id=p.folder_id
                   WHERE p.content_id=? ORDER BY p.sort_order,f.name COLLATE NOCASE""",
                (int(content_id),),
            ).fetchall()
        ]
        result["relations"] = [
            dict(row)
            for row in self.connection.execute(
                """SELECT r.id,r.relation_type,r.target_content_id,
                          c.title target_title,c.status target_status,c.perspective target_perspective
                   FROM playbook_content_relations r
                   JOIN playbook_contents c ON c.id=r.target_content_id
                   WHERE r.source_content_id=?
                   ORDER BY r.relation_type,c.title COLLATE NOCASE""",
                (int(content_id),),
            ).fetchall()
        ]
        result["attachments"] = [
            {
                key: value
                for key, value in dict(row).items()
                if key != "storage_key"
            }
            for row in self.connection.execute(
                """SELECT id,content_id,storage_kind,label,url,storage_key,mime_type,
                          size_bytes,offline_essential,created_at
                   FROM playbook_attachments WHERE content_id=? ORDER BY id""",
                (int(content_id),),
            ).fetchall()
        ]
        return result

    def list_published_exercise_specs(self, team_ids: Iterable[int]) -> list[dict[str, Any]]:
        self._require_available()
        if not self._table_exists("playbook_exercise_specs"):
            return []
        allowed = _ids(team_ids)
        if not allowed:
            return []
        rows = self.connection.execute(
            f"""SELECT c.id content_id,c.title,s.spec_json
                  FROM playbook_contents c
                  JOIN playbook_exercise_specs s ON s.content_id=c.id
                 WHERE c.team_id IN ({_placeholders(allowed)})
                   AND c.status='PUBLISHED' AND UPPER(c.content_kind)='EXERCISE'
                 ORDER BY c.title COLLATE NOCASE,c.id""",
            allowed,
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            spec = json.loads(str(row["spec_json"]))
            variants = spec.get("variants") if isinstance(spec, dict) else None
            if isinstance(variants, list) and variants:
                result.append(
                    {"content_id": int(row["content_id"]), "title": str(row["title"]), "variants": variants}
                )
        return result

    def create_content(
        self,
        team_id: int,
        payload: Mapping[str, Any],
        *,
        actor_user_id: int,
    ) -> dict[str, Any]:
        self._require_available()
        self._assert_team_exists(team_id)
        title = str(payload.get("title") or "").strip()
        if not title or len(title) > 220:
            raise ValueError("Informe um título entre 1 e 220 caracteres.")
        perspective = payload.get("perspective")
        if perspective is not None:
            perspective = str(perspective).upper()
            if perspective not in {"ATTACK", "DEFENSE", "NEUTRAL"}:
                raise ValueError("Perspectiva tática inválida.")
        now = _now_iso()
        cursor = self.connection.execute(
            """INSERT INTO playbook_contents(
                   team_id,title,content_kind,status,perspective,objective,when_to_use,
                   prerequisites,steps,notes,current_revision,published_at,
                   published_by_user_id,archived_at,archived_by_user_id,
                   created_by_user_id,updated_by_user_id,created_at,updated_at
               ) VALUES(?,?,?,'DRAFT',?,?,?,?,?,?,1,NULL,NULL,NULL,NULL,?,?,?,?)""",
            (
                int(team_id),
                title,
                str(payload.get("content_kind") or "CONTENT").strip()[:80] or "CONTENT",
                perspective,
                str(payload.get("objective") or "").strip(),
                str(payload.get("when_to_use") or "").strip(),
                str(payload.get("prerequisites") or "").strip(),
                str(payload.get("steps") or "").strip(),
                str(payload.get("notes") or "").strip(),
                int(actor_user_id),
                int(actor_user_id),
                now,
                now,
            ),
        )
        content_id = int(cursor.lastrowid)
        self._replace_aliases_positions(content_id, payload)
        self._replace_exercise_spec(content_id, payload)
        self._replace_placements(
            content_id,
            int(team_id),
            payload.get("placements") or (),
        )
        self._store_revision(content_id, revision_number=1, actor_user_id=actor_user_id, change_note="Criação")
        result = self.content_detail(content_id, team_ids=[team_id])
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.content.create",
            entity="playbook_content",
            target_id=content_id,
            after=result,
        )
        return result

    def update_content(
        self,
        content_id: int,
        payload: Mapping[str, Any],
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
        change_note: str = "",
    ) -> dict[str, Any]:
        self._require_available()
        before = self.content_detail(content_id, team_ids=team_ids)
        if before["status"] == "ARCHIVED":
            raise ValueError("Restaure o conteúdo antes de editá-lo.")
        title = str(payload.get("title") or "").strip()
        if not title or len(title) > 220:
            raise ValueError("Informe um título entre 1 e 220 caracteres.")
        perspective = payload.get("perspective")
        if perspective is not None:
            perspective = str(perspective).upper()
            if perspective not in {"ATTACK", "DEFENSE", "NEUTRAL"}:
                raise ValueError("Perspectiva tática inválida.")
        next_revision = int(before["current_revision"]) + 1
        now = _now_iso()
        self.connection.execute(
            """UPDATE playbook_contents
               SET title=?,content_kind=?,perspective=?,objective=?,when_to_use=?,
                   prerequisites=?,steps=?,notes=?,current_revision=?,
                   updated_by_user_id=?,updated_at=? WHERE id=?""",
            (
                title,
                str(payload.get("content_kind") or "CONTENT").strip()[:80] or "CONTENT",
                perspective,
                str(payload.get("objective") or "").strip(),
                str(payload.get("when_to_use") or "").strip(),
                str(payload.get("prerequisites") or "").strip(),
                str(payload.get("steps") or "").strip(),
                str(payload.get("notes") or "").strip(),
                next_revision,
                int(actor_user_id),
                now,
                int(content_id),
            ),
        )
        self._replace_aliases_positions(content_id, payload)
        self._replace_exercise_spec(content_id, payload)
        self._replace_placements(content_id, int(before["team_id"]), payload.get("placements") or ())
        self._store_revision(
            content_id,
            revision_number=next_revision,
            actor_user_id=actor_user_id,
            change_note=change_note or "Edição",
        )
        after = self.content_detail(content_id, team_ids=team_ids)
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.content.update",
            entity="playbook_content",
            target_id=content_id,
            before=before,
            after=after,
        )
        return after

    def move_contents(
        self,
        content_ids: Iterable[int],
        *,
        folder_id: int,
        operation: str,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> list[dict[str, Any]]:
        """Move vários conteúdos ou cria atalhos, sem duplicar o material.

        ``MOVE`` substitui apenas as localizações normais do conteúdo e mantém
        atalhos explícitos já existentes. ``SHORTCUT`` acrescenta a localização
        de atalho, com ``UPSERT`` idempotente. Em ambos os casos versões,
        favoritos, anexos e itens de planos continuam apontando para o mesmo ID.
        """

        self._require_available()
        allowed = _ids(team_ids)
        ordered = _ids(content_ids)
        if not ordered:
            raise ValueError("Selecione ao menos um conteúdo para mover.")
        if len(ordered) > 100:
            raise ValueError("Mova no máximo 100 conteúdos por vez.")
        destination = self._allowed_folder(folder_id, allowed, include_archived=False)
        desired = str(operation or "MOVE").upper()
        if desired not in {"MOVE", "SHORTCUT"}:
            raise ValueError("Tipo de movimentação inválido.")
        now = _now_iso()
        results: list[dict[str, Any]] = []
        for content_id in ordered:
            content = self._allowed_content(content_id, allowed)
            if int(content["team_id"]) != int(destination["team_id"]):
                raise ValueError("Conteúdo e pasta de destino devem pertencer à mesma equipe.")
            before = self.content_detail(content_id, team_ids=allowed)
            if desired == "MOVE":
                self.connection.execute(
                    "DELETE FROM playbook_content_folders "
                    "WHERE content_id=? AND placement_kind='PLACEMENT'",
                    (content_id,),
                )
                existing = self.connection.execute(
                    "SELECT placement_kind FROM playbook_content_folders "
                    "WHERE content_id=? AND folder_id=?",
                    (content_id, int(folder_id)),
                ).fetchone()
                if existing is None:
                    self.connection.execute(
                        """INSERT INTO playbook_content_folders(
                               content_id,folder_id,placement_kind,sort_order,created_at
                           ) VALUES(?,?, 'PLACEMENT', ?, ?)""",
                        (
                            content_id,
                            int(folder_id),
                            self.connection.execute(
                                "SELECT COALESCE(MAX(sort_order),-1)+1 "
                                "FROM playbook_content_folders WHERE folder_id=?",
                                (int(folder_id),),
                            ).fetchone()[0],
                            now,
                        ),
                    )
                elif str(existing["placement_kind"]) == "SHORTCUT":
                    self.connection.execute(
                        "UPDATE playbook_content_folders SET placement_kind='PLACEMENT',sort_order=? "
                        "WHERE content_id=? AND folder_id=?",
                        (
                            self.connection.execute(
                                "SELECT COALESCE(MAX(sort_order),-1)+1 "
                                "FROM playbook_content_folders WHERE folder_id=?",
                                (int(folder_id),),
                            ).fetchone()[0],
                            content_id,
                            int(folder_id),
                        ),
                    )
            else:
                existing = self.connection.execute(
                    "SELECT placement_kind FROM playbook_content_folders "
                    "WHERE content_id=? AND folder_id=?",
                    (content_id, int(folder_id)),
                ).fetchone()
                if existing is None:
                    self.connection.execute(
                        """INSERT INTO playbook_content_folders(
                               content_id,folder_id,placement_kind,sort_order,created_at
                           ) VALUES(?,?, 'SHORTCUT', ?, ?)""",
                        (
                            content_id,
                            int(folder_id),
                            self.connection.execute(
                                "SELECT COALESCE(MAX(sort_order),-1)+1 "
                                "FROM playbook_content_folders WHERE folder_id=?",
                                (int(folder_id),),
                            ).fetchone()[0],
                            now,
                        ),
                    )
            after = self.content_detail(content_id, team_ids=allowed)
            self._audit(
                actor_user_id=actor_user_id,
                action=(
                    "playbook.content.move" if desired == "MOVE"
                    else "playbook.content.shortcut.create"
                ),
                entity="playbook_content",
                target_id=content_id,
                before={"folders": before["folders"]},
                after={"folders": after["folders"], "destination_folder_id": int(folder_id)},
            )
            results.append(after)
        return results

    def set_content_status(
        self,
        content_id: int,
        *,
        status: str,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]:
        self._require_available()
        before = self._allowed_content(content_id, team_ids)
        desired = status.upper()
        if desired not in {"PUBLISHED", "ARCHIVED", "RESTORE"}:
            raise ValueError("Estado de conteúdo inválido.")
        now = _now_iso()
        if desired == "PUBLISHED":
            if before["status"] == "ARCHIVED":
                raise ValueError("Restaure o conteúdo antes de publicá-lo.")
            values = ("PUBLISHED", now, int(actor_user_id), int(actor_user_id), now, int(content_id))
            self.connection.execute(
                """UPDATE playbook_contents SET status=?,published_at=?,published_by_user_id=?,
                           updated_by_user_id=?,updated_at=? WHERE id=?""",
                values,
            )
            action = "publish"
        elif desired == "ARCHIVED":
            values = ("ARCHIVED", now, int(actor_user_id), int(actor_user_id), now, int(content_id))
            self.connection.execute(
                """UPDATE playbook_contents SET status=?,archived_at=?,archived_by_user_id=?,
                           updated_by_user_id=?,updated_at=? WHERE id=?""",
                values,
            )
            action = "archive"
        else:
            restored_status = "PUBLISHED" if before["published_at"] is not None else "DRAFT"
            self.connection.execute(
                """UPDATE playbook_contents SET status=?,archived_at=NULL,archived_by_user_id=NULL,
                           updated_by_user_id=?,updated_at=? WHERE id=?""",
                (restored_status, int(actor_user_id), now, int(content_id)),
            )
            action = "restore"
        after = self.content_detail(content_id, team_ids=team_ids)
        self._audit(
            actor_user_id=actor_user_id,
            action=f"playbook.content.{action}",
            entity="playbook_content",
            target_id=content_id,
            before=before,
            after=after,
        )
        return after

    def list_revisions(
        self,
        content_id: int,
        *,
        team_ids: Iterable[int],
    ) -> list[dict[str, Any]]:
        self._require_available()
        self._allowed_content(content_id, team_ids)
        return [
            dict(row)
            for row in self.connection.execute(
                """SELECT id,content_id,revision_number,change_note,restored_from_revision_id,
                          created_by_user_id,created_at
                   FROM playbook_content_revisions WHERE content_id=?
                   ORDER BY revision_number DESC""",
                (int(content_id),),
            ).fetchall()
        ]

    def restore_revision(
        self,
        content_id: int,
        revision_id: int,
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]:
        self._require_available()
        content = self._allowed_content(content_id, team_ids)
        if content["status"] == "ARCHIVED":
            raise ValueError("Restaure o conteúdo antes de restaurar uma versão.")
        row = self.connection.execute(
            """SELECT id,snapshot_json FROM playbook_content_revisions
               WHERE id=? AND content_id=?""",
            (int(revision_id), int(content_id)),
        ).fetchone()
        if row is None:
            raise KeyError("Versão não encontrada para este conteúdo.")
        try:
            snapshot = json.loads(str(row["snapshot_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("O histórico desta versão está inválido.") from exc
        if not isinstance(snapshot, dict):
            raise ValueError("O histórico desta versão está inválido.")
        before = self.content_detail(content_id, team_ids=team_ids)
        next_revision = int(content["current_revision"]) + 1
        self.connection.execute(
            """UPDATE playbook_contents
               SET title=?,content_kind=?,perspective=?,objective=?,when_to_use=?,
                   prerequisites=?,steps=?,notes=?,current_revision=?,
                   updated_by_user_id=?,updated_at=? WHERE id=?""",
            (
                str(snapshot.get("title") or "").strip(),
                str(snapshot.get("content_kind") or "CONTENT").strip()[:80] or "CONTENT",
                snapshot.get("perspective"),
                str(snapshot.get("objective") or ""),
                str(snapshot.get("when_to_use") or ""),
                str(snapshot.get("prerequisites") or ""),
                str(snapshot.get("steps") or ""),
                str(snapshot.get("notes") or ""),
                next_revision,
                int(actor_user_id),
                _now_iso(),
                int(content_id),
            ),
        )
        self._replace_aliases_positions(content_id, snapshot)
        self._replace_exercise_spec(content_id, snapshot)
        # Uma pasta pode ter sido excluída definitivamente depois desta versão.
        # Restaurar o texto e as relações de um conteúdo histórico não deve
        # falhar nem ressuscitar uma pasta que já foi removida. Só repomos as
        # localizações ainda válidas; se nenhuma existir, preservamos as
        # localizações atuais (inclusive o estado explicitamente "sem pasta").
        valid_placements: list[Mapping[str, Any]] = []
        for raw in snapshot.get("folders") or ():
            try:
                folder_id = int(raw["folder_id"])
            except (KeyError, TypeError, ValueError):
                continue
            folder = self._folder(folder_id)
            if (
                folder is not None
                and int(folder["team_id"]) == int(content["team_id"])
                and folder["archived_at"] is None
            ):
                valid_placements.append(raw)
        if valid_placements:
            self._replace_placements(
                content_id,
                int(content["team_id"]),
                valid_placements,
            )
        self._store_revision(
            content_id,
            revision_number=next_revision,
            actor_user_id=actor_user_id,
            change_note=f"Restauração da versão {int(row['id'])}",
            restored_from_revision_id=int(row["id"]),
        )
        after = self.content_detail(content_id, team_ids=team_ids)
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.content.restore_revision",
            entity="playbook_content",
            target_id=content_id,
            before=before,
            after=after,
        )
        return after

    def set_relations(
        self,
        content_id: int,
        relations: Iterable[Mapping[str, Any]],
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> list[dict[str, Any]]:
        self._require_available()
        source = self._allowed_content(content_id, team_ids)
        normalized: list[tuple[int, str]] = []
        seen: set[tuple[int, str]] = set()
        for raw in relations:
            target_id = int(raw["target_content_id"])
            relation_type = str(raw["relation_type"] or "").upper()
            if target_id == int(content_id):
                raise ValueError("Um conteúdo não pode se relacionar consigo mesmo.")
            if relation_type not in {"PROPOSAL", "RESPONSE", "COUNTERRESPONSE", "VARIATION"}:
                raise ValueError("Tipo de relação inválido.")
            target = self._content(target_id)
            if target is None or int(target["team_id"]) != int(source["team_id"]):
                raise ValueError("A relação deve apontar para conteúdo da mesma equipe.")
            key = (target_id, relation_type)
            if key not in seen:
                seen.add(key)
                normalized.append(key)
        before = [
            dict(row)
            for row in self.connection.execute(
                "SELECT target_content_id,relation_type FROM playbook_content_relations WHERE source_content_id=?",
                (int(content_id),),
            ).fetchall()
        ]
        self.connection.execute(
            "DELETE FROM playbook_content_relations WHERE source_content_id=?", (int(content_id),)
        )
        now = _now_iso()
        self.connection.executemany(
            """INSERT INTO playbook_content_relations(
                   source_content_id,target_content_id,relation_type,created_by_user_id,created_at
               ) VALUES(?,?,?,?,?)""",
            [
                (int(content_id), target_id, relation_type, int(actor_user_id), now)
                for target_id, relation_type in normalized
            ],
        )
        after = [
            dict(row)
            for row in self.connection.execute(
                """SELECT r.id,r.relation_type,r.target_content_id,c.title target_title
                   FROM playbook_content_relations r
                   JOIN playbook_contents c ON c.id=r.target_content_id
                   WHERE r.source_content_id=? ORDER BY r.relation_type,c.title COLLATE NOCASE""",
                (int(content_id),),
            ).fetchall()
        ]
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.content.relations.update",
            entity="playbook_content",
            target_id=content_id,
            before=before,
            after=after,
        )
        return after

    def add_drive_attachment(
        self,
        content_id: int,
        *,
        url: str,
        label: str,
        offline_essential: bool,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]:
        self._require_available()
        self._allowed_content(content_id, team_ids)
        now = _now_iso()
        cursor = self.connection.execute(
            """INSERT INTO playbook_attachments(
                   content_id,storage_kind,label,url,storage_key,mime_type,size_bytes,
                   offline_essential,created_by_user_id,created_at
               ) VALUES(?,'DRIVE_LINK',?,?,NULL,'',NULL,?,?,?)""",
            (
                int(content_id),
                str(label or "").strip(),
                str(url).strip(),
                1 if offline_essential else 0,
                int(actor_user_id),
                now,
            ),
        )
        result = self.attachment(int(cursor.lastrowid), team_ids=team_ids)
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.attachment.add_drive_link",
            entity="playbook_attachment",
            target_id=result["id"],
            after={key: value for key, value in result.items() if key != "storage_key"},
        )
        return self._public_attachment(result)

    def add_local_attachment(
        self,
        content_id: int,
        *,
        storage_key: str,
        label: str,
        mime_type: str,
        size_bytes: int,
        offline_essential: bool,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]:
        self._require_available()
        self._allowed_content(content_id, team_ids)
        cursor = self.connection.execute(
            """INSERT INTO playbook_attachments(
                   content_id,storage_kind,label,url,storage_key,mime_type,size_bytes,
                   offline_essential,created_by_user_id,created_at
               ) VALUES(?,'LOCAL_FILE',?,NULL,?,?,?,?,?,?)""",
            (
                int(content_id),
                str(label or "").strip(),
                str(storage_key),
                str(mime_type),
                int(size_bytes),
                1 if offline_essential else 0,
                int(actor_user_id),
                _now_iso(),
            ),
        )
        result = self.attachment(int(cursor.lastrowid), team_ids=team_ids)
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.attachment.upload",
            entity="playbook_attachment",
            target_id=result["id"],
            after={key: value for key, value in result.items() if key != "storage_key"},
        )
        return self._public_attachment(result)

    @staticmethod
    def _public_attachment(item: Mapping[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in dict(item).items() if key != "storage_key"}

    def attachment(
        self,
        attachment_id: int,
        *,
        team_ids: Iterable[int],
        published_only: bool = False,
    ) -> dict[str, Any]:
        self._require_available()
        allowed = _ids(team_ids)
        if not allowed:
            raise KeyError("Anexo não encontrado.")
        published_clause = " AND c.status='PUBLISHED'" if published_only else ""
        row = self.connection.execute(
            f"""SELECT a.*,c.team_id,c.status content_status,c.title content_title
                FROM playbook_attachments a
                JOIN playbook_contents c ON c.id=a.content_id
                WHERE a.id=? AND c.team_id IN ({_placeholders(allowed)}){published_clause}""",
            (int(attachment_id), *allowed),
        ).fetchone()
        if row is None:
            raise KeyError("Anexo não encontrado na equipe autorizada.")
        return dict(row)

    def delete_attachment(
        self,
        attachment_id: int,
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]:
        self._require_available()
        before = self.attachment(attachment_id, team_ids=team_ids)
        self.connection.execute("DELETE FROM playbook_attachments WHERE id=?", (int(attachment_id),))
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.attachment.delete",
            entity="playbook_attachment",
            target_id=attachment_id,
            before={key: value for key, value in before.items() if key != "storage_key"},
        )
        return before

    def toggle_favorite(
        self,
        content_id: int,
        *,
        user_id: int,
        team_ids: Iterable[int],
        published_only: bool = False,
    ) -> bool:
        self._require_available()
        self._allowed_content(content_id, team_ids, published_only=published_only)
        present = self.connection.execute(
            "SELECT 1 FROM playbook_favorites WHERE user_id=? AND content_id=?",
            (int(user_id), int(content_id)),
        ).fetchone()
        if present:
            self.connection.execute(
                "DELETE FROM playbook_favorites WHERE user_id=? AND content_id=?",
                (int(user_id), int(content_id)),
            )
            return False
        self.connection.execute(
            "INSERT INTO playbook_favorites(user_id,content_id,created_at) VALUES(?,?,?)",
            (int(user_id), int(content_id), _now_iso()),
        )
        return True

    def mark_recent_view(
        self,
        content_id: int,
        *,
        user_id: int,
        team_ids: Iterable[int],
        published_only: bool = False,
    ) -> None:
        self._require_available()
        self._allowed_content(content_id, team_ids, published_only=published_only)
        self.connection.execute(
            """INSERT INTO playbook_recent_views(user_id,content_id,last_viewed_at,view_count)
               VALUES(?,?,?,1)
               ON CONFLICT(user_id,content_id) DO UPDATE SET
                   last_viewed_at=excluded.last_viewed_at,
                   view_count=playbook_recent_views.view_count+1""",
            (int(user_id), int(content_id), _now_iso()),
        )

    def user_collections(
        self,
        *,
        user_id: int,
        team_ids: Iterable[int],
        published_only: bool,
    ) -> dict[str, list[dict[str, Any]]]:
        self._require_available()
        allowed = _ids(team_ids)
        if not allowed:
            return {"favorites": [], "recent": [], "frequent": []}
        published_clause = " AND c.status='PUBLISHED'" if published_only else " AND c.status<>'ARCHIVED'"
        base = f"c.team_id IN ({_placeholders(allowed)}){published_clause}"
        favorites = self.connection.execute(
            f"""SELECT c.id,c.title,c.status,c.perspective,c.updated_at
                FROM playbook_favorites f JOIN playbook_contents c ON c.id=f.content_id
                WHERE f.user_id=? AND {base}
                ORDER BY f.created_at DESC LIMIT 12""",
            (int(user_id), *allowed),
        ).fetchall()
        recent = self.connection.execute(
            f"""SELECT c.id,c.title,c.status,c.perspective,r.last_viewed_at,r.view_count
                FROM playbook_recent_views r JOIN playbook_contents c ON c.id=r.content_id
                WHERE r.user_id=? AND {base}
                ORDER BY r.last_viewed_at DESC LIMIT 12""",
            (int(user_id), *allowed),
        ).fetchall()
        frequent = self.connection.execute(
            f"""SELECT c.id,c.title,c.status,c.perspective,SUM(r.view_count) use_count,
                       MAX(r.last_viewed_at) last_viewed_at
                FROM playbook_recent_views r
                JOIN playbook_contents c ON c.id=r.content_id
                WHERE {base}
                GROUP BY c.id
                ORDER BY use_count DESC,last_viewed_at DESC,c.title COLLATE NOCASE
                LIMIT 12""",
            allowed,
        ).fetchall()
        return {
            "favorites": [dict(row) for row in favorites],
            "recent": [dict(row) for row in recent],
            "frequent": [dict(row) for row in frequent],
        }

    def hard_delete_content(
        self,
        content_id: int,
        *,
        confirmation: str,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]:
        self._require_available()
        expected = f"EXCLUIR CONTEÚDO {int(content_id)}"
        if str(confirmation or "").strip() != expected:
            raise ValueError(f"Para excluir definitivamente, digite exatamente: {expected}")
        content = self._allowed_content(content_id, team_ids)
        if content["status"] != "ARCHIVED":
            raise ValueError("Archive o conteúdo antes da exclusão definitiva para ter uma etapa reversível.")
        plan_rows = self.connection.execute(
            """SELECT DISTINCT e.id,e.starts_at,e.title
               FROM playbook_training_plan_items i
               JOIN playbook_sessions ps ON ps.plan_id=i.plan_id
               JOIN playbook_session_event_links l ON l.session_id=ps.id
               JOIN calendar_events e ON e.id=l.calendar_event_id
               WHERE i.content_id=?""",
            (int(content_id),),
        ).fetchall()
        if plan_rows:
            raise ValueError(
                "O conteúdo está vinculado a planos de treino; remova-o dos planos "
                "antes de excluí-lo definitivamente."
            )
        evaluation_rows = self.connection.execute(
            """SELECT DISTINCT e.id,e.starts_at,e.title
               FROM playbook_session_evaluations v
               JOIN calendar_events e ON e.id=v.calendar_event_id
               WHERE v.content_id=? ORDER BY e.starts_at,e.id""",
            (int(content_id),),
        ).fetchall()
        if evaluation_rows:
            raise ValueError(
                "O conteúdo possui avaliações pós-treino registradas; mantenha-o "
                "arquivado para preservar o histórico esportivo."
            )
        attachments = [
            self.attachment(int(row[0]), team_ids=team_ids)
            for row in self.connection.execute(
                "SELECT id FROM playbook_attachments WHERE content_id=?", (int(content_id),)
            ).fetchall()
        ]
        impact = {
            "content": self.content_detail(content_id, team_ids=team_ids),
            "linked_plan_events": [dict(row) for row in plan_rows],
            "evaluation_events": [dict(row) for row in evaluation_rows],
            "attachment_count": len(attachments),
        }
        self.connection.execute("DELETE FROM playbook_contents WHERE id=?", (int(content_id),))
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.content.delete_permanent",
            entity="playbook_content",
            target_id=content_id,
            before=impact,
            after={"deleted": True},
        )
        return {"deleted": True, "content_id": int(content_id), "attachments": attachments, "impact": impact}

    # ------------------------------------------------------------------
    # Plano ligado ao evento do Calendário, sem copiar eventos ou chamadas
    # ------------------------------------------------------------------
    def _event(self, event_id: int, team_ids: Iterable[int]) -> dict[str, Any]:
        allowed = _ids(team_ids)
        if not allowed:
            raise KeyError("Evento não encontrado.")
        row = self.connection.execute(
            f"""SELECT e.id,e.team_id,e.season_id,e.event_type,e.status,e.title,e.starts_at,
                       e.ends_at,e.attendance_session_id,e.notes,e.version,s.label season_label
                FROM calendar_events e
                JOIN seasons s ON s.id=e.season_id AND s.team_id=e.team_id
                WHERE e.id=? AND e.team_id IN ({_placeholders(allowed)})""",
            (int(event_id), *allowed),
        ).fetchone()
        if row is None:
            raise KeyError("Evento não encontrado na equipe autorizada.")
        return dict(row)

    def _assert_training_event(self, event_id: int, team_ids: Iterable[int]) -> dict[str, Any]:
        event = self._event(event_id, team_ids)
        if event["event_type"] != "TRAINING":
            raise ValueError("O plano do Playbook só pode ser ligado a um treino do Calendário.")
        if event["status"] in {"CANCELLED", "RESCHEDULED"}:
            raise ValueError("Treino cancelado ou remarcado não aceita plano ativo.")
        return event

    def _plan(self, event_id: int) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM playbook_training_plans WHERE calendar_event_id=?", (int(event_id),)
        ).fetchone()
        return dict(row) if row is not None else None

    def _attendance_summary(self, event: Mapping[str, Any]) -> dict[str, Any] | None:
        session_id = event.get("attendance_session_id")
        if session_id is None:
            return None
        rows = self.connection.execute(
            """SELECT ar.member_id,ar.confirmation_status,tm.position,
                      arp.position selected_position
               FROM attendance_records ar
               JOIN team_members tm ON tm.id=ar.member_id
               LEFT JOIN attendance_record_positions arp ON arp.attendance_record_id=ar.id
               WHERE ar.session_id=? ORDER BY ar.member_id,arp.ordinal""",
            (int(session_id),),
        ).fetchall()
        members: dict[int, dict[str, Any]] = {}
        for row in rows:
            member_id = int(row["member_id"])
            item = members.setdefault(
                member_id,
                {
                    "confirmation_status": str(row["confirmation_status"]),
                    "positions": [],
                    "fallback_position": str(row["position"]),
                },
            )
            if row["selected_position"] is not None:
                item["positions"].append(str(row["selected_position"]))
        summary = {"confirmed": 0, "absent": 0, "pending": 0, "positions": {}}
        for item in members.values():
            status = item["confirmation_status"]
            group = "confirmed" if status.startswith("CONFIRMED") else "absent" if status.startswith("CANCELLED") else "pending"
            summary[group] += 1
            if group == "confirmed":
                positions = item["positions"] or [part.strip() for part in item["fallback_position"].replace(",", "/").split("/") if part.strip()]
                for position in positions:
                    summary["positions"][position] = summary["positions"].get(position, 0) + 1
        return summary

    def plan_for_event(
        self,
        event_id: int,
        *,
        team_ids: Iterable[int],
        published_only: bool = False,
    ) -> dict[str, Any]:
        self._require_available()
        event = self._assert_training_event(event_id, team_ids)
        plan = self._plan(event_id)
        result: dict[str, Any] = {
            "event": event,
            "plan": plan,
            "items": [],
            "availability": self._attendance_summary(event),
            "transfers": [],
            "evaluations": [],
        }
        if plan is not None:
            filter_clause = " AND c.status='PUBLISHED'" if published_only else ""
            rows = self.connection.execute(
                f"""SELECT i.id,i.content_id,i.sort_order,i.planned_minutes,i.notes,
                           c.title,c.status,c.perspective,c.objective,c.steps
                    FROM playbook_training_plan_items i
                    JOIN playbook_contents c ON c.id=i.content_id
                    WHERE i.plan_id=?{filter_clause}
                    ORDER BY i.sort_order,i.id""",
                (int(plan["id"]),),
            ).fetchall()
            result["items"] = [dict(row) for row in rows]
        result["transfers"] = [
            dict(row)
            for row in self.connection.execute(
                """SELECT id,plan_id,from_event_id,to_event_id,reason,actor_user_id,transferred_at
                   FROM playbook_plan_transfers
                   WHERE from_event_id=? OR to_event_id=? ORDER BY transferred_at DESC,id DESC""",
                (int(event_id), int(event_id)),
            ).fetchall()
        ]
        result["evaluations"] = [
            dict(row)
            for row in self.connection.execute(
                """SELECT e.content_id,e.mastery_stage,e.continuity_decision,e.notes,
                          e.evaluated_at,c.title
                   FROM playbook_plan_evaluations e
                   JOIN playbook_contents c ON c.id=e.content_id
                   WHERE e.calendar_event_id=? ORDER BY c.title COLLATE NOCASE""",
                (int(event_id),),
            ).fetchall()
        ]
        return result

    def next_training_event_id(self, team_ids: Iterable[int]) -> int | None:
        self._require_available()
        allowed = _ids(team_ids)
        if not allowed:
            return None
        now = _now_iso()
        row = self.connection.execute(
            f"""SELECT id FROM calendar_events
                WHERE team_id IN ({_placeholders(allowed)})
                  AND event_type='TRAINING'
                  AND status IN('PLANNED','CONFIRMED')
                  AND ends_at>=?
                ORDER BY starts_at,id LIMIT 1""",
            (*allowed, now),
        ).fetchone()
        return int(row[0]) if row is not None else None

    def offline_essential_attachments(
        self,
        *,
        team_ids: Iterable[int],
        published_only: bool,
    ) -> list[dict[str, Any]]:
        self._require_available()
        allowed = _ids(team_ids)
        if not allowed:
            return []
        published_clause = " AND c.status='PUBLISHED'" if published_only else ""
        rows = self.connection.execute(
            f"""SELECT a.id,a.content_id,a.storage_kind,a.label,a.url,a.mime_type,
                       a.size_bytes,a.offline_essential,c.title content_title
                FROM playbook_attachments a
                JOIN playbook_contents c ON c.id=a.content_id
                WHERE c.team_id IN ({_placeholders(allowed)})
                  AND a.offline_essential=1{published_clause}
                ORDER BY c.title COLLATE NOCASE,a.id""",
            allowed,
        ).fetchall()
        return [dict(row) for row in rows]

    def save_plan(
        self,
        event_id: int,
        payload: Mapping[str, Any],
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]:
        self._require_available()
        event = self._assert_training_event(event_id, team_ids)
        before = self.plan_for_event(event_id, team_ids=team_ids)
        raw_items = list(payload.get("items") or ())
        normalized: list[dict[str, Any]] = []
        seen: set[int] = set()
        for ordinal, raw in enumerate(raw_items):
            content_id = int(raw["content_id"])
            if content_id in seen:
                raise ValueError("Um conteúdo só pode aparecer uma vez no plano.")
            content = self._allowed_content(content_id, [int(event["team_id"])])
            if content["status"] == "ARCHIVED":
                raise ValueError("Conteúdo arquivado não pode entrar no plano.")
            minutes = raw.get("planned_minutes")
            if minutes is not None and int(minutes) <= 0:
                raise ValueError("A duração planejada deve ser positiva.")
            seen.add(content_id)
            normalized.append(
                {
                    "content_id": content_id,
                    "sort_order": int(raw.get("sort_order", ordinal)),
                    "planned_minutes": int(minutes) if minutes is not None else None,
                    "notes": str(raw.get("notes") or "").strip()[:2000],
                }
            )
        plan = self._plan(event_id)
        now = _now_iso()
        if plan is None:
            cursor = self.connection.execute(
                """INSERT INTO playbook_training_plans(
                       calendar_event_id,team_id,title,seasonal_objective,
                       context_adjustment,notes,created_by_user_id,
                       updated_by_user_id,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    int(event_id),
                    int(event["team_id"]),
                    str(payload.get("title") or "").strip()[:180],
                    str(payload.get("seasonal_objective") or "").strip()[:2000],
                    str(payload.get("context_adjustment") or "").strip()[:2000],
                    str(payload.get("notes") or "").strip()[:4000],
                    int(actor_user_id),
                    int(actor_user_id),
                    now,
                    now,
                ),
            )
            plan_id = int(cursor.lastrowid)
        else:
            plan_id = int(plan["id"])
            self.connection.execute(
                """UPDATE playbook_training_plans
                   SET title=?,seasonal_objective=?,context_adjustment=?,notes=?,
                       updated_by_user_id=?,updated_at=?
                   WHERE id=?""",
                (
                    str(payload.get("title") or "").strip()[:180],
                    str(payload.get("seasonal_objective") or "").strip()[:2000],
                    str(payload.get("context_adjustment") or "").strip()[:2000],
                    str(payload.get("notes") or "").strip()[:4000],
                    int(actor_user_id),
                    now,
                    plan_id,
                ),
            )
            self.connection.execute(
                "DELETE FROM playbook_training_plan_items WHERE plan_id=?", (plan_id,)
            )
        self.connection.executemany(
            """INSERT INTO playbook_training_plan_items(
                   plan_id,content_id,sort_order,planned_minutes,notes,created_at
               ) VALUES(?,?,?,?,?,?)""",
            [
                (
                    plan_id,
                    item["content_id"],
                    item["sort_order"],
                    item["planned_minutes"],
                    item["notes"],
                    now,
                )
                for item in normalized
            ],
        )
        after = self.plan_for_event(event_id, team_ids=team_ids)
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.plan.save",
            entity="playbook_training_plan",
            target_id=plan_id,
            before=before,
            after=after,
        )
        return after

    def reuse_plan(
        self,
        event_id: int,
        *,
        source_event_id: int,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]:
        self._require_available()
        if int(event_id) == int(source_event_id):
            raise ValueError("Escolha outro treino como origem do plano.")
        self._assert_training_event(event_id, team_ids)
        source = self.plan_for_event(source_event_id, team_ids=team_ids)
        if source["plan"] is None:
            raise ValueError("O treino de origem ainda não possui plano para reutilizar.")
        saved = self.save_plan(
            event_id,
            {
                "title": source["plan"]["title"],
                "seasonal_objective": source["plan"]["seasonal_objective"],
                "context_adjustment": source["plan"]["context_adjustment"],
                "notes": source["plan"]["notes"],
                "items": [
                    {
                        "content_id": item["content_id"],
                        "sort_order": item["sort_order"],
                        "planned_minutes": item["planned_minutes"],
                        "notes": item["notes"],
                    }
                    for item in source["items"]
                ],
            },
            team_ids=team_ids,
            actor_user_id=actor_user_id,
        )
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.plan.reuse",
            entity="playbook_training_plan",
            target_id=saved["plan"]["id"] if saved["plan"] else None,
            after={"source_event_id": int(source_event_id), "target_event_id": int(event_id)},
        )
        return saved

    def transfer_plan_for_reschedule(
        self,
        source_event_id: int,
        replacement_event_id: int,
        *,
        actor_user_id: int,
        reason: str,
    ) -> dict[str, Any] | None:
        """Move o vínculo do plano na transação que remarca o evento."""
        if not self.is_available():
            return None
        plan = self._plan(source_event_id)
        if plan is None:
            return None
        existing_target = self._plan(replacement_event_id)
        if existing_target is not None:
            raise RuntimeError("O evento substituto já possui um plano de treino.")
        self.connection.execute(
            """UPDATE playbook_training_plans
               SET calendar_event_id=?,updated_by_user_id=?,updated_at=? WHERE id=?""",
            (int(replacement_event_id), int(actor_user_id), _now_iso(), int(plan["id"])),
        )
        self.connection.execute(
            """INSERT INTO playbook_plan_transfers(
                   plan_id,from_event_id,to_event_id,reason,actor_user_id,transferred_at
               ) VALUES(?,?,?,?,?,?)""",
            (
                int(plan["id"]),
                int(source_event_id),
                int(replacement_event_id),
                str(reason or "").strip(),
                int(actor_user_id),
                _now_iso(),
            ),
        )
        result = {
            "plan_id": int(plan["id"]),
            "from_event_id": int(source_event_id),
            "to_event_id": int(replacement_event_id),
        }
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.plan.transfer_on_reschedule",
            entity="playbook_training_plan",
            target_id=plan["id"],
            before={"calendar_event_id": int(source_event_id)},
            after=result,
        )
        return result

    def record_evaluations(
        self,
        event_id: int,
        evaluations: Iterable[Mapping[str, Any]],
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> list[dict[str, Any]]:
        self._require_available()
        self._assert_training_event(event_id, team_ids)
        plan = self._plan(event_id)
        planned_content_ids = {
            int(row[0])
            for row in self.connection.execute(
                "SELECT content_id FROM playbook_training_plan_items WHERE plan_id=?",
                (int(plan["id"]),),
            ).fetchall()
        } if plan is not None else set()
        normalized: list[tuple[int, str, str, str]] = []
        seen: set[int] = set()
        for raw in evaluations:
            content_id = int(raw["content_id"])
            if content_id not in planned_content_ids:
                raise ValueError("Só é possível avaliar conteúdos que fazem parte deste plano.")
            if content_id in seen:
                raise ValueError("Cada conteúdo deve ter uma única avaliação final.")
            stage = str(raw["mastery_stage"] or "").upper()
            decision = str(raw["continuity_decision"] or "").upper()
            if stage not in {"STARTING", "IMPROVING", "REFINING", "CONSOLIDATED"}:
                raise ValueError("Estágio de domínio inválido.")
            if decision not in {"CONTINUE", "COMPLETE", "REVIEW"}:
                raise ValueError("Decisão de continuidade inválida.")
            seen.add(content_id)
            normalized.append((content_id, stage, decision, str(raw.get("notes") or "").strip()[:2000]))
        now = _now_iso()
        for content_id, stage, decision, notes in normalized:
            self.connection.execute(
                """INSERT INTO playbook_plan_evaluations(
                       calendar_event_id,content_id,mastery_stage,continuity_decision,
                       notes,actor_user_id,evaluated_at
                   ) VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(calendar_event_id,content_id) DO UPDATE SET
                       mastery_stage=excluded.mastery_stage,
                       continuity_decision=excluded.continuity_decision,
                       notes=excluded.notes,actor_user_id=excluded.actor_user_id,
                       evaluated_at=excluded.evaluated_at""",
                (int(event_id), content_id, stage, decision, notes, int(actor_user_id), now),
            )
        result = [
            dict(row)
            for row in self.connection.execute(
                """SELECT content_id,mastery_stage,continuity_decision,notes,evaluated_at
                   FROM playbook_plan_evaluations WHERE calendar_event_id=?
                   ORDER BY content_id""",
                (int(event_id),),
            ).fetchall()
        ]
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.plan.evaluate",
            entity="calendar_event",
            target_id=event_id,
            after={"evaluations": result},
        )
        return result

    # ------------------------------------------------------------------
    # PB-3B / V10: plano independente, série e sessão com vínculo opcional
    # ------------------------------------------------------------------
    def _v10_event(
        self,
        event_id: int,
        team_ids: Iterable[int],
        *,
        player_visible_only: bool = False,
    ) -> dict[str, Any]:
        allowed = _ids(team_ids)
        if not allowed:
            raise KeyError("Evento não encontrado.")
        visibility_clause = " AND e.is_player_visible=1" if player_visible_only else ""
        row = self.connection.execute(
            f"""SELECT e.id,e.team_id,e.season_id,e.event_type,e.status,e.title,e.starts_at,
                       e.ends_at,e.attendance_session_id,e.notes,e.version,e.is_player_visible,
                       s.label season_label
                FROM calendar_events e
                JOIN seasons s ON s.id=e.season_id AND s.team_id=e.team_id
                WHERE e.id=? AND e.team_id IN ({_placeholders(allowed)}){visibility_clause}""",
            (int(event_id), *allowed),
        ).fetchone()
        if row is None:
            raise KeyError("Evento não encontrado na equipe autorizada.")
        return dict(row)

    def _v10_assert_training_event(
        self,
        event_id: int,
        team_ids: Iterable[int],
        *,
        player_visible_only: bool = False,
    ) -> dict[str, Any]:
        event = self._v10_event(
            event_id,
            team_ids,
            player_visible_only=player_visible_only,
        )
        if event["event_type"] != "TRAINING":
            raise ValueError("A sessão do Playbook só pode ser ligada a um treino do Calendário.")
        if event["status"] in {"CANCELLED", "RESCHEDULED"}:
            raise ValueError("Treino cancelado ou remarcado não aceita vínculo ativo.")
        return event

    @staticmethod
    def _v10_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _v10_decode(value: object, *, fallback: Any) -> Any:
        try:
            return json.loads(str(value or ""))
        except (TypeError, ValueError):
            return fallback

    def _v10_plan(self, plan_id: int, team_ids: Iterable[int]) -> dict[str, Any]:
        allowed = _ids(team_ids)
        if not allowed:
            raise KeyError("Plano não encontrado.")
        row = self.connection.execute(
            f"""SELECT * FROM playbook_training_plans
                WHERE id=? AND team_id IN ({_placeholders(allowed)})""",
            (int(plan_id), *allowed),
        ).fetchone()
        if row is None:
            raise KeyError("Plano não encontrado na equipe autorizada.")
        return dict(row)

    def _v10_session(
        self,
        session_id: int,
        team_ids: Iterable[int],
        *,
        player_visible_only: bool = False,
    ) -> dict[str, Any]:
        allowed = _ids(team_ids)
        if not allowed:
            raise KeyError("Sessão não encontrada.")
        player_clause = """
            AND EXISTS(
                SELECT 1 FROM playbook_session_event_links vl
                JOIN calendar_events ve ON ve.id=vl.calendar_event_id
                WHERE vl.session_id=ps.id AND vl.link_state='ACTIVE'
                  AND ve.is_player_visible=1
                  AND ve.event_type='TRAINING'
                  AND ve.status IN('PLANNED','CONFIRMED')
                  AND ve.ends_at>=?
            )
        """ if player_visible_only else ""
        params: tuple[object, ...] = (int(session_id), *allowed)
        if player_visible_only:
            params = (*params, _now_iso())
        row = self.connection.execute(
            f"""SELECT ps.*,p.title plan_title,p.status plan_status,
                       sr.title series_title
                FROM playbook_sessions ps
                JOIN playbook_training_plans p ON p.id=ps.plan_id
                LEFT JOIN playbook_series sr ON sr.id=ps.series_id
                WHERE ps.id=? AND ps.team_id IN ({_placeholders(allowed)})
                  {player_clause}""",
            params,
        ).fetchone()
        if row is None:
            raise KeyError("Sessão não encontrada na equipe autorizada.")
        return dict(row)

    def _v10_plan_items(
        self,
        plan_id: int,
        *,
        published_only: bool = False,
    ) -> list[dict[str, Any]]:
        filter_clause = " AND c.status='PUBLISHED'" if published_only else ""
        rows = self.connection.execute(
            f"""SELECT i.id,i.plan_id,i.content_id,i.sort_order,i.planned_minutes,i.notes,
                       i.created_at,i.updated_at,c.title,c.status,c.perspective,
                       c.objective,c.steps
                FROM playbook_training_plan_items i
                JOIN playbook_contents c ON c.id=i.content_id
                WHERE i.plan_id=?{filter_clause}
                ORDER BY i.sort_order,i.id""",
            (int(plan_id),),
        ).fetchall()
        return [dict(row) for row in rows]

    def _v10_plan_snapshot(self, plan_id: int) -> dict[str, Any]:
        row = self.connection.execute(
            """SELECT team_id,title,seasonal_objective,context_adjustment,notes,status
               FROM playbook_training_plans WHERE id=?""",
            (int(plan_id),),
        ).fetchone()
        if row is None:
            raise KeyError("Plano não encontrado.")
        return {
            "plan": dict(row),
            "items": [
                {
                    "content_id": int(item["content_id"]),
                    "sort_order": int(item["sort_order"]),
                    "planned_minutes": item["planned_minutes"],
                    "notes": str(item["notes"]),
                }
                for item in self._v10_plan_items(plan_id)
            ],
        }

    def _v10_session_links(self, session_id: int) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT l.*,e.team_id,e.event_type,e.status event_status,e.title event_title,
                      e.starts_at event_starts_at,e.ends_at event_ends_at,
                      e.is_player_visible
               FROM playbook_session_event_links l
               JOIN calendar_events e ON e.id=l.calendar_event_id
               WHERE l.session_id=?
               ORDER BY CASE l.link_state WHEN 'ACTIVE' THEN 0 ELSE 1 END,
                        l.link_order,l.id""",
            (int(session_id),),
        ).fetchall()
        return [dict(row) for row in rows]

    def _v10_session_snapshot(self, session_id: int) -> dict[str, Any]:
        row = self.connection.execute(
            """SELECT team_id,plan_id,series_id,title_override,starts_at,ends_at,
                      local_overrides_json,execution_status,execution_notes
               FROM playbook_sessions WHERE id=?""",
            (int(session_id),),
        ).fetchone()
        if row is None:
            raise KeyError("Sessão não encontrada.")
        snapshot = dict(row)
        snapshot["local_overrides"] = self._v10_decode(
            snapshot.pop("local_overrides_json"), fallback={}
        )
        snapshot["event_links"] = self._v10_session_links(session_id)
        return snapshot

    def _v10_write_plan_revision(
        self,
        plan_id: int,
        *,
        actor_user_id: int,
        change_summary: str,
        restored_from_revision_id: int | None = None,
    ) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(MAX(revision_number),0)+1 FROM playbook_training_plan_revisions WHERE plan_id=?",
            (int(plan_id),),
        ).fetchone()
        revision_number = int(row[0])
        cursor = self.connection.execute(
            """INSERT INTO playbook_training_plan_revisions(
                   plan_id,revision_number,snapshot_json,change_summary,
                   restored_from_revision_id,created_by_user_id,created_at
               ) VALUES(?,?,?,?,?,?,?)""",
            (
                int(plan_id),
                revision_number,
                self._v10_json(self._v10_plan_snapshot(plan_id)),
                str(change_summary or "").strip()[:500],
                int(restored_from_revision_id) if restored_from_revision_id else None,
                int(actor_user_id),
                _now_iso(),
            ),
        )
        self.connection.execute(
            "UPDATE playbook_training_plans SET current_revision=? WHERE id=?",
            (revision_number, int(plan_id)),
        )
        return int(cursor.lastrowid)

    def _v10_write_session_revision(
        self,
        session_id: int,
        *,
        actor_user_id: int,
        change_summary: str,
        restored_from_revision_id: int | None = None,
    ) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(MAX(revision_number),0)+1 FROM playbook_session_revisions WHERE session_id=?",
            (int(session_id),),
        ).fetchone()
        revision_number = int(row[0])
        cursor = self.connection.execute(
            """INSERT INTO playbook_session_revisions(
                   session_id,revision_number,snapshot_json,change_summary,
                   restored_from_revision_id,created_by_user_id,created_at
               ) VALUES(?,?,?,?,?,?,?)""",
            (
                int(session_id),
                revision_number,
                self._v10_json(self._v10_session_snapshot(session_id)),
                str(change_summary or "").strip()[:500],
                int(restored_from_revision_id) if restored_from_revision_id else None,
                int(actor_user_id),
                _now_iso(),
            ),
        )
        self.connection.execute(
            "UPDATE playbook_sessions SET current_revision=? WHERE id=?",
            (revision_number, int(session_id)),
        )
        return int(cursor.lastrowid)

    def _v10_normalize_plan_payload(
        self,
        payload: Mapping[str, Any],
        *,
        team_id: int,
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        seen: set[int] = set()
        for ordinal, raw in enumerate(list(payload.get("items") or ())):
            content_id = int(raw["content_id"])
            if content_id in seen:
                raise ValueError("Um conteúdo só pode aparecer uma vez no plano.")
            content = self._allowed_content(content_id, [int(team_id)])
            if content["status"] == "ARCHIVED":
                raise ValueError("Conteúdo arquivado não pode entrar no plano.")
            minutes = raw.get("planned_minutes")
            if minutes is not None and int(minutes) <= 0:
                raise ValueError("A duração planejada deve ser positiva.")
            seen.add(content_id)
            normalized.append(
                {
                    "content_id": content_id,
                    "sort_order": int(raw.get("sort_order", ordinal)),
                    "planned_minutes": int(minutes) if minutes is not None else None,
                    "notes": str(raw.get("notes") or "").strip()[:2000],
                }
            )
        return normalized

    def list_plans(
        self,
        *,
        team_ids: Iterable[int],
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        self._require_available()
        allowed = _ids(team_ids)
        if not allowed:
            return []
        archived_clause = "" if include_archived else " AND p.status='ACTIVE'"
        rows = self.connection.execute(
            f"""SELECT p.*,COUNT(DISTINCT i.id) item_count,COUNT(DISTINCT ps.id) session_count
                FROM playbook_training_plans p
                LEFT JOIN playbook_training_plan_items i ON i.plan_id=p.id
                LEFT JOIN playbook_sessions ps ON ps.plan_id=p.id
                WHERE p.team_id IN ({_placeholders(allowed)}){archived_clause}
                GROUP BY p.id
                ORDER BY p.updated_at DESC,p.id DESC""",
            allowed,
        ).fetchall()
        return [dict(row) for row in rows]

    def plan_detail(
        self,
        plan_id: int,
        *,
        team_ids: Iterable[int],
        published_only: bool = False,
    ) -> dict[str, Any]:
        self._require_available()
        plan = self._v10_plan(plan_id, team_ids)
        revisions = [
            dict(row)
            for row in self.connection.execute(
                """SELECT id,revision_number,change_summary,restored_from_revision_id,
                          created_by_user_id,created_at
                   FROM playbook_training_plan_revisions WHERE plan_id=?
                   ORDER BY revision_number DESC""",
                (int(plan_id),),
            ).fetchall()
        ]
        return {
            "plan": plan,
            "items": self._v10_plan_items(plan_id, published_only=published_only),
            "revisions": revisions,
        }

    def save_independent_plan(
        self,
        payload: Mapping[str, Any],
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
        plan_id: int | None = None,
    ) -> dict[str, Any]:
        self._require_available()
        requested_team_id = int(payload.get("team_id") or 0)
        if plan_id is None:
            if requested_team_id not in _ids(team_ids):
                raise PermissionError("A equipe escolhida está fora do escopo autorizado.")
            self._assert_team_exists(requested_team_id)
            before = None
            now = _now_iso()
            cursor = self.connection.execute(
                """INSERT INTO playbook_training_plans(
                       team_id,title,seasonal_objective,context_adjustment,notes,status,
                       current_revision,created_by_user_id,updated_by_user_id,created_at,updated_at
                   ) VALUES(?,?,?,?,?,'ACTIVE',1,?,?,?,?)""",
                (
                    requested_team_id,
                    str(payload.get("title") or "").strip()[:180],
                    str(payload.get("seasonal_objective") or "").strip()[:2000],
                    str(payload.get("context_adjustment") or "").strip()[:2000],
                    str(payload.get("notes") or "").strip()[:4000],
                    int(actor_user_id),
                    int(actor_user_id),
                    now,
                    now,
                ),
            )
            effective_plan_id = int(cursor.lastrowid)
            team_id = requested_team_id
        else:
            existing = self._v10_plan(plan_id, team_ids)
            team_id = int(existing["team_id"])
            if requested_team_id and requested_team_id != team_id:
                raise ValueError("Um plano não pode ser movido de equipe nesta operação.")
            before = self.plan_detail(plan_id, team_ids=team_ids)
            effective_plan_id = int(plan_id)
            self.connection.execute(
                """UPDATE playbook_training_plans
                   SET title=?,seasonal_objective=?,context_adjustment=?,notes=?,
                       updated_by_user_id=?,updated_at=? WHERE id=?""",
                (
                    str(payload.get("title") or "").strip()[:180],
                    str(payload.get("seasonal_objective") or "").strip()[:2000],
                    str(payload.get("context_adjustment") or "").strip()[:2000],
                    str(payload.get("notes") or "").strip()[:4000],
                    int(actor_user_id),
                    _now_iso(),
                    effective_plan_id,
                ),
            )
            self.connection.execute(
                "DELETE FROM playbook_training_plan_items WHERE plan_id=?",
                (effective_plan_id,),
            )
        normalized = self._v10_normalize_plan_payload(payload, team_id=team_id)
        now = _now_iso()
        self.connection.executemany(
            """INSERT INTO playbook_training_plan_items(
                   plan_id,content_id,sort_order,planned_minutes,notes,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?)""",
            [
                (
                    effective_plan_id,
                    item["content_id"],
                    item["sort_order"],
                    item["planned_minutes"],
                    item["notes"],
                    now,
                    now,
                )
                for item in normalized
            ],
        )
        self._v10_write_plan_revision(
            effective_plan_id,
            actor_user_id=actor_user_id,
            change_summary=str(payload.get("change_summary") or "Alteração do plano.").strip(),
        )
        after = self.plan_detail(effective_plan_id, team_ids=team_ids)
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.plan.save_independent",
            entity="playbook_training_plan",
            target_id=effective_plan_id,
            before=before,
            after=after,
        )
        return after

    def restore_plan_revision(
        self,
        plan_id: int,
        revision_id: int,
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]:
        self._require_available()
        plan = self._v10_plan(plan_id, team_ids)
        row = self.connection.execute(
            """SELECT * FROM playbook_training_plan_revisions
               WHERE id=? AND plan_id=?""",
            (int(revision_id), int(plan_id)),
        ).fetchone()
        if row is None:
            raise KeyError("Revisão do plano não encontrada.")
        snapshot = self._v10_decode(row["snapshot_json"], fallback={})
        values = snapshot.get("plan") if isinstance(snapshot, dict) else None
        items = snapshot.get("items") if isinstance(snapshot, dict) else None
        if not isinstance(values, dict) or not isinstance(items, list):
            raise ValueError("A revisão escolhida não contém um retrato restaurável do plano.")
        before = self.plan_detail(plan_id, team_ids=team_ids)
        self.connection.execute(
            """UPDATE playbook_training_plans
               SET title=?,seasonal_objective=?,context_adjustment=?,notes=?,status=?,
                   updated_by_user_id=?,updated_at=? WHERE id=?""",
            (
                str(values.get("title") or "")[:180],
                str(values.get("seasonal_objective") or "")[:2000],
                str(values.get("context_adjustment") or "")[:2000],
                str(values.get("notes") or "")[:4000],
                str(values.get("status") or plan["status"]),
                int(actor_user_id),
                _now_iso(),
                int(plan_id),
            ),
        )
        self.connection.execute("DELETE FROM playbook_training_plan_items WHERE plan_id=?", (int(plan_id),))
        now = _now_iso()
        normalized = self._v10_normalize_plan_payload({"items": items}, team_id=int(plan["team_id"]))
        self.connection.executemany(
            """INSERT INTO playbook_training_plan_items(
                   plan_id,content_id,sort_order,planned_minutes,notes,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?)""",
            [
                (int(plan_id), item["content_id"], item["sort_order"], item["planned_minutes"], item["notes"], now, now)
                for item in normalized
            ],
        )
        self._v10_write_plan_revision(
            int(plan_id),
            actor_user_id=actor_user_id,
            change_summary=f"Restauração da revisão {int(row['revision_number'])}.",
            restored_from_revision_id=int(revision_id),
        )
        after = self.plan_detail(plan_id, team_ids=team_ids)
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.plan.restore_revision",
            entity="playbook_training_plan",
            target_id=plan_id,
            before=before,
            after=after,
        )
        return after

    def list_series(self, *, team_ids: Iterable[int], include_archived: bool = False) -> list[dict[str, Any]]:
        self._require_available()
        allowed = _ids(team_ids)
        if not allowed:
            return []
        archived_clause = "" if include_archived else " AND s.status='ACTIVE'"
        rows = self.connection.execute(
            f"""SELECT s.*,p.title plan_title,COUNT(ps.id) session_count
                FROM playbook_series s
                LEFT JOIN playbook_training_plans p ON p.id=s.plan_id
                LEFT JOIN playbook_sessions ps ON ps.series_id=s.id
                WHERE s.team_id IN ({_placeholders(allowed)}){archived_clause}
                GROUP BY s.id ORDER BY s.updated_at DESC,s.id DESC""",
            allowed,
        ).fetchall()
        return [dict(row) for row in rows]

    def save_series(
        self,
        payload: Mapping[str, Any],
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
        series_id: int | None = None,
    ) -> dict[str, Any]:
        self._require_available()
        requested_team_id = int(payload.get("team_id") or 0)
        if series_id is None:
            if requested_team_id not in _ids(team_ids):
                raise PermissionError("A equipe escolhida está fora do escopo autorizado.")
            self._assert_team_exists(requested_team_id)
            team_id = requested_team_id
        else:
            existing = self.connection.execute(
                "SELECT * FROM playbook_series WHERE id=?", (int(series_id),)
            ).fetchone()
            if existing is None or int(existing["team_id"]) not in _ids(team_ids):
                raise KeyError("Série não encontrada na equipe autorizada.")
            team_id = int(existing["team_id"])
            if requested_team_id and requested_team_id != team_id:
                raise ValueError("Uma série não pode ser movida de equipe nesta operação.")
        plan_id = payload.get("plan_id")
        if plan_id is not None:
            plan = self._v10_plan(int(plan_id), [team_id])
            if int(plan["team_id"]) != team_id:
                raise ValueError("O plano da série precisa pertencer à mesma equipe.")
        now = _now_iso()
        values = (
            int(plan_id) if plan_id is not None else None,
            str(payload.get("title") or "").strip()[:180],
            str(payload.get("recurrence_rule") or "").strip()[:500],
            payload.get("starts_on"),
            payload.get("ends_on"),
            str(payload.get("notes") or "").strip()[:4000],
            str(payload.get("status") or "ACTIVE"),
        )
        if values[-1] not in {"ACTIVE", "ARCHIVED"}:
            raise ValueError("Status de série inválido.")
        if series_id is None:
            cursor = self.connection.execute(
                """INSERT INTO playbook_series(
                       team_id,plan_id,title,recurrence_rule,starts_on,ends_on,notes,status,
                       created_by_user_id,updated_by_user_id,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (team_id, *values, int(actor_user_id), int(actor_user_id), now, now),
            )
            effective_id = int(cursor.lastrowid)
        else:
            effective_id = int(series_id)
            self.connection.execute(
                """UPDATE playbook_series
                   SET plan_id=?,title=?,recurrence_rule=?,starts_on=?,ends_on=?,notes=?,status=?,
                       updated_by_user_id=?,updated_at=? WHERE id=?""",
                (*values, int(actor_user_id), now, effective_id),
            )
        row = self.connection.execute("SELECT * FROM playbook_series WHERE id=?", (effective_id,)).fetchone()
        result = dict(row)
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.series.save",
            entity="playbook_series",
            target_id=effective_id,
            after=result,
        )
        return result

    def session_detail(
        self,
        session_id: int,
        *,
        team_ids: Iterable[int],
        published_only: bool = False,
        player_visible_only: bool = False,
    ) -> dict[str, Any]:
        self._require_available()
        session = self._v10_session(
            session_id,
            team_ids,
            player_visible_only=player_visible_only,
        )
        plan = self._v10_plan(int(session["plan_id"]), team_ids)
        revisions = [
            dict(row)
            for row in self.connection.execute(
                """SELECT id,revision_number,change_summary,restored_from_revision_id,
                          created_by_user_id,created_at
                   FROM playbook_session_revisions WHERE session_id=?
                   ORDER BY revision_number DESC""",
                (int(session_id),),
            ).fetchall()
        ]
        evaluations = [
            dict(row)
            for row in self.connection.execute(
                """SELECT v.*,c.title content_title
                   FROM playbook_session_evaluations v
                   JOIN playbook_contents c ON c.id=v.content_id
                   WHERE v.session_id=? ORDER BY v.evaluated_at DESC,v.id DESC""",
                (int(session_id),),
            ).fetchall()
        ]
        session["local_overrides"] = self._v10_decode(
            session.pop("local_overrides_json"), fallback={}
        )
        return {
            "session": session,
            "plan": plan,
            "items": self._v10_plan_items(int(plan["id"]), published_only=published_only),
            "event_links": self._v10_session_links(session_id),
            "history": [
                dict(row)
                for row in self.connection.execute(
                    """SELECT * FROM playbook_session_event_history
                       WHERE session_id=? ORDER BY occurred_at DESC,id DESC""",
                    (int(session_id),),
                ).fetchall()
            ],
            "evaluations": evaluations,
            "revisions": revisions,
        }

    def list_sessions(
        self,
        *,
        team_ids: Iterable[int],
        event_id: int | None = None,
        future_only: bool = False,
        player_visible_only: bool = False,
    ) -> list[dict[str, Any]]:
        self._require_available()
        allowed = _ids(team_ids)
        if not allowed:
            return []
        clauses = [f"ps.team_id IN ({_placeholders(allowed)})"]
        params: list[object] = list(allowed)
        join = ""
        if event_id is not None or player_visible_only or future_only:
            join = """
                JOIN playbook_session_event_links l ON l.session_id=ps.id AND l.link_state='ACTIVE'
                JOIN calendar_events e ON e.id=l.calendar_event_id
            """
        if event_id is not None:
            clauses.append("e.id=?")
            params.append(int(event_id))
        if future_only:
            clauses.extend(("e.status IN('PLANNED','CONFIRMED')", "e.ends_at>=?"))
            params.append(_now_iso())
        if player_visible_only:
            clauses.append("e.is_player_visible=1")
        order_expression = "COALESCE(e.starts_at,ps.starts_at)" if join else "ps.starts_at"
        rows = self.connection.execute(
            f"""SELECT DISTINCT ps.id
                FROM playbook_sessions ps {join}
                WHERE {' AND '.join(clauses)}
                ORDER BY {order_expression} ASC,ps.id ASC""",
            tuple(params),
        ).fetchall()
        return [
            self.session_detail(
                int(row["id"]),
                team_ids=allowed,
                published_only=player_visible_only,
                player_visible_only=player_visible_only,
            )
            for row in rows
        ]

    def save_session(
        self,
        payload: Mapping[str, Any],
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
        session_id: int | None = None,
    ) -> dict[str, Any]:
        self._require_available()
        if session_id is None:
            team_id = int(payload.get("team_id") or 0)
            if team_id not in _ids(team_ids):
                raise PermissionError("A equipe escolhida está fora do escopo autorizado.")
            self._assert_team_exists(team_id)
            plan_id = int(payload.get("plan_id") or 0)
            self._v10_plan(plan_id, [team_id])
            before = None
            current_execution = "NOT_STARTED"
        else:
            existing = self._v10_session(session_id, team_ids)
            team_id = int(existing["team_id"])
            requested_team = payload.get("team_id")
            if requested_team is not None and int(requested_team) != team_id:
                raise ValueError("Uma sessão não pode ser movida de equipe nesta operação.")
            plan_id = int(payload.get("plan_id") or existing["plan_id"])
            self._v10_plan(plan_id, [team_id])
            before = self.session_detail(session_id, team_ids=team_ids)
            current_execution = str(existing["execution_status"])
        series_id = payload.get("series_id")
        if series_id is not None:
            series = self.connection.execute(
                "SELECT team_id FROM playbook_series WHERE id=?", (int(series_id),)
            ).fetchone()
            if series is None or int(series["team_id"]) != team_id:
                raise ValueError("A série escolhida não pertence à mesma equipe da sessão.")
        starts_at = payload.get("starts_at")
        ends_at = payload.get("ends_at")
        if starts_at and ends_at and str(ends_at) <= str(starts_at):
            raise ValueError("O fim da sessão precisa ser posterior ao início.")
        overrides = payload.get("local_overrides") or {}
        if not isinstance(overrides, Mapping):
            raise ValueError("As substituições locais da sessão precisam ser um objeto.")
        now = _now_iso()
        values = (
            plan_id,
            int(series_id) if series_id is not None else None,
            str(payload.get("title_override") or "").strip()[:180],
            starts_at,
            ends_at,
            self._v10_json(dict(overrides)),
            str(payload.get("execution_notes") or "").strip()[:4000],
        )
        if session_id is None:
            cursor = self.connection.execute(
                """INSERT INTO playbook_sessions(
                       team_id,plan_id,series_id,title_override,starts_at,ends_at,
                       local_overrides_json,execution_status,execution_notes,current_revision,
                       created_by_user_id,updated_by_user_id,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?, ?,?,1,?,?,?,?)""",
                (
                    team_id,
                    *values[:6],
                    current_execution,
                    values[6],
                    int(actor_user_id),
                    int(actor_user_id),
                    now,
                    now,
                ),
            )
            effective_id = int(cursor.lastrowid)
        else:
            effective_id = int(session_id)
            self.connection.execute(
                """UPDATE playbook_sessions
                   SET plan_id=?,series_id=?,title_override=?,starts_at=?,ends_at=?,
                       local_overrides_json=?,execution_notes=?,updated_by_user_id=?,updated_at=?
                   WHERE id=?""",
                (*values, int(actor_user_id), now, effective_id),
            )
        self._v10_write_session_revision(
            effective_id,
            actor_user_id=actor_user_id,
            change_summary=str(payload.get("change_summary") or "Alteração da sessão.").strip(),
        )
        after = self.session_detail(effective_id, team_ids=team_ids)
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.session.save",
            entity="playbook_session",
            target_id=effective_id,
            before=before,
            after=after,
        )
        return after

    def link_session_event(
        self,
        session_id: int,
        event_id: int,
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
        reason: str = "",
    ) -> dict[str, Any]:
        self._require_available()
        session = self._v10_session(session_id, team_ids)
        event = self._v10_assert_training_event(event_id, [int(session["team_id"])])
        active_link = self.connection.execute(
            """SELECT * FROM playbook_session_event_links
               WHERE session_id=? AND link_state='ACTIVE'""",
            (int(session_id),),
        ).fetchone()
        if active_link is not None and int(active_link["calendar_event_id"]) == int(event_id):
            return self.session_detail(session_id, team_ids=team_ids)
        now = _now_iso()
        if active_link is not None:
            self.connection.execute(
                """UPDATE playbook_session_event_links
                   SET link_state='HISTORICAL',unlinked_by_user_id=?,unlinked_at=?,unlink_reason=?
                   WHERE id=?""",
                (int(actor_user_id), now, str(reason or "").strip()[:1000], int(active_link["id"])),
            )
            self.connection.execute(
                """INSERT INTO playbook_session_event_history(
                       session_id,from_event_id,to_event_id,action,reason,actor_user_id,occurred_at
                   ) VALUES(?,?,NULL,'UNLINK',?,?,?)""",
                (int(session_id), int(active_link["calendar_event_id"]), str(reason or "").strip()[:1000], int(actor_user_id), now),
            )
        order_row = self.connection.execute(
            "SELECT COALESCE(MAX(link_order),-1)+1 FROM playbook_session_event_links WHERE calendar_event_id=?",
            (int(event_id),),
        ).fetchone()
        self.connection.execute(
            """INSERT INTO playbook_session_event_links(
                   session_id,calendar_event_id,link_state,link_order,linked_by_user_id,linked_at
               ) VALUES(?,?,'ACTIVE',?,?,?)""",
            (int(session_id), int(event_id), int(order_row[0]), int(actor_user_id), now),
        )
        self.connection.execute(
            """INSERT INTO playbook_session_event_history(
                   session_id,from_event_id,to_event_id,action,reason,actor_user_id,occurred_at
               ) VALUES(NULLIF(?,0),NULL,?,'LINK',?,?,?)""",
            (int(session_id), int(event["id"]), str(reason or "").strip()[:1000], int(actor_user_id), now),
        )
        self._v10_write_session_revision(
            session_id,
            actor_user_id=actor_user_id,
            change_summary="Vínculo de calendário atualizado.",
        )
        result = self.session_detail(session_id, team_ids=team_ids)
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.session.link_calendar_event",
            entity="playbook_session",
            target_id=session_id,
            after={"event_id": int(event_id), "session": result},
        )
        return result

    def unlink_session_event(
        self,
        session_id: int,
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
        reason: str,
    ) -> dict[str, Any]:
        self._require_available()
        self._v10_session(session_id, team_ids)
        link = self.connection.execute(
            """SELECT * FROM playbook_session_event_links
               WHERE session_id=? AND link_state='ACTIVE'""",
            (int(session_id),),
        ).fetchone()
        if link is None:
            raise ValueError("A sessão não possui vínculo ativo com o Calendário.")
        now = _now_iso()
        clean_reason = str(reason or "").strip()[:1000]
        self.connection.execute(
            """UPDATE playbook_session_event_links
               SET link_state='HISTORICAL',unlinked_by_user_id=?,unlinked_at=?,unlink_reason=?
               WHERE id=?""",
            (int(actor_user_id), now, clean_reason, int(link["id"])),
        )
        self.connection.execute(
            """INSERT INTO playbook_session_event_history(
                   session_id,from_event_id,to_event_id,action,reason,actor_user_id,occurred_at
               ) VALUES(?,?,NULL,'UNLINK',?,?,?)""",
            (int(session_id), int(link["calendar_event_id"]), clean_reason, int(actor_user_id), now),
        )
        self._v10_write_session_revision(
            session_id,
            actor_user_id=actor_user_id,
            change_summary="Vínculo de calendário removido.",
        )
        return self.session_detail(session_id, team_ids=team_ids)

    def restore_session_revision(
        self,
        session_id: int,
        revision_id: int,
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]:
        self._require_available()
        session = self._v10_session(session_id, team_ids)
        row = self.connection.execute(
            "SELECT * FROM playbook_session_revisions WHERE id=? AND session_id=?",
            (int(revision_id), int(session_id)),
        ).fetchone()
        if row is None:
            raise KeyError("Revisão da sessão não encontrada.")
        snapshot = self._v10_decode(row["snapshot_json"], fallback={})
        if not isinstance(snapshot, dict):
            raise ValueError("A revisão escolhida não contém um retrato restaurável da sessão.")
        plan_id = int(snapshot.get("plan_id") or session["plan_id"])
        self._v10_plan(plan_id, [int(session["team_id"])])
        overrides = snapshot.get("local_overrides")
        if not isinstance(overrides, Mapping):
            overrides = self._v10_decode(snapshot.get("local_overrides_json"), fallback={})
        self.connection.execute(
            """UPDATE playbook_sessions
               SET plan_id=?,series_id=?,title_override=?,starts_at=?,ends_at=?,
                   local_overrides_json=?,execution_status=?,execution_notes=?,
                   updated_by_user_id=?,updated_at=? WHERE id=?""",
            (
                plan_id,
                snapshot.get("series_id"),
                str(snapshot.get("title_override") or "")[:180],
                snapshot.get("starts_at"),
                snapshot.get("ends_at"),
                self._v10_json(dict(overrides or {})),
                str(snapshot.get("execution_status") or session["execution_status"]),
                str(snapshot.get("execution_notes") or "")[:4000],
                int(actor_user_id),
                _now_iso(),
                int(session_id),
            ),
        )
        self._v10_write_session_revision(
            session_id,
            actor_user_id=actor_user_id,
            change_summary=f"Restauração da revisão {int(row['revision_number'])}.",
            restored_from_revision_id=int(revision_id),
        )
        result = self.session_detail(session_id, team_ids=team_ids)
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.session.restore_revision",
            entity="playbook_session",
            target_id=session_id,
            after=result,
        )
        return result

    def execute_session(
        self,
        session_id: int,
        payload: Mapping[str, Any],
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]:
        """Registra execução independente da conclusão do evento de calendário."""

        self._require_available()
        session = self._v10_session(session_id, team_ids)
        status = str(payload.get("execution_status") or "COMPLETED").upper()
        if status not in {"NOT_STARTED", "IN_PROGRESS", "COMPLETED", "CANCELLED"}:
            raise ValueError("Status de execução inválido.")
        before = self.session_detail(session_id, team_ids=team_ids)
        self.connection.execute(
            """UPDATE playbook_sessions
               SET execution_status=?,execution_notes=?,updated_by_user_id=?,updated_at=?
               WHERE id=?""",
            (
                status,
                str(payload.get("execution_notes") or "").strip()[:4000],
                int(actor_user_id),
                _now_iso(),
                int(session_id),
            ),
        )
        self._v10_write_session_revision(
            session_id,
            actor_user_id=actor_user_id,
            change_summary=str(payload.get("change_summary") or "Registro de execução da sessão.").strip(),
        )
        after = self.session_detail(session_id, team_ids=team_ids)
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.session.execute",
            entity="playbook_session",
            target_id=session_id,
            before=before,
            after=after,
        )
        return after

    # Os quatro métodos abaixo mantêm os endpoints PB-3A, agora como uma
    # adaptação de sessão para evento. Assim, nenhum evento é dono do plano.
    def plan_for_event(
        self,
        event_id: int,
        *,
        team_ids: Iterable[int],
        published_only: bool = False,
        player_visible_only: bool = False,
    ) -> dict[str, Any]:
        self._require_available()
        event = self._v10_assert_training_event(
            event_id,
            team_ids,
            player_visible_only=player_visible_only,
        )
        rows = self.connection.execute(
            """SELECT l.session_id FROM playbook_session_event_links l
               JOIN playbook_sessions ps ON ps.id=l.session_id
               WHERE l.calendar_event_id=? AND l.link_state='ACTIVE'
               ORDER BY l.link_order,l.id""",
            (int(event_id),),
        ).fetchall()
        sessions = [
            self.session_detail(
                int(row["session_id"]),
                team_ids=team_ids,
                published_only=published_only,
                player_visible_only=player_visible_only,
            )
            for row in rows
        ]
        primary = sessions[0] if sessions else None
        transfers = [
            dict(row)
            for row in self.connection.execute(
                """SELECT * FROM playbook_session_event_history
                   WHERE from_event_id=? OR to_event_id=?
                   ORDER BY occurred_at DESC,id DESC""",
                (int(event_id), int(event_id)),
            ).fetchall()
        ]
        evaluations = [
            dict(row)
            for row in self.connection.execute(
                """SELECT v.content_id,v.mastery_stage,v.continuity_decision,v.notes,
                          v.evaluated_at,v.session_id,c.title
                   FROM playbook_session_evaluations v
                   JOIN playbook_contents c ON c.id=v.content_id
                   WHERE v.calendar_event_id=? ORDER BY c.title COLLATE NOCASE,v.id""",
                (int(event_id),),
            ).fetchall()
        ]
        return {
            "event": event,
            "plan": primary["plan"] if primary else None,
            "items": primary["items"] if primary else [],
            "sessions": sessions,
            "availability": self._attendance_summary(event),
            "transfers": transfers,
            "evaluations": evaluations,
        }

    def next_training_event_id(
        self,
        team_ids: Iterable[int],
        *,
        player_visible_only: bool = False,
    ) -> int | None:
        self._require_available()
        allowed = _ids(team_ids)
        if not allowed:
            return None
        visible_clause = " AND is_player_visible=1" if player_visible_only else ""
        row = self.connection.execute(
            f"""SELECT id FROM calendar_events
                WHERE team_id IN ({_placeholders(allowed)})
                  AND event_type='TRAINING'
                  AND status IN('PLANNED','CONFIRMED')
                  AND ends_at>=?{visible_clause}
                ORDER BY starts_at,id LIMIT 1""",
            (*allowed, _now_iso()),
        ).fetchone()
        return int(row[0]) if row is not None else None

    def save_plan(
        self,
        event_id: int,
        payload: Mapping[str, Any],
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]:
        self._require_available()
        event = self._v10_assert_training_event(event_id, team_ids)
        existing = self.connection.execute(
            """SELECT l.session_id,ps.plan_id FROM playbook_session_event_links l
               JOIN playbook_sessions ps ON ps.id=l.session_id
               WHERE l.calendar_event_id=? AND l.link_state='ACTIVE'
               ORDER BY l.link_order,l.id LIMIT 1""",
            (int(event_id),),
        ).fetchone()
        enriched = {**dict(payload), "team_id": int(event["team_id"])}
        if existing is None:
            saved = self.save_independent_plan(
                enriched,
                team_ids=team_ids,
                actor_user_id=actor_user_id,
            )
            session = self.save_session(
                {
                    "team_id": int(event["team_id"]),
                    "plan_id": int(saved["plan"]["id"]),
                    "title_override": str(event["title"] or saved["plan"]["title"]),
                    "starts_at": event["starts_at"],
                    "ends_at": event["ends_at"],
                    "change_summary": "Sessão criada pelo endpoint de evento legado.",
                },
                team_ids=team_ids,
                actor_user_id=actor_user_id,
            )
            self.link_session_event(
                int(session["session"]["id"]),
                int(event_id),
                team_ids=team_ids,
                actor_user_id=actor_user_id,
                reason="Vínculo criado pelo endpoint de plano do evento.",
            )
        else:
            self.save_independent_plan(
                enriched,
                plan_id=int(existing["plan_id"]),
                team_ids=team_ids,
                actor_user_id=actor_user_id,
            )
        result = self.plan_for_event(event_id, team_ids=team_ids)
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.plan.save_event_adapter",
            entity="calendar_event",
            target_id=event_id,
            after=result,
        )
        return result

    def reuse_plan(
        self,
        event_id: int,
        *,
        source_event_id: int,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> dict[str, Any]:
        self._require_available()
        if int(event_id) == int(source_event_id):
            raise ValueError("Escolha outro treino como origem do plano.")
        target_event = self._v10_assert_training_event(event_id, team_ids)
        source = self.plan_for_event(source_event_id, team_ids=team_ids)
        if source["plan"] is None:
            raise ValueError("O treino de origem ainda não possui plano para reutilizar.")
        session = self.save_session(
            {
                "team_id": int(target_event["team_id"]),
                "plan_id": int(source["plan"]["id"]),
                "title_override": str(target_event["title"] or source["plan"]["title"]),
                "starts_at": target_event["starts_at"],
                "ends_at": target_event["ends_at"],
                "change_summary": f"Reuso do plano {int(source['plan']['id'])}.",
            },
            team_ids=team_ids,
            actor_user_id=actor_user_id,
        )
        self.link_session_event(
            int(session["session"]["id"]),
            event_id,
            team_ids=team_ids,
            actor_user_id=actor_user_id,
            reason=f"Reuso do plano do evento {int(source_event_id)}.",
        )
        result = self.plan_for_event(event_id, team_ids=team_ids)
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.plan.reuse",
            entity="playbook_training_plan",
            target_id=source["plan"]["id"],
            after={"source_event_id": int(source_event_id), "target_event_id": int(event_id)},
        )
        return result

    def transfer_plan_for_reschedule(
        self,
        source_event_id: int,
        replacement_event_id: int,
        *,
        actor_user_id: int,
        reason: str,
    ) -> dict[str, Any] | None:
        """Move vínculos, não o plano; preserva IDs e ordem históricos."""

        if not self.is_available():
            return None
        source_links = self.connection.execute(
            """SELECT l.*,ps.plan_id FROM playbook_session_event_links l
               JOIN playbook_sessions ps ON ps.id=l.session_id
               WHERE l.calendar_event_id=? AND l.link_state='ACTIVE'
               ORDER BY link_order,id""",
            (int(source_event_id),),
        ).fetchall()
        if not source_links:
            return None
        now = _now_iso()
        next_order_row = self.connection.execute(
            "SELECT COALESCE(MAX(link_order),-1)+1 FROM playbook_session_event_links WHERE calendar_event_id=?",
            (int(replacement_event_id),),
        ).fetchone()
        next_order = int(next_order_row[0])
        session_ids: list[int] = []
        for offset, link in enumerate(source_links):
            session_id = int(link["session_id"])
            session_ids.append(session_id)
            self.connection.execute(
                """UPDATE playbook_session_event_links
                   SET link_state='HISTORICAL',unlinked_by_user_id=?,unlinked_at=?,unlink_reason=?
                   WHERE id=?""",
                (int(actor_user_id), now, str(reason or "").strip()[:1000], int(link["id"])),
            )
            target_link = self.connection.execute(
                """SELECT id FROM playbook_session_event_links
                   WHERE session_id=? AND calendar_event_id=? AND link_state='ACTIVE'""",
                (session_id, int(replacement_event_id)),
            ).fetchone()
            if target_link is None:
                self.connection.execute(
                    """INSERT INTO playbook_session_event_links(
                           session_id,calendar_event_id,link_state,link_order,
                           linked_by_user_id,linked_at
                       ) VALUES(?,?,'ACTIVE',?,?,?)""",
                    (session_id, int(replacement_event_id), next_order + offset, int(actor_user_id), now),
                )
            self.connection.execute(
                """INSERT INTO playbook_session_event_history(
                       session_id,from_event_id,to_event_id,action,reason,actor_user_id,occurred_at
                   ) VALUES(?,?,?,'RESCHEDULE',?,?,?)""",
                (session_id, int(source_event_id), int(replacement_event_id), str(reason or "").strip()[:1000], int(actor_user_id), now),
            )
            self._v10_write_session_revision(
                session_id,
                actor_user_id=actor_user_id,
                change_summary="Vínculo movido durante reagendamento do Calendário.",
            )
        result = {
            "plan_id": int(source_links[0]["plan_id"]),
            "from_event_id": int(source_event_id),
            "to_event_id": int(replacement_event_id),
        }
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.session.transfer_on_reschedule",
            entity="calendar_event",
            target_id=source_event_id,
            before={"event_id": int(source_event_id)},
            after=result,
        )
        return result

    def record_evaluations(
        self,
        event_id: int,
        evaluations: Iterable[Mapping[str, Any]],
        *,
        team_ids: Iterable[int],
        actor_user_id: int,
        session_id: int | None = None,
    ) -> list[dict[str, Any]]:
        self._require_available()
        self._v10_assert_training_event(event_id, team_ids)
        active_sessions = self.connection.execute(
            """SELECT session_id FROM playbook_session_event_links
               WHERE calendar_event_id=? AND link_state='ACTIVE'
               ORDER BY link_order,id""",
            (int(event_id),),
        ).fetchall()
        if session_id is None:
            if len(active_sessions) != 1:
                raise ValueError(
                    "Escolha explicitamente a sessão de destino para registrar a avaliação deste evento."
                )
            effective_session_id = int(active_sessions[0]["session_id"])
        else:
            effective_session_id = int(session_id)
            if effective_session_id not in {int(row["session_id"]) for row in active_sessions}:
                raise ValueError("A sessão escolhida não está vinculada ativamente a este evento.")
        session = self._v10_session(effective_session_id, team_ids)
        planned_ids = {
            int(row[0])
            for row in self.connection.execute(
                "SELECT content_id FROM playbook_training_plan_items WHERE plan_id=?",
                (int(session["plan_id"]),),
            ).fetchall()
        }
        normalized: list[tuple[int, str, str, str]] = []
        seen: set[int] = set()
        for raw in evaluations:
            content_id = int(raw["content_id"])
            if content_id not in planned_ids:
                raise ValueError("Só é possível avaliar conteúdos que fazem parte do plano da sessão.")
            if content_id in seen:
                raise ValueError("Cada conteúdo pode receber uma única avaliação final.")
            stage = str(raw.get("mastery_stage") or "").upper()
            decision = str(raw.get("continuity_decision") or "").upper()
            if stage not in {"STARTING", "IMPROVING", "REFINING", "CONSOLIDATED"}:
                raise ValueError("Estágio de domínio inválido.")
            if decision not in {"CONTINUE", "COMPLETE", "REVIEW"}:
                raise ValueError("Decisão de continuidade inválida.")
            seen.add(content_id)
            normalized.append((content_id, stage, decision, str(raw.get("notes") or "").strip()[:2000]))
        now = _now_iso()
        for content_id, stage, decision, notes in normalized:
            existing = self.connection.execute(
                """SELECT id FROM playbook_session_evaluations
                   WHERE session_id=? AND calendar_event_id=? AND content_id=?
                   ORDER BY id DESC LIMIT 1""",
                (effective_session_id, int(event_id), content_id),
            ).fetchone()
            if existing is None:
                self.connection.execute(
                    """INSERT INTO playbook_session_evaluations(
                           session_id,calendar_event_id,content_id,mastery_stage,
                           continuity_decision,notes,actor_user_id,evaluated_at
                       ) VALUES(?,?,?,?,?,?,?,?)""",
                    (effective_session_id, int(event_id), content_id, stage, decision, notes, int(actor_user_id), now),
                )
            else:
                self.connection.execute(
                    """UPDATE playbook_session_evaluations
                       SET mastery_stage=?,continuity_decision=?,notes=?,actor_user_id=?,evaluated_at=?
                       WHERE id=?""",
                    (stage, decision, notes, int(actor_user_id), now, int(existing["id"])),
                )
        self._v10_write_session_revision(
            effective_session_id,
            actor_user_id=actor_user_id,
            change_summary="Avaliações de domínio atualizadas.",
        )
        result = [
            dict(row)
            for row in self.connection.execute(
                """SELECT content_id,mastery_stage,continuity_decision,notes,evaluated_at,session_id
                   FROM playbook_session_evaluations
                   WHERE calendar_event_id=? AND session_id=? ORDER BY content_id,id""",
                (int(event_id), effective_session_id),
            ).fetchall()
        ]
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.session.evaluate",
            entity="playbook_session",
            target_id=effective_session_id,
            after={"event_id": int(event_id), "evaluations": result},
        )
        return result

    def record_session_evaluations(
        self,
        session_id: int,
        evaluations: Iterable[Mapping[str, Any]],
        *,
        calendar_event_id: int | None,
        change_summary: str,
        team_ids: Iterable[int],
        actor_user_id: int,
    ) -> list[dict[str, Any]]:
        """Avalia uma sessão independente; o evento é contexto opcional.

        Quando um evento é informado, ele precisa ser o vínculo ativo da sessão.
        Sem esse contexto a avaliação continua válida e fica explicitamente com
        ``calendar_event_id`` nulo, sem criar ou alterar nenhum evento.
        """

        self._require_available()
        session = self._v10_session(session_id, team_ids)
        effective_event_id = (
            int(calendar_event_id) if calendar_event_id is not None else None
        )
        if effective_event_id is not None:
            self._v10_assert_training_event(
                effective_event_id,
                [int(session["team_id"])],
            )
            linked = self.connection.execute(
                """SELECT 1 FROM playbook_session_event_links
                   WHERE session_id=? AND calendar_event_id=? AND link_state='ACTIVE'""",
                (int(session_id), effective_event_id),
            ).fetchone()
            if linked is None:
                raise ValueError(
                    "O evento informado não é o vínculo ativo desta sessão."
                )
        planned_ids = {
            int(row[0])
            for row in self.connection.execute(
                "SELECT content_id FROM playbook_training_plan_items WHERE plan_id=?",
                (int(session["plan_id"]),),
            ).fetchall()
        }
        normalized: list[tuple[int, str, str, str]] = []
        seen: set[int] = set()
        for raw in evaluations:
            content_id = int(raw["content_id"])
            if content_id not in planned_ids:
                raise ValueError(
                    "Só é possível avaliar conteúdos que fazem parte do plano da sessão."
                )
            if content_id in seen:
                raise ValueError("Cada conteúdo pode receber uma única avaliação por sessão.")
            stage = str(raw.get("mastery_stage") or "").upper()
            decision = str(raw.get("continuity_decision") or "").upper()
            if stage not in {"STARTING", "IMPROVING", "REFINING", "CONSOLIDATED"}:
                raise ValueError("Estágio de domínio inválido.")
            if decision not in {"CONTINUE", "COMPLETE", "REVIEW"}:
                raise ValueError("Decisão de continuidade inválida.")
            seen.add(content_id)
            normalized.append(
                (
                    content_id,
                    stage,
                    decision,
                    str(raw.get("notes") or "").strip()[:2000],
                )
            )
        now = _now_iso()
        for content_id, stage, decision, notes in normalized:
            existing = self.connection.execute(
                """SELECT id FROM playbook_session_evaluations
                   WHERE session_id=? AND calendar_event_id IS ? AND content_id=?
                   ORDER BY id DESC LIMIT 1""",
                (int(session_id), effective_event_id, content_id),
            ).fetchone()
            if existing is None:
                self.connection.execute(
                    """INSERT INTO playbook_session_evaluations(
                           session_id,calendar_event_id,content_id,mastery_stage,
                           continuity_decision,notes,actor_user_id,evaluated_at
                       ) VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        int(session_id),
                        effective_event_id,
                        content_id,
                        stage,
                        decision,
                        notes,
                        int(actor_user_id),
                        now,
                    ),
                )
            else:
                self.connection.execute(
                    """UPDATE playbook_session_evaluations
                       SET mastery_stage=?,continuity_decision=?,notes=?,
                           actor_user_id=?,evaluated_at=?
                       WHERE id=?""",
                    (stage, decision, notes, int(actor_user_id), now, int(existing["id"])),
                )
        self._v10_write_session_revision(
            int(session_id),
            actor_user_id=actor_user_id,
            change_summary=(
                str(change_summary or "").strip()
                or "Avaliações independentes da sessão atualizadas."
            ),
        )
        result = [
            dict(row)
            for row in self.connection.execute(
                """SELECT content_id,mastery_stage,continuity_decision,notes,
                          evaluated_at,session_id,calendar_event_id
                   FROM playbook_session_evaluations
                   WHERE session_id=? AND calendar_event_id IS ?
                   ORDER BY content_id,id""",
                (int(session_id), effective_event_id),
            ).fetchall()
        ]
        self._audit(
            actor_user_id=actor_user_id,
            action="playbook.session.evaluate_independent",
            entity="playbook_session",
            target_id=int(session_id),
            after={
                "calendar_event_id": effective_event_id,
                "evaluations": result,
            },
        )
        return result
