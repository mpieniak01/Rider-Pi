# Sonar and test coverage

`Sonar quality gate` runs on same-repository pull requests and main pushes. It
checks out the exact published head, executes isolated Python 3.9 and Node 22
regressions, imports both coverage reports and waits for the Sonar quality gate.
The existing Tests and Quality Guard workflows remain enabled.

`SONAR_TOKEN` is a repository Actions secret. The scanner receives it only in its
own step through the container environment; the workflow never writes it to a
repository file or interpolates it into a shell command. The pinned image
entrypoint internally maps it to the scanner authentication property. Fork pull requests have no secret and require a trusted manual analysis;
the workflow fails visibly rather than publishing an unauthenticated result.
Sonar Automatic Analysis remains off because CI performs explicit analysis.

## One producer for each published analysis

CI owns analysis of published main and same-repository PRs. Runs for the same
Sonar target share a concurrency group; an active run is allowed to finish,
including server-side processing and gate evaluation. A newer pending run can
replace an older pending run under GitHub's concurrency rules.

After merging, wait for the main push workflow and read its exact-SHA report.
For an explicit main rescan, use **Run workflow** on `Sonar quality gate` with
branch `main`; it uses the same concurrency group. Do not launch a second local
scanner to refresh a report while CI owns that target. Concurrent submissions
can make Sonar reject a report as older even when both use the same commit.

The canonical local launcher checks the configured workflow state before tests
and again before submission. While CI is active it refuses local submissions;
`--check` remains read-only and reports the scan owner. Local scanning is a
fallback when the workflow is disabled, and does not replace a failed CI check.
If workflow ownership cannot be verified, do not submit another report.
Automatic Analysis stays off. Coverage reproduction below creates local files
without publishing an analysis.

## Reproduce the measured reports

From the repository root, use the existing project virtualenv and Node 22:

```sh
mkdir -p docs_pl/_done/ci-sonar
.venv/bin/python -m pytest tests -m "not hardware and not physical_motion and not network" \
  --cov=apps --cov=services --cov=common --cov=drivers --cov=scripts --cov-report=
node --experimental-vm-modules --experimental-test-coverage --test \
  --test-reporter=spec --test-reporter-destination=stdout \
  --test-reporter=lcov --test-reporter-destination=docs_pl/_done/ci-sonar/node.lcov tests/*.test.mjs
.venv/bin/python tests/quality_reports.py --python-data .coverage \
  --javascript docs_pl/_done/ci-sonar/node.lcov --output docs_pl/_done/ci-sonar
```

Windows operators can use their existing Node 22 executable for the Node command
against the same WSL checkout. The report normalizer handles Windows separators;
it preserves measured line and branch hits and rejects unresolved source paths.
Python reports use one repository root, preventing collisions between identical
basenames in different packages. Generated reports are ignored local artifacts.

Production JavaScript is loaded unchanged for coverage. In inert UI fixtures,
injected import/export declarations preserve original character/line positions;
only a final fixture binding is outside the production source. Anonymous or
rewritten data-URL modules previously executed successfully while losing useful
source coverage. Deployment subprocess fixtures compile the transmitted helper
with its real filename, allowing pytest-cov to measure that code as well.

## Interpreting the gate

The main project retains its previous-version baseline from 2026-02-17.
A green PR gate describes only that PR; it does not erase existing main debt.
The enforced conditions include reliability A, security A and at least 80% new
coverage, plus duplication and hotspot review. No source exclusion, coverage
exclusion, baseline reset or reduced threshold is used to achieve a green gate.

Code fixes and individually justified issue dispositions must be reported
separately. Compare issue IDs after a fresh main scan: a finding that moves to
a helper is still a finding. Hardware and motion tests are never run by CI.
