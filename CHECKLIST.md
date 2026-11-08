# Submission checklist

Source: https://x.com/NousResearch/status/2118094256438936062 and
https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/catalog-submission

## Plugin (Claude)
- [x] `hermes plugins validate` passes, no warnings
- [x] `requires_hermes: ">=0.23.0"`
- [x] Background thread, local processes and network use disclosed (rule 13)
- [x] No core override, no private imports (rule 9)
- [x] State only in `plugin-data/brownout/`
- [x] Fails cleanly with no power reading / no messaging configured
- [x] Commands work from Telegram via gateway (run 3, Nov 8)
- [x] Every README claim proven in CLAIMS.md (run 4: live agent turn blocked)
- [ ] CI green
- [ ] Catalog YAML with 40-char SHA pin

## Sam only
- [ ] Ask eligibility in the Nous Discord
- [x] Provide a model for the agent demo (Bedrock Nova 2 Lite, Gemini fallback)
- [ ] Approve and make commits; make repo public
- [ ] Open catalog PR
- [ ] Record video (< 90 s), post on X tagging @NousResearch
- [ ] Fill the Typeform: https://form.typeform.com/to/FwJLvOln (fields: [FILL])
- [ ] `/revoke` the test bot token in BotFather
- [ ] Tag `main` at submission and freeze
