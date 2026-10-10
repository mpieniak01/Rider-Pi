# Documentation policy

The repository contains maintained project documentation in `docs/` (English)
and `docs_pl/` (Polish): vision, architecture, interfaces, configuration,
development instructions and user guides. Update both language indexes when
adding or moving a public document.

| Material | Location | GitHub |
| --- | --- | --- |
| Project documentation and released changes | `docs/`, `docs_pl/`, root project guides | Published |
| Images and diagrams used by public guides | `docs/assets/`, `docs_pl/assets/` | Published |
| Plans, task checklists and work in progress | `_to_do/` | Local, ignored |
| Completed task notes, audits and session reports | `_done/` or `done/` | Local, ignored |
| Developer configuration and credentials | `.env`, private `.env.*`, `evn.ssh.local`, `config/local/` | Local, ignored |
| Public configuration templates | `.env.example`, `.env.*.example` | Published with placeholders |

The local directories may also exist inside either documentation tree. They
are deliberately absent from Git: do not force-add them, attach them to PRs or
include them in deployment packages. The old `archive/`, `_todo/` and
`_pr_summaries/` names are also reserved for local working material.

Before publishing a document, remove session-specific paths, host inventories,
execution logs, review conversations and task checkboxes. Keep the resulting
interface descriptions, operating instructions and architectural decisions in
the public guide. Record the date, revision and result of a particular test in
the local task record. Describe planned features as plans, without declaring
that they have been verified on hardware.

Public links must resolve to other published files, to project assets or to
stable external resources. A link to an ignored local report will not work for
someone cloning the repository. Keep one maintained source for each document;
translations can have their own names and indexes.

When retiring an already tracked operational file, preserve its local copy and
remove it from the Git index. Ignore rules alone do not untrack existing files.
Review `git diff --cached --name-status` before committing. Never use
`git add -f` for local notes or credentials.
