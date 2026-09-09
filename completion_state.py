"""Display completion only when every expected item has explicit matching readback."""


def verified_completed_stages(state, domain_results, verification, validation):
    expected = {}
    for item in validation.get('items', []):
        expected.setdefault(item['domain'], []).append(item)
    completed = []
    for stage in state.get('completed', []):
        if stage in {'rr_analysis', 'rr_inspection', 'target_discovery'}:
            completed.append(stage)
            continue
        desired = expected.get(stage, [])
        result = domain_results.get('domains', {}).get(stage, {})
        observed = verification.get('domains', {}).get(stage, {}).get('items', [])
        expected_ids = {item['itemId'] for item in desired}
        observed_ids = {item['itemId'] for item in observed}
        if (desired and result.get('status') == 'completed' and not result.get('blocked')
                and all(item.get('status') == 'VERIFIED' for item in desired)
                and expected_ids == observed_ids and len(observed) == len(expected_ids)
                and all(item.get('status') == 'MATCH' and item.get('cventEvidence') for item in observed)):
            completed.append(stage)
    return completed
