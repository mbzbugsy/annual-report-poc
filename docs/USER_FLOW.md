# User Flow

## Goal

Enable non-developers to update the annual report using AI while preserving the report's visual identity and ensuring version control.

---

## Option A - Developer Workflow (Current PoC)

Economy

↓

VS Code

↓

GitHub Copilot

↓

Git

↓

GitHub Actions

↓

PDF Artifact

### Pros

- Very little implementation required.
- Full version history.
- Developers already know the workflow.

### Cons

- Requires Git knowledge.
- Requires VS Code.
- Not ideal for non-technical users.

---

## Option B - End User Workflow (Future Vision)

Economy

↓

Upload Excel files

↓

Write prompt

↓

Preview changes

↓

Generate PDF

↓

Download PDF

### Pros

- No Git knowledge required.
- No IDE required.
- Very easy for end users.

### Cons

- Requires a web application.
- More development effort.
- Still needs Git/LaTeX behind the scenes.