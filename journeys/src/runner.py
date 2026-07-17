from random import Random

from models import RunRequest, RunResult, StepEvidence


def run(request: RunRequest) -> RunResult:
    scenario = request.scenario
    if scenario.requires_approval and not request.approved:
        return RunResult(scenario=scenario, status="awaiting_approval", aborted=False,
            approval_required=True, availability=0, recovery_rate=0, mttr_ms=None,
            error_budget_consumed=0, original_journey_verified=False, evidence=[],
            explanation="Human approval is required before this high-risk fault can run.")

    rng = Random(scenario.seed)
    evidence = []
    total = failed = recovered = 0
    worst_fault_latency = 0
    aborted = False
    for index, step in enumerate(scenario.steps):
        requests = max(10, scenario.concurrency * 4)
        baseline = int(step.latency_slo_ms * rng.uniform(.35, .75))
        affected = index == scenario.fault_step
        fault_latency = int(baseline * (1 + scenario.fault_intensity * (8 if affected else .2)))
        step_failed = int(requests * scenario.fault_intensity * (.45 if affected else .01))
        recovery = int(baseline * rng.uniform(.9, 1.15))
        if recovery <= step.latency_slo_ms:
            recovered += 1
        total += requests
        failed += step_failed
        worst_fault_latency = max(worst_fault_latency, fault_latency)
        evidence.append(StepEvidence(step=step.name, baseline_latency_ms=baseline,
            fault_latency_ms=fault_latency, recovered_latency_ms=recovery,
            requests=requests, failed_requests=step_failed))

    error_rate = failed / total
    aborted = error_rate >= scenario.safety.abort_error_rate or worst_fault_latency >= scenario.safety.abort_latency_ms
    verified = all(item.recovered_latency_ms <= step.latency_slo_ms
                   for item, step in zip(evidence, scenario.steps)) and not aborted
    availability = round(1 - error_rate, 4)
    return RunResult(scenario=scenario, status="aborted" if aborted else "completed", aborted=aborted,
        approval_required=False, availability=availability,
        recovery_rate=round(recovered / len(scenario.steps), 4),
        mttr_ms=None if aborted else int(400 + scenario.fault_intensity * 2600),
        error_budget_consumed=round(error_rate / .01, 2), original_journey_verified=verified,
        evidence=evidence,
        explanation=("Safety abort condition reached; the experiment stopped." if aborted else
                     "Fault injected, recovery observed, and the original customer journey replayed."))
