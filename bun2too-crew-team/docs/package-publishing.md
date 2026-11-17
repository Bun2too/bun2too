# GitHub Packages publication

Full deployments on `main` and `qa` now execute **verify → packages → deploy**. Package publishing happens before Railway credential/platform checks, so a Railway outage cannot prevent a verified build from reaching GitHub Packages. A failed package job blocks the application deployment. Explicit `infrastructure-only` and `import-state` operations skip package publishing. Pull requests and other branches do not publish.

The current repository has one container target, declared in `.github/package-targets.json`. It publishes:

- `ghcr.io/bun2too/bun2too-crew-team:sha-<full Git commit SHA>`
- `ghcr.io/bun2too/bun2too-crew-team:main` or `:qa`

The digest is read back with `docker buildx imagetools inspect` and recorded in the Actions summary. Use the digest for exact identity; branch tags move, and rebuilding the same commit can change its image when upstream dependencies change. The package is associated with this repository through the OCI source label and appears under [Bun2too Packages](https://github.com/orgs/Bun2too/packages) once the first authorized push succeeds. The workflow does not make packages public or change organization permissions.

The publishing job uses `GITHUB_TOKEN` with `contents: read` and `packages: write`. Allow package creation in the organization; if a package already exists, grant this repository Actions access to it. No package PAT is required for normal publication from this repository. Deployment jobs retain read-only repository permissions.

`crewai_agents/.dockerignore` excludes `.env`, local data, virtualenvs and tests from the build context. The Dockerfile copies only requirements, app code/context, configuration and the launcher. Terraform plans/state and runtime secrets are not package artifacts.

Railway still uploads and builds the checked-out source through its existing CLI. This change archives the build in GHCR; it does **not** switch Railway to deploying that registry digest. Promoting the exact GHCR image to Railway would require separate registry access and deployment configuration.

## Register another build

Add an entry to `.github/package-targets.json`:

```json
{"include":[
  {"kind":"container","directory":"crewai_agents","image":"bun2too-crew-team"},
  {"kind":"npm","directory":"packages/example"},
  {"kind":"maven","directory":"services/example-java"},
  {"kind":"gradle","directory":"services/example-gradle"}
]}
```

Only add entries for real projects; the additional directories above are examples and do not exist in this repository. `python scripts/publish_package.py matrix` rejects missing build files, invalid namespaces/destinations and duplicate targets. The reusable workflow supports these kinds; Java and Node packages are not currently built or published here.

### npm

Use Node 24, a committed `package-lock.json`, a lowercase `@bun2too/...` package name, a test script, and an explicit `files` list containing the distributable outputs. `private:true` is rejected. Set `publishConfig.registry` to `https://npm.pkg.github.com` or omit it; another registry is rejected. The workflow runs `npm ci`, the build script if present, `npm test`, and `npm publish` to GitHub Packages. `main` uses the `latest` distribution tag; `qa` uses `qa`. Supply a distinct prerelease version on QA: distribution tags do not allow reusing an existing version.

### Maven

Java 21 is configured. Use `mvnw` if committed/executable, otherwise the hosted runner's Maven. Configure `maven-deploy-plugin` **3.x** in the project POM; its `id::url` destination syntax is required. The workflow runs the `deploy` lifecycle, including tests, and overrides general, release and snapshot destinations to `https://maven.pkg.github.com/bun2too/<repository>`. Generated Maven settings use server ID `github` and the workflow token. Do not configure build plugins to skip tests or upload to unrelated registries.

### Gradle

Commit an executable Gradle wrapper and configure the `maven-publish` plugin and Maven publications in the actual project. Java 21 is configured. The workflow runs `build` and then only `publishAllPublicationsToGitHubPackagesRepository`. `scripts/github-packages.init.gradle` creates/configures that named destination with the calling repository's GitHub Packages URL and workflow credentials. It does not invoke the general `publish` task, which could upload to other registries.

### Version and release behavior

npm and Maven/Gradle release versions must be unique. Bump versions as part of each release; use distinct prereleases/snapshots for QA according to the package ecosystem. Re-publishing an existing immutable version fails the pipeline; it is not silently treated as a new successful upload. Registering a package makes it part of every full deployment on main/qa, so its version policy must match that cadence. Current container builds use commit tags and do not need a package manifest version bump.

## Verification

Run `python scripts/verify_marketing.py` and `python scripts/publish_package.py matrix`. Use actionlint to check both workflows. Local tests validate publication routing and gates, not remote package access. The first GitHub Actions run must confirm organization permissions, registry acceptance and the resulting package/version. There are no Java/npm projects here to exercise live ecosystem builds yet.

References: [GitHub container publishing](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images), [npm registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-npm-registry), [Maven publishing](https://docs.github.com/en/actions/tutorials/publish-packages/publish-java-packages-with-maven), [Gradle publishing](https://docs.github.com/en/actions/tutorials/publish-packages/publish-java-packages-with-gradle).
