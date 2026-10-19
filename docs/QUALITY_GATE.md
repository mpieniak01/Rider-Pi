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
