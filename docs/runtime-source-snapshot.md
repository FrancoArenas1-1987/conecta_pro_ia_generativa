Runtime source snapshot captured 2026-11-12.

This branch preserves the source variant present in the deployed container. The inventory lists SHA-256 hashes after normalizing CRLF and removing a UTF-8 BOM. The only source difference from the development copy at backup time was scripts/deploy_prod.sh. Additional local rendering helpers on the parent branch are not present in the runtime inventory.

This is an archival branch, not a deployment instruction. It does not contain environment variables, credentials, logs, media files or mutable publication state. Do not invoke archived deployment scripts without reviewing the current deployment procedure and image-generation policy.
