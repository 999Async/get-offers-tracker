"""Re-score a fresh four-arm retrieval run with the final frozen judgments.

Input ranks and timings stay immutable. Validate every search input before reusing
ranks: only label/reviewer/version changes are permitted. Preserve raw execution
and its dataset, and identify both in the final report.
"""
import copy
import hashlib
import json
from pathlib import Path
from statistics import mean

from getoffers_agent.domain.contracts import digest
from getoffers_agent.job_search.evaluation import SearchDataset, retrieval_metrics

ROOT = Path(__file__).resolve().parents[3]
BASE = Path(__file__).resolve().parent
FINAL = ROOT / 'docs/experiments/phase1-ai-reviewed-neural-paired.json'
RAW = ROOT / 'docs/experiments/phase1-ai-review-execution.json'


def read_dataset(path):
    return SearchDataset.model_validate_json(path.read_text())


def main():
    execution = read_dataset(BASE / 'execution-dataset.json')
    final = read_dataset(BASE / 'official-ai-reviewed.json')
    raw = json.loads((RAW if RAW.exists() else FINAL).read_text())
    assert raw['dataset_hash'] == digest(execution.model_dump(mode='json'))
    assert execution.jobs == final.jobs and execution.as_of == final.as_of
    assert execution.source_kind == final.source_kind
    assert [(c.case_id, c.request) for c in execution.cases] == [(c.case_id, c.request) for c in final.cases]
    labels = {c.case_id: c.relevance for c in final.cases}
    assert len(raw['reports']) == 4
    assert {r['config']['mode'] for r in raw['reports']} == {'lexical','dense','hybrid','hybrid-rerank'}
    scored = copy.deepcopy(raw)
    for report in scored['reports']:
        assert [c['case_id'] for c in report['cases']] == list(labels)
        for case in report['cases']:
            grades = labels[case['case_id']]
            assert len(grades) == 30
            assert set(case['ranked_version_ids']) <= grades.keys()
            case['metrics'] = retrieval_metrics(case['ranked_version_ids'], grades)
            case['judged_result_count'] = len(case['ranked_version_ids'])
        report['metrics'] = {k: mean(c['metrics'][k] for c in report['cases']) for k in report['cases'][0]['metrics']}
    for paired, challenger in zip(scored['paired_comparisons'], scored['reports'][1:], strict=True):
        paired['case_deltas'] = [
            {'case_id': a['case_id'],
             'mrr_delta': b['metrics']['mrr'] - a['metrics']['mrr'],
             'ndcg_at_10_delta': b['metrics']['ndcg_at_10'] - a['metrics']['ndcg_at_10']}
            for a,b in zip(scored['reports'][0]['cases'],challenger['cases'],strict=True)
        ]
    if not RAW.exists():
        RAW.write_bytes(FINAL.read_bytes())
    scored.update(dataset_version=final.dataset_version, dataset_hash=digest(final.model_dump(mode='json')))
    scored['scoring_provenance'] = {
        'type': 'fresh_four_arm_retrieval_then_final_label_rescore',
        'execution_report': str(RAW.relative_to(ROOT)),
        'execution_report_sha256': hashlib.sha256(RAW.read_bytes()).hexdigest(),
        'execution_dataset': str((BASE/'execution-dataset.json').relative_to(ROOT)),
        'execution_dataset_hash': raw['dataset_hash'],
        'final_dataset': str((BASE/'official-ai-reviewed.json').relative_to(ROOT)),
        'scoring_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'unchanged': ['jobs','as_of','requests','case_order','ranked_version_ids','model_identities','search_configs','timings'],
        'reason': 'Final boundary review removed 16 weak positives while retrieval was running. Labels never affect retrieval; only metrics are recomputed.',
        'storage': 'Qdrant local mode, fresh dedicated directory; historical phase1 used Qdrant service. Do not compare their latency as a controlled performance experiment.',
    }
    FINAL.write_text(json.dumps(scored,ensure_ascii=False,indent=2)+'\n')
    # Quantify annotation effects on identical historical ranks and the same subset.
    historical=json.loads((ROOT/'docs/experiments/phase1-official-neural-paired.json').read_text())
    draft=read_dataset(ROOT/'datasets/evals/job-search-v1/official-draft.json')
    draft_labels={c.case_id:c.relevance for c in draft.cases}
    effects=[]
    for report in historical['reports']:
        cases=[c for c in report['cases'] if c['case_id'] in labels]
        assert len(cases)==len(labels)
        old=[retrieval_metrics(c['ranked_version_ids'],draft_labels[c['case_id']]) for c in cases]
        new=[retrieval_metrics(c['ranked_version_ids'],labels[c['case_id']]) for c in cases]
        effects.append({'mode':report['config']['mode'], 'same_subset_case_count':len(cases),'draft_labels':{k:mean(c[k] for c in old) for k in old[0]},'final_ai_labels':{k:mean(c[k] for c in new) for k in new[0]}})
    (BASE/'historical-label-effect.json').write_text(json.dumps({'type':'historical_rank_replay_not_a_fresh_execution','case_count':len(labels),'reports':effects},ensure_ascii=False,indent=2)+'\n')
    for report in scored['reports']:
        print(report['config']['mode'],json.dumps(report['metrics']), 'p50_ms',report['p50_ms'],'p95_ms',report['p95_ms'])
    print('Gate:', scored['gate'])

if __name__=='__main__':
    main()
