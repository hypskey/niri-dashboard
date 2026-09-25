# NiriDashboard icon sources

Researched/downloaded 2026-09-21. Only Wikimedia Commons file pages and originals hosted under upload.wikimedia.org/wikipedia/commons/ were used. Upstream sources mentioned below are provenance recorded on Commons; no assets were fetched from those sites. Current/historical assessments are based on Commons, not an independent audit of the brands’ websites.

**Delivered: 6 of 10.** Missing: YouTube, Google Maps, Google G, Reddit. Calendar and Gmail have indirect upstream provenance; GitHub has low dark-background contrast.

## Inspection and handling

- All delivered files parse as SVG, have a positive viewBox, and contain only vector artwork. No raster images, scripts, foreignObject, text/font dependencies, external href dependencies, missing local href/paint references, or CSS imports were found. XML namespace URLs are identifiers, not downloads.
- No paths, colors, gradients, masks, filters, transforms, backgrounds, or transparency were changed. Four files are byte-identical to Commons; only root viewBox attributes were added to Chat and Calendar. Small editor metadata was retained.
- Visually inspected contact-sheet.png with proportional 96 px, 24 px, 32 px and 48 px renders on a dark background. Rendering used the local Qt SVG utility ksvgtopng; Maps and G failures were also reproduced with the project environment’s PySide6 / Qt 6.11.2 QSvgRenderer. Valid XML alone did not guarantee correct rendering.
- The PNG contact sheet is a preview only; it does not replace or rasterize the delivered SVG assets.
- Commons labels the delivered non-GitHub assets PD-textlogo. GitHub attribution/license is recorded below.

## Proton Mail

- Requested filename: `proton-mail.svg`
- Status/version: Appears current: 2022-era Proton envelope mark; Commons upload 2024-10-26.
- Commons file page: [ProtonMail icon.svg](https://commons.wikimedia.org/wiki/File:ProtonMail_icon.svg)
- Direct original (candidate if missing): [SVG](https://upload.wikimedia.org/wikipedia/commons/0/0c/ProtonMail_icon.svg)
- Selection / caveat: Commons credits Proton Mail and points to its official full-logo SVG. Chosen standalone mark avoids the horizontal wordmark. No newer standalone SVG was found.
- Local changes: None; byte-identical download.

- Local SHA-256: `ad7be3dc146d42c3997c6fa68a52aa4b8228b51284693925408c073fb1c9ab03`

## WhatsApp

- Requested filename: `whatsapp.svg`
- Status/version: Appears current. Source date 2022-05-24; Commons upload 2025-02-28.
- Commons file page: [WhatsApp Logo green.svg](https://commons.wikimedia.org/wiki/File:WhatsApp_Logo_green.svg)
- Direct original (candidate if missing): [SVG](https://upload.wikimedia.org/wikipedia/commons/4/4c/WhatsApp_Logo_green.svg)
- Selection / caveat: Commons credits WhatsApp and cites Meta’s official brand resources. Flat green outline mark, transparent interior. Preferred over WhatsApp.svg: that alternative has a shadow and a dangling internal gradient reference. Horizontal and vertical wordmarks were rejected.
- Local changes: None; byte-identical download.

- Local SHA-256: `afce9b3329a85b462e0b4020e9aa81ae5154f84b64a3653ddf530e0f943511bb`

## YouTube

- Requested filename: `youtube.svg`
- Status/version: MISSING. Candidate depicts the current 2024/2025 pink-red mark; uploaded 2024-10-18.
- Commons file page: [YouTube full-color icon (2024).svg](https://commons.wikimedia.org/wiki/File:YouTube_full-color_icon_(2024).svg)
- Direct original (candidate if missing): [SVG](https://upload.wikimedia.org/wikipedia/commons/f/fd/YouTube_full-color_icon_%282024%29.svg)
- Selection / caveat: The page explicitly credits the vector to Logopedia and the design to Google, so it does not establish an official original SVG. Current circle/squircle variants derive from the same Logopedia-sourced logo. The 2017 full-color file has an “official version” revision dated 2024-01-07, but is an older design. Neither was substituted.
- Local changes: No output file.

## Google Chat

- Requested filename: `google-chat.svg`
- Status/version: Appears current: design dated 2026-05-19; uploaded 2026-05-20.
- Commons file page: [Google Chat Logo 05.2026.svg](https://commons.wikimedia.org/wiki/File:Google_Chat_Logo_05.2026.svg)
- Direct original (candidate if missing): [SVG](https://upload.wikimedia.org/wikipedia/commons/2/2d/Google_Chat_Logo_05.2026.svg)
- Selection / caveat: Commons credits Google and its Workspace Chat product page. Compact green speech-bubble mark. The 2023 multicolor icon is superseded, as is the 2020 icon.
- Local changes: Added only viewBox="0 0 192 192" to the root SVG, matching original dimensions.

- Local SHA-256: `9354abd5fc140e332bcdd0c563827f0bb24cf3db4b28f7a1a3ae28635f77c7d3`

## Google Calendar

- Requested filename: `google-calendar.svg`
- Status/version: Appears current: page identifies the redesign of 2026-05-19; file dated/uploaded 2026-05-20.
- Commons file page: [Google Calendar icon (2026).svg](https://commons.wikimedia.org/wiki/File:Google_Calendar_icon_(2026).svg)
- Direct original (candidate if missing): [SVG](https://upload.wikimedia.org/wikipedia/commons/f/fa/Google_Calendar_icon_%282026%29.svg)
- Selection / caveat: Commons identifies Google as author and the current Calendar mark. Provenance caveat: its upstream source is a Logopedia SVG, not a direct Google URL; official-original byte provenance is not independently established. Unlike the rejected YouTube file, it does not credit a third-party vectorizer. The 2020 multicolor mark is historical. “31” is part of the icon artwork.
- Local changes: Added only viewBox="0 0 800 859.0954" to the root SVG, matching original dimensions.

- Local SHA-256: `7dc297a0c4802a91b163624f620751737e7881f0f0eefcdcbb886d566936c6bd`

## Google Maps

- Requested filename: `google-maps.svg`
- Status/version: MISSING. Current candidate dated 2026; uploaded 2026-03-04.
- Commons file page: [Google Maps icon (2026).svg](https://commons.wikimedia.org/wiki/File:Google_Maps_icon_(2026).svg)
- Direct original (candidate if missing): [SVG](https://upload.wikimedia.org/wikipedia/commons/a/a3/Google_Maps_icon_%282026%29.svg)
- Selection / caveat: Commons credits Google and Google Maps developer documentation. The 4,303,143-byte original embeds 19 PNG images under a vector clipping path; these are artwork, not removable metadata. Both local Qt SVG rendering checks lost the pin clipping and displayed a gradient rectangle. Cannot deliver a clean Qt dashboard icon without changing internal artwork. The 2020 flat pin is historical and was not substituted.
- Local changes: Candidate downloaded and inspected, then excluded; no output file.

## Google Search / Google G

- Requested filename: `google.svg`
- Status/version: MISSING. Current gradient design introduced 2025-05-12; latest file revision 2025-10-15 04:23 UTC.
- Commons file page: [Google Favicon 2025.svg](https://commons.wikimedia.org/wiki/File:Google_Favicon_2025.svg)
- Direct original (candidate if missing): [SVG](https://upload.wikimedia.org/wikipedia/commons/3/3c/Google_Favicon_2025.svg)
- Selection / caveat: The latest Commons original is explicitly a contributor vectorization. An earlier revision uploaded 2025-10-15 04:21 UTC cites Google Search directly, but uses foreignObject plus a CSS conic gradient and renders as only a blue bar in Qt. Repair would require internal artwork changes. The 2015 flat G is historical.
- Local changes: Archived candidate inspected and excluded; no output file.

- Google-sourced archived candidate: [2025-10-15 04:21 UTC original](https://upload.wikimedia.org/wikipedia/commons/archive/3/3c/20251015042302%21Google_Favicon_2025.svg). The archive filename reflects replacement time; Commons history gives its upload time.

## GitHub

- Requested filename: `github.svg`
- Status/version: Appears current: design dated 2021-02-08; uploaded 2023-04-17.
- Commons file page: [GitHub Invertocat Logo.svg](https://commons.wikimedia.org/wiki/File:GitHub_Invertocat_Logo.svg)
- Direct original (candidate if missing): [SVG](https://upload.wikimedia.org/wikipedia/commons/c/c2/GitHub_Invertocat_Logo.svg)
- Selection / caveat: Commons credits GitHub and its official logos page. Selected standalone black Invertocat. Recognizable at small sizes but low contrast on dark surfaces; no recoloring or background added. The Commons invert variant (2025-12-28) is described as a contributor modification, so the directly sourced original was preferred.
- Local changes: None; byte-identical download. Attribution: GitHub, licensed under CC BY 4.0: https://creativecommons.org/licenses/by/4.0/ (per Commons file page).

- Local SHA-256: `5d21755d08ca9818d969dc8aa51ffa7b4bb469c32e8ccff331dfd622cbe6dd95`

## Reddit

- Requested filename: `reddit.svg`
- Status/version: MISSING. Examined icon is historical, dated/uploaded 2021-02-10.
- Commons file page: [Snoo.svg](https://commons.wikimedia.org/wiki/File:Snoo.svg)
- Direct original (candidate if missing): [SVG](https://upload.wikimedia.org/wikipedia/commons/a/aa/Snoo.svg)
- Selection / caveat: No confidently current standalone official SVG was found in the Commons Reddit logo category. Snoo.svg is an older flat icon. Reddit wordmark.svg is the 2023 wordmark, not the requested compact mascot mark. No wordmark or historical icon was substituted.
- Local changes: No output file.

- Alternatives: [2023 wordmark](https://commons.wikimedia.org/wiki/File:Reddit_wordmark.svg), [Reddit logo category](https://commons.wikimedia.org/wiki/Category:Logos_of_Reddit).

## Gmail

- Requested filename: `gmail.svg`
- Status/version: Appears current: page dates redesign to 2026-05-19; uploaded 2026-05-20.
- Commons file page: [Gmail icon (2026).svg](https://commons.wikimedia.org/wiki/File:Gmail_icon_(2026).svg)
- Direct original (candidate if missing): [SVG](https://upload.wikimedia.org/wikipedia/commons/8/8f/Gmail_icon_%282026%29.svg)
- Selection / caveat: Commons identifies Google as author and this as the current Gmail icon. Provenance caveat: upstream source is a Logopedia SVG, not a direct Google URL; official-original byte provenance is not independently established. No third-party vectorizer is credited. The 2020 multicolor mark is historical. Gmail Logo 05.2026.svg redirects to this asset.
- Local changes: None; byte-identical download.

- Local SHA-256: `8b2b295300d7dec8aa066cd6d9e5ae72f6a90aec565308ff5d44c6915257b184`
