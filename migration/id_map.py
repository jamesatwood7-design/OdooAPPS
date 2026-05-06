import os
import sqlite3
import datetime as _dt


SCHEMA = """
CREATE TABLE IF NOT EXISTS id_map (
  odoo_model   TEXT NOT NULL,
  odoo_id      INTEGER NOT NULL,
  variant      TEXT NOT NULL DEFAULT '',
  zoho_type    TEXT NOT NULL,
  zoho_id      TEXT NOT NULL,
  status       TEXT NOT NULL,
  payload_hash TEXT,
  error        TEXT,
  created_at   TEXT NOT NULL,
  PRIMARY KEY (odoo_model, odoo_id, variant)
);
CREATE INDEX IF NOT EXISTS ix_id_map_status ON id_map(status);
CREATE INDEX IF NOT EXISTS ix_id_map_zoho ON id_map(zoho_type, zoho_id);
"""


class IdMap:
    """SQLite-backed Odoo->Zoho ID mapping store for idempotent migrations."""

    def __init__(self, db_path):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    def close(self):
        self._conn.close()

    def get(self, odoo_model, odoo_id, variant=''):
        cur = self._conn.execute(
            "SELECT zoho_id, zoho_type, status FROM id_map "
            "WHERE odoo_model=? AND odoo_id=? AND variant=?",
            (odoo_model, int(odoo_id), variant),
        )
        return cur.fetchone()

    def get_zoho_id(self, odoo_model, odoo_id, variant=''):
        row = self.get(odoo_model, odoo_id, variant)
        if row and row['status'] == 'created':
            return row['zoho_id']
        return None

    def put(self, odoo_model, odoo_id, zoho_type, zoho_id, status='created',
            variant='', payload_hash=None, error=None):
        self._conn.execute(
            "INSERT OR REPLACE INTO id_map "
            "(odoo_model, odoo_id, variant, zoho_type, zoho_id, status, "
            " payload_hash, error, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                odoo_model, int(odoo_id), variant, zoho_type, str(zoho_id),
                status, payload_hash, error,
                _dt.datetime.utcnow().isoformat(timespec='seconds'),
            ),
        )

    def mark_failed(self, odoo_model, odoo_id, error, variant='', zoho_type=''):
        self._conn.execute(
            "INSERT OR REPLACE INTO id_map "
            "(odoo_model, odoo_id, variant, zoho_type, zoho_id, status, "
            " payload_hash, error, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                odoo_model, int(odoo_id), variant, zoho_type, '', 'failed',
                None, str(error)[:4000],
                _dt.datetime.utcnow().isoformat(timespec='seconds'),
            ),
        )

    def iter_failed(self, odoo_model=None):
        if odoo_model:
            cur = self._conn.execute(
                "SELECT * FROM id_map WHERE status='failed' AND odoo_model=?",
                (odoo_model,),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM id_map WHERE status='failed'"
            )
        return list(cur.fetchall())

    def counts(self):
        cur = self._conn.execute(
            "SELECT zoho_type, status, COUNT(*) as c FROM id_map "
            "GROUP BY zoho_type, status"
        )
        return [dict(r) for r in cur.fetchall()]
