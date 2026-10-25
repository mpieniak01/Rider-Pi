# Documentation policy

Maintain two current versions of project documentation: `docs_pl/` (Polish)
and `docs/` (English). Polish is the starting point; update contracts,
configuration and instructions in English in the same commit.
Both language indexes link only to maintained documents and their assets.

| Material | Location | GitHub |
| --- | --- | --- |
| Vision, architecture, contracts, guides and releases | `docs_pl/`, `docs/`, root guides | Published |
| Images and diagrams used by guides | `docs/assets/`, or `docs_pl/assets/` when needed | Published |
| Plans and work in progress | `docs_pl/_to_do/` | Local, ignored |
| Completed tasks, audits and session reports | `docs_pl/_done/` | Local, ignored |
| Developer settings and credentials | `.env`, private `.env.*`, `evn.ssh.local`, `config/local/` | Local, ignored |
| Configuration templates without secrets | `.env.example`, `.env.*.example` | Published |

Operational directories exist only in `docs_pl/`. Do not create copies
in `docs/` or separate `done` directories. Remove empty directories after
consolidation. Historical material can remain under `_done/`; label different
versions and avoid keeping identical copies.

Publish the result of the work: an interface description, procedure or design
decision. Logs, checklists, host inventory and individual execution results
stay local. Never force-add them, attach them to PRs or include them in
deployment packages. Public links must not point to local plans or reports.
Describe planned features as planned.

Before committing, check `git diff --cached --name-status` and
`git diff --cached --check`. Ignore rules do not remove already tracked files;
untrack operational material while preserving its local copy.


## Checking freshness

Current route registration, validators and configuration descriptors define
the contract, rather than a document's edit date or a historical release label.
Check link targets, heading anchors, index reachability and source agreement
separately. An existing link does not establish correctness.

When a parameter changes, update both languages and duplicated limits in
the contract, application guide and UI description. Initial default, supported
range and a device's saved setting are separate facts. State profile revisions;
distinguish API envelopes, payload schemas and data revisions.

Translated filenames may differ (for example BRAMKA_JAKOSCI/QUALITY_GATE,
WDROZENIE/DEPLOYMENT). English PROJECT/ARCHITECTURE/WORKING-AGREEMENTS guides
live at the repository root; their Polish counterparts are under docs_pl.
New standalone topics need counterparts and links in both indexes.
Label old-tag descriptions as historical; a deployment plan or a single
device's recorded settings must not appear as current project instructions.
