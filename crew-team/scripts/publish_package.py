"""Validate explicit package targets and publish only to GitHub Packages."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

KINDS = {'container', 'npm', 'maven', 'gradle'}


def target(root, kind, directory, image='bun2too-crew-team'):
    root = Path(root).resolve()
    path = (root / directory).resolve()
    if kind not in KINDS or not path.is_relative_to(root) or not path.is_dir():
        raise ValueError('Invalid package kind or directory outside repository')
    required = {'container': ['Dockerfile'], 'npm': ['package.json', 'package-lock.json'],
                'maven': ['pom.xml'], 'gradle': ['gradlew']}[kind]
    if any(not (path / name).is_file() for name in required):
        raise ValueError('Missing package build files: ' + ', '.join(required))
    if kind == 'container' and not re.fullmatch(r'[a-z0-9]+(?:[._-][a-z0-9]+)*', image):
        raise ValueError('Container image name must be lowercase')
    if kind == 'npm':
        package = json.loads((path / 'package.json').read_text())
        if not re.fullmatch(r'@bun2too/[a-z0-9][a-z0-9._-]*', package.get('name', '')):
            raise ValueError('npm package must use the lowercase @bun2too scope')
        if package.get('private') or not package.get('version'):
            raise ValueError('npm package needs a version and must not be private:true')
        registry = package.get('publishConfig', {}).get('registry', 'https://npm.pkg.github.com')
        if registry.rstrip('/') != 'https://npm.pkg.github.com':
            raise ValueError('npm publishConfig must target GitHub Packages')
        if not package.get('files'):
            raise ValueError('Declare package.json files to explicitly select distributable files')
    return path


def matrix(root):
    data = json.loads((Path(root) / '.github/package-targets.json').read_text())
    targets = data['include']
    if not targets or len(targets) > 32:
        raise ValueError('Register between 1 and 32 package targets')
    seen = set()
    images = set()
    for item in targets:
        path = target(root, item['kind'], item['directory'], item.get('image', 'bun2too-crew-team'))
        key = (item['kind'], str(path))
        if key in seen:
            raise ValueError('Duplicate package target')
        seen.add(key)
        if item['kind'] == 'container':
            image = item.get('image', 'bun2too-crew-team')
            if image in images:
                raise ValueError('Container targets must use distinct image names')
            images.add(image)
    return data


def commands(kind, path, repository):
    """No shell interpolation; repository code is trusted branch build code."""
    if not re.fullmatch(r'Bun2too/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Publishing is restricted to a Bun2too repository')
    registry = 'https://maven.pkg.github.com/' + repository.lower()
    if kind == 'npm':
        return [['npm', 'ci'], ['npm', 'run', 'build', '--if-present'], ['npm', 'test'],
                ['npm', 'publish', '--registry=https://npm.pkg.github.com',
                 '--tag=' + ('latest' if os.getenv('GITHUB_REF_NAME') == 'main' else 'qa')]]
    if kind == 'maven':
        executable = './mvnw' if (path / 'mvnw').is_file() else 'mvn'
        # All destination overrides: release/snapshot-specific config cannot redirect a deployment.
        return [[executable, '-B', 'deploy',
                 '-DaltDeploymentRepository=github::' + registry,
                 '-DaltReleaseDeploymentRepository=github::' + registry,
                 '-DaltSnapshotDeploymentRepository=github::' + registry]]
    if kind == 'gradle':
        return [['./gradlew', '--no-daemon', 'build'],
                ['./gradlew', '--no-daemon', '--init-script', str(Path(__file__).with_name('github-packages.init.gradle').resolve()),
                 'publishAllPublicationsToGitHubPackagesRepository']]
    raise ValueError('Containers are published by the Docker build/push step')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['matrix', 'validate', 'publish'])
    args = parser.parse_args()
    root = Path.cwd()
    if args.action == 'matrix':
        result = json.dumps(matrix(root), separators=(',', ':'))
        if os.getenv('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as f: f.write('matrix=' + result + '\n')
        print(result)
        return
    kind = os.environ['PACKAGE_KIND']
    image = os.getenv('PACKAGE_IMAGE_NAME', 'bun2too-crew-team')
    path = target(root, kind, os.environ['PACKAGE_DIRECTORY'], image)
    if args.action == 'validate':
        if os.getenv('GITHUB_OUTPUT') and kind == 'container':
            with open(os.environ['GITHUB_OUTPUT'], 'a') as f: f.write('image=ghcr.io/bun2too/' + image + '\n')
        return
    for command in commands(kind, path, os.environ['GITHUB_REPOSITORY']):
        subprocess.run(command, cwd=path, check=True)
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(f'\nPublished {kind} package from `{path.relative_to(root)}` to GitHub Packages.\n')


if __name__ == '__main__':
    main()
