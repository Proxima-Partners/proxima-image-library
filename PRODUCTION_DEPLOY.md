# Production Deployment Checklist

Steps required before and after each production deployment to Azure App Service.

---

## Environment

- [ ] Set `TEST_MODE=false`
- [ ] Set `STORAGE_MODE=sharepoint`
- [ ] Set `DEV_AUTH_BYPASS=false` (required: runtime validation blocks bypass outside TEST_MODE)
- [ ] Set `MAINTENANCE_ADMIN_USERS` with one or more allowed admin identities (email/UPN)
- [ ] Confirm required env vars are set in Azure App Settings:
  - `ANTHROPIC_API_KEY`
  - `SHAREPOINT_TENANT_ID`, `SHAREPOINT_CLIENT_ID`, `SHAREPOINT_CLIENT_SECRET`
  - `SHAREPOINT_SITE_ID`, `SHAREPOINT_DRIVE_ID`
  - `FLASK_SECRET_KEY`
  - `MSAL_CLIENT_ID`, `MSAL_CLIENT_SECRET`, `MSAL_TENANT_ID`, `MSAL_REDIRECT_URI`
  - `CORS_ORIGINS`
- [ ] Confirm recommended SharePoint settings are explicit:
  - `SHAREPOINT_LIST_NAME` (default `Assets`)
  - `SHAREPOINT_IMAGE_FOLDER` (default `Images`)
- [ ] If stock search is required in production, also set:
  - `PEXELS_API_KEY`, `SHUTTERSTOCK_CLIENT_ID`, `SHUTTERSTOCK_CLIENT_SECRET`
  - `UNSPLASH_ACCESS_KEY`, `PIXABAY_API_KEY`

---

## MCP Server (Claude Desktop)

- [ ] Update `cwd` in `claude_desktop_config.json` if project path changes
- [ ] Remove `TEST_MODE` override from MCP server env if set
- [ ] Point MCP server at production app or keep as local stdio — decide before go-live
- [ ] If using production-hosted image previews from Claude Desktop, update all hardcoded localhost URLs in `src/mcp_server.py` (`/thumbnail` and `/image` references)
- [ ] Restart Claude Desktop after any config change

---

## Auth

- [ ] Add production redirect URI to Azure AD app registration:
  `https://<production-hostname>/auth/callback`
- [ ] Verify MSAL login flow end-to-end with a liveproxima.org account
- [ ] Confirm sign-out clears session correctly
- [ ] Verify maintenance access control:
  - Allowlisted user can access `/maintenance` and `/api/maintenance/*`
  - Non-allowlisted authenticated user receives `403`

---

## Data & Storage

- [ ] Clear any test records from local JSON store (`test_data/local_table.json`) before packaging/releasing data snapshots
- [ ] Verify SharePoint Assets list columns match schema in `sharepoint_list_client.py`
- [ ] Confirm `SHAREPOINT_IMAGE_FOLDER` path exists in the target drive
- [ ] Run a test upload end-to-end and verify image appears in library
- [ ] Run one stock "Add to Library" flow and verify:
  - High-Res file lands under `High-Res/{source}/...`
  - WebP file lands under `WebP/{category}/...`
  - Metadata record includes `Source`, `Location`, and `High-Res Location`

---

## Edit List

- [ ] Review `EDIT_LIST.md` and confirm there are no unresolved go-live blockers
- [ ] Keep `EDIT_LIST.md` as a living change log; do not delete it as part of deployment

---

## Post-Deploy Checks

- [ ] Health endpoints return 200: `GET /health` and `GET /healthz`
- [ ] Library loads and images display
- [ ] Upload pipeline completes without connection errors
- [ ] Review queue loads and status changes persist
- [ ] Maintenance page loads for admin accounts and is blocked for non-admin accounts
- [ ] Stock search returns results from configured sources
- [ ] Shutterstock quota modal fires on card click
- [ ] Download modal shows metadata and triggers file download
- [ ] MCP tools (`search_image_library`, `search_stock_photos`, `catalog_stock_image`, `catalog_image_from_file`) respond correctly in Claude Desktop
