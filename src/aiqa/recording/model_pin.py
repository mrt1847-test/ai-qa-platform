"""Resolve current recording model metadata. Never opens a credential or provider."""
from __future__ import annotations

from decimal import Decimal
from aiqa.contracts.authoring import AUTHORING_SCHEMA, authoring_policy_ref
from aiqa.domain.versions import parse_case_settings


def current_authoring_binding(connection, project_id) -> dict[str, object]:
    row = connection.execute(
        """SELECT r.binding_id,r.revision_id,r.revision,r.content_hash,r.key_ref_id,r.key_revision,r.compatibility_status
           FROM binding_revisions r JOIN model_bindings b ON b.project_id=r.project_id
             AND b.binding_id=r.binding_id AND b.latest_revision_id=r.revision_id
           WHERE r.project_id=? AND r.role='authoring'
           ORDER BY r.created_at DESC,r.binding_id,r.revision_id LIMIT 1""", (str(project_id),)
    ).fetchone()
    if row is None:
        raise ValueError("authoring binding is missing")
    if row[6] not in ("unchecked", "compatible"):
        raise ValueError("authoring binding is incompatible")
    key = connection.execute(
        "SELECT 1 FROM secret_refs WHERE project_id=? AND ref_id=? AND revision=? AND availability='available'",
        (str(project_id),str(row[4]),row[5]),
    ).fetchone()
    if key is None:
        raise ValueError("authoring key is unavailable")
    return {"binding_id":str(row[0]),"revision_id":str(row[1]),"revision":int(row[2]),"role":"authoring",
            "content_hash":str(row[3]),"key_ref_id":str(row[4]),"key_revision":int(row[5])}


def recording_caps(raw: object) -> dict[str, object]:
    if type(raw) is not dict or "timeout_seconds" not in raw:
        raise ValueError("budget is missing")
    parsed = parse_case_settings({"target_kind":"web","limits":raw},None).document["limits"]
    caps = {"timeout_seconds":parsed["timeout_seconds"],"max_actions":parsed.get("max_actions",50),
            "max_model_calls":parsed.get("max_model_calls",80),"budget":parsed.get("budget","2.00"),"currency":"USD"}
    if caps["max_model_calls"] <= 0 or Decimal(caps["budget"]) <= 0:
        raise ValueError("authoring budget is unavailable")
    if Decimal(caps["budget"]) > Decimal("2.00"):
        caps["budget"] = "2.00"
    return caps


def freeze_authoring_limits(binding: dict[str, object], raw: object, version_id, version_hash: str) -> dict[str, object]:
    limits = {**recording_caps(raw),"authoring_schema":AUTHORING_SCHEMA,"authoring_binding":dict(binding),
              "input_case_version_id":str(version_id),"input_version_hash":version_hash}
    limits["policy_ref"] = authoring_policy_ref(limits)
    return limits
