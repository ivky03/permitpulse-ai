# Stage 6: durable portfolio release

## Completed behavior

- Binary filing inputs are normalized to the training representation, fixing false
  `Yes` versus `YES` unseen-category warnings.
- LangGraph checkpoints persist in `artifacts/permitpulse_state.sqlite`.
- A paused approval can resume after FastAPI restarts when its thread ID is reused.
- Demo workspace IDs group assessment history and are explicitly not authentication.
- The Streamlit sidebar lists and reopens earlier assessments.
- Approval freezes the displayed risk, inputs, comparable evidence, local sensitivity,
  checklist, warnings, model context, and reviewer note into a PDF.
- Rejection persists the reviewer decision and generates no PDF.
- PDF bytes stay outside LangGraph checkpoints. The checkpoint stores only filename,
  SHA-256, size, and status metadata.
- The download endpoint verifies workspace ownership before returning a report.
- Repeated generation for the same thread returns the existing immutable report.

## Verification

- 26 unit and integration tests pass.
- Tests cover restart-resume, approval generation, PDF text/context, idempotent output,
  rejection without output, workspace isolation, API download, and artifact install.
- A real-model assessment returned 82.5% risk, survived a workflow restart, generated
  a valid PDF after approval, and denied the same download to another workspace.
- The report is rendered to PNG and visually inspected for spacing, tables, headers,
  footers, page numbering, and readable multi-page layout.

## Persistence boundary

SQLite and local report storage are appropriate for this local, single-instance
portfolio application. A volume must be mounted when Docker is used. A public
multi-instance deployment needs real authentication, object storage, and a shared
database/checkpointer such as Postgres.

Workspace IDs only separate demo records. Anyone who knows an ID could request its
history, so the application must not collect private project or personal data in this
mode.

## Human-review boundary

Approval means only that the reviewer accepts the displayed planning assessment for
PDF generation. It does not mean that NYC DOB approved a permit, and it never sends a
message, submits a filing, or changes a project schedule. Rejection creates no report.

## Public-repository artifact handoff

Generated runtime artifacts remain outside Git history. The owner can create a
verified release bundle:

```bash
python scripts/manage_demo_artifacts.py build permitpulse-demo-artifacts.tar.gz
```

Upload that archive to a GitHub Release. Reviewers install it with:

```bash
python scripts/manage_demo_artifacts.py install permitpulse-demo-artifacts.tar.gz
```

The installer allows only the three expected runtime files and verifies every SHA-256
hash before writing them.
