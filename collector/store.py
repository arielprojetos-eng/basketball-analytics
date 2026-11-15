"""Camada de armazenamento: Firestore em produção, memória nos testes."""
import json
import os
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MemoryStore:
    """Implementação em memória, usada nos testes."""

    def __init__(self):
        self.games = {}
        self.teams = {}
        self.meta = {}

    def get_meta(self, name):
        return dict(self.meta.get(name, {}))

    def set_meta(self, name, data):
        self.meta[name] = dict(data)

    def existing_game_ids(self, ids):
        return {i for i in ids if i in self.games}

    def put_game(self, game):
        self.games[game["id"]] = dict(game)

    def update_game(self, gid, fields):
        self.games[gid].update(fields)

    def pending_games(self, limit):
        rows = [g for g in self.games.values() if not g.get("periodsFetched")]
        rows.sort(key=lambda g: (g.get("tier", 1), _neg(g.get("sortKey", ""))))
        return rows[:limit]

    def count_pending(self):
        return sum(1 for g in self.games.values() if not g.get("periodsFetched"))

    def get_team(self, tid):
        t = self.teams.get(tid)
        return json.loads(json.dumps(t)) if t else None

    def put_team(self, tid, data):
        self.teams[tid] = json.loads(json.dumps(data))


def _neg(text):
    # ordena texto em ordem decrescente sem depender de índice composto
    return tuple(-ord(c) for c in text)


class BufferedStore:
    """Acumula equipes e o índice em memória e grava uma única vez no flush().

    O plano gratuito do Firestore permite 20 mil gravações por dia; gravar a cada jogo
    esgotaria a cota no histórico retroativo. Aqui cada equipe é gravada uma vez por execução.
    """

    BUFFERED_META = {"index"}

    def __init__(self, inner):
        self.inner = inner
        self._teams = {}
        self._dirty = set()
        self._meta = {}
        self._meta_dirty = set()

    def get_team(self, tid):
        if tid not in self._teams:
            self._teams[tid] = self.inner.get_team(tid)
        t = self._teams[tid]
        return json.loads(json.dumps(t)) if t else None

    def put_team(self, tid, data):
        self._teams[tid] = json.loads(json.dumps(data))
        self._dirty.add(tid)

    def get_meta(self, name):
        if name in self.BUFFERED_META:
            if name not in self._meta:
                self._meta[name] = self.inner.get_meta(name)
            return json.loads(json.dumps(self._meta[name]))
        return self.inner.get_meta(name)

    def set_meta(self, name, data):
        if name in self.BUFFERED_META:
            self._meta[name] = json.loads(json.dumps(data))
            self._meta_dirty.add(name)
        else:
            self.inner.set_meta(name, data)

    def flush(self):
        teams = {tid: self._teams[tid] for tid in self._dirty}
        if hasattr(self.inner, "put_teams_batch"):
            self.inner.put_teams_batch(teams)
        else:
            for tid, data in teams.items():
                self.inner.put_team(tid, data)
        for name in self._meta_dirty:
            self.inner.set_meta(name, self._meta[name])
        n = len(self._dirty) + len(self._meta_dirty)
        self._dirty.clear()
        self._meta_dirty.clear()
        return n

    def __getattr__(self, name):
        return getattr(self.inner, name)


class FirestoreStore:
    def __init__(self):
        import firebase_admin
        from firebase_admin import credentials, firestore

        raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
        if raw:
            cred = credentials.Certificate(json.loads(raw))
        else:
            cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred)
        self.db = firestore.client()

    def get_meta(self, name):
        snap = self.db.collection("meta").document(name).get()
        return snap.to_dict() or {} if snap.exists else {}

    def set_meta(self, name, data):
        self.db.collection("meta").document(name).set(data)

    def existing_game_ids(self, ids):
        found = set()
        ids = list(ids)
        for i in range(0, len(ids), 300):
            refs = [self.db.collection("games").document(x) for x in ids[i:i + 300]]
            for snap in self.db.get_all(refs):
                if snap.exists:
                    found.add(snap.id)
        return found

    def put_game(self, game):
        self.db.collection("games").document(game["id"]).set(game)

    def update_game(self, gid, fields):
        self.db.collection("games").document(gid).update(fields)

    def _pending_query(self):
        from google.cloud.firestore_v1.base_query import FieldFilter

        return (
            self.db.collection("games")
            .where(filter=FieldFilter("periodsFetched", "==", False))
            .order_by("tier")
            .order_by("sortKey", direction="DESCENDING")
        )

    def pending_games(self, limit):
        return [s.to_dict() for s in self._pending_query().limit(limit).stream()]

    def count_pending(self):
        from google.cloud.firestore_v1.base_aggregation import AggregationQuery  # noqa: F401

        agg = self._pending_query().count(alias="n").get()
        return int(agg[0][0].value)

    def get_team(self, tid):
        snap = self.db.collection("teams").document(tid).get()
        return snap.to_dict() if snap.exists else None

    def put_team(self, tid, data):
        self.db.collection("teams").document(tid).set(data)

    def put_teams_batch(self, teams):
        items = list(teams.items())
        for i in range(0, len(items), 400):
            batch = self.db.batch()
            for tid, data in items[i:i + 400]:
                batch.set(self.db.collection("teams").document(tid), data)
            batch.commit()
