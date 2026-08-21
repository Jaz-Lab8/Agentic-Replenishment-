// Probot entry
const { Probot } = require('probot');
const app = require('./lib/app');

const probot = new Probot({
  appId: process.env.APP_ID,
  privateKey: process.env.PRIVATE_KEY, // the PEM private key, include newlines
  secret: process.env.WEBHOOK_SECRET,
  // optional: set Octokit options
});

probot.load(app);

probot.start().catch((err) => {
  console.error('Failed to start Probot:', err);
  process.exit(1);
});