from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    topic: str = Field(..., min_length=5, max_length=300)
    num_papers: int = Field(default=8, ge=3, le=20)
    max_hypotheses: int = Field(default=3, ge=1, le=5)
    model: str = Field(default="openai/gpt-oss-120b")


class RunResponse(BaseModel):
    run_id: str


class RunStatus(BaseModel):
    run_id: str
    status: str
    stage: str = ""
    progress: int = 0
    error: str | None = None
    output_dir: str | None = None
    compile_ok: bool | None = None