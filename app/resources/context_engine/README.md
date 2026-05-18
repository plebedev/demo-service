# Context Engine Model Flow Configuration

`model-flows.yaml` configures optional model-backed Context Engine steps.

Selection is keyed by:

- `domain_id`
- `flow_id`
- `step_id`
- `purpose`

Model profiles name existing provider/model settings in the same style as the
messy-notes workflow YAML. Runtime execution still goes through
`app.services.model_factory`; this directory does not introduce a provider
client.

All model-backed Context Engine steps use PydanticAI structured output by
passing the Pydantic response model as `Agent(..., output_type=...)`. There is
no domain-level or provider-level switch between structured-output mechanisms.

To switch modes for all configured Context Engine steps, set:

```bash
CONTEXT_ENGINE_EXECUTION_MODE=deterministic
CONTEXT_ENGINE_EXECUTION_MODE=llm
CONTEXT_ENGINE_EXECUTION_MODE=hybrid
```

To change models, edit `model_profiles` or point
`CONTEXT_ENGINE_MODEL_CONFIG_PATH` at another catalog file. Keep prompt templates
inside the owning domain pack, for example `app/domains/job_search/prompts/`.
