# agentic-replenishment-app (Probot)

This repository contains a Probot-based GitHub App scaffold for Agentic Replenishment.

## Quick start (local)

1. Install deps:
   npm install

2. Create a GitHub App using the included `manifest.yml`:
   - Go to GitHub -> Settings -> Developer settings -> GitHub Apps -> Create a GitHub App from a manifest
   - Paste the contents of manifest.yml, set the webhook URL later (use ngrok for local testing)
   - After creating the App, download the private key and note the App ID

3. Configure environment variables locally:
   - APP_ID or APP_ID (set `APP_ID` as the numeric id)
   - PRIVATE_KEY — the PEM private key as a multi-line string (keep newlines)
   - WEBHOOK_SECRET — a random string you set when creating the App

   Example (bash):
   export APP_ID=12345
   export PRIVATE_KEY="$(cat ./private-key.pem)"
   export WEBHOOK_SECRET="some-secret"

4. Run locally with ngrok:
   - ngrok http 3000
   - Update your App's webhook URL to the ngrok `https://xxxx.ngrok.io` + `/` (example `https://xxxx.ngrok.io/`)
   - Start the app:
     npm start

5. Install the App on your repo:
   - On the App page in GitHub, go to Install App -> Install on Repositories -> choose `Jaz-Lab8/Agentic-Replenishment`

## Replacing PAT/GITHUB_TOKEN usage
- This App will perform actions as the installation (installation tokens).
- Common places to replace:
  - Scripts that do `Authorization: token $PAT` → generate an installation token and use that token.
  - Workflows that need App-level access: either call a server which uses the App, or in Actions generate an installation token using the private key and `@octokit/auth-app` (store PRIVATE_KEY, APP_ID, and installationId as secrets).

Example: generate installation token (Node)
```js
const { createAppAuth } = require('@octokit/auth-app');
const { Octokit } = require('@octokit/rest');

async function getInstallationOctokit(appId, privateKey, installationId) {
  const auth = createAppAuth({ appId, privateKey });
  const installationAuth = await auth({ type: 'installation', installationId });
  return new Octokit({ auth: installationAuth.token });
}