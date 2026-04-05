# Production Deployment Checklist

Steps required before and after each production deployment to Azure App Service.

---

## Environment

- [ ] Remove `TEST_MODE=true` from Azure App Settings (or set to `false`)
- [ ] Set `STORAGE_MODE=sharepoint` in Azure App Settings
- [ ] Confirm all required env vars are set in Azure App Settings:
  - `ANTHROPIC_API_KEY`
  - `SHAREPOINT_TENANT_ID`, `SHAREPOINT_CLIENT_ID`, `SHAREPOINT_CLIENT_SECRET`
  - `SHAREPOINT_SITE_ID`, `SHAREPOINT_DRIVE_ID`
  - `FLASK_SECRET_KEY`
  - `MSAL_CLIENT_ID`, `MSAL_CLIENT_SECRET`, `MSAL_TENANT_ID`, `MSAL_REDIRECT_URI`
  - `PEXELS_API_KEY`, `SHUTTERSTOCK_CLIENT_ID`, `SHUTTERSTOCK_CLIENT_SECRET`
  - `UNSPLASH_ACCESS_KEY`, `PIXABAY_API_KEY`
  - `CORS_ORIGINS`

---

## MCP Server (Claude Desktop)

- [ ] Update `cwd` in `claude_desktop_config.json` if project path changes
- [ ] Remove `TEST_MODE` override from MCP server env if set
- [ ] Point MCP server at production app or keep as local stdio — decide before go-live
- [ ] Update `_search_image_library` thumbnail URL in `mcp_server.py`: replace `http://localhost:5000/thumbnail` with the production hostname
- [ ] Restart Claude Desktop after any config change

---

## Auth

- [ ] Add production redirect URI to Azure AD app registration:
  `https://<production-hostname>/auth/callback`
- [ ] Verify MSAL login flow end-to-end with a liveproxima.org account
- [ ] Confirm sign-out clears session correctly

---

## Data & Storage

- [ ] Clear any test records from local JSON store (`proxima_test_store.json`)
- [ ] Verify SharePoint Assets list columns match schema in `sharepoint_list_client.py`
- [ ] Confirm `SHAREPOINT_IMAGE_FOLDER` path exists in the target drive
- [ ] Run a test upload end-to-end and verify image appears in library

---

## Edit List

- [ ] **Work through and apply all items in `EDIT_LIST.md` before final go-live**
  - Item 2: Thumbnail URL caching
  - Item 3: Increase Shutterstock modal thumbnail size
  - Item 4: Increase stock search results per library (default 12, cap 20)
  - Item 5: Hybrid metadata for stock photo downloads
  - Item 6: Image review workflow utility
- [ ] Move applied items to the Applied section in `EDIT_LIST.md`
- [ ] Archive or delete `EDIT_LIST.md` once all items are resolved

---

## Post-Deploy Checks

- [ ] Health endpoint returns 200: `GET /health`
- [ ] Library loads and images display
- [ ] Upload pipeline completes without connection errors
- [ ] Stock search returns results from all four sources
- [ ] Shutterstock quota modal fires on card click
- [ ] Download modal shows metadata and triggers file download
- [ ] MCP tools (`search_image_library`, `search_stock_photos`, `catalog_stock_image`) respond correctly in Claude Desktop
