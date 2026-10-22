# AI Studio — Visual Commerce Workspace

An interactive workspace for preparing product images, arranging editable layers, and exporting commerce-ready layouts.

## Project status

- The prototype includes project management, a canvas editor, local U2Net background removal, draft recovery, task status, and multi-size export.
- Background image generation currently uses a remote API provider. Prompts sent to that feature leave the device.
- The target product design is fully local inference with no cloud fallback. Local text-to-image generation is not implemented or tested; the current prototype does not meet that target.
- No model weights or credentials are included in this repository.

## Run locally

### Frontend

```bash
cd frontend
npm ci
npm run build
```

### Backend

Use Python 3.12 or newer. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example backend/.env
cd backend
python -m uvicorn app.main:app --app-dir . --host 127.0.0.1 --port 8001
```

Open <http://127.0.0.1:8001/>. Runtime data is created locally under `backend/data/` and is excluded from version control.

The requirements include machine-learning runtime libraries. Installing Python packages does not download the large image-generation model weights; those weights are not part of this repository.

## Configuration and privacy

- `.env.example` contains blank credential fields. Put any API credential only in the local ignored `backend/.env`; never commit it or paste it into an issue, screenshot, or prompt.
- The current remote image-generation feature may incur provider charges. Do not use it until the account, price, and authorization have been checked.
- Product images and project data are stored locally by the prototype. Text-to-image prompts are sent to the configured remote provider.
- This is a local demo, not a production service. It does not provide real user authentication or multi-user data isolation.

## Verification

Backend tests:

```bash
cd backend
python -m pytest tests -q
```

Frontend checks:

```bash
cd frontend
npm run lint
npm run build
```

The accompanying reports distinguish automated checks, browser observations, and model tests. The local U2Net evidence covers one sample only; local image generation has not been tested.

## Product notes

- [Product solution](docs/需求与解决方案.md)
- [Interaction guide](docs/交互说明.md)
- [Test and model evaluation report](docs/测试报告.md)
- [Task scheduling design](docs/任务调度方案.md)
