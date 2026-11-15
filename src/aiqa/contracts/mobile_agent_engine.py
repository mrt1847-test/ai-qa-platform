"""Exact source and parent/child protocol pin; no runtime imports or credentials."""
MOBILE_AGENT_COMMIT='81fa28b564ef7a695521500bc15a0e1324b2b394'
MOBILE_AGENT_MANIFEST_SHA256='ee406e537f411cc4e92d4cc2094d34c4b4ac00c99d5cb758efc98899e09aec72'
_ENGINE=(('kind','mobile-agent-v3.5'),('upstream_commit',MOBILE_AGENT_COMMIT),
         ('manifest_sha256',MOBILE_AGENT_MANIFEST_SHA256),('protocol','mobile-agent-parent-rpc-v1'))


def mobile_agent_engine_ref():
    return dict(_ENGINE)


def require_mobile_agent_engine(value):
    expected=mobile_agent_engine_ref()
    if type(value) is not dict or value!=expected:
        raise ValueError('recording engine pin invalid')
    return expected
