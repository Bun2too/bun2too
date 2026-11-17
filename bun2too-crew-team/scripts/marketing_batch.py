"""Prepare, submit, poll and collect offline marketing enrichment batches."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
from crewai_agents.app.batch_jobs import BatchJobs


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['prepare', 'submit', 'poll', 'collect'])
    p.add_argument('job_key')
    p.add_argument('--db', required=True, help='Persistent private SQLite path')
    p.add_argument('--provider', choices=['openai', 'anthropic'])
    p.add_argument('--model')
    p.add_argument('--task', choices=['tagging', 'enrichment', 'log_summary'])
    p.add_argument('--input', help='JSON array of text items')
    p.add_argument('--max-tokens', type=int, default=1000)
    p.add_argument('--output', help='New private JSON result file (collect only)')
    args = p.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / 'crewai_agents/.env')
    jobs = BatchJobs(args.db)
    if args.action == 'prepare':
        if not all([args.provider, args.model, args.task, args.input]):
            p.error('prepare requires --provider --model --task --input')
        items = json.loads(Path(args.input).read_text())
        if not isinstance(items, list):
            p.error('--input must contain a JSON array of text items')
        result = jobs.prepare(args.job_key, args.provider, args.model, args.task, items, args.max_tokens)
    elif args.action == 'collect':
        if not args.output:
            p.error('collect requires --output')
        with open(args.output, 'x') as f:
            import os
            os.chmod(args.output, 0o600)
            json.dump(jobs.collect(args.job_key), f)
        result = jobs.get(args.job_key)
    else:
        result = getattr(jobs, args.action)(args.job_key)
    print(json.dumps({k: result.get(k) for k in ('job_key', 'status', 'provider_id')}))


if __name__ == '__main__':
    main()
