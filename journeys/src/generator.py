import secrets
from random import Random

from models import FaultType, GenerateRequest, JourneyStep, LoadProfile, RiskLevel, SafetyBudget, Scenario


JOURNEYS = {
    "checkout": [
        JourneyStep(name="browse", operation="GET /catalog", target="catalog", latency_slo_ms=250),
        JourneyStep(name="cart", operation="POST /cart", target="cart", latency_slo_ms=350),
        JourneyStep(name="pay", operation="POST /payments", target="payments", latency_slo_ms=800),
        JourneyStep(name="confirm", operation="GET /orders/{id}", target="orders", latency_slo_ms=400),
    ],
    "sign-in": [
        JourneyStep(name="login", operation="POST /sessions", target="identity", latency_slo_ms=500),
        JourneyStep(name="profile", operation="GET /me", target="profile", latency_slo_ms=300),
    ],
    "provision": [
        JourneyStep(name="allocate", operation="POST /volumes", target="provisioning", latency_slo_ms=900),
        JourneyStep(name="attach", operation="POST /instances", target="compute", latency_slo_ms=1200),
        JourneyStep(name="verify", operation="GET /instances/{id}", target="compute", latency_slo_ms=500),
    ],
}


def generate(request: GenerateRequest) -> list[Scenario]:
    root_seed = request.seed if request.seed is not None else secrets.randbits(63)
    scenarios = []
    for offset in range(request.count):
        seed = root_seed + offset
        rng = Random(seed)
        journey = request.journey or rng.choice(sorted(JOURNEYS))
        if journey not in JOURNEYS:
            raise ValueError(f"unknown journey: {journey}")
        profile = rng.choice(list(LoadProfile))
        concurrency = {LoadProfile.STEADY: 5, LoadProfile.SPIKE: 20, LoadProfile.BURST: 25,
                       LoadProfile.SOAK: 8, LoadProfile.CONCURRENCY_RAMP: 15}[profile]
        fault = rng.choice(list(FaultType))
        risk = RiskLevel.HIGH if fault in {FaultType.POD_KILL, FaultType.DEPENDENCY_OUTAGE} else RiskLevel.MEDIUM
        steps = JOURNEYS[journey]
        scenarios.append(Scenario(
            seed=seed, name=f"{journey}-{fault.value}-{seed}", journey=journey, steps=steps,
            load_profile=profile, concurrency=concurrency,
            duration_seconds=rng.randint(20, 120), fault_type=fault,
            fault_step=rng.randrange(len(steps)), fault_intensity=round(rng.uniform(.1, .8), 2),
            risk=risk, requires_approval=risk == RiskLevel.HIGH, safety=SafetyBudget(),
        ))
    return scenarios
