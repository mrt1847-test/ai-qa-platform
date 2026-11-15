"""Normalize provider-reported counts. Missing is null; reasoning/cache are subsets."""


def provider_measurements(result):
    def count(name):
        value=getattr(result,name,None)
        return value if type(value) is int and value>=0 else None
    incoming,outgoing=count('input_tokens'),count('output_tokens')
    cached,reasoning=count('cached_input_tokens'),count('reasoning_tokens')
    if incoming is None or cached is not None and cached>incoming:cached=None
    if outgoing is None or reasoning is not None and reasoning>outgoing:reasoning=None
    complete=incoming is not None and outgoing is not None
    return {'input_tokens':incoming,'output_tokens':outgoing,'cached_input_tokens':cached,
            'reasoning_tokens':reasoning,'total_tokens':incoming+outgoing if complete else None,
            'measurement_status':'measured' if complete else 'unreported','token_scope':'call','tokens_complete':complete}
