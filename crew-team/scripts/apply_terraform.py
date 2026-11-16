"""Apply an inspected plan, recovering once from a missing CrewAI build source."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def missing_crewai_source(output):
    # Never recover unrelated/mixed failures, including missing n8n image sources.
    errors = output.split('Error: ')
    return (len(errors) == 2
            and 'with railway_variable_collection.marketing_runtime[0],' in errors[1]
            and 'Unable to redeploy service after variable collection updated' in errors[1]
            and "This deployment's source is no longer" in errors[1]
            and 'available to rebuild' in errors[1])


def apply(plan, env, run=subprocess.run):
    plan = str(Path(plan).resolve())
    wrapper = [sys.executable, str(ROOT / 'scripts/run_deployment_step.py')]

    def command(args, cwd=ROOT / 'terraform', capture=False):
        return run(wrapper + args, cwd=cwd, check=False, text=True,
                   stdout=subprocess.PIPE if capture else None,
                   stderr=subprocess.STDOUT if capture else None)

    apply_command = ['terraform', 'apply', '-input=false', '-no-color', plan]
    result = command(apply_command, capture=True)
    # Same Terraform output as before, subject to normal CI secret masking.
    print(result.stdout or '', end='', flush=True)
    if result.returncode == 0:
        return 0
    if env.get('DEPLOY_OPERATION') != 'deploy' or not missing_crewai_source(result.stdout or ''):
        return result.returncode
    print('::warning::CrewAI variables were written but the previous build source is unavailable. '
          'Uploading this checkout once, then replanning and rechecking storage before retrying.', flush=True)
    # Never replay the partially applied plan. Preserve all normal safety checks.
    commands = [
        ([sys.executable, '-m', 'scripts.deploy_crewai'], ROOT),
        (['terraform', 'plan', '-input=false', '-no-color', '-out=' + plan], ROOT / 'terraform'),
        ([sys.executable, str(ROOT / 'scripts/check_n8n_storage_plan.py'), plan], ROOT / 'terraform'),
        (apply_command, ROOT / 'terraform'),
    ]
    for args, cwd in commands:
        result = command(args, cwd=cwd)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == '__main__':
    sys.exit(apply(sys.argv[1], os.environ))
