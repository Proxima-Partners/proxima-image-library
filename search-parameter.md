# Search Parameters

Defines the search parameters accepted by each stock photo API integrated in the Proxima Image Library. The current implementation searches Pexels, Shutterstock, and Unsplash concurrently using phrase-based keyword queries.

## How the Search Works

1. User provides a skill output file (Markdown or plain text) or types phrases directly
2. App extracts photo suggestion phrases from the `Photo Suggestion` section of the content (1–7 words per phrase, up to 20 phrases)
3. All phrases are submitted concurrently to all three APIs (up to 12 parallel requests)
4. Results are returned grouped by phrase, with each API shown in a separate tab
5. User opens preferred image in the source platform to license and download

The search is phrase-only: no filters, orientation, or color options are currently exposed to the user. Those parameters are documented below as available for future enhancement.

## Environment Variables

| Variable | API | Required |
| -------- | --- | -------- |
| `PEXELS_API_KEY` | Pexels | Yes |
| `SHUTTERSTOCK_CLIENT_ID` | Shutterstock | Yes |
| `SHUTTERSTOCK_CLIENT_SECRET` | Shutterstock | Yes |
| `UNSPLASH_ACCESS_KEY` | Unsplash | Yes |

If a variable is missing, that API is skipped and the tab shows "not configured" rather than erroring.

---

## Pexels

**Endpoint:** `GET https://api.pexels.com/v1/search`

**Authentication:** API key passed as `Authorization` header (no prefix)

**API docs:** https://www.pexels.com/api/documentation/

### Parameters in use

| Parameter | Type | Value | Description |
| --------- | ---- | ----- | ----------- |
| `query` | string | phrase | Keyword search string |
| `per_page` | integer | 1–12 (default 8) | Number of results to return |

### Additional parameters available

| Parameter | Type | Options | Description |
| --------- | ---- | ------- | ----------- |
| `orientation` | string | `landscape`, `portrait`, `square` | Filter by image orientation |
| `size` | string | `large`, `medium`, `small` | Filter by minimum image size |
| `color` | string | hex code or named color | Filter results by dominant color |
| `locale` | string | e.g. `en-US` | Return results localized to language |
| `page` | integer | default 1 | Pagination |

### Response fields used

| Field | Description |
| ----- | ----------- |
| `photos[].alt` | Image description (used as title) |
| `photos[].url` | Link to image on Pexels.com |
| `photos[].src.medium` | Thumbnail URL for preview grid |

### Notes

- Free to use with attribution to Pexels (link back to source required)
- `src` object also contains: `original`, `large2x`, `large`, `small`, `portrait`, `landscape`, `tiny`

---

## Shutterstock

**Endpoint:** `GET https://api.shutterstock.com/v2/images/search`

**Authentication:** HTTP Basic Auth using `{CLIENT_ID}:{CLIENT_SECRET}` encoded as Base64

**API docs:** https://api-reference.shutterstock.com/

### Parameters in use

| Parameter | Type | Value | Description |
| --------- | ---- | ----- | ----------- |
| `query` | string | phrase | Keyword search string |
| `per_page` | integer | 1–12 (default 8) | Number of results to return |
| `image_type` | string | `photo` | Hardcoded to photos only (excludes vectors and illustrations) |
| `fields` | string | `id,description,assets` | Limits response payload to required fields |

### Additional parameters available

| Parameter | Type | Options | Description |
| --------- | ---- | ------- | ----------- |
| `orientation` | string | `horizontal`, `vertical` | Filter by image orientation |
| `category` | string | e.g. `business`, `nature` | Filter by Shutterstock category |
| `color` | string | hex code | Filter by dominant color |
| `safe` | boolean | `true` / `false` | Safe search filter |
| `people_number` | integer | 0, 1, 2, 3, 4 | Number of people in the image |
| `people_age` | string | `infants`, `children`, `teenagers`, `20s`, `30s`, `40s`, `50s`, `60s`, `older` | Filter by apparent age of people |
| `people_gender` | string | `male`, `female`, `both` | Filter by gender of people shown |
| `people_ethnicity` | string | `african_american`, `black`, `brazilian`, `chinese`, `caucasian`, `hispanic`, `japanese`, `middle_eastern`, `native_american`, `pacific_islander`, `south_asian`, `southeast_asian`, `other`, `multiethnic` | Filter by ethnicity (use with care) |
| `page` | integer | default 1 | Pagination |

### Response fields used

| Field | Description |
| ----- | ----------- |
| `data[].id` | Image ID (used to construct Shutterstock link) |
| `data[].description` | Image description (used as title) |
| `data[].assets.large_thumb.url` | Thumbnail URL (preferred) |
| `data[].assets.preview.url` | Thumbnail URL (fallback) |

### Notes

- Shutterstock requires a paid subscription or license to download images
- The `image_type` parameter can also be `vector` or `illustration` if those content types are needed in future

---

## Unsplash

**Endpoint:** `GET https://api.unsplash.com/search/photos`

**Authentication:** API key passed as `Authorization: Client-ID {key}` header

**API docs:** https://unsplash.com/documentation

### Parameters in use

| Parameter | Type | Value | Description |
| --------- | ---- | ----- | ----------- |
| `query` | string | phrase | Keyword search string |
| `per_page` | integer | 1–12 (default 8) | Number of results to return |

### Additional parameters available

| Parameter | Type | Options | Description |
| --------- | ---- | ------- | ----------- |
| `orientation` | string | `landscape`, `portrait`, `squarish` | Filter by image orientation |
| `color` | string | `black_and_white`, `black`, `white`, `yellow`, `orange`, `red`, `purple`, `magenta`, `green`, `teal`, `blue` | Filter by dominant color |
| `content_filter` | string | `low` (default), `high` | Stricter content filtering when set to `high` |
| `order_by` | string | `relevant` (default), `latest` | Sort order |
| `page` | integer | default 1 | Pagination |

### Response fields used

| Field | Description |
| ----- | ----------- |
| `results[].alt_description` | Primary image description |
| `results[].description` | Fallback description |
| `results[].urls.small` | Thumbnail URL for preview grid |
| `results[].links.html` | Link to photo on Unsplash |
| `results[].user.name` | Photographer name (required for attribution) |
| `results[].user.links.html` | Photographer profile URL (required for attribution) |

### Attribution requirement

Unsplash requires attribution on every photo. The app appends UTM parameters to all Unsplash links and displays the photographer credit below each thumbnail:

```
Photo by {photographer_name} on Unsplash
```

Both the photographer name and the Unsplash logo/name must link back with UTM parameters:
- Photo link: `?utm_source=proxima_image_library&utm_medium=referral`
- Profile link: `?utm_source=proxima_image_library&utm_medium=referral`

This is enforced in `templates/stock_search.html` and must be preserved in any UI changes.

---

## Phrase Extraction Rules

Phrases are extracted from skill output content by `parse_photo_suggestions()` in [src/stock_client.py](src/stock_client.py).

| Rule | Value |
| ---- | ----- |
| Source section | `Photo Suggestion` heading in Markdown |
| Fallback | One phrase per line if no section found |
| Min words | 1 |
| Max words | 7 |
| Max phrases | 20 |
| Excluded terms | `suggestion`, `adobe`, `shutterstock`, `unsplash`, `search phrase`, `per the` |

## Global Limits

| Constraint | Value |
| ---------- | ----- |
| Results per API per phrase | 1–12 (UI default: 8) |
| Max phrases per search | 20 |
| Max concurrent API requests | 12 |
| Per-request timeout | 10 seconds |
| Total search timeout | 25 seconds |
