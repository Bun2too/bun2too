"""Versioned, idempotent ingestion of measured quality and optional embedding drift.

Scores must come from an actual evaluator or labeled benchmark. No LLM judge is
silently invoked and no missing score is converted to a passing result.
"""
import json
import math
import statistics
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from . import otel
from .store import now


class Evaluation(BaseModel):
    evaluation_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,100}$')
    evaluator: Literal['human', 'benchmark', 'model_judge', 'embedding']
    evaluator_version: str = Field(min_length=1, max_length=100)
    dataset_version: str = Field(min_length=1, max_length=100)
    scores: dict[str, float] = Field(default_factory=dict, max_length=8)
    embedding: list[float] | None = Field(default=None, min_length=2, max_length=4096)
    embedding_model: str | None = Field(default=None, max_length=100)

    @field_validator('scores')
    @classmethod
    def valid_scores(cls, value):
        allowed = {'faithfulness', 'toxicity', 'context_relevance', 'mrr', 'ground_truth_accuracy', 'useful_token_ratio'}
        if any(key not in allowed or not math.isfinite(score) or not 0 <= score <= 1 for key, score in value.items()):
            raise ValueError('Use supported quality scores between zero and one')
        return value

    @field_validator('embedding')
    @classmethod
    def valid_embedding(cls, value):
        if value is not None and (any(not math.isfinite(x) for x in value) or math.hypot(*value) == 0):
            raise ValueError('Embedding must be finite and nonzero')
        return value


def record(db, run_id, evaluation):
    run = db.get(run_id)
    data = evaluation.model_dump(exclude={'embedding'})
    scores = dict(evaluation.scores)
    manifest = run.get('telemetry_manifest', {})
    cohort = json.dumps([evaluation.embedding_model, evaluation.dataset_version,
                         manifest.get('prompt_version'), evaluation.evaluator_version])
    with db.connect() as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS evaluations (id TEXT PRIMARY KEY, run_id TEXT, data TEXT)')
        connection.execute('CREATE TABLE IF NOT EXISTS drift_baselines (cohort TEXT PRIMARY KEY, vector TEXT, distances TEXT)')
        connection.execute('BEGIN IMMEDIATE')
        previous = connection.execute('SELECT run_id, data FROM evaluations WHERE id = ?', (evaluation.evaluation_id,)).fetchone()
        if previous:
            if previous[0] != run_id:
                raise ValueError('Evaluation ID belongs to a different run')
            return json.loads(previous[1])
        if evaluation.embedding is not None:
            if not evaluation.embedding_model:
                raise ValueError('Embedding model is required for drift comparison')
            norm = math.hypot(*evaluation.embedding)
            vector = [x / norm for x in evaluation.embedding]
            baseline = connection.execute('SELECT vector, distances FROM drift_baselines WHERE cohort = ?', (cohort,)).fetchone()
            if baseline:
                reference, distances = json.loads(baseline[0]), json.loads(baseline[1])
                if len(vector) != len(reference):
                    raise ValueError('Embedding dimension changed; use a new embedding model/version')
                distance = min(2, max(0, 1 - sum(a * b for a, b in zip(reference, vector))))
                distances = (distances + [distance])[-100:]
                scores.update(cosine_distance=distance, semantic_volatility=statistics.pvariance(distances))
                connection.execute('UPDATE drift_baselines SET distances = ? WHERE cohort = ?', (json.dumps(distances), cohort))
                data['drift_sample_count'] = len(distances)
            else:
                connection.execute('INSERT INTO drift_baselines VALUES (?, ?, ?)', (cohort, json.dumps(vector), '[]'))
                data['drift_status'] = 'baseline_created'
        data.update(scores=scores, at=now(), run_id=run_id)
        connection.execute('INSERT INTO evaluations VALUES (?, ?, ?)', (evaluation.evaluation_id, run_id, json.dumps(data)))
        # Persist the audit event atomically with deduplication and baseline update.
        event = dict(kind='quality_evaluated', at=data['at'], evaluator=evaluation.evaluator,
                     quality=data, **otel.correlation())
        connection.execute('INSERT INTO events (run_id, data) VALUES (?, ?)', (run_id, json.dumps(event)))
    for key, score in scores.items():
        otel.measure('ai.quality.score', score, {'evaluator': evaluation.evaluator, 'metric': key}, histogram=True)
    return data


def replay_bundle(db, run_id):
    """Export existing redacted evidence only; never executes tools or publication."""
    from .observability import redact
    run = db.get(run_id)
    return redact({'schema_version': 1, 'run_id': run_id,
                   'manifest': run.get('telemetry_manifest', {}),
                   'generation_settings': run.get('generation_settings'),
                   'brief': run['brief'], 'source_snapshots': run.get('source_snapshots', []),
                   'tasks': run.get('tasks', []), 'artifact': run.get('artifact'),
                   'planned_tasks': [event for event in db.events(run_id) if event['kind'] == 'task_planned'],
                   'constraints': {'execute_tools': False, 'publish': False,
                                   'reproduction': 'best_effort; provider nondeterminism and redaction apply'}})
