from fastapi.testclient import TestClient
from generator import generate
from main import app
from models import GenerateRequest, RunRequest
from runner import run

client = TestClient(app)

def test_seed_is_replayable():
    first = generate(GenerateRequest(seed=42, count=5))
    second = generate(GenerateRequest(seed=42, count=5))
    assert first == second
    assert len({item.seed for item in first}) == 5

def test_high_risk_fault_waits_for_human():
    scenario = next(item for item in generate(GenerateRequest(seed=1, count=100)) if item.requires_approval)
    result = run(RunRequest(scenario=scenario))
    assert result.status == "awaiting_approval"
    assert result.evidence == []

def test_approved_run_produces_evidence_and_verification():
    scenario = generate(GenerateRequest(seed=42, count=1))[0]
    result = run(RunRequest(scenario=scenario, approved=True))
    assert result.status in {"completed", "aborted"}
    assert len(result.evidence) == len(scenario.steps)
    assert 0 <= result.availability <= 1

def test_api_generate_and_unknown_journey():
    response = client.post("/scenarios/generate", json={"seed": 42, "count": 2})
    assert response.status_code == 200
    assert len(response.json()) == 2
    assert client.post("/scenarios/generate", json={"journey": "nope"}).status_code == 422

def test_safety_budget_rejects_unsafe_scenario():
    scenario = generate(GenerateRequest(seed=42))[0].model_dump()
    scenario["concurrency"] = 100
    response = client.post("/scenarios/run", json={"scenario": scenario, "approved": True})
    assert response.status_code == 422
