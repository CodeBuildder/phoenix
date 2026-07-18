from fastapi import FastAPI, HTTPException
from generator import generate
from models import GenerateRequest, RunRequest, RunResult, Scenario
from runner import run

app = FastAPI(title="Phoenix Customer Journey Resilience Lab", version="0.1.0")

@app.get("/health")
def health():
    return {"status": "ok", "service": "phoenix-journeys", "mode": "cluster-free"}

@app.post("/scenarios/generate", response_model=list[Scenario])
def generate_scenarios(request: GenerateRequest):
    try:
        return generate(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@app.post("/scenarios/run", response_model=RunResult)
def run_scenario(request: RunRequest):
    return run(request)
