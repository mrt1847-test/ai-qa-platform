"""Healing preflight resolves exact metadata without reading or sending a key."""
import sqlite3
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from aiqa.contracts.cases import CaseDefinition, CaseVersion, PathPolicy
from aiqa.contracts.healing import ApprovedHealingPolicy, HealingRequest, Limits
from aiqa.healing.policy import resolve_healing_policy, reserve_window
from ux_support import ux_app


def _version(project):
    return CaseVersion(uuid4(), UUID(project), uuid4(), CaseDefinition("tap", "check", (), {}, {}, (), (), PathPolicy()), uuid4(), uuid4(), "recorded", "sha256:"+"a"*64, "digest")


@pytest.fixture
def healing_metadata(ux_app):
    app, project, database = ux_app
    binding, revision, key = map(str, (uuid4(), uuid4(), uuid4()))
    with sqlite3.connect(database) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO secret_refs(project_id,ref_id,revision,name,availability,created_at,actor_id) VALUES(?,?,1,'fixture','available','2026-11-09',?)", (project,key,str(uuid4())))
        db.execute("INSERT INTO model_bindings(project_id,binding_id,name,next_revision,latest_revision_id) VALUES(?,?,'fixture',2,?)",(project,binding,revision))
        db.execute("INSERT INTO binding_revisions(project_id,binding_id,revision_id,revision,role,provider,endpoint_kind,endpoint,model,key_ref_id,key_revision,prompt_hash,tariff_id,compatibility_status,content_hash,actor_id,created_at) VALUES(?,?,?,1,'healing','fixture','openai_compatible','https://model.example','fixture-model',?,1,?,'fixture-tariff','unchecked',?,?,'2026-11-09')", (project,binding,revision,key,'sha256:'+'b'*64,'sha256:'+'c'*64,str(uuid4())))
    settings={"target_kind":"web","healing_policy":{"allowed":True,"scope":"locator","model_binding_ref":binding,"binding_revision":revision,"max_episodes_per_item":1,"max_model_calls_per_item":1,"max_seconds":20},"limits":{"budget":"0.50","timeout_seconds":90,"max_model_calls":4,"max_seconds":15}}
    return project,database,binding,revision,key,settings


def _resolve(db, project, settings, **kwargs):
    from aiqa.healing.admission import resolve_execution_healing
    return resolve_execution_healing(db, UUID(project), kwargs.pop("version",_version(project)),settings,**kwargs)


def test_exact_healing_revision_is_pinned_even_when_newer_exists(healing_metadata):
    project,database,binding,revision,key,settings=healing_metadata
    with sqlite3.connect(database) as db:
        newer=str(uuid4())
        db.execute("INSERT INTO binding_revisions SELECT project_id,binding_id,?,2,role,provider,endpoint_kind,endpoint,'newer-model',key_ref_id,key_revision,prompt_hash,tariff_id,compatibility_status,?,actor_id,created_at FROM binding_revisions WHERE revision_id=?",(newer,'sha256:'+'d'*64,revision))
        db.execute("UPDATE model_bindings SET next_revision=3,latest_revision_id=? WHERE binding_id=?",(newer,binding))
        before=db.total_changes
        actual=_resolve(db,project,settings,requested_enabled=True)
        assert actual.blockers == ()
        assert actual.policy.effective_enabled is True and actual.policy.rejected is False
        assert actual.policy.binding_revision == revision
        assert actual.policy.effective_limits == {"budget":"0.50","max_episodes_per_item":1,"max_model_calls_per_item":1,"max_seconds":15,"timeout_seconds":90}
        assert actual.binding_pin == {"binding_id":binding,"revision_id":revision,"revision":1,"role":"healing","content_hash":"sha256:"+"c"*64,"key_ref_id":key,"key_revision":1}
        assert db.total_changes == before
        settings["healing_policy"]["binding_revision"]="1"
        numbered=_resolve(db,project,settings,requested_enabled=True)
        assert numbered.policy.resolution_hash == actual.policy.resolution_hash
        assert numbered.binding_pin == actual.binding_pin


@pytest.mark.parametrize("change,code",[("wrong_project","HEALING_BINDING_UNAVAILABLE"),("wrong_role","HEALING_BINDING_UNAVAILABLE"),("missing_revision","HEALING_BINDING_UNAVAILABLE"),("wrong_key_revision","HEALING_KEY_UNAVAILABLE"),("key_revoked","HEALING_KEY_UNAVAILABLE"),("key_missing","HEALING_KEY_UNAVAILABLE"),("incompatible","HEALING_BINDING_UNAVAILABLE")])
def test_unavailable_metadata_cannot_be_overridden_by_client_key_present(healing_metadata,change,code):
    project,database,binding,revision,key,settings=healing_metadata
    settings["healing_policy"]["healer_key_present"]=True
    with sqlite3.connect(database) as db:
        if change=="wrong_project": project=str(uuid4())
        elif change in {"wrong_role","wrong_key_revision","incompatible"}:
            changed=str(uuid4())
            role="verification" if change=="wrong_role" else "healing"
            key_revision=2 if change=="wrong_key_revision" else 1
            compatibility="incompatible" if change=="incompatible" else "unchecked"
            db.execute("INSERT INTO binding_revisions SELECT project_id,binding_id,?,2,?,provider,endpoint_kind,endpoint,model,key_ref_id,?,prompt_hash,tariff_id,?,?,actor_id,created_at FROM binding_revisions WHERE revision_id=?",(changed,role,key_revision,compatibility,'sha256:'+'d'*64,revision))
            settings["healing_policy"]["binding_revision"]=changed
        elif change=="missing_revision": settings["healing_policy"]["binding_revision"]=str(uuid4())
        elif change=="key_revoked": db.execute("UPDATE secret_refs SET availability='unavailable'")
        elif change=="key_missing": db.execute("DELETE FROM secret_refs")
        actual=_resolve(db,project,settings,requested_enabled=True)
        assert code in actual.blockers
        assert actual.policy.effective_enabled is False and actual.policy.rejected is True
        assert actual.binding_pin is None


@pytest.mark.parametrize("mutation,code",[("unapproved","HEALING_APPROVAL_REQUIRED"),("no_package","HEALING_APPROVAL_REQUIRED"),("disabled","HEALING_NOT_APPROVED"),("no_scope","HEALING_NOT_APPROVED"),("zero_budget","HEALING_BUDGET_UNAVAILABLE"),("zero_calls","HEALING_BUDGET_UNAVAILABLE"),("nan_budget","HEALING_POLICY_INVALID"),("no_revision","HEALING_BINDING_UNAVAILABLE")])
def test_on_requires_approved_policy_and_positive_budget(healing_metadata,mutation,code):
    project,database,_,_,_,settings=healing_metadata
    version=_version(project)
    if mutation=="unapproved": version=replace(version,approval_id=None)
    elif mutation=="no_package": version=replace(version,replay_package_id=None)
    elif mutation=="disabled": settings["healing_policy"]["allowed"]=False
    elif mutation=="no_scope": settings["healing_policy"]["scope"]=""
    elif mutation=="zero_budget": settings["limits"]["budget"]="0"
    elif mutation=="zero_calls": settings["limits"]["max_model_calls"]=0
    elif mutation=="nan_budget": settings["limits"]["budget"]="NaN"
    elif mutation=="no_revision": settings["healing_policy"].pop("binding_revision")
    with sqlite3.connect(database) as db:
        actual=_resolve(db,project,settings,requested_enabled=True,version=version)
    assert code in actual.blockers
    assert actual.policy.effective_enabled is False and actual.policy.rejected is True
    assert actual.binding_pin is None


def test_off_and_trial_do_not_require_or_read_healer_metadata(healing_metadata):
    project,database,_,_,_,settings=healing_metadata
    with sqlite3.connect(database) as db:
        reads=[]
        db.set_trace_callback(reads.append)
        off=_resolve(db,project,settings)
        trial=_resolve(db,project,settings,requested_enabled=True,purpose="trial")
    assert off.blockers == trial.blockers == ()
    assert off.policy.effective_enabled is trial.policy.effective_enabled is False
    assert off.binding_pin is trial.binding_pin is None
    assert off.policy.effective_limits["budget"] == "0.50"
    assert trial.policy.effective_limits["max_seconds"] == 15
    assert not any("binding_revisions" in sql or "secret_refs" in sql for sql in reads)


@pytest.mark.parametrize("value",["NaN","Infinity","bad","0","-0.01"])
def test_policy_budget_never_turns_invalid_input_into_positive_allowance(value):
    policy=ApprovedHealingPolicy(True,"locator","binding","revision",True)
    version=replace(_version(str(uuid4())),approved_healing=policy)
    resolved=resolve_healing_policy(version,HealingRequest(True),Limits(budget=value))
    assert resolved.effective_limits["budget"] in {"0", "0.00"}
    assert resolved.effective_enabled is False and resolved.rejected is True
    assert reserve_window(resolved,60,60) is None


def test_model_references_are_visible_for_copying_into_case_settings(healing_metadata,ux_app):
    import asyncio
    import httpx
    from ux_support import session
    app,project,_=ux_app
    _,_,binding,revision,_,_=healing_metadata
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://127.0.0.1") as client:
            await session(client,project)
            page=await client.get(f"/ui/projects/{project}/settings")
            assert page.status_code==200
            assert revision in page.text
            assert binding in page.text
    asyncio.run(scenario())


@pytest.mark.parametrize("prepopulated",[False,True])
def test_off_caps_come_from_saved_approval_without_key_lookup(healing_metadata,prepopulated):
    project,database,_,_,_,settings=healing_metadata
    settings["healing_policy"]["max_seconds"]=3
    settings["limits"]["max_model_calls"]=1
    version=_version(project)
    if prepopulated:
        version=replace(version,approved_healing=ApprovedHealingPolicy(True,"locator","binding","revision",False,max_model_calls_per_item=1,max_seconds=3))
    with sqlite3.connect(database) as db:
        actual=_resolve(db,project,settings,version=version)
    assert actual.blockers==() and actual.policy.rejected is False
    assert actual.policy.effective_limits["max_model_calls_per_item"]==1
    assert actual.policy.effective_limits["max_seconds"]==3


def test_explicit_request_can_narrow_but_not_expand_approval(healing_metadata):
    project,database,_,_,_,settings=healing_metadata
    settings["healing_policy"]["max_model_calls_per_item"]=2
    with sqlite3.connect(database) as db:
        narrow=_resolve(db,project,settings,requested_enabled=True,request_caps={"max_model_calls_per_item":1,"max_seconds":5})
        assert narrow.blockers==() and narrow.policy.effective_enabled is True
        assert narrow.policy.effective_limits["max_model_calls_per_item"]==1
        assert narrow.policy.effective_limits["max_seconds"]==5
        settings["healing_policy"]["max_model_calls_per_item"]=1
        expanded=_resolve(db,project,settings,requested_enabled=True,request_caps={"max_model_calls_per_item":2})
        assert "HEALING_REQUEST_EXCEEDS_APPROVAL" in expanded.blockers
        assert expanded.policy.effective_enabled is False
        assert expanded.binding_pin is None


@pytest.mark.parametrize("scope",[None,False,[],{}])
def test_invalid_immutable_scope_fails_closed(healing_metadata,scope):
    project,database,_,_,_,settings=healing_metadata
    settings["healing_policy"]["scope"]=scope
    with sqlite3.connect(database) as db:
        actual=_resolve(db,project,settings,requested_enabled=True)
    assert "HEALING_POLICY_INVALID" in actual.blockers
    assert actual.policy.effective_enabled is False and actual.binding_pin is None


@pytest.mark.parametrize("calls,window",[(0,None),(1,(1,30))])
def test_policy_reservation_cannot_exceed_total_model_call_cap(calls,window):
    version=replace(_version(str(uuid4())),approved_healing=ApprovedHealingPolicy(True,"locator","binding","revision",True))
    policy=resolve_healing_policy(version,HealingRequest(True),Limits(max_model_calls=calls))
    assert reserve_window(policy,60,60)==window
