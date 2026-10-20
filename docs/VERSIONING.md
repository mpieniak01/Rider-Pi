# Versioning and releases

## Project version

[VERSION](../VERSION) contains the project version as `MAJOR.MINOR.PATCH`.
Release 1.0 uses `1.0.0`, tag `v1.0.0` and release notes in both languages:
[EN](release-notes/v1.0.0.md), [PL](../docs_pl/release-notes/v1.0.0.md).
The English and Polish READMEs carry the same version. For the next release,
update VERSION, both READMEs and both release notes in one PR.

- PATCH: compatible bug fixes and documentation corrections.
- MINOR: new features preserving public contracts.
- MAJOR: changes requiring migration of existing clients or configuration.

The project version is separate from vendor SDK, firmware and HTTP/BUS contract
versions. `/api/status/version` continues to report branch, SHA and checkout
cleanliness; it does not supply the semantic version. Historical tags, including
`R-1.1.7`, remain unchanged. The `v1.0.0` line introduces the shared convention
for subsequent project releases.

## Prepare a release

1. Open a PR updating VERSION, both READMEs and release notes. Preserve Python
   3.9 and the change scope described in [development](development.md).
2. Check the current SHA: Tests, Quality Guard, Sonar and available external
   checks. Address substantive review findings. Branch protection determines
   required checks; an absent optional review is not a failed check.
3. Merge without bypassing protection, fast-forward a clean local `main` and
   check its push workflows for the integration SHA. Wait for Sonar's report
   of the same revision. Do not run a concurrent local scanner.
4. Create an annotated tag on the verified SHA and publish only that tag:

```sh
git switch main
git pull --ff-only origin main
# Checks and the main report must already match this SHA.
version=$(cat VERSION)
sha=$(git rev-parse HEAD)
git tag -a "v$version" "$sha" -m "Rider-Pi $version"
git push origin "refs/tags/v$version"
```

5. In GitHub Releases, select the existing tag, title it `Rider-Pi <version>`
   and use `docs/release-notes/` for the description. Publish a regular release
   after checks finish. GitHub source archives exclude ignored secrets and reports.

Do not move published tags or force-push them. A release correction receives
a new version and tag. Neither the tag nor VERSION changes Sonar configuration
or the new-code baseline. Publishing a GitHub release does not deploy the robot;
[deployment](DEPLOYMENT.md) is a separate step.
